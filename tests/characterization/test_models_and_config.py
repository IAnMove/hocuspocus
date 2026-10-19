"""Model catalog over a fake WanGP catalog, and the configuration reads the Settings screen makes."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

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


def _write_lora_library(root: Path) -> Path:
    """One weight file, so the unsorted installed walk cannot change order."""
    wan = root / "wan"
    wan.mkdir(parents=True)
    (root / "flux").mkdir()
    hidden = root / ".hidden"
    hidden.mkdir()
    (hidden / "note.txt").write_text("skip\n", encoding="utf-8")
    (root / "readme.txt").write_text("ignore\n", encoding="utf-8")
    (wan / "style.safetensors").write_bytes(b"lora-weight")
    (wan / "style.civitai.json").write_text(
        json.dumps(
            {
                "modelId": 12345,
                "versionId": 99,
                "name": "Style LoRA",
                "baseModel": "Wan Video",
                "trainedWords": ["styleword"],
                "nsfw": False,
                "downloadedAt": "2020-01-02T03:04:05Z",
                "publishedAt": "2020-01-01T00:00:00Z",
                "tags": ["cinematic"],
                "description": "A calm style.",
                "images": [],
            }
        ),
        encoding="utf-8",
    )
    (wan / "style.guide.md").write_text(
        "Use the trigger word styleword for a calm look.\n",
        encoding="utf-8",
    )
    return wan


@pytest.fixture
def lora_library(catalog, monkeypatch, tmp_path):
    """A temp LoRA tree on an absolute root, with the WanGP lookups the list routes need."""
    root = tmp_path / "lora-root"
    wan = _write_lora_library(root)
    config = catalog.wgp.server_config
    monkeypatch.setitem(config, "loras_root", str(root))
    monkeypatch.setitem(config, "checkpoints_paths", [str(tmp_path / "primary-ckpts")])

    def get_lora_dir(model_type):
        if model_type == "not_a_model":
            raise RuntimeError("unknown model type")
        return str(wan)

    monkeypatch.setattr(catalog.wgp, "get_lora_dir", get_lora_dir, raising=False)
    monkeypatch.setattr(catalog.wgp, "get_lora_search_dirs", lambda _model_type: [str(wan)], raising=False)
    monkeypatch.setattr(
        catalog.wgp,
        "resolve_lora_path",
        lambda _model_type, filename: str(wan / filename),
        raising=False,
    )
    catalog.lora_root = root
    catalog.lora_wan = wan
    return catalog


def test_lora_library_reads(lora_library, golden) -> None:
    """Directories, the installed list, and one model's list and details, on a temp tree."""
    lora_library.check(golden, "lora directories", "GET", "/api/v1/loras/directories")
    lora_library.check(golden, "loras installed", "GET", "/api/v1/loras/installed")
    lora_library.check(golden, "loras for model", "GET", "/api/v1/loras/fake_t2v")
    lora_library.check(golden, "lora details for model", "GET", "/api/v1/loras/fake_t2v/details")
    lora_library.check(golden, "loras for legacy h3", "GET", "/api/v1/loras/minimax_h3_legacy")
    lora_library.check(golden, "lora details for legacy h3", "GET", "/api/v1/loras/minimax_h3_legacy/details")
    lora_library.check(golden, "loras for 3d model", "GET", "/api/v1/loras/hunyuan3d-2mv")
    lora_library.check(golden, "lora details for 3d model", "GET", "/api/v1/loras/hunyuan3d-2mv/details")
    lora_library.check(golden, "loras unknown model", "GET", "/api/v1/loras/not_a_real_model")
    lora_library.check(golden, "lora details unknown model", "GET", "/api/v1/loras/not_a_real_model/details")
    lora_library.check(golden, "lora update manifest empty", "GET", "/api/v1/loras/update-manifest")
    lora_library.check(golden, "lora preview invalid name", "GET", "/api/v1/loras/preview/.secret.png")
    lora_library.check(golden, "lora preview missing", "GET", "/api/v1/loras/preview/no-such.png")


def test_lora_delete_validation(lora_library, golden, monkeypatch, tmp_path) -> None:
    """Delete refuses a bad name, a missing file, a linked copy, and a bundled LoRA."""
    server = lora_library
    config = server.wgp.server_config
    missing_root = str(tmp_path / "no-such-loras")
    monkeypatch.setitem(config, "loras_root", missing_root)
    server.check(
        golden,
        "lora delete no root",
        "DELETE",
        "/api/v1/loras/file",
        params={"directory": "wan", "filename": "style.safetensors"},
    )
    monkeypatch.setitem(config, "loras_root", str(server.lora_root))
    server.check(golden, "lora delete missing params", "DELETE", "/api/v1/loras/file")
    server.check(
        golden,
        "lora delete bad extension",
        "DELETE",
        "/api/v1/loras/file",
        params={"directory": "wan", "filename": "readme.txt"},
    )
    server.check(
        golden,
        "lora delete traversal name",
        "DELETE",
        "/api/v1/loras/file",
        params={"directory": "wan", "filename": "../x.safetensors"},
    )
    server.check(
        golden,
        "lora delete invalid directory",
        "DELETE",
        "/api/v1/loras/file",
        params={"directory": "..", "filename": "style.safetensors"},
    )
    server.check(
        golden,
        "lora delete missing file",
        "DELETE",
        "/api/v1/loras/file",
        params={"directory": "wan", "filename": "missing.safetensors"},
    )

    linked = tmp_path / "other-install"
    linked_wan = linked / "loras" / "wan"
    linked_wan.mkdir(parents=True)
    (linked / "ckpts").mkdir()
    (linked_wan / "linked_only.safetensors").write_bytes(b"linked-weight")
    monkeypatch.setitem(
        config,
        "checkpoints_paths",
        [str(tmp_path / "primary-ckpts"), str(linked / "ckpts")],
    )
    server.check(
        golden,
        "lora delete linked copy",
        "DELETE",
        "/api/v1/loras/file",
        params={"directory": "wan", "filename": "linked_only.safetensors"},
    )

    def bundled(model_type, prop="URLs", sub_prop_name=None, return_list=True, stack=()):
        if prop == "loras":
            return ["https://example.invalid/weights/style.safetensors"]
        return []

    monkeypatch.setattr(server.wgp, "get_model_recursive_prop", bundled, raising=False)
    server.check(
        golden,
        "lora delete bundled",
        "DELETE",
        "/api/v1/loras/file",
        params={"directory": "wan", "filename": "style.safetensors"},
    )

    wan = server.lora_wan
    (wan / "gone.safetensors").write_bytes(b"gone-weight")
    (wan / "gone.civitai.json").write_text("{}\n", encoding="utf-8")
    (wan / "gone.guide.md").write_text("gone\n", encoding="utf-8")
    (wan / "gone_preview1.png").write_bytes(b"png")
    server.check(
        golden,
        "lora delete file",
        "DELETE",
        "/api/v1/loras/file",
        params={"directory": "wan", "filename": "gone.safetensors"},
    )


def test_lora_nsfw_override_validation(lora_library, golden, monkeypatch, tmp_path) -> None:
    """Override refuses a bad body, then writes and clears the flag on one file."""
    server = lora_library
    config = server.wgp.server_config
    monkeypatch.setitem(config, "loras_root", str(tmp_path / "no-such-loras"))
    server.check(
        golden,
        "lora nsfw override no root",
        "POST",
        "/api/v1/loras/nsfw-override",
        json={"filename": "plain.safetensors", "nsfw": True},
    )
    monkeypatch.setitem(config, "loras_root", str(server.lora_root))
    server.check(golden, "lora nsfw override missing filename", "POST", "/api/v1/loras/nsfw-override", json={})
    server.check(
        golden,
        "lora nsfw override bad flag",
        "POST",
        "/api/v1/loras/nsfw-override",
        json={"filename": "plain.safetensors", "nsfw": "yes"},
    )
    server.check(
        golden,
        "lora nsfw override traversal",
        "POST",
        "/api/v1/loras/nsfw-override",
        json={"filename": "../x.safetensors", "nsfw": True},
    )
    server.check(
        golden,
        "lora nsfw override missing file",
        "POST",
        "/api/v1/loras/nsfw-override",
        json={"filename": "missing.safetensors", "nsfw": True},
    )
    (server.lora_wan / "plain.safetensors").write_bytes(b"plain-weight")
    server.check(
        golden,
        "lora nsfw override set",
        "POST",
        "/api/v1/loras/nsfw-override",
        json={"filename": "plain.safetensors", "nsfw": True},
    )
    server.check(
        golden,
        "lora nsfw override clear",
        "POST",
        "/api/v1/loras/nsfw-override",
        json={"filename": "plain.safetensors", "nsfw": None},
    )


class _CivitaiResponse:
    """One canned CivitAI reply. Search and model detail read status, text and json."""

    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers: dict = {}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise OSError(f"status {self.status_code}")


def _civitai_get(search_payloads: list[dict], detail_payloads: list[dict]):
    """Return a ``requests.get`` whose second reply differs, so a cache miss shows up."""
    search_calls = {"n": 0}
    detail_calls = {"n": 0}

    def get(url, **_kwargs):
        text = str(url)
        if text.rstrip("/").endswith("/models"):
            index = min(search_calls["n"], len(search_payloads) - 1)
            search_calls["n"] += 1
            return _CivitaiResponse(search_payloads[index])
        if "/models/" in text:
            index = min(detail_calls["n"], len(detail_payloads) - 1)
            detail_calls["n"] += 1
            return _CivitaiResponse(detail_payloads[index])
        raise AssertionError(f"unexpected CivitAI URL {url}")

    return get


def test_civitai_filters_and_checkpoint_architectures(server, golden) -> None:
    """The browser filter list, and the architecture picker with and without a base model."""
    server.check(golden, "civitai base models", "GET", "/api/v1/civitai/base-models")
    server.check(
        golden,
        "civitai checkpoint architectures",
        "GET",
        "/api/v1/civitai/checkpoint-architectures",
    )
    server.check(
        golden,
        "civitai checkpoint architectures for a base",
        "GET",
        "/api/v1/civitai/checkpoint-architectures",
        params={"base_model": "LTXV2"},
    )


def test_civitai_search_and_detail_hit_the_cache(server, golden, monkeypatch) -> None:
    """A fake search and a fake model, each asked twice. The second answer is the cached first one."""
    import sys

    launch = sys.modules["_launch_runtime"]
    launch._CIVITAI_CACHE.clear()
    search_first = {
        "items": [{
            "id": 7,
            "name": "Cached LoRA",
            "modelVersions": [{
                "id": 70,
                "baseModel": "Wan Video 14B t2v",
                "images": [{"url": "abc123uuid", "type": "image"}],
            }],
        }],
        "metadata": {"nextCursor": ""},
    }
    search_second = {
        "items": [{"id": 8, "name": "Uncached LoRA", "modelVersions": []}],
        "metadata": {},
    }
    detail_first = {
        "id": 4242,
        "name": "Cached Detail",
        "modelVersions": [{
            "id": 90,
            "baseModel": "Wan Video 14B t2v",
            "images": [{"url": "detailuuid", "type": "video"}],
        }],
    }
    detail_second = {"id": 4242, "name": "Uncached Detail", "modelVersions": []}
    monkeypatch.setattr(
        launch.requests,
        "get",
        _civitai_get([search_first, search_second], [detail_first, detail_second]),
    )
    server.check(
        golden,
        "civitai search",
        "GET",
        "/api/v1/civitai/search",
        params={"query": "slice19", "limit": 2},
    )
    server.check(
        golden,
        "civitai search cached",
        "GET",
        "/api/v1/civitai/search",
        params={"query": "slice19", "limit": 2},
    )
    server.check(golden, "civitai model detail", "GET", "/api/v1/civitai/model/4242")
    server.check(golden, "civitai model detail cached", "GET", "/api/v1/civitai/model/4242")


def test_civitai_download_rejects_a_bad_target(server, golden) -> None:
    """A missing URL, a foreign host, and an empty download list. No file is fetched."""
    server.check(golden, "civitai downloads empty", "GET", "/api/v1/civitai/downloads")
    server.check(
        golden,
        "civitai download missing url",
        "POST",
        "/api/v1/civitai/download",
        json={"filename": "model.safetensors"},
    )
    server.check(
        golden,
        "civitai download rejected host",
        "POST",
        "/api/v1/civitai/download",
        json={"download_url": "http://127.0.0.1/secret", "filename": "model.safetensors"},
    )
    server.check(
        golden,
        "civitai download rejected scheme",
        "POST",
        "/api/v1/civitai/download",
        json={"download_url": "file:///etc/passwd", "filename": "model.safetensors"},
    )


def test_checkpoints_installed_on_a_temp_tree(server, golden, monkeypatch, tmp_path) -> None:
    """Installed checkpoints come from a temp finetunes folder, including an empty one."""
    import services.checkpoints as checkpoints

    finetunes = tmp_path / "finetunes"
    finetunes.mkdir()
    monkeypatch.setattr(checkpoints, "_FINETUNES_DIR", str(finetunes))
    server.check(golden, "checkpoints installed empty", "GET", "/api/v1/checkpoints/installed")
    server.check(golden, "checkpoints check updates empty", "POST", "/api/v1/checkpoints/check-updates")
    (finetunes / "example_checkpoint.json").write_text(
        json.dumps({
            "model": {
                "name": "Example Checkpoint",
                "architecture": "ltx2",
                "civitai": {
                    "modelId": 77,
                    "versionId": 88,
                    "baseModel": "LTXV2",
                    "filename": "",
                },
            },
        }),
        encoding="utf-8",
    )
    server.check(golden, "checkpoints installed one", "GET", "/api/v1/checkpoints/installed")
    server.check(
        golden,
        "checkpoint guide unknown",
        "POST",
        "/api/v1/checkpoints/not_a_checkpoint/generate-guide",
        json={},
    )


def test_huggingface_import_rejects_a_bad_body(server, golden) -> None:
    """A body that is not a Hugging Face or CivitAI URL is refused before any download.

    A body that is not JSON at all raises inside ``request.json()`` and never
    becomes a response. That path is left as it is.
    """
    server.check(golden, "hf import empty body", "POST", "/api/v1/huggingface/import-lora", json={})
    server.check(
        golden,
        "hf import bad url",
        "POST",
        "/api/v1/huggingface/import-lora",
        json={"url": "https://example.invalid/not-a-repo"},
    )
    server.check(
        golden,
        "hf import bad target dir",
        "POST",
        "/api/v1/huggingface/import-lora",
        json={"url": "https://huggingface.co/someone/repo", "target_dir": "../etc"},
    )


def test_lora_guide_reads(lora_library, golden) -> None:
    """A missing scan, a missing guide, and a guide that is already on disk."""
    lora_library.check(golden, "lora scan missing", "GET", "/api/v1/loras/scan-status/missing-scan")
    lora_library.check(
        golden,
        "lora guide missing",
        "GET",
        "/api/v1/loras/fake_t2v/absent.safetensors/guide",
    )
    lora_library.check(
        golden,
        "lora guide unknown model",
        "GET",
        "/api/v1/loras/not_a_model/style.safetensors/guide",
    )
    lora_library.check(
        golden,
        "lora guide present",
        "GET",
        "/api/v1/loras/fake_t2v/style.safetensors/guide",
    )


class _CivitaiReply:
    """What ``requests.get`` returns for the CivitAI calls the LoRA routes make."""

    def __init__(self, status: int, payload=None) -> None:
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            error = requests.HTTPError(str(self.status_code))
            error.response = self
            raise error


def _write_update_tree(wan: Path) -> None:
    """Files with sidecars for every update status, plus one the update check must skip."""

    def lora(name: str, **meta) -> None:
        (wan / name).write_bytes(b"weights-" + name.encode())
        sidecar = {"name": name, "baseModel": "Wan Video", "nsfw": False, "downloadedAt": "2020-01-02T03:04:05Z"}
        sidecar.update(meta)
        (wan / (os.path.splitext(name)[0] + ".civitai.json")).write_text(json.dumps(sidecar), encoding="utf-8")

    lora("old.safetensors", modelId=111, versionId=5)
    lora("removed.safetensors", modelId=222, versionId=1)
    lora("bundle.safetensors", modelId=333, versionId=2)
    lora("newer_v1.safetensors", modelId=555, versionId=7)
    lora("newer_v2.safetensors", modelId=555, versionId=8)
    lora("ltx-2-19b-distilled-lora-384.safetensors", modelId=444, versionId=1)


def _civitai_models() -> dict:
    return {
        111: _CivitaiReply(200, {"type": "LORA", "modelVersions": [
            {"id": 6, "publishedAt": "2026-01-02T00:00:00Z", "description": "<p>Fixed <b>hands</b></p>"},
            {"id": 5, "publishedAt": "2025-01-02T00:00:00Z"},
        ]}),
        222: _CivitaiReply(404),
        333: _CivitaiReply(200, {"type": "Checkpoint", "modelVersions": [{"id": 3, "publishedAt": "2026-02-02T00:00:00Z"}]}),
        555: _CivitaiReply(200, {"type": "LORA", "modelVersions": [{"id": 9, "publishedAt": "2026-03-03T00:00:00Z"}]}),
        12345: _CivitaiReply(200, {"type": "LORA", "modelVersions": [{"id": 99, "publishedAt": "2020-01-01T00:00:00Z"}]}),
    }


def _installed_rows(server, golden, case: str) -> None:
    """The installed list sorted by file name: the walk is unsorted and differs between file systems."""
    response = server.client.get("/api/v1/loras/installed")
    rows = sorted(response.json()["loras"], key=lambda row: (row["directory"], row["filename"]))
    body = {**response.json(), "loras": rows}
    golden.check(case, response.status_code, server.normalise(body))


def test_lora_update_check(lora_library, golden, monkeypatch) -> None:
    """Check-updates over fake CivitAI answers, the statuses the lists then show, and an offline retry."""
    import requests

    server = lora_library
    _write_update_tree(server.lora_wan)
    asked: list[str] = []
    models = _civitai_models()

    def fake_get(url, headers=None, timeout=None, **_kwargs):
        asked.append(url.rsplit("/api/v1/", 1)[-1])
        model_id = url.rsplit("/", 1)[-1]
        return models.get(int(model_id), _CivitaiReply(404)) if model_id.isdigit() else _CivitaiReply(404)

    monkeypatch.setattr(requests, "get", fake_get)
    server.check(golden, "lora update check", "POST", "/api/v1/loras/check-updates")
    golden.check("lora update requests", 200, sorted(asked))
    server.check(golden, "lora update check fresh", "POST", "/api/v1/loras/check-updates")
    asked.clear()
    server.check(golden, "lora update check forced", "POST", "/api/v1/loras/check-updates", params={"force": "true"})
    golden.check("lora update requests forced", 200, sorted(asked))
    manifest = json.loads((server.lora_root / ".lora_update_manifest.json").read_text(encoding="utf-8"))
    golden.check("lora update manifest file", 200, server.normalise(manifest))
    _installed_rows(server, golden, "loras installed after update check")
    server.check(golden, "lora details after update check", "GET", "/api/v1/loras/fake_t2v/details")
    sidecar = json.loads((server.lora_wan / "old.civitai.json").read_text(encoding="utf-8"))
    golden.check("lora sidecar published date", 200, server.normalise(sidecar))

    def offline(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", offline)
    server.check(golden, "lora update check offline", "POST", "/api/v1/loras/check-updates", params={"force": "true"})
    manifest = json.loads((server.lora_root / ".lora_update_manifest.json").read_text(encoding="utf-8"))
    golden.check("lora update manifest after offline", 200, server.normalise(manifest))


def _text_files(root: Path) -> dict:
    """Every guide and sidecar under ``root`` by relative path, for a before and after comparison."""
    found = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name.endswith((".guide.md", ".civitai.json")):
            found[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return found


def test_lora_guide_generation(lora_library, golden, monkeypatch) -> None:
    """One guide through a fake language model, then a scan that fetches metadata and writes guides."""
    import hashlib
    import time

    import requests
    from services import llm_routing, llm_service

    server = lora_library
    wan = server.lora_wan
    long_text = "A calm cinematic style that shifts colours towards teal and orange with soft contrast. " * 2

    def lora(filename: str, **meta) -> None:
        (wan / filename).write_bytes(b"weights-" + filename.encode())
        if meta:
            sidecar = {"name": filename, "baseModel": "Wan Video", "description": long_text, "trainedWords": ["trigger"]}
            sidecar.update(meta)
            (wan / (os.path.splitext(filename)[0] + ".civitai.json")).write_text(json.dumps(sidecar), encoding="utf-8")

    lora("target.safetensors", modelId=1, versionId=1, name="Target")
    lora("plain.safetensors", modelId=2, versionId=1, name="Plain")
    lora("empty.safetensors", modelId=3, versionId=1, name="Empty")
    lora("short.safetensors", modelId=4, versionId=1, name="Short", description="")
    lora("no_sidecar.safetensors")

    def answer(**request) -> str:
        prompt = request["prompt"]
        if "LoRA Name: Target" in prompt or "LoRA Name: Scanned" in prompt:
            return '```json\n{"guide": "Use the trigger word.", "recommended_weights": {"source": "civitai", "default": 0.7, "min": 0.5, "max": 1.0}}\n```'
        if "LoRA Name: Plain" in prompt:
            return "Just write the guide as plain text."
        return ""

    monkeypatch.setattr(llm_service, "is_loaded", lambda: True)
    monkeypatch.setattr(llm_service, "generate", answer)
    monkeypatch.setattr(llm_routing, "_ensure_llm_loaded", lambda *_args, **_kwargs: None)

    def generate(case: str, body: dict) -> None:
        server.check(golden, case, "POST", "/api/v1/loras/generate-guide", json=body)

    generate("lora guide generate", {"model_type": "fake_t2v", "filename": "target.safetensors"})
    generate("lora guide generate plain text", {"model_type": "fake_t2v", "filename": "plain.safetensors"})
    generate("lora guide generate empty answer", {"model_type": "fake_t2v", "filename": "empty.safetensors"})
    generate("lora guide generate too little metadata", {"model_type": "fake_t2v", "filename": "short.safetensors"})
    generate("lora guide generate no sidecar", {"model_type": "fake_t2v", "filename": "no_sidecar.safetensors"})
    generate("lora guide generate missing file", {"model_type": "fake_t2v", "filename": "ghost.safetensors"})
    generate("lora guide generate unknown model", {"model_type": "not_a_model", "filename": "target.safetensors"})
    generate("lora guide generate missing fields", {"model_type": "fake_t2v"})

    # Production resolve_lora_path uses basename, so a path that names an
    # installed LoRA used to pass the existence check and then write the
    # sidecar/guide next to os.path.join(lora_dir, filename).
    outside = server.lora_root.parent / "outside-guides"
    outside.mkdir()
    (outside / "target.guide.md").write_text("LEAKED\n", encoding="utf-8")
    monkeypatch.setattr(
        server.wgp,
        "resolve_lora_path",
        lambda _model_type, filename: str(wan / os.path.basename(filename)),
        raising=False,
    )
    traversal = os.path.relpath(outside / "target.safetensors", wan).replace("\\", "/")
    generate("lora guide generate traversal", {"model_type": "fake_t2v", "filename": traversal})
    generate("lora guide generate absolute", {"model_type": "fake_t2v", "filename": str(outside / "target.safetensors")})
    server.check(
        golden,
        "lora guide get traversal",
        "GET",
        f"/api/v1/loras/fake_t2v/{quote(traversal, safe='')}/guide",
    )
    from fastapi import HTTPException
    from services import lora_guides
    with pytest.raises(HTTPException) as leaked:
        lora_guides.get_lora_guide("fake_t2v", traversal)
    assert leaked.value.status_code == 400
    assert leaked.value.detail == "Invalid filename"
    assert (outside / "target.civitai.json").exists() is False
    assert (outside / "target.guide.md").read_text(encoding="utf-8") == "LEAKED\n"

    server.check(golden, "lora guide after generate", "GET", "/api/v1/loras/fake_t2v/target.safetensors/guide")
    golden.check("lora guide files after generate", 200, server.normalise(_text_files(server.lora_root)))

    # The scan: one file with no sidecar (CivitAI knows its hash), one CivitAI does not know.
    lora("scan_new.safetensors")
    scan_hash = hashlib.sha256((wan / "scan_new.safetensors").read_bytes()).hexdigest()
    asked: list[str] = []

    def fake_get(url, headers=None, timeout=None, **_kwargs):
        asked.append(url.rsplit("/api/v1/", 1)[-1].replace(scan_hash, "<HASH>"))
        if url.endswith(f"/model-versions/by-hash/{scan_hash}"):
            return _CivitaiReply(200, {
                "modelId": 9001, "id": 9002, "model": {"name": "Scanned"}, "baseModel": "Wan Video",
                "trainedWords": ["scanword"],
                "images": [{"url": "https://images.invalid/a.png", "meta": {"prompt": "a prompt"}}],
            })
        if url.endswith("/models/9001"):
            return _CivitaiReply(200, {"description": "<p>Scanned   <i>description</i></p>", "tags": ["scan-tag"]})
        return _CivitaiReply(404)

    monkeypatch.setattr(requests, "get", fake_get)

    def scan(case: str, body: dict) -> None:
        started = server.check(
            golden, f"{case} start", "POST", "/api/v1/loras/scan-and-generate-guides", json=body, mask=("scan_id",),
        )
        scan_id = started.json().get("scan_id")
        if not scan_id:
            return
        deadline = time.time() + 20
        state = {}
        while time.time() < deadline:
            state = server.client.get(f"/api/v1/loras/scan-status/{scan_id}").json()
            if state.get("status") == "complete":
                break
            time.sleep(0.02)
        state["results"] = sorted(state.get("results", []), key=lambda item: (item["filename"], sorted(item)))
        golden.check(f"{case} final", 200, server.normalise(state))

    scan("lora scan", {})
    golden.check("lora scan requests", 200, sorted(asked))
    golden.check("lora scan files", 200, server.normalise(_text_files(server.lora_root)))
    asked.clear()
    scan("lora scan again", {})
    scan("lora scan forced", {"force": True})


class _TextReply(_CivitaiReply):
    """A CivitAI reply that also has a body text, for the maintenance page."""

    def __init__(self, status: int, payload=None, text: str = "") -> None:
        super().__init__(status, payload)
        self.text = text


def test_civitai_download_refuses_look_alike_hosts(server, golden) -> None:
    """The allow-list is exact: other schemes, host names that only end in the name, and a user part are refused."""
    for case, url in (
        ("ftp scheme", "ftp://civitai.com/model.safetensors"),
        ("host that ends with the name", "https://evilcivitai.com/model.safetensors"),
        ("name as a sub-domain of another host", "https://civitai.com.evil.example/model.safetensors"),
        ("name in the user part", "https://civitai.com@evil.example/model.safetensors"),
        ("another bucket of the CDN", "https://other-bucket.r2.cloudflarestorage.com/model.safetensors"),
    ):
        server.check(
            golden,
            f"civitai download refuses {case}",
            "POST",
            "/api/v1/civitai/download",
            json={"download_url": url, "filename": "model.safetensors"},
        )
    server.check(golden, "civitai downloads still empty", "GET", "/api/v1/civitai/downloads")


def test_civitai_search_cache_key_errors_and_maintenance(server, golden, monkeypatch) -> None:
    """The mature flag is part of the cache key, an error is never cached, and a maintenance page is told apart."""
    import requests
    import sys

    launch = sys.modules["_launch_runtime"]
    launch._CIVITAI_CACHE.clear()
    asked: list[tuple] = []
    queues: dict[tuple, list] = {}

    def page(name: str) -> dict:
        return {"items": [{"id": 1, "name": name, "modelVersions": []}], "metadata": {}}

    def fake_get(url, params=None, **_kwargs):
        key = (params.get("query"), params.get("nsfw"))
        asked.append(key)
        queue = queues[key]
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(requests, "get", fake_get)
    queues[("mature", "false")] = [_TextReply(200, page("safe results"))]
    queues[("mature", "true")] = [_TextReply(200, page("mature results"))]
    queues[("flaky", "false")] = [_TextReply(500, text="boom"), _TextReply(200, page("second try"))]
    queues[("down", "false")] = [_TextReply(503, text="We'll be right back")]
    queues[("slow", "false")] = [_TextReply(503, text="plain outage")]

    for case, query, nsfw in (
        ("safe", "mature", "false"),
        ("mature", "mature", "true"),
        ("safe again", "mature", "false"),
        ("flaky first", "flaky", "false"),
        ("flaky second", "flaky", "false"),
        ("flaky third", "flaky", "false"),
        ("maintenance", "down", "false"),
        ("other 503", "slow", "false"),
    ):
        server.check(
            golden,
            f"civitai search {case}",
            "GET",
            "/api/v1/civitai/search",
            params={"query": query, "nsfw": nsfw},
        )
    golden.check("civitai search requests", 200, [list(item) for item in asked])
    golden.check("civitai search cache keys", 200, sorted(repr(key[1:5]) for key in launch._CIVITAI_CACHE))
    launch._CIVITAI_CACHE.clear()


def test_civitai_cache_drops_the_oldest_quarter_when_full(server, golden, monkeypatch) -> None:
    """With room for four entries, the fifth search drops the oldest one and the sixth the next."""
    import requests
    import sys

    import services.civitai as civitai

    launch = sys.modules["_launch_runtime"]
    launch._CIVITAI_CACHE.clear()
    monkeypatch.setattr(civitai, "_CIVITAI_CACHE_MAX", 4)
    monkeypatch.setattr(
        requests,
        "get",
        lambda url, params=None, **_kwargs: _TextReply(
            200, {"items": [{"id": 1, "name": params["query"], "modelVersions": []}], "metadata": {}},
        ),
    )
    for index in range(6):
        server.check(
            golden,
            f"civitai fill {index}",
            "GET",
            "/api/v1/civitai/search",
            params={"query": f"fill{index}"},
        )
        remaining = sorted(key[1] for key in launch._CIVITAI_CACHE)
        golden.check(f"civitai cache after fill {index}", 200, remaining)
    launch._CIVITAI_CACHE.clear()


def _write_checkpoint(finetunes: Path, slug: str, name: str, model_id: int, version_id: int) -> None:
    (finetunes / f"{slug}.json").write_text(
        json.dumps({
            "model": {
                "name": name,
                "architecture": "ltx2",
                "civitai": {"modelId": model_id, "versionId": version_id, "baseModel": "LTXV2", "filename": ""},
            },
        }),
        encoding="utf-8",
    )


def test_checkpoint_update_check_keeps_what_the_network_cannot_answer(server, golden, monkeypatch, tmp_path) -> None:
    """Three imported checkpoints, the 24 hour skip, a forced check, and an offline forced check."""
    import requests
    import services.checkpoints as checkpoints

    finetunes = tmp_path / "finetunes"
    finetunes.mkdir()
    monkeypatch.setattr(checkpoints, "_FINETUNES_DIR", str(finetunes))
    # The file names sort the other way round from the display names.
    _write_checkpoint(finetunes, "a_slug_for_zeta", "Zeta Checkpoint", 22, 5)
    _write_checkpoint(finetunes, "m_slug_for_gone", "Gone Checkpoint", 33, 1)
    _write_checkpoint(finetunes, "z_slug_for_alpha", "Alpha Checkpoint", 11, 1)
    asked: list[str] = []
    models = {
        11: _CivitaiReply(200, {"type": "Checkpoint", "modelVersions": [
            {"id": 2, "publishedAt": "2026-01-02T00:00:00Z", "description": "<p>Better <b>faces</b></p>"},
        ]}),
        22: _CivitaiReply(200, {"type": "Checkpoint", "modelVersions": [{"id": 5, "publishedAt": "2026-01-01T00:00:00Z"}]}),
        33: _CivitaiReply(404),
    }

    def fake_get(url, headers=None, timeout=None, **_kwargs):
        asked.append(url.rsplit("/api/v1/", 1)[-1])
        return models[int(url.rsplit("/", 1)[-1])]

    monkeypatch.setattr(requests, "get", fake_get)
    server.check(golden, "checkpoints installed before the check", "GET", "/api/v1/checkpoints/installed")
    server.check(golden, "checkpoints update check", "POST", "/api/v1/checkpoints/check-updates")
    golden.check("checkpoints update requests", 200, sorted(asked))
    asked.clear()
    server.check(golden, "checkpoints update check skipped", "POST", "/api/v1/checkpoints/check-updates")
    golden.check("checkpoints update requests when skipped", 200, sorted(asked))
    server.check(golden, "checkpoints installed after the check", "GET", "/api/v1/checkpoints/installed")
    server.check(
        golden, "checkpoints update check forced", "POST", "/api/v1/checkpoints/check-updates", params={"force": "true"},
    )
    golden.check("checkpoints update requests forced", 200, sorted(asked))

    def offline(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(requests, "get", offline)
    server.check(
        golden, "checkpoints update check offline", "POST", "/api/v1/checkpoints/check-updates", params={"force": "true"},
    )
    server.check(golden, "checkpoints installed after the offline check", "GET", "/api/v1/checkpoints/installed")
    manifest = json.loads((finetunes / ".checkpoint_update_manifest.json").read_text(encoding="utf-8"))
    golden.check("checkpoints update manifest file", 200, server.normalise(manifest))


def test_checkpoint_guide_needs_a_civitai_provenance_block(server, golden, monkeypatch, tmp_path) -> None:
    """A finetune that was not imported from CivitAI, and one that cannot be read, are refused before any model loads."""
    import services.checkpoints as checkpoints
    from services import llm_routing

    finetunes = tmp_path / "finetunes"
    finetunes.mkdir()
    monkeypatch.setattr(checkpoints, "_FINETUNES_DIR", str(finetunes))
    monkeypatch.setattr(llm_routing, "_ensure_llm_loaded", lambda *_args, **_kwargs: None)
    (finetunes / "plain.json").write_text(json.dumps({"model": {"name": "Plain", "architecture": "ltx2"}}), encoding="utf-8")
    (finetunes / "broken.json").write_text("{not json", encoding="utf-8")
    server.check(golden, "checkpoint guide not imported", "POST", "/api/v1/checkpoints/plain/generate-guide", json={})
    server.check(golden, "checkpoint guide unreadable", "POST", "/api/v1/checkpoints/broken/generate-guide", json={})


def test_civitai_url_import_refusals(server, golden, monkeypatch) -> None:
    """A pasted CivitAI link that cannot become a download answers before any thread or file."""
    import requests

    def model(model_id: int, kind: str = "LORA", versions=None) -> dict:
        return {"id": model_id, "name": f"Model {model_id}", "type": kind, "modelVersions": versions if versions is not None else []}

    def one_file(**file) -> list:
        return [{"id": 1, "baseModel": "LTXV2", "files": [file]}]

    replies = {
        "models/201": _CivitaiReply(200, model(201, "Checkpoint")),
        "models/202": _CivitaiReply(200, model(202)),
        "models/203": _CivitaiReply(200, model(203, versions=[{"id": 1, "files": []}])),
        "models/204": _CivitaiReply(200, model(204, versions=one_file(name="CON.safetensors", downloadUrl="https://civitai.com/d"))),
        "models/205": _CivitaiReply(200, model(205, versions=one_file(name="a.safetensors"))),
        "models/206": _CivitaiReply(404),
        "models/207": _CivitaiReply(200, model(207, versions=one_file(name="a.safetensors", downloadUrl="https://civitai.com/d"))),
        "model-versions/301": _CivitaiReply(200, {"error": "gone"}),
        "model-versions/302": _CivitaiReply(200, {}),
    }
    asked: list[str] = []

    def fake_get(url, headers=None, timeout=None, **_kwargs):
        key = url.rsplit("/api/v1/", 1)[-1]
        asked.append(key)
        if key == "models/208":
            raise requests.Timeout("slow")
        if key == "models/209":
            raise requests.ConnectionError("down")
        return replies[key]

    monkeypatch.setattr(requests, "get", fake_get)
    for case, url, extra in (
        ("not a lora", "https://civitai.com/models/201", {}),
        ("no versions", "https://civitai.com/models/202", {}),
        ("no files", "https://civitai.com/models/203", {}),
        ("device file name", "https://civitai.com/models/204", {}),
        ("no download url", "https://civitai.com/models/205", {}),
        ("model not found", "https://civitai.com/models/206", {}),
        ("version not on the model", "https://civitai.com/models/207?modelVersionId=999", {}),
        ("version link with an error", "https://civitai.com/api/download/models/301", {}),
        ("version link without a model", "https://civitai.com/api/download/models/302", {}),
        ("timeout", "https://civitai.com/models/208", {}),
        ("connection error", "https://civitai.com/models/209", {}),
        ("not a model link", "https://civitai.com/user/someone", {}),
        ("directory leaves the folder", "https://civitai.com/models/207", {"target_dir": "../elsewhere"}),
    ):
        server.check(
            golden,
            f"civitai import {case}",
            "POST",
            "/api/v1/huggingface/import-lora",
            json={"url": url, **extra},
        )
    golden.check("civitai import requests", 200, asked)
    server.check(golden, "civitai downloads after the refusals", "GET", "/api/v1/civitai/downloads")
