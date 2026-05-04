from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import BrowserContext, Frame, Locator, Page, Playwright, Response, TimeoutError, sync_playwright

from viewer.local_page_builder import build_local_page


USER_DATA_DIR = Path("./data/browser_profile")
SAVED_POSTS_DIR = Path("./saved_posts")
DEBUG_DIR = SAVED_POSTS_DIR / "_debug"
SESSION_STATE_PATH = Path("./data/auth/naver_state.json")
MAX_FOLDER_NAME_LENGTH = 80
INVALID_FILENAME_CHARS = r'[\\/:*?"<>|]'

TITLE_SELECTORS: Sequence[str] = (
    ".ArticleTitle .title_text",
    ".article_header .title",
    ".tit-box span.b",
    ".title_area .title_text",
    ".title_text",
    "h3.title",
    "h3",
    "title",
)

BODY_SELECTORS: Sequence[str] = (
    ".se-main-container",
    ".ContentRenderer",
    ".article_viewer",
    "#tbody",
    ".NHN_Writeform_Main",
    ".view_content",
    ".article_container",
    ".article_view",
    ".ArticleContentBox",
    "article",
)

ACCESS_KEYWORDS: Sequence[str] = (
    "로그인",
    "접근 권한",
    "권한이 없습니다",
    "카페 가입",
    "멤버만",
    "비공개",
    "게시판 권한",
    "열람 권한",
)

ProgressCallback = Callable[[str], None]
ExistingFolderCallback = Callable[[Path, str], bool]
TargetPage = Page | Frame
SESSION_EXPIRED_MESSAGE = "네이버 로그인 세션이 만료되었거나 카페 접근 권한 확인이 필요합니다. [네이버 로그인 세션 연결]을 다시 실행해주세요."


@dataclass
class ParsedCafeUrl:
    original_url: str
    normalized_url: str
    cafe_name: Optional[str]
    club_id: Optional[str]
    article_id: Optional[str]


@dataclass
class FrameTarget:
    target: TargetPage
    used_iframe: bool
    iframe_name: Optional[str]
    iframe_url: Optional[str]


@dataclass
class ImageInfo:
    url: str
    replacement_values: list[str]


@dataclass
class ExtractionResult:
    title: str
    body_text: str
    body_html: str
    image_infos: list[ImageInfo]
    final_url: str
    used_iframe: bool
    iframe_name: Optional[str]
    iframe_url: Optional[str]
    access_status: str
    title_selector: str
    body_selector: str


class AccessRequiredError(RuntimeError):
    pass


class DownloadCancelledError(RuntimeError):
    pass


def emit(progress: Optional[ProgressCallback], message: str) -> None:
    if progress:
        progress(message)


def first_query_value(query: dict[str, list[str]], *keys: str) -> Optional[str]:
    for key in keys:
        values = query.get(key)
        if values:
            return values[0]
    return None


def parse_naver_cafe_url(url: str) -> ParsedCafeUrl:
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    query = parse_qs(parsed.query)

    cafe_name: Optional[str] = None
    club_id = first_query_value(query, "clubid", "clubId")
    article_id = first_query_value(query, "articleid", "articleId")

    path_parts = [part for part in parsed.path.split("/") if part]
    host = parsed.netloc.lower()

    if host in {"cafe.naver.com", "m.cafe.naver.com"}:
        if len(path_parts) >= 2 and path_parts[0].lower() not in {"articleread.nhn", "ca-fe"}:
            cafe_name = path_parts[0]
            if article_id is None and path_parts[1].isdigit():
                article_id = path_parts[1]

        if "cafes" in path_parts and "articles" in path_parts:
            try:
                club_id = club_id or path_parts[path_parts.index("cafes") + 1]
                article_id = article_id or path_parts[path_parts.index("articles") + 1]
            except IndexError:
                pass

    normalized_url = parsed.geturl() if parsed.scheme and parsed.netloc else cleaned
    return ParsedCafeUrl(
        original_url=cleaned,
        normalized_url=normalized_url,
        cafe_name=cafe_name,
        club_id=club_id,
        article_id=article_id,
    )


def create_browser_context(playwright: Playwright, *, headless: bool) -> BrowserContext:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Keep the app isolated from the user's normal Chrome profile while still
    # allowing Naver cookies to survive app restarts.
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(USER_DATA_DIR),
        headless=headless,
        viewport={"width": 1440, "height": 960},
    )


def has_naver_login_cookie(context: BrowserContext) -> bool:
    try:
        cookies = context.cookies(["https://www.naver.com", "https://cafe.naver.com", "https://nid.naver.com"])
    except Exception:
        return False

    login_cookie_names = {"NID_AUT", "NID_SES"}
    return any(cookie.get("name") in login_cookie_names for cookie in cookies)


def save_session_state(context: BrowserContext) -> None:
    SESSION_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # This file is a sensitive cookie/session backup. Never log its contents or
    # commit it; .gitignore excludes data/auth/*.json.
    context.storage_state(path=str(SESSION_STATE_PATH))


def apply_saved_session_state(context: BrowserContext) -> None:
    if not SESSION_STATE_PATH.exists():
        return

    try:
        raw = json.loads(SESSION_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return

    cookies = raw.get("cookies")
    if isinstance(cookies, list) and cookies:
        try:
            context.add_cookies(cookies)
        except Exception:
            pass


def setup_login_session(progress: Optional[ProgressCallback] = None) -> None:
    emit(progress, "로그인 세션 연결을 시작합니다.")
    with sync_playwright() as playwright:
        context = create_browser_context(playwright, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded", timeout=60000)
            emit(progress, "열린 브라우저에서 네이버 로그인을 완료해주세요. 로그인 세션이 확인되면 자동으로 저장합니다.")

            for _ in range(600):
                if has_naver_login_cookie(context):
                    # Save as soon as login cookies appear so closing the
                    # visible setup browser does not lose the session.
                    emit(progress, "네이버 로그인 세션을 확인했습니다. 세션을 저장하는 중...")
                    page.wait_for_timeout(1500)
                    save_session_state(context)
                    emit(progress, "로그인 세션이 저장되었습니다. 이제 브라우저 창을 닫아도 됩니다.")
                    return
                if page.is_closed():
                    break
                page.wait_for_timeout(1000)

            if has_naver_login_cookie(context):
                save_session_state(context)
                emit(progress, "로그인 세션이 저장되었습니다.")
                return

            raise AccessRequiredError("네이버 로그인 세션을 확인하지 못했습니다. 다시 로그인 세션 연결을 진행해주세요.")
        finally:
            context.close()


def check_saved_session(progress: Optional[ProgressCallback] = None) -> bool:
    emit(progress, "저장된 네이버 로그인 세션을 확인하는 중...")
    with sync_playwright() as playwright:
        context: Optional[BrowserContext] = None
        try:
            context = create_browser_context(playwright, headless=True)
            apply_saved_session_state(context)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://cafe.naver.com", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except TimeoutError:
                pass
            return has_naver_login_cookie(context) and "nid.naver.com" not in page.url.lower()
        except Exception:
            return False
        finally:
            if context is not None:
                context.close()


def open_post_page(page: Page, url: str, progress: Optional[ProgressCallback] = None) -> None:
    emit(progress, "네이버 카페 게시글을 다운로드하는 중...")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except TimeoutError:
        pass
    page.wait_for_timeout(1500)


def list_frames(page: Page) -> list[dict[str, str]]:
    return [{"name": frame.name or "", "url": frame.url or ""} for frame in page.frames]


def get_cafe_article_frame_or_page(page: Page) -> FrameTarget:
    for frame in page.frames:
        frame_name = (frame.name or "").strip()
        if frame_name.lower() == "cafe_main" or "cafe_main" in frame_name.lower():
            return FrameTarget(frame, True, frame_name or "cafe_main", frame.url or None)

    for selector in ("iframe#cafe_main", "iframe[name='cafe_main']"):
        try:
            iframe = page.locator(selector).first
            if iframe.count() == 0:
                continue
            handle = iframe.element_handle()
            frame = handle.content_frame() if handle else None
            if frame:
                return FrameTarget(frame, True, frame.name or "cafe_main", frame.url or None)
        except Exception:
            continue

    for frame in page.frames:
        if frame == page.main_frame:
            continue
        frame_url = (frame.url or "").lower()
        if "articleread" in frame_url or "/ca-fe/" in frame_url:
            return FrameTarget(frame, True, frame.name or None, frame.url or None)

    return FrameTarget(page, False, None, None)


def get_host_page(target: TargetPage) -> Page:
    return target if isinstance(target, Page) else target.page


def get_target_url(target_info: FrameTarget) -> str:
    if target_info.used_iframe and target_info.iframe_url:
        return target_info.iframe_url
    return get_host_page(target_info.target).url


def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    normalized = re.sub(r"[ ]{2,}", " ", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def looks_like_access_limited_text(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in text for keyword in ACCESS_KEYWORDS) or ("naver" in lowered and "login" in lowered)


def is_login_or_access_issue(page: Page, target: TargetPage) -> bool:
    if "nid.naver.com" in page.url.lower():
        return True

    for selector in ("input#id", "input[type='password']", "form[action*='nidlogin.login']"):
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible(timeout=300):
                return True
        except Exception:
            continue

    for candidate in (target, page):
        try:
            body_text = clean_text(candidate.locator("body").first.inner_text(timeout=1500))
            if looks_like_access_limited_text(body_text):
                return True
        except Exception:
            continue

    return False


def wait_for_article_content(target: TargetPage) -> None:
    host_page = get_host_page(target)
    for _ in range(20):
        for selector in (*TITLE_SELECTORS[:-1], *BODY_SELECTORS):
            try:
                if target.locator(selector).first.count() > 0:
                    return
            except Exception:
                continue
        host_page.wait_for_timeout(500)


def is_valid_title(title: str) -> bool:
    if not title:
        return False
    normalized = clean_text(title)
    lowered = normalized.lower()
    if normalized in {"블로그 접속 불가", "네이버 카페", "NAVER CAFE"}:
        return False
    if normalized.startswith("네이버 카페"):
        return False
    if "login" in lowered and "naver" in lowered:
        return False
    return True


def build_fallback_title(parsed_url: ParsedCafeUrl) -> str:
    if parsed_url.cafe_name and parsed_url.article_id:
        return f"naver_cafe_{parsed_url.cafe_name}_{parsed_url.article_id}"
    if parsed_url.club_id and parsed_url.article_id:
        return f"naver_cafe_{parsed_url.club_id}_{parsed_url.article_id}"
    return "naver_cafe_saved_post"


def extract_title(frame_or_page: TargetPage, parsed_url: ParsedCafeUrl) -> tuple[str, str]:
    for selector in TITLE_SELECTORS:
        try:
            if selector == "title":
                title = clean_text(get_host_page(frame_or_page).title())
            else:
                locator = frame_or_page.locator(selector).first
                if locator.count() == 0:
                    continue
                title = clean_text(locator.inner_text(timeout=2000))
            if is_valid_title(title):
                return title, selector
        except Exception:
            continue

    return build_fallback_title(parsed_url), "fallback"


def extract_body_container(frame_or_page: TargetPage) -> tuple[Locator, str]:
    for selector in BODY_SELECTORS:
        try:
            locator = frame_or_page.locator(selector).first
            if locator.count() == 0:
                continue
            text = clean_text(locator.inner_text(timeout=3000))
            html = get_outer_or_inner_html(locator)
            if text or html.strip():
                return locator, selector
        except Exception:
            continue

    try:
        body = frame_or_page.locator("body").first
        if body.count() > 0:
            text = clean_text(body.inner_text(timeout=3000))
            if text and not looks_like_access_limited_text(text):
                return body, "body"
    except Exception:
        pass

    raise RuntimeError("본문 컨테이너를 찾지 못했습니다.")


def extract_text(container: Locator) -> str:
    return clean_text(container.inner_text(timeout=5000))


def get_outer_or_inner_html(locator: Locator) -> str:
    try:
        return str(locator.evaluate("(node) => node.outerHTML"))
    except Exception:
        return locator.inner_html(timeout=3000)


def parse_srcset(srcset: str, base_url: str) -> Optional[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for part in srcset.split(","):
        segment = part.strip()
        if not segment:
            continue
        url_part = segment.split()[0]
        if url_part:
            candidates.append((resolve_url(base_url, url_part), url_part))
    return candidates[-1] if candidates else None


def resolve_url(base_url: str, candidate: str) -> str:
    if candidate.startswith("//"):
        scheme = urlparse(base_url).scheme or "https"
        return f"{scheme}:{candidate}"
    return urljoin(base_url, candidate)


def should_skip_image_url(url: str, class_name: str, alt_text: str) -> bool:
    lowered_url = url.lower()
    lowered_class = class_name.lower()
    lowered_alt = alt_text.lower()
    if not url or lowered_url.startswith("data:") or lowered_url.startswith("blob:"):
        return True
    if lowered_url.endswith(".svg"):
        return True
    if "ssl.pstatic.net/static" in lowered_url or "static.nid.naver.com" in lowered_url:
        return True
    skip_tokens = ("icon", "ico", "button", "profile", "sticker", "menu", "comment")
    return any(token in lowered_class for token in skip_tokens) or any(token in lowered_alt for token in skip_tokens)


def extract_image_urls(container: Locator, base_url: str) -> list[ImageInfo]:
    image_data = container.evaluate(
        """
        (node) => Array.from(node.querySelectorAll('img')).map((img) => ({
            dataLazySrc: img.getAttribute('data-lazy-src'),
            dataSrc: img.getAttribute('data-src'),
            dataOriginal: img.getAttribute('data-original'),
            src: img.getAttribute('src'),
            srcset: img.getAttribute('srcset'),
            className: img.className || '',
            alt: img.getAttribute('alt') || ''
        }))
        """
    )

    results: list[ImageInfo] = []
    seen: set[str] = set()
    for item in image_data:
        if not isinstance(item, dict):
            continue

        candidates: list[tuple[str, str]] = []
        srcset = item.get("srcset")
        if isinstance(srcset, str) and srcset.strip():
            parsed_srcset = parse_srcset(srcset, base_url)
            if parsed_srcset:
                candidates.append(parsed_srcset)

        for key in ("dataLazySrc", "dataSrc", "dataOriginal", "src"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append((resolve_url(base_url, value.strip()), value.strip()))

        class_name = str(item.get("className") or "")
        alt_text = str(item.get("alt") or "")
        chosen: Optional[ImageInfo] = None
        for absolute, raw_value in candidates:
            if should_skip_image_url(absolute, class_name, alt_text):
                continue
            replacement_values = [absolute, raw_value, resolve_url(base_url, raw_value)]
            if isinstance(srcset, str) and srcset.strip():
                replacement_values.append(srcset)
            chosen = ImageInfo(url=absolute, replacement_values=list(dict.fromkeys(replacement_values)))
            break

        if chosen and chosen.url not in seen:
            seen.add(chosen.url)
            results.append(chosen)

    return results


def sanitize_filename(name: str) -> str:
    cleaned = name.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    cleaned = re.sub(INVALID_FILENAME_CHARS, "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "naver_cafe_saved_post"
    return cleaned[:MAX_FOLDER_NAME_LENGTH].rstrip(" .") or "naver_cafe_saved_post"


def create_unique_folder(base_dir: Path, title: str) -> Path:
    safe_name = sanitize_filename(title)
    candidate = base_dir / safe_name
    if not candidate.exists():
        return candidate

    index = 2
    while True:
        numbered = base_dir / f"{safe_name}_{index}"
        if not numbered.exists():
            return numbered
        index += 1


def extension_from_response(image_url: str, response: Response) -> str:
    suffix = Path(urlparse(image_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix

    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return mapping.get(content_type, ".jpg")


def download_images(
    context: BrowserContext,
    image_infos: Sequence[ImageInfo],
    images_dir: Path,
    referer_url: str,
    progress: Optional[ProgressCallback] = None,
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    images_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[str] = []
    failed_images: list[dict[str, str]] = []
    image_map: dict[str, str] = {}

    if image_infos:
        emit(progress, f"이미지 {len(image_infos)}개 다운로드 중...")

    for index, image_info in enumerate(image_infos, start=1):
        try:
            response = context.request.get(image_info.url, headers={"Referer": referer_url}, timeout=30000)
            if not response.ok:
                failed_images.append({"url": image_info.url, "reason": f"HTTP {response.status}"})
                continue

            extension = extension_from_response(image_info.url, response)
            file_name = f"{index:03d}{extension}"
            relative_path = str(Path("images") / file_name)
            file_path = images_dir / file_name
            file_path.write_bytes(response.body())
            saved_files.append(relative_path)
            for source in image_info.replacement_values:
                image_map[source] = relative_path.replace("\\", "/")
        except Exception as exc:
            failed_images.append({"url": image_info.url, "reason": str(exc)})

    return saved_files, failed_images, image_map


def save_debug_files(page: Page, info_data: dict[str, Any]) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG_DIR / "debug_screenshot.png"), full_page=True)
    except Exception as exc:
        info_data["debug_screenshot_error"] = str(exc)

    try:
        (DEBUG_DIR / "debug_page.html").write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        info_data["debug_html_error"] = str(exc)

    (DEBUG_DIR / "debug_info.json").write_text(json.dumps(info_data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_debug_info(
    page: Page,
    parsed_url: ParsedCafeUrl,
    target_info: Optional[FrameTarget],
    error_message: str,
) -> dict[str, Any]:
    frames = list_frames(page)
    return {
        "source_url": parsed_url.original_url,
        "current_url": page.url,
        "final_url": get_target_url(target_info) if target_info else page.url,
        "all_frame_names": [frame["name"] for frame in frames],
        "all_frame_urls": [frame["url"] for frame in frames],
        "cafe_main_detected": any("cafe_main" in (frame["name"] or "").lower() for frame in frames),
        "title_selectors_tried": list(TITLE_SELECTORS),
        "body_selectors_tried": list(BODY_SELECTORS),
        "error_message": error_message,
    }


def extract_current_post(page: Page, parsed_url: ParsedCafeUrl) -> ExtractionResult:
    target_info = get_cafe_article_frame_or_page(page)
    target = target_info.target
    wait_for_article_content(target)
    title, title_selector = extract_title(target, parsed_url)
    container, body_selector = extract_body_container(target)
    body_text = extract_text(container)

    if not body_text or looks_like_access_limited_text(body_text):
        raise RuntimeError("본문 텍스트를 추출하지 못했습니다.")

    final_url = get_target_url(target_info)
    body_html = get_outer_or_inner_html(container)
    image_infos = extract_image_urls(container, final_url)

    return ExtractionResult(
        title=title,
        body_text=body_text,
        body_html=body_html,
        image_infos=image_infos,
        final_url=final_url,
        used_iframe=target_info.used_iframe,
        iframe_name=target_info.iframe_name,
        iframe_url=target_info.iframe_url,
        access_status="accessible",
        title_selector=title_selector,
        body_selector=body_selector,
    )


def build_meta(
    *,
    post_id: str,
    parsed_url: ParsedCafeUrl,
    result: ExtractionResult,
    folder: Path,
    local_view_path: Path,
    image_files: Sequence[str],
    failed_images: Sequence[dict[str, str]],
) -> dict[str, Any]:
    return {
        "id": post_id,
        "source_url": parsed_url.original_url,
        "final_url": result.final_url,
        "cafe_name": parsed_url.cafe_name,
        "club_id": parsed_url.club_id,
        "article_id": parsed_url.article_id,
        "title": result.title,
        "saved_at": datetime.now().astimezone().isoformat(),
        "folder_path": str(folder.resolve()),
        "local_view_path": str(local_view_path.resolve()),
        "body_text_length": len(result.body_text),
        "image_count": len(image_files),
        "image_files": list(image_files),
        "failed_images": list(failed_images),
        "used_iframe": result.used_iframe,
        "iframe_name": result.iframe_name,
        "iframe_url": result.iframe_url,
        "selectors_used": {
            "title": result.title_selector,
            "body": result.body_selector,
        },
        "access_status": result.access_status,
    }


def save_post_files(folder: Path, text: str, html: str, meta: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "content.txt").write_text(text, encoding="utf-8")
    (folder / "content.html").write_text(html, encoding="utf-8")
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _download_post_once(
    parsed_url: ParsedCafeUrl,
    *,
    headless: bool,
    progress: Optional[ProgressCallback],
    confirm_existing_folder: Optional[ExistingFolderCallback],
) -> dict[str, Any]:
    with sync_playwright() as playwright:
        context: Optional[BrowserContext] = None
        page: Optional[Page] = None
        target_info: Optional[FrameTarget] = None
        try:
            context = create_browser_context(playwright, headless=headless)
            apply_saved_session_state(context)
            page = context.pages[0] if context.pages else context.new_page()
            open_post_page(page, parsed_url.normalized_url, progress)
            target_info = get_cafe_article_frame_or_page(page)
            if is_login_or_access_issue(page, target_info.target):
                raise AccessRequiredError(SESSION_EXPIRED_MESSAGE)

            result = extract_current_post(page, parsed_url)
            existing_folder = SAVED_POSTS_DIR / sanitize_filename(result.title)
            if existing_folder.exists() and confirm_existing_folder and not confirm_existing_folder(existing_folder, result.title):
                raise DownloadCancelledError("다운로드가 취소되었습니다.")

            post_id = uuid.uuid4().hex
            folder = create_unique_folder(SAVED_POSTS_DIR, result.title)
            image_files, failed_images, image_map = download_images(
                context=context,
                image_infos=result.image_infos,
                images_dir=folder / "images",
                referer_url=result.final_url,
                progress=progress,
            )
            saved_at = datetime.now().astimezone().isoformat()
            local_view_path = folder / "view.html"
            build_local_page(
                title=result.title,
                content_html=result.body_html,
                image_map=image_map,
                source_url=result.final_url,
                saved_at=saved_at,
                output_path=local_view_path,
            )
            meta = build_meta(
                post_id=post_id,
                parsed_url=parsed_url,
                result=result,
                folder=folder,
                local_view_path=local_view_path,
                image_files=image_files,
                failed_images=failed_images,
            )
            meta["saved_at"] = saved_at
            save_post_files(folder, result.body_text, result.body_html, meta)
            save_session_state(context)
            return meta
        except DownloadCancelledError:
            raise
        except Exception as exc:
            if page is not None:
                if target_info is None:
                    try:
                        target_info = get_cafe_article_frame_or_page(page)
                    except Exception:
                        target_info = None
                save_debug_files(page, build_debug_info(page, parsed_url, target_info, str(exc)))
            raise
        finally:
            if context is not None:
                context.close()


def download_post(
    url: str,
    progress: Optional[ProgressCallback] = None,
    confirm_existing_folder: Optional[ExistingFolderCallback] = None,
) -> dict[str, Any]:
    parsed_url = parse_naver_cafe_url(url)
    SAVED_POSTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        return _download_post_once(
            parsed_url,
            headless=True,
            progress=progress,
            confirm_existing_folder=confirm_existing_folder,
        )
    except AccessRequiredError:
        emit(progress, "백그라운드 세션이 인증을 요구해 보이는 브라우저로 한 번 더 확인합니다.")
        return _download_post_once(
            parsed_url,
            headless=False,
            progress=progress,
            confirm_existing_folder=confirm_existing_folder,
        )
