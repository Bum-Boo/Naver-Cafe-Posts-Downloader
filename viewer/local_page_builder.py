from __future__ import annotations

import html
from pathlib import Path


def _replace_image_references(content_html: str, image_map: dict[str, str]) -> str:
    # Naver can store the same image URL in escaped and unescaped attributes.
    # Rewriting both forms keeps view.html usable offline with local images.
    rewritten = content_html
    for source, local_path in image_map.items():
        if not source:
            continue
        replacements = {
            source,
            html.escape(source, quote=True),
            html.escape(source, quote=False),
        }
        for candidate in replacements:
            rewritten = rewritten.replace(candidate, local_path)
    return rewritten


def build_local_page(
    *,
    title: str,
    content_html: str,
    image_map: dict[str, str],
    source_url: str,
    saved_at: str,
    output_path: Path,
) -> Path:
    body_html = _replace_image_references(content_html, image_map)
    page = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    body {{
      margin: 0;
      background: #f6f7f8;
      color: #202124;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif;
      line-height: 1.65;
    }}
    main {{
      max-width: 860px;
      margin: 0 auto;
      padding: 40px 20px 64px;
      background: #fff;
      min-height: 100vh;
    }}
    header {{
      border-bottom: 1px solid #e5e7eb;
      margin-bottom: 28px;
      padding-bottom: 18px;
    }}
    h1 {{
      font-size: 26px;
      line-height: 1.35;
      margin: 0 0 14px;
    }}
    .meta {{
      color: #5f6368;
      font-size: 13px;
      word-break: break-all;
    }}
    .content img {{
      max-width: 100%;
      height: auto;
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{html.escape(title)}</h1>
      <div class="meta">원본: {html.escape(source_url)}</div>
      <div class="meta">저장일: {html.escape(saved_at)}</div>
    </header>
    <section class="content">
{body_html}
    </section>
  </main>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return output_path
