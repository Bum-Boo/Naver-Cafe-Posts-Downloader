# Usage

This is a simple Python desktop archive manager for saving Naver Cafe posts.

## Install

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python app.py
```

## First Use

1. Click `네이버 로그인 세션 연결`.
2. Log in to Naver manually in the visible Chromium browser.
3. Wait until the app reports that the login session was saved.
4. Paste a Naver Cafe post URL.
5. Click `Download`.

The primary login session is stored in `./data/browser_profile`, and the backup auth state is stored in `./data/auth/naver_state.json`.

## Viewing Saved Posts

Saved posts appear in the left list. Select a post to view metadata, then click:

- `Open Local Page` to open `view.html`
- `Open Folder` to open the saved post folder
- `Delete Archive` to remove the saved folder and archive entry after confirmation

The top status label shows whether the Naver login session is applied.

## Output

```text
saved_posts/
  Safe_Post_Title/
    content.txt
    content.html
    view.html
    meta.json
    images/
      001.jpg
```

The archive list is stored in `data/archive_index.json`.
