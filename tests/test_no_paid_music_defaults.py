"""Music never reaches the paid MiniMax API by default or for an agent.

Every fill picks the local model Studio and production.* use. A paid MiniMax id
runs only when a person picks it in Story Lab and confirms the cost; agents,
MCP and production specs get a clear refusal and no provider call.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services import core_production, media_options, minimax_music_service
from services.music_model_contract import (
    DEFAULT_MUSIC_MODEL,
    MusicModelError,
    freeze_music_spec,
    require_confirmed_paid_music,
)
from services.music_production import ProductionError, validate_spec
from services.music_submission import classify_music_route
from services.production_song import _music_params
from services.studio_music_spec import StudioMusicSpecError, freeze_studio_music_spec

APP = Path(__file__).resolve().parents[1] / "app"
LOCAL = "ace_step_v1_5_xl_sft_lm_4b"
PAID_REFUSAL = "Paid MiniMax music is disabled (music-3.0); use a local model: ace_step_v1_5_xl_sft_lm_4b, minimax_music3"
SONG = {"prompt": "cinematic dream pop", "lyrics": "[Verse]\nAcross the night", "count": 1}


# -- every fill is the local model -------------------------------------------------------------

def test_the_default_is_the_local_model_studio_and_production_use():
    assert DEFAULT_MUSIC_MODEL == LOCAL
    assert _music_params({"lyrics": "la", "caption": "pop", "duration": 30, "bpm": 100}, 1, "es")["model_type"] == LOCAL


def test_a_request_without_a_model_freezes_and_routes_local():
    spec = freeze_music_spec(SONG)
    assert (spec["model"], spec["route"]) == (LOCAL, "local")
    assert classify_music_route(None) == classify_music_route("") == "local"


def test_the_core_profile_puts_local_music_first():
    assert core_production.CORE_DEFAULT_PROFILE["music"] == {"provider": "local", "model": LOCAL}
    normalized = core_production.normalize_production_profile(core_production.CORE_DEFAULT_PROFILE)
    assert normalized["music"] == {"provider": "local", "model": LOCAL}


def test_the_minimax_client_never_picks_a_model_by_itself(tmp_path):
    calls = []
    session = SimpleNamespace(post=lambda *args, **kwargs: calls.append(args))
    with pytest.raises(minimax_music_service.MiniMaxMusicError) as error:
        minimax_music_service.generate_candidates(
            api_key="secret", prompt="pop", lyrics="words", count=1, output_dir=str(tmp_path), session=session,
        )
    assert error.value.status_code == 400 and "explicitly" in str(error.value)
    assert calls == []


def test_the_runtime_minimax_worker_fills_no_model(tmp_path, monkeypatch):
    """A queued job without a model fails at the client; nothing is posted to MiniMax."""
    from tests.test_minimax_music_jobs import _base_namespace, _job, _load

    namespace = _load(
        "_minimax_music_job_update", "_minimax_music_child_update", "_minimax_music_claim_candidate",
        "_finish_unstarted_music_children", "_run_minimax_music_job", namespace=_base_namespace(tmp_path),
    )
    job_id = "minimax-music-0123456789ab"
    job = _job(job_id, 1)
    del job["request"]["model"]
    namespace["_minimax_music_jobs"][job_id] = job
    posted = []
    # Only the client's own reference: the global requests module stays untouched for other tests.
    monkeypatch.setattr(minimax_music_service, "requests", SimpleNamespace(Session=lambda: SimpleNamespace(
        post=lambda *args, **kwargs: posted.append(args), close=lambda: None)))
    namespace["_run_minimax_music_job"](job_id)
    failed = namespace["_minimax_music_jobs"][job_id]
    assert (failed["status"], failed["statusCode"]) == ("failed", 400) and "explicitly" in failed["error"]
    assert posted == []


def test_the_core_endpoint_never_turns_a_missing_model_into_a_paid_one(tmp_path, monkeypatch):
    """With no model the core runtime asks for the local default, which it cannot run (409)."""
    from routers import system_capabilities
    from routers.core_remote import core_music_generation_gate

    def unavailable(capability):
        raise HTTPException(status_code=409, detail={"code": "feature_unavailable", "capability": capability})

    started = []
    monkeypatch.setattr(system_capabilities, "require_capability_http", unavailable)
    with _story_music_client(
        tmp_path, monkeypatch, started, music_generation_gate=core_music_generation_gate,
    ) as client:
        refused = client.post("/api/v1/stories/music-candidates/jobs", json={**SONG, "workspace": "default"})
    assert refused.status_code == 409 and refused.json()["detail"]["capability"] == "local_audio_ai"
    assert started == []


# -- the paid Story endpoints need the person's confirmation ------------------------------------

def test_the_paid_contract_needs_an_explicit_confirmed_choice():
    with pytest.raises(MusicModelError) as missing:
        require_confirmed_paid_music(SONG)
    assert missing.value.status_code == 400 and LOCAL in str(missing.value)
    with pytest.raises(MusicModelError) as unconfirmed:
        require_confirmed_paid_music({**SONG, "model": "music-3.0"})
    assert unconfirmed.value.status_code == 403 and str(unconfirmed.value).startswith(PAID_REFUSAL)
    with pytest.raises(MusicModelError):
        require_confirmed_paid_music({**SONG, "model": "music-2.6", "paid_music_confirmed": "yes"})
    assert require_confirmed_paid_music({**SONG, "model": "music-2.6", "paid_music_confirmed": True}) == "music-2.6"


@contextmanager
def _story_music_client(tmp_path, monkeypatch, started, music_generation_gate=None):
    from routers import story_music

    saved = {
        name: getattr(story_music, name, None)
        for name in (
            "_get_active_workspace", "_workspace_dir", "_story_cover_reference_path",
            "_load_minimax_music_job", "_persist_minimax_music_job", "_publish_minimax_music_job",
            "_public_minimax_music_job", "_run_minimax_music_job", "_minimax_music_jobs",
            "_minimax_music_jobs_lock", "_MINIMAX_MUSIC_TERMINAL", "_finish_unstarted_music_children",
            "_minimax_music_job_update", "wgp", "_music_generation_gate", "_music_before_reserve",
            "_music_resolve_workspace",
        )
    }
    monkeypatch.setattr(story_music.execution_mode, "validate_remote_provider", lambda *_args: None)
    app = FastAPI()
    app.include_router(story_music.create_story_music_router(
        SimpleNamespace(
            workspace_dir=lambda *_args: str(tmp_path),
            load_minimax_music_job=lambda _job_id: None,
            persist_minimax_music_job=lambda _job: None,
            publish_minimax_music_job=lambda _job: None,
            public_minimax_music_job=lambda job: {key: value for key, value in job.items() if key != "request"},
            run_minimax_music_job=started.append,
            minimax_music_jobs={},
            minimax_music_jobs_lock=threading.RLock(),
            minimax_music_terminal={"completed", "failed", "cancelled"},
            finish_unstarted_music_children=lambda *_args, **_kwargs: None,
            minimax_music_job_update=lambda *_args, **_kwargs: None,
        ),
        get_active_workspace=lambda: "default",
        story_cover_reference_path=lambda *_args: None,
        wgp_module=SimpleNamespace(server_config={"services": {}}),
        music_generation_gate=music_generation_gate,
    ))
    try:
        yield TestClient(app)
    finally:
        for name, value in saved.items():
            setattr(story_music, name, value)


def test_the_story_job_endpoint_refuses_unconfirmed_or_missing_models(tmp_path, monkeypatch):
    started = []
    body = {**SONG, "workspace": "default"}
    with _story_music_client(tmp_path, monkeypatch, started) as client:
        missing = client.post("/api/v1/stories/music-candidates/jobs", json=body)
        unconfirmed = client.post("/api/v1/stories/music-candidates/jobs", json={**body, "model": "music-3.0"})
        assert missing.status_code == 400 and LOCAL in missing.json()["detail"]
        assert unconfirmed.status_code == 403 and unconfirmed.json()["detail"].startswith(PAID_REFUSAL)
        assert started == [] and not (tmp_path / "music-submissions").exists()
        accepted = client.post("/api/v1/stories/music-candidates/jobs", json={
            **body, "model": "music-3.0", "paid_music_confirmed": True,
        })
        assert accepted.status_code == 202 and accepted.json()["model"] == "music-3.0"
        for _ in range(50):
            if started:
                break
            threading.Event().wait(0.02)
        assert started == [accepted.json()["jobId"]]


def test_the_legacy_sync_endpoint_refuses_before_calling_minimax(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(minimax_music_service, "generate_candidates", lambda **kwargs: calls.append(kwargs) or [])
    with _story_music_client(tmp_path, monkeypatch, []) as client:
        refused = client.post("/api/v1/stories/music-candidates", json={**SONG, "model": "music-2.6"})
    assert refused.status_code == 403 and "Paid MiniMax music is disabled (music-2.6)" in refused.json()["detail"]
    assert calls == []


def test_the_core_endpoint_refuses_an_unconfirmed_paid_model(tmp_path, monkeypatch):
    from routers.core_remote import core_music_generation_gate

    started = []
    with _story_music_client(
        tmp_path, monkeypatch, started, music_generation_gate=core_music_generation_gate,
    ) as client:
        refused = client.post(
            "/api/v1/stories/music-candidates/jobs",
            json={**SONG, "model": "music-3.0", "workspace": "default"},
        )
        assert refused.status_code == 403 and refused.json()["detail"].startswith(PAID_REFUSAL)
        confirmed = client.post(
            "/api/v1/stories/music-candidates/jobs",
            json={**SONG, "model": "music-3.0", "paid_music_confirmed": True, "workspace": "default"},
        )
        assert confirmed.status_code == 202 and confirmed.json()["model"] == "music-3.0"
        for _ in range(50):
            if started:
                break
            threading.Event().wait(0.02)
    assert started == [confirmed.json()["jobId"]]


# -- agents, MCP and production.* get a clear refusal -------------------------------------------

def test_mcp_generate_refuses_a_paid_music_model_without_calling_the_handler(tmp_path):
    from routers.wangp_mcp import create_wangp_mcp_router

    calls = []
    app = FastAPI()
    app.include_router(create_wangp_mcp_router(
        handlers={"generate": lambda request: calls.append(request) or {"job_id": "x"}},
        journal_path=tmp_path / "requests.db", token_getter=lambda: "test-token"))
    with TestClient(app) as client:
        answer = client.post("/api/v1/mcp", headers={"Authorization": "Bearer test-token"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "generate", "arguments": {
                "request_id": "paid-1", "params": {"generation_mode": "audio", "model_type": "music-3.0", "prompt": "x"}}}}).json()
    assert answer["result"]["isError"] is True
    assert answer["result"]["content"][0]["text"].startswith(PAID_REFUSAL)
    assert calls == []


def test_the_studio_music_command_names_the_local_models():
    command = {"version": 2, "operation": "generation.music", "intent_id": "paid-music", "input": {
        "workspace": "music-test", "params": {
            "model_type": "music-3.0", "prompt": "[Verse]\nA line", "alt_prompt": "warm acoustic pop",
            "generation_mode": "audio", "image_mode": 0, "video_length": 0, "_audio_sub_mode": "music"}}}
    with pytest.raises(StudioMusicSpecError) as refused:
        freeze_studio_music_spec(command)
    assert "Paid MiniMax music is disabled (music-3.0)" in str(refused.value)


def test_a_production_spec_with_a_paid_song_model_is_refused():
    spec = {"title": "t", "song": {"lyrics": "a\nb", "caption": "pop", "duration": 30, "bpm": 120, "model": "music-3.0"},
            "style": {}, "shots": [{"key": "intro", "kind": "still", "t0": 0, "still": "k"}]}
    with pytest.raises(ProductionError) as refused:
        validate_spec(spec)
    assert refused.value.code == "invalid_spec" and str(refused.value).startswith(PAID_REFUSAL)
    spec["song"]["model"] = "minimax_music3"
    assert validate_spec(spec)["song"]["model"] == "minimax_music3"


def test_the_production_spec_check_needs_no_http_client():
    """production.* and media.options read the paid ids without the MiniMax client (the E2E server has no requests)."""
    script = (
        "import sys\n"
        "sys.modules['requests'] = None\n"
        "import services.media_options\n"
        "from services.music_production import ProductionError, validate_spec\n"
        "song = {'lyrics': 'a', 'caption': 'pop', 'duration': 30, 'bpm': 120, 'model': 'music-3.0'}\n"
        "spec = {'title': 't', 'song': song, 'style': {}, 'shots': [{'key': 'i', 'kind': 'still', 't0': 0, 'still': 'k'}]}\n"
        "try:\n"
        "    validate_spec(spec)\n"
        "except ProductionError as error:\n"
        "    print(error)\n"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=APP, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(PAID_REFUSAL)


def test_media_options_lists_local_music_and_no_paid_music():
    models = [
        {"model_type": LOCAL, "name": "ACE-Step 1.5 XL", "is_downloaded": True, "resource_requirements": {"vram_gb": 12}},
        {"model_type": "minimax_music3", "name": "MiniMax Music 3", "is_downloaded": False},
        {"model_type": "yue2", "name": "YuE 2", "is_downloaded": True},
        {"model_type": "heartmula_oss_3b", "name": "HeartMuLa", "is_downloaded": True},
    ]
    result = media_options.build(models, {"minimax_music_api_key_set": True}, {"configured": False, "profile": {}})
    assert result["local"]["music"] == [
        {"id": LOCAL, "name": "ACE-Step 1.5 XL", "vram_gb": 12, "default": True},
        {"id": "yue2", "name": "YuE 2"},
    ]
    assert "music" not in result["cloud"]
    assert "music-3.0" not in json.dumps(result) and "Music is local only" in result["guidance"]
    handler = media_options.command_handlers(lambda: (models, {}, {"configured": False, "profile": {}}))["media.options"]
    assert asyncio.run(handler({"version": 1}))["result"]["local"]["music"][0]["id"] == LOCAL
