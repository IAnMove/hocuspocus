"""MiniMax-M3 must stay on the hosted API, never a Hugging Face GGUF."""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services import director_pipeline, llm_service  # noqa: E402


class TestMiniMaxChatRouting(unittest.TestCase):
    def test_normalize_forces_hosted_minimax_for_chat_ids(self):
        provider, url = llm_service.normalize_minimax_chat_routing(
            "MiniMax-M3",
            "local",
            "",
        )
        self.assertEqual(provider, "minimax")
        self.assertEqual(url, "https://api.minimax.io")

    def test_load_model_does_not_download_minimax_chat_gguf(self):
        with patch.object(llm_service, "_download_gguf") as download:
            llm_service.load_model(
                model_id="MiniMax-M3",
                device="cpu",
                provider="local",
                remote_url="",
                api_key="server-secret",
            )
        download.assert_not_called()
        status = llm_service.get_status()
        self.assertEqual(status.get("provider"), "minimax")
        self.assertEqual(status.get("model_id"), "MiniMax-M3")
        llm_service.unload_model()

    def test_director_ensure_passes_minimax_api_key(self):
        previous = director_pipeline._wgp
        captured = {}

        def fake_load(**kwargs):
            captured.update(kwargs)

        director_pipeline._wgp = SimpleNamespace(server_config={
            "services": {
                "llm_provider": "minimax",
                "llm_model_id": "MiniMax-M3",
                "minimax_api_key": "server-secret",
            },
        })
        try:
            with patch.object(llm_service, "is_loaded", return_value=False), patch.object(
                llm_service, "load_model", side_effect=fake_load,
            ):
                director_pipeline._ensure_llm_loaded({
                    "llm_provider": "local",
                })
        finally:
            director_pipeline._wgp = previous

        self.assertEqual(captured.get("provider"), "minimax")
        self.assertEqual(captured.get("model_id"), "MiniMax-M3")
        self.assertEqual(captured.get("api_key"), "server-secret")
        self.assertEqual(captured.get("remote_url"), "https://api.minimax.io")


if __name__ == "__main__":
    unittest.main()
