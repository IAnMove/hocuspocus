"""Regression coverage for Maestro Next's shared stable LoRA library."""

from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.shared.utils import files_locator


class TestReadOnlyLoraRoots(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.local = root / "next" / "loras"
        self.shared = root / "stable" / "loras"
        self.local.mkdir(parents=True)
        self.shared.mkdir(parents=True)
        self.environment = mock.patch.dict(
            os.environ,
            {files_locator.READ_ONLY_LORAS_ENV: str(self.shared)},
            clear=False,
        )
        self.environment.start()
        files_locator.set_loras_paths([str(self.local)])

    def tearDown(self):
        self.environment.stop()
        importlib.reload(files_locator)
        self.temp_dir.cleanup()

    def test_lookup_is_local_first_then_shared(self):
        shared = self.shared / "ltx2" / "refiner.safetensors"
        shared.parent.mkdir()
        shared.write_bytes(b"shared")
        self.assertEqual(
            files_locator.locate_lora_file("refiner.safetensors", "ltx2"),
            str(shared),
        )
        self.assertTrue(files_locator.is_read_only_lora_path(shared))

        local = self.local / "ltx2" / shared.name
        local.parent.mkdir()
        local.write_bytes(b"local")
        self.assertEqual(
            files_locator.locate_lora_file(shared.name, "ltx2"),
            str(local),
        )

    def test_download_is_always_local(self):
        (self.shared / "ltx2").mkdir()
        destination = files_locator.get_lora_download_location(
            "new.safetensors", "ltx2"
        )
        self.assertEqual(destination, str(self.local / "ltx2" / "new.safetensors"))
        self.assertFalse(files_locator.is_read_only_lora_path(destination))

    def test_shared_root_cannot_be_reclassified_as_writable(self):
        files_locator.set_loras_paths([str(self.shared)])

        destination = files_locator.get_lora_download_location(
            "new.safetensors", "ltx2"
        )

        self.assertTrue(files_locator.is_read_only_lora_path(self.shared))
        self.assertFalse(
            Path(destination).is_relative_to(self.shared)
        )

    def test_mutation_of_shared_lora_is_rejected(self):
        shared = self.shared / "ltx2" / "refiner.safetensors"
        shared.parent.mkdir()
        shared.write_bytes(b"shared")
        with self.assertRaisesRegex(PermissionError, "read-only LoRA"):
            files_locator.assert_writable_lora_path(shared, "rename")
        self.assertEqual(shared.read_bytes(), b"shared")

    def test_reset_script_never_targets_lora_roots(self):
        reset_script = (
            Path(__file__).resolve().parents[1] / "reset.js"
        ).read_text(encoding="utf-8")
        self.assertNotIn('path: "app/loras"', reset_script)
        self.assertNotIn("MAESTRO_READ_ONLY_LORAS", reset_script)

    def test_no_symlink_is_created(self):
        shared = self.shared / "ltx2" / "refiner.safetensors"
        shared.parent.mkdir()
        shared.write_bytes(b"shared")
        resolved = Path(
            files_locator.locate_lora_file(shared.name, relative_dir="ltx2")
        )
        self.assertEqual(resolved, shared)
        self.assertFalse(resolved.is_symlink())


if __name__ == "__main__":
    unittest.main()
