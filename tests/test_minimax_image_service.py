"""Tests for the shared external MiniMax Image-01 integration."""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from services import director_pipeline, minimax_image_service  # noqa: E402


class _MiniMaxResponse:
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {"image_base64": [base64.b64encode(b"jpeg-bytes").decode("ascii")]},
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }


class TestMiniMaxImageService(unittest.TestCase):
    def test_resolution_maps_to_supported_aspect_ratio(self):
        self.assertEqual(minimax_image_service.aspect_ratio_for_resolution("1280x720"), "16:9")
        self.assertEqual(minimax_image_service.aspect_ratio_for_resolution("720x1280"), "9:16")
        self.assertEqual(minimax_image_service.aspect_ratio_for_resolution("1024x1024"), "1:1")

    def test_generation_uses_fixed_provider_model_without_persisting_key(self):
        post = Mock(return_value=_MiniMaxResponse())
        with tempfile.TemporaryDirectory() as output_dir, patch.object(
            minimax_image_service.requests, "post", post,
        ):
            result = minimax_image_service.generate_image(
                api_key="test-secret-not-for-production",
                prompt="  A cinematic frame\nwith one hero.  ",
                aspect_ratio="16:9",
                output_dir=output_dir,
            )

            request = post.call_args
            self.assertEqual(request.args[0], minimax_image_service.API_URL)
            self.assertEqual(request.kwargs["json"]["model"], "image-01")
            self.assertEqual(
                request.kwargs["headers"]["Authorization"],
                "Bearer test-secret-not-for-production",
            )
            self.assertTrue(os.path.isfile(result["path"]))
            meta_path = os.path.splitext(result["path"])[0] + ".meta.json"
            with open(meta_path, "r", encoding="utf-8") as handle:
                metadata_text = handle.read()
            self.assertNotIn("test-secret-not-for-production", metadata_text)
            self.assertEqual(json.loads(metadata_text)["params"]["provider"], "minimax")

    def test_director_prioritises_character_reference_and_saved_key(self):
        previous_wgp = director_pipeline._wgp
        director_pipeline._wgp = types.SimpleNamespace(server_config={
            "services": {"minimax_api_key": "configured-in-settings"},
        })
        try:
            with tempfile.TemporaryDirectory() as output_dir:
                character_path = os.path.join(output_dir, "character.png")
                with open(character_path, "wb") as handle:
                    handle.write(b"reference")
                generated = Mock(return_value={"name": "frame.jpg"})
                with patch.object(minimax_image_service, "generate_image", generated):
                    name = director_pipeline._generate_minimax_director_image(
                        prompt="A hero enters the observatory.",
                        resolution="1280x720",
                        output_dir=output_dir,
                        reference_paths=[character_path],
                    )
                self.assertEqual(name, "frame.jpg")
                kwargs = generated.call_args.kwargs
                self.assertEqual(kwargs["api_key"], "configured-in-settings")
                self.assertEqual(kwargs["aspect_ratio"], "16:9")
                self.assertTrue(kwargs["subject_reference"].startswith("data:image/png;base64,"))
        finally:
            director_pipeline._wgp = previous_wgp


if __name__ == "__main__":
    unittest.main()
