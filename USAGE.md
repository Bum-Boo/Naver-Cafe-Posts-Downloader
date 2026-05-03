# Usage

This file mirrors the Korean instructions in an ASCII file name so repository import tools can read the project more reliably.

## Requirements

- Windows
- Python 3.10 or newer recommended
- Chrome or Microsoft Edge
- A Naver account that can view the target Cafe post

## Quick Start

1. Sign in to Naver in your normal Chrome browser.
2. Double-click `run.bat`.
3. Run `1. First install` the first time only.
4. Run `2. Save cafe post`.
5. Paste the Naver Cafe post URL and press Enter.

Saved posts are created under the `saved_posts` folder.

## Command Line

Install dependencies:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Run and paste a URL:

```bash
python save_naver_cafe_post.py
```

Run with a URL:

```bash
python save_naver_cafe_post.py --url "https://cafe.naver.com/yourcafe/123456"
```

Use Edge cookies:

```bash
python save_naver_cafe_post.py --cookie-browser msedge
```

## Output

```text
saved_posts/
  Post title/
    content.txt
    content.html
    meta.json
    images/
      001.jpg
```

## Troubleshooting

If automatic extraction fails, use `3. Manual HTML save` from the batch menu. This mode lets you save the page from your normal browser with `Ctrl+S`, then the tool reads that saved HTML file.

If extraction fails, check `saved_posts/_debug`.
