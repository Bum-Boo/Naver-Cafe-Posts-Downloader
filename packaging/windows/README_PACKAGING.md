# Windows 포터블 ZIP 배포 가이드

이 문서는 Windows 10/11 64-bit용 포터블 ZIP 패키지를 만드는 방법을 설명합니다.

## 사전 준비

- Python 3.11 이상
- PowerShell
- 인터넷 연결

처음 빌드 전 의존성을 설치합니다.

```powershell
pip install -r requirements.txt
python -m playwright install chromium
```

## 빌드 명령

프로젝트 루트에서 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/build_portable.ps1
```

## 결과물

빌드가 성공하면 아래 ZIP 파일이 생성됩니다.

```text
release/NaverCafeArchiveManager-v0.1.0-win64.zip
```

ZIP 내부 구조:

```text
NaverCafeArchiveManager/
  NaverCafeArchiveManager.exe
  _internal/
  ms-playwright/
  README_QUICKSTART.txt
  data/
  saved_posts/
```

`data/`와 `saved_posts/`는 빈 런타임 폴더로만 포함됩니다. 개발 PC의 로그인 세션, 인증 JSON, 저장된 게시글은 배포 ZIP에 포함하지 않습니다.

## 아이콘 변경

앱 아이콘을 바꾸려면 아래 파일을 추가하거나 교체한 뒤 다시 빌드합니다.

```text
assets/app_icon.ico
```

아이콘 파일이 없어도 빌드는 실패하지 않습니다.

## 정리 명령

빌드 산출물을 지우려면 아래 명령을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/clean_build.ps1
```

이 명령은 `build/`, `dist/`, `release/*.zip`, `__pycache__/`만 정리합니다. 소스 작업 폴더의 `data/`, `saved_posts/`, `data/auth/`, `data/browser_profile/`는 삭제하지 않습니다.

## 테스트 체크리스트

1. `release/NaverCafeArchiveManager-v0.1.0-win64.zip`을 새 폴더에 압축 해제합니다.
2. `NaverCafeArchiveManager.exe`를 실행합니다.
3. `네이버 로그인 세션 연결`을 누릅니다.
4. 열린 브라우저에서 네이버에 직접 로그인합니다.
5. 개별 게시글 주소를 다운로드합니다.
6. 메뉴/게시판 주소 전체 다운로드를 실행합니다.
7. 진행 팝업과 실시간 로그가 표시되는지 확인합니다.
8. 다운로드 중 `취소` 버튼이 안전하게 동작하는지 확인합니다.
9. 저장된 게시글에서 `저장 페이지 열기`가 동작하는지 확인합니다.
10. 앱을 종료 후 다시 실행했을 때 저장 목록이 유지되는지 확인합니다.
