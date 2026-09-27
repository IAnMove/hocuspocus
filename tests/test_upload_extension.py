import ast
import os
import re
from pathlib import Path

LAUNCH = Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py"


def _upload_extension():
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_upload_extension")
    namespace = {"os": os, "re": re}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(LAUNCH), "exec"), namespace)
    return namespace["_upload_extension"]


def test_upload_extension_drops_url_query_and_fragment():
    ext = _upload_extension()
    assert ext("b44e65f3.jpg?workspace=default", "img.png") == ".jpg"
    assert ext("clip.MP4#t=3", "audio.wav") == ".mp4"
    assert ext(None, "img.png") == ".png"
    assert ext("evil.jp g/../x", "img.png") == ""
