"""Regression coverage for Maestro Next's shared stable model library."""

from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.services import llm_service
from app.shared.utils import files_locator


class TestReadOnlyCheckpointRoots(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.local = root / "next" / "ckpts"
        self.shared = root / "stable" / "ckpts"
        self.local.mkdir(parents=True)
        self.shared.mkdir(parents=True)
        self.environment = mock.patch.dict(
            os.environ,
            {files_locator.READ_ONLY_CHECKPOINTS_ENV: str(self.shared)},
            clear=False,
        )
        self.environment.start()
        files_locator.set_checkpoints_paths([str(self.local)])

    def tearDown(self):
        self.environment.stop()
        importlib.reload(files_locator)
        self.temp_dir.cleanup()

    def test_lookup_finds_existing_shared_weight(self):
        weight = self.shared / "ltx" / "model.safetensors"
        weight.parent.mkdir()
        weight.write_bytes(b"shared")

        self.assertEqual(files_locator.locate_file("ltx/model.safetensors"), str(weight))
        self.assertTrue(files_locator.is_read_only_path(weight))

    def test_downloads_never_select_shared_family_directory(self):
        (self.shared / "ltx").mkdir()

        self.assertEqual(
            files_locator.get_smart_download_root("ltx"),
            str(self.local),
        )
        self.assertEqual(
            files_locator.get_smart_download_location("new.safetensors", "ltx"),
            str(self.local / "ltx" / "new.safetensors"),
        )

    def test_missing_shared_root_is_not_added(self):
        missing = Path(self.temp_dir.name) / "missing"
        with mock.patch.dict(
            os.environ,
            {files_locator.READ_ONLY_CHECKPOINTS_ENV: str(missing)},
            clear=False,
        ):
            files_locator.set_checkpoints_paths([str(self.local)])

        self.assertEqual(files_locator.get_read_only_checkpoints_paths(), [])

    def test_local_llm_reuses_shared_gguf_without_downloading(self):
        shared_file = self.shared / "llm" / "writer" / "writer.gguf"
        shared_file.parent.mkdir(parents=True)
        shared_file.write_bytes(b"shared-llm")
        local_cache = self.local / "llm" / "writer"

        with mock.patch.object(
            llm_service,
            "_BASE_DIR",
            str(self.local.parent / "services"),
        ):
            resolved = llm_service._download_gguf(
                "example/writer",
                "writer.gguf",
                str(local_cache),
            )

        self.assertEqual(resolved, str(shared_file))
        self.assertFalse((local_cache / "writer.gguf").exists())


if __name__ == "__main__":
    unittest.main()
