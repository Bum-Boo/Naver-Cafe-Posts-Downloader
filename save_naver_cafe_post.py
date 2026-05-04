from __future__ import annotations

import argparse

from downloader.naver_cafe_downloader import AccessRequiredError, download_post, setup_login_session
from storage.archive_index import make_index_entry, upsert_archive_entry


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save a single Naver Cafe post")
    parser.add_argument("--url", help="Naver Cafe post URL")
    parser.add_argument("--login-only", action="store_true", help="Open Chromium and save a Naver login session")
    return parser.parse_args()


def prompt_for_url() -> str:
    while True:
        value = input("네이버 카페 게시글 URL을 입력하세요: ").strip()
        if value:
            return value
        print("URL을 입력해주세요.")


def main() -> int:
    args = parse_args()

    if args.login_only:
        setup_login_session(progress=print)
        return 0

    url = args.url or prompt_for_url()
    try:
        meta = download_post(url, progress=print)
    except AccessRequiredError as exc:
        print(str(exc))
        return 1
    except Exception as exc:
        print(f"다운로드 실패: {exc}")
        return 1

    upsert_archive_entry(make_index_entry(meta))
    print("다운로드 완료")
    print(f"저장 완료: {meta['folder_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
