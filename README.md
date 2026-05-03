# Naver Cafe Posts Downloader

네이버 카페 게시글을 로컬 파일로 저장하는 Windows용 Python 도구입니다.

게시글 URL을 입력하면 본문 텍스트, HTML, 이미지, 저장 메타데이터를 `saved_posts` 폴더에 정리해서 저장합니다. 평소 사용하는 Chrome 또는 Edge의 네이버 로그인 쿠키를 가져와 적용하므로, 이미 브라우저에서 네이버에 로그인되어 있다면 자동 저장 브라우저에서 다시 로그인하지 않아도 됩니다.

## 주요 기능

- 네이버 카페 게시글 1개 저장
- 게시글 제목, 본문 텍스트, 본문 HTML 추출
- 본문 이미지 다운로드
- Chrome 또는 Edge 로그인 쿠키 사용
- 접근 권한 또는 로그인 필요 시 브라우저에서 로그인 후 재시도
- 자동 저장 실패 시 수동 HTML 저장 모드 제공
- 실패 원인 확인용 디버그 파일 저장

## 요구 사항

- Windows
- Python 3.10 이상 권장
- Chrome 또는 Microsoft Edge
- 네이버 카페 게시글을 볼 수 있는 계정

## 빠른 시작

1. 평소 사용하는 Chrome에서 네이버에 로그인합니다.
2. 이 폴더의 `실행하기.bat`를 더블클릭합니다.
3. 처음 한 번만 `1. First install`을 실행합니다.
4. 설치가 끝나면 `2. Save cafe post`를 선택합니다.
5. 저장할 네이버 카페 게시글 URL을 붙여넣고 Enter를 누릅니다.

저장이 완료되면 `saved_posts` 폴더 아래에 게시글 제목으로 된 폴더가 생성됩니다.

## GPT에서 불러오기

ChatGPT나 다른 도구에서 GitHub 페이지를 바로 읽지 못하면 아래 주소를 사용하세요.

- Repository: `https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader`
- ZIP: `https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader/archive/refs/heads/main.zip`
- Raw README: `https://raw.githubusercontent.com/Bum-Boo/Naver-Cafe-Posts-Downloader/refs/heads/main/README.md`

일부 도구는 한글 파일명을 제대로 처리하지 못할 수 있어, 같은 사용 설명을 `USAGE.md`에도 제공합니다.

## 저장 결과

각 게시글은 별도 폴더에 저장됩니다.

```text
saved_posts/
  게시글 제목/
    content.txt
    content.html
    meta.json
    images/
      001.jpg
      002.png
```

- `content.txt`: 본문 텍스트
- `content.html`: 본문 HTML
- `meta.json`: 원본 URL, 최종 URL, 저장 시간, 이미지 목록 등
- `images`: 본문 이미지 파일

## 명령어로 실행

설치:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

URL을 실행 중에 입력:

```bash
python save_naver_cafe_post.py
```

URL을 바로 지정:

```bash
python save_naver_cafe_post.py --url "https://cafe.naver.com/yourcafe/123456"
```

Edge에 저장된 로그인 쿠키 사용:

```bash
python save_naver_cafe_post.py --cookie-browser msedge
```

쿠키 가져오기 없이 실행:

```bash
python save_naver_cafe_post.py --no-cookie-import
```

## 수동 HTML 저장 모드

자동 저장이 실패하면 `실행하기.bat`에서 `3. Manual HTML save`를 사용합니다.

이 모드는 평소 사용하는 브라우저에서 게시글을 열고, 사용자가 `Ctrl+S`로 저장한 HTML 파일을 도구가 다시 읽어서 같은 형식으로 정리합니다.

## 문제 해결

로그인이 필요하다는 메시지가 나오면 열린 브라우저에서 네이버 로그인 또는 카페 접근을 완료한 뒤 터미널에서 Enter를 누릅니다.

게시글을 볼 수 없다는 메시지가 나오면 해당 계정이 카페에 가입되어 있는지, 게시판 열람 권한이 있는지 확인합니다.

추출에 실패하면 `saved_posts/_debug` 폴더의 파일을 확인합니다.

## 주의 사항

이 도구는 사용자가 열람 권한을 가진 게시글을 개인적으로 저장하기 위한 도구입니다. 저장한 콘텐츠의 이용과 재배포는 해당 카페와 게시글의 권리 및 정책을 따라야 합니다.

`browser_profile` 폴더에는 로컬 브라우저 세션 정보가 포함될 수 있습니다. 다른 사람에게 공유하거나 공개 저장소에 올리지 마세요.
