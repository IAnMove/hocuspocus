"""Model catalog over a fake WanGP catalog, and the configuration reads the Settings screen makes."""
from __future__ import annotations

import json
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
    import sys

    finetunes = tmp_path / "finetunes"
    finetunes.mkdir()
    launch = sys.modules["_launch_runtime"]
    monkeypatch.setattr(launch, "_FINETUNES_DIR", str(finetunes))
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
