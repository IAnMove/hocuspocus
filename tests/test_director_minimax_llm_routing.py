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

    def test_generic_generate_uses_hardened_minimax_completion_path(self):
        previous = {
            "provider": llm_service._provider,
            "model_id": llm_service._model_id,
            "remote_url": llm_service._remote_url,
            "api_key": llm_service._api_key,
        }
        llm_service._provider = "minimax"
        llm_service._model_id = "MiniMax-M3"
        llm_service._remote_url = "https://api.minimax.io"
        llm_service._api_key = "server-secret"
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
        try:
            with patch.object(llm_service, "is_loaded", return_value=True), patch.object(
                llm_service, "generate_openai_compatible", return_value='{"ok":true}',
            ) as compatible:
                result = llm_service.generate(
                    prompt="return JSON",
                    system_prompt="planner",
                    max_new_tokens=4000,
                    temperature=0.15,
                    json_schema=schema,
                )
        finally:
            llm_service._provider = previous["provider"]
            llm_service._model_id = previous["model_id"]
            llm_service._remote_url = previous["remote_url"]
            llm_service._api_key = previous["api_key"]

        self.assertEqual(result, '{"ok":true}')
        compatible.assert_called_once()
        kwargs = compatible.call_args.kwargs
        self.assertEqual(kwargs["model_id"], "MiniMax-M3")
        self.assertEqual(kwargs["json_schema"], schema)
        self.assertEqual(kwargs["max_new_tokens"], 4000)

    def test_director_reloads_when_a_deepseek_url_changes_and_sends_its_key(self):
        """Director used to ignore a DeepSeek URL change and never read its key."""
        previous = director_pipeline._wgp
        unloaded = []
        loaded = {}

        def fake_load(**kwargs):
            loaded.update(kwargs)

        director_pipeline._wgp = SimpleNamespace(server_config={
            "services": {
                "llm_provider": "deepseek",
                "llm_model_id": "deepseek-v4-flash",
                "llm_remote_url": "https://api.deepseek.com",
                "deepseek_api_key": "ds-secret",
            },
        })
        try:
            with patch.object(llm_service, "is_loaded", return_value=True), patch.object(
                llm_service, "get_status", return_value={
                    "model_id": "deepseek-v4-flash",
                    "provider": "deepseek",
                    "device": "deepseek",
                    "remote_url": "https://old.example",
                },
            ), patch.object(
                llm_service, "unload_model", side_effect=lambda: unloaded.append(True),
            ), patch.object(llm_service, "load_model", side_effect=fake_load):
                director_pipeline._ensure_llm_loaded({})
        finally:
            director_pipeline._wgp = previous

        self.assertEqual(unloaded, [True])
        self.assertEqual(loaded.get("provider"), "deepseek")
        self.assertEqual(loaded.get("model_id"), "deepseek-v4-flash")
        self.assertEqual(loaded.get("api_key"), "ds-secret")
        self.assertEqual(loaded.get("remote_url"), "https://api.deepseek.com")

    def test_director_reloads_a_local_model_when_the_device_changes(self):
        previous = director_pipeline._wgp
        unloaded = []
        loaded = {}

        def fake_load(**kwargs):
            loaded.update(kwargs)

        director_pipeline._wgp = SimpleNamespace(server_config={"services": {}})
        try:
            with patch.object(llm_service, "is_loaded", return_value=True), patch.object(
                llm_service, "get_status", return_value={
                    "model_id": "Abhiray/gemma-4-E4B-it-heretic-GGUF",
                    "provider": "local",
                    "device": "cpu",
                    "remote_url": "",
                },
            ), patch.object(
                llm_service, "unload_model", side_effect=lambda: unloaded.append(True),
            ), patch.object(llm_service, "load_model", side_effect=fake_load):
                director_pipeline._ensure_llm_loaded({"llm_device": "cuda", "llm_provider": "local"})
        finally:
            director_pipeline._wgp = previous

        self.assertEqual(unloaded, [True])
        self.assertEqual(loaded.get("provider"), "local")
        self.assertEqual(loaded.get("device"), "cuda")
        self.assertEqual(loaded.get("model_id"), "Abhiray/gemma-4-E4B-it-heretic-GGUF")

    def test_director_keeps_a_loaded_deepseek_model_when_nothing_changed(self):
        previous = director_pipeline._wgp
        director_pipeline._wgp = SimpleNamespace(server_config={
            "services": {
                "llm_provider": "deepseek",
                "llm_model_id": "deepseek-v4-flash",
                "llm_remote_url": "https://api.deepseek.com",
                "deepseek_api_key": "ds-secret",
            },
        })
        try:
            with patch.object(llm_service, "is_loaded", return_value=True), patch.object(
                llm_service, "get_status", return_value={
                    "model_id": "deepseek-v4-flash",
                    "provider": "deepseek",
                    "device": "deepseek",
                    "remote_url": "https://api.deepseek.com",
                },
            ), patch.object(llm_service, "unload_model") as unload, patch.object(
                llm_service, "load_model",
            ) as load:
                director_pipeline._ensure_llm_loaded({})
        finally:
            director_pipeline._wgp = previous
        unload.assert_not_called()
        load.assert_not_called()


class TestSharedLlmReload(unittest.TestCase):
    """The shared loader reloads when an Anthropic or DeepSeek URL changes.

    Launch's copy compared only remote, ollama, openai, minimax and grok, so a
    new Anthropic or DeepSeek URL kept talking to the previous host.
    """

    def _load(self, *, provider, model, old_url, new_url, device="cpu", status_device=None):
        from services import llm_routing

        loaded = {}
        unloaded = []

        def fake_load(**kwargs):
            loaded.update(kwargs)

        with patch.object(llm_service, "is_loaded", return_value=True), patch.object(
            llm_service, "get_status", return_value={
                "model_id": model,
                "provider": provider,
                "device": provider if status_device is None else status_device,
                "remote_url": old_url,
            },
        ), patch.object(
            llm_service, "unload_model", side_effect=lambda: unloaded.append(True),
        ), patch.object(llm_service, "load_model", side_effect=fake_load):
            llm_routing._ensure_llm_loaded(
                services={f"{provider}_api_key": "secret"},
                provider=provider,
                model=model,
                remote_url=new_url,
                device=device,
                default_model="Abhiray/gemma-4-E4B-it-heretic-GGUF",
            )
        return unloaded, loaded

    def test_an_anthropic_url_that_the_service_reports_and_changed_reloads(self):
        unloaded, loaded = self._load(
            provider="anthropic",
            model="claude",
            old_url="https://old.example",
            new_url="https://api.anthropic.com",
            status_device="anthropic",
        )
        self.assertEqual(unloaded, [True])
        self.assertEqual(loaded.get("remote_url"), "https://api.anthropic.com")
        self.assertEqual(loaded.get("api_key"), "secret")
        self.assertEqual(loaded.get("provider"), "anthropic")

    def test_anthropic_with_a_configured_url_does_not_reload_on_every_call(self):
        """The real llm_service never reports an Anthropic URL, so "" is not a change.

        ``get_status()`` hides ``remote_url`` for Anthropic and Anthropic
        requests ignore it. A leftover ``llm_remote_url`` made every call look
        like a URL change and unloaded and loaded the client each time.
        """
        from services import llm_routing

        unloaded = []
        real_unload = llm_service.unload_model
        self.addCleanup(real_unload)

        def counting_unload():
            unloaded.append(True)
            real_unload()

        with patch.object(llm_service, "unload_model", side_effect=counting_unload):
            for _ in range(3):
                llm_routing._ensure_llm_loaded(
                    services={"anthropic_api_key": "secret"},
                    provider="anthropic",
                    model="claude",
                    remote_url="https://proxy.example",
                    device="cpu",
                    default_model="Abhiray/gemma-4-E4B-it-heretic-GGUF",
                )
        self.assertEqual(llm_service.get_status()["provider"], "anthropic")
        self.assertEqual(unloaded, [])

    def test_deepseek_url_change_reloads_and_the_same_url_does_not(self):
        unloaded, loaded = self._load(
            provider="deepseek",
            model="deepseek-v4-flash",
            old_url="https://old.example",
            new_url="https://api.deepseek.com",
            status_device="deepseek",
        )
        self.assertEqual(unloaded, [True])
        self.assertEqual(loaded.get("api_key"), "secret")
        same_unloaded, same_loaded = self._load(
            provider="deepseek",
            model="deepseek-v4-flash",
            old_url="https://api.deepseek.com",
            new_url="https://api.deepseek.com",
            status_device="deepseek",
        )
        self.assertEqual(same_unloaded, [])
        self.assertEqual(same_loaded, {})

    def test_core_reloads_when_a_deepseek_url_changes(self):
        """Core's loader is the shared one, so a new DeepSeek URL reloads."""
        from services import core_production

        loaded = {}
        unloaded = []

        def fake_load(**kwargs):
            loaded.update(kwargs)

        with patch.object(core_production.core, "services_raw", return_value={
            "deepseek_api_key": "ds-secret",
            "llm_remote_url": "https://api.deepseek.com",
        }), patch.object(
            core_production, "production_profile_response", return_value={
                "configured": True,
                "profile": {"text": {
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "base_url": "https://api.deepseek.com",
                }},
            },
        ), patch.object(llm_service, "is_loaded", return_value=True), patch.object(
            llm_service, "get_status", return_value={
                "model_id": "deepseek-v4-flash",
                "provider": "deepseek",
                "device": "deepseek",
                "remote_url": "https://old.example",
            },
        ), patch.object(
            llm_service, "unload_model", side_effect=lambda: unloaded.append(True),
        ), patch.object(llm_service, "load_model", side_effect=fake_load):
            core_production.ensure_llm_loaded()
        self.assertEqual(unloaded, [True])
        self.assertEqual(loaded.get("model_id"), "deepseek-v4-flash")
        self.assertEqual(loaded.get("api_key"), "ds-secret")
        self.assertEqual(loaded.get("device"), "cpu")
        self.assertEqual(loaded.get("remote_url"), "https://api.deepseek.com")

    def test_a_local_provider_runs_the_injected_gate_before_loading(self):
        from services import llm_routing

        seen = []

        def require_local():
            seen.append("gate")
            raise RuntimeError("local llm unavailable")

        with patch.object(llm_service, "load_model") as load:
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                llm_routing._ensure_llm_loaded(
                    services={},
                    provider="local",
                    model="Abhiray/gemma-4-E4B-it-heretic-GGUF",
                    remote_url="",
                    device="cpu",
                    default_model="Abhiray/gemma-4-E4B-it-heretic-GGUF",
                    require_local=require_local,
                )
        self.assertEqual(seen, ["gate"])
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
