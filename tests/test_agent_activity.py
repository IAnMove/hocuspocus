"""Whatever an agent makes through MCP shows up in Activity, attributed and openable."""
import asyncio
import json
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.wangp_mcp import create_wangp_mcp_router
from services.agent_activity import (
    AgentActivity, SERVER_CALLER, actor_label, artifact_targets, caller_scope, is_external_agent, requested_by,
    trusted_tool,
)
from services.local_mcp import LocalMcp
from services.task_manager import TaskRegistry

AGENT = {"surface": "mcp", "tool": "external_agent"}
PUBLISHED = {"version": 1, "operation": "world3d.scene.publish", "status": "completed", "result": {"status": "completed", "scene": {
    "sceneId": "w3d-0123456789ab", "revision": 3, "file": "w3d-0123456789ab-f00.world3d.scene.json",
    "url": "/api/v1/file/w3d-0123456789ab-f00.world3d.scene.json?workspace=show", "editor": "video3d", "document": {"slots": []}}}}


def _activity(tmp_path):
    registries = {}

    def registry_for(workspace):
        if workspace not in registries:
            (tmp_path / workspace).mkdir(exist_ok=True)
            registries[workspace] = TaskRegistry(str(tmp_path / workspace))
        return registries[workspace]
    return AgentActivity(registry_for, lambda: "show"), registry_for


def _agent_tasks(registry):
    return [task for task in registry.list(limit=100) if task["kind"] == "agent"]


def test_targets_name_each_artifact_once_with_the_most_specific_first():
    targets = artifact_targets({"input": {"workspace": "show", "scene_id": "w3d-0123456789ab"}}, PUBLISHED)
    assert [(item["kind"], item["id"]) for item in targets] == [
        ("world3d_scene", "w3d-0123456789ab"), ("scene_file", "w3d-0123456789ab-f00.world3d.scene.json")]
    assert targets[1]["editor"] == "video3d"
    template = artifact_targets({}, {"result": {"template": {"id": "user-duelo", "source": "workspace", "title": "Duelo"}}})
    assert template == [{"kind": "world3d_template", "id": "user-duelo", "title": "Duelo"}]
    kit = artifact_targets({}, {"result": {"character": {"id": "pu-ines", "name": "Inés"}}})
    assert kit == [{"kind": "character_kit", "id": "pu-ines", "title": "Inés"}]
    take = artifact_targets({"input": {"series_id": "pu-es", "episode_id": "ep1"}}, {"result": {"asset": {"id": "asset_1"}}})
    assert take == [{"kind": "series_episode", "id": "ep1", "series": "pu-es"}]
    compose = artifact_targets({}, {"result": {"file": "compose-galeon-0011.glb", "url": "/api/v1/file/compose-galeon-0011.glb?workspace=show"}})
    assert compose == [{"kind": "file", "id": "compose-galeon-0011.glb", "file": "compose-galeon-0011.glb"}]
    assert artifact_targets({}, {"result": {"file": "/etc/passwd.png", "path": "../escape.png"}}) == []


def test_agent_changes_become_one_task_per_artifact(tmp_path):
    activity, registry_for = _activity(tmp_path)
    instantiated = {"result": {"scene": {"sceneId": "w3d-0123456789ab", "revision": 1, "templateId": "user-duelo"}}}
    with caller_scope(AGENT):
        activity.record("world3d.scene.instantiate", {"intent_id": "a", "input": {"workspace": "show"}}, instantiated)
        for index in range(3):
            activity.record("world3d.scene.patch", {"intent_id": f"p{index}", "input": {"workspace": "show", "scene_id": "w3d-0123456789ab"}},
                            {"result": {"scene": {"sceneId": "w3d-0123456789ab", "revision": index + 2}}})
        activity.record("world3d.scene.publish", {"intent_id": "pub", "input": {"workspace": "show"}}, PUBLISHED)
        activity.record("world3d.scene.publish", {"intent_id": "pub", "input": {"workspace": "show"}}, {**PUBLISHED, "replayed": True})
    [task] = _agent_tasks(registry_for("show"))
    assert task["status"] == "completed" and task["workspace"] == "show"
    metadata = task["metadata"]
    assert metadata["tool"] == "external_agent" and metadata["actor"] == "agent" and metadata["capability"] == "world3d.scene.publish"
    assert metadata["operations"] == {"world3d.scene.instantiate": 1, "world3d.scene.patch": 3, "world3d.scene.publish": 1}
    assert task["title"] == "Agent · user-duelo"
    assert task["result_refs"] == ["w3d-0123456789ab-f00.world3d.scene.json"]
    assert {item["kind"] for item in metadata["targets"]} == {"world3d_scene", "scene_file"}


def test_server_jobs_plain_http_and_failures_are_not_agent_work(tmp_path):
    activity, registry_for = _activity(tmp_path)
    activity.record("scenes.document.save", {"input": {"workspace": "show"}}, {"result": {"name": "a.scene.json", "editor": "video2d"}})
    with caller_scope(SERVER_CALLER):
        activity.record("scenes.document.save", {"input": {"workspace": "show"}}, {"result": {"name": "b.scene.json", "editor": "video2d"}})
    with caller_scope(AGENT):
        activity.record("scenes.document.save", {"input": {"workspace": "show"}}, {"status": "failed", "error": {"code": "x"}})
        activity.record("jobs.resume", {"input": {"workspace": "show"}}, {"status": "completed"})
        activity.record("series.episode.render_native.cancel", {"input": {"workspace": "show"}}, {"status": "completed"})
    assert _agent_tasks(registry_for("show")) == []


def test_a_job_the_agent_admitted_is_attributed_instead_of_duplicated(tmp_path):
    activity, registry_for = _activity(tmp_path)
    registry = registry_for("show")
    registry.create(id="world3d-export-1", kind="video", workflow="scenes.world3d.export", title="Video 3D export",
                    status="queued", workspace="show", metadata={"operation": "scenes.world3d.export"})
    with caller_scope(AGENT):
        activity.record("scenes.world3d.export", {"intent_id": "exp-1", "input": {"workspace": "show"}},
                        {"receipt": {"taskIds": ["world3d-export-1"], "result": {"task_id": "world3d-export-1"}}})
    assert _agent_tasks(registry) == []
    metadata = registry.get("world3d-export-1")["metadata"]
    assert metadata["tool"] == "external_agent" and metadata["capability"] == "scenes.world3d.export" and metadata["command_id"] == "exp-1"
    assert metadata["operation"] == "scenes.world3d.export"
    assert requested_by(metadata) == {"requested_by": {"tool": "external_agent", "capability": "scenes.world3d.export", "command_id": "exp-1"},
                                      "command_id": "exp-1"}
    assert requested_by({"tool": "studio"}) == {}


def test_the_agent_view_lists_only_agent_and_wizard_work(tmp_path):
    registry = TaskRegistry(str(tmp_path))
    for task_id, kind, metadata in (("agent", "agent", {"adapter": "agent"}), ("mcp-image", "image", {"tool": "external_agent"}),
                                    ("wizard-sfx", "audio", {"tool": "studio", "actor": "wizard"}), ("studio", "image", {"tool": "studio", "actor": "user"})):
        registry.create(id=task_id, kind=kind, title=task_id, status="completed", workspace="show", metadata=metadata)
    assert {task["id"] for task in registry.list(limit=50, origin="agent")} == {"agent", "mcp-image", "wizard-sfx"}
    assert len(registry.list(limit=50)) == 4


def test_caller_scope_decides_the_provenance_tool():
    assert trusted_tool() is None and trusted_tool(default_external=True) == "external_agent"
    with caller_scope(AGENT):
        assert is_external_agent() and trusted_tool() == "external_agent" and actor_label() == "agent"
    with caller_scope(SERVER_CALLER):
        assert not is_external_agent() and trusted_tool(default_external=True) is None and actor_label() == "user"
    with caller_scope({"surface": "wizard", "internal": "wizard"}):
        assert actor_label() == "wizard"


def test_local_mcp_runs_handlers_as_the_server():
    seen = []

    def sync(arguments):
        seen.append(("sync", trusted_tool(default_external=True)))
        return {"ok": True}

    async def coroutine(arguments):
        seen.append(("async", trusted_tool(default_external=True)))
        return {"ok": True}
    local = LocalMcp(lambda: {"sync": sync, "async": coroutine})
    assert local.call("sync", {}) == {"ok": True}
    assert local.call("async", {}) == {"ok": True}
    assert seen == [("sync", None), ("async", None)]


def test_music_shot_command_can_call_async_local_tools_without_nesting_event_loops(tmp_path, monkeypatch):
    from services.agent_activity import current_actor
    from services.production_commands import SHOT_UPDATE, extra_handlers

    seen = []

    async def tool(arguments):
        seen.append(current_actor())
        return {"file": "edited.mp4"}

    local = LocalMcp(lambda: {"demo": tool})

    def update(production, *args, **kwargs):
        seen.append(current_actor())
        return production.mcp("demo", {})

    monkeypatch.setattr("services.production_shot_edit.update_shot", update)
    (tmp_path / "p.production.json").write_text(json.dumps({"spec": {"title": "test"}}))
    handlers = extra_handlers(lambda _: str(tmp_path), lambda: str(tmp_path), lambda: "", lambda: "", mcp=local.call)

    async def request():
        local.bind_loop(asyncio.get_running_loop())
        with caller_scope(AGENT):
            return await handlers[SHOT_UPDATE]({"version": 1, "input": {"workspace": "show", "production_id": "p", "shot": "s1"}})

    assert asyncio.run(request())["result"]["file"] == "edited.mp4"
    assert seen == ["agent", "server"]


def _mcp_app(tmp_path, recorded):
    operations = [{"name": name, "description": name, "mutation": mutation, "inputSchema": {
        "type": "object", "properties": {"version": {"const": 1}, "input": {"type": "object"}}, "required": ["version", "input"]}}
        for name, mutation in (("demo.save", True), ("demo.read", False))]
    seen = []

    async def save(arguments):
        seen.append(is_external_agent())
        return {"status": "completed", "result": {"name": "demo.scene.json", "editor": "video2d"}}
    app = FastAPI()
    app.include_router(create_wangp_mcp_router(
        handlers={"demo.save": save, "demo.read": lambda arguments: {"status": "completed"}},
        journal_path=tmp_path / "requests.sqlite3", token_getter=lambda: "token", command_operations=operations,
        profiles={"test": {"tools": ["demo.save", "demo.read"]}},
        on_mutation=lambda name, arguments, result: recorded.append((name, is_external_agent(), result["result"]["name"]))))
    return app, seen


def _call(client, name, headers=None, path="/api/v1/mcp"):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": {"version": 1, "input": {}}}}
    response = client.post(path, json=body, headers={"Authorization": "Bearer token", **(headers or {})})
    assert response.status_code == 200
    return json.loads(response.json()["result"]["content"][0]["text"])


@pytest.mark.parametrize("path", ["/api/v1/mcp", "/api/v1/mcp/test"])
def test_the_mcp_endpoint_reports_mutations_from_outside_clients_only(tmp_path, path):
    recorded = []
    app, seen = _mcp_app(tmp_path, recorded)
    with TestClient(app) as client:
        _call(client, "demo.save", path=path)
        _call(client, "demo.read", path=path)
        _call(client, "demo.save", {"X-Hocus-Caller": "production", "X-Hocus-Actor": "server"}, path=path)
    assert seen == [True, True]  # an external client cannot declare itself a server job
    assert recorded == [("demo.save", True, "demo.scene.json"), ("demo.save", True, "demo.scene.json")]
    activity_calls = []

    class Spy(AgentActivity):
        def _record(self, name, arguments, result):
            activity_calls.append(name)
    spy = Spy(lambda workspace: None, lambda: "show")
    with caller_scope({**AGENT, "internal": "production"}):
        spy.record("demo.save", {}, {"status": "completed"})
    with caller_scope(AGENT):
        spy.record("demo.save", {}, {"status": "completed"})
    assert activity_calls == ["demo.save"]


def test_recording_never_breaks_the_tool_call(tmp_path):
    def broken(_workspace):
        raise OSError("disk full")
    activity = AgentActivity(broken, lambda: "show")
    with caller_scope(AGENT):
        activity.record("scenes.document.save", {"input": {"workspace": "show"}}, {"result": {"name": "a.scene.json", "editor": "video2d"}})


def test_async_handlers_keep_the_scope_across_the_threadpool():
    from starlette.concurrency import run_in_threadpool

    async def main():
        with caller_scope(AGENT):
            return await run_in_threadpool(is_external_agent)
    assert asyncio.run(main()) is True
