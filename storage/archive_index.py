from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_INDEX_PATH = Path("./data/archive_index.json")


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


def make_index_entry(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": meta["id"],
        "title": meta["title"],
        "source_url": meta["source_url"],
        "saved_at": meta["saved_at"],
        "folder_path": meta["folder_path"],
        "local_view_path": meta["local_view_path"],
        "image_count": meta["image_count"],
    }


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
