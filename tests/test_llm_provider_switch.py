"""Switching the LLM provider to the internal server must not keep a remote model."""
from __future__ import annotations

import ast
import asyncio
import copy
import json
import os
import sys
from types import SimpleNamespace

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAUNCH_PATH = os.path.join(ROOT, "app", "_launch_runtime.py")
sys.path.insert(0, os.path.join(ROOT, "app"))

from services.llm_service import DEFAULT_HF_REPO, MODEL_REGISTRY  # noqa: E402

PROFILE_KEY = "maestro_production_profile"


class _HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = ""):
        super().__init__(detail)
        self.status_code = status_code


class _Request:
    def __init__(self, body: dict):
        self._body = body

    async def json(self) -> dict:
        return self._body


def _handler(config: dict, config_path: str):
    source = open(LAUNCH_PATH, encoding="utf-8").read()
    function = next(
        node for node in ast.parse(source, filename=LAUNCH_PATH).body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "update_services_config"
    )
    function.decorator_list = []
    module = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "json": json,
        "HTTPException": _HTTPException,
        "wgp": SimpleNamespace(server_config=config, server_config_filename=config_path),
        "_mask_key": lambda value: value,
        "_PUBLIC_LLM_PROVIDERS": frozenset({"openai", "anthropic", "minimax", "grok"}),
        "_PRODUCTION_PROFILE_CONFIG_KEY": PROFILE_KEY,
        "_DEFAULT_LLM_REPO": DEFAULT_HF_REPO,
        "_active_production_profile": lambda: copy.deepcopy(config[PROFILE_KEY]),
        "_normalize_production_profile": lambda profile: profile,
        "_effective_llm_routing": lambda services=None: (
            config[PROFILE_KEY]["text"]["provider"],
            config[PROFILE_KEY]["text"]["model"],
            config[PROFILE_KEY]["text"]["base_url"],
        ),
    }
    exec(compile(module, LAUNCH_PATH, "exec"), namespace)
    return namespace["update_services_config"]


def _minimax_config() -> dict:
    return {
        "services": {"llm_provider": "minimax", "llm_remote_url": "https://api.minimax.io"},
        PROFILE_KEY: {"text": {"provider": "minimax", "model": "MiniMax-M3",
                               "base_url": "https://api.minimax.io"}},
    }


def _update(tmp_path, config: dict, body: dict) -> dict:
    handler = _handler(config, str(tmp_path / "wgp_config.json"))
    return asyncio.run(handler(_Request(body)))


def test_switching_to_local_replaces_a_minimax_model_and_url(tmp_path):
    config = _minimax_config()
    result = _update(tmp_path, config, {"llm_provider": "local"})
    text = config[PROFILE_KEY]["text"]
    assert text == {"provider": "local", "model": DEFAULT_HF_REPO, "base_url": ""}
    assert result["updated"]["llm_model_id"] == DEFAULT_HF_REPO
    assert config["services"]["llm_remote_url"] == ""


def test_switching_to_local_keeps_an_explicit_model(tmp_path):
    config = _minimax_config()
    chosen = next(iter(MODEL_REGISTRY))
    _update(tmp_path, config, {"llm_provider": "local", "llm_model_id": chosen})
    assert config[PROFILE_KEY]["text"]["model"] == chosen


def test_switching_to_local_keeps_a_registered_local_model(tmp_path):
    config = _minimax_config()
    local_model = next(iter(MODEL_REGISTRY))
    config[PROFILE_KEY]["text"]["model"] = local_model
    _update(tmp_path, config, {"llm_provider": "local"})
    assert config[PROFILE_KEY]["text"]["model"] == local_model


def test_switching_between_remote_providers_is_unchanged(tmp_path):
    config = _minimax_config()
    _update(tmp_path, config, {"llm_provider": "grok", "llm_remote_url": "https://api.x.ai"})
    text = config[PROFILE_KEY]["text"]
    assert text["provider"] == "grok" and text["model"] == "MiniMax-M3"
    assert text["base_url"] == "https://api.x.ai"
