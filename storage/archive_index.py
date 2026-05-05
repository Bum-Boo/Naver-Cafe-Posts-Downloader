from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app_paths import get_archive_index_path


DEFAULT_INDEX_PATH = get_archive_index_path()
INDEX_OPTIONAL_FIELDS = (
    "download_type",
    "article_key",
    "club_id",
    "article_id",
    "cafe_name",
    "menu_id",
    "menu_title",
    "source_menu_url",
    "batch_id",
)


def ensure_index_file(index_path: Path = DEFAULT_INDEX_PATH) -> None:
    # The index is local user data. It is generated on demand and intentionally
    # ignored by git because entries can contain private cafe post URLs/titles.
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if not index_path.exists():
        index_path.write_text(json.dumps({"posts": []}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_archive_index(index_path: Path = DEFAULT_INDEX_PATH) -> list[dict[str, Any]]:
    ensure_index_file(index_path)
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        posts = raw.get("posts", [])
        if isinstance(posts, list):
            return [item for item in posts if isinstance(item, dict)]
    return []


def save_archive_index(posts: list[dict[str, Any]], index_path: Path = DEFAULT_INDEX_PATH) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps({"posts": posts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def make_article_key(
    *,
    club_id: Any = None,
    article_id: Any = None,
    cafe_name: Any = None,
    source_url: Any = None,
) -> str:
    # Titles can change or duplicate across posts, so duplicate detection uses
    # stable cafe/article identifiers whenever Naver exposes them.
    club = str(club_id or "").strip()
    article = str(article_id or "").strip()
    cafe = str(cafe_name or "").strip()
    source = str(source_url or "").strip()

    if club and article:
        return f"{club}:{article}"
    if cafe and article:
        return f"{cafe}:{article}"
    return source


def get_existing_article_keys(index_path: Path = DEFAULT_INDEX_PATH) -> set[str]:
    keys: set[str] = set()
    for post in load_archive_index(index_path):
        key = str(post.get("article_key") or "").strip()
        if not key:
            key = make_article_key(
                club_id=post.get("club_id"),
                article_id=post.get("article_id"),
                cafe_name=post.get("cafe_name"),
                source_url=post.get("source_url"),
            )
        if key:
            keys.add(key)
    return keys


def has_article_key(article_key: str, index_path: Path = DEFAULT_INDEX_PATH) -> bool:
    return bool(article_key) and article_key in get_existing_article_keys(index_path)


def make_index_entry(meta: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "id": meta["id"],
        "title": meta["title"],
        "source_url": meta["source_url"],
        "saved_at": meta["saved_at"],
        "folder_path": meta["folder_path"],
        "local_view_path": meta["local_view_path"],
        "image_count": meta["image_count"],
    }
    for field in INDEX_OPTIONAL_FIELDS:
        value = meta.get(field)
        if value not in (None, ""):
            entry[field] = value
    return entry


def upsert_archive_entry(entry: dict[str, Any], index_path: Path = DEFAULT_INDEX_PATH) -> list[dict[str, Any]]:
    posts = load_archive_index(index_path)
    posts = [post for post in posts if post.get("id") != entry.get("id")]
    posts.insert(0, entry)
    save_archive_index(posts, index_path)
    return posts


def remove_archive_entry(post_id: str, index_path: Path = DEFAULT_INDEX_PATH) -> list[dict[str, Any]]:
    posts = load_archive_index(index_path)
    posts = [post for post in posts if post.get("id") != post_id]
    save_archive_index(posts, index_path)
    return posts


def remove_archive_entries(post_ids: set[str], index_path: Path = DEFAULT_INDEX_PATH) -> list[dict[str, Any]]:
    posts = load_archive_index(index_path)
    posts = [post for post in posts if str(post.get("id") or "") not in post_ids]
    save_archive_index(posts, index_path)
    return posts


def update_archive_entry_paths(
    post_id: str,
    *,
    folder_path: str,
    local_view_path: str,
    index_path: Path = DEFAULT_INDEX_PATH,
) -> list[dict[str, Any]]:
    # Folder renames happen outside the original download flow. Keep the index
    # aligned so preview/open/delete operations point at the new location.
    posts = load_archive_index(index_path)
    for post in posts:
        if str(post.get("id") or "") == post_id:
            post["folder_path"] = folder_path
            post["local_view_path"] = local_view_path
            break
    save_archive_index(posts, index_path)
    return posts


def update_archive_entries_paths(
    path_updates: dict[str, dict[str, str]],
    index_path: Path = DEFAULT_INDEX_PATH,
) -> list[dict[str, Any]]:
    # Menu group renames update every child post path in one index write.
    posts = load_archive_index(index_path)
    for post in posts:
        post_id = str(post.get("id") or "")
        update = path_updates.get(post_id)
        if not update:
            continue
        post["folder_path"] = update["folder_path"]
        post["local_view_path"] = update["local_view_path"]
    save_archive_index(posts, index_path)
    return posts
