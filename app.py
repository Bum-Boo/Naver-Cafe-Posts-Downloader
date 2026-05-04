from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import QUrl

from downloader.naver_cafe_downloader import (
    SESSION_EXPIRED_MESSAGE,
    AccessRequiredError,
    DownloadCancelledError,
    check_saved_session,
    download_post,
    setup_login_session,
)
from storage.archive_index import load_archive_index, make_index_entry, remove_archive_entry, upsert_archive_entry


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
    archive_root = Path("./saved_posts").resolve()
    try:
        target.relative_to(archive_root)
    except ValueError:
        return False
    return target.exists() and target.is_dir() and target != archive_root


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


class DownloadWorker(QThread):
    progress = Signal(str)
    duplicate_folder_found = Signal(str, str)
    completed = Signal(dict)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self._duplicate_event: Optional[threading.Event] = None
        self._duplicate_decision = False

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
            meta = download_post(
                self.url,
                progress=self.progress.emit,
                confirm_existing_folder=self.confirm_existing_folder,
            )
            self.completed.emit(meta)
        except DownloadCancelledError as exc:
            self.cancelled.emit(str(exc))
        except AccessRequiredError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"다운로드 실패: {exc}")


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
        self.setWindowTitle("Naver Cafe Archive Manager")
        self.resize(980, 620)

        self.posts: list[dict[str, Any]] = []
        self.selected_post: Optional[dict[str, Any]] = None
        self.download_worker: Optional[DownloadWorker] = None
        self.login_worker: Optional[LoginWorker] = None
        self.session_check_worker: Optional[SessionCheckWorker] = None
        self.session_check_dialog: Optional[QMessageBox] = None

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("네이버 카페 게시글 URL을 붙여넣으세요")
        self.download_button = QPushButton("Download")
        self.login_button = QPushButton("네이버 로그인 세션 연결")
        self.session_status_label = QLabel("세션 상태: 확인 중")
        self.session_status_label.setMinimumWidth(180)

        top_layout = QHBoxLayout()
        top_layout.addWidget(self.url_input, 1)
        top_layout.addWidget(self.download_button)
        top_layout.addWidget(self.login_button)
        top_layout.addWidget(self.session_status_label)

        self.post_list = QListWidget()
        self.post_list.setMinimumWidth(300)

        self.title_value = make_value_label()
        self.source_url_value = make_readonly_text_box()
        self.saved_at_value = make_value_label()
        self.image_count_value = make_value_label()
        self.folder_path_value = make_readonly_text_box()

        details_layout = QFormLayout()
        details_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        details_layout.addRow("title", self.title_value)
        details_layout.addRow("source URL", self.source_url_value)
        details_layout.addRow("saved date", self.saved_at_value)
        details_layout.addRow("image count", self.image_count_value)
        details_layout.addRow("local folder", self.folder_path_value)
        details_panel = QWidget()
        details_panel.setLayout(details_layout)

        self.open_page_button = QPushButton("Open Local Page")
        self.open_folder_button = QPushButton("Open Folder")
        self.delete_button = QPushButton("Delete Archive")
        self.refresh_button = QPushButton("Refresh List")
        self.preview_browser = make_preview_browser()

        side_button_layout = QVBoxLayout()
        side_button_layout.addWidget(self.open_page_button)
        side_button_layout.addWidget(self.open_folder_button)
        side_button_layout.addWidget(self.delete_button)
        side_button_layout.addWidget(self.refresh_button)
        side_button_layout.addStretch(1)

        preview_layout = QHBoxLayout()
        preview_layout.addWidget(self.preview_browser, 1)
        preview_layout.addLayout(side_button_layout)
        preview_panel = QWidget()
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
        splitter.addWidget(self.post_list)
        splitter.addWidget(right_panel)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([300, 680])

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.addLayout(top_layout)
        root_layout.addWidget(splitter, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())

        self.download_button.clicked.connect(self.start_download)
        self.url_input.returnPressed.connect(self.start_download)
        self.login_button.clicked.connect(self.start_login_setup)
        self.refresh_button.clicked.connect(self.refresh_posts)
        self.open_page_button.clicked.connect(self.open_selected_page)
        self.open_folder_button.clicked.connect(self.open_selected_folder)
        self.delete_button.clicked.connect(self.delete_selected_archive)
        self.post_list.currentItemChanged.connect(self.handle_selection_changed)

        self.refresh_posts()
        self.start_session_check()

    def set_busy(self, busy: bool) -> None:
        self.download_button.setDisabled(busy)
        self.login_button.setDisabled(busy)

    def refresh_posts(self) -> None:
        self.posts = load_archive_index()
        self.post_list.clear()
        for post in self.posts:
            item = QListWidgetItem(post.get("title") or "(제목 없음)")
            item.setData(Qt.UserRole, post)
            self.post_list.addItem(item)
        self.statusBar().showMessage(f"저장된 게시글 {len(self.posts)}개")

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

    def handle_selection_changed(self, current: Optional[QListWidgetItem]) -> None:
        self.selected_post = current.data(Qt.UserRole) if current else None
        self.show_post_details(self.selected_post)

    def show_post_details(self, post: Optional[dict[str, Any]]) -> None:
        if not post:
            self.title_value.setText("-")
            self.source_url_value.setPlainText("")
            self.saved_at_value.setText("-")
            self.image_count_value.setText("-")
            self.folder_path_value.setPlainText("")
            self.preview_browser.setHtml("<p style='color:#777;'>저장된 페이지 미리보기</p>")
            return

        self.title_value.setText(str(post.get("title") or "-"))
        self.source_url_value.setPlainText(str(post.get("source_url") or ""))
        self.saved_at_value.setText(str(post.get("saved_at") or "-"))
        self.image_count_value.setText(str(post.get("image_count") or 0))
        self.folder_path_value.setPlainText(str(post.get("folder_path") or ""))
        self.update_page_preview(str(post.get("local_view_path") or ""))

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

        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "입력 필요", "URL을 입력해주세요.")
            return

        self.set_busy(True)
        self.statusBar().showMessage("네이버 카페 게시글을 다운로드하는 중...")
        self.download_worker = DownloadWorker(url)
        self.download_worker.progress.connect(self.statusBar().showMessage)
        self.download_worker.duplicate_folder_found.connect(self.handle_duplicate_folder_found)
        self.download_worker.completed.connect(self.handle_download_completed)
        self.download_worker.failed.connect(self.handle_download_failed)
        self.download_worker.cancelled.connect(self.handle_download_cancelled)
        self.download_worker.finished.connect(lambda: self.set_busy(False))
        self.download_worker.start()

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
        QMessageBox.information(self, "완료", "다운로드 완료")

    def handle_download_failed(self, message: str) -> None:
        self.statusBar().showMessage("다운로드 실패")
        QMessageBox.warning(self, "다운로드 실패", message or "다운로드 실패")

    def handle_download_cancelled(self, message: str) -> None:
        self.statusBar().showMessage(message or "다운로드가 취소되었습니다.")

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
        if not self.selected_post or not open_path(str(self.selected_post.get("folder_path") or "")):
            QMessageBox.warning(self, "오류", "저장 폴더를 열 수 없습니다.")

    def delete_selected_archive(self) -> None:
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

    def closeEvent(self, event: Any) -> None:
        self.close_session_check_dialog()
        for worker in (self.download_worker, self.login_worker, self.session_check_worker):
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(3000)
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
