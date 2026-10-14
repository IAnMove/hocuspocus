"""Model-free regressions for CivitAI/HuggingFace download state wiring."""
from __future__ import annotations

import ast
import json
import os
from pathlib import PureWindowsPath
import struct
import tempfile
import threading
import time
import unittest
import uuid
import zipfile

from services.kernel.paths import PathPolicy


_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_HF_IMPORT_PATH = os.path.join(_ROOT, "app", "services", "hf_import.py")
_DOWNLOADS_PATH = os.path.join(_ROOT, "app", "services", "civitai_downloads.py")
_GUIDES_PATH = os.path.join(_ROOT, "app", "services", "lora_guides.py")
_UI_STORE_PATH = os.path.join(_ROOT, "ui", "src", "stores", "civitaiSlice.ts")
_MODEL_DETAIL_PATH = os.path.join(
    _ROOT, "ui", "src", "components", "LoraBrowser", "ModelDetail.tsx",
)


def _parse_source(path: str, filename: str) -> tuple[ast.Module, str]:
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    return ast.parse(source, filename=filename), source


def _parse_hf() -> tuple[ast.Module, str]:
    return _parse_source(_HF_IMPORT_PATH, "app/services/hf_import.py")


def _parse_downloads() -> tuple[ast.Module, str]:
    return _parse_source(_DOWNLOADS_PATH, "app/services/civitai_downloads.py")


def _parse_guides() -> tuple[ast.Module, str]:
    with open(_GUIDES_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    return ast.parse(source, filename="app/services/lora_guides.py"), source


def _function(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found")


def _source_segment(tree: ast.AST, source: str, name: str) -> str:
    segment = ast.get_source_segment(source, _function(tree, name))
    if segment is None:
        raise AssertionError(f"Could not read source for {name!r}")
    return segment


def _load_helpers(tree: ast.Module, names: tuple[str, ...]) -> dict:
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "os": os,
        "PureWindowsPath": PureWindowsPath,
        "time": time,
        "threading": threading,
        "uuid": uuid,
        "_civitai_downloads": {},
        "_civitai_download_lock": threading.Lock(),
        "_download_target_reservations": {},
        "_lora_guide_scans": {},
        "_lora_guide_scan_lock": threading.Lock(),
        "_safe_join": PathPolicy().safe_join,
    }
    exec(compile(module, "app/services/civitai_downloads.py", "exec"), namespace)
    return namespace


class TestDownloadState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree, cls.source = _parse_hf()
        cls.downloads_tree, cls.downloads_source = _parse_downloads()
        cls.guides_tree, cls.guides_source = _parse_guides()

    def test_common_record_and_serialization_contract(self):
        helpers = _load_helpers(
            self.downloads_tree,
            (
                "_new_download_record",
                "_safe_download_number",
                "_serialize_download_record",
            ),
        )
        record = helpers["_new_download_record"](
            "hf_example",
            "example.safetensors",
            _internal=object(),
        )
        required = {
            "id", "filename", "status", "progress", "bytes_downloaded",
            "bytes_total", "error", "started_at", "completed_at",
        }
        self.assertTrue(required <= record.keys())
        self.assertEqual(record["progress"], 0)
        self.assertIsNotNone(record["started_at"])
        self.assertIsNone(record["completed_at"])

        public = helpers["_serialize_download_record"](
            {
                "progress": 999,
                "bytes_downloaded": "12",
                "bytes_total": object(),
                "error": RuntimeError("network failed"),
                "model_type": "civitai_example_checkpoint",
                "warnings": "not-a-list",
                "_internal": object(),
            },
            fallback_id="legacy-entry",
        )
        self.assertTrue(required <= public.keys())
        self.assertEqual(public["id"], "legacy-entry")
        self.assertEqual(public["progress"], 100)
        self.assertEqual(public["bytes_downloaded"], 12)
        self.assertEqual(public["bytes_total"], 0)
        self.assertEqual(public["error"], "network failed")
        self.assertEqual(public["model_type"], "civitai_example_checkpoint")
        self.assertNotIn("_internal", public)
        json.dumps(public)

    def test_checkpoint_completion_refresh_is_global_and_filename_independent(self):
        with open(_UI_STORE_PATH, "r", encoding="utf-8") as handle:
            store_source = handle.read()
        with open(_MODEL_DETAIL_PATH, "r", encoding="utf-8") as handle:
            detail_source = handle.read()

        self.assertIn("download.status === 'completed'", store_source)
        self.assertIn("!!download.model_type", store_source)
        self.assertIn("await api.reloadModels()", store_source)
        self.assertIn("await get().loadModels()", store_source)
        self.assertNotIn("reloadModels", detail_source)

    def test_terminal_helpers_set_completed_at_under_registry_lock(self):
        helpers = _load_helpers(
            self.downloads_tree,
            (
                "_new_download_record",
                "_update_download_record",
                "_complete_download_record",
                "_fail_download_record",
            ),
        )
        registry = helpers["_civitai_downloads"]
        registry["done"] = helpers["_new_download_record"]("done", "done.bin")
        helpers["_complete_download_record"]("done")
        self.assertEqual(registry["done"]["status"], "completed")
        self.assertEqual(registry["done"]["progress"], 100)
        self.assertIsNotNone(registry["done"]["completed_at"])

        registry["failed"] = helpers["_new_download_record"]("failed", "failed.bin")
        helpers["_fail_download_record"]("failed", ValueError("bad payload"))
        self.assertEqual(registry["failed"]["status"], "failed")
        self.assertEqual(registry["failed"]["error"], "bad payload")
        self.assertIsNotNone(registry["failed"]["completed_at"])

    def test_hf_progress_uses_zero_to_one_hundred_scale(self):
        helpers = _load_helpers(
            self.downloads_tree,
            (
                "_response_content_length",
                "_download_progress_percent",
                "_require_complete_download",
            ),
        )
        response_total = helpers["_response_content_length"]
        self.assertEqual(response_total({"content-length": "200"}), 200)
        self.assertEqual(
            response_total({
                "content-length": "200", "content-encoding": "identity",
            }),
            200,
        )
        self.assertEqual(
            response_total({
                "content-length": "80", "content-encoding": "gzip",
            }),
            0,
        )
        self.assertEqual(
            response_total({
                "content-length": "80", "content-encoding": "br",
            }),
            0,
        )
        self.assertEqual(
            response_total({
                "Content-Length": "80", "Content-Encoding": "gzip",
            }),
            0,
        )
        progress = helpers["_download_progress_percent"]
        self.assertEqual(progress(0, 200), 0)
        self.assertEqual(progress(50, 200), 25)
        self.assertEqual(progress(200, 200), 100)
        self.assertEqual(progress(300, 200), 100)
        self.assertEqual(progress(50, 0), 0)
        require_complete = helpers["_require_complete_download"]
        require_complete(200, 200)
        require_complete(50, 0)
        with self.assertRaisesRegex(IOError, "received 199 of 200 bytes"):
            require_complete(199, 200)

        hf_import = _function(self.tree, "hf_import_lora")
        hf_worker = _function(hf_import, "_do_download")
        calls = {
            node.func.id
            for node in ast.walk(hf_worker)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("_download_progress_percent", calls)
        self.assertIn("_response_content_length", calls)

    def test_path_components_reject_traversal_and_endpoint_wiring(self):
        helpers = _load_helpers(self.downloads_tree, ("_is_safe_path_component",))
        is_safe = helpers["_is_safe_path_component"]
        for value in ("model.safetensors", "flux2_klein_9b", "name-with dots"):
            with self.subTest(value=value):
                self.assertTrue(is_safe(value))
        for value in (
            "", ".", "..", "../escape", "folder/file", "folder\\file",
            "bad\x00name", "trailing.", "trailing ", "C:\\escape",
            "file:stream", "bad?.safetensors", "CON.safetensors", "LPT9.txt",
            "CON .safetensors", "CONIN$", "CONOUT$",
            "COM¹.txt", "COM².txt", "COM³.txt",
            "LPT¹.txt", "LPT².txt", "LPT³.txt",
        ):
            with self.subTest(value=value):
                self.assertFalse(is_safe(value))

        civitai_endpoint = _source_segment(
            self.downloads_tree, self.downloads_source, "civitai_download",
        )
        self.assertIn("_is_safe_path_component(filename)", civitai_endpoint)
        self.assertIn("_is_safe_path_component(target_arch)", civitai_endpoint)
        self.assertIn("_safe_join(lora_root, target_arch)", civitai_endpoint)
        hf_endpoint = _source_segment(
            self.tree, self.source, "hf_import_lora",
        )
        self.assertIn(
            "_is_safe_path_component(target_dir_override)", hf_endpoint,
        )
        self.assertIn("_is_safe_path_component(disk_filename)", hf_endpoint)

        civitai_worker = _source_segment(
            self.downloads_tree, self.downloads_source, "_run_civitai_download",
        )
        self.assertIn("os.path.basename", civitai_worker)
        self.assertIn("_is_safe_path_component(remote_filename)", civitai_worker)

    def test_target_reservation_is_normalized_and_single_flight(self):
        helpers = _load_helpers(
            self.downloads_tree,
            (
                "_normalize_download_target",
                "_reserve_download_target",
                "_release_download_target",
            ),
        )
        reserve = helpers["_reserve_download_target"]
        release = helpers["_release_download_target"]
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, "models", "model.safetensors")
            equivalent = os.path.join(
                directory, "models", "..", "models", "model.safetensors",
            )
            reserved = reserve("first", target)
            self.assertIsNotNone(reserved)
            self.assertIsNone(reserve("second", equivalent))
            release("not-the-owner", target)
            self.assertIsNone(reserve("second", target))
            release("first", equivalent)
            self.assertIsNotNone(reserve("second", target))
            release("second", target)

    def test_guide_scans_use_a_separate_registry(self):
        status_source = _source_segment(
            self.guides_tree, self.guides_source, "scan_status",
        )
        start_source = _source_segment(
            self.guides_tree, self.guides_source, "scan_and_generate_guides",
        )
        self.assertIn("_lora_guide_scans", status_source)
        for helper_name in (
            "_register_lora_guide_scan",
            "_update_lora_guide_scan",
            "_append_lora_guide_scan_result",
        ):
            self.assertIn(helper_name, start_source)
        self.assertNotIn("_civitai_downloads", status_source)
        self.assertNotIn("_civitai_downloads", start_source)

    def test_guide_scan_helpers_lock_updates_and_appends(self):
        helpers = _load_helpers(
            self.guides_tree,
            (
                "_register_lora_guide_scan",
                "_update_lora_guide_scan",
                "_append_lora_guide_scan_result",
            ),
        )
        register = helpers["_register_lora_guide_scan"]
        update = helpers["_update_lora_guide_scan"]
        append = helpers["_append_lora_guide_scan_result"]
        registry = helpers["_lora_guide_scans"]
        register("scan", {"status": "running", "results": []})

        threads = [
            threading.Thread(
                target=append,
                args=("scan", {"result": index}),
            )
            for index in range(40)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        update("scan", status="complete", current=40)

        self.assertEqual(registry["scan"]["status"], "complete")
        self.assertEqual(registry["scan"]["current"], 40)
        self.assertEqual(len(registry["scan"]["results"]), 40)
        for helper_name in (
            "_register_lora_guide_scan",
            "_update_lora_guide_scan",
            "_append_lora_guide_scan_result",
        ):
            helper_source = _source_segment(
                self.guides_tree, self.guides_source, helper_name,
            )
            self.assertIn("with _lora_guide_scan_lock", helper_source)

    def test_status_feed_serializes_instead_of_indexing_internal_records(self):
        status_source = _source_segment(
            self.downloads_tree, self.downloads_source, "civitai_downloads_status",
        )
        self.assertIn("_serialize_download_record", status_source)
        for required_key in (
            'dl["id"]', 'dl["filename"]', 'dl["bytes_downloaded"]',
        ):
            self.assertNotIn(required_key, status_source)

    def test_completion_follows_provider_postprocessing(self):
        civitai = _source_segment(
            self.downloads_tree, self.downloads_source, "_run_civitai_download",
        )
        civitai_complete = civitai.rindex("_complete_download_record")
        self.assertGreater(
            civitai_complete, civitai.index("_register_checkpoint_finetune"),
        )
        self.assertGreater(
            civitai_complete, civitai.index("_generate_and_save_checkpoint_guide"),
        )
        self.assertGreater(
            civitai_complete, civitai.index("_generate_and_save_lora_guide"),
        )

        hf_import = _function(self.tree, "hf_import_lora")
        hf_worker = _function(hf_import, "_do_download")
        hf_source = ast.get_source_segment(self.source, hf_worker)
        self.assertIsNotNone(hf_source)
        hf_complete = hf_source.rindex("_complete_download_record")
        self.assertGreater(hf_complete, hf_source.index("for i, media_url"))
        self.assertGreater(
            hf_complete, hf_source.index("_generate_and_save_lora_guide"),
        )

    def test_civitai_archive_members_are_validated_and_published_atomically(self):
        helpers = _load_helpers(
            self.downloads_tree,
            (
                "_is_safe_path_component",
                "_normalize_download_target",
                "_reserve_download_target",
                "_release_download_target",
                "_validate_safetensors_payload",
                "_zip_member_target",
                "_copy_zip_member_to_partial",
                "_extract_civitai_archive",
            ),
        )
        reserve = helpers["_reserve_download_target"]
        release = helpers["_release_download_target"]
        extract = helpers["_extract_civitai_archive"]
        member_target = helpers["_zip_member_target"]
        valid_payload = (
            struct.pack("<Q", 2)
            + b"{}"
            + b"\0" * (100 * 1024)
        )

        with tempfile.TemporaryDirectory() as directory:
            target_dir = os.path.join(directory, "loras")
            os.makedirs(target_dir)
            archive = os.path.join(target_dir, "bundle.zip")
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("nested/model.safetensors", valid_payload)

            reserved_targets = {reserve("download", archive)}
            partial_paths = set()
            try:
                extracted = extract(
                    archive,
                    target_dir,
                    "download",
                    reserved_targets,
                    partial_paths,
                )
                self.assertEqual(
                    [os.path.realpath(path) for path in extracted],
                    [os.path.realpath(os.path.join(target_dir, "model.safetensors"))],
                )
                self.assertTrue(os.path.isfile(extracted[0]))
                self.assertEqual(os.path.getsize(extracted[0]), len(valid_payload))
                self.assertFalse(partial_paths)
                self.assertTrue(os.path.isfile(archive))
            finally:
                for partial_path in tuple(partial_paths):
                    if os.path.isfile(partial_path):
                        os.remove(partial_path)
                for target in tuple(reserved_targets):
                    release("download", target)

            self.assertTrue(
                member_target(target_dir, "nested/good.txt", flatten=False).endswith(
                    os.path.join("nested", "good.txt")
                )
            )
            for unsafe_member in (
                "../escape.txt", "nested/../escape.txt", "nested/CONIN$",
            ):
                with self.subTest(member=unsafe_member):
                    with self.assertRaisesRegex(ValueError, "unsafe archive member"):
                        member_target(target_dir, unsafe_member, flatten=False)

    def test_civitai_archive_failure_keeps_archive_and_rejects_duplicates(self):
        helpers = _load_helpers(
            self.downloads_tree,
            (
                "_is_safe_path_component",
                "_normalize_download_target",
                "_reserve_download_target",
                "_release_download_target",
                "_validate_safetensors_payload",
                "_zip_member_target",
                "_copy_zip_member_to_partial",
                "_extract_civitai_archive",
            ),
        )
        reserve = helpers["_reserve_download_target"]
        release = helpers["_release_download_target"]
        extract = helpers["_extract_civitai_archive"]
        valid_payload = (
            struct.pack("<Q", 2)
            + b"{}"
            + b"\0" * (100 * 1024)
        )

        with tempfile.TemporaryDirectory() as directory:
            target_dir = os.path.join(directory, "loras")
            os.makedirs(target_dir)
            archive = os.path.join(target_dir, "duplicate.zip")
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("one/model.safetensors", valid_payload)
                handle.writestr("two/model.safetensors", valid_payload)

            reserved_targets = {reserve("download", archive)}
            partial_paths = set()
            try:
                with self.assertRaisesRegex(ValueError, "duplicate target"):
                    extract(
                        archive,
                        target_dir,
                        "download",
                        reserved_targets,
                        partial_paths,
                    )
                self.assertTrue(os.path.isfile(archive))
                self.assertFalse(
                    os.path.exists(os.path.join(target_dir, "model.safetensors"))
                )
            finally:
                for partial_path in tuple(partial_paths):
                    if os.path.isfile(partial_path):
                        os.remove(partial_path)
                for target in tuple(reserved_targets):
                    release("download", target)

            invalid_archive = os.path.join(target_dir, "invalid.zip")
            with zipfile.ZipFile(invalid_archive, "w") as handle:
                handle.writestr("bad.safetensors", b"not safetensors")
            reserved_targets = {reserve("invalid", invalid_archive)}
            partial_paths = set()
            try:
                with self.assertRaisesRegex(
                    RuntimeError, "Invalid safetensors archive member",
                ):
                    extract(
                        invalid_archive,
                        target_dir,
                        "invalid",
                        reserved_targets,
                        partial_paths,
                    )
                self.assertTrue(os.path.isfile(invalid_archive))
            finally:
                for partial_path in tuple(partial_paths):
                    if os.path.isfile(partial_path):
                        os.remove(partial_path)
                for target in tuple(reserved_targets):
                    release("invalid", target)

            short_archive = os.path.join(target_dir, "short.zip")
            with zipfile.ZipFile(short_archive, "w") as handle:
                handle.writestr("payload.bin", b"expected payload")

            def short_copy(_zip_file, _member, partial_path):
                with open(partial_path, "wb") as handle:
                    handle.write(b"x")
                return 1

            helpers["_copy_zip_member_to_partial"] = short_copy
            reserved_targets = {reserve("short", short_archive)}
            partial_paths = set()
            try:
                with self.assertRaisesRegex(IOError, "Incomplete archive member"):
                    extract(
                        short_archive,
                        target_dir,
                        "short",
                        reserved_targets,
                        partial_paths,
                    )
                self.assertTrue(os.path.isfile(short_archive))
            finally:
                for partial_path in tuple(partial_paths):
                    if os.path.isfile(partial_path):
                        os.remove(partial_path)
                for target in tuple(reserved_targets):
                    release("short", target)

    def test_provider_streams_publish_atomically_and_clean_partials(self):
        civitai = _source_segment(
            self.downloads_tree, self.downloads_source, "_run_civitai_download",
        )
        hf_import = _function(self.tree, "hf_import_lora")
        hf_worker = _function(hf_import, "_do_download")
        hf_source = ast.get_source_segment(self.source, hf_worker)
        self.assertIsNotNone(hf_source)

        for provider_source in (civitai, hf_source):
            self.assertIn("uuid.uuid4().hex", provider_source)
            self.assertIn(".part", provider_source)
            self.assertIn("_response_content_length", provider_source)
            self.assertIn("os.replace(partial_path, save_path)", provider_source)
            reserve_at = provider_source.index("_reserve_download_target")
            open_at = provider_source.index('open(partial_path, "wb")')
            size_check_at = provider_source.index("_require_complete_download")
            replace_at = provider_source.index(
                "os.replace(partial_path, save_path)",
            )
            release_at = provider_source.index("_release_download_target")
            self.assertLess(reserve_at, open_at)
            self.assertLess(size_check_at, replace_at)
            self.assertGreater(release_at, replace_at)

        self.assertIn("os.remove(cleanup_path)", civitai)
        self.assertNotIn("ZIP extraction failed", civitai)
        self.assertIn("_extract_civitai_archive", civitai)
        self.assertIn("_validate_safetensors_payload(partial_path)", civitai)
        self.assertGreater(
            hf_source.index("os.remove(partial_path)"),
            hf_source.index("os.replace(partial_path, save_path)"),
        )

        archive_source = _source_segment(
            self.downloads_tree, self.downloads_source, "_extract_civitai_archive",
        )
        for wiring in (
            "_zip_member_target",
            "_reserve_download_target",
            "duplicate target",
            "uuid.uuid4().hex",
            "copied != member.file_size",
            "_validate_safetensors_payload(partial_path)",
            "os.replace(partial_path, final_path)",
        ):
            self.assertIn(wiring, archive_source)

        hf_import_source = _source_segment(
            self.tree, self.source, "hf_import_lora",
        )
        self.assertIn('dl_id = f"hf_{uuid.uuid4().hex}"', hf_import_source)

    def test_safetensors_gate_rejects_small_files_and_impossible_headers(self):
        helpers = _load_helpers(self.downloads_tree, ("_validate_safetensors_payload",))
        validate = helpers["_validate_safetensors_payload"]

        def write(directory, name, raw_header_length, size):
            path = os.path.join(directory, name)
            with open(path, "wb") as handle:
                handle.write(struct.pack("<Q", raw_header_length))
                handle.write(b"\0" * (size - 8))
            return path

        with tempfile.TemporaryDirectory() as directory:
            validate(write(directory, "ok.safetensors", 2, 150 * 1024))
            with self.assertRaisesRegex(ValueError, "too small to be a real LoRA"):
                validate(write(directory, "small.safetensors", 2, 50 * 1024))
            with self.assertRaisesRegex(ValueError, "out of range"):
                validate(write(directory, "zero.safetensors", 0, 150 * 1024))
            with self.assertRaisesRegex(ValueError, "out of range"):
                validate(write(directory, "huge.safetensors", 300 * 1024 * 1024, 150 * 1024))
            with self.assertRaisesRegex(ValueError, "claims .* bytes but file is only"):
                validate(write(directory, "overrun.safetensors", 150 * 1024, 150 * 1024))

    def test_archive_refuses_a_member_over_its_own_path_and_a_busy_target(self):
        helpers = _load_helpers(
            self.downloads_tree,
            (
                "_is_safe_path_component",
                "_normalize_download_target",
                "_reserve_download_target",
                "_release_download_target",
                "_validate_safetensors_payload",
                "_zip_member_target",
                "_copy_zip_member_to_partial",
                "_extract_civitai_archive",
            ),
        )
        reserve = helpers["_reserve_download_target"]
        release = helpers["_release_download_target"]
        extract = helpers["_extract_civitai_archive"]
        valid_payload = struct.pack("<Q", 2) + b"{}" + b"\0" * (100 * 1024)

        def run(directory, archive, download_id):
            reserved_targets = {reserve(download_id, archive)}
            partial_paths = set()
            try:
                return extract(archive, directory, download_id, reserved_targets, partial_paths)
            finally:
                for partial_path in tuple(partial_paths):
                    if os.path.isfile(partial_path):
                        os.remove(partial_path)
                for target in tuple(reserved_targets):
                    release(download_id, target)

        with tempfile.TemporaryDirectory() as directory:
            collide = os.path.join(directory, "collide.zip")
            with zipfile.ZipFile(collide, "w") as handle:
                handle.writestr("collide.zip", b"payload")
            with self.assertRaisesRegex(ValueError, "collides with its archive path"):
                run(directory, collide, "collide")
            self.assertEqual(open(collide, "rb").read()[:2], b"PK")

            busy = os.path.join(directory, "busy.zip")
            with zipfile.ZipFile(busy, "w") as handle:
                handle.writestr("deep/model.safetensors", valid_payload)
            target = os.path.join(directory, "model.safetensors")
            self.assertIsNotNone(reserve("other-download", target))
            try:
                with self.assertRaisesRegex(RuntimeError, "Another download is already writing model.safetensors"):
                    run(directory, busy, "busy")
            finally:
                release("other-download", target)
            self.assertFalse(os.path.exists(target))

            mixed = os.path.join(directory, "mixed.zip")
            with zipfile.ZipFile(mixed, "w") as handle:
                handle.writestr("README.txt", b"read me")
                handle.writestr("weights/lora.safetensors", valid_payload)
            extracted = run(directory, mixed, "mixed")
            self.assertEqual([os.path.basename(path) for path in extracted], ["lora.safetensors"])
            self.assertFalse(os.path.exists(os.path.join(directory, "README.txt")))

    def test_archive_weights_with_windows_separators_are_flattened(self):
        helpers = _load_helpers(
            self.downloads_tree,
            (
                "_is_safe_path_component",
                "_normalize_download_target",
                "_reserve_download_target",
                "_release_download_target",
                "_validate_safetensors_payload",
                "_zip_member_target",
                "_copy_zip_member_to_partial",
                "_extract_civitai_archive",
            ),
        )
        valid_payload = struct.pack("<Q", 2) + b"{}" + b"\0" * (100 * 1024)
        with tempfile.TemporaryDirectory() as directory:
            archive = os.path.join(directory, "windows.zip")
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("weights\\sub\\lora.safetensors", valid_payload)
            reserved_targets = {helpers["_reserve_download_target"]("windows", archive)}
            partial_paths = set()
            try:
                extracted = helpers["_extract_civitai_archive"](
                    archive, directory, "windows", reserved_targets, partial_paths,
                )
            finally:
                for target in tuple(reserved_targets):
                    helpers["_release_download_target"]("windows", target)
            self.assertEqual([os.path.basename(path) for path in extracted], ["lora.safetensors"])
            self.assertEqual(os.path.realpath(os.path.dirname(extracted[0])), os.path.realpath(directory))

    def test_updating_a_record_that_is_gone_is_a_no_op(self):
        helpers = _load_helpers(
            self.downloads_tree,
            ("_update_download_record", "_complete_download_record", "_fail_download_record"),
        )
        self.assertIsNone(helpers["_update_download_record"]("gone", status="x"))
        helpers["_complete_download_record"]("gone")
        helpers["_fail_download_record"]("gone", ValueError("late"))
        self.assertEqual(helpers["_civitai_downloads"], {})


class TestCivitaiUrlGuard(unittest.TestCase):
    def test_only_http_civitai_hosts_and_its_cdn_bucket_are_accepted(self):
        from services.civitai import _is_safe_civitai_url

        for url in (
            "https://civitai.com/api/download/models/1",
            "http://www.civitai.com/x",
            "https://image.civitai.com/x",
            "https://CIVITAI.COM/x",
            "https://civitai-delivery-worker-prod.5ac0637cfd0766c97916cefa3764fbdf"
            ".r2.cloudflarestorage.com/model",
        ):
            with self.subTest(url=url):
                self.assertTrue(_is_safe_civitai_url(url))
        for url in (
            "https://evilcivitai.com/x",
            "https://civitai.com.evil.example/x",
            "https://civitai.com@evil.example/x",
            "https://evil.example/?next=civitai.com",
            "https://other-bucket.r2.cloudflarestorage.com/model",
            "ftp://civitai.com/x",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "//civitai.com/x",
            "civitai.com/x",
            "http://127.0.0.1/x",
            "",
            None,
            12,
        ):
            with self.subTest(url=url):
                self.assertFalse(_is_safe_civitai_url(url))


class _FakeStream:
    """What ``requests.get(..., stream=True)`` returns for a download."""

    def __init__(self, payload, headers=None, status=200):
        self.status_code = status
        self.headers = {"content-length": str(len(payload))} if headers is None else headers
        self.text = ""
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise IOError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self._payload), 40_000):
            yield self._payload[start:start + 40_000]


class TestCivitaiWorker(unittest.TestCase):
    """The background download worker, end to end, with the network faked."""

    def _download(self, directory, filename, payload, **stream):
        from types import SimpleNamespace
        from unittest import mock

        from services import civitai_downloads as worker

        download_id = "w" + uuid.uuid4().hex[:7]
        record = worker._new_download_record(download_id, filename)
        record.update({
            "target_dir": directory,
            "_url": "https://civitai.com/api/download/models/1",
            "_model_id": 1, "_version_id": 2, "_model_name": "Model",
            "_trained_words": [], "_images": [], "_kind": "lora",
        })
        with worker._civitai_download_lock:
            worker._civitai_downloads[download_id] = record
        try:
            with mock.patch.object(worker, "wgp", SimpleNamespace(server_config={"services": {}})), \
                    mock.patch.object(worker, "_safe_join", PathPolicy().safe_join), \
                    mock.patch.object(worker, "_ensure_llm_loaded", lambda: None), \
                    mock.patch.object(worker, "_generate_and_save_lora_guide", lambda *args, **kwargs: None), \
                    mock.patch.object(worker.requests, "get", lambda url, **kwargs: _FakeStream(payload, **stream)):
                worker._run_civitai_download(download_id)
            result = dict(worker._civitai_downloads[download_id])
            reservations = dict(worker._download_target_reservations)
        finally:
            with worker._civitai_download_lock:
                worker._civitai_downloads.pop(download_id, None)
        self.assertEqual(
            [name for name in os.listdir(directory) if name.endswith(".part")], [],
        )
        return result, reservations

    def test_a_valid_file_is_published_and_the_target_released(self):
        valid = struct.pack("<Q", 2) + b"{}" + b"\0" * (150 * 1024)
        with tempfile.TemporaryDirectory() as directory:
            record, reservations = self._download(directory, "ok.safetensors", valid)
            self.assertEqual(
                (record["status"], record["progress"], record["error"]),
                ("completed", 100, None),
            )
            self.assertEqual(os.path.getsize(os.path.join(directory, "ok.safetensors")), len(valid))
            self.assertTrue(os.path.isfile(os.path.join(directory, "ok.civitai.json")))
            self.assertEqual(reservations, {})

    def test_an_error_page_saved_as_a_model_is_refused_and_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            record, reservations = self._download(
                directory, "bogus.safetensors", b"<html>denied</html>" * 200,
            )
            self.assertEqual(record["status"], "failed")
            self.assertIn("invalid LoRA payload", record["error"])
            self.assertEqual(os.listdir(directory), [])
            self.assertEqual(reservations, {})

    def test_a_short_stream_fails_and_leaves_nothing_behind(self):
        valid = struct.pack("<Q", 2) + b"{}" + b"\0" * (150 * 1024)
        with tempfile.TemporaryDirectory() as directory:
            record, _ = self._download(
                directory, "short.safetensors", valid[:100_000],
                headers={"content-length": str(len(valid))},
            )
            self.assertEqual(record["status"], "failed")
            self.assertIn("Incomplete download", record["error"])
            self.assertEqual(os.listdir(directory), [])

    def test_the_server_file_name_is_used_only_when_it_is_one_safe_component(self):
        valid = struct.pack("<Q", 2) + b"{}" + b"\0" * (150 * 1024)
        for disposition, expected in (
            ('attachment; filename="renamed.safetensors"', "renamed.safetensors"),
            ('attachment; filename="../../up.safetensors"', "up.safetensors"),
            ('attachment; filename="..\\..\\win.safetensors"', "win.safetensors"),
            ('attachment; filename="CON.safetensors"', "asked.safetensors"),
            ("inline", "asked.safetensors"),
        ):
            with self.subTest(disposition=disposition), tempfile.TemporaryDirectory() as parent:
                directory = os.path.join(parent, "loras")
                os.makedirs(directory)
                record, _ = self._download(
                    directory, "asked.safetensors", valid,
                    headers={
                        "content-length": str(len(valid)),
                        "content-disposition": disposition,
                    },
                )
                self.assertEqual((record["status"], record["filename"]), ("completed", expected))
                self.assertEqual(
                    sorted(os.listdir(directory)),
                    [os.path.splitext(expected)[0] + ".civitai.json", expected],
                )
                self.assertEqual(os.listdir(parent), ["loras"])

    def test_a_zip_is_unpacked_to_its_weights_and_the_archive_removed(self):
        valid = struct.pack("<Q", 2) + b"{}" + b"\0" * (150 * 1024)
        buffer = tempfile.SpooledTemporaryFile()
        with zipfile.ZipFile(buffer, "w") as handle:
            handle.writestr("notes.txt", b"hello")
            handle.writestr("inner/one.safetensors", valid)
        buffer.seek(0)
        archive = buffer.read()
        with tempfile.TemporaryDirectory() as directory:
            record, reservations = self._download(directory, "pack.zip", archive)
            self.assertEqual((record["status"], record["filename"]), ("completed", "one.safetensors"))
            self.assertEqual(
                sorted(os.listdir(directory)), ["one.civitai.json", "one.safetensors"],
            )
            self.assertEqual(reservations, {})


_APP_DIR = os.path.join(_ROOT, "app")
_LORA_PAYLOAD = b"lora-bytes" * 30_000  # 300,000 bytes: the fake stream yields 40,000-byte chunks
_LORA_SHA256 = __import__("hashlib").sha256(_LORA_PAYLOAD).hexdigest()


class TestManagedLoraDownload(unittest.TestCase):
    """``_ensure_managed_loras_present``: the one-time download of a managed LoRA, with the network faked.

    The function runs from ``services.managed_loras`` with the engine, the download registry, the managed table,
    ``requests`` and ``time`` replaced. These cases passed on the full server before the C9c move too.
    """

    def setUp(self):
        from types import SimpleNamespace
        from unittest import mock

        from services import managed_loras as module

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = temp.name
        self.lora_dir = os.path.join(self.tmp, "engine", "loras_ltx2")
        self.base = "acme.safetensors"
        self.save_path = os.path.join(self.lora_dir, self.base)
        self.gets, self.progress, self.sleeps = [], [], []
        self.on_sleep = None
        self.response = _FakeStream(_LORA_PAYLOAD)
        self.registry = {}
        self.table = {}
        self.wgp = SimpleNamespace(
            get_lora_dir=lambda model_type: self.lora_dir,
            resolve_lora_path=lambda model_type, base: os.path.join(self.lora_dir, base),
            server_config={},
        )
        objects = {
            "wgp": self.wgp,
            "_civitai_download_lock": threading.Lock(),
            "_civitai_downloads": self.registry,
            "_MANAGED_LORAS": self.table,
            "requests": SimpleNamespace(get=self._get),
            "time": SimpleNamespace(sleep=self._sleep),
        }
        for name, value in objects.items():
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.ensure = module._ensure_managed_loras_present

    def _get(self, url, stream=False, timeout=None):
        self.gets.append((url, stream, timeout))
        return self.response

    def _sleep(self, seconds):
        self.sleeps.append(seconds)
        if self.on_sleep:
            self.on_sleep(len(self.sleeps))

    def _spec(self, **extra):
        spec = {"repo_id": "acme/loras", "label": "Acme", "support_url": "https://example.test/acme"}
        spec.update(extra)
        self.table[self.base] = spec
        return spec

    def _run(self, names=None):
        return self.ensure([self.base] if names is None else names, "ltx2_test", progress=self.progress.append)

    def _read(self, path):
        with open(path, "rb") as handle:
            return handle.read()

    def test_nothing_is_fetched_without_a_missing_managed_lora(self):
        self._spec()
        self.assertEqual(self.ensure([], "ltx2_test"), [])
        self.assertEqual(self.ensure(None, "ltx2_test"), [])
        self.assertEqual(self._run(["other.safetensors", "dir/other.safetensors"]), [])
        linked = os.path.join(self.tmp, "linked", self.base)
        os.makedirs(os.path.dirname(linked))
        with open(linked, "wb") as handle:
            handle.write(b"linked copy")
        self.wgp.resolve_lora_path = lambda model_type, base: linked
        self.assertEqual(self._run(["some/folder/" + self.base]), [])
        self.assertEqual((self.gets, self.progress, self.sleeps), ([], [], []))
        self.assertFalse(os.path.exists(self.lora_dir))

    def test_a_missing_lora_is_downloaded_checked_and_published_into_the_engine_folder(self):
        self._spec(revision="abc123", remote_path="sub/acme-src.safetensors",
                   size=len(_LORA_PAYLOAD), sha256=_LORA_SHA256.upper())
        self.assertEqual(self._run(), [self.base])
        self.assertEqual(self.gets, [
            ("https://huggingface.co/acme/loras/resolve/abc123/sub/acme-src.safetensors", True, 30),
        ])
        self.assertEqual(self._read(self.save_path), _LORA_PAYLOAD)
        self.assertEqual(os.listdir(self.lora_dir), [self.base])
        self.assertEqual(self.progress, ["Downloading Acme model (one-time setup)…"] + [
            f"Downloading Acme model (one-time setup)… {pct}%" for pct in (13, 26, 40, 53, 66, 80, 93, 100)
        ])

    def test_a_plain_entry_downloads_its_own_name_from_main(self):
        self.table[self.base] = {"repo_id": "acme/loras"}
        self.response = _FakeStream(_LORA_PAYLOAD, headers={})
        self.assertEqual(self._run(), [self.base])
        self.assertEqual(self.gets, [("https://huggingface.co/acme/loras/resolve/main/acme.safetensors", True, 30)])
        # Without a content length there is no percentage, only the start message, named after the file.
        self.assertEqual(self.progress, ["Downloading acme.safetensors model (one-time setup)…"])

    def test_a_size_mismatch_publishes_nothing_and_leaves_no_partial(self):
        self._spec(size=len(_LORA_PAYLOAD) + 1, sha256=_LORA_SHA256)
        with self.assertRaises(RuntimeError) as caught:
            self._run()
        self.assertEqual(str(caught.exception), (
            f"Could not download the Acme model automatically: download size mismatch (expected "
            f"{len(_LORA_PAYLOAD) + 1} bytes, got {len(_LORA_PAYLOAD)}). Check your internet connection. "
            "Try again, or import it manually from https://example.test/acme."
        ))
        self.assertEqual(os.listdir(self.lora_dir), [])

    def test_a_sha256_mismatch_publishes_nothing_and_leaves_no_partial(self):
        self._spec(size=len(_LORA_PAYLOAD), sha256="0" * 64)
        with self.assertRaises(RuntimeError) as caught:
            self._run()
        self.assertIn("download SHA-256 mismatch; the checkpoint was not published", str(caught.exception))
        self.assertEqual(os.listdir(self.lora_dir), [])

    def test_an_http_error_points_at_the_repository_page_when_there_is_no_support_link(self):
        self.table[self.base] = {"repo_id": "acme/loras", "label": "Acme"}
        self.response = _FakeStream(b"", status=503)
        with self.assertRaises(RuntimeError) as caught:
            self._run()
        self.assertEqual(str(caught.exception), (
            "Could not download the Acme model automatically: HTTP 503. Check your internet connection. "
            "Try again, or import it manually from https://huggingface.co/acme/loras."
        ))
        self.assertIsInstance(caught.exception.__cause__, IOError)
        self.assertEqual(os.listdir(self.lora_dir), [])

    def _fake_converter(self, outcome):
        import sys
        from types import ModuleType
        from unittest import mock

        calls = []

        def convert(source, target, expected_sha256=None):
            calls.append((source, target, expected_sha256, self._read(source)))
            if isinstance(outcome, Exception):
                raise outcome
            with open(target, "wb") as handle:
                handle.write(outcome)
            return 7

        fake = ModuleType("services.scail2_lora")
        fake.convert_scail2_sat_lora = convert
        patcher = mock.patch.dict(sys.modules, {"services.scail2_lora": fake})
        patcher.start()
        self.addCleanup(patcher.stop)
        return calls

    def test_a_converted_lora_is_converted_from_the_downloaded_source_then_published(self):
        self._spec(converter="scail2_sat_lora", size=len(_LORA_PAYLOAD), sha256=_LORA_SHA256)
        calls = self._fake_converter(b"converted tensors")
        self.assertEqual(self._run(), [self.base])
        self.assertEqual(self._read(self.save_path), b"converted tensors")
        self.assertEqual(os.listdir(self.lora_dir), [self.base])
        [(source, target, expected, downloaded)] = calls
        self.assertTrue(source.startswith(self.save_path + ".") and source.endswith(".source.part"))
        self.assertTrue(target.startswith(self.save_path + ".") and target.endswith(".part"))
        self.assertNotIn(".source.", target)
        self.assertEqual((expected, downloaded), (_LORA_SHA256, _LORA_PAYLOAD))
        self.assertEqual(self.progress[-1], "Converting Acme model (one-time setup)…")

    def test_a_failed_conversion_names_the_manual_conversion_and_leaves_no_partial(self):
        self._spec(converter="scail2_sat_lora", sha256=_LORA_SHA256)
        self._fake_converter(ValueError("bad tensors"))
        with self.assertRaises(RuntimeError) as caught:
            self._run()
        self.assertEqual(str(caught.exception), (
            "Could not download the Acme model automatically: bad tensors. Check your internet connection. "
            "Retry the automatic setup, or download the official source from https://example.test/acme and "
            "convert it with SCAIL-2's convert_lora.py."
        ))
        self.assertEqual(os.listdir(self.lora_dir), [])

    def test_it_waits_for_the_same_file_downloading_elsewhere_instead_of_racing_it(self):
        self._spec()
        # A finished record for the same name comes first; the in-flight one is the one waited on.
        self.registry["d0"] = {"filename": self.base, "status": "completed", "progress": 100}
        self.registry["d1"] = {"filename": os.path.join("x", self.base), "status": "downloading", "progress": 40}

        def finish_elsewhere(count):
            os.makedirs(self.lora_dir, exist_ok=True)
            with open(self.save_path, "wb") as handle:
                handle.write(b"from elsewhere")
            self.registry["d1"]["status"] = "completed"

        self.on_sleep = finish_elsewhere
        self.assertEqual(self._run(), [])
        self.assertEqual((self.gets, self.sleeps), ([], [2]))
        self.assertEqual(self.progress, ["Downloading Acme model (one-time setup)… 40%"])
        self.assertEqual(self._read(self.save_path), b"from elsewhere")

    def test_a_failed_download_elsewhere_drops_its_partial_and_downloads_again(self):
        self._spec()
        os.makedirs(self.lora_dir)
        with open(self.save_path, "wb") as handle:
            handle.write(b"partial")
        self.wgp.resolve_lora_path = lambda model_type, base: os.path.join(self.tmp, "elsewhere", base)
        self.registry["d1"] = {"filename": self.base, "status": "downloading", "progress": 10}
        self.on_sleep = lambda count: self.registry["d1"].update(status="failed")
        self.assertEqual(self._run(), [self.base])
        self.assertEqual(self.sleeps, [2])
        self.assertEqual(len(self.gets), 1)
        self.assertEqual(self._read(self.save_path), _LORA_PAYLOAD)

    def test_the_wait_for_another_download_gives_up_after_ten_minutes(self):
        self._spec()
        self.registry["d1"] = {"filename": self.base, "status": "downloading"}
        self.assertEqual(self._run(), [self.base])
        self.assertEqual(self.sleeps, [2] * 300)
        self.assertEqual(self.progress[:2], ["Downloading Acme model (one-time setup)… 0%"] * 2)
        self.assertEqual(len(self.gets), 1)

    def test_without_an_engine_folder_it_downloads_under_the_configured_root(self):
        self._spec()

        def no_folder(*_args):
            raise RuntimeError("no LoRA folder for this model")

        self.wgp.get_lora_dir = no_folder
        self.wgp.resolve_lora_path = no_folder
        absolute = os.path.join(self.tmp, "absolute-root")
        self.wgp.server_config = {"loras_root": absolute}
        self.assertEqual(self._run(), [self.base])
        self.assertEqual(self._read(os.path.join(absolute, "ltx2", self.base)), _LORA_PAYLOAD)
        # A relative root is under the app folder (the folder of the full server), not the working directory.
        # The working directory is deeper than the app folder, so resolving from it lands somewhere else.
        try:
            relative = os.path.relpath(os.path.join(self.tmp, "relative-root"), _APP_DIR)
        except ValueError:
            self.skipTest("the temporary folder is on another drive than the app folder")
        deep = os.path.join(self.tmp, *["cwd"] * (len(os.path.abspath(_APP_DIR).split(os.sep)) + 2))
        os.makedirs(deep)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(deep)
        self.wgp.server_config = {"loras_root": relative}
        self.assertEqual(self._run(), [self.base])
        self.assertEqual(self._read(os.path.join(self.tmp, "relative-root", "ltx2", self.base)), _LORA_PAYLOAD)


class TestCheckpointRegistration(unittest.TestCase):
    """Registering a downloaded checkpoint as a finetune of a supported architecture."""

    def _register(self, sidecar, architecture, **options):
        from unittest import mock

        from services import checkpoints

        with tempfile.TemporaryDirectory() as directory:
            defaults = os.path.join(directory, "defaults")
            finetunes = os.path.join(directory, "finetunes")
            os.makedirs(defaults)
            with open(os.path.join(defaults, "base_model.json"), "w", encoding="utf-8") as handle:
                json.dump({
                    "model": {
                        "name": "Base", "architecture": "base_arch",
                        "source": "https://example.invalid/base", "source2": "https://example.invalid/base2",
                        "URLs2": ["companion.safetensors"],
                    },
                    "prompt": "template prompt", "num_inference_steps": 20,
                }, handle)
            with mock.patch.object(checkpoints, "_DEFAULTS_DIR", defaults), \
                    mock.patch.object(checkpoints, "_FINETUNES_DIR", finetunes):
                result = checkpoints._register_checkpoint_finetune(
                    os.path.join(directory, "ckpts", "My Model.safetensors"), sidecar, architecture, **options,
                )
                written = {}
                for name in os.listdir(finetunes):
                    with open(os.path.join(finetunes, name), "r", encoding="utf-8") as handle:
                        written[name] = json.load(handle)
        return result, written

    def test_a_checkpoint_becomes_a_finetune_that_keeps_the_architecture_settings(self):
        sidecar = {
            "name": "My Model", "modelId": 9, "versionId": 10, "baseModel": "Base",
            "description": "  A long enough description.  ",
        }
        (slug, path), written = self._register(sidecar, "base_arch", auto_quantize=True)
        self.assertEqual(slug, "civitai_9_My_Model")
        self.assertEqual(os.path.basename(path), "civitai_9_My_Model.json")
        self.assertEqual(list(written), ["civitai_9_My_Model.json"])
        finetune = written["civitai_9_My_Model.json"]
        model = finetune["model"]
        self.assertEqual(model["name"], "My Model (Civitai)")
        self.assertEqual(model["architecture"], "base_arch")
        self.assertEqual(model["URLs"], ["My Model.safetensors"])
        self.assertEqual(model["URLs2"], ["companion.safetensors"])
        self.assertNotIn("source", model)
        self.assertNotIn("source2", model)
        self.assertEqual(model["description"], "A long enough description.")
        self.assertTrue(model["auto_quantize"])
        self.assertEqual(model["civitai"], {
            "modelId": 9, "versionId": 10, "modelType": "Checkpoint",
            "baseModel": "Base", "filename": "My Model.safetensors",
        })
        self.assertEqual((finetune["prompt"], finetune["num_inference_steps"]), ("template prompt", 20))

    def test_an_architecture_without_a_template_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "Unsupported target architecture 'no_such_arch'"):
            self._register({"name": "X", "modelId": 1}, "no_such_arch")


if __name__ == "__main__":
    unittest.main(verbosity=2)
