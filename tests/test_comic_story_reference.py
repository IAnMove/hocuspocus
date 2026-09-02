"""Regression tests for Story Lab character IDs and MiniMax identity references."""

from __future__ import annotations

import ast
import base64
import copy
import os
import re
import tempfile
import unittest
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from services import minimax_image_service  # noqa: E402


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
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from routers.comics import create_comics_router

        with tempfile.TemporaryDirectory() as workspace:
            post = Mock(return_value=_MiniMaxResponse())

            def safe_join(root: str, filename: str):
                candidate = os.path.abspath(os.path.join(root, filename))
                return candidate if candidate.startswith(os.path.abspath(root) + os.sep) else None

            app = FastAPI()
            app.include_router(create_comics_router(
                workspace_dir=lambda _workspace=None: workspace,
                get_active_workspace=lambda: "default",
                safe_join=safe_join,
                get_services_config=lambda: {"minimax_api_key": "configured-in-settings"},
                publish_legacy_task=lambda *_args, **_kwargs: None,
            ))
            reference_path = os.path.join(workspace, "hero.png")
            with open(reference_path, "wb") as handle:
                handle.write(b"reference-image")

            with patch.object(minimax_image_service.requests, "post", post):
                result = TestClient(app).post("/api/v1/comics/generate/minimax", json={
                    "prompt": "The hero crosses the salt desert at dusk.",
                    "aspect_ratio": "4:3",
                    "subject_reference": "/api/v1/file/hero.png",
                }).json()

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
        from fastapi import HTTPException as FastAPIHTTPException
        from routers.comics import _comic_reference_image_file

        with self.assertRaises(FastAPIHTTPException) as raised:
            _comic_reference_image_file("http://127.0.0.1/private.png")
        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
