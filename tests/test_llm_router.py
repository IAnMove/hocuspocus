"""ASGI contracts for the extracted /api/v1/llm FastAPI routers."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI, HTTPException
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


def test_generate_reports_a_provider_failure_as_502_with_a_stable_code_and_keeps_500_for_the_rest():
    from services.llm_service import LLMProviderError

    app = FastAPI()
    app.include_router(_core_router())
    client = TestClient(app)
    message = 'OpenAI-compatible request failed: {"type":"authorized_error","http_code":"401"}'
    with patch("services.llm_service.generate", side_effect=LLMProviderError(message, status=401)):
        response = client.post("/api/v1/llm/generate", json={"prompt": "Say hi"})
    assert response.status_code == 502
    assert response.json() == {"detail": message, "code": "provider_auth_failed"}
    with patch("services.llm_service.generate", side_effect=LLMProviderError("down", status=503)):
        assert client.post("/api/v1/llm/generate", json={"prompt": "Say hi"}).json()["code"] == "provider_failed"
    with patch("services.llm_service.generate", side_effect=RuntimeError("boom")):
        response = client.post("/api/v1/llm/generate", json={"prompt": "Say hi"})
    assert response.status_code == 500 and response.json() == {"detail": "boom"}


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


def test_list_llm_models_never_points_a_public_provider_at_a_client_url():
    app = FastAPI()
    app.include_router(_core_router())
    client = TestClient(app)
    with patch("services.llm_service.get_available_models", return_value=[]) as catalog:
        response = client.get("/api/v1/llm/models", params={"provider": "openai", "url": "http://attacker.example/"})
    assert response.status_code == 200
    assert "attacker" not in str(catalog.call_args.kwargs["remote_url"]), "the stored key would have travelled there"


def test_llm_load_runs_the_local_gate_only_for_the_local_provider():
    gated = []

    def gate():
        gated.append("local")
        raise HTTPException(status_code=409, detail={"code": "feature_unavailable"})

    app = FastAPI()
    app.include_router(_core_router(require_local_llm=gate))
    client = TestClient(app)
    with patch("services.llm_service.load_model") as load, patch("services.llm_service.get_status", return_value={}):
        blocked = client.post("/api/v1/llm/load", json={"provider": "local"})
        assert (blocked.status_code, blocked.json()["detail"]["code"]) == (409, "feature_unavailable")
        load.assert_not_called()
        remote = client.post("/api/v1/llm/load", json={"provider": "openai", "model_id": "gpt-test"})
        assert remote.status_code == 200, remote.text
        load.assert_called_once()
        # No provider in the body: the routing decides, and it is local here.
        assert client.post("/api/v1/llm/load", json={}).status_code == 409
    assert gated == ["local", "local"]


def test_llm_load_without_a_gate_loads_the_local_provider():
    app = FastAPI()
    app.include_router(_core_router())
    client = TestClient(app)
    with patch("services.llm_service.load_model") as load, patch("services.llm_service.get_status", return_value={}):
        response = client.post("/api/v1/llm/load", json={"provider": "local"})
    assert response.status_code == 200, response.text
    load.assert_called_once()


def test_plan_h3_windows_runs_its_gate_before_reading_the_body():
    def gate():
        raise HTTPException(status_code=409, detail={"code": "feature_unavailable"})

    app = FastAPI()
    app.include_router(_prompt_router(plan_h3_gate=gate))
    client = TestClient(app)
    for request in ({"json": {"prompt": "Clark turns toward the truck"}}, {"content": b"not json"}, {}):
        response = client.post("/api/v1/llm/plan-h3-windows", **request)
        assert (response.status_code, response.json()["detail"]["code"]) == (409, "feature_unavailable")
