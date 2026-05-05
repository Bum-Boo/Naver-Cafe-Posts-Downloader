# 앱 아이콘

Windows 아이콘 파일은 아래 이름 중 하나로 넣습니다. 둘 다 있으면 `app_icon.ico`를 우선 사용합니다.

```text
assets/app_icon.ico
assets/naver_cafe_archive_icon.ico
```

그다음 빌드를 다시 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/build_portable.ps1
```

생성된 실행 파일은 위 `.ico` 파일을 앱 아이콘으로 사용합니다. 아이콘 파일이 없어도 빌드는 실패하지 않고 기본 실행 파일 아이콘을 사용합니다.

`naver_cafe_archive_icon.svg`는 원본 편집용으로 보관할 수 있지만, Windows 실행 파일 아이콘에는 `.ico` 파일이 사용됩니다.
