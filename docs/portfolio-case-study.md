# Naver Cafe Posts Downloader Portfolio Case Study

Naver Cafe Posts Downloader is a Windows local archive manager for saving and reviewing Naver Cafe posts on the user's own PC. It is framed as a personal archive and offline review tool, not as a bypass or redistribution system.

## Positioning

This project fits the portfolio theme of local-first productivity tools. Its strongest public value is the workflow around saving, indexing, previewing, and reopening posts locally while keeping responsibility and session data on the user's machine.

The public framing should stay focused on:

- personal local archives
- user-controlled login/session flow
- local saved-post index
- local HTML preview generation
- clear permission and responsibility boundaries

## Problem

Users sometimes need to preserve posts they are allowed to access, especially for personal reference, study, record keeping, or repeated offline review. Browser bookmarks do not provide a durable local copy, and manual saving can scatter text, images, and metadata across folders.

The tool addresses that by creating a predictable local archive workflow with saved post lists, generated local pages, and folders that can be inspected on disk.

## Product Shape

The main workflow is:

1. Connect a Naver login session through the user's browser.
2. Enter an individual post URL or menu URL.
3. Download allowed content into local folders.
4. Save title, body text, HTML, images, and metadata.
5. Review saved posts from the app.
6. Open the generated local HTML page for offline reading.

The interface emphasizes progress visibility, saved-item selection, and opening the local output rather than hidden background automation.

## Safety and Responsibility Boundaries

This repository should keep the legal and privacy framing visible because it works with platform content and login sessions.

Public documentation should state that:

- users are responsible for using it only with content they are allowed to access
- the app does not store Naver passwords
- login/session data remains local
- private or copyrighted content should not be redistributed
- screenshots and fixtures should avoid real private posts
- the tool should not claim to bypass access controls

## Implementation Notes

The repository is a Python Windows desktop app with browser-session support, downloader services, local storage/indexing, local HTML page generation, packaging scripts, and demo screenshots.

The local data model is the important portfolio story: downloaded content, metadata, and generated pages are kept in predictable folders so the user can inspect and manage the archive outside the app.

## Portfolio Value

The project demonstrates:

- local-first archive workflow design
- Windows desktop utility implementation
- progress and status UI for long-running operations
- local metadata/index management
- generated offline preview pages
- safety-conscious framing around user-owned sessions and content access

## Next Steps

- Keep README limitations and responsibility notes near the top.
- Add a sanitized demo fixture that does not use private Cafe content.
- Document validation commands for downloader, storage, and local-page generation.
- Keep generated archives and session data out of git.
- Consider a release note explaining exactly what the tool does not do.
