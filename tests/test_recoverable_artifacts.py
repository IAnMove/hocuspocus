"""Agent-made artifacts keep what the app needs to list, open and redo them."""
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.wangp_mcp import create_wangp_mcp_router
from routers.world3d_templates import create_world3d_templates_router
from services import rig_service
from services.series_native_render import _carry_sidecar, _replace_with_sidecar
from services.task_manager import TaskRegistry
from services.world3d_export import World3DExportService
from services.world3d_template_commands import command_catalog, command_handlers

DOCUMENT = {"version": 1, "templateId": "two-shot", "duration": 6, "width": 1920, "height": 1080,
            "slots": [{"id": "subject_1", "slot": "subject_1", "media": "model3d", "sourceUrl": "/api/v1/file/rayo.glb?workspace=studio"},
                      {"id": "background", "slot": "background", "media": "image", "sourceUrl": ""}]}


def _client(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    app = FastAPI()
    app.include_router(create_world3d_templates_router(root))
    app.include_router(create_wangp_mcp_router(handlers=command_handlers(root), command_operations=command_catalog(),
                                               journal_path=str(tmp_path / "journal.sqlite3"), token_getter=lambda: "token"))
    return TestClient(app)


def _put(client, template_id, *, mcp, headers=None):
    arguments = {"version": 1, "intent_id": f"put-{template_id}", "input": {
        "workspace": "studio", "id": template_id, "title": template_id.title(), "description": "for the trail", "document": DOCUMENT}}
    if mcp:
        response = client.post("/api/v1/mcp", headers={"Authorization": "Bearer token"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "world3d.templates.user.put", "arguments": arguments}})
    else:
        response = client.post("/api/v1/world3d/templates/commands", headers=headers or {},
                               json={"operation": "world3d.templates.user.put", **arguments})
    assert response.status_code == 200, response.text


def test_workspace_templates_say_who_saved_them_and_open_as_saved(tmp_path):
    client = _client(tmp_path)
    _put(client, "user-agent-shot", mcp=True)
    _put(client, "user-wizard-shot", mcp=False, headers={"X-Hocus-UI-Surface": "wizard"})
    _put(client, "user-plain-shot", mcp=False)
    listed = client.get("/api/v1/world3d/templates/workspace", params={"workspace": "studio"}).json()["templates"]
    by_id = {item["id"]: item for item in listed}
    assert {key: by_id[key]["createdBy"] for key in by_id} == {
        "user-agent-shot": "agent", "user-wizard-shot": "wizard", "user-plain-shot": "user"}
    agent = by_id["user-agent-shot"]
    assert agent["slots"] == 2 and agent["pending"] == 1 and agent["duration"] == 6 and agent["baseTemplateId"] == "two-shot"
    assert agent["createdAt"] and agent["updatedAt"]
    stored = client.get("/api/v1/world3d/templates/workspace/user-agent-shot", params={"workspace": "studio"}).json()["template"]
    assert stored["document"]["templateId"] == "two-shot"  # the editor keeps its base shot
    first = agent["createdAt"]
    _put(client, "user-agent-shot", mcp=False)  # a later save keeps the creation time and creator
    again = {item["id"]: item for item in client.get("/api/v1/world3d/templates/workspace", params={"workspace": "studio"}).json()["templates"]}
    assert again["user-agent-shot"]["createdAt"] == first and again["user-agent-shot"]["createdBy"] == "agent"
    missing = client.get("/api/v1/world3d/templates/workspace/user-nope", params={"workspace": "studio"})
    assert missing.status_code == 404
    assert client.get("/api/v1/world3d/templates/workspace", params={"workspace": "../x"}).status_code == 422


def test_an_empty_workspace_lists_no_templates(tmp_path):
    response = _client(tmp_path).get("/api/v1/world3d/templates/workspace", params={"workspace": "empty"})
    assert response.status_code == 200 and response.json()["templates"] == []


def test_an_export_keeps_who_requested_it_when_it_finishes(tmp_path):
    registry = TaskRegistry(str(tmp_path))
    registry.create(id="export-1", kind="video", title="Video 3D export", status="running", workspace="show",
                    metadata={"operation": "scenes.world3d.export", "tool": "external_agent", "capability": "scenes.world3d.export"})
    service = World3DExportService(workspace_dir=lambda workspace: str(tmp_path), registry_for=lambda workspace: registry)
    service._finish(registry, "export-1", "completed", message="Published", result_refs=["clip.mp4"],
                    metadata={"operation": "scenes.world3d.export", "output": {"name": "clip.mp4"}})
    metadata = registry.get("export-1")["metadata"]
    assert metadata["tool"] == "external_agent" and metadata["output"] == {"name": "clip.mp4"}


def test_a_rig_names_who_asked_for_it_on_the_glb(tmp_path):
    job = {"provenance": {"actor": "user", "tool": "external_agent", "capability": "model3d.rig", "command": {"command_id": "rig-ines"}}}
    assert rig_service._sidecar_origin(job) == {"tool": "external_agent", "actor": "user", "capability": "model3d.rig"}
    assert rig_service._command_id(job) == {"command_id": "rig-ines"}
    assert rig_service._sidecar_origin({}) == {"tool": "rig"}
    assert rig_service._command_id({}) == {}


def _write(path: Path, data: bytes = b"RIFF0000WAVE") -> None:
    path.write_bytes(data)


def test_a_trimmed_series_line_keeps_the_take_provenance(tmp_path):
    raw, final = tmp_path / "ln-ep-b0-key-raw.wav", tmp_path / "ln-ep-b0-key.wav"
    _write(raw), _write(final, b"RIFF00WAVE")
    (tmp_path / "ln-ep-b0-key-raw.meta.json").write_text(json.dumps({
        "asset": {"filename": raw.name, "uri": raw.name, "id": "asset_1", "media": {"size_bytes": 12}},
        "params": {"prompt": "¡A babor!", "alt_prompt": "voz grave castellana", "model_type": "qwen3_tts_voicedesign"},
        "origin": {"tool": "studio", "capability": "generation.speech"}, "lineage": {"parents": [], "transformations": []},
    }), encoding="utf-8")
    _carry_sidecar(str(raw), str(final))
    carried = json.loads((tmp_path / "ln-ep-b0-key.meta.json").read_text(encoding="utf-8"))
    assert carried["asset"]["filename"] == final.name and carried["asset"]["uri"] == final.name
    assert carried["asset"]["media"]["size_bytes"] == final.stat().st_size
    assert carried["params"]["prompt"] == "¡A babor!" and carried["params"]["alt_prompt"] == "voz grave castellana"
    assert carried["lineage"]["transformations"] == [{"kind": "trim", "from": raw.name}]
    best = tmp_path / "ln-ep-b0-key.best.wav"
    _replace_with_sidecar(str(final), str(best))
    assert best.is_file() and (tmp_path / "ln-ep-b0-key.best.meta.json").is_file()
    assert not (tmp_path / "ln-ep-b0-key.meta.json").exists()
    _replace_with_sidecar(str(best), str(final))
    assert (tmp_path / "ln-ep-b0-key.meta.json").is_file()


def test_a_take_without_a_sidecar_leaves_none_behind(tmp_path):
    raw, final = tmp_path / "raw.wav", tmp_path / "line.wav"
    _write(raw), _write(final)
    _carry_sidecar(str(raw), str(final))
    assert not (tmp_path / "line.meta.json").exists()
    (tmp_path / "other.meta.json").write_text("{}", encoding="utf-8")
    _write(tmp_path / "other.wav")
    _replace_with_sidecar(str(final), str(tmp_path / "other.wav"))
    assert not (tmp_path / "other.meta.json").exists()  # a stale sidecar never describes the replaced file
