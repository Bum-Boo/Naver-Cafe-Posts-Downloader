from __future__ import annotations

import json
import random
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Sequence
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import BrowserContext, Frame, Locator, Page, Playwright, Response, TimeoutError, sync_playwright

from storage.archive_index import get_existing_article_keys, make_article_key, make_index_entry, upsert_archive_entry
from viewer.local_page_builder import build_local_page


USER_DATA_DIR = Path("./data/browser_profile")
SAVED_POSTS_DIR = Path("./saved_posts")
DEBUG_DIR = SAVED_POSTS_DIR / "_debug"
BATCHES_DIR = Path("./data/batches")
SESSION_STATE_PATH = Path("./data/auth/naver_state.json")
MAX_FOLDER_NAME_LENGTH = 80
INVALID_FILENAME_CHARS = r'[\\/:*?"<>|]'
BATCH_POST_DELAY_RANGE = (0.6, 1.2)
POST_SETTLE_TIMEOUT_MS = 700
MENU_SETTLE_TIMEOUT_MS = 800
NETWORK_IDLE_TIMEOUT_MS = 6000

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

MENU_TITLE_SELECTORS: Sequence[str] = (
    ".BoardTitle",
    ".board_title",
    ".board_name",
    ".MenuTitle",
    ".menu_name",
    "[class*='BoardTitle']",
    "[class*='board_title']",
    "[class*='boardName']",
    "[class*='menu_name']",
    "[class*='MenuTitle']",
    ".title_area .title",
    ".title_area .title_text",
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
ProgressValueCallback = Callable[[int, int], None]
ExistingFolderCallback = Callable[[Path, str], bool]
CancelCallback = Callable[[], bool]
TargetPage = Page | Frame
UrlType = Literal["single_post", "menu", "unsupported"]
SESSION_EXPIRED_MESSAGE = "네이버 로그인 세션이 만료되었거나 카페 접근 권한 확인이 필요합니다. [네이버 로그인 세션 연결]을 다시 실행해주세요."


@dataclass
class ParsedCafeUrl:
    original_url: str
    normalized_url: str
    cafe_name: Optional[str]
    club_id: Optional[str]
    article_id: Optional[str]
    url_type: UrlType = "unsupported"
    menu_id: Optional[str] = None


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


@dataclass
class MenuCollectionResult:
    source_url: str
    final_url: str
    club_id: Optional[str]
    menu_id: Optional[str]
    menu_title: Optional[str]
    article_urls: list[str]


@dataclass
class BatchDownloadResult:
    batch_id: str
    source_menu_url: str
    menu_id: Optional[str]
    menu_title: Optional[str]
    started_at: str
    completed_at: str
    total_found: int
    downloaded_count: int
    skipped_count: int
    failed_count: int
    downloaded_article_keys: list[str]
    failed_urls: list[dict[str, str]]
    skipped_urls: list[str]
    downloaded_meta: list[dict[str, Any]]
    menu_folder_path: str
    result_path: str
    failed_urls_path: str
    cancelled: bool = False
    cancelled_at: Optional[str] = None
    remaining_count: int = 0


class AccessRequiredError(RuntimeError):
    pass


class DownloadCancelledError(RuntimeError):
    pass


class PostDownloadError(RuntimeError):
    def __init__(self, message: str, debug_folder: Optional[Path] = None) -> None:
        super().__init__(message)
        self.debug_folder = debug_folder


def emit(progress: Optional[ProgressCallback], message: str) -> None:
    if progress:
        progress(message)


def emit_progress_value(progress_value: Optional[ProgressValueCallback], current: int, total: int) -> None:
    if progress_value:
        progress_value(current, total)


def check_cancelled(should_cancel: Optional[CancelCallback], message: str = "다운로드가 취소되었습니다.") -> None:
    if should_cancel and should_cancel():
        raise DownloadCancelledError(message)


def first_query_value(query: dict[str, list[str]], *keys: str) -> Optional[str]:
    for key in keys:
        values = query.get(key)
        if values:
            return values[0]
    return None


def path_value_after(path_parts: Sequence[str], marker: str) -> Optional[str]:
    try:
        return path_parts[path_parts.index(marker) + 1]
    except (ValueError, IndexError):
        return None


def parse_naver_cafe_url(url: str) -> ParsedCafeUrl:
    # Keep URL classification in one place so the UI and downloader agree on
    # whether a pasted URL is a single article, a menu/board, or unsupported.
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    query = parse_qs(parsed.query)

    cafe_name: Optional[str] = None
    club_id = first_query_value(query, "clubid", "clubId")
    article_id = first_query_value(query, "articleid", "articleId")
    menu_id: Optional[str] = None
    url_type: UrlType = "unsupported"

    path_parts = [part for part in parsed.path.split("/") if part]
    host = parsed.netloc.lower()

    if host in {"cafe.naver.com", "m.cafe.naver.com"}:
        if "cafes" in path_parts:
            club_id = club_id or path_value_after(path_parts, "cafes")
        if "menus" in path_parts:
            menu_id = path_value_after(path_parts, "menus")
        if "articles" in path_parts:
            article_id = article_id or path_value_after(path_parts, "articles")

        if len(path_parts) >= 2 and path_parts[0].lower() not in {"articleread.nhn", "ca-fe", "f-e"}:
            cafe_name = path_parts[0]
            if article_id is None and path_parts[1].isdigit():
                article_id = path_parts[1]

        if menu_id and club_id:
            url_type = "menu"
        elif article_id and (club_id or cafe_name or (path_parts and path_parts[0].lower() == "articleread.nhn")):
            url_type = "single_post"

    normalized_url = parsed.geturl() if parsed.scheme and parsed.netloc else cleaned
    return ParsedCafeUrl(
        original_url=cleaned,
        normalized_url=normalized_url,
        cafe_name=cafe_name,
        club_id=club_id,
        article_id=article_id,
        url_type=url_type,
        menu_id=menu_id,
    )


def parse_naver_cafe_url_type(url: str) -> ParsedCafeUrl:
    return parse_naver_cafe_url(url)


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


def open_post_page(
    page: Page,
    url: str,
    progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> None:
    check_cancelled(should_cancel)
    emit(progress, "게시글 페이지를 여는 중...")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    check_cancelled(should_cancel)
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    except TimeoutError:
        pass
    check_cancelled(should_cancel)
    page.wait_for_timeout(POST_SETTLE_TIMEOUT_MS)


def list_frames(page: Page) -> list[dict[str, str]]:
    return [{"name": frame.name or "", "url": frame.url or ""} for frame in page.frames]


def get_cafe_article_frame_or_page(page: Page) -> FrameTarget:
    # Old Cafe pages render the article inside cafe_main, while newer pages can
    # render directly. Always prefer the cafe frame before direct-page fallback.
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


def is_login_page_or_form(page: Page) -> bool:
    if "nid.naver.com" in page.url.lower():
        return True
    for selector in ("input#id", "input[type='password']", "form[action*='nidlogin.login']"):
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible(timeout=300):
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


def normalize_article_url(candidate_url: str, base_url: str = "https://cafe.naver.com") -> Optional[str]:
    absolute = resolve_url(base_url, candidate_url.strip())
    parsed = urlparse(absolute)
    host = parsed.netloc.lower()
    if host not in {"cafe.naver.com", "m.cafe.naver.com"}:
        return None

    query = parse_qs(parsed.query)
    path_parts = [part for part in parsed.path.split("/") if part]
    club_id = first_query_value(query, "clubid", "clubId")
    article_id = first_query_value(query, "articleid", "articleId")
    cafe_name: Optional[str] = None

    if "cafes" in path_parts:
        club_id = club_id or path_value_after(path_parts, "cafes")
    if "articles" in path_parts:
        article_id = article_id or path_value_after(path_parts, "articles")

    if len(path_parts) >= 2 and path_parts[0].lower() not in {"articleread.nhn", "ca-fe", "f-e"}:
        cafe_name = path_parts[0]
        article_id = article_id or path_parts[1]

    if not article_id:
        return None
    if club_id:
        return f"https://cafe.naver.com/ca-fe/cafes/{club_id}/articles/{article_id}"
    if cafe_name:
        return f"https://cafe.naver.com/{cafe_name}/{article_id}"
    return None


def collect_article_urls_from_target(target: TargetPage, base_url: str) -> list[str]:
    try:
        hrefs = target.evaluate(
            """
            (baseUrl) => Array.from(document.querySelectorAll('a[href]'))
              .filter((anchor) => {
                const rect = anchor.getBoundingClientRect();
                const style = window.getComputedStyle(anchor);
                return style.display !== 'none'
                  && style.visibility !== 'hidden'
                  && (rect.width > 0 || rect.height > 0);
              })
              .map((anchor) => {
                try {
                  return new URL(anchor.getAttribute('href'), baseUrl).href;
                } catch {
                  return '';
                }
              })
              .filter(Boolean)
            """,
            base_url,
        )
    except Exception:
        return []

    results: list[str] = []
    for href in hrefs:
        if not isinstance(href, str):
            continue
        normalized = normalize_article_url(href, base_url)
        if normalized:
            results.append(normalized)
    return results


def collect_visible_article_urls(page: Page, base_url: str) -> list[str]:
    collected: list[str] = []
    for frame in page.frames:
        collected.extend(collect_article_urls_from_target(frame, base_url))
    return collected


def extract_menu_title_from_target(target: TargetPage) -> Optional[str]:
    for selector in MENU_TITLE_SELECTORS:
        try:
            locator = target.locator(selector).first
            if locator.count() == 0:
                continue
            title = clean_text(locator.inner_text(timeout=1500))
            if title and len(title) <= 120 and not looks_like_access_limited_text(title):
                return title
        except Exception:
            continue
    return None


def extract_menu_title(page: Page) -> Optional[str]:
    for frame in page.frames:
        title = extract_menu_title_from_target(frame)
        if title:
            return title

    title = clean_text(page.title())
    for suffix in (" : 네이버 카페", " - 네이버 카페", " 네이버 카페"):
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    return title or None


def click_visible_more_button(page: Page) -> bool:
    selectors = (
        "button:has-text('더보기')",
        "a:has-text('더보기')",
        "button:has-text('더 보기')",
        "a:has-text('더 보기')",
        ".btn_more",
        ".more",
        "[class*='more']",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible(timeout=300):
                locator.click(timeout=1000)
                page.wait_for_timeout(1000)
                return True
        except Exception:
            continue
    return False


def open_menu_page(
    page: Page,
    url: str,
    progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> None:
    check_cancelled(should_cancel, "메뉴 다운로드가 취소되었습니다.")
    emit(progress, "메뉴 게시글 목록을 수집하는 중...")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    check_cancelled(should_cancel, "메뉴 다운로드가 취소되었습니다.")
    try:
        page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
    except TimeoutError:
        pass
    check_cancelled(should_cancel, "메뉴 다운로드가 취소되었습니다.")
    page.wait_for_timeout(MENU_SETTLE_TIMEOUT_MS)


def _collect_menu_article_urls_once(
    parsed_url: ParsedCafeUrl,
    *,
    headless: bool,
    progress: Optional[ProgressCallback],
    max_posts: Optional[int],
    max_scroll_rounds: int,
    should_cancel: Optional[CancelCallback],
) -> MenuCollectionResult:
    with sync_playwright() as playwright:
        context: Optional[BrowserContext] = None
        page: Optional[Page] = None
        try:
            context = create_browser_context(playwright, headless=headless)
            apply_saved_session_state(context)
            page = context.pages[0] if context.pages else context.new_page()
            open_menu_page(page, parsed_url.normalized_url, progress, should_cancel)
            if is_login_page_or_form(page):
                raise AccessRequiredError(SESSION_EXPIRED_MESSAGE)

            article_urls: list[str] = []
            seen: set[str] = set()
            stagnant_rounds = 0

            for _round in range(max_scroll_rounds):
                check_cancelled(should_cancel, "메뉴 다운로드가 취소되었습니다.")
                before_count = len(article_urls)
                for article_url in collect_visible_article_urls(page, page.url):
                    check_cancelled(should_cancel, "메뉴 다운로드가 취소되었습니다.")
                    if article_url in seen:
                        continue
                    seen.add(article_url)
                    article_urls.append(article_url)
                    if max_posts is not None and len(article_urls) >= max_posts:
                        break

                if max_posts is not None and len(article_urls) >= max_posts:
                    break

                clicked_more = click_visible_more_button(page)
                check_cancelled(should_cancel, "메뉴 다운로드가 취소되었습니다.")
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(MENU_SETTLE_TIMEOUT_MS)

                if len(article_urls) == before_count and not clicked_more:
                    stagnant_rounds += 1
                else:
                    stagnant_rounds = 0
                if stagnant_rounds >= 3:
                    break

            if not article_urls:
                try:
                    body_text = clean_text(page.locator("body").first.inner_text(timeout=1500))
                except Exception:
                    body_text = ""
                if looks_like_access_limited_text(body_text):
                    raise AccessRequiredError(SESSION_EXPIRED_MESSAGE)

            menu_title = extract_menu_title(page)
            return MenuCollectionResult(
                source_url=parsed_url.original_url,
                final_url=page.url,
                club_id=parsed_url.club_id,
                menu_id=parsed_url.menu_id,
                menu_title=menu_title,
                article_urls=article_urls,
            )
        except AccessRequiredError:
            raise
        except DownloadCancelledError:
            raise
        except Exception as exc:
            if page is not None:
                debug_folder = save_debug_files(page, build_debug_info(page, parsed_url, None, str(exc)), parsed_url)
                raise PostDownloadError(str(exc), debug_folder) from exc
            raise
        finally:
            if context is not None:
                context.close()


def collect_menu_article_urls(
    menu_url: str,
    progress: Optional[ProgressCallback] = None,
    max_posts: Optional[int] = None,
    max_scroll_rounds: int = 30,
    should_cancel: Optional[CancelCallback] = None,
) -> MenuCollectionResult:
    # Menu collection only reads links visible in the logged-in browser session.
    # It does not call private APIs or infer hidden posts.
    parsed_url = parse_naver_cafe_url(menu_url)
    if parsed_url.url_type != "menu":
        raise ValueError("지원하지 않는 메뉴 URL입니다.")

    try:
        return _collect_menu_article_urls_once(
            parsed_url,
            headless=True,
            progress=progress,
            max_posts=max_posts,
            max_scroll_rounds=max_scroll_rounds,
            should_cancel=should_cancel,
        )
    except AccessRequiredError:
        emit(progress, "백그라운드 세션이 인증을 요구해 보이는 브라우저로 메뉴를 다시 확인합니다.")
        return _collect_menu_article_urls_once(
            parsed_url,
            headless=False,
            progress=progress,
            max_posts=max_posts,
            max_scroll_rounds=max_scroll_rounds,
            should_cancel=should_cancel,
        )


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


def create_menu_base_folder(menu_id: Optional[str], menu_title: Optional[str]) -> Path:
    if menu_title:
        folder_name = f"{menu_id or 'menu'}_{sanitize_filename(menu_title)}"
    else:
        folder_name = f"menu_{menu_id or 'unknown'}"
    return SAVED_POSTS_DIR / "menus" / folder_name


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
    progress_value: Optional[ProgressValueCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    images_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[str] = []
    failed_images: list[dict[str, str]] = []
    image_map: dict[str, str] = {}

    if image_infos:
        emit(progress, f"이미지 {len(image_infos)}개 다운로드 중...")
        emit_progress_value(progress_value, 0, len(image_infos))

    for index, image_info in enumerate(image_infos, start=1):
        check_cancelled(should_cancel)
        emit(progress, f"이미지 {index}/{len(image_infos)} 다운로드 중...")
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
        finally:
            emit_progress_value(progress_value, index, len(image_infos))

    return saved_files, failed_images, image_map


def make_debug_folder(parsed_url: Optional[ParsedCafeUrl]) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    identity = "unknown"
    if parsed_url is not None:
        identity = parsed_url.article_id or parsed_url.menu_id or "unknown"
    folder = DEBUG_DIR / f"{timestamp}_{sanitize_filename(identity)}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_debug_files(page: Page, info_data: dict[str, Any], parsed_url: Optional[ParsedCafeUrl] = None) -> Path:
    debug_folder = make_debug_folder(parsed_url)
    info_data["debug_folder"] = str(debug_folder.resolve())
    try:
        page.screenshot(path=str(debug_folder / "debug_screenshot.png"), full_page=True)
    except Exception as exc:
        info_data["debug_screenshot_error"] = str(exc)

    try:
        (debug_folder / "debug_page.html").write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        info_data["debug_html_error"] = str(exc)

    (debug_folder / "debug_info.json").write_text(json.dumps(info_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return debug_folder


def build_debug_info(
    page: Page,
    parsed_url: ParsedCafeUrl,
    target_info: Optional[FrameTarget],
    error_message: str,
) -> dict[str, Any]:
    frames = list_frames(page)
    return {
        "source_url": parsed_url.original_url,
        "url_type": parsed_url.url_type,
        "current_url": page.url,
        "final_url": get_target_url(target_info) if target_info else page.url,
        "club_id": parsed_url.club_id,
        "article_id": parsed_url.article_id,
        "menu_id": parsed_url.menu_id,
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
    source_menu_url: Optional[str] = None,
    menu_id: Optional[str] = None,
    menu_title: Optional[str] = None,
    batch_id: Optional[str] = None,
    download_type: str = "single_post",
) -> dict[str, Any]:
    article_key = make_article_key(
        club_id=parsed_url.club_id,
        article_id=parsed_url.article_id,
        cafe_name=parsed_url.cafe_name,
        source_url=parsed_url.normalized_url,
    )
    return {
        "id": post_id,
        "download_type": download_type,
        "article_key": article_key,
        "source_url": parsed_url.original_url,
        "final_url": result.final_url,
        "cafe_name": parsed_url.cafe_name,
        "club_id": parsed_url.club_id,
        "article_id": parsed_url.article_id,
        "menu_id": menu_id,
        "menu_title": menu_title,
        "source_menu_url": source_menu_url,
        "batch_id": batch_id,
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


def _download_post_with_context(
    *,
    context: BrowserContext,
    page: Page,
    parsed_url: ParsedCafeUrl,
    progress: Optional[ProgressCallback],
    confirm_existing_folder: Optional[ExistingFolderCallback],
    destination_base_dir: Path,
    source_menu_url: Optional[str] = None,
    menu_id: Optional[str] = None,
    menu_title: Optional[str] = None,
    batch_id: Optional[str] = None,
    progress_value: Optional[ProgressValueCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
    save_state_after: bool = True,
) -> dict[str, Any]:
    # Shared implementation for single-post downloads and menu batch downloads.
    # Batch mode passes an existing context/page so it avoids reopening Chromium
    # for every article.
    target_info: Optional[FrameTarget] = None
    try:
        check_cancelled(should_cancel)
        open_post_page(page, parsed_url.normalized_url, progress, should_cancel)
        target_info = get_cafe_article_frame_or_page(page)
        if is_login_or_access_issue(page, target_info.target):
            raise AccessRequiredError(SESSION_EXPIRED_MESSAGE)

        check_cancelled(should_cancel)
        emit(progress, "제목과 본문을 추출하는 중...")
        result = extract_current_post(page, parsed_url)
        existing_folder = SAVED_POSTS_DIR / sanitize_filename(result.title)
        if existing_folder.exists() and confirm_existing_folder and not confirm_existing_folder(existing_folder, result.title):
            raise DownloadCancelledError("다운로드가 취소되었습니다.")

        check_cancelled(should_cancel)
        post_id = uuid.uuid4().hex
        folder = create_unique_folder(destination_base_dir, result.title)
        image_files, failed_images, image_map = download_images(
            context=context,
            image_infos=result.image_infos,
            images_dir=folder / "images",
            referer_url=result.final_url,
            progress=progress,
            progress_value=progress_value,
            should_cancel=should_cancel,
        )
        saved_at = datetime.now().astimezone().isoformat()
        local_view_path = folder / "view.html"
        check_cancelled(should_cancel)
        emit(progress, "로컬 페이지를 생성하는 중...")
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
            source_menu_url=source_menu_url,
            menu_id=menu_id,
            menu_title=menu_title,
            batch_id=batch_id,
            download_type="menu_batch" if batch_id else "single_post",
        )
        meta["saved_at"] = saved_at
        save_post_files(folder, result.body_text, result.body_html, meta)
        if save_state_after:
            save_session_state(context)
        emit(progress, "저장 완료")
        return meta
    except DownloadCancelledError:
        raise
    except AccessRequiredError:
        raise
    except PostDownloadError:
        raise
    except Exception as exc:
        if target_info is None:
            try:
                target_info = get_cafe_article_frame_or_page(page)
            except Exception:
                target_info = None
        debug_folder = save_debug_files(page, build_debug_info(page, parsed_url, target_info, str(exc)), parsed_url)
        raise PostDownloadError(str(exc), debug_folder) from exc


def _download_post_once(
    parsed_url: ParsedCafeUrl,
    *,
    headless: bool,
    progress: Optional[ProgressCallback],
    confirm_existing_folder: Optional[ExistingFolderCallback],
    destination_base_dir: Path,
    source_menu_url: Optional[str] = None,
    menu_id: Optional[str] = None,
    menu_title: Optional[str] = None,
    batch_id: Optional[str] = None,
    progress_value: Optional[ProgressValueCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> dict[str, Any]:
    with sync_playwright() as playwright:
        context: Optional[BrowserContext] = None
        page: Optional[Page] = None
        target_info: Optional[FrameTarget] = None
        try:
            check_cancelled(should_cancel)
            context = create_browser_context(playwright, headless=headless)
            apply_saved_session_state(context)
            page = context.pages[0] if context.pages else context.new_page()
            open_post_page(page, parsed_url.normalized_url, progress, should_cancel)
            target_info = get_cafe_article_frame_or_page(page)
            if is_login_or_access_issue(page, target_info.target):
                raise AccessRequiredError(SESSION_EXPIRED_MESSAGE)

            check_cancelled(should_cancel)
            emit(progress, "제목과 본문을 추출하는 중...")
            result = extract_current_post(page, parsed_url)
            existing_folder = SAVED_POSTS_DIR / sanitize_filename(result.title)
            if existing_folder.exists() and confirm_existing_folder and not confirm_existing_folder(existing_folder, result.title):
                raise DownloadCancelledError("다운로드가 취소되었습니다.")

            check_cancelled(should_cancel)
            post_id = uuid.uuid4().hex
            folder = create_unique_folder(destination_base_dir, result.title)
            image_files, failed_images, image_map = download_images(
                context=context,
                image_infos=result.image_infos,
                images_dir=folder / "images",
                referer_url=result.final_url,
                progress=progress,
                progress_value=progress_value,
                should_cancel=should_cancel,
            )
            saved_at = datetime.now().astimezone().isoformat()
            local_view_path = folder / "view.html"
            check_cancelled(should_cancel)
            emit(progress, "로컬 페이지를 생성하는 중...")
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
                source_menu_url=source_menu_url,
                menu_id=menu_id,
                menu_title=menu_title,
                batch_id=batch_id,
                download_type="menu_batch" if batch_id else "single_post",
            )
            meta["saved_at"] = saved_at
            save_post_files(folder, result.body_text, result.body_html, meta)
            save_session_state(context)
            emit(progress, "저장 완료")
            return meta
        except DownloadCancelledError:
            raise
        except AccessRequiredError:
            raise
        except PostDownloadError:
            raise
        except Exception as exc:
            if page is not None:
                if target_info is None:
                    try:
                        target_info = get_cafe_article_frame_or_page(page)
                    except Exception:
                        target_info = None
                debug_folder = save_debug_files(page, build_debug_info(page, parsed_url, target_info, str(exc)), parsed_url)
                raise PostDownloadError(str(exc), debug_folder) from exc
            raise PostDownloadError(str(exc)) from exc
        finally:
            if context is not None:
                context.close()


def download_post(
    url: str,
    progress: Optional[ProgressCallback] = None,
    confirm_existing_folder: Optional[ExistingFolderCallback] = None,
    progress_value: Optional[ProgressValueCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> dict[str, Any]:
    parsed_url = parse_naver_cafe_url(url)
    if parsed_url.url_type != "single_post":
        raise ValueError("지원하지 않는 게시글 URL입니다.")
    SAVED_POSTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        return _download_post_once(
            parsed_url,
            headless=True,
            progress=progress,
            confirm_existing_folder=confirm_existing_folder,
            destination_base_dir=SAVED_POSTS_DIR,
            progress_value=progress_value,
            should_cancel=should_cancel,
        )
    except AccessRequiredError:
        emit(progress, "백그라운드 세션이 인증을 요구해 보이는 브라우저로 한 번 더 확인합니다.")
        return _download_post_once(
            parsed_url,
            headless=False,
            progress=progress,
            confirm_existing_folder=confirm_existing_folder,
            destination_base_dir=SAVED_POSTS_DIR,
            progress_value=progress_value,
            should_cancel=should_cancel,
        )


def download_single_post(
    url: str,
    progress: Optional[ProgressCallback] = None,
    target_base_dir: Optional[Path] = None,
    source_menu_info: Optional[dict[str, Any]] = None,
    confirm_existing_folder: Optional[ExistingFolderCallback] = None,
    progress_value: Optional[ProgressValueCallback] = None,
    should_cancel: Optional[CancelCallback] = None,
) -> dict[str, Any]:
    if source_menu_info:
        parsed_url = parse_naver_cafe_url(url)
        destination_base_dir = target_base_dir or SAVED_POSTS_DIR
        common_args = {
            "destination_base_dir": destination_base_dir,
            "source_menu_url": source_menu_info.get("source_menu_url"),
            "menu_id": source_menu_info.get("menu_id"),
            "menu_title": source_menu_info.get("menu_title"),
            "batch_id": source_menu_info.get("batch_id"),
        }
        try:
            return _download_post_once(
                parsed_url,
                headless=True,
                progress=progress,
                confirm_existing_folder=confirm_existing_folder,
                progress_value=progress_value,
                should_cancel=should_cancel,
                **common_args,
            )
        except AccessRequiredError:
            emit(progress, "백그라운드 세션이 인증을 요구해 보이는 브라우저로 한 번 더 확인합니다.")
            return _download_post_once(
                parsed_url,
                headless=False,
                progress=progress,
                confirm_existing_folder=confirm_existing_folder,
                progress_value=progress_value,
                should_cancel=should_cancel,
                **common_args,
            )

    return download_post(
        url,
        progress=progress,
        confirm_existing_folder=confirm_existing_folder,
        progress_value=progress_value,
        should_cancel=should_cancel,
    )


def save_batch_result(result: BatchDownloadResult) -> None:
    BATCHES_DIR.mkdir(parents=True, exist_ok=True)
    Path(result.result_path).write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")

    failed_lines = []
    for item in result.failed_urls:
        line = item.get("url", "")
        reason = item.get("reason", "")
        debug_folder = item.get("debug_folder", "")
        if reason:
            line += f"\t{reason}"
        if debug_folder:
            line += f"\tdebug={debug_folder}"
        failed_lines.append(line)
    Path(result.failed_urls_path).write_text("\n".join(failed_lines), encoding="utf-8")


def download_menu_posts(
    menu_url: str,
    progress: Optional[ProgressCallback] = None,
    progress_value: Optional[ProgressValueCallback] = None,
    max_posts: Optional[int] = None,
    skip_existing: bool = True,
    should_cancel: Optional[CancelCallback] = None,
) -> BatchDownloadResult:
    # Batch mode collects article URLs first, then downloads sequentially in one
    # persistent browser context. This preserves cookies and avoids aggressive
    # parallel requests against Naver Cafe.
    started_at = datetime.now().astimezone().isoformat()
    batch_id = uuid.uuid4().hex
    result_path = BATCHES_DIR / f"{batch_id}.json"
    failed_urls_path = BATCHES_DIR / f"{batch_id}_failed_urls.txt"
    collection: Optional[MenuCollectionResult] = None
    menu_base_folder = create_menu_base_folder(None, None)
    existing_keys = get_existing_article_keys()

    downloaded_meta: list[dict[str, Any]] = []
    skipped_urls: list[str] = []
    failed_urls: list[dict[str, str]] = []
    downloaded_article_keys: list[str] = []
    total = 0
    processed = 0

    def build_result(*, cancelled: bool = False, cancelled_at: Optional[str] = None) -> BatchDownloadResult:
        return BatchDownloadResult(
            batch_id=batch_id,
            source_menu_url=collection.source_url if collection else menu_url,
            menu_id=collection.menu_id if collection else parse_naver_cafe_url(menu_url).menu_id,
            menu_title=collection.menu_title if collection else None,
            started_at=started_at,
            completed_at=datetime.now().astimezone().isoformat(),
            total_found=total,
            downloaded_count=len(downloaded_meta),
            skipped_count=len(skipped_urls),
            failed_count=len(failed_urls),
            downloaded_article_keys=downloaded_article_keys,
            failed_urls=failed_urls,
            skipped_urls=skipped_urls,
            downloaded_meta=downloaded_meta,
            menu_folder_path=str(menu_base_folder.resolve()),
            result_path=str(result_path.resolve()),
            failed_urls_path=str(failed_urls_path.resolve()),
            cancelled=cancelled,
            cancelled_at=cancelled_at,
            remaining_count=max(total - processed, 0),
        )

    try:
        check_cancelled(should_cancel, "메뉴 다운로드가 취소되었습니다.")
        collection = collect_menu_article_urls(
            menu_url,
            progress=progress,
            max_posts=max_posts,
            should_cancel=should_cancel,
        )
        menu_base_folder = create_menu_base_folder(collection.menu_id, collection.menu_title)
        total = len(collection.article_urls)
        emit_progress_value(progress_value, 0, total)
    except DownloadCancelledError:
        result = build_result(cancelled=True, cancelled_at=datetime.now().astimezone().isoformat())
        save_batch_result(result)
        raise

    with sync_playwright() as playwright:
        context: Optional[BrowserContext] = None
        try:
            context = create_browser_context(playwright, headless=True)
            apply_saved_session_state(context)
            page = context.pages[0] if context.pages else context.new_page()

            for index, article_url in enumerate(collection.article_urls, start=1):
                try:
                    check_cancelled(should_cancel, "메뉴 다운로드가 취소되었습니다.")
                except DownloadCancelledError:
                    result = build_result(cancelled=True, cancelled_at=datetime.now().astimezone().isoformat())
                    save_batch_result(result)
                    raise
                parsed_article = parse_naver_cafe_url(article_url)
                article_key = make_article_key(
                    club_id=parsed_article.club_id,
                    article_id=parsed_article.article_id,
                    cafe_name=parsed_article.cafe_name,
                    source_url=parsed_article.normalized_url,
                )

                if skip_existing and article_key and article_key in existing_keys:
                    emit(progress, f"이미 저장된 게시글 스킵: {article_url}")
                    skipped_urls.append(article_url)
                    processed = index
                    emit_progress_value(progress_value, processed, total)
                    continue

                emit(progress, f"게시글 {index}/{total} 처리 중...")
                try:
                    try:
                        meta = _download_post_with_context(
                            context=context,
                            page=page,
                            parsed_url=parsed_article,
                            progress=progress,
                            confirm_existing_folder=None,
                            destination_base_dir=menu_base_folder,
                            source_menu_url=collection.source_url,
                            menu_id=collection.menu_id,
                            menu_title=collection.menu_title,
                            batch_id=batch_id,
                            should_cancel=should_cancel,
                            save_state_after=False,
                        )
                    except AccessRequiredError:
                        if context is not None:
                            context.close()
                        context = create_browser_context(playwright, headless=False)
                        apply_saved_session_state(context)
                        page = context.pages[0] if context.pages else context.new_page()
                        meta = _download_post_with_context(
                            context=context,
                            page=page,
                            parsed_url=parsed_article,
                            progress=progress,
                            confirm_existing_folder=None,
                            destination_base_dir=menu_base_folder,
                            source_menu_url=collection.source_url,
                            menu_id=collection.menu_id,
                            menu_title=collection.menu_title,
                            batch_id=batch_id,
                            should_cancel=should_cancel,
                            save_state_after=False,
                        )
                    downloaded_meta.append(meta)
                    upsert_archive_entry(make_index_entry(meta))
                    saved_key = str(meta.get("article_key") or article_key)
                    if saved_key:
                        existing_keys.add(saved_key)
                        downloaded_article_keys.append(saved_key)
                except DownloadCancelledError:
                    processed = index - 1
                    result = build_result(cancelled=True, cancelled_at=datetime.now().astimezone().isoformat())
                    save_batch_result(result)
                    raise DownloadCancelledError("메뉴 다운로드가 취소되었습니다.")
                except Exception as exc:
                    debug_folder = ""
                    if isinstance(exc, PostDownloadError) and exc.debug_folder is not None:
                        debug_folder = str(exc.debug_folder.resolve())
                    emit(progress, f"실패: {article_url}")
                    failed_urls.append({"url": article_url, "reason": str(exc), "debug_folder": debug_folder})
                finally:
                    if processed < index:
                        processed = index
                    emit_progress_value(progress_value, processed, total)

                if index < total:
                    delay_until = time.monotonic() + random.uniform(*BATCH_POST_DELAY_RANGE)
                    while time.monotonic() < delay_until:
                        try:
                            check_cancelled(should_cancel, "메뉴 다운로드가 취소되었습니다.")
                        except DownloadCancelledError:
                            result = build_result(cancelled=True, cancelled_at=datetime.now().astimezone().isoformat())
                            save_batch_result(result)
                            raise
                        time.sleep(0.2)
        finally:
            if context is not None:
                try:
                    save_session_state(context)
                except Exception:
                    pass
                context.close()

    result = build_result()
    save_batch_result(result)
    emit(
        progress,
        f"메뉴 다운로드 완료: 다운로드 {result.downloaded_count}, 스킵 {result.skipped_count}, 실패 {result.failed_count}",
    )
    return result
