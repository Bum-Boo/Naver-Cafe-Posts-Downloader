from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QProgressBar,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl

from app_paths import (
    configure_playwright_browsers_path,
    ensure_runtime_dirs,
    get_app_base_dir,
    get_batches_dir,
    get_saved_posts_dir,
)

configure_playwright_browsers_path()

from downloader.naver_cafe_downloader import (
    SESSION_EXPIRED_MESSAGE,
    AccessRequiredError,
    BatchDownloadResult,
    DownloadCancelledError,
    check_saved_session,
    download_menu_posts,
    download_single_post,
    parse_naver_cafe_url_type,
    sanitize_filename,
    setup_login_session,
)
from storage.archive_index import (
    has_article_key,
    load_archive_index,
    make_article_key,
    make_index_entry,
    remove_archive_entries,
    remove_archive_entry,
    update_archive_entries_paths,
    update_archive_entry_paths,
    upsert_archive_entry,
)


APP_VERSION = "0.1.0"
DOWNLOAD_MODE_AUTO = "자동 감지"
DOWNLOAD_MODE_SINGLE = "개별 게시글 다운로드"
DOWNLOAD_MODE_MENU = "메뉴 전체 다운로드"
FILTER_ALL = "전체 보기"
FILTER_SINGLE = "개별 다운로드만"
FILTER_MENU = "메뉴 다운로드만"


def apply_app_theme(app: QApplication) -> None:
    app.setFont(QFont("맑은 고딕", 10))
    app.setStyleSheet(
        """
        QWidget {
            background: #f3f8ff;
            color: #12304f;
            font-family: "Pretendard", "Segoe UI", "맑은 고딕", sans-serif;
            font-size: 10pt;
        }
        QMainWindow, #appRoot {
            background: #eef6ff;
        }
        #sidePanel, #detailsPanel, #previewPanel {
            background: #ffffff;
            border: 1px solid #d6e7fb;
            border-radius: 10px;
        }
        QLabel {
            background: transparent;
            color: #173b63;
        }
        QLineEdit, QTextEdit, QTextBrowser, QComboBox, QTreeWidget {
            background: #ffffff;
            border: 1px solid #bfd8f3;
            border-radius: 8px;
            padding: 7px 9px;
            selection-background-color: #2f80ed;
            selection-color: #ffffff;
        }
        QTextEdit:read-only {
            background: #f7fbff;
        }
        QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus, QComboBox:focus, QTreeWidget:focus {
            border: 1px solid #2f80ed;
        }
        QPushButton {
            background: #e6f1ff;
            color: #11406d;
            border: 1px solid #a9cdf3;
            border-radius: 8px;
            padding: 8px 13px;
            font-weight: 600;
        }
        QPushButton:hover {
            background: #d6eaff;
            border-color: #73afea;
        }
        QPushButton:pressed {
            background: #c2dcfa;
        }
        QPushButton:disabled {
            background: #eef3f8;
            color: #8ba2b8;
            border-color: #d6e1ec;
        }
        #downloadButton {
            background: #1f6fd1;
            color: #ffffff;
            border: 1px solid #1f6fd1;
        }
        #downloadButton:hover {
            background: #185fb8;
        }
        #loginButton {
            background: #0f4f8f;
            color: #ffffff;
            border: 1px solid #0f4f8f;
        }
        #loginButton:hover {
            background: #0b427a;
        }
        QTreeWidget::item {
            min-height: 28px;
            border-radius: 6px;
            padding: 4px 6px;
        }
        QTreeWidget::item:selected {
            background: #d7ebff;
            color: #0b3a68;
        }
        QTreeWidget::item:hover {
            background: #edf6ff;
        }
        QProgressBar {
            background: #dbeafb;
            border: 1px solid #b8d5f1;
            border-radius: 7px;
            height: 16px;
            text-align: center;
            color: #12304f;
        }
        QProgressBar::chunk {
            background: #2f80ed;
            border-radius: 6px;
        }
        QStatusBar {
            background: #e6f1ff;
            color: #173b63;
            border-top: 1px solid #c8def5;
        }
        QSplitter::handle {
            background: #d8e9fb;
        }
        QScrollBar:vertical, QScrollBar:horizontal {
            background: #eef6ff;
            border: none;
            width: 12px;
            height: 12px;
        }
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
            background: #9bc7f2;
            border-radius: 6px;
            min-height: 24px;
            min-width: 24px;
        }
        """
    )


def display_download_type(value: str) -> str:
    if value == "menu_batch":
        return "메뉴 일괄 다운로드"
    if value == "single_post":
        return "개별 게시글 다운로드"
    return value or "-"


def open_path(path: str) -> bool:
    target = Path(path)
    if not target.exists():
        return False

    if QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve()))):
        return True

    try:
        if sys.platform.startswith("win"):
            os.startfile(str(target.resolve()))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target.resolve())])
        else:
            subprocess.Popen(["xdg-open", str(target.resolve())])
        return True
    except Exception:
        return False


def can_delete_archive_folder(path: str) -> bool:
    if not path:
        return False
    target = Path(path).resolve()
    archive_root = get_saved_posts_dir().resolve()
    try:
        target.relative_to(archive_root)
    except ValueError:
        return False
    # Folder management actions are intentionally limited to saved_posts so a
    # bad index entry cannot rename or delete an arbitrary user folder.
    return target.exists() and target.is_dir() and target != archive_root


def can_manage_archive_folder(path: str) -> bool:
    return can_delete_archive_folder(path)


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def update_post_meta_paths(folder_path: Path, local_view_path: Path) -> None:
    # Rename operations move folders after download, so stored paths in meta
    # need to follow the actual folder location.
    meta_path = folder_path / "meta.json"
    meta = read_json_file(meta_path)
    if not meta:
        return
    meta["folder_path"] = str(folder_path.resolve())
    meta["local_view_path"] = str(local_view_path.resolve())
    write_json_file(meta_path, meta)


def infer_download_type(post: dict[str, Any]) -> str:
    explicit = str(post.get("download_type") or "").strip()
    if explicit:
        return explicit
    if post.get("source_menu_url") or post.get("menu_id") or post.get("batch_id"):
        return "menu_batch"
    return "single_post"


def batch_summary_path(batch_id: str) -> Path:
    return get_batches_dir() / f"{batch_id}.json"


def load_batch_summary(batch_id: str) -> dict[str, Any]:
    if not batch_id:
        return {}
    path = batch_summary_path(batch_id)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def derive_menu_folder_path(posts: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    summary_folder = str(summary.get("menu_folder_path") or "")
    if summary_folder:
        return summary_folder
    for post in posts:
        folder_path = str(post.get("folder_path") or "")
        if folder_path:
            return str(Path(folder_path).parent)
    return ""


def make_value_label() -> QLabel:
    label = QLabel("-")
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    return label


def make_readonly_text_box(height: int = 54) -> QTextEdit:
    box = QTextEdit()
    box.setReadOnly(True)
    box.setAcceptRichText(False)
    box.setFixedHeight(height)
    box.setLineWrapMode(QTextEdit.WidgetWidth)
    box.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    box.setPlaceholderText("-")
    return box


def make_preview_browser() -> QTextBrowser:
    preview = QTextBrowser()
    preview.setOpenExternalLinks(False)
    preview.setMinimumHeight(260)
    preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    preview.setPlaceholderText("저장된 페이지 미리보기")
    return preview


class ProgressDialog(QDialog):
    # A single dialog is reused by both single-post and menu batch workers. The
    # worker only emits Qt signals; all UI updates stay on the main thread.
    cancel_requested = Signal()

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 360)
        self._running = True

        self.message_label = QLabel("다운로드 준비 중...")
        self.message_label.setWordWrap(True)
        self.progress_bar = QProgressBar()
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.cancel_button = QPushButton("취소")
        self.close_button = QPushButton("닫기")
        self.close_button.setEnabled(False)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.message_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.log_box, 1)
        layout.addLayout(button_layout)

        self.cancel_button.clicked.connect(self.request_cancel)
        self.close_button.clicked.connect(self.accept)
        self.set_indeterminate()

    def set_message(self, text: str) -> None:
        self.message_label.setText(text)

    def append_log(self, text: str) -> None:
        self.log_box.append(text)
        scrollbar = self.log_box.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_indeterminate(self) -> None:
        self.progress_bar.setRange(0, 0)

    def set_progress(self, current: int, total: int) -> None:
        if total <= 0:
            self.set_indeterminate()
            return
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(max(0, min(current, total)))

    def request_cancel(self) -> None:
        if not self._running:
            return
        self.cancel_button.setEnabled(False)
        self.set_message("취소 요청을 처리하는 중...")
        self.append_log("취소 요청을 처리하는 중...")
        self.cancel_requested.emit()

    def finish(self, message: str) -> None:
        self._running = False
        self.set_message(message)
        self.append_log(message)
        self.cancel_button.setEnabled(False)
        self.close_button.setEnabled(True)

    def mark_completed(self, message: str) -> None:
        self.finish(message)

    def mark_failed(self, message: str) -> None:
        self.finish(message)

    def mark_cancelled(self, message: str) -> None:
        self.finish(message)

    def closeEvent(self, event: Any) -> None:
        if not self._running:
            super().closeEvent(event)
            return

        answer = QMessageBox.question(
            self,
            "다운로드 취소",
            "다운로드가 진행 중입니다. 취소하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.request_cancel()
        event.ignore()


class SinglePostDownloadWorker(QThread):
    # Single post downloads can block on Playwright/network work. Running them
    # in a worker keeps the PySide UI responsive and enables cooperative cancel.
    progress_message = Signal(str)
    progress_value = Signal(int, int)
    duplicate_folder_found = Signal(str, str)
    completed = Signal(dict)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self._duplicate_event: Optional[threading.Event] = None
        self._duplicate_decision = False
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True
        if self._duplicate_event is not None:
            # If the worker is waiting for the duplicate-folder confirmation
            # dialog, cancellation should release that wait immediately.
            self._duplicate_decision = False
            self._duplicate_event.set()

    def is_cancel_requested(self) -> bool:
        return self._cancel_requested

    def confirm_existing_folder(self, folder: Path, title: str) -> bool:
        self._duplicate_decision = False
        self._duplicate_event = threading.Event()
        self.duplicate_folder_found.emit(str(folder.resolve()), title)
        self._duplicate_event.wait()
        return self._duplicate_decision

    def resolve_duplicate_confirmation(self, should_continue: bool) -> None:
        self._duplicate_decision = should_continue
        if self._duplicate_event is not None:
            self._duplicate_event.set()

    def run(self) -> None:
        try:
            meta = download_single_post(
                self.url,
                progress=self.progress_message.emit,
                progress_value=self.progress_value.emit,
                should_cancel=self.is_cancel_requested,
                confirm_existing_folder=self.confirm_existing_folder,
            )
            self.completed.emit(meta)
        except DownloadCancelledError as exc:
            self.cancelled.emit(str(exc))
        except AccessRequiredError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"다운로드 실패: {exc}")


class BatchDownloadWorker(QThread):
    # Menu downloads reuse the downloader's batch flow. Progress is reported as
    # both text logs and numeric values once the total post count is known.
    progress_message = Signal(str)
    progress_value = Signal(int, int)
    completed = Signal(dict)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def is_cancel_requested(self) -> bool:
        return self._cancel_requested

    def run(self) -> None:
        try:
            result = download_menu_posts(
                self.url,
                progress=self.progress_message.emit,
                progress_value=self.progress_value.emit,
                should_cancel=self.is_cancel_requested,
            )
            self.completed.emit(result.__dict__.copy())
        except DownloadCancelledError as exc:
            self.cancelled.emit(str(exc))
        except AccessRequiredError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"메뉴 다운로드 실패: {exc}")


class LoginWorker(QThread):
    progress = Signal(str)
    completed = Signal()
    failed = Signal(str)

    def run(self) -> None:
        try:
            setup_login_session(progress=self.progress.emit)
            self.completed.emit()
        except Exception as exc:
            self.failed.emit(f"로그인 세션 연결 실패: {exc}")


class SessionCheckWorker(QThread):
    completed = Signal(bool, str)

    def run(self) -> None:
        is_valid = check_saved_session()
        message = "네이버 로그인 세션 적용됨" if is_valid else SESSION_EXPIRED_MESSAGE
        self.completed.emit(is_valid, message)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_runtime_dirs()
        self.setWindowTitle(f"네이버 카페 아카이브 매니저 v{APP_VERSION}")
        for icon_path in (
            get_app_base_dir() / "assets" / "app_icon.ico",
            get_app_base_dir() / "assets" / "naver_cafe_archive_icon.ico",
        ):
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
                break
        self.resize(980, 620)

        self.posts: list[dict[str, Any]] = []
        self.selected_post: Optional[dict[str, Any]] = None
        self.selected_group: Optional[dict[str, Any]] = None
        self.download_worker: Optional[SinglePostDownloadWorker] = None
        self.batch_worker: Optional[BatchDownloadWorker] = None
        self.login_worker: Optional[LoginWorker] = None
        self.session_check_worker: Optional[SessionCheckWorker] = None
        self.session_check_dialog: Optional[QMessageBox] = None
        self.progress_dialog: Optional[ProgressDialog] = None

        self.mode_selector = QComboBox()
        self.mode_selector.addItems([DOWNLOAD_MODE_AUTO, DOWNLOAD_MODE_SINGLE, DOWNLOAD_MODE_MENU])
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("네이버 카페 게시글 주소를 붙여넣으세요")
        self.download_button = QPushButton("다운로드")
        self.download_button.setObjectName("downloadButton")
        self.login_button = QPushButton("네이버 로그인 세션 연결")
        self.login_button.setObjectName("loginButton")
        self.session_status_label = QLabel("세션 상태: 확인 중")
        self.session_status_label.setMinimumWidth(180)

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.mode_selector)
        top_layout.addWidget(self.url_input, 1)
        top_layout.addWidget(self.download_button)
        top_layout.addWidget(self.login_button)
        top_layout.addWidget(self.session_status_label)

        self.list_filter = QComboBox()
        self.list_filter.addItems([FILTER_ALL, FILTER_SINGLE, FILTER_MENU])
        self.post_tree = QTreeWidget()
        self.post_tree.setHeaderHidden(True)
        self.post_tree.setMinimumWidth(320)
        # The tree keeps old single-post archives visible while grouping newer
        # menu batch downloads by menu/batch metadata.
        left_panel = QWidget()
        left_panel.setObjectName("sidePanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("목록 필터"))
        left_layout.addWidget(self.list_filter)
        left_layout.addWidget(self.post_tree, 1)

        self.title_value = make_value_label()
        self.source_url_value = make_readonly_text_box()
        self.saved_at_value = make_value_label()
        self.image_count_value = make_value_label()
        self.folder_path_value = make_readonly_text_box()
        self.download_type_value = make_value_label()
        self.menu_title_value = make_value_label()
        self.menu_id_value = make_value_label()
        self.source_menu_url_value = make_readonly_text_box()
        self.batch_id_value = make_value_label()
        self.total_posts_value = make_value_label()
        self.batch_counts_value = make_value_label()

        details_layout = QFormLayout()
        details_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        details_layout.addRow("제목", self.title_value)
        details_layout.addRow("원본 주소", self.source_url_value)
        details_layout.addRow("저장일", self.saved_at_value)
        details_layout.addRow("이미지 수", self.image_count_value)
        details_layout.addRow("저장 폴더", self.folder_path_value)
        details_layout.addRow("다운로드 유형", self.download_type_value)
        details_layout.addRow("메뉴 제목", self.menu_title_value)
        details_layout.addRow("메뉴 ID", self.menu_id_value)
        details_layout.addRow("원본 메뉴 주소", self.source_menu_url_value)
        details_layout.addRow("배치 ID", self.batch_id_value)
        details_layout.addRow("게시글 수", self.total_posts_value)
        details_layout.addRow("처리 결과", self.batch_counts_value)
        details_panel = QWidget()
        details_panel.setObjectName("detailsPanel")
        details_panel.setLayout(details_layout)

        self.open_page_button = QPushButton("저장 페이지 열기")
        self.open_folder_button = QPushButton("저장 폴더 열기")
        self.rename_folder_button = QPushButton("폴더명 변경")
        self.delete_button = QPushButton("저장 항목 삭제")
        self.refresh_button = QPushButton("목록 새로고침")
        self.preview_browser = make_preview_browser()

        side_button_layout = QVBoxLayout()
        side_button_layout.addWidget(self.open_page_button)
        side_button_layout.addWidget(self.open_folder_button)
        side_button_layout.addWidget(self.rename_folder_button)
        side_button_layout.addWidget(self.delete_button)
        side_button_layout.addWidget(self.refresh_button)
        side_button_layout.addStretch(1)

        preview_layout = QHBoxLayout()
        preview_layout.addWidget(self.preview_browser, 1)
        preview_layout.addLayout(side_button_layout)
        preview_panel = QWidget()
        preview_panel.setObjectName("previewPanel")
        preview_panel.setLayout(preview_layout)

        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(details_panel)
        right_splitter.addWidget(preview_panel)
        right_splitter.setChildrenCollapsible(False)
        right_splitter.setStretchFactor(0, 0)
        right_splitter.setStretchFactor(1, 1)
        right_splitter.setSizes([220, 380])

        right_panel = QWidget()
        right_panel.setMinimumWidth(0)
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(right_splitter, 1)

        splitter = QSplitter()
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([300, 680])

        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QVBoxLayout(root)
        root_layout.addLayout(top_layout)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())

        self.download_button.clicked.connect(self.start_download)
        self.url_input.returnPressed.connect(self.start_download)
        self.url_input.textChanged.connect(self.update_download_button_text)
        self.mode_selector.currentTextChanged.connect(lambda _text: self.update_download_button_text(self.url_input.text()))
        self.list_filter.currentTextChanged.connect(lambda _text: self.refresh_posts())
        self.login_button.clicked.connect(self.start_login_setup)
        self.refresh_button.clicked.connect(self.refresh_posts)
        self.open_page_button.clicked.connect(self.open_selected_page)
        self.open_folder_button.clicked.connect(self.open_selected_folder)
        self.rename_folder_button.clicked.connect(self.rename_selected_folder)
        self.delete_button.clicked.connect(self.delete_selected_archive)
        self.post_tree.currentItemChanged.connect(self.handle_selection_changed)

        self.refresh_posts()
        self.update_download_button_text(self.url_input.text())
        self.show_post_details(None)
        self.start_session_check()

    def set_busy(self, busy: bool) -> None:
        self.download_button.setDisabled(busy)
        self.login_button.setDisabled(busy)

    def show_progress_dialog(self, title: str, worker: SinglePostDownloadWorker | BatchDownloadWorker) -> ProgressDialog:
        if self.progress_dialog is not None:
            self.progress_dialog.close()

        dialog = ProgressDialog(title, self)
        dialog.cancel_requested.connect(worker.request_cancel)
        self.progress_dialog = dialog
        dialog.show()
        return dialog

    def handle_progress_message(self, message: str) -> None:
        self.statusBar().showMessage(message)
        if self.progress_dialog is not None:
            self.progress_dialog.set_message(message)
            self.progress_dialog.append_log(message)

    def handle_progress_value(self, current: int, total: int) -> None:
        if self.progress_dialog is not None:
            self.progress_dialog.set_progress(current, total)

    def refresh_posts(self) -> None:
        self.posts = load_archive_index()
        self.post_tree.clear()
        current_filter = self.list_filter.currentText()

        single_root = QTreeWidgetItem(["개별 다운로드"])
        menu_root = QTreeWidgetItem(["메뉴 다운로드"])
        single_root.setData(0, Qt.UserRole, {"kind": "root"})
        menu_root.setData(0, Qt.UserRole, {"kind": "root"})

        if current_filter in {FILTER_ALL, FILTER_SINGLE}:
            self.post_tree.addTopLevelItem(single_root)
        if current_filter in {FILTER_ALL, FILTER_MENU}:
            self.post_tree.addTopLevelItem(menu_root)

        menu_groups: dict[str, dict[str, Any]] = {}
        for post in self.posts:
            download_type = infer_download_type(post)
            post = {**post, "download_type": download_type}
            if download_type == "menu_batch":
                key = str(post.get("batch_id") or post.get("source_menu_url") or post.get("menu_id") or "menu")
                group = menu_groups.setdefault(
                    key,
                    {
                        "posts": [],
                        "menu_title": post.get("menu_title"),
                        "menu_id": post.get("menu_id"),
                        "source_menu_url": post.get("source_menu_url"),
                        "batch_id": post.get("batch_id"),
                    },
                )
                group["posts"].append(post)
                for field in ("menu_title", "menu_id", "source_menu_url", "batch_id"):
                    if not group.get(field) and post.get(field):
                        group[field] = post.get(field)
            elif current_filter in {FILTER_ALL, FILTER_SINGLE}:
                title = str(post.get("title") or "(제목 없음)")
                item = QTreeWidgetItem([title])
                item.setData(0, Qt.UserRole, {"kind": "post", "post": post})
                single_root.addChild(item)

        if current_filter in {FILTER_ALL, FILTER_MENU}:
            for group in menu_groups.values():
                posts = group["posts"]
                summary = load_batch_summary(str(group.get("batch_id") or ""))
                label_base = str(group.get("menu_title") or group.get("menu_id") or "메뉴")
                saved_at = str(summary.get("completed_at") or posts[0].get("saved_at") or "")
                label = f"{label_base} / {saved_at[:19]}" if saved_at else label_base
                group_data = {
                    "kind": "menu_group",
                    "menu_title": group.get("menu_title"),
                    "menu_id": group.get("menu_id"),
                    "source_menu_url": group.get("source_menu_url"),
                    "batch_id": group.get("batch_id"),
                    "posts": posts,
                    "summary": summary,
                    "folder_path": derive_menu_folder_path(posts, summary),
                }
                group_item = QTreeWidgetItem([label])
                group_item.setData(0, Qt.UserRole, group_data)
                menu_root.addChild(group_item)
                for post in posts:
                    item = QTreeWidgetItem([str(post.get("title") or "(제목 없음)")])
                    item.setData(0, Qt.UserRole, {"kind": "post", "post": post})
                    group_item.addChild(item)

        self.post_tree.expandAll()
        self.statusBar().showMessage(f"저장된 게시글 {len(self.posts)}개")

    def update_download_button_text(self, url: str) -> None:
        mode = self.mode_selector.currentText()
        if mode == DOWNLOAD_MODE_SINGLE:
            self.download_button.setText("개별 게시글 다운로드")
        elif mode == DOWNLOAD_MODE_MENU:
            self.download_button.setText("메뉴 전체 다운로드")
        else:
            self.download_button.setText("다운로드")

    def start_session_check(self) -> None:
        self.set_busy(True)
        self.statusBar().showMessage("저장된 네이버 로그인 세션을 확인하는 중...")
        self.show_session_check_dialog("세션 상태 확인 중", "네이버 로그인 세션 상태를 확인하는 중입니다...")
        self.session_check_worker = SessionCheckWorker()
        self.session_check_worker.completed.connect(self.handle_session_check_completed)
        self.session_check_worker.finished.connect(lambda: self.set_busy(False))
        self.session_check_worker.start()

    def show_session_check_dialog(self, title: str, message: str) -> None:
        if self.session_check_dialog is not None:
            self.close_session_check_dialog()

        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setIcon(QMessageBox.Information)
        dialog.setStandardButtons(QMessageBox.NoButton)
        dialog.setModal(False)
        self.session_check_dialog = dialog
        dialog.show()

    def finish_session_check_dialog(self, title: str, message: str, is_valid: bool) -> None:
        self.close_session_check_dialog()

        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setIcon(QMessageBox.Information if is_valid else QMessageBox.Warning)
        dialog.setStandardButtons(QMessageBox.Ok)
        dialog.buttonClicked.connect(lambda _button: self.close_session_check_dialog())
        self.session_check_dialog = dialog
        dialog.show()

    def close_session_check_dialog(self) -> None:
        if self.session_check_dialog is None:
            return

        dialog = self.session_check_dialog
        self.session_check_dialog = None
        dialog.hide()
        dialog.done(0)
        dialog.deleteLater()

    def handle_session_check_completed(self, is_valid: bool, message: str) -> None:
        if is_valid:
            self.session_status_label.setText("세션 상태: 적용됨")
            self.statusBar().showMessage(message)
            self.finish_session_check_dialog("세션 확인 완료", "네이버 로그인 세션이 적용되어 있습니다.", True)
            return

        self.session_status_label.setText("세션 상태: 확인 필요")
        self.statusBar().showMessage(message)
        self.finish_session_check_dialog("로그인 세션 확인 필요", message, False)

    def handle_selection_changed(self, current: Optional[QTreeWidgetItem]) -> None:
        data = current.data(0, Qt.UserRole) if current else None
        if not isinstance(data, dict):
            data = {}

        kind = data.get("kind")
        if kind == "post":
            self.selected_post = data.get("post")
            self.selected_group = None
            self.show_post_details(self.selected_post)
        elif kind == "menu_group":
            self.selected_post = None
            self.selected_group = data
            self.show_menu_group_details(data)
        else:
            self.selected_post = None
            self.selected_group = None
            self.show_post_details(None)

    def show_post_details(self, post: Optional[dict[str, Any]]) -> None:
        if not post:
            self.title_value.setText("-")
            self.source_url_value.setPlainText("")
            self.saved_at_value.setText("-")
            self.image_count_value.setText("-")
            self.folder_path_value.setPlainText("")
            self.download_type_value.setText("-")
            self.menu_title_value.setText("-")
            self.menu_id_value.setText("-")
            self.source_menu_url_value.setPlainText("")
            self.batch_id_value.setText("-")
            self.total_posts_value.setText("-")
            self.batch_counts_value.setText("-")
            self.preview_browser.setHtml("<p style='color:#777;'>저장된 페이지 미리보기</p>")
            self.open_page_button.setEnabled(False)
            self.open_folder_button.setEnabled(False)
            self.rename_folder_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        self.title_value.setText(str(post.get("title") or "-"))
        self.source_url_value.setPlainText(str(post.get("source_url") or ""))
        self.saved_at_value.setText(str(post.get("saved_at") or "-"))
        self.image_count_value.setText(str(post.get("image_count") or 0))
        self.folder_path_value.setPlainText(str(post.get("folder_path") or ""))
        self.download_type_value.setText(display_download_type(infer_download_type(post)))
        self.menu_title_value.setText(str(post.get("menu_title") or "-"))
        self.menu_id_value.setText(str(post.get("menu_id") or "-"))
        self.source_menu_url_value.setPlainText(str(post.get("source_menu_url") or ""))
        self.batch_id_value.setText(str(post.get("batch_id") or "-"))
        self.total_posts_value.setText("-")
        self.batch_counts_value.setText("-")
        self.update_page_preview(str(post.get("local_view_path") or ""))
        self.open_page_button.setEnabled(True)
        self.open_folder_button.setEnabled(True)
        self.rename_folder_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def show_menu_group_details(self, group: dict[str, Any]) -> None:
        posts = group.get("posts") if isinstance(group.get("posts"), list) else []
        summary = group.get("summary") if isinstance(group.get("summary"), dict) else {}
        title = str(group.get("menu_title") or group.get("menu_id") or "메뉴 다운로드")
        self.title_value.setText(title)
        self.source_url_value.setPlainText("")
        self.saved_at_value.setText(str(summary.get("completed_at") or "-"))
        self.image_count_value.setText("-")
        self.folder_path_value.setPlainText(str(group.get("folder_path") or ""))
        self.download_type_value.setText(display_download_type("menu_batch"))
        self.menu_title_value.setText(str(group.get("menu_title") or "-"))
        self.menu_id_value.setText(str(group.get("menu_id") or "-"))
        self.source_menu_url_value.setPlainText(str(group.get("source_menu_url") or ""))
        self.batch_id_value.setText(str(group.get("batch_id") or "-"))
        self.total_posts_value.setText(str(summary.get("total_found") or len(posts)))
        downloaded = summary.get("downloaded_count", len(posts))
        skipped = summary.get("skipped_count", "-")
        failed = summary.get("failed_count", "-")
        self.batch_counts_value.setText(f"다운로드 {downloaded}, 스킵 {skipped}, 실패 {failed}")
        self.preview_browser.setHtml("<p style='color:#777;'>메뉴 그룹에는 페이지 미리보기가 없습니다.</p>")
        self.open_page_button.setEnabled(False)
        self.open_folder_button.setEnabled(bool(group.get("folder_path")))
        self.rename_folder_button.setEnabled(bool(group.get("folder_path")))
        self.delete_button.setEnabled(bool(group.get("folder_path")))

    def update_page_preview(self, local_view_path: str) -> None:
        path = Path(local_view_path)
        if not local_view_path or not path.exists():
            self.preview_browser.setHtml("<p style='color:#777;'>미리볼 수 있는 저장 페이지가 없습니다.</p>")
            return
        self.preview_browser.setSource(QUrl.fromLocalFile(str(path.resolve())))

    def start_download(self) -> None:
        if not self.download_button.isEnabled():
            return
        if self.download_worker is not None and self.download_worker.isRunning():
            return
        if self.batch_worker is not None and self.batch_worker.isRunning():
            return

        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "입력 필요", "주소를 입력해주세요.")
            return

        parsed = parse_naver_cafe_url_type(url)
        mode = self.mode_selector.currentText()
        # Mode validation happens before starting a worker so unsupported or
        # mismatched addresses fail fast with a Korean UI message.
        if parsed.url_type == "unsupported":
            QMessageBox.warning(self, "지원하지 않는 주소", "지원하지 않는 네이버 카페 주소입니다.")
            return
        if mode == DOWNLOAD_MODE_SINGLE and parsed.url_type == "menu":
            QMessageBox.warning(self, "모드 확인", "이 주소는 메뉴/게시판 주소입니다. 메뉴 전체 다운로드 모드를 선택해주세요.")
            return
        if mode == DOWNLOAD_MODE_MENU and parsed.url_type == "single_post":
            QMessageBox.warning(self, "모드 확인", "이 주소는 개별 게시글 주소입니다. 개별 게시글 다운로드 모드를 선택해주세요.")
            return

        if parsed.url_type == "menu":
            self.start_batch_download(url)
            return

        # Single-post mode checks article identity before download. Menu batch
        # mode performs the same check internally and skips duplicates.
        article_key = make_article_key(
            club_id=parsed.club_id,
            article_id=parsed.article_id,
            cafe_name=parsed.cafe_name,
            source_url=parsed.normalized_url,
        )
        if has_article_key(article_key):
            answer = QMessageBox.question(
                self,
                "이미 저장된 게시글",
                "이미 저장된 게시글입니다. 다시 다운로드할까요?",
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if answer != QMessageBox.Ok:
                self.statusBar().showMessage("다운로드가 취소되었습니다.")
                return

        self.set_busy(True)
        self.statusBar().showMessage("개별 게시글 다운로드 중...")
        self.download_worker = SinglePostDownloadWorker(url)
        dialog = self.show_progress_dialog("개별 게시글 다운로드 진행 중", self.download_worker)
        dialog.set_indeterminate()
        dialog.append_log("다운로드 준비 중...")
        self.download_worker.progress_message.connect(self.handle_progress_message)
        self.download_worker.progress_value.connect(self.handle_progress_value)
        self.download_worker.duplicate_folder_found.connect(self.handle_duplicate_folder_found)
        self.download_worker.completed.connect(self.handle_download_completed)
        self.download_worker.failed.connect(self.handle_download_failed)
        self.download_worker.cancelled.connect(self.handle_download_cancelled)
        self.download_worker.finished.connect(lambda: self.set_busy(False))
        self.download_worker.start()

    def start_batch_download(self, url: str) -> None:
        self.set_busy(True)
        self.statusBar().showMessage("메뉴 전체 다운로드 중...")
        self.batch_worker = BatchDownloadWorker(url)
        dialog = self.show_progress_dialog("메뉴 전체 다운로드 진행 중", self.batch_worker)
        dialog.set_indeterminate()
        dialog.append_log("다운로드 준비 중...")
        self.batch_worker.progress_message.connect(self.handle_progress_message)
        self.batch_worker.progress_value.connect(self.handle_progress_value)
        self.batch_worker.completed.connect(self.handle_batch_download_completed)
        self.batch_worker.failed.connect(self.handle_download_failed)
        self.batch_worker.cancelled.connect(self.handle_download_cancelled)
        self.batch_worker.finished.connect(lambda: self.set_busy(False))
        self.batch_worker.start()

    def handle_duplicate_folder_found(self, folder_path: str, title: str) -> None:
        answer = QMessageBox.question(
            self,
            "이미 존재하는 폴더",
            f"'{title}' 이름의 저장 폴더가 이미 존재합니다.\n\n그래도 다운로드할까요?\n계속하면 새 폴더 이름에 _2, _3 같은 번호가 붙습니다.",
            QMessageBox.Ok | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        should_continue = answer == QMessageBox.Ok
        if self.download_worker is not None:
            self.download_worker.resolve_duplicate_confirmation(should_continue)

    def handle_download_completed(self, meta: dict[str, Any]) -> None:
        upsert_archive_entry(make_index_entry(meta))
        self.refresh_posts()
        self.statusBar().showMessage("다운로드 완료")
        if self.progress_dialog is not None:
            self.progress_dialog.mark_completed("다운로드 완료")

    def handle_download_failed(self, message: str) -> None:
        self.statusBar().showMessage("다운로드 실패")
        if self.progress_dialog is not None:
            self.progress_dialog.mark_failed(message or "다운로드 실패")
        else:
            QMessageBox.warning(self, "다운로드 실패", message or "다운로드 실패")

    def handle_download_cancelled(self, message: str) -> None:
        self.refresh_posts()
        self.statusBar().showMessage(message or "다운로드가 취소되었습니다.")
        if self.progress_dialog is not None:
            self.progress_dialog.mark_cancelled(message or "다운로드가 취소되었습니다.")

    def handle_batch_download_completed(self, result: dict[str, Any] | BatchDownloadResult) -> None:
        self.refresh_posts()
        if isinstance(result, dict):
            downloaded_count = result.get("downloaded_count", 0)
            skipped_count = result.get("skipped_count", 0)
            failed_count = result.get("failed_count", 0)
        else:
            downloaded_count = result.downloaded_count
            skipped_count = result.skipped_count
            failed_count = result.failed_count
        message = (
            f"메뉴 다운로드 완료: 다운로드 {downloaded_count}, "
            f"스킵 {skipped_count}, 실패 {failed_count}"
        )
        self.statusBar().showMessage(message)
        if self.progress_dialog is not None:
            self.progress_dialog.mark_completed(message)

    def start_login_setup(self) -> None:
        self.set_busy(True)
        self.statusBar().showMessage("로그인 세션 연결 중...")
        self.login_worker = LoginWorker()
        self.login_worker.progress.connect(self.statusBar().showMessage)
        self.login_worker.completed.connect(self.handle_login_completed)
        self.login_worker.failed.connect(self.handle_login_failed)
        self.login_worker.finished.connect(lambda: self.set_busy(False))
        self.login_worker.start()

    def handle_login_completed(self) -> None:
        self.session_status_label.setText("세션 상태: 적용됨")
        self.statusBar().showMessage("로그인 세션 연결 완료")
        QMessageBox.information(self, "완료", "로그인 세션 연결이 완료되었습니다.")

    def handle_login_failed(self, message: str) -> None:
        self.statusBar().showMessage("로그인 세션 연결 실패")
        QMessageBox.warning(self, "오류", message)

    def open_selected_page(self) -> None:
        if not self.selected_post or not open_path(str(self.selected_post.get("local_view_path") or "")):
            QMessageBox.warning(self, "오류", "저장된 페이지를 열 수 없습니다.")

    def open_selected_folder(self) -> None:
        folder_path = ""
        if self.selected_post:
            folder_path = str(self.selected_post.get("folder_path") or "")
        elif self.selected_group:
            folder_path = str(self.selected_group.get("folder_path") or "")
        if not folder_path or not open_path(folder_path):
            QMessageBox.warning(self, "오류", "저장 폴더를 열 수 없습니다.")

    def ask_new_folder_name(self, current_folder: Path, title: str) -> Optional[Path]:
        value, ok = QInputDialog.getText(self, "폴더명 변경", "새 폴더명을 입력하세요:", text=current_folder.name)
        if not ok:
            return None

        safe_name = sanitize_filename(value)
        if not safe_name:
            QMessageBox.warning(self, "변경 실패", "폴더명을 입력해주세요.")
            return None

        target = current_folder.parent / safe_name
        if target.resolve() == current_folder.resolve():
            self.statusBar().showMessage("폴더명이 변경되지 않았습니다.")
            return None
        if target.exists():
            QMessageBox.warning(self, "변경 실패", f"'{safe_name}' 폴더가 이미 존재합니다.")
            return None

        answer = QMessageBox.question(
            self,
            "폴더명 변경 확인",
            f"'{current_folder.name}' 폴더명을 '{safe_name}'로 변경할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return None
        return target

    def rename_selected_folder(self) -> None:
        if self.selected_group:
            self.rename_selected_menu_group_folder()
            return
        if self.selected_post:
            self.rename_selected_post_folder()
            return
        QMessageBox.warning(self, "변경 실패", "폴더명을 변경할 항목을 선택해주세요.")

    def rename_selected_post_folder(self) -> None:
        if not self.selected_post:
            return

        current_folder = Path(str(self.selected_post.get("folder_path") or "")).resolve()
        if not can_manage_archive_folder(str(current_folder)):
            QMessageBox.warning(self, "변경 실패", "저장 폴더명을 변경할 수 없습니다.")
            return

        target_folder = self.ask_new_folder_name(current_folder, str(self.selected_post.get("title") or ""))
        if target_folder is None:
            return

        try:
            current_folder.rename(target_folder)
            local_view_path = target_folder / "view.html"
            update_archive_entry_paths(
                str(self.selected_post.get("id") or ""),
                folder_path=str(target_folder.resolve()),
                local_view_path=str(local_view_path.resolve()),
            )
            update_post_meta_paths(target_folder, local_view_path)
        except Exception as exc:
            QMessageBox.warning(self, "변경 실패", f"폴더명을 변경할 수 없습니다: {exc}")
            return

        self.selected_post = None
        self.show_post_details(None)
        self.refresh_posts()
        self.statusBar().showMessage("폴더명 변경 완료")

    def rename_selected_menu_group_folder(self) -> None:
        if not self.selected_group:
            return

        current_folder = Path(str(self.selected_group.get("folder_path") or "")).resolve()
        if not can_manage_archive_folder(str(current_folder)):
            QMessageBox.warning(self, "변경 실패", "메뉴 저장 폴더명을 변경할 수 없습니다.")
            return

        target_folder = self.ask_new_folder_name(current_folder, str(self.selected_group.get("menu_title") or ""))
        if target_folder is None:
            return

        posts = self.selected_group.get("posts")
        post_list = posts if isinstance(posts, list) else []
        path_updates: dict[str, dict[str, str]] = {}

        try:
            current_folder.rename(target_folder)
            for post in post_list:
                post_id = str(post.get("id") or "")
                old_folder = Path(str(post.get("folder_path") or ""))
                if not post_id or not old_folder:
                    continue
                try:
                    relative_folder = old_folder.resolve().relative_to(current_folder)
                except ValueError:
                    continue
                new_folder = target_folder / relative_folder
                new_view = new_folder / "view.html"
                path_updates[post_id] = {
                    "folder_path": str(new_folder.resolve()),
                    "local_view_path": str(new_view.resolve()),
                }
                update_post_meta_paths(new_folder, new_view)

            if path_updates:
                update_archive_entries_paths(path_updates)

            # Batch summaries keep a menu root path for group-level browsing.
            # Update it so the folder-open action keeps working after a menu folder rename.
            batch_id = str(self.selected_group.get("batch_id") or "")
            summary_path = batch_summary_path(batch_id)
            summary = read_json_file(summary_path)
            if summary:
                summary["menu_folder_path"] = str(target_folder.resolve())
                write_json_file(summary_path, summary)
        except Exception as exc:
            QMessageBox.warning(self, "변경 실패", f"메뉴 저장 폴더명을 변경할 수 없습니다: {exc}")
            return

        self.selected_group = None
        self.selected_post = None
        self.show_post_details(None)
        self.refresh_posts()
        self.statusBar().showMessage("메뉴 폴더명 변경 완료")

    def delete_selected_archive(self) -> None:
        if self.selected_group:
            self.delete_selected_menu_group()
            return

        if not self.selected_post:
            QMessageBox.warning(self, "삭제 실패", "삭제할 게시글을 선택해주세요.")
            return

        title = str(self.selected_post.get("title") or "(제목 없음)")
        folder_path = str(self.selected_post.get("folder_path") or "")
        if not can_delete_archive_folder(folder_path):
            QMessageBox.warning(self, "삭제 실패", "저장 폴더를 삭제할 수 없습니다.")
            return

        answer = QMessageBox.question(
            self,
            "삭제 확인",
            f"'{title}' 저장 폴더와 목록 항목을 삭제할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            shutil.rmtree(Path(folder_path))
            remove_archive_entry(str(self.selected_post.get("id") or ""))
        except Exception as exc:
            QMessageBox.warning(self, "삭제 실패", f"저장 폴더를 삭제할 수 없습니다: {exc}")
            return

        self.selected_post = None
        self.show_post_details(None)
        self.refresh_posts()
        self.statusBar().showMessage("삭제 완료")

    def delete_selected_menu_group(self) -> None:
        if not self.selected_group:
            QMessageBox.warning(self, "삭제 실패", "삭제할 메뉴 그룹을 선택해주세요.")
            return

        folder_path = str(self.selected_group.get("folder_path") or "")
        if not can_delete_archive_folder(folder_path):
            QMessageBox.warning(self, "삭제 실패", "메뉴 저장 폴더를 삭제할 수 없습니다.")
            return

        posts = self.selected_group.get("posts")
        post_list = posts if isinstance(posts, list) else []
        post_ids = {str(post.get("id") or "") for post in post_list if str(post.get("id") or "")}
        menu_title = str(self.selected_group.get("menu_title") or self.selected_group.get("menu_id") or "메뉴 다운로드")

        answer = QMessageBox.question(
            self,
            "메뉴 폴더 삭제 확인",
            f"'{menu_title}' 메뉴 저장 폴더와 포함된 목록 항목 {len(post_ids)}개를 삭제할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            shutil.rmtree(Path(folder_path))
            remove_archive_entries(post_ids)
        except Exception as exc:
            QMessageBox.warning(self, "삭제 실패", f"메뉴 저장 폴더를 삭제할 수 없습니다: {exc}")
            return

        self.selected_group = None
        self.selected_post = None
        self.show_post_details(None)
        self.refresh_posts()
        self.statusBar().showMessage("메뉴 폴더 삭제 완료")

    def closeEvent(self, event: Any) -> None:
        self.close_session_check_dialog()
        for worker in (self.download_worker, self.batch_worker, self.login_worker, self.session_check_worker):
            if worker is not None and worker.isRunning():
                if hasattr(worker, "request_cancel"):
                    worker.request_cancel()
                worker.quit()
                worker.wait(3000)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    apply_app_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
