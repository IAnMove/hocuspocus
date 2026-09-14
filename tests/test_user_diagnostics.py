"""User diagnostics: facts, redaction, and no heavy-engine imports."""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.user_diagnostics import create_user_diagnostics_router
from services.user_diagnostics import (
    collect_report,
    correlate_error,
    parse_gpu,
    receipt_status,
    snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "app" / "services" / "user_diagnostics.py"
ROUTER = ROOT / "app" / "routers" / "user_diagnostics.py"
BANNED_MODULES = {
    "torch", "wgp", "pynvml", "flash_attn", "sageattention", "triton",
}
BANNED_FROM = {
    "services.hardware_detect", "services.live_stats", "services.perf_recommend",
}
SECRETS = (
    "sk-test-h18-secret-9f3a2c1b",
    "h18-cookie-value-do-not-export",
    "h18-token-xyz-private",
    "PRIVATE_PROMPT_do_not_include_in_pack",
    "secret-lyrics-never-export",
)
FACT_KEYS = (
    "component", "driver", "backend", "ram_gb_observed", "vram_gb_observed",
    "version", "repair_path", "available", "reasons",
)

MISSING_ENGINES = {
    name: {"present": False, "installed": False, "fingerprint_match": False}
    for name in ("wangp", "hunyuan3d", "minimax_h3", "sam", "rigging")
}
READY_ENGINES = {
    name: {"present": True, "installed": True, "fingerprint_match": True}
    for name in ("wangp", "hunyuan3d", "minimax_h3", "sam", "rigging")
}


def _cpu_observe(**extra):
    observe = {
        "platform": "linux",
        "architecture": "x64",
        "gpu_csv": None,
        "ram_gb": 32.0,
        "cpu_count": 8,
        "app_version": "0.9.0",
        "git_revision": "deadbeef",
        "ui_build_id": "missing",
        "receipts": dict(MISSING_ENGINES),
    }
    observe.update(extra)
    return observe


def _nvidia_observe(**extra):
    observe = _cpu_observe(
        gpu_csv="NVIDIA GeForce RTX 4090, 580.82.09, 24564",
        ram_gb=64.0,
        cpu_count=16,
        receipts=dict(READY_ENGINES),
    )
    observe.update(extra)
    return observe


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.add(node.module.split(".")[0])
    return names


def test_source_does_not_import_heavy_engines():
    names = _imported_names(SERVICE) | _imported_names(ROUTER)
    assert names.isdisjoint(BANNED_MODULES)
    assert names.isdisjoint(BANNED_FROM)


def test_collect_report_subprocess_does_not_load_heavy_engines():
    script = (
        "import sys\n"
        "banned = ('torch', 'wgp', 'pynvml', 'flash_attn', 'sageattention')\n"
        "for name in banned:\n"
        "    sys.modules.pop(name, None)\n"
        "from services.user_diagnostics import collect_report\n"
        "collect_report(observe={"
        "'gpu_csv': None, 'ram_gb': 32.0, 'cpu_count': 8, 'app_version': '0.9.0',"
        "'git_revision': 'deadbeef', 'ui_build_id': 'missing',"
        "'platform': 'linux', 'architecture': 'x64',"
        "'receipts': {name: {'present': False, 'installed': False, 'fingerprint_match': False}"
        " for name in ('wangp', 'hunyuan3d', 'minimax_h3', 'sam', 'rigging')}})\n"
        "loaded = [name for name in banned if name in sys.modules]\n"
        "raise SystemExit(0 if not loaded else 'loaded ' + ','.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT / "app")},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_cpu_host_explains_unavailable_generation_with_repair_path():
    pack = collect_report(observe=_cpu_observe())
    image = next(item for item in pack["availability"] if item["id"] == "generation.image")
    assert image["available"] is False
    assert image["component"] == "wangp"
    assert image["backend"] == "none"
    assert image["ram_gb_observed"] == 32.0
    assert image["vram_gb_observed"] is None
    assert image["version"]["app"] == "0.9.0"
    assert image["repair_path"]["id"] == "cpu_amd_recipe"
    receipt = next(item for item in pack["availability"] if item["id"] == "generation.receipt")
    assert receipt["available"] is True
    assert receipt["repair_path"] is None


def test_nvidia_host_marks_published_ops_available_and_unpublished_model3d_not():
    pack = collect_report(observe=_nvidia_observe())
    by_id = {item["id"]: item for item in pack["availability"]}
    assert by_id["generation.image"]["available"] is True
    assert by_id["generation.image"]["driver"] == "580.82.09"
    assert by_id["generation.image"]["vram_gb_observed"] == 24.0
    assert by_id["flux2_klein_4b"]["available"] is True
    assert by_id["generation.model3d"]["available"] is False
    assert by_id["generation.model3d"]["repair_path"]["id"] == "unpublished"
    for item in pack["availability"]:
        for key in FACT_KEYS:
            assert key in item


def test_low_vram_blocks_large_model_with_existing_repair():
    pack = collect_report(observe=_nvidia_observe(
        gpu_csv="NVIDIA GeForce RTX 3060, 570.124.06, 8192",
    ))
    by_id = {item["id"]: item for item in pack["availability"]}
    assert by_id["flux2_klein_4b"]["available"] is True
    assert by_id["ltx2_22B"]["available"] is False
    assert by_id["ltx2_22B"]["repair_path"]["id"] == "lower_vram"
    assert by_id["engine.minimax_h3"]["available"] is False
    assert by_id["engine.minimax_h3"]["repair_path"]["id"] == "nvidia_driver"


def test_missing_receipt_uses_install_update_repair():
    pack = collect_report(observe=_nvidia_observe(receipts=dict(MISSING_ENGINES)))
    image = next(item for item in pack["availability"] if item["id"] == "generation.image")
    assert image["available"] is False
    assert image["repair_path"]["id"] == "install_update"


def test_synthetic_secrets_and_prompts_never_appear_in_the_pack():
    task = {
        "id": "task-h18",
        "status": "failed",
        "workflow": "generation.image",
        "message": "CUDA out of memory api_key=sk-test-h18-secret-9f3a2c1b",
        "workspace": "ws",
        "backend_job_id": "job-1",
        "prompt": "PRIVATE_PROMPT_do_not_include_in_pack",
        "lyrics": "secret-lyrics-never-export",
        "api_key": "sk-test-h18-secret-9f3a2c1b",
        "cookie": "session=h18-cookie-value-do-not-export",
        "authorization": "Bearer h18-token-xyz-private",
        "metadata": {
            "prompt": "PRIVATE_PROMPT_do_not_include_in_pack",
            "oom_info": {
                "is_oom": True,
                "current_coefficient": 0.8,
                "suggested_coefficient": 0.7,
            },
        },
    }
    receipt = {
        "commandId": "intent-h18",
        "operation": "generation.image",
        "status": "queued",
        "input": {"prompt": "PRIVATE_PROMPT_do_not_include_in_pack"},
        "result": {"task_id": "task-h18", "job_id": "job-1", "workspace": "ws"},
    }
    pack = collect_report(
        observe=_cpu_observe(),
        task=task,
        receipt=receipt,
        error={"code": "oom", "message": "failed Cookie: session=h18-cookie-value-do-not-export"},
    )
    blob = json.dumps(pack, ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in blob
    assert pack["error"]["task_id"] == "task-h18"
    assert pack["error"]["intent_id"] == "intent-h18"
    assert pack["error"]["operation"] == "generation.image"
    assert pack["error"]["job_id"] == "job-1"
    assert pack["error"]["code"] == "oom"
    assert pack["error"]["oom"]["is_oom"] is True
    assert "prompt" not in json.dumps(pack["error"])
    assert pack["schema"] == "hocuspocus.user-diagnostics-report"
    assert pack["build"]["app_version"] == "0.9.0"
    assert pack["platform"]["os"] == "linux"
    assert "engines" in pack["capabilities"]


def test_correlate_error_without_payload_is_none():
    assert correlate_error() is None


def test_parse_gpu_without_nvidia_smi_is_none_backend():
    parsed = parse_gpu(None)
    assert parsed["backend"] == "none"
    assert parsed["vram_gb"] is None
    parsed = parse_gpu("NVIDIA RTX 4090, 580.82.09, 24564")
    assert parsed["kind"] == "nvidia"
    assert parsed["vram_gb"] == 24.0
    assert parsed["driver"] == "580.82.09"


def test_receipt_status_rejects_non_object_receipts(tmp_path, monkeypatch):
    from services import runtime_profiles as profiles
    app = tmp_path / "app"
    env = app / "env"
    env.mkdir(parents=True)
    receipt = env / ".hocus-runtime-profile.json"
    monkeypatch.setattr(profiles, "APP_DIR", app)
    monkeypatch.setattr(profiles, "dependency_fingerprint", lambda engine, platform: "matching")
    receipt.write_text(json.dumps(["corrupt"]))
    assert receipt_status("wangp", "linux")["installed"] is False
    receipt.write_text(json.dumps({
        "fingerprint": "matching",
        "profile": "linux-x64-nvidia-wangp",
        "cudaCalculation": True,
    }))
    assert receipt_status("wangp", "linux")["installed"] is True


def test_shared_environment_does_not_check_an_unsupported_platform_recipe(tmp_path, monkeypatch):
    from services import runtime_profiles as profiles
    app = tmp_path / "app"
    env = app / "env"
    env.mkdir(parents=True)
    (env / ".hocus-runtime-profile.json").write_text(json.dumps({
        "fingerprint": "matching", "profile": "linux-x64-nvidia-wangp", "cudaCalculation": True,
    }))
    monkeypatch.setattr(profiles, "APP_DIR", app)

    def unsupported_fingerprint(*args):
        raise AssertionError("There is no core recipe for Linux or Windows")

    monkeypatch.setattr(profiles, "dependency_fingerprint", unsupported_fingerprint)
    for platform in ("linux", "win32"):
        assert receipt_status("core", platform) == {
            "present": False, "installed": False, "fingerprint_match": False,
        }


def test_incomplete_recipe_is_reported_without_crashing_diagnostics(tmp_path, monkeypatch):
    from services import runtime_profiles as profiles
    app = tmp_path / "app"
    env = app / "env"
    env.mkdir(parents=True)
    (env / ".hocus-runtime-profile.json").write_text(json.dumps({"fingerprint": "old"}))
    monkeypatch.setattr(profiles, "APP_DIR", app)
    # The installed receipt exists, but this checkout is missing recipe files.
    assert receipt_status("wangp", "linux") == {
        "present": True, "installed": False, "fingerprint_match": False,
    }


def test_core_receipt_does_not_require_a_cuda_calculation(tmp_path, monkeypatch):
    from services import runtime_profiles as profiles
    app = tmp_path / "app"
    env = app / "env"
    env.mkdir(parents=True)
    receipt = env / ".hocus-runtime-profile.json"
    monkeypatch.setattr(profiles, "APP_DIR", app)
    monkeypatch.setattr(profiles, "dependency_fingerprint", lambda engine, platform: "matching")
    for cuda, expected in ((False, True), (True, False), (None, False)):
        receipt.write_text(json.dumps({
            "fingerprint": "matching", "profile": "darwin-arm64-core-core", "cudaCalculation": cuda,
        }))
        assert receipt_status("core", "darwin")["installed"] is expected


def test_router_get_and_report_redact_loaded_task():
    def load_task(_task_id: str):
        return {
            "id": "task-h18",
            "status": "failed",
            "workflow": "generation.image",
            "prompt": "PRIVATE_PROMPT_do_not_include_in_pack",
            "api_key": "sk-test-h18-secret-9f3a2c1b",
            "message": "model files missing",
        }

    def load_receipt(_workspace: str, _intent_id: str):
        return {
            "commandId": "intent-h18",
            "operation": "generation.image",
            "result": {"task_id": "task-h18", "job_id": "job-9", "workspace": "ws"},
        }

    def collect(**kwargs):
        return collect_report(observe=_cpu_observe(), **kwargs)

    app = FastAPI()
    app.include_router(create_user_diagnostics_router(
        collect=collect, load_task=load_task, load_receipt=load_receipt,
    ))
    client = TestClient(app)
    snapshot_body = client.get("/api/v1/diagnostics").json()
    assert snapshot_body["schema"] == "hocuspocus.user-diagnostics-report"
    assert snapshot_body["error"] is None
    report = client.post("/api/v1/diagnostics/report", json={
        "task_id": "task-h18",
        "intent_id": "intent-h18",
        "workspace": "ws",
    }).json()
    blob = json.dumps(report)
    for secret in SECRETS:
        assert secret not in blob
    assert report["error"]["task_id"] == "task-h18"
    assert report["error"]["intent_id"] == "intent-h18"
    assert report["error"]["job_id"] == "job-9"


def test_snapshot_pack_shape_has_build_platform_and_capabilities():
    pack = snapshot(observe=_cpu_observe())
    assert set(pack["build"]) == {"app_version", "git_revision", "ui_build_id"}
    assert pack["platform"]["backend"] == "none"
    assert isinstance(pack["capabilities"]["engines"], list)
    assert {engine["id"] for engine in pack["capabilities"]["engines"]} >= {"wangp", "hunyuan3d"}
