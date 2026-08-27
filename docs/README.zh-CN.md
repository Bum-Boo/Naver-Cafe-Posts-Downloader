# Naver Cafe Posts Downloader

[한국어](../README.md) | [English](README.en.md) | [日本語](README.ja.md) | [中文](README.zh-CN.md)

用于将**您有权查看的 Naver Cafe 帖子**保存到 Windows 电脑供个人使用，并生成本地 HTML 以便离线阅读。应用内名称为 **Naver Cafe Archive Manager**。

> [!IMPORTANT]
> 本项目不是 Naver 或 Naver Cafe 的官方产品。请自行确认并遵守 Naver 服务条款、Cafe 运营政策、版权规定和隐私法律。

## 主要功能与限制

- 下载单个帖子 URL，或从受支持的 Cafe 菜单 URL 批量收集帖子
- 保存正文、图片、元数据及本地阅读页面 `view.html`
- 浏览已保存项目，打开页面/文件夹，并在确认后删除
- 跳过重复帖子、显示进度及取消批处理
- 通过隔离的 Chromium profile 由用户手动登录

本工具不会绕过访问权限、会员等级、私密帖子或其他平台限制。Naver 页面结构或政策改变后，下载功能可能失效。

## 下载

Windows 64 位版本：[v0.1.0 release](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader/releases/tag/v0.1.0) · [直接下载 ZIP](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader/releases/download/v0.1.0/NaverCafeArchiveManager-v0.1.0-win64.zip)

解压 ZIP 后运行 `NaverCafeArchiveManager.exe`。运行时会使用可执行文件旁的 `data/`、`saved_posts/` 和 `ms-playwright/`。切勿再分发包含个人数据的副本。

## 从源码运行

需要 Windows、Python 3 和互联网连接。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

## 使用方法与存储位置

1. 点击 `네이버 로그인 세션 연결`，在打开的 Chromium 中手动登录。
2. 会话确认后，粘贴帖子 URL 或受支持的菜单 URL。
3. 点击 `Download` 并查看进度，再从已保存列表打开本地页面。

会话数据保存在本地 `data/browser_profile/` 和 `data/auth/naver_state.json`。应用不保存密码本身，但这些文件包含可能用于访问账号的敏感 Cookie。请勿分享、提交到 Git 或上传。若要移除会话，请关闭应用后删除上述两个位置。

帖子通常保存在 `saved_posts/<标题>/` 下，包括 `content.txt`、`content.html`、`view.html`、`meta.json` 和 `images/`；索引位于 `data/archive_index.json`。

## 负责任地使用

仅处理您可合法查看并供个人存档的内容。请勿再分发私密或受版权保护的内容，也不要进行无差别大规模采集。请控制自动化频率和范围，避免给服务造成负担。生成页面可能包含原文与图片，存储、删除和分享责任由用户承担。

## 当前状态

当前公开版是面向 Windows 的早期版本 `v0.1.0`。仓库没有自动化测试套件。另请参阅[使用说明](../USAGE.md)和 [Windows 打包指南](../packaging/windows/README_PACKAGING.md)。

## 许可证与署名请求

仓库目前没有独立许可证文件。请勿因源码公开就假定可以复制、修改或再分发，应先确认所需权利。

如介绍本项目或在获得授权的衍生项目中使用，欢迎注明 `@Bum-Boo` 和[原始仓库](https://github.com/Bum-Boo/Naver-Cafe-Posts-Downloader)。这只是礼貌请求，不增加或取代任何许可证义务。
