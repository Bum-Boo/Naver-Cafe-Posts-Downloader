# 네이버 카페 게시글 저장 도구

네이버 카페 게시글 1개를 저장하는 Python 터미널 도구입니다. 기본 사용법은 URL만 붙여넣는 방식입니다.

도구는 평소 Chrome에 저장된 네이버 로그인 쿠키를 읽어서 자동 저장 브라우저에 적용합니다. 그래서 네이버에 이미 로그인되어 있다면 매번 자동화 브라우저에서 다시 로그인할 필요가 없도록 구성했습니다.

## 가장 쉬운 실행 방법

1. 평소 쓰는 Chrome에서 네이버에 로그인되어 있는지 확인합니다.
2. `실행하기.bat`를 더블클릭합니다.
3. 처음 한 번만 `1. First install`을 실행합니다.
4. 메뉴에서 `2. Save cafe post`를 실행합니다.
5. 네이버 카페 게시글 URL을 붙여넣습니다.

## 저장 결과

저장 결과는 `./saved_posts/` 아래에 생성됩니다.

- `content.txt`
- `content.html`
- `meta.json`
- `images/001.jpg`, `002.png`, `003.webp` 등

추출에 실패하면 디버그 파일이 `./saved_posts/_debug/`에 저장됩니다.

## 직접 명령어로 실행

설치:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

URL 입력 방식:

```bash
python save_naver_cafe_post.py
```

URL을 바로 넣어서 저장:

```bash
python save_naver_cafe_post.py --url "https://cafe.naver.com/irelandprestigeuhak/33829"
```

Edge에 로그인된 쿠키를 쓰려면:

```bash
python save_naver_cafe_post.py --cookie-browser msedge
```

## 예비 수동 방식

자동 저장이 실패할 때만 `실행하기.bat`에서 `3. Manual HTML save`를 사용하세요. 이 방식은 평소 브라우저에서 `Ctrl+S`로 저장한 HTML 파일을 도구가 정리합니다.
