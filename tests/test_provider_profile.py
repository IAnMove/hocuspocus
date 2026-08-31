from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services import llm_service, provider_profile  # noqa: E402
from services.meshy_3d_service import generate_model as meshy_generate  # noqa: E402
from services.hi3d_service import generate_model as hi3d_generate  # noqa: E402


class TestProviderProfile(unittest.TestCase):
    def test_canonicalize_strips_v1_and_slash(self):
        self.assertEqual(
            provider_profile.canonicalize_remote_url("http://127.0.0.1:11434/v1/"),
            "http://127.0.0.1:11434",
        )
        self.assertEqual(
            provider_profile.openai_chat_completions_url("http://127.0.0.1:11434/v1"),
            "http://127.0.0.1:11434/v1/chat/completions",
        )

    def test_minimax_keys_are_split_with_legacy_fallback(self):
        services = {"minimax_api_key": "shared", "minimax_image_api_key": "image-only"}
        self.assertEqual(provider_profile.resolve_minimax_key(services, "llm"), "shared")
        self.assertEqual(provider_profile.resolve_minimax_key(services, "image"), "image-only")
        self.assertEqual(provider_profile.resolve_minimax_key(services, "music"), "shared")

    def test_ollama_writing_override_does_not_need_a_key(self):
        override = provider_profile.resolve_writing_override(
            provider="ollama",
            model="gemma3:4b",
            requested_url="http://192.168.1.10:11434/v1",
            services={},
        )
        self.assertEqual(override["provider"], "ollama")
        self.assertEqual(override["model"], "gemma3:4b")
        self.assertEqual(override["base_url"], "http://192.168.1.10:11434")
        self.assertEqual(override["api_key"], "")

    def test_character_describe_only_minimax_or_local(self):
        self.assertEqual(provider_profile.character_describe_backend("minimax"), "minimax")
        self.assertEqual(provider_profile.character_describe_backend("local"), "local")
        self.assertEqual(provider_profile.character_describe_backend("ollama"), "unavailable")
        self.assertEqual(provider_profile.character_describe_backend("grok"), "unavailable")

    def test_alias_remote_11434_to_ollama(self):
        self.assertEqual(
            provider_profile.alias_text_provider("remote", "http://127.0.0.1:11434"),
            "ollama",
        )


class TestOllamaModelListing(unittest.TestCase):
    def test_lists_ollama_tags_without_double_v1(self):
        class _Resp:
            ok = True
            def json(self):
                return {"models": [{"name": "gemma3:4b"}, {"name": "llama3.2:3b"}]}

        with patch("services.llm_service.requests.get", return_value=_Resp()) as get:
            models = llm_service.get_available_models(
                provider="ollama",
                remote_url="http://127.0.0.1:11434/v1",
            )
        self.assertEqual(get.call_args.args[0], "http://127.0.0.1:11434/api/tags")
        ids = [item["id"] for item in models if item.get("provider") == "ollama"]
        self.assertEqual(ids, ["gemma3:4b", "llama3.2:3b"])


class TestRemote3D(unittest.TestCase):
    def test_meshy_image_to_3d_polls_and_downloads(self):
        class _Resp:
            def __init__(self, payload, content=b"", ok=True, status_code=200):
                self._payload = payload
                self.content = content or b"{}"
                self.ok = ok
                self.status_code = status_code
            def json(self):
                return self._payload
            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError("http")

        calls = []

        def fake_post(url, **kwargs):
            calls.append(("post", url))
            return _Resp({"result": "task-1"})

        def fake_get(url, **kwargs):
            calls.append(("get", url))
            if "image-to-3d/task-1" in url:
                return _Resp({
                    "status": "SUCCEEDED",
                    "model_urls": {"glb": "https://assets.meshy.ai/model.glb"},
                })
            return _Resp({}, content=b"glb-bytes")

        with patch("services.meshy_3d_service.requests.post", side_effect=fake_post), patch(
            "services.meshy_3d_service.requests.get", side_effect=fake_get,
        ), patch(
            "services.meshy_3d_service.local_image_data_uri",
            return_value="data:image/png;base64,xx",
        ):
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                result = meshy_generate(
                    api_key="msy-key",
                    output_dir=tmp,
                    image_path="/tmp/ref.png",
                    filename_stem="meshy-test",
                )
                self.assertTrue(os.path.isfile(result["path"]))
                self.assertEqual(result["provider"], "meshy")
        self.assertTrue(any(url.endswith("/image-to-3d") for kind, url in calls if kind == "post"))

    def test_hi3d_requires_an_image(self):
        with self.assertRaisesRegex(Exception, "reference image"):
            hi3d_generate(api_key="hi-key", image_path="", output_dir="/tmp")


if __name__ == "__main__":
    unittest.main()
