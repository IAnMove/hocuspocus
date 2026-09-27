"""ASGI contracts for the extracted /api/v1/llm FastAPI routers."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.llm import create_llm_prompt_router, create_llm_router


LLM_HTTP_SURFACE = [
    ("GET", "/api/v1/llm/status", "llm_status"),
    ("POST", "/api/v1/llm/load", "llm_load"),
    ("POST", "/api/v1/llm/unload", "llm_unload"),
    ("GET", "/api/v1/llm/models", "list_llm_models"),
    ("GET", "/api/v1/llm/stream-status", "llm_stream_status"),
    ("POST", "/api/v1/llm/generate", "llm_generate"),
    ("POST", "/api/v1/llm/test", "llm_test"),
    ("POST", "/api/v1/llm/write-song", "llm_write_song"),
]

LLM_PROMPT_HTTP_SURFACE = [
    ("POST", "/api/v1/llm/plan-h3-windows", "llm_plan_h3_windows"),
    ("POST", "/api/v1/llm/enhance-prompt", "llm_enhance_prompt"),
    ("POST", "/api/v1/llm/describe-image", "llm_describe_image"),
]


def _core_router(**overrides):
    kwargs = dict(
        get_services_config=lambda: {"llm_device": "cpu"},
        effective_llm_routing=lambda _services: ("local", "test-model", ""),
        llm_provider_credentials=lambda _provider, _services, remote_url="": ("", remote_url),
        llm_default_device=lambda: "cpu",
        default_llm_repo="test-repo",
        ensure_llm_loaded=lambda: None,
        comic_writing_llm=lambda _body: None,
    )
    kwargs.update(overrides)
    return create_llm_router(**kwargs)


def _prompt_router(**overrides):
    kwargs = dict(
        get_services_config=lambda: {"nsfw_mode": False},
        effective_llm_routing=lambda _services: ("local", "test-model", ""),
        public_llm_providers=frozenset({"openai", "anthropic", "minimax", "grok", "deepseek"}),
        ensure_llm_loaded=lambda: None,
        get_model_def=lambda _model_type: {"architecture": "minimax_h3", "fps": 24},
        get_lora_dir=lambda _model_type: "/tmp",
        get_cached_hardware=lambda: {"gpu_vram_gb": 0.0},
        get_enhancer_enabled=lambda: 0,
        enhance_with_wangp=lambda *_args, **_kwargs: {"original": "x", "enhanced": "y"},
    )
    kwargs.update(overrides)
    return create_llm_prompt_router(**kwargs)


def _route_surface(router):
    found = []
    for route in router.routes:
        methods = sorted(
            method for method in (route.methods or set()) if method not in {"HEAD", "OPTIONS"}
        )
        for method in methods:
            found.append((method, route.path, route.endpoint.__name__))
    return found


def test_llm_router_exposes_the_extracted_http_surface():
    assert _route_surface(_core_router()) == LLM_HTTP_SURFACE


def test_llm_prompt_router_exposes_the_extracted_http_surface():
    assert _route_surface(_prompt_router()) == LLM_PROMPT_HTTP_SURFACE


def test_generate_and_write_song_require_their_payloads():
    app = FastAPI()
    app.include_router(_core_router())
    client = TestClient(app)
    assert client.post("/api/v1/llm/generate", json={}).json()["detail"] == "prompt is required"
    assert client.post("/api/v1/llm/write-song", json={}).json()["detail"] == "description is required"


def test_generate_returns_llm_text_without_loading_wgp():
    app = FastAPI()
    app.include_router(_core_router())
    client = TestClient(app)
    with patch("services.llm_service.generate", return_value="hello") as generate:
        response = client.post("/api/v1/llm/generate", json={"prompt": "Say hi"})
    assert response.status_code == 200
    assert response.json() == {"text": "hello"}
    generate.assert_called_once()


def test_generate_can_use_scoped_series_writer_without_changing_the_global_model():
    app = FastAPI()
    loaded = []
    requests = []
    def writer(body):
        requests.append(body)
        return {"model": "series-writer", "base_url": "http://writer.example/v1", "api_key": "test"}
    app.include_router(_core_router(ensure_llm_loaded=lambda: loaded.append(True), comic_writing_llm=writer))
    client = TestClient(app)
    schema = {"type": "object", "properties": {"environment": {"type": "string"}}}
    with patch("services.llm_service.generate_openai_compatible", return_value='{"environment":"Empty diner"}') as generate:
        response = client.post("/api/v1/llm/generate", json={
            "prompt": "Prepare the location", "writingProvider": "minimax", "writingModel": "series-writer",
            "system_prompt": "Remove occupants", "json_schema": schema,
        })
    assert response.status_code == 200
    assert response.json() == {"text": '{"environment":"Empty diner"}'}
    assert requests[0]["writingProvider"] == "minimax"
    assert not loaded
    assert generate.call_args.kwargs["model_id"] == "series-writer"
    assert generate.call_args.kwargs["json_schema"] == schema
    assert generate.call_args.kwargs["system_prompt"] == "Remove occupants"


def test_list_llm_models_forwards_url_query_to_the_catalog():
    app = FastAPI()
    app.include_router(_core_router())
    client = TestClient(app)
    with patch("services.llm_service.get_available_models", return_value=[
        {"id": "qwen3:32b", "label": "qwen3:32b (Ollama)", "size_hint": "ollama", "provider": "ollama"},
    ]) as catalog:
        response = client.get("/api/v1/llm/models", params={
            "provider": "ollama",
            "url": "http://192.168.1.10:11434",
        })
    assert response.status_code == 200
    assert response.json()["models"][0]["id"] == "qwen3:32b"
    catalog.assert_called_once()
    assert catalog.call_args.kwargs["provider"] == "ollama"
    assert catalog.call_args.kwargs["remote_url"] == "http://192.168.1.10:11434"


def test_plan_h3_windows_rejects_non_h3_models():
    app = FastAPI()
    app.include_router(_prompt_router(get_model_def=lambda _model_type: {"architecture": "ltx2"}))
    client = TestClient(app)
    response = client.post("/api/v1/llm/plan-h3-windows", json={
        "prompt": "Clark turns toward the truck",
        "model_type": "ltx2",
    })
    assert response.status_code == 400
    assert "MiniMax H3" in response.json()["detail"]


def test_describe_image_requires_a_path():
    app = FastAPI()
    app.include_router(_prompt_router())
    client = TestClient(app)
    response = client.post("/api/v1/llm/describe-image", json={})
    assert response.status_code == 400
    assert response.json()["detail"] == "image_path is required"
