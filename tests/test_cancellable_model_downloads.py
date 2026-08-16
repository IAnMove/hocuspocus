"""Model-free regressions for generation cancellation during downloads."""
from __future__ import annotations

import os
import sys
import threading
import unittest
from io import StringIO


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP = os.path.join(ROOT, "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

from services import safe_download  # noqa: E402


class TestCancellableDownloads(unittest.TestCase):
    def test_scope_raises_only_for_its_owner_thread(self):
        cancelled = False
        with safe_download.cancellable_downloads(lambda: cancelled):
            cancelled = True
            with self.assertRaisesRegex(
                safe_download.DownloadCancelled,
                "Model download cancelled",
            ):
                safe_download.raise_if_download_cancelled()
            cancelled = False

        # The predicate must not leak after the context exits.
        safe_download.raise_if_download_cancelled()

        worker_errors: list[BaseException] = []
        cancelled = False
        with safe_download.cancellable_downloads(lambda: cancelled):
            cancelled = True
            worker = threading.Thread(
                target=lambda: self._capture_cancel_check(worker_errors),
            )
            worker.start()
            worker.join(timeout=2)
            cancelled = False
        self.assertFalse(worker.is_alive())
        self.assertEqual(worker_errors, [])

    @staticmethod
    def _capture_cancel_check(errors: list[BaseException]) -> None:
        try:
            safe_download.raise_if_download_cancelled()
        except BaseException as error:  # pragma: no cover - assertion reports it
            errors.append(error)

    def test_huggingface_style_byte_bar_observes_cancel(self):
        from tqdm import tqdm

        bar = tqdm(
            total=32 * 1024,
            unit="B",
            unit_scale=True,
            desc="cancel-test.safetensors",
            disable=False,
            file=StringIO(),
        )
        try:
            cancelled = False
            with safe_download.cancellable_downloads(lambda: cancelled):
                cancelled = True
                with self.assertRaises(safe_download.DownloadCancelled):
                    bar.update(1024)
                cancelled = False
        finally:
            bar.close()

    def test_generation_worker_and_ui_are_wired_to_cooperative_cancel(self):
        with open(os.path.join(APP, "_launch_runtime.py"), "r", encoding="utf-8") as handle:
            launch = handle.read()
        with open(
            os.path.join(ROOT, "ui", "src", "stores", "useStore.ts"),
            "r",
            encoding="utf-8",
        ) as handle:
            store = handle.read()

        self.assertIn("with safe_download.cancellable_downloads(", launch)
        self.assertIn("lambda: is_cancel_requested(job)", launch)
        legacy_call = launch[launch.index("generated = minimax_h3_service.generate(") - 300:]
        legacy_call = legacy_call[:legacy_call.index("if is_cancel_requested(job):")]
        self.assertIn("with safe_download.cancellable_downloads(", legacy_call)
        stop = store[store.index("stopGeneration: (jobId) => {"):]
        stop = stop[:stop.index("\n  },")]
        self.assertIn("message: 'Cancelling…'", stop)
        self.assertIn("void api.cancelJob(id)", stop)
        self.assertNotIn("filter(j => j.id !== jobId)", stop)


if __name__ == "__main__":
    unittest.main()
