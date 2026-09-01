"""Regression tests for Story Lab character IDs and MiniMax identity references."""

from __future__ import annotations

import ast
import base64
import copy
import json
import os
import re
import tempfile
import time
import types
import unittest
import uuid
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from services import minimax_image_service  # noqa: E402


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _load_launch_functions(*names: str, namespace: dict | None = None) -> dict:
    launch_path = os.path.join(os.path.dirname(__file__), "..", "app", "_launch_runtime.py")
    with open(launch_path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node = copy.deepcopy(node)
            node.decorator_list = []
            selected.append(node)
    scope = dict(namespace or {})
    exec(compile(ast.Module(body=selected, type_ignores=[]), "_launch_runtime.py", "exec"), scope)
    return scope


class _MiniMaxResponse:
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {"image_base64": [base64.b64encode(b"jpeg-bytes").decode("ascii")]},
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }


class TestComicStoryReferences(unittest.TestCase):
    def test_panel_characters_resolve_names_and_keep_visual_priority(self):
        scope = _load_launch_functions(
            "_normalize_comic_panel_character_ids",
            namespace={"re": re},
        )
        panel = {"characters": [" VIGIL ", "Nara", "vigil", "unknown"]}
        scope["_normalize_comic_panel_character_ids"](panel, [
            {"id": "nara", "name": "Nara"},
            {"id": "vigil", "name": "The Vigil"},
        ])
        self.assertEqual(panel["characters"], ["vigil", "nara"])

    def test_local_reference_is_sent_to_minimax_as_one_character_subject(self):
        with tempfile.TemporaryDirectory() as workspace:
            post = Mock(return_value=_MiniMaxResponse())
            requests = types.SimpleNamespace(post=post, RequestException=Exception)
            wgp = types.SimpleNamespace(server_config={
                "services": {"minimax_api_key": "configured-in-settings"},
            })

            def safe_join(root: str, filename: str):
                candidate = os.path.abspath(os.path.join(root, filename))
                return candidate if candidate.startswith(os.path.abspath(root) + os.sep) else None

            scope = _load_launch_functions(
                "_comic_reference_image_file",
                "generate_comic_minimax",
                namespace={
                    "HTTPException": HTTPException,
                    "_safe_join": safe_join,
                    "_get_active_workspace": lambda: "default",
                    "_workspace_dir": lambda _workspace=None: workspace,
                    "execution_mode": types.SimpleNamespace(
                        validate_remote_provider=lambda _workspace, _provider: None,
                    ),
                    "base64": base64,
                    "json": json,
                    "os": os,
                    "re": re,
                    "requests": requests,
                    "time": time,
                    "uuid": uuid,
                    "wgp": wgp,
                },
            )
            reference_path = os.path.join(workspace, "hero.png")
            with open(reference_path, "wb") as handle:
                handle.write(b"reference-image")

            scope["minimax_image_service"] = minimax_image_service
            with patch.object(minimax_image_service.requests, "post", post):
                result = scope["generate_comic_minimax"]({
                    "prompt": "The hero crosses the salt desert at dusk.",
                    "aspect_ratio": "4:3",
                    "subject_reference": "/api/v1/file/hero.png",
                })

            payload = post.call_args.kwargs["json"]
            self.assertEqual(payload["model"], "image-01")
            self.assertEqual(payload["aspect_ratio"], "4:3")
            self.assertFalse(payload["prompt_optimizer"])
            self.assertEqual(len(payload["subject_reference"]), 1)
            self.assertEqual(payload["subject_reference"][0]["type"], "character")
            self.assertTrue(
                payload["subject_reference"][0]["image_file"].startswith("data:image/png;base64,")
            )
            self.assertTrue(result["asset"]["metadata"]["subjectReference"])
            self.assertEqual(result["asset"]["metadata"]["aspectRatio"], "4:3")

    def test_private_reference_url_is_rejected(self):
        scope = _load_launch_functions(
            "_comic_reference_image_file",
            namespace={"HTTPException": HTTPException},
        )
        with self.assertRaises(HTTPException) as raised:
            scope["_comic_reference_image_file"]("http://127.0.0.1/private.png")
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
