"""media.options: a ~1 KB answer to «what can this machine create with», never a secret."""
from __future__ import annotations

import asyncio
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "app"))

from services import media_options  # noqa: E402

MODELS = [
    {"model_type": "qwen_image_21", "architecture": "qwen_image_21", "name": "Qwen Image 2.1", "is_downloaded": True,
     "resource_requirements": {"vram_gb": 16}},
    {"model_type": "flux2_klein_9b", "architecture": "flux2_klein_9b", "name": "Flux Klein 9B", "is_downloaded": True},
    {"model_type": "qwen_image_21_bf16", "architecture": "qwen_image_21", "name": "Qwen BF16", "is_downloaded": False},
    {"model_type": "qwen_image_edit_20B", "architecture": "qwen_image_edit", "name": "Qwen Edit", "is_downloaded": True},
    {"model_type": "z_image_nsfw", "architecture": "z_image", "name": "Hidden", "is_downloaded": True, "nsfw_only": True},
    {"model_type": "ltx2_22B", "architecture": "ltx2", "name": "LTX", "is_downloaded": True},
]
SERVICES = {"minimax_image_api_key_set": True, "minimax_music_api_key_set": False, "meshy_api_key_set": False,
            "openai_api_key_set": True, "minimax_api_key": "sk-secret-value"}
PROFILE = {"configured": False, "profile": {"version": 1, "image": {"provider": "minimax", "model": "image-01"},
                                           "text": {"provider": "minimax", "model": "MiniMax-M3", "base_url": "https://x"}}}


def test_only_installed_visible_image_models_are_listed_with_their_cost():
    local = media_options.build(MODELS, SERVICES, PROFILE)["local"]["image"]
    assert [m["id"] for m in local] == ["flux2_klein_9b", "qwen_image_21", "qwen_image_edit_20B"]
    assert next(m for m in local if m["id"] == "qwen_image_21")["vram_gb"] == 16
    assert next(m for m in local if m["id"] == "qwen_image_edit_20B")["needs_input_image"] is True


def test_cloud_providers_are_ready_or_need_a_key_and_no_secret_is_returned():
    result = media_options.build(MODELS, SERVICES, PROFILE)
    assert result["cloud"]["image"] == {"ready": ["minimax"], "needs_key": []}
    assert result["cloud"]["music"] == {"ready": [], "needs_key": ["minimax"]}
    assert result["cloud"]["model3d"]["needs_key"] == ["meshy", "hi3d"]
    assert "openai" in result["cloud"]["text"]["ready"]
    assert "sk-secret-value" not in json.dumps(result)


def test_the_profile_is_what_a_request_with_no_choice_would_use():
    profile = media_options.build(MODELS, SERVICES, PROFILE)["profile"]
    assert profile == {"configured": False, "image": {"provider": "minimax", "model": "image-01"},
                       "text": {"provider": "minimax", "model": "MiniMax-M3"}}


def test_the_answer_is_small_and_tells_the_assistant_to_ask():
    result = media_options.build(MODELS, SERVICES, PROFILE)
    assert len(json.dumps(result)) < 2500 and "ask once" in result["guidance"]


def test_the_handler_answers_in_the_shape_of_the_other_commands():
    handlers = media_options.command_handlers(lambda: (MODELS, SERVICES, PROFILE))
    answer = asyncio.run(handlers["media.options"]({"version": 1}))
    assert answer["status"] == "completed" and answer["operation"] == "media.options"
    assert answer["result"]["local"]["image"][0]["id"] == "flux2_klein_9b"
    catalog = media_options.command_catalog()[0]
    assert catalog["name"] == "media.options" and catalog["mutation"] is False


def test_the_launcher_registers_the_command_and_reads_the_masked_services_booleans():
    source = open(os.path.join(ROOT, "app", "_launch_runtime.py"), encoding="utf-8").read()
    assert "**media_options_handlers(_media_options_sources)" in source and "*media_options_catalog()" in source
    assert "get_services_config(), _production_profile_response()" in source


def test_an_assistant_finds_and_calls_it_through_the_real_mcp_router(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.wangp_mcp import create_wangp_mcp_router

    app = FastAPI()
    app.include_router(create_wangp_mcp_router(
        handlers=media_options.command_handlers(lambda: (MODELS, SERVICES, PROFILE)),
        journal_path=tmp_path / "requests.db", token_getter=lambda: "test-token",
        command_operations=media_options.command_catalog()))
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(app) as client:
        listed = client.post("/api/v1/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()
        tool = next(t for t in listed["result"]["tools"] if t["name"] == "media.options")
        assert "ask the user" in tool["description"]
        called = client.post("/api/v1/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "media.options", "arguments": {"version": 1}}}).json()
        text = called["result"]["content"][0]["text"]
        assert not called["result"].get("isError") and "flux2_klein_9b" in text and "sk-secret-value" not in text
