from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from playwright.sync_api import Browser, BrowserContext, Frame, Locator, Page, Playwright, Response, TimeoutError, sync_playwright

try:
    from bs4 import BeautifulSoup, Tag as BeautifulSoupTag
except ModuleNotFoundError:
    BeautifulSoup = None
    BeautifulSoupTag = None

try:
    import browser_cookie3
except ModuleNotFoundError:
    browser_cookie3 = None


USER_DATA_DIR = Path("./browser_profile")
SAVED_POSTS_DIR = Path("./saved_posts")
DEBUG_DIR = SAVED_POSTS_DIR / "_debug"
DEFAULT_CDP_PORT = 9222
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
)

# 네이버 카페는 구형/신형 에디터와 모바일/PC URL에 따라 본문 DOM이 다르게 렌더링됩니다.
# 흔한 컨테이너부터 검사하고, 마지막에 body를 fallback으로 사용합니다.
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
    "body",
)

LOGIN_PROMPT_MESSAGE = (
    "\ub124\uc774\ubc84 \ub85c\uadf8\uc778 \ub610\ub294 \uce74\ud398 \uc811\uadfc \uad8c\ud55c\uc774 "
    "\ud544\uc694\ud55c \uae00\uc77c \uc218 \uc788\uc2b5\ub2c8\ub2e4. \uc5f4\ub9b0 \ube0c\ub77c\uc6b0\uc800"
    "\uc5d0\uc11c \ub85c\uadf8\uc778/\uce74\ud398 \uc811\uadfc\uc744 \uc644\ub8cc\ud55c \ub4a4 Enter\ub97c "
    "\ub20c\ub7ec\uc8fc\uc138\uc694."
)
ACCESS_DENIED_MESSAGE = (
    "\ud604\uc7ac \ub85c\uadf8\uc778 \uc138\uc158\uc73c\ub85c\ub294 \uc774 \uce74\ud398 \uae00\uc744 \ubcfc \uc218 "
    "\uc5c6\uc2b5\ub2c8\ub2e4. \uce74\ud398 \uac00\uc785 \uc5ec\ubd80 \ub610\ub294 \uac8c\uc2dc\ud310 \uad8c\ud55c"
    "\uc744 \ud655\uc778\ud574\uc8fc\uc138\uc694."
)

BAD_TITLE_VALUES = {
    "\ube14\ub85c\uadf8 \uc811\uc18d \ubd88\uac00",
    "\ub124\uc774\ubc84 \uce74\ud398",
    "NAVER CAFE",
}

ACCESS_KEYWORDS = (
    "\ub85c\uadf8\uc778",
    "\uc811\uadfc \uad8c\ud55c",
    "\uad8c\ud55c\uc774 \uc5c6\uc2b5\ub2c8\ub2e4",
    "\uce74\ud398 \uac00\uc785",
    "\uba64\ubc84\ub9cc",
    "\ube44\uacf5\uac1c",
    "\uac8c\uc2dc\ud310 \uad8c\ud55c",
    "\uc5f4\ub78c \uad8c\ud55c",
)

TargetPage = Page | Frame


@dataclass
class ParsedCafeUrl:
    original_url: str
    normalized_url: str
    cafe_name: Optional[str]
    club_id: Optional[str]
    article_id: Optional[str]


@dataclass
class ExtractionResult:
    # 추출 결과와 실제로 사용된 selector를 함께 보관해 디버그/메타데이터에서 원인을 추적하기 쉽게 합니다.
    title: str
    body_text: str
    body_html: str
    image_urls: list[str]
    final_url: str
    used_iframe: bool
    iframe_name: Optional[str]
    access_status: str
    title_selector: str
    body_selector: str


@dataclass
class BrowserSession:
    context: BrowserContext
    page: Page
    browser: Optional[Browser] = None
    browser_process: Optional[subprocess.Popen] = None
    close_context: bool = True

    def close(self) -> None:
        if self.close_context:
            self.context.close()


class AccessDeniedError(RuntimeError):
    pass


class BrowserStartupError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save a single Naver Cafe post")
    parser.add_argument("--url", help="Naver Cafe post URL")
    parser.add_argument(
        "--current-browser",
        action="store_true",
        help="Open the URL in your normal browser and extract from a saved HTML file",
    )
    parser.add_argument(
        "--automation",
        action="store_true",
        help="Use Playwright automation extraction instead of current-browser saved HTML mode",
    )
    parser.add_argument(
        "--manual-html",
        action="store_true",
        help="Open the URL in your normal browser, then extract from a manually saved HTML file",
    )
    parser.add_argument(
        "--no-cookie-import",
        action="store_true",
        help="Do not import Naver cookies from Chrome/Edge",
    )
    parser.add_argument(
        "--cookie-browser",
        choices=("chrome", "msedge"),
        default="chrome",
        help="Browser profile to read Naver cookies from. Default: chrome",
    )
    parser.add_argument(
        "--browser",
        choices=("chrome", "chromium", "msedge"),
        default="chrome",
        help="Browser to launch. Default: chrome",
    )
    parser.add_argument(
        "--user-data-dir",
        default=str(USER_DATA_DIR),
        help="Persistent browser profile folder. Default: ./browser_profile",
    )
    parser.add_argument(
        "--connect-cdp",
        help="Connect to an already-running Chrome over CDP, for example http://127.0.0.1:9222",
    )
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=DEFAULT_CDP_PORT,
        help="Local debugging port for Chrome/Edge CDP mode. Default: 9222",
    )
    parser.add_argument(
        "--playwright-managed-browser",
        action="store_true",
        help="Use Playwright's managed browser launch. This may show the automation banner.",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Open Naver login page using the saved browser profile, then exit",
    )
    return parser.parse_args()


def info(message: str) -> None:
    print(message)


def warn(message: str) -> None:
    print(message)


def prompt_for_url() -> str:
    while True:
        value = input("\ub124\uc774\ubc84 \uce74\ud398 URL\uc744 \uc785\ub825\ud558\uc138\uc694: ").strip()
        if value:
            return value
        warn("URL\uc774 \ube44\uc5b4 \uc788\uc2b5\ub2c8\ub2e4. \ub2e4\uc2dc \uc785\ub825\ud574\uc8fc\uc138\uc694.")


def parse_naver_cafe_url(url: str) -> ParsedCafeUrl:
    # PC 구형 URL, ca-fe URL, 모바일 URL에서 cafe_name/club_id/article_id를 최대한 뽑아냅니다.
    # 이후 최종 이동 URL과 합쳐 메타데이터를 보강합니다.
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    query = parse_qs(parsed.query)

    cafe_name: Optional[str] = None
    club_id: Optional[str] = None
    article_id: Optional[str] = None

    club_id = first_query_value(query, "clubid", "clubId")
    article_id = first_query_value(query, "articleid", "articleId")

    path_parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.lower() in {"cafe.naver.com", "m.cafe.naver.com"}:
        if len(path_parts) >= 2 and path_parts[0].lower() not in {"articleread.nhn", "ca-fe"}:
            cafe_name = path_parts[0]
            if article_id is None and path_parts[1].isdigit():
                article_id = path_parts[1]

        if "cafes" in path_parts and "articles" in path_parts:
            try:
                club_index = path_parts.index("cafes")
                article_index = path_parts.index("articles")
                club_id = club_id or path_parts[club_index + 1]
                article_id = article_id or path_parts[article_index + 1]
            except (IndexError, ValueError):
                pass

    normalized_url = parsed.geturl() if parsed.scheme and parsed.netloc else cleaned
    return ParsedCafeUrl(
        original_url=cleaned,
        normalized_url=normalized_url,
        cafe_name=cafe_name,
        club_id=club_id,
        article_id=article_id,
    )


def first_query_value(query: dict[str, list[str]], *keys: str) -> Optional[str]:
    for key in keys:
        values = query.get(key)
        if values:
            return values[0]
    return None


def merge_parsed_urls(primary: ParsedCafeUrl, secondary: ParsedCafeUrl) -> ParsedCafeUrl:
    return ParsedCafeUrl(
        original_url=primary.original_url,
        normalized_url=primary.normalized_url,
        cafe_name=primary.cafe_name or secondary.cafe_name,
        club_id=primary.club_id or secondary.club_id,
        article_id=primary.article_id or secondary.article_id,
    )


def create_browser_context(playwright: Playwright, args: argparse.Namespace) -> BrowserContext:
    user_data_dir = Path(args.user_data_dir)
    user_data_dir.mkdir(parents=True, exist_ok=True)

    launch_options: dict[str, Any] = {
        "user_data_dir": str(user_data_dir),
        "headless": False,
        "viewport": {"width": 1440, "height": 960},
    }

    if args.browser != "chromium":
        launch_options["channel"] = args.browser

    try:
        return playwright.chromium.launch_persistent_context(**launch_options)
    except Exception:
        if args.browser == "chromium":
            raise

        warn(
            "\uc124\uce58\ub41c Chrome/Edge\ub97c \uc5f4 \uc218 \uc5c6\uc5b4 "
            "Playwright Chromium\uc73c\ub85c \ub2e4\uc2dc \uc2dc\ub3c4\ud569\ub2c8\ub2e4."
        )
        launch_options.pop("channel", None)
        return playwright.chromium.launch_persistent_context(**launch_options)


def find_installed_browser(browser_name: str) -> Path:
    candidates: list[Path] = []

    if browser_name == "chrome":
        candidates = [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
        ]
    elif browser_name == "msedge":
        candidates = [
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path.home() / r"AppData\Local\Microsoft\Edge\Application\msedge.exe",
        ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise BrowserStartupError(
        f"{browser_name} \uc2e4\ud589 \ud30c\uc77c\uc744 \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. "
        "--browser chromium \uc635\uc158\uc73c\ub85c \ub2e4\uc2dc \uc2dc\ub3c4\ud558\uac70\ub098, Chrome/Edge\ub97c \uc124\uce58\ud574\uc8fc\uc138\uc694."
    )


def cdp_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def is_cdp_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url(port)}/json/version", timeout=1):
            return True
    except Exception:
        return False


def wait_for_cdp(port: int, timeout_seconds: int = 12) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_cdp_ready(port):
            return True
        time.sleep(0.3)
    return False


def launch_browser_for_cdp(args: argparse.Namespace) -> subprocess.Popen:
    browser_path = find_installed_browser(args.browser)
    user_data_dir = Path(args.user_data_dir)
    user_data_dir.mkdir(parents=True, exist_ok=True)

    return subprocess.Popen(
        [
            str(browser_path),
            f"--remote-debugging-port={args.cdp_port}",
            f"--user-data-dir={user_data_dir.resolve()}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_browser_cookie3_installed() -> None:
    if browser_cookie3 is None:
        raise RuntimeError(
            "browser-cookie3\uac00 \uc124\uce58\ub418\uc5b4 \uc788\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. "
            "\uc2e4\ud589\ud558\uae30.bat\uc5d0\uc11c 1\ubc88 First install\uc744 \ub2e4\uc2dc \uc2e4\ud589\ud574\uc8fc\uc138\uc694."
        )


def load_naver_cookies_from_browser(browser_name: str) -> list[dict[str, Any]]:
    ensure_browser_cookie3_installed()

    # browser_cookie3가 평소 브라우저 프로필의 쿠키 저장소를 읽고 복호화합니다.
    # Playwright 컨텍스트에 넣을 수 있도록 필요한 필드만 dict 형태로 변환합니다.
    if browser_name == "msedge":
        cookie_jar = browser_cookie3.edge(domain_name="naver.com")
    else:
        cookie_jar = browser_cookie3.chrome(domain_name="naver.com")

    cookies: list[dict[str, Any]] = []
    for cookie in cookie_jar:
        if not cookie.name or cookie.value is None:
            continue
        domain = cookie.domain or ".naver.com"
        if "naver.com" not in domain:
            continue
        cookies.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": domain,
                "path": cookie.path or "/",
                "expires": int(cookie.expires) if cookie.expires else -1,
                "secure": bool(cookie.secure),
            }
        )
    return cookies


def import_naver_cookies(context: BrowserContext, args: argparse.Namespace) -> None:
    if args.no_cookie_import:
        return

    try:
        # 쿠키 읽기 실패는 치명 오류로 막지 않습니다.
        # 사용자가 열린 브라우저에서 직접 로그인할 수 있도록 경고만 출력합니다.
        cookies = load_naver_cookies_from_browser(args.cookie_browser)
        if not cookies:
            warn(
                "\ud3c9\uc18c \ube0c\ub77c\uc6b0\uc800\uc5d0\uc11c \ub124\uc774\ubc84 \ub85c\uadf8\uc778 \ucfe0\ud0a4\ub97c "
                "\ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. \ub85c\uadf8\uc778\uc774 \ud544\uc694\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4."
            )
            return
        context.add_cookies(cookies)
        info(f"\ud3c9\uc18c \ube0c\ub77c\uc6b0\uc800\uc758 \ub124\uc774\ubc84 \ucfe0\ud0a4 {len(cookies)}\uac1c\ub97c \uc801\uc6a9\ud588\uc2b5\ub2c8\ub2e4.")
    except Exception as exc:
        warn(
            "\ud3c9\uc18c \ube0c\ub77c\uc6b0\uc800\uc758 \ub124\uc774\ubc84 \ub85c\uadf8\uc778 \ucfe0\ud0a4\ub97c "
            f"\uc77d\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4: {exc}"
        )


def create_browser_session(playwright: Playwright, args: argparse.Namespace) -> BrowserSession:
    # 기본은 일반 Chrome/Edge를 원격 디버깅 모드로 띄워 자동화 배너와 로그인 불편을 줄입니다.
    # 필요하면 이미 열려 있는 CDP 브라우저나 Playwright 관리 브라우저로도 동작합니다.
    if args.connect_cdp:
        info(
            "CDP\ub85c \uc774\ubbf8 \uc5f4\ub9b0 Chrome\uc5d0 \uc5f0\uacb0\ud558\ub294 \uc911..."
        )
        try:
            browser = playwright.chromium.connect_over_cdp(args.connect_cdp)
        except Exception as exc:
            raise BrowserStartupError(
                "Chrome \uc6d0\uaca9 \ub514\ubc84\uae45 \ud3ec\ud2b8\uc5d0 \uc5f0\uacb0\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.\n"
                "\uc544\ub798 \uc21c\uc11c\ub300\ub85c \ub2e4\uc2dc \uc2dc\ub3c4\ud574\uc8fc\uc138\uc694.\n"
                "1. \uc5f4\ub824 \uc788\ub294 Chrome \ucc3d\uc744 \ubaa8\ub450 \ub2eb\uc2b5\ub2c8\ub2e4.\n"
                "2. \uc791\uc5c5 \uad00\ub9ac\uc790\uc5d0 Chrome\uc774 \ub0a8\uc544 \uc788\uc73c\uba74 chrome.exe\ub97c \ubaa8\ub450 \uc885\ub8cc\ud569\ub2c8\ub2e4.\n"
                "3. \uc774 \ud3f4\ub354\uc758 open_chrome_debug.bat\ub97c \ub354\ube14\ud074\ub9ad\ud569\ub2c8\ub2e4.\n"
                "4. \uc5f4\ub9b0 Chrome \ucc3d\uc744 \ub2eb\uc9c0 \uc54a\uace0 \ub450\uc5b4\uc57c \ud569\ub2c8\ub2e4.\n"
                "5. \ub2e4\uc2dc \uc774 \uba85\ub839\uc744 \uc2e4\ud589\ud569\ub2c8\ub2e4.\n"
                f"\uc6d0\ubcf8 \uc624\ub958: {exc}"
            ) from exc
        if not browser.contexts:
            raise RuntimeError("CDP\ub85c \uc5f0\uacb0\ub41c Chrome\uc5d0 \uc0ac\uc6a9 \uac00\ub2a5\ud55c \ube0c\ub77c\uc6b0\uc800 \ud504\ub85c\ud544\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.")
        context = browser.contexts[0]
        import_naver_cookies(context, args)
        page = context.new_page()
        return BrowserSession(context=context, page=page, browser=browser, close_context=False)

    if not args.playwright_managed_browser and args.browser in {"chrome", "msedge"}:
        info("Chrome/Edge \uc77c\ubc18 \ub514\ubc84\uae45 \ubaa8\ub4dc\ub85c \ube0c\ub77c\uc6b0\uc800\ub97c \uc5ec\ub294 \uc911...")
        browser_process: Optional[subprocess.Popen] = None
        if not is_cdp_ready(args.cdp_port):
            browser_process = launch_browser_for_cdp(args)
            if not wait_for_cdp(args.cdp_port):
                raise BrowserStartupError(
                    "Chrome/Edge\ub97c \uc5f4\uc5c8\uc9c0\ub9cc \uc6d0\uaca9 \ub514\ubc84\uae45 \ud3ec\ud2b8\uc5d0 "
                    "\uc5f0\uacb0\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. \uc5f4\ub824 \uc788\ub294 Chrome/Edge \ucc3d\uc744 "
                    "\ubaa8\ub450 \ub2eb\uace0 \ub2e4\uc2dc \uc2e4\ud589\ud574\uc8fc\uc138\uc694."
                )

        browser = playwright.chromium.connect_over_cdp(cdp_url(args.cdp_port))
        if not browser.contexts:
            raise BrowserStartupError("CDP\ub85c \uc5f0\uacb0\ub41c \ube0c\ub77c\uc6b0\uc800 \ud504\ub85c\ud544\uc744 \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")
        context = browser.contexts[0]
        import_naver_cookies(context, args)
        page = context.new_page()
        return BrowserSession(
            context=context,
            page=page,
            browser=browser,
            browser_process=browser_process,
            close_context=False,
        )

    context = create_browser_context(playwright, args)
    import_naver_cookies(context, args)
    page = context.pages[0] if context.pages else context.new_page()
    return BrowserSession(context=context, page=page)


def open_post_page(page: Page, url: str) -> str:
    info("\uce74\ud398 \uac8c\uc2dc\uae00\uc744 \ubd88\ub7ec\uc624\ub294 \uc911...")
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except TimeoutError:
        warn("\ud398\uc774\uc9c0 \ub85c\ub529\uc774 \uae38\uc5b4\uc9c0\uace0 \uc788\uc5b4 \ud604\uc7ac \uc0c1\ud0dc\uc5d0\uc11c \uacc4\uc18d \uc9c4\ud589\ud569\ub2c8\ub2e4.")
    page.wait_for_timeout(1500)
    return page.url


def list_frames(page: Page) -> list[dict[str, str]]:
    frames: list[dict[str, str]] = []
    for frame in page.frames:
        frames.append(
            {
                "name": frame.name or "",
                "url": frame.url or "",
            }
        )
    return frames


def get_cafe_article_frame_or_page(
    page: Page,
    announce: bool = True,
) -> tuple[TargetPage, bool, Optional[str]]:
    # 네이버 카페 PC 페이지는 실제 글 본문이 cafe_main iframe 안에 들어가는 경우가 많습니다.
    # iframe이 없으면 모바일/ca-fe 페이지처럼 현재 page에서 바로 추출합니다.
    if announce:
        info("cafe_main iframe \ud655\uc778 \uc911...")

    for frame in page.frames:
        frame_name = (frame.name or "").strip()
        if frame_name.lower() == "cafe_main" or "cafe_main" in frame_name.lower():
            page.wait_for_timeout(500)
            return frame, True, frame_name

    for selector in ("iframe#cafe_main", "iframe[name='cafe_main']"):
        try:
            iframe_locator = page.locator(selector).first
            if iframe_locator.count() == 0:
                continue
            handle = iframe_locator.element_handle()
            frame = handle.content_frame() if handle else None
            if frame:
                page.wait_for_timeout(500)
                return frame, True, frame.name or "cafe_main"
        except Exception:
            continue

    return page, False, None


def get_host_page(target: TargetPage) -> Page:
    return target if isinstance(target, Page) else target.page


def get_target_url(target: TargetPage) -> str:
    if isinstance(target, Frame) and target.url and target.url != "about:blank":
        return target.url
    return get_host_page(target).url


def wait_for_article_content(target: TargetPage) -> None:
    host_page = get_host_page(target)

    for _ in range(20):
        if has_any_selector(target, TITLE_SELECTORS):
            return
        if has_any_selector(target, BODY_SELECTORS[:-1]):
            return
        host_page.wait_for_timeout(1000)

    body_locator = target.locator("body").first
    if body_locator.count() > 0:
        return

    raise RuntimeError("\ubcf8\ubb38 \uc601\uc5ed\uc744 \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")


def has_any_selector(target: TargetPage, selectors: Sequence[str]) -> bool:
    for selector in selectors:
        try:
            if target.locator(selector).first.count() > 0:
                return True
        except Exception:
            continue
    return False


def is_login_or_access_issue(page: Page, target: TargetPage) -> bool:
    # 로그인 페이지로 이동했거나, 본문/호스트 페이지에 권한 제한 문구가 보이면 재로그인 흐름으로 넘깁니다.
    if "nid.naver.com" in page.url.lower():
        return True

    login_selectors = (
        "input#id",
        "input[type='password']",
        "form[action*='nidlogin.login']",
        "button[type='submit']",
    )
    for selector in login_selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible(timeout=300):
                return True
        except Exception:
            continue

    target_text = ""
    try:
        target_text = clean_text(target.locator("body").first.inner_text(timeout=1500))
    except Exception:
        pass

    if looks_like_access_limited_text(target_text):
        return True

    page_text = ""
    try:
        page_text = clean_text(page.locator("body").first.inner_text(timeout=1500))
    except Exception:
        pass

    return looks_like_access_limited_text(page_text)


def looks_like_access_limited_text(text: str) -> bool:
    if not text:
        return False

    lowered = text.lower()
    return any(keyword in text for keyword in ACCESS_KEYWORDS) or "login" in lowered


def extract_title(target: TargetPage, parsed_url: ParsedCafeUrl) -> tuple[str, str]:
    # 제목 selector가 실패하면 브라우저 title을 사용하고, 그것도 부적절하면 URL 정보로 안전한 폴더명을 만듭니다.
    for selector in TITLE_SELECTORS:
        locator = target.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            text = clean_text(locator.inner_text(timeout=2000))
            if is_valid_title(text):
                return text, selector
        except Exception:
            continue

    fallback_title = clean_text(get_host_page(target).title())
    if is_valid_title(fallback_title):
        return fallback_title, "title"

    return build_fallback_title(parsed_url), "fallback"


def is_valid_title(title: str) -> bool:
    if not title:
        return False
    normalized = title.strip()
    lowered = normalized.lower()
    if normalized in BAD_TITLE_VALUES:
        return False
    if lowered in {"naver cafe", "cafe.naver.com"}:
        return False
    if "\ube14\ub85c\uadf8 \uc811\uc18d \ubd88\uac00" in normalized:
        return False
    if normalized.startswith("\ub124\uc774\ubc84 \uce74\ud398"):
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


def extract_body_container(target: TargetPage) -> tuple[Locator, str]:
    # body fallback은 마지막 수단입니다. 로그인/권한 안내 페이지를 본문으로 저장하지 않도록 한 번 더 걸러냅니다.
    for selector in BODY_SELECTORS:
        locator = target.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            text = clean_text(locator.inner_text(timeout=3000))
            html = get_outer_or_inner_html(locator)
            if selector == "body" and looks_like_access_limited_text(text):
                continue
            if text or html:
                return locator, selector
        except Exception:
            continue

    raise RuntimeError("\ubcf8\ubb38 \ucee8\ud14c\uc774\ub108\ub97c \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")


def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\t", " ")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    normalized = re.sub(r"[ ]{2,}", " ", normalized)
    return normalized.strip()


def extract_text(container: Locator) -> str:
    return clean_text(container.inner_text(timeout=5000))


def extract_html(container: Locator, base_url: str) -> str:
    raw_html = get_outer_or_inner_html(container)
    return (
        "<!doctype html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <base href=\"{html_escape(base_url)}\">\n"
        "  <title>Naver Cafe Saved Post</title>\n"
        "  <style>body{font-family:sans-serif;line-height:1.6;max-width:960px;margin:40px auto;padding:0 16px;}img{max-width:100%;height:auto;}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{raw_html}\n"
        "</body>\n"
        "</html>\n"
    )


def get_outer_or_inner_html(locator: Locator) -> str:
    try:
        return str(locator.evaluate("(node) => node.outerHTML"))
    except Exception:
        return locator.inner_html(timeout=3000)


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("\"", "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def parse_srcset(srcset: str, base_url: str) -> Optional[str]:
    candidates: list[str] = []
    for part in srcset.split(","):
        segment = part.strip()
        if not segment:
            continue
        url_part = segment.split()[0]
        if url_part:
            candidates.append(resolve_url(base_url, url_part))
    return candidates[-1] if candidates else None


def resolve_url(base_url: str, candidate: str) -> str:
    if candidate.startswith("//"):
        parsed = urlparse(base_url)
        scheme = parsed.scheme or "https"
        return f"{scheme}:{candidate}"
    return urljoin(base_url, candidate)


def extract_image_urls(container: Locator, base_url: str) -> list[str]:
    # 본문 이미지 후보를 srcset/data-* 속성까지 포함해 수집하되,
    # 아이콘/프로필/스티커 같은 장식 이미지는 저장 대상에서 제외합니다.
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

    results: list[str] = []
    seen: set[str] = set()

    for item in image_data:
        if not isinstance(item, dict):
            continue

        candidates: list[str] = []
        srcset = item.get("srcset")
        if isinstance(srcset, str) and srcset.strip():
            parsed_srcset = parse_srcset(srcset, base_url)
            if parsed_srcset:
                candidates.append(parsed_srcset)

        for key in ("dataLazySrc", "dataSrc", "dataOriginal", "src"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

        class_name = str(item.get("className", "")).lower()
        alt_text = str(item.get("alt", "")).lower()

        chosen: Optional[str] = None
        for candidate in candidates:
            if not candidate:
                continue
            lowered_candidate = candidate.lower()
            if lowered_candidate.startswith("data:") or lowered_candidate.startswith("blob:"):
                continue

            absolute = resolve_url(base_url, candidate)
            lowered_absolute = absolute.lower()
            if lowered_absolute.endswith(".svg"):
                continue
            if "ssl.pstatic.net/static" in lowered_absolute or "static.nid.naver.com" in lowered_absolute:
                continue
            if any(token in class_name for token in ("icon", "ico", "button", "profile", "sticker")):
                continue
            if any(token in alt_text for token in ("icon", "button", "profile", "sticker")):
                continue
            chosen = absolute
            break

        if not chosen or chosen in seen:
            continue
        seen.add(chosen)
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
    path_suffix = Path(urlparse(image_url).path).suffix.lower()
    if path_suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if path_suffix == ".jpeg" else path_suffix

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
    image_urls: Sequence[str],
    images_dir: Path,
    referer_url: str,
) -> tuple[list[str], list[dict[str, str]]]:
    # 이미지 서버가 referer를 검사하는 경우가 있어 게시글 URL을 함께 보내 다운로드합니다.
    images_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[str] = []
    failed_images: list[dict[str, str]] = []

    if image_urls:
        info(f"\uc774\ubbf8\uc9c0 {len(image_urls)}\uac1c \ub2e4\uc6b4\ub85c\ub4dc \uc911...")

    for index, image_url in enumerate(image_urls, start=1):
        try:
            response = context.request.get(
                image_url,
                headers={"Referer": referer_url},
                timeout=30000,
            )
            if not response.ok:
                failed_images.append({"url": image_url, "reason": f"HTTP {response.status}"})
                continue

            extension = extension_from_response(image_url, response)
            file_name = f"{index:03d}{extension}"
            file_path = images_dir / file_name
            file_path.write_bytes(response.body())
            saved_files.append(str(Path("images") / file_name))
        except Exception as exc:
            failed_images.append({"url": image_url, "reason": str(exc)})

    return saved_files, failed_images


def save_content_files(folder: Path, text: str, html: str, meta: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "content.txt").write_text(text, encoding="utf-8")
    (folder / "content.html").write_text(html, encoding="utf-8")
    (folder / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def save_debug_files(page: Page, info_data: dict[str, Any]) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    screenshot_path = DEBUG_DIR / "debug_screenshot.png"
    html_path = DEBUG_DIR / "debug_page.html"
    info_path = DEBUG_DIR / "debug_info.json"

    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
    except Exception as exc:
        info_data["debug_screenshot_error"] = str(exc)

    try:
        html_path.write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        info_data["debug_html_error"] = str(exc)

    info_path.write_text(
        json.dumps(info_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def open_in_current_browser(url: str) -> None:
    if os.name == "nt":
        os.startfile(url)  # type: ignore[attr-defined]
        return

    opener = "open" if os.name == "posix" else "xdg-open"
    subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def prompt_for_saved_html_path() -> Path:
    while True:
        value = input("\uc800\uc7a5\ud55c HTML \ud30c\uc77c \uacbd\ub85c\ub97c \ubd99\uc5ec\ub123\uace0 Enter\ub97c \ub20c\ub7ec\uc8fc\uc138\uc694: ").strip().strip('"')
        html_path = Path(value)
        if html_path.exists() and html_path.is_file():
            return html_path
        warn("\ud30c\uc77c\uc744 \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. Chrome\uc5d0\uc11c Ctrl+S\ub85c \uc800\uc7a5\ud55c .html \ud30c\uc77c \uacbd\ub85c\ub97c \ub2e4\uc2dc \ub123\uc5b4\uc8fc\uc138\uc694.")


def read_saved_html(html_path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return html_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return html_path.read_text(encoding="utf-8", errors="replace")


def ensure_beautifulsoup_installed() -> None:
    if BeautifulSoup is None or BeautifulSoupTag is None:
        raise RuntimeError(
            "beautifulsoup4\uac00 \uc124\uce58\ub418\uc5b4 \uc788\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4. "
            "\uc2e4\ud589\ud558\uae30.bat\uc5d0\uc11c 1\ubc88 First install\uc744 \ub2e4\uc2dc \uc2e4\ud589\ud574\uc8fc\uc138\uc694."
        )


def extract_title_from_soup(soup: Any, parsed_url: ParsedCafeUrl) -> tuple[str, str]:
    for selector in TITLE_SELECTORS:
        element = soup.select_one(selector)
        if not element:
            continue
        title = clean_text(element.get_text("\n"))
        if is_valid_title(title):
            return title, selector

    if soup.title:
        title = clean_text(soup.title.get_text("\n"))
        if is_valid_title(title):
            return title, "title"

    return build_fallback_title(parsed_url), "fallback"


def extract_body_from_soup(soup: Any) -> tuple[Any, str]:
    for selector in BODY_SELECTORS:
        element = soup.select_one(selector)
        if not isinstance(element, BeautifulSoupTag):
            continue
        text = clean_text(element.get_text("\n"))
        if selector == "body" and looks_like_access_limited_text(text):
            continue
        if text or str(element).strip():
            return element, selector

    body = soup.body
    if isinstance(body, BeautifulSoupTag):
        return body, "body"

    raise RuntimeError("\ubcf8\ubb38 \ucee8\ud14c\uc774\ub108\ub97c \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")


def wrap_manual_html(raw_html: str, base_url: str) -> str:
    return (
        "<!doctype html>\n"
        "<html lang=\"ko\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"  <base href=\"{html_escape(base_url)}\">\n"
        "  <title>Naver Cafe Saved Post</title>\n"
        "  <style>body{font-family:sans-serif;line-height:1.6;max-width:960px;margin:40px auto;padding:0 16px;}img{max-width:100%;height:auto;}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{raw_html}\n"
        "</body>\n"
        "</html>\n"
    )


def resolve_saved_image_reference(candidate: str, html_path: Path, base_url: str) -> Optional[str]:
    # Ctrl+S 저장 HTML은 이미지 경로가 로컬 파일, file:// URL, 상대 경로, 원격 URL로 섞일 수 있습니다.
    # 다운로드/복사 단계에서 동일하게 처리할 수 있도록 실제 로컬 경로나 절대 URL로 정규화합니다.
    candidate = candidate.strip()
    if not candidate:
        return None

    lowered = candidate.lower()
    if lowered.startswith("data:") or lowered.startswith("blob:"):
        return None
    if re.match(r"^[a-zA-Z]:[\\/]", candidate):
        return str(Path(candidate))
    if candidate.startswith("//"):
        return f"https:{candidate}"

    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        return candidate
    if parsed.scheme == "file":
        file_path = unquote(parsed.path)
        if re.match(r"^/[a-zA-Z]:/", file_path):
            file_path = file_path[1:]
        return str(Path(file_path))

    local_part = unquote(parsed.path or candidate)
    local_path = (html_path.parent / local_part).resolve()
    if local_path.exists():
        return str(local_path)
    return urljoin(base_url, candidate)


def extract_image_refs_from_soup(container: Any, html_path: Path, base_url: str) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for image in container.select("img"):
        class_name = " ".join(image.get("class", [])).lower() if isinstance(image.get("class"), list) else str(image.get("class", "")).lower()
        alt_text = str(image.get("alt", "")).lower()
        if any(token in class_name for token in ("icon", "ico", "button", "profile", "sticker")):
            continue
        if any(token in alt_text for token in ("icon", "button", "profile", "sticker")):
            continue

        candidates: list[str] = []
        srcset = image.get("srcset")
        if isinstance(srcset, str) and srcset.strip():
            srcset_candidate = parse_srcset(srcset, base_url)
            if srcset_candidate:
                candidates.append(srcset_candidate)

        for key in ("data-lazy-src", "data-src", "data-original", "src"):
            value = image.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

        chosen: Optional[str] = None
        for candidate in candidates:
            resolved = resolve_saved_image_reference(candidate, html_path, base_url)
            if not resolved:
                continue
            lowered = resolved.lower()
            if lowered.endswith(".svg"):
                continue
            if "ssl.pstatic.net/static" in lowered or "static.nid.naver.com" in lowered:
                continue
            chosen = resolved
            break

        if chosen and chosen not in seen:
            seen.add(chosen)
            results.append(chosen)

    return results


def extension_from_source(source: str, content_type: Optional[str] = None) -> str:
    suffix = Path(urlparse(source).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix

    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    if content_type:
        return mapping.get(content_type.split(";")[0].strip().lower(), ".jpg")
    return ".jpg"


def save_manual_images(
    image_refs: Sequence[str],
    images_dir: Path,
    referer_url: str,
) -> tuple[list[str], list[dict[str, str]]]:
    images_dir.mkdir(parents=True, exist_ok=True)
    saved_files: list[str] = []
    failed_images: list[dict[str, str]] = []

    if image_refs:
        info(f"\uc774\ubbf8\uc9c0 {len(image_refs)}\uac1c \uc800\uc7a5 \uc911...")

    for index, image_ref in enumerate(image_refs, start=1):
        try:
            parsed = urlparse(image_ref)
            if parsed.scheme in {"http", "https"}:
                request = urllib.request.Request(
                    image_ref,
                    headers={
                        "Referer": referer_url,
                        "User-Agent": "Mozilla/5.0",
                    },
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = response.read()
                    extension = extension_from_source(image_ref, response.headers.get("content-type"))
                file_name = f"{index:03d}{extension}"
                (images_dir / file_name).write_bytes(body)
            else:
                source_path = Path(image_ref)
                if not source_path.exists():
                    failed_images.append({"url": image_ref, "reason": "local file not found"})
                    continue
                extension = extension_from_source(str(source_path))
                file_name = f"{index:03d}{extension}"
                shutil.copyfile(source_path, images_dir / file_name)

            saved_files.append(str(Path("images") / file_name))
        except Exception as exc:
            failed_images.append({"url": image_ref, "reason": str(exc)})

    return saved_files, failed_images


def extract_from_saved_html(
    html_path: Path,
    parsed_url: ParsedCafeUrl,
) -> ExtractionResult:
    ensure_beautifulsoup_installed()
    html = read_saved_html(html_path)
    soup = BeautifulSoup(html, "html.parser")
    title, title_selector = extract_title_from_soup(soup, parsed_url)
    container, body_selector = extract_body_from_soup(soup)
    body_text = clean_text(container.get_text("\n"))
    if not body_text:
        raise RuntimeError("\ubcf8\ubb38 \ud14d\uc2a4\ud2b8\ub97c \ucd94\ucd9c\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")

    image_refs = extract_image_refs_from_soup(container, html_path, parsed_url.normalized_url)
    body_html = wrap_manual_html(str(container), parsed_url.normalized_url)

    return ExtractionResult(
        title=title,
        body_text=body_text,
        body_html=body_html,
        image_urls=image_refs,
        final_url=parsed_url.normalized_url,
        used_iframe=False,
        iframe_name=None,
        access_status="saved_from_current_browser",
        title_selector=title_selector,
        body_selector=body_selector,
    )


def run_current_browser_mode(args: argparse.Namespace) -> int:
    # 자동화 추출이 막힐 때 쓰는 예비 모드입니다.
    # 사용자가 평소 브라우저에서 Ctrl+S로 저장한 HTML을 정리해 같은 형식으로 저장합니다.
    url = args.url or prompt_for_url()
    parsed_url = parse_naver_cafe_url(url)
    SAVED_POSTS_DIR.mkdir(parents=True, exist_ok=True)

    print("\ud604\uc7ac \uc0ac\uc6a9 \uc911\uc778 \ube0c\ub77c\uc6b0\uc800\ub85c \uce74\ud398 \uae00\uc744 \uc5fd\ub2c8\ub2e4.")
    open_in_current_browser(parsed_url.normalized_url)
    print("\ube0c\ub77c\uc6b0\uc800\uc5d0\uc11c \uae00\uc774 \ubcf4\uc774\uba74 Ctrl+S\ub97c \ub20c\ub7ec HTML\ub85c \uc800\uc7a5\ud574\uc8fc\uc138\uc694.")
    print("\uc800\uc7a5 \ud615\uc2dd\uc740 \uac00\ub2a5\ud558\uba74 '\uc6f9\ud398\uc774\uc9c0, \uc804\uccb4'\ub97c \uc120\ud0dd\ud574\uc8fc\uc138\uc694.")
    html_path = prompt_for_saved_html_path()

    try:
        result = extract_from_saved_html(html_path, parsed_url)
        folder = create_unique_folder(SAVED_POSTS_DIR, result.title)
        image_files, failed_images = save_manual_images(
            image_refs=result.image_urls,
            images_dir=folder / "images",
            referer_url=result.final_url,
        )
        meta = build_meta(parsed_url, result, image_files, failed_images)
        meta["source_mode"] = "current_browser_saved_html"
        meta["saved_html_path"] = str(html_path)
        save_content_files(folder, result.body_text, result.body_html, meta)
        info("\ubcf8\ubb38 \uc800\uc7a5 \uc644\ub8cc")
        if failed_images:
            info(f"\uc77c\ubd80 \uc774\ubbf8\uc9c0 \uc800\uc7a5 \uc2e4\ud328: {len(failed_images)}\uac1c")
        info(f"\uc800\uc7a5 \uc644\ub8cc: {folder}")
        return 0
    except Exception as exc:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (DEBUG_DIR / "debug_info.json").write_text(
            json.dumps(
                {
                    "error": str(exc),
                    "source_url": parsed_url.original_url,
                    "saved_html_path": str(html_path),
                    "title_selectors_tried": list(TITLE_SELECTORS),
                    "body_selectors_tried": list(BODY_SELECTORS),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(str(exc))
        print("\uc800\uc7a5\ud55c HTML\uc5d0\uc11c \uac8c\uc2dc\uae00 \ucd94\ucd9c\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4. saved_posts/_debug \ud3f4\ub354\ub97c \ud655\uc778\ud574\uc8fc\uc138\uc694.")
        return 1


def build_debug_info(page: Page, error_message: str) -> dict[str, Any]:
    # 실패 시 현재 URL, iframe 목록, 시도한 selector를 남겨 네이버 DOM 변경 여부를 빠르게 확인합니다.
    frames = list_frames(page)
    target, used_iframe, iframe_name = get_cafe_article_frame_or_page(page, announce=False)
    return {
        "error": error_message,
        "current_url": page.url,
        "final_url": get_target_url(target),
        "cafe_main_detected": used_iframe,
        "iframe_name": iframe_name,
        "frames": frames,
        "title_selectors_tried": list(TITLE_SELECTORS),
        "body_selectors_tried": list(BODY_SELECTORS),
    }


def extract_current_post(page: Page, parsed_url: ParsedCafeUrl, access_status: str) -> ExtractionResult:
    # 자동화 모드의 핵심 추출 단계입니다. iframe 탐지, 본문 대기, 텍스트/HTML/이미지 후보 수집을 한 번에 수행합니다.
    target, used_iframe, iframe_name = get_cafe_article_frame_or_page(page)
    info(f"iframe \uc0ac\uc6a9 \uc5ec\ubd80: {str(used_iframe).lower()}")

    wait_for_article_content(target)
    title, title_selector = extract_title(target, parsed_url)
    container, body_selector = extract_body_container(target)
    body_text = extract_text(container)

    if not body_text:
        raise RuntimeError("\ubcf8\ubb38 \ud14d\uc2a4\ud2b8\ub97c \ucd94\ucd9c\ud558\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.")

    final_url = get_target_url(target)
    body_html = extract_html(container, final_url)
    image_urls = extract_image_urls(container, final_url)

    info(f"\uc81c\ubaa9 \ucd94\ucd9c \uc644\ub8cc: {title}")
    return ExtractionResult(
        title=title,
        body_text=body_text,
        body_html=body_html,
        image_urls=image_urls,
        final_url=final_url,
        used_iframe=used_iframe,
        iframe_name=iframe_name,
        access_status=access_status,
        title_selector=title_selector,
        body_selector=body_selector,
    )


def load_and_extract(page: Page, parsed_url: ParsedCafeUrl) -> ExtractionResult:
    open_post_page(page, parsed_url.normalized_url)

    try:
        return extract_current_post(page, parsed_url, "accessible")
    except Exception as first_error:
        # 첫 추출 실패가 로그인/권한 문제로 보일 때만 사용자 로그인 후 재시도합니다.
        # selector 변경 같은 일반 추출 오류는 원래 예외를 유지해야 디버그가 쉬워집니다.
        target, _, _ = get_cafe_article_frame_or_page(page)
        if not is_login_or_access_issue(page, target):
            raise first_error

        print(LOGIN_PROMPT_MESSAGE)
        input()
        open_post_page(page, parsed_url.normalized_url)

        try:
            return extract_current_post(page, parsed_url, "retried_after_login")
        except Exception as second_error:
            target, _, _ = get_cafe_article_frame_or_page(page)
            if is_login_or_access_issue(page, target):
                raise AccessDeniedError(ACCESS_DENIED_MESSAGE) from second_error
            raise second_error


def build_meta(
    parsed_url: ParsedCafeUrl,
    result: ExtractionResult,
    image_files: Sequence[str],
    failed_images: Sequence[dict[str, str]],
) -> dict[str, Any]:
    # meta.json은 저장 결과 검증용입니다. 어떤 URL/selector/권한 상태에서 저장됐는지 함께 남깁니다.
    return {
        "source_url": parsed_url.original_url,
        "final_url": result.final_url,
        "cafe_name": parsed_url.cafe_name,
        "club_id": parsed_url.club_id,
        "article_id": parsed_url.article_id,
        "title": result.title,
        "saved_at": datetime.now().astimezone().isoformat(),
        "body_text_length": len(result.body_text),
        "image_count": len(image_files),
        "image_files": list(image_files),
        "failed_images": list(failed_images),
        "used_iframe": result.used_iframe,
        "iframe_name": result.iframe_name,
        "access_status": result.access_status,
        "selectors_used": {
            "title": result.title_selector,
            "body": result.body_selector,
        },
    }


def run_login_only(args: argparse.Namespace) -> int:
    info("\ub124\uc774\ubc84 \ub85c\uadf8\uc778 \uc804\uc6a9 \ucc3d\uc744 \uc5ec\ub294 \uc911...")
    with sync_playwright() as playwright:
        session: Optional[BrowserSession] = None
        try:
            session = create_browser_session(playwright, args)
            page = session.page
            page.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded", timeout=60000)
            print(
                "\uc5f4\ub9b0 \ube0c\ub77c\uc6b0\uc800\uc5d0\uc11c \ub124\uc774\ubc84 \ub85c\uadf8\uc778\uc744 "
                "\uc644\ub8cc\ud55c \ub4a4, \uc774 \ud130\ubbf8\ub110\uc5d0\uc11c Enter\ub97c \ub20c\ub7ec\uc8fc\uc138\uc694."
            )
            input()
            page.goto("https://www.naver.com", wait_until="domcontentloaded", timeout=60000)
            print("\ub85c\uadf8\uc778 \ud504\ub85c\ud544 \uc800\uc7a5\uc744 \uc644\ub8cc\ud588\uc2b5\ub2c8\ub2e4.")
            return 0
        except BrowserStartupError as exc:
            print(str(exc))
            return 1
        except Exception as exc:
            print(f"\ub85c\uadf8\uc778 \ucc3d\uc744 \uc5ec\ub294 \uc911 \uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4: {exc}")
            return 1
        finally:
            if session is not None:
                session.close()


def main() -> int:
    args = parse_args()
    if args.login_only:
        return run_login_only(args)
    if args.current_browser or args.manual_html:
        return run_current_browser_mode(args)

    url = args.url or prompt_for_url()
    parsed_url = parse_naver_cafe_url(url)
    SAVED_POSTS_DIR.mkdir(parents=True, exist_ok=True)

    info("\ube0c\ub77c\uc6b0\uc800\ub97c \uc5ec\ub294 \uc911...")

    with sync_playwright() as playwright:
        session: Optional[BrowserSession] = None
        try:
            session = create_browser_session(playwright, args)
            context = session.context
            page = session.page
            result = load_and_extract(page, parsed_url)
            enriched = merge_parsed_urls(parsed_url, parse_naver_cafe_url(result.final_url))

            folder = create_unique_folder(SAVED_POSTS_DIR, result.title)
            images_dir = folder / "images"
            image_files, failed_images = download_images(
                context=context,
                image_urls=result.image_urls,
                images_dir=images_dir,
                referer_url=result.final_url,
            )

            meta = build_meta(enriched, result, image_files, failed_images)
            save_content_files(folder, result.body_text, result.body_html, meta)

            info("\ubcf8\ubb38 \uc800\uc7a5 \uc644\ub8cc")
            if failed_images:
                info(f"\uc77c\ubd80 \uc774\ubbf8\uc9c0 \ub2e4\uc6b4\ub85c\ub4dc \uc2e4\ud328: {len(failed_images)}\uac1c")
            info(f"\uc800\uc7a5 \uc644\ub8cc: {folder}")
            return 0

        except BrowserStartupError as exc:
            print(str(exc))
            return 1
        except AccessDeniedError as exc:
            if session is None:
                print(str(exc))
                return 1
            page = session.page
            debug_info = build_debug_info(page, str(exc))
            save_debug_files(page, debug_info)
            print(str(exc))
            return 1
        except Exception as exc:
            if session is None:
                print(str(exc))
                return 1
            page = session.page
            debug_info = build_debug_info(page, str(exc))
            save_debug_files(page, debug_info)
            print("\uac8c\uc2dc\uae00 \ucd94\ucd9c\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4. saved_posts/_debug \ud3f4\ub354\ub97c \ud655\uc778\ud574\uc8fc\uc138\uc694.")
            print(f"\ud604\uc7ac URL: {page.url}")
            return 1
        finally:
            if session is not None:
                session.close()


if __name__ == "__main__":
    raise SystemExit(main())
