from __future__ import annotations

import os
import sys
from pathlib import Path


def get_app_base_dir() -> Path:
    """Return the folder that owns runtime data for source and packaged runs."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_user_data_dir() -> Path:
    return get_app_base_dir() / "data"


def get_saved_posts_dir() -> Path:
    return get_app_base_dir() / "saved_posts"


def get_browser_profile_dir() -> Path:
    return get_user_data_dir() / "browser_profile"


def get_auth_state_path() -> Path:
    return get_user_data_dir() / "auth" / "naver_state.json"


def get_archive_index_path() -> Path:
    return get_user_data_dir() / "archive_index.json"


def get_batches_dir() -> Path:
    return get_user_data_dir() / "batches"


def get_debug_dir() -> Path:
    return get_saved_posts_dir() / "_debug"


def get_playwright_browsers_path() -> Path:
    return get_app_base_dir() / "ms-playwright"


def configure_playwright_browsers_path() -> None:
    if getattr(sys, "frozen", False):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(get_playwright_browsers_path())


def ensure_runtime_dirs() -> None:
    for path in (
        get_user_data_dir(),
        get_saved_posts_dir(),
        get_browser_profile_dir(),
        get_auth_state_path().parent,
        get_batches_dir(),
    ):
        path.mkdir(parents=True, exist_ok=True)


def app_base_dir() -> Path:
    return get_app_base_dir()


def app_path(*parts: str) -> Path:
    return get_app_base_dir().joinpath(*parts)
