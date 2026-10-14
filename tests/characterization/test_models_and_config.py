"""Model catalog over a fake WanGP catalog, and the configuration reads the Settings screen makes."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.support.fake_wgp import catalog_attributes
from tests.support.full_server import APP_DIR


@pytest.fixture
def catalog(server, monkeypatch):
    """Two fake WanGP models; the 3D, rig and MiniMax weights are never on disk."""
    from services import minimax_h3_service, model3d_service, rig_service

    for name, value in catalog_attributes().items():
        monkeypatch.setattr(server.wgp, name, value, raising=False)
    monkeypatch.setattr(model3d_service, "is_model_downloaded", lambda _model_id: False)
    monkeypatch.setattr(minimax_h3_service, "is_model_downloaded", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(rig_service, "is_unirig_downloaded", lambda: False)
    return server


def test_model_catalog(catalog, golden) -> None:
    catalog.check(golden, "models", "GET", "/api/v1/models")
    catalog.check(golden, "models summary", "GET", "/api/v1/models", params={"detail": "false"})


def test_model_settings_defaults(server, golden) -> None:
    server.check(golden, "model visibility", "GET", "/api/v1/model-visibility")
    server.check(golden, "model selections", "GET", "/api/v1/model-selections")
    server.check(golden, "production profile", "GET", "/api/v1/production-profile")


def _keep_config_keys(monkeypatch, config, *keys: str) -> None:
    """Put each key back after a route that writes ``wgp.server_config``."""
    for key in keys:
        monkeypatch.setitem(config, key, config.get(key))


def test_model_visibility_and_selections_round_trip(server, golden, monkeypatch) -> None:
    """Visibility and per-mode selections, including the ids and modes the server refuses.

    Both writes go through the kernel config file. The server fixture points that
    file at this test's temp folder, and the keys are put back afterwards.
    """
    config = server.wgp.server_config
    _keep_config_keys(
        monkeypatch,
        config,
        "maestro_model_visibility",
        "maestro_model_selections",
    )
    server.check(
        golden,
        "visibility save",
        "PUT",
        "/api/v1/model-visibility",
        json={
            "enabled_models": [" fake_t2v ", "fake_t2v", "fake_i2v"],
            "initialized_mature_models": [" fake_i2v "],
            "defaults_version": 3,
        },
    )
    server.check(
        golden,
        "visibility not an object",
        "PUT",
        "/api/v1/model-visibility",
        json=["fake_t2v"],
    )
    server.check(
        golden,
        "visibility ids not a list",
        "PUT",
        "/api/v1/model-visibility",
        json={"enabled_models": "fake_t2v"},
    )
    server.check(
        golden,
        "visibility id not a string",
        "PUT",
        "/api/v1/model-visibility",
        json={"enabled_models": [123]},
    )
    server.check(
        golden,
        "selections save",
        "PUT",
        "/api/v1/model-selections",
        json={"selected_models": {"video": " fake_t2v ", "image": "", "audio": "fake_i2v"}},
    )
    server.check(
        golden,
        "selections not an object",
        "PUT",
        "/api/v1/model-selections",
        json=["video"],
    )
    server.check(
        golden,
        "selections unknown mode",
        "PUT",
        "/api/v1/model-selections",
        json={"selected_models": {"nope": "fake_t2v"}},
    )
    server.check(
        golden,
        "selections value not a string",
        "PUT",
        "/api/v1/model-selections",
        json={"selected_models": {"video": 123}},
    )


def test_production_profile_rejects_a_bad_body(server, golden) -> None:
    """A profile that is not the object the normaliser expects is refused before it is saved."""
    server.check(
        golden,
        "production profile not an object",
        "PUT",
        "/api/v1/production-profile",
        json={"profile": "local"},
    )
    server.check(
        golden,
        "production profile missing sections",
        "PUT",
        "/api/v1/production-profile",
        json={"profile": {"text": {"provider": "minimax", "model": "MiniMax-M3"}}},
    )


def test_model_options_defaults_resolutions_and_download_errors(catalog, golden, monkeypatch) -> None:
    """Cheap catalog reads, and the delete/download answers that need no weights.

    A real download, a delete of files that are on disk, and options for an
    installed WanGP model need the GPU install. Those stay out of this golden.
    """
    base_def = catalog.wgp.get_model_def

    def model_def(model_type: str):
        if model_type == "fake_image":
            return {
                "name": "Fake Image",
                "architecture": "fake_image",
                "description": "A stills model that exists only in tests.",
                "image_outputs": True,
                "fps": 0,
                "image_prompt_types_allowed": "",
                "guide_preprocessing": {"selection": ["", "PV"], "default": ""},
                "sample_solvers": [("UniPC", "unipc"), ("Euler", "euler")],
                "inpaint_support": True,
                "native_rgba": True,
            }
        return base_def(model_type)

    monkeypatch.setattr(catalog.wgp, "get_model_def", model_def, raising=False)

    def resolution_choices(current_resolution_choice, model_resolutions=None):
        # The real helper returns (choices, current). The route unpacks that pair.
        return ([("480p", "832x480"), ("720p", "1280x720")], current_resolution_choice)

    monkeypatch.setattr(catalog.wgp, "get_resolution_choices", resolution_choices, raising=False)
    monkeypatch.setattr(catalog.wgp, "load_model_definitions", lambda: None, raising=False)

    catalog.check(golden, "options text to video", "GET", "/api/v1/model-options/fake_t2v")
    catalog.check(golden, "options image to video", "GET", "/api/v1/model-options/fake_i2v")
    catalog.check(golden, "options image", "GET", "/api/v1/model-options/fake_image")
    catalog.check(golden, "options unknown", "GET", "/api/v1/model-options/not_a_model")
    catalog.check(golden, "defaults text to video", "GET", "/api/v1/defaults/fake_t2v")
    catalog.check(golden, "defaults unknown", "GET", "/api/v1/defaults/not_a_model")
    catalog.check(golden, "resolutions", "GET", "/api/v1/resolutions")
    catalog.check(golden, "downloads status", "GET", "/api/v1/models/downloads/status")
    catalog.check(golden, "active downloads", "GET", "/api/v1/downloads/active")
    catalog.check(golden, "reload definitions", "POST", "/api/v1/models/reload")
    catalog.check(golden, "debug text to video", "GET", "/api/v1/models/fake_t2v/debug")
    catalog.check(golden, "debug unknown", "GET", "/api/v1/models/not_a_model/debug")
    catalog.check(golden, "delete unknown", "DELETE", "/api/v1/models/not_a_model")
    catalog.check(golden, "delete nothing on disk", "DELETE", "/api/v1/models/fake_t2v")
    catalog.check(golden, "download unknown", "POST", "/api/v1/models/not_a_model/download")

    import sys

    launch = sys.modules["_launch_runtime"]
    launch._jobs["golden-delete"] = {
        "id": "golden-delete",
        "status": "running",
        "params": {"model_type": "fake_i2v"},
    }
    try:
        catalog.check(golden, "delete while generating", "DELETE", "/api/v1/models/fake_i2v")
    finally:
        launch._jobs.pop("golden-delete", None)


def test_model_preferences_rewrite_the_whole_config_file(server, monkeypatch) -> None:
    """Visibility, selections and the profile share one writer: the live config, four-space JSON, no temp file left.

    The goldens record the answers; this records what lands on disk and what a refusal leaves alone.
    """
    import json

    config = server.wgp.server_config
    _keep_config_keys(
        monkeypatch,
        config,
        "maestro_model_visibility",
        "maestro_model_selections",
        "maestro_production_profile",
    )
    monkeypatch.setitem(config, "services", dict(config.get("services") or {}))
    path = Path(server.wgp.server_config_filename)
    assert not path.exists()

    def saved() -> tuple[str, dict]:
        text = path.read_text(encoding="utf-8")
        return text, json.loads(text)

    def leftovers() -> list[str]:
        return sorted(item.name for item in path.parent.iterdir() if item.name.endswith(".tmp"))

    response = server.client.put(
        "/api/v1/model-visibility",
        json={"enabled_models": [" fake_t2v ", "fake_i2v"], "defaults_version": 2},
    )
    assert response.status_code == 200
    text, document = saved()
    assert document["maestro_model_visibility"] == {
        "enabled_models": ["fake_t2v", "fake_i2v"],
        "initialized_mature_models": [],
        "defaults_version": 2,
    }
    assert text == json.dumps(document, indent=4)
    assert leftovers() == []

    chosen = {"image": "fake_i2v", "video": "fake_t2v", "audio": "fake_i2v"}
    response = server.client.put("/api/v1/model-selections", json={"selected_models": chosen})
    assert response.status_code == 200
    text, document = saved()
    assert document["maestro_model_selections"] == chosen
    assert document["maestro_model_visibility"]["enabled_models"] == ["fake_t2v", "fake_i2v"]
    assert text == json.dumps(document, indent=4)

    before = path.read_text(encoding="utf-8")
    too_long = server.client.put("/api/v1/model-visibility", json={"enabled_models": ["x" * 201]})
    assert (too_long.status_code, too_long.json()["detail"]) == (400, "A model identifier is too long.")
    crowded = server.client.put(
        "/api/v1/model-selections",
        json={"selected_models": {mode: "x" for mode in ("image", "video", "audio", "model3d", "avatar", "sixth")}},
    )
    assert (crowded.status_code, crowded.json()["detail"]) == (400, "Too many model selection entries.")
    assert path.read_text(encoding="utf-8") == before

    profile = server.client.get("/api/v1/production-profile").json()["profile"]
    profile["text"] = {"provider": "ollama", "model": "llama"}
    response = server.client.put("/api/v1/production-profile", json={"profile": profile})
    assert response.status_code == 200
    text, document = saved()
    saved_text = document["maestro_production_profile"]["text"]
    assert (saved_text["provider"], saved_text["model"]) == ("ollama", "llama")
    # Saving the profile mirrors its text section into the legacy services keys and drops the image and video overrides.
    assert document["services"]["llm_provider"] == "ollama"
    assert document["services"]["llm_model_id"] == "llama"
    assert document["services"]["llm_remote_url"] == "http://127.0.0.1:11434"
    assert document["maestro_model_selections"] == {"audio": "fake_i2v"}
    assert text == json.dumps(document, indent=4)
    assert leftovers() == []


def test_a_model_download_runs_in_the_background_and_shows_in_the_status(catalog, monkeypatch) -> None:
    """The pre-download worker writes the one download map the status route reads, on success and on failure."""
    import sys
    import time
    from types import SimpleNamespace

    wgp = catalog.wgp
    launch = sys.modules["_launch_runtime"]
    on_disk: set[str] = set()
    fetched: list[tuple] = []

    def locate_file(file_name, create_path_if_none=False, error_if_none=True, extra_paths=None):
        name = os.path.basename(str(file_name))
        if name in on_disk:
            return str(catalog.root / name)
        if error_if_none:
            raise Exception(f"{name} is not on disk")
        return None

    def get_model_filename(model_type=None, quantization=None, dtype_policy=None, submodel_no=1, URLs=None, module_type=None):
        return "" if URLs is not None else f"ckpts/{model_type}.safetensors"

    def download_models(filename, model_type, source_type, submodel_no, force_path=None):
        fetched.append((os.path.basename(filename), model_type, source_type, submodel_no))
        on_disk.add(os.path.basename(filename))

    for name, value in {
        "fl": SimpleNamespace(locate_file=locate_file),
        "transformer_quantization": "int8",
        "transformer_dtype_policy": "auto",
        "text_encoder_quantization": "int8",
        "get_transformer_dtype": lambda model_type, policy: "bf16",
        "get_model_filename": get_model_filename,
        "download_models": download_models,
        "get_local_model_filename": lambda name, extra_paths=None: locate_file(name, error_if_none=False),
    }.items():
        monkeypatch.setattr(wgp, name, value, raising=False)

    def wait_for(model_type: str) -> dict:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            entry = catalog.client.get("/api/v1/models/downloads/status").json()["downloads"].get(model_type)
            if entry and entry["status"] != "downloading":
                return entry
            time.sleep(0.02)
        raise AssertionError(f"{model_type} never left the downloading state")

    try:
        started = catalog.client.post("/api/v1/models/fake_t2v/download")
        assert (started.status_code, started.json()) == (200, {"status": "downloading", "model_type": "fake_t2v"})
        assert wait_for("fake_t2v") == {"status": "completed", "error": None}
        assert fetched == [("fake_t2v.safetensors", "fake_t2v", 0, 1)]
        assert "fake_t2v" in launch._model_downloads
        listed = {item["model_type"]: item["is_downloaded"] for item in catalog.client.get("/api/v1/models").json()["models"]}
        assert listed["fake_t2v"] is True and listed["fake_i2v"] is False

        def refuse(filename, model_type, source_type, submodel_no, force_path=None):
            raise RuntimeError("disk full")

        monkeypatch.setattr(wgp, "download_models", refuse, raising=False)
        catalog.client.post("/api/v1/models/fake_i2v/download")
        assert wait_for("fake_i2v") == {"status": "failed", "error": "disk full"}
        assert catalog.client.get("/api/v1/models/downloads/status").json()["downloads"] == {
            "fake_t2v": {"status": "completed", "error": None},
            "fake_i2v": {"status": "failed", "error": "disk full"},
        }
    finally:
        with launch._model_downloads_lock:
            launch._model_downloads.clear()


def test_production_profile_save(server, golden, monkeypatch) -> None:
    """The saved profile the Settings screen writes. Recorded before the normalizer moves."""
    config = server.wgp.server_config
    monkeypatch.setitem(config, "maestro_production_profile", config.get("maestro_production_profile"))
    services = config.get("services")
    if isinstance(services, dict):
        monkeypatch.setitem(config, "services", dict(services))
    selections = config.get("maestro_model_selections")
    if isinstance(selections, dict):
        monkeypatch.setitem(config, "maestro_model_selections", dict(selections))
    server.check(
        golden,
        "production profile save",
        "PUT",
        "/api/v1/production-profile",
        json={"profile": {
            "text": {"provider": "minimax", "model": "MiniMax-M3", "base_url": "https://api.minimax.io"},
            "image": {"provider": "minimax", "model": "image-01"},
            "music": {"provider": "local", "model": "ace_step_v1_5_xl_sft_lm_4b"},
            "model3d": {"provider": "local", "model": "hunyuan3d-2mini-turbo"},
            "video": {
                "provider": "local",
                "model": "minimax_h3_legacy",
                "settings": {
                    "profile": "quality",
                    "steps": 20,
                    "flowShift": 12,
                    "audioShift": 3,
                    "turbo": False,
                    "cache": False,
                    "loras": [],
                    "resolution": "540p",
                    "aspectRatio": "16:9",
                },
            },
        }},
    )


def test_the_server_keeps_temp_files_and_libraries_in_its_state_folder(full_server) -> None:
    """The import sweeps the temp folder; Numba and the libraries default to the live install's folders."""
    import tempfile

    from services.style_library import resolve_style_library_root
    from services.template_library import resolve_template_library_root

    state = full_server.state_root.resolve()
    assert Path(tempfile.gettempdir()).resolve().is_relative_to(state)
    assert Path(os.environ["TMPDIR"]).resolve().is_relative_to(state)
    assert Path(os.environ["NUMBA_CACHE_DIR"]).resolve().is_relative_to(state)
    numba = pytest.importorskip("numba")  # It reads NUMBA_CACHE_DIR once, when first imported.
    assert Path(numba.config.CACHE_DIR).resolve().is_relative_to(state)
    assert resolve_style_library_root(APP_DIR).is_relative_to(state)
    assert resolve_template_library_root(APP_DIR).is_relative_to(state)


def test_settings_reads(server, golden) -> None:
    server.check(golden, "services config", "GET", "/api/v1/services-config")
    server.check(golden, "presets", "GET", "/api/v1/presets")
    server.check(
        golden,
        "services config empty update",
        "PUT",
        "/api/v1/services-config",
        json={},
    )
    server.check(
        golden,
        "system config empty update",
        "PUT",
        "/api/v1/system-config",
        json={},
    )
    server.check(golden, "mcp settings", "GET", "/api/v1/settings/mcp")
    server.check(golden, "llm status", "GET", "/api/v1/llm/status")
    server.check(golden, "lan auth status", "GET", "/api/v1/auth/lan/status")


def test_system_reads_and_release(server, golden) -> None:
    """Cheap system routes before they leave the launch module.

    Hardware, free disk and the live gauges depend on the machine, so those
    fields are masked or asserted only by shape. Applying a detected profile
    writes the real recommendation and is left for a GPU check.
    """
    import sys

    server.check(
        golden,
        "system detect",
        "GET",
        "/api/v1/system-detect",
        mask=("hardware", "recommended"),
    )
    server.check(
        golden,
        "system stats",
        "GET",
        "/api/v1/system-stats",
        mask=("cpu", "ram", "gpu", "runtime"),
    )
    server.check(golden, "debug user action", "POST", "/api/v1/debug/user-action", json={})
    server.check(golden, "release model idle", "POST", "/api/v1/system/release-model")

    launch = sys.modules["_launch_runtime"]
    launch._jobs["golden-running"] = {"id": "golden-running", "status": "running"}
    try:
        server.check(golden, "release model busy", "POST", "/api/v1/system/release-model")
    finally:
        launch._jobs.pop("golden-running", None)

    preflight = server.client.get("/api/v1/system/preflight")
    assert preflight.status_code == 200
    body = preflight.json()
    assert isinstance(body.get("ok"), bool)
    assert isinstance(body.get("checks"), list)

    capabilities = server.client.get("/api/v1/runtime-capabilities")
    assert capabilities.status_code == 200
    detected = capabilities.json()
    assert isinstance(detected.get("engines"), dict)
    assert isinstance(detected.get("platform"), str)

    wangp = server.client.get("/api/v1/wangp/capabilities")
    assert wangp.status_code == 200
    processors = wangp.json()
    assert processors["revision"] == "362c3467a70e1136ceb52eec95907205a8f88543"
    assert {"rife2", "rife4"} <= {item["value"] for item in processors["processors"]}


def test_tools_reject_invalid_input(server, golden) -> None:
    """Upscale and revoice refuse a bad request before any model work.

    A real upscale or revoice needs a clip and a GPU, so only the validation
    answers are recorded here.
    """
    server.check(
        golden,
        "upscale unsupported method",
        "POST",
        "/api/v1/tools/upscale",
        json={"method": "not-a-method"},
    )
    server.check(
        golden,
        "upscale missing source",
        "POST",
        "/api/v1/tools/upscale",
        json={},
    )
    server.check(
        golden,
        "revoice missing source",
        "POST",
        "/api/v1/tools/revoice",
        json={},
    )


def test_director_and_describe_refuse_an_empty_request(server, golden) -> None:
    """Director music and character description refuse an empty body before any model work.

    A real song or a description needs a loaded model and, for music, a GPU.
    These are the answers the full server gives first.
    """
    server.check(
        golden,
        "describe refs missing images",
        "POST",
        "/api/v1/characters/describe-refs",
        json={},
    )
    server.check(
        golden,
        "generate music empty",
        "POST",
        "/api/v1/director/generate-music",
        json={},
    )


def test_mcp_transport_while_access_is_disabled(server, golden) -> None:
    """The full server's MCP routes before this step's router edit. Access is off, so POST never reaches a tool."""
    message = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    server.check(golden, "mcp post disabled", "POST", "/api/v1/mcp", json=message)
    server.check(golden, "mcp alias post disabled", "POST", "/api/v1/wangp/mcp", json=message)
    server.check(golden, "mcp get", "GET", "/api/v1/mcp")
    server.check(golden, "mcp alias get", "GET", "/api/v1/wangp/mcp")
