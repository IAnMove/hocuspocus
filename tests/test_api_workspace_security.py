import ast
import asyncio
import copy
import os
import re
from pathlib import Path

from fastapi import Request as FastAPIRequest
from fastapi.responses import JSONResponse


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "launch.py"


def load_function(name: str, namespace: dict):
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    node = copy.deepcopy(next(
        item for item in tree.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name
    ))
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(LAUNCH), "exec"), namespace)


def test_output_resolution_never_searches_another_workspace(tmp_path):
    default = tmp_path / "default"
    other = tmp_path / "other"
    default.mkdir(); other.mkdir()
    (other / "same.mp4").write_bytes(b"other")

    def safe_join(base, *parts):
        candidate = os.path.realpath(os.path.join(base, *parts))
        return candidate if candidate.startswith(os.path.realpath(base) + os.sep) else None

    namespace = {
        "os": os,
        "_workspace_dir": lambda workspace=None: str(other if workspace == "other" else default),
        "_safe_join": safe_join,
    }
    load_function("_resolve_output_file", namespace)

    assert namespace["_resolve_output_file"]("same.mp4") is None
    assert namespace["_resolve_output_file"]("same.mp4", "other") == str(other / "same.mp4")


def test_browser_mutations_require_a_same_host_origin():
    namespace = {"re": re, "JSONResponse": JSONResponse, "Request": FastAPIRequest}
    load_function("protect_cross_origin_mutations", namespace)
    calls = []

    class Request:
        method = "POST"

        def __init__(self, origin, host):
            self.headers = {"origin": origin, "host": host}

    async def next_handler(_request):
        calls.append(True)
        return JSONResponse({"ok": True})

    rejected = asyncio.run(namespace["protect_cross_origin_mutations"](
        Request("https://evil.example", "192.168.1.5:42004"), next_handler,
    ))
    accepted = asyncio.run(namespace["protect_cross_origin_mutations"](
        Request("http://192.168.1.5:42004", "192.168.1.5:42004"), next_handler,
    ))

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert calls == [True]
