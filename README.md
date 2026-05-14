# Naver-Cafe-Posts-Downloader

> Local Windows archive manager for Naver Cafe posts.

| Area | Detail |
|---|---|
| Platform | Windows desktop |
| Product name in app | Naver Cafe Archive Manager |
| Scope | Personal/local archive for posts the user is allowed to access |
| Storage | Local `data/` and `saved_posts/` folders |
| Safety stance | No password storage, no private-access bypass, no redistribution workflow |

## Safety / Privacy Scope

- Use only with posts and Cafe content you are allowed to access.
- The app does not store Naver passwords.
- Login/session data and saved posts stay on the user's PC.
- The tool does not bypass Cafe access permissions, member level restrictions, private post restrictions, or Naver platform controls.
- Do not redistribute downloaded private or copyrighted content.
- Do not share builds with personal `data/`, `browser_profile`, or `saved_posts` folders included.

## Download / Release

Latest release: [Naver Cafe Archive Manager v0.1.0](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader/releases/tag/v0.1.0)

Windows ZIP:

- [NaverCafeArchiveManager-v0.1.0-win64.zip](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader/releases/download/v0.1.0/NaverCafeArchiveManager-v0.1.0-win64.zip)

## Preview

The app connects a user-controlled browser login session, downloads allowed posts, and opens generated local pages for offline review.

![Login session applied](docs/demo-screenshots/naver-live-01-session-applied.png)

<details>
<summary>View demo walkthrough</summary>

1. Run `dist\NaverCafeArchiveManager\NaverCafeArchiveManager.exe`.
2. Connect a Naver login session in the browser.
3. Enter an individual post URL or menu URL.
4. Click `Download`.
5. Review progress for opening the post, extracting text, downloading images, and generating a local page.
6. Select the saved post from the local list.
7. Open the generated local HTML page for offline reading.

![Cafe post URL entered](docs/demo-screenshots/naver-live-02-url-entered.png)

![Download result](docs/demo-screenshots/naver-live-04-download-result.png)

![Saved item selected](docs/demo-screenshots/naver-live-05-saved-item-selected.png)

![Generated local page](docs/demo-screenshots/naver-live-06-local-page.png)

</details>

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

## Documentation

- [Quickstart text](README_QUICKSTART.txt)
- [Usage](USAGE.md)
- [Portfolio case study](docs/portfolio-case-study.md)

## Status

This is a personal archive workflow tool. Public demos should use sanitized examples and should not include real private Cafe content, cookies, tokens, or saved third-party material.
