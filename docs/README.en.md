# Naver Cafe Posts Downloader

[한국어](../README.md) | [English](README.en.md) | [日本語](README.ja.md) | [中文](README.zh-CN.md)

A Windows desktop tool that saves **Naver Cafe posts you are authorized to view** for personal, local use and generates local HTML pages for later reading. The app is displayed as **Naver Cafe Archive Manager**.

> [!IMPORTANT]
> This is not an official Naver or Naver Cafe product. You are responsible for following Naver's terms, Cafe policies, copyright rules, and privacy laws.

## Features

- Download an individual post URL.
- Collect posts from supported Cafe menu URLs in a batch.
- Save text, images, metadata, and a local `view.html` page.
- Browse saved items; open their page/folder; delete after confirmation.
- Skip duplicates, show progress, and cancel batch work.
- Let the user log in manually through an isolated Chromium profile.

The downloader may stop working when Naver changes its pages or policies. It does not bypass access permissions, membership levels, private posts, or other platform controls.

## Download

Windows 64-bit build: [v0.1.0 release](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader/releases/tag/v0.1.0) · [direct ZIP](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader/releases/download/v0.1.0/NaverCafeArchiveManager-v0.1.0-win64.zip)

Extract the ZIP and run `NaverCafeArchiveManager.exe`. Runtime data is kept beside the executable in `data/` and `saved_posts/`; packaged Chromium is under `ms-playwright/`. Never redistribute a copy containing your personal data.

## Run from source

Windows, Python 3, and an internet connection are required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

## Use

1. Select `네이버 로그인 세션 연결` and sign in manually in the Chromium window.
2. After the session is confirmed, paste a post URL or supported menu URL.
3. Select `Download` and monitor progress.
4. Choose an item in the saved list to open its local page or folder.

Session data is stored locally in `data/browser_profile/` and `data/auth/naver_state.json`. The app does not store your password, but these files contain sensitive cookies that may provide account access. Never share, commit, or upload them. To remove the session, close the app and delete `data/browser_profile/` and `data/auth/`.

Outputs are normally written under `saved_posts/<title>/` as `content.txt`, `content.html`, `view.html`, `meta.json`, and `images/`. The archive index is `data/archive_index.json`.

## Preview

![Login session applied](demo-screenshots/naver-live-01-session-applied.png)

[URL entry](demo-screenshots/naver-live-02-url-entered.png) · [download result](demo-screenshots/naver-live-04-download-result.png) · [saved item](demo-screenshots/naver-live-05-saved-item-selected.png) · [local page](demo-screenshots/naver-live-06-local-page.png)

## Responsible use

- Use only content you may lawfully access and archive for personal use.
- Do not redistribute private or copyrighted material or perform indiscriminate collection.
- Keep automation frequency and scope low enough not to burden the service.
- Generated pages may contain original text and images; you are responsible for storage, deletion, and sharing.

## Status

The current public version is the Windows-focused initial release `v0.1.0`. The repository has no automated test suite. See [USAGE.md](../USAGE.md) and the [Windows packaging guide](../packaging/windows/README_PACKAGING.md).

## License and attribution request

This repository currently has no separate license file. Do not assume that public source code grants permission to copy, modify, or redistribute it; determine the rights you need first.

If you showcase this project or use it in an authorized derivative, a mention of `@Bum-Boo` and the [original repository](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader) would be appreciated. This is a courtesy request, not an additional license condition and not a replacement for license obligations.
