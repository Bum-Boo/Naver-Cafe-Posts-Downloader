# 네이버 카페 아카이브 매니저

네이버 카페 게시글을 로컬에 저장하고, 저장된 글을 목록으로 관리하는 간단한 Python 데스크톱 앱입니다.

이 앱은 네이버 블로그가 아니라 네이버 카페 게시글만 대상으로 합니다. 사용자가 직접 로그인한 네이버 세션으로 볼 수 있는 글만 저장하며, 접근 제한을 우회하지 않습니다.

## 설치

Python 3.11 이상을 권장합니다.

```bash
pip install -r requirements.txt
```

Playwright Chromium을 설치합니다.

```bash
python -m playwright install chromium
```

## 실행

```bash
python app.py
```

## 처음 사용

1. 앱을 실행합니다.
2. `네이버 로그인 세션 연결` 버튼을 누릅니다.
3. 열린 Chromium 브라우저에서 네이버에 직접 로그인합니다.
4. 앱 상태 표시줄에 `로그인 세션이 저장되었습니다` 메시지가 뜰 때까지 기다립니다.
5. 앱으로 돌아와 네이버 카페 게시글 URL을 붙여넣습니다.
6. `Download` 버튼을 누릅니다.

로그인 세션은 1차로 `./data/browser_profile`에 저장되고, 보조 인증 상태는 `./data/auth/naver_state.json`에 저장됩니다. 다음 실행부터는 같은 세션으로 글을 다운로드합니다.

일부 네이버 인증 화면은 백그라운드 브라우저를 다시 인증 대상으로 볼 수 있습니다. 이 경우 앱이 같은 세션으로 보이는 Chromium을 한 번 더 열어 확인한 뒤 다운로드를 계속 시도합니다.

## 게시글 저장

지원하는 URL 형식:

- `https://cafe.naver.com/{cafeName}/{articleId}`
- `https://cafe.naver.com/ArticleRead.nhn?clubid={clubId}&articleid={articleId}`
- `https://cafe.naver.com/ca-fe/cafes/{clubId}/articles/{articleId}`
- `https://m.cafe.naver.com/ca-fe/web/cafes/{clubId}/articles/{articleId}`

저장 결과는 `./saved_posts/` 아래에 게시글 제목으로 된 폴더로 생성됩니다.

```text
saved_posts/
  Safe_Post_Title/
    content.txt
    content.html
    view.html
    meta.json
    images/
      001.jpg
      002.png
```

## 저장된 글 보기

1. 왼쪽 목록에서 저장된 게시글을 클릭합니다.
2. 오른쪽에서 제목, 원본 URL, 저장일, 이미지 수, 폴더 경로를 확인합니다.
3. `Open Local Page`를 누르면 `view.html`이 기본 브라우저에서 열립니다.
4. `Open Folder`를 누르면 저장 폴더가 열립니다.
5. `Delete Archive`를 누르면 확인 후 저장 폴더와 목록 항목을 삭제합니다.

`view.html`은 저장된 본문과 로컬 이미지로 구성되어 오프라인에서도 볼 수 있습니다.

상단의 세션 상태 표시에서 네이버 로그인 세션이 적용 중인지 확인할 수 있습니다.

## 데이터 파일

- `data/archive_index.json`: 저장된 게시글 목록
- `data/auth/naver_state.json`: 저장된 브라우저 쿠키/세션 상태
- `saved_posts/`: 게시글 본문, HTML, 이미지, 메타데이터
- `data/browser_profile/`: 네이버 로그인 세션이 저장되는 Chromium 프로필

## 문제 해결

다운로드 중 아래 메시지가 나오면 `네이버 로그인 세션 연결`을 먼저 실행하세요.

```text
네이버 로그인 세션이 만료되었거나 카페 접근 권한 확인이 필요합니다. [네이버 로그인 세션 연결]을 다시 실행해주세요.
```

추출에 실패하면 `saved_posts/_debug/` 폴더에 아래 파일이 생성됩니다.

- `debug_screenshot.png`
- `debug_page.html`
- `debug_info.json`
