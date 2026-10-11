from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path

from PySide6.QtCore import Qt

from app import SinglePostDownloadWorker


class DuplicateConfirmationCancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = SinglePostDownloadWorker("https://cafe.naver.com/synthetic/1")
        self.results: list[bool] = []
        self.thread = threading.Thread(
            target=lambda: self.results.append(
                self.worker.confirm_existing_folder(Path("synthetic-unused-folder"), "Synthetic title")
            ),
            daemon=True,
        )
        self.addCleanup(self.release_confirmation)

    def release_confirmation(self) -> None:
        self.worker.resolve_duplicate_confirmation(False)
        if self.thread.ident is not None:
            self.thread.join(1)

    def start_waiting(self) -> None:
        self.thread.start()
        deadline = time.monotonic() + 1
        while self.worker._duplicate_event is None and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertIsNotNone(self.worker._duplicate_event)

    def assert_finished_with(self, decision: bool) -> None:
        self.thread.join(1)
        self.assertFalse(self.thread.is_alive(), "Confirmation must finish without an extra UI response")
        self.assertEqual(self.results, [decision])
        self.assertIsNone(self.worker._duplicate_event)

    def test_cancel_before_confirmation_does_not_wait(self) -> None:
        self.worker.request_cancel()
        self.thread.start()
        self.assert_finished_with(False)

    def test_cancel_during_confirmation_releases_wait(self) -> None:
        self.start_waiting()
        self.worker.request_cancel()
        self.assert_finished_with(False)

    def test_user_approval_still_allows_download(self) -> None:
        self.start_waiting()
        self.worker.resolve_duplicate_confirmation(True)
        self.assert_finished_with(True)

    def test_late_approval_cannot_override_cancellation(self) -> None:
        # Both actions occur during signal delivery, before confirm resumes.
        self.worker.duplicate_folder_found.connect(
            lambda *_args: (self.worker.request_cancel(), self.worker.resolve_duplicate_confirmation(True)),
            # A direct connection exercises the ordering without a GUI loop.
            Qt.DirectConnection,
        )
        self.thread.start()
        self.assert_finished_with(False)


if __name__ == "__main__":
    unittest.main()
