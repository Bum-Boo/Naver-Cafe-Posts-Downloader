# Naver Cafe Posts Downloader

[한국어](../README.md) | [English](README.en.md) | [日本語](README.ja.md) | [中文](README.zh-CN.md)

**閲覧権限のある Naver Cafe 投稿**を個人用として Windows PC に保存し、ローカル HTML で読み返せるデスクトップツールです。アプリ内では **Naver Cafe Archive Manager** と表示されます。

> [!IMPORTANT]
> Naver または Naver Cafe の公式製品ではありません。Naver の利用規約、Cafe の運営方針、著作権およびプライバシー関連法令を確認し、遵守してください。

## 主な機能と制限

- 個別投稿 URL、または対応する Cafe メニュー URL からの一括保存
- 本文、画像、メタデータ、閲覧用 `view.html` の生成
- 保存一覧、フォルダー／ローカルページの表示、確認後の削除
- 重複スキップ、進捗表示、一括処理のキャンセル
- 分離された Chromium プロファイルでのユーザー自身によるログイン

アクセス権、会員ランク、非公開投稿などの制限を回避しません。Naver の画面構造や方針が変わると動作しなくなる場合があります。

## ダウンロード

Windows 64-bit: [v0.1.0 リリース](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader/releases/tag/v0.1.0) · [ZIP](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader/releases/download/v0.1.0/NaverCafeArchiveManager-v0.1.0-win64.zip)

ZIP を展開し `NaverCafeArchiveManager.exe` を実行します。`data/`、`saved_posts/`、`ms-playwright/` は実行ファイルと同じ場所で使われます。個人データ入りのフォルダーを再配布しないでください。

## ソースから実行

Windows、Python 3、インターネット接続が必要です。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

## 使い方と保存先

1. `네이버 로그인 세션 연결` を押し、開いた Chromium で手動ログインします。
2. セッション確認後、投稿 URL または対応メニュー URL を貼り付けます。
3. `Download` を押し、保存一覧からローカルページを開きます。

セッションは `data/browser_profile/` と `data/auth/naver_state.json` にローカル保存されます。パスワード自体は保存しませんが、アカウントへのアクセスに使われ得る機密 Cookie が含まれます。共有、コミット、クラウドへのアップロードをしないでください。削除するにはアプリ終了後にこの二つの場所を削除します。

投稿は通常 `saved_posts/<タイトル>/` に `content.txt`、`content.html`、`view.html`、`meta.json`、`images/` として保存され、一覧は `data/archive_index.json` に記録されます。

## 責任ある利用

合法的に閲覧・個人保存できる内容だけを対象にし、非公開または著作権保護された内容を再配布したり、無差別に大量収集したりしないでください。サービスに負荷をかけない範囲で利用し、生成物の保管・削除・共有は利用者が管理してください。

## 現在の状態

公開版は Windows 中心の初期リリース `v0.1.0` です。自動テスト一式は含まれていません。[利用方法](../USAGE.md) と [Windows パッケージ手順](../packaging/windows/README_PACKAGING.md)も参照してください。

## ライセンスと出典表記のお願い

現在、個別のライセンスファイルはありません。公開ソースであることだけを理由に複製・変更・再配布できると判断せず、必要な権利を確認してください。

紹介または許可を得た派生利用では、`@Bum-Boo` と [元のリポジトリ](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader)を記載していただけると幸いです。これは任意のお願いであり、ライセンス上の義務を追加・代替するものではありません。
