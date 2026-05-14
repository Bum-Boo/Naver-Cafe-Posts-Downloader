# Naver-Cafe-Posts-Downloader Portfolio Case Study

## Problem

Users sometimes need to preserve posts they are allowed to access for personal reference, study, record keeping, or repeated offline review. Browser bookmarks do not provide a durable local copy, and manual saving can scatter text, images, and metadata across folders.

## Target Users

- Naver Cafe users who need a personal local archive.
- Korean-language users who want offline review of posts they can already access.
- People who need saved post lists and generated local pages rather than raw browser bookmarks.

## Design Goal

Create a predictable local archive workflow that saves post content, metadata, images, and generated local HTML pages on the user's PC while keeping responsibility and session data local.

## Core Workflow

1. Connect a Naver login session through the user's browser.
2. Enter an individual post URL or menu URL.
3. Download allowed content into local folders.
4. Save title, body text, HTML, images, and metadata.
5. Review saved posts from the app.
6. Open the generated local HTML page for offline reading.

## Architecture Summary

The repository is a Python Windows desktop app with browser-session support, downloader services, local storage/indexing, local HTML page generation, packaging scripts, and demo screenshots.

## Safety / Privacy Decisions

- Use only with content the user is allowed to access.
- The app does not store Naver passwords.
- Login/session data remains local.
- The tool does not bypass Cafe access controls.
- Private or copyrighted content should not be redistributed.
- Public screenshots and fixtures should avoid real private posts.

## Technical Highlights

- User-controlled browser session flow.
- Local saved-post index.
- Local folder and HTML page generation.
- Progress/status UI for long-running downloads.
- Windows ZIP release asset.

## Current Limitations

- Platform/session behavior depends on Naver and user account access.
- The project is a personal archive workflow, not a redistribution system.
- Generated archives and session data must stay out of git.

## Next Steps

- Add sanitized demo fixtures that do not use private Cafe content.
- Document validation commands for downloader, storage, and local-page generation.
- Keep responsibility and privacy notes near the top of README.
- Add release notes that explain exactly what the tool does not do.

## Portfolio Value

This project demonstrates local-first archive workflow design, Windows desktop utility implementation, progress visibility, local metadata/index management, generated offline preview pages, and safety-conscious framing around user-owned sessions and content access.
