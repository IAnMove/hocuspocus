import ast
import copy
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "launch.py"


def load_list_outputs(namespace: dict):
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    node = copy.deepcopy(next(
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "list_outputs"
    ))
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(LAUNCH), "exec"), namespace)


def list_test_outputs(tmp_path):
    namespace = {
        "os": os,
        "json": json,
        "time": time,
        "threading": threading,
        "quote": quote,
        "Response": object,
        "wgp": SimpleNamespace(server_config={"save_path": str(tmp_path)}),
        "_workspace_dir": lambda workspace=None: str(tmp_path),
        "_load_favorites": lambda: set(),
        "_output_scan_cache": {},
        "_output_scan_cache_lock": threading.Lock(),
        "_OUTPUT_SCAN_CACHE_MAX_AGE_SECONDS": 5.0,
    }
    load_list_outputs(namespace)

    class Response:
        headers = {}

    return namespace["list_outputs"](Response())["outputs"]


def test_output_list_exposes_exact_sidecar_completion_time(tmp_path):
    media = tmp_path / "result.mp4"
    media.write_bytes(b"video")
    os.utime(media, (100.0, 100.0))
    (tmp_path / "result.meta.json").write_text(
        json.dumps({"created_at": 234.5, "params": {}}),
        encoding="utf-8",
    )

    [output] = list_test_outputs(tmp_path)

    assert output["created_at"] == 100.0
    assert output["completed_at"] == 234.5
    assert output["completion_time_source"] == "metadata"


def test_output_list_marks_file_timestamp_as_approximate_fallback(tmp_path):
    media = tmp_path / "legacy.png"
    media.write_bytes(b"image")
    os.utime(media, (345.0, 345.0))

    [output] = list_test_outputs(tmp_path)

    assert output["completed_at"] == 345.0
    assert output["completion_time_source"] == "file"
