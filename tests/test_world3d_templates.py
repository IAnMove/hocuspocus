"""MCP, Wizard HTTP and the production planner share the Video 3D shot library."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import shutil
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from routers.wangp_mcp import create_wangp_mcp_router
from routers.world3d_templates import create_world3d_templates_router
from services.production_plan import PlanError, plan_brief
from services.production_scene3d import validate_scene3d_shot
from services.world3d_scenes import inspect_scene, patch_scene
from services.world3d_template_catalog import World3DTemplateError, builtin_cards, search_templates
from services.world3d_template_commands import command_catalog, command_handlers, execute_command

ROOT = Path(__file__).resolve().parents[1]
ROBOT = "/api/v1/file/robot.glb?workspace=studio"
ROOM = "/api/v1/file/room.png?workspace=studio"
needs_ui = pytest.mark.skipif(
    not (ROOT / "ui/node_modules/tsx/dist/loader.mjs").is_file(),
    reason="UI dependencies not installed in Python-only CI",
)


def client_for(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    app = FastAPI()
    app.include_router(create_world3d_templates_router(root))
    app.include_router(create_wangp_mcp_router(handlers=command_handlers(root), command_operations=command_catalog(),
        journal_path=str(tmp_path / "journal.json"), token_getter=lambda: "test-token"))
    return TestClient(app), root


def post(client, name, data, intent=None, *, mcp=False):
    arguments = {"version": 1, "input": {"workspace": "studio", **data}, **({"intent_id": intent} if intent else {})}
    if mcp:
        return client.post("/api/v1/mcp", headers={"Authorization": "Bearer test-token"}, json={"jsonrpc": "2.0", "id": 1,
            "method": "tools/call", "params": {"name": name, "arguments": arguments}})
    return client.post("/api/v1/world3d/templates/commands", json={"operation": name, **arguments})


def call(client, name, data, intent=None, *, mcp=False):
    response = post(client, name, data, intent, mcp=mcp)
    assert response.status_code == 200, response.text
    body = response.json()
    if not mcp:
        return body
    payload = body["result"]
    assert payload.get("isError") is not True, payload
    return payload["structuredContent"]


def _brief(**extra):
    brief = {
        "tema": "HocusPocus", "publico": "makers", "duracion": "48 seconds", "musica": "bright pop 120 BPM",
        "estilo": "anime product musical", "protagonista": "a friendly inventor", "cta": "Try the studio",
        "limites": "no real people",
        "lyrics": "[Verse]\nA small inventor wakes up\nThe desk is full of light\n[Chorus]\nTry the studio now\n",
    }
    brief.update(extra)
    return brief


def _scene_files(root):
    folder = Path(root("studio")) / "world3d-edits"
    return list(folder.glob("w3d-*.json")) if folder.is_dir() else []


@needs_ui
def test_catalog_matches_the_editor_library_and_keeps_scenarios():
    node = shutil.which("node")
    loader = ROOT / "ui/node_modules/tsx/dist/loader.mjs"
    result = subprocess.run([node, "--import", str(loader), "scripts/export-world3d-catalog.mjs", "--check"],
                            cwd=ROOT / "ui", capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    cards = list(builtin_cards())
    ids = {card["id"] for card in cards}
    assert {"cine-dolly-zoom", "cine-orbit-360", "cine-rain"} <= ids
    assert any(str(card["id"]).startswith("atmos-") for card in cards)
    assert any(card.get("format") == "portrait" for card in cards)
    assert any(card.get("category") != "cinema" for card in cards)
    assert "ok" in result.stdout


def test_search_is_bounded_bilingual_and_rejects_a_bad_limit():
    empty = search_templates("")
    assert len(empty) == 8
    assert empty[0]["id"] == "topdown-dragon-portals"
    assert search_templates("dolly zoom", limit=1)[0]["id"] == "cine-dolly-zoom"
    assert search_templates("lluvia", limit=1)[0]["id"] == "cine-rain"
    assert search_templates("rain", language="es", limit=1)[0]["id"] == "cine-rain"
    zoom = search_templates("zoom", limit=4)
    assert zoom[0]["id"] == "cine-zoom"
    around = search_templates("girar alrededor")
    assert len(around) > 1 and around[0]["score"] == around[1]["score"]
    assert "cine-orbit-360" in {card["id"] for card in around}
    with pytest.raises(World3DTemplateError) as limited:
        search_templates("zoom", limit=25)
    assert limited.value.code == "invalid_limit"
    with pytest.raises(World3DTemplateError) as language:
        search_templates("zoom", language="fr")
    assert language.value.code == "invalid_language"


def test_search_keeps_templates_that_take_a_cast_and_a_painted_set():
    fit = search_templates("baile", roles=["subject_1", "background"], limit=24)
    assert fit and all({"subject_1", "background"} <= set(card["roles"]) for card in fit)
    sea = search_templates("", roles=["background"], setting="Sea", limit=24)
    assert sea and all(card["setting"] == "sea" for card in sea)
    assert search_templates("", roles=["subject_2", "background"], setting="moon") == [
        card for card in search_templates("", setting="moon") if {"subject_2", "background"} <= set(card["roles"])]
    with pytest.raises(World3DTemplateError) as bad:
        search_templates("", roles="background")
    assert bad.value.code == "invalid_roles"


def test_list_filters_by_role_and_setting_over_mcp(tmp_path):
    client, _root = client_for(tmp_path)
    page = call(client, "world3d.templates.list", {"roles": ["subject_1", "background"], "setting": "city"}, mcp=True)["result"]
    assert page["total"] == len([card for card in builtin_cards() if card.get("setting") == "city"
                                 and {"subject_1", "background"} <= set(card.get("roles") or ())])
    assert page["templates"] and all(card["setting"] == "city" for card in page["templates"])


def test_mutation_without_intent_is_rejected(tmp_path):
    client, root = client_for(tmp_path)
    response = post(client, "world3d.scene.apply_query", {"query": "dolly zoom"})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "intent_conflict"
    assert _scene_files(root) == []


def test_unknown_id_is_not_the_first_template(tmp_path):
    client, _root = client_for(tmp_path)
    response = post(client, "world3d.templates.get", {"template_id": "nope"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "unknown_template"
    assert "topdown-dragon-portals" not in response.text
    assert _scene_files(_root) == []


def test_list_and_catalog_match_over_http_and_mcp(tmp_path):
    client, _root = client_for(tmp_path)
    tools = client.post("/api/v1/mcp", headers={"Authorization": "Bearer test-token"}, json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "world3d.templates.catalog" in names
    assert "world3d.scene.apply_query" in names
    http = call(client, "world3d.templates.list", {"query": "dolly zoom", "limit": 3})
    catalog = call(client, "world3d.templates.catalog", {"query": "dolly zoom", "limit": 3})
    mcp = call(client, "world3d.templates.list", {"query": "dolly zoom", "limit": 3}, mcp=True)
    assert http["result"]["templates"][0]["id"] == "cine-dolly-zoom"
    assert [card["id"] for card in http["result"]["templates"]] == [card["id"] for card in catalog["result"]["templates"]]
    assert [card["id"] for card in mcp["result"]["templates"]] == [card["id"] for card in http["result"]["templates"]]


@needs_ui
def test_robot_request_discovers_applies_adapts_and_stays_editable(tmp_path):
    client, root = client_for(tmp_path)
    http = call(client, "world3d.scene.apply_query", {"query": "dolly zoom"}, "robot-http")
    mcp = call(client, "world3d.scene.apply_query", {"query": "dolly zoom"}, "robot-mcp", mcp=True)
    assert http["status"] == "completed"
    assert http["result"]["chosenId"] == mcp["result"]["chosenId"] == "cine-dolly-zoom"
    left, right = http["result"]["scene"], mcp["result"]["scene"]
    assert left["traits"]["playbackSpeed"] == right["traits"]["playbackSpeed"] == 1
    assert left["traits"]["fovTo"] == right["traits"]["fovTo"]
    assert isinstance(left["traits"]["fovTo"], (int, float))
    assert left["traits"]["roles"] == right["traits"]["roles"]
    assert left["sceneId"] != right["sceneId"]
    subject = next(item for item in left["objects"] if item["role"] == "subject_1")
    background = next(item for item in left["objects"] if item["role"] == "background")
    assert subject["marker"] is True and subject["finished"] is False
    assert "GLB" in next(item["requirements"] for item in left["pending"] if item["id"] == subject["id"])
    before = call(client, "world3d.scene.preview", {"scene_id": left["sceneId"]})
    bound = call(client, "world3d.scene.patch", {
        "scene_id": left["sceneId"], "base_revision": left["revision"],
        "bindings": [
            {"object_id": subject["id"], "source_url": ROBOT, "clip": {"index": 0, "name": "Idle"}},
            {"objectId": background["id"], "sourceUrl": ROOM},
        ],
    }, "robot-bind")
    subject_after = next(item for item in bound["result"]["scene"]["objects"] if item["id"] == subject["id"])
    background_after = next(item for item in bound["result"]["scene"]["objects"] if item["id"] == background["id"])
    assert subject_after["finished"] is True and subject_after["sourceUrl"] == ROBOT
    assert subject_after["clip"]["name"] == "Idle"
    assert background_after["sourceUrl"] == ROOM
    assert bound["result"]["scene"]["traits"]["fovTo"] == left["traits"]["fovTo"]
    assert bound["result"]["scene"]["traits"]["targetSlot"] == subject["id"]
    unverified = call(client, "world3d.scene.patch", {
        "scene_id": left["sceneId"], "base_revision": bound["result"]["scene"]["revision"],
        "bindings": [{"objectId": subject["id"], "sourceUrl": ROBOT}],
    }, "robot-clip")
    assert any(item.startswith(f"clip_unverified:{subject['id']}:Idle") for item in unverified["result"]["scene"]["warnings"])
    assert next(item for item in unverified["result"]["scene"]["objects"] if item["id"] == subject["id"])["clip"]["name"] == "Idle"
    same_pixels = call(client, "world3d.scene.preview", {"scene_id": left["sceneId"], "expected_revision": unverified["result"]["scene"]["revision"]})
    assert [frame["sha256"] for frame in same_pixels["result"]["frames"]] == [frame["sha256"] for frame in before["result"]["frames"]]
    assert all(item["id"] != subject["id"] for item in same_pixels["result"]["pending"])
    cleared = call(client, "world3d.scene.patch", {
        "scene_id": left["sceneId"], "base_revision": unverified["result"]["scene"]["revision"],
        "bindings": [{"objectId": subject["id"], "clips": ["Walk"]}],
    }, "robot-clip-clear")
    assert any(item.startswith("incompatible_clip:") for item in cleared["result"]["scene"]["warnings"])
    assert next(item for item in cleared["result"]["scene"]["objects"] if item["id"] == subject["id"])["clip"] is None
    assert cleared["result"]["scene"]["traits"]["fovTo"] == left["traits"]["fovTo"]
    saved = call(client, "world3d.scene.publish", {"scene_id": left["sceneId"]}, "robot-publish")
    opened = saved["result"]["scene"]
    assert opened["file"].endswith(".scene.json")
    assert opened["document"]["templateId"] == "cine-dolly-zoom"
    assert opened["document"]["playbackSpeed"] == 1
    assert opened["document"]["camera"]["framing"]["fovTo"] == left["traits"]["fovTo"]
    assert {slot["sourceUrl"] for slot in opened["document"]["slots"]} >= {ROBOT, ROOM}
    assert opened["traits"]["templateId"] == "cine-dolly-zoom"
    widened = call(client, "world3d.scene.patch", {
        "scene_id": left["sceneId"], "base_revision": cleared["result"]["scene"]["revision"],
        "camera": {"fov": 12},
    }, "robot-fov")
    changed = call(client, "world3d.scene.preview", {"scene_id": left["sceneId"]})
    assert [frame["sha256"] for frame in changed["result"]["frames"]] != [frame["sha256"] for frame in before["result"]["frames"]]
    held = call(client, "world3d.scene.patch", {
        "scene_id": left["sceneId"], "base_revision": widened["result"]["scene"]["revision"],
        "camera": {"family": "establishment", "eye": [0, 2, 6], "fov": 28},
    }, "robot-hold")
    held_preview = call(client, "world3d.scene.preview", {"scene_id": left["sceneId"]})
    moved = [subject["position"][0] + 3, subject["position"][1], subject["position"][2]]
    call(client, "world3d.scene.patch", {
        "scene_id": left["sceneId"], "base_revision": held["result"]["scene"]["revision"],
        "bindings": [{"objectId": subject["id"], "position": moved}],
    }, "robot-move")
    moved_preview = call(client, "world3d.scene.preview", {"scene_id": left["sceneId"]})
    assert [frame["sha256"] for frame in moved_preview["result"]["frames"]] != [frame["sha256"] for frame in held_preview["result"]["frames"]]
    stale = post(client, "world3d.scene.patch", {"scene_id": left["sceneId"], "base_revision": 1, "bindings": []}, "robot-stale")
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    preview = post(client, "world3d.scene.preview", {"scene_id": left["sceneId"]}, mcp=True)
    content = preview.json()["result"]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image" and content[1]["mimeType"] == "image/png" and content[1]["data"]
    replay = call(client, "world3d.scene.apply_query", {"query": "dolly zoom"}, "robot-http")
    assert replay["replayed"] is True
    assert replay["result"]["scene"]["sceneId"] == left["sceneId"]
    receipt = call(client, "world3d.receipt", {"operation": "world3d.scene.apply_query", "intent_id": "robot-http"})
    assert receipt["result"]["scene"]["sceneId"] == left["sceneId"]
    conflict = post(client, "world3d.scene.apply_query", {"query": "lluvia"}, "robot-http")
    assert conflict.status_code == 409


def test_ambiguous_query_creates_nothing_and_a_retry_stays_empty(tmp_path):
    client, root = client_for(tmp_path)
    choice = call(client, "world3d.scene.apply_query", {"query": "girar alrededor"}, "orbit-choice")
    assert choice["status"] == "needs_choice"
    assert choice["result"]["scene"] is None
    assert choice["result"]["chosenId"] is None
    assert len(choice["result"]["candidates"]) > 1
    assert _scene_files(root) == []
    again = call(client, "world3d.scene.apply_query", {"query": "girar alrededor"}, "orbit-choice")
    assert again["replayed"] is True
    assert again["result"]["scene"] is None
    assert _scene_files(root) == []
    missing = post(client, "world3d.scene.apply_query", {"query": "xyzzy-no-such-shot"}, "missing-shot")
    assert missing.status_code == 200
    assert missing.json()["status"] == "not_found"
    assert _scene_files(root) == []


@needs_ui
def test_transport_retry_does_not_duplicate_the_scene(tmp_path):
    _client, root = client_for(tmp_path)
    args = {"version": 1, "intent_id": "same", "input": {"workspace": "studio", "query": "dolly zoom"}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: execute_command("world3d.scene.apply_query", deepcopy(args), root), range(2)))
    assert sorted(reply.get("replayed", False) for reply in replies) == [False, True]
    assert replies[0]["result"]["scene"]["sceneId"] == replies[1]["result"]["scene"]["sceneId"]
    assert len(_scene_files(root)) == 1
    with pytest.raises(HTTPException) as conflict:
        execute_command("world3d.scene.apply_query", {"version": 1, "intent_id": "same", "input": {"workspace": "studio", "query": "lluvia"}}, root)
    assert conflict.value.status_code == 409


@needs_ui
def test_one_prop_bind_leaves_the_other_prop_and_a_two_shot_keeps_both_holes(tmp_path):
    client, _root = client_for(tmp_path)
    sea = call(client, "world3d.scene.instantiate", {"template_id": "dark-still-salt-sea"}, "sea")["result"]["scene"]
    props = [item for item in sea["objects"] if item["role"] == "prop"]
    assert {item["id"] for item in props} >= {"near-prop", "exterior-video"}
    refused = post(client, "world3d.scene.patch", {"scene_id": sea["sceneId"], "base_revision": sea["revision"],
        "bindings": [{"role": "prop", "sourceUrl": ROOM}]}, "sea-role")
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "ambiguous_role"
    bound = call(client, "world3d.scene.patch", {"scene_id": sea["sceneId"], "base_revision": sea["revision"],
        "bindings": [{"objectId": "near-prop", "sourceUrl": ROOM}]}, "sea-one")["result"]["scene"]
    by_id = {item["id"]: item for item in bound["objects"]}
    assert by_id["near-prop"]["sourceUrl"] == ROOM
    assert by_id["exterior-video"]["sourceUrl"] == ""
    assert by_id["exterior-video"]["marker"] is True
    pair = call(client, "world3d.scene.instantiate", {"template_id": "two-shot"}, "pair")["result"]["scene"]
    assert pair["traits"]["roles"] == ["subject_1", "subject_2", "background"]
    assert {item["role"] for item in pair["pending"]} >= {"subject_1", "subject_2"}
    hero = next(item for item in pair["objects"] if item["role"] == "subject_1")
    patched = call(client, "world3d.scene.patch", {"scene_id": pair["sceneId"], "base_revision": pair["revision"],
        "bindings": [{"role": "subject_1", "sourceUrl": ROBOT}]}, "pair-one")["result"]["scene"]
    other = next(item for item in patched["objects"] if item["role"] == "subject_2")
    assert other["sourceUrl"] == "" and other["marker"] is True
    assert next(item for item in patched["objects"] if item["id"] == hero["id"])["sourceUrl"] == ROBOT


def test_screen_binding_writes_nested_source_url(tmp_path):
    workspace_dir = lambda workspace: str(tmp_path / workspace)
    scene_id = "w3d-ab12cd34ef56"
    demo = "/examples/dark-stillness/still-sea.mp4"
    document = {
        "templateId": "dark-still-salt-sea",
        "slots": [{
            "id": "exterior-video", "slot": "prop", "media": "screen", "sourceUrl": "",
            "clip": None, "position": [0, 0, 0], "rotationY": 0, "scale": 1,
            "screen": {"sourceUrl": demo, "media": "video", "mode": "mesh", "targetMesh": "SCREEN_CONTENT"},
        }],
        "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]},
    }
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    (folder / f"{scene_id}.json").write_text(json.dumps({
        "revision": 1, "templateId": "dark-still-salt-sea", "document": document, "warnings": [],
    }), encoding="utf-8")
    viewed = patch_scene("studio", scene_id, workspace_dir, {
        "bindings": [{"object_id": "exterior-video", "source_url": ROOM, "source_ref": {"name": "room.png"}}],
    }, 1)
    slot = viewed["document"]["slots"][0]
    assert slot["screen"]["sourceUrl"] == ROOM
    assert slot["screen"]["sourceRef"] == {"name": "room.png"}
    assert slot["sourceUrl"] == ROOM
    assert viewed["objects"][0]["finished"] is True
    moved = patch_scene("studio", scene_id, workspace_dir, {
        "bindings": [{"objectId": "exterior-video", "position": [1, 0, 0]}],
    }, viewed["revision"])
    assert moved["document"]["slots"][0]["screen"]["sourceUrl"] == ROOM
    assert moved["document"]["slots"][0]["position"] == [1, 0, 0]
    stored = inspect_scene("studio", scene_id, workspace_dir)
    assert stored["document"]["slots"][0]["screen"]["sourceUrl"] == ROOM


def test_screen_binding_creates_screen_when_missing(tmp_path):
    workspace_dir = lambda workspace: str(tmp_path / workspace)
    scene_id = "w3d-ffffffffffff"
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    (folder / f"{scene_id}.json").write_text(json.dumps({
        "revision": 1, "templateId": "bare-screen", "warnings": [],
        "document": {
            "templateId": "bare-screen",
            "slots": [{"id": "billboard", "slot": "prop", "media": "screen", "sourceUrl": ""}],
            "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]},
        },
    }), encoding="utf-8")
    viewed = patch_scene("studio", scene_id, workspace_dir, {
        "bindings": [{"objectId": "billboard", "sourceUrl": ROOM}],
    }, 1)
    assert viewed["document"]["slots"][0]["screen"]["sourceUrl"] == ROOM


@needs_ui
def test_screen_slot_patch_replaces_the_texture_url(tmp_path):
    client, _root = client_for(tmp_path)
    sea = call(client, "world3d.scene.instantiate", {"template_id": "dark-still-salt-sea"}, "sea-screen")["result"]["scene"]
    before = next(slot for slot in sea["document"]["slots"] if slot["id"] == "exterior-video")
    assert before["media"] == "screen"
    assert before["sourceUrl"] == ""
    assert before["screen"]["sourceUrl"] == "/examples/dark-stillness/still-sea.mp4"
    bound = call(client, "world3d.scene.patch", {
        "scene_id": sea["sceneId"], "base_revision": sea["revision"],
        "bindings": [{"objectId": "exterior-video", "sourceUrl": ROOM}],
    }, "sea-screen-bind")["result"]["scene"]
    after = next(slot for slot in bound["document"]["slots"] if slot["id"] == "exterior-video")
    assert after["screen"]["sourceUrl"] == ROOM
    assert after["sourceUrl"] == ROOM
    assert next(item for item in bound["objects"] if item["id"] == "exterior-video")["sourceUrl"] == ROOM


@needs_ui
def test_personal_template_is_distinct_and_does_not_replace_a_builtin(tmp_path):
    client, root = client_for(tmp_path)
    document = call(client, "world3d.templates.get", {"template_id": "product-orbit"})["result"]["document"]
    stored = call(client, "world3d.templates.user.put", {"id": "user-robot", "title": "Robot propio", "description": "presentación", "document": document}, "user-robot")
    assert stored["result"]["template"]["source"] == "workspace"
    call(client, "world3d.templates.user.put", {"id": "user-extra", "title": "Extra", "document": document}, "user-extra")
    rows = json.loads((Path(root("studio")) / "world3d-user-templates.json").read_text(encoding="utf-8"))["templates"]
    assert {row["id"] for row in rows} == {"user-robot", "user-extra"}
    found = call(client, "world3d.templates.list", {"query": "Robot propio", "limit": 4})["result"]["templates"]
    assert found[0]["id"] == "user-robot" and found[0]["source"] == "workspace"
    scene = call(client, "world3d.scene.instantiate", {"template_id": "user-robot"}, "user-scene")["result"]["scene"]
    assert scene["templateId"] == "user-robot"
    assert scene["document"]["templateId"] == "user-robot"
    refused = post(client, "world3d.templates.user.put", {"id": "cine-dolly-zoom", "title": "Nope", "document": document}, "user-builtin")
    assert refused.status_code == 422
    assert refused.json()["detail"]["code"] == "invalid_user_template"


def test_planner_uses_a_real_id_and_refuses_a_tie():
    spec = plan_brief(_brief(world3d="dolly zoom", world3d_subject=ROBOT))
    shot = spec["shots"][0]
    assert shot["kind"] == "scene3d"
    assert shot["scene3d"]["template"] == "cine-dolly-zoom"
    assert shot["scene3d"]["subject"] == ROBOT
    assert shot["t1"] == 5
    assert spec["world3d_template"] == "cine-dolly-zoom"
    validate_scene3d_shot(shot)
    with pytest.raises(PlanError) as tied:
        plan_brief(_brief(toma="girar alrededor"))
    assert tied.value.code == "ambiguous_template"
    with pytest.raises(PlanError) as missing:
        plan_brief(_brief(world3d="xyzzy-no-such-shot"))
    assert missing.value.code == "unknown_template"
    plain = plan_brief(_brief())
    assert "world3d_template" not in plain
    assert all(item.get("kind") != "scene3d" for item in plain["shots"])


def test_a_scene_patch_sets_the_scene_sound_and_keeps_talk_tracks(tmp_path):
    from services.world3d_scenes import World3DSceneError
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"templateId": "dark-still-salt-sea", "slots": [], "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]},
                "soundtrack": [{"id": "talk-elon-0", "audio": {"url": "/api/v1/file/ln.wav?workspace=studio", "filename": "ln.wav", "workspaceId": "studio"},
                                "start": 0.8, "offset": 0, "gain": 1}]}
    (folder / "w3d-0000abcd1234.json").write_text(json.dumps({"revision": 1, "templateId": "dark-still-salt-sea", "document": document, "warnings": []}), encoding="utf-8")
    viewed = patch_scene("studio", "w3d-0000abcd1234", workspace_dir, {"soundtrack": [
        {"id": "scene-ambience", "audio": "/api/v1/file/amb/wind.wav?workspace=studio", "start": 0, "gain": 0.3}]}, 1)
    tracks = viewed["document"]["soundtrack"]
    assert [track["id"] for track in tracks] == ["talk-elon-0", "scene-ambience"]
    assert tracks[1] == {"id": "scene-ambience", "audio": {"url": "/api/v1/file/amb/wind.wav?workspace=studio", "filename": "wind.wav", "workspaceId": "studio"},
                         "start": 0.0, "offset": 0, "gain": 0.3}
    again = patch_scene("studio", "w3d-0000abcd1234", workspace_dir, {"soundtrack": [
        {"id": "scene-music", "audio": "/api/v1/file/theme.wav?workspace=studio", "start": 2, "gain": 1}]}, 2)
    assert [track["id"] for track in again["document"]["soundtrack"]] == ["talk-elon-0", "scene-music"], "scene tracks are replaced, talk stays"
    for bad in ([{"id": "talk-x", "audio": "/api/v1/file/a.wav", "start": 0, "gain": 1}],
                [{"id": "scene-x", "audio": "https://evil.example/a.wav", "start": 0, "gain": 1}],
                [{"id": "scene-x", "audio": "/api/v1/file/a.wav", "start": 0, "gain": 7}], "nope"):
        with pytest.raises(World3DSceneError):
            patch_scene("studio", "w3d-0000abcd1234", workspace_dir, {"soundtrack": bad}, 3)


def test_a_scene_patch_sets_merges_and_clears_the_render_look(tmp_path):
    from services.world3d_scenes import World3DSceneError
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"templateId": "two-shot", "slots": [], "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]}}
    (folder / "w3d-00000000700e.json").write_text(json.dumps({"revision": 1, "templateId": "two-shot", "document": document, "warnings": []}), encoding="utf-8")
    viewed = patch_scene("studio", "w3d-00000000700e", workspace_dir, {"renderLook": "toon", "toon": {"steps": 2, "ink": "#AA0000"}}, 1)
    assert viewed["document"]["renderLook"] == "toon"
    assert viewed["document"]["toon"] == {"steps": 2, "ink": "#aa0000"}
    assert viewed["traits"]["renderLook"] == "toon"
    assert {"renderLook", "toon"} <= set(viewed["editable"])
    merged = patch_scene("studio", "w3d-00000000700e", workspace_dir, {"toon": {"outline": 4.5}}, 2)
    assert merged["document"]["toon"] == {"steps": 2, "ink": "#aa0000", "outline": 4.5}
    cleared = patch_scene("studio", "w3d-00000000700e", workspace_dir, {"renderLook": "none"}, 3)
    assert "renderLook" not in cleared["document"]
    assert cleared["document"]["toon"]["steps"] == 2, "settings stay for the next time the look is chosen"
    for bad in ({"renderLook": "cel"}, {"toon": {"steps": 5}}, {"toon": {"outline": -1}}, {"toon": {"ink": "black"}},
                {"toon": {"width": 2}}, {"toon": "thick"}, {"toon": {"steps": True}}):
        with pytest.raises(World3DSceneError) as caught:
            patch_scene("studio", "w3d-00000000700e", workspace_dir, bad, 4)
        assert caught.value.code == "invalid_render_look"
    assert inspect_scene("studio", "w3d-00000000700e", workspace_dir)["revision"] == 4


def test_the_patch_tool_documents_the_render_look():
    patch = next(item for item in command_catalog() if item["name"] == "world3d.scene.patch")
    fields = patch["inputSchema"]["properties"]["input"]["properties"]
    assert fields["renderLook"]["enum"] == ["none", "n64", "toon"]
    assert set(fields["toon"]["properties"]) == {"steps", "outline", "ink"}
    assert fields["toon"]["additionalProperties"] is False


def test_a_patch_adds_an_animated_prop_and_stretches_the_template_cues_to_the_new_length(tmp_path):
    from services.world3d_scenes import World3DSceneError
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"templateId": "dark-still-salt-sea", "duration": 8,
                "slots": [{"id": "hero", "slot": "subject_1", "media": "model3d", "sourceUrl": "", "clip": None, "position": [0, 0, 0],
                           "rotationY": 0, "scale": 1, "appearance": {"start": 2, "duration": 1, "color": "#fff"},
                           "clips": [{"clip": {"index": 0, "name": "Run"}, "start": 4, "duration": 2, "offset": 0.5}]}],
                "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]},
                "sfx": [{"id": "flash", "kind": "impact_flash", "start": 4, "end": 4.4}],
                "worldSfx": [{"id": "boom", "kind": "explosion", "start": 6, "end": 8, "motion": [{"time": 6, "scale": 1}, {"time": 8, "scale": 2}]}],
                "texts": [{"id": "title", "text": "BAM", "start": 1, "end": 3}],
                "soundtrack": [{"id": "scene-music", "start": 2, "offset": 0, "gain": 1, "audio": {"url": "/api/v1/file/m.wav?workspace=studio"}}]}
    (folder / "w3d-0000abcd5678.json").write_text(json.dumps({"revision": 1, "templateId": "dark-still-salt-sea", "document": document, "warnings": []}), encoding="utf-8")
    viewed = patch_scene("studio", "w3d-0000abcd5678", workspace_dir, {"duration": 4, "retime": True, "bindings": [
        {"object_id": "ship", "add": True, "source_url": ROBOT, "clip": {"index": 1, "name": "Fly"},
         "clipPlayback": {"speed": 1.5, "start": 0, "loop": True}, "position": [0, 3, -8], "motion": {"to": [6, 3, -8], "faceTravel": True}},
        {"object_id": "poster", "add": True, "media": "image", "source_url": ROOM}]}, 1)
    out = viewed["document"]
    assert (out["sfx"][0]["start"], out["sfx"][0]["end"]) == (2.0, 2.2)
    assert (out["worldSfx"][0]["start"], [frame["time"] for frame in out["worldSfx"][0]["motion"]]) == (3.0, [3.0, 4.0])
    assert (out["texts"][0]["start"], out["texts"][0]["end"]) == (0.5, 1.5)
    hero = out["slots"][0]
    assert hero["appearance"]["start"] == 1.0 and hero["clips"][0] == {"clip": {"index": 0, "name": "Run"}, "start": 2.0, "duration": 1.0, "offset": 0.5}
    assert out["soundtrack"][0]["start"] == 2, "the caller places the soundtrack"
    ship, poster = out["slots"][1], out["slots"][2]
    assert (ship["slot"], ship["media"], ship["sourceUrl"], ship["clip"]["name"], ship["clipPlayback"]["speed"]) == ("prop", "model3d", ROBOT, "Fly", 1.5)
    assert ship["motion"] == {"to": [6, 3, -8], "faceTravel": True} and ship["position"] == [0, 3, -8]
    assert (poster["media"], poster["surface"], poster["sourceUrl"]) == ("image", "cutout", ROOM)
    again = patch_scene("studio", "w3d-0000abcd5678", workspace_dir, {"duration": 4, "retime": True, "bindings": [
        {"object_id": "ship", "add": True, "scale": 2}]}, 2)
    assert len(again["document"]["slots"]) == 3 and again["document"]["slots"][1]["scale"] == 2, "adding an existing id binds it"
    assert again["document"]["sfx"][0]["start"] == 2.0, "the same length does not stretch again"
    plain = patch_scene("studio", "w3d-0000abcd5678", workspace_dir, {"duration": 8}, 3)
    assert plain["document"]["sfx"][0]["start"] == 2.0, "without retime the cues keep their seconds"
    for bad in ({"object_id": "x", "add": True, "media": "screen"}, {"add": True, "media": "model3d"}):
        with pytest.raises(World3DSceneError):
            patch_scene("studio", "w3d-0000abcd5678", workspace_dir, {"bindings": [bad]}, 4)


ANIME_IDS = ["anime-speedline-charge", "anime-impact-frame", "anime-snap-zoom", "anime-sword-clash",
             "anime-face-off", "anime-airship-flyby", "anime-fleet-approach", "anime-eyecatch", "anime-code-rain"]


def test_anime_shots_are_searchable_cards_with_bindable_objects():
    cards = {card["id"]: card for card in builtin_cards()}
    assert set(ANIME_IDS) <= set(cards)
    for template_id in ANIME_IDS:
        card = cards[template_id]
        assert card["tags"] == ["anime"]
        assert card["width"] == 1920 and card["height"] == 1080 and 2.5 <= card["duration"] <= 6
        assert {item["id"] for item in card["required"]} >= {"background"}
    fleet = cards["anime-fleet-approach"]["required"]
    ships = [item for item in fleet if item["media"] == "model3d"]
    assert [item["id"] for item in ships] == ["vehicle_1", "vehicle_2", "vehicle_3", "vehicle_4"]
    assert {item["role"] for item in ships} == {"prop"}
    assert {item["id"]: item["media"] for item in cards["anime-sword-clash"]["required"]} == {
        "subject": "image", "rival": "image", "background": "image"}
    assert search_templates("impact frame", limit=1)[0]["id"] == "anime-impact-frame"
    assert search_templates("eyecatch", limit=1)[0]["id"] == "anime-eyecatch"
    assert search_templates("code rain", limit=1)[0]["id"] == "anime-code-rain"
    assert {item["id"]: item["media"] for item in cards["anime-code-rain"]["required"]} == {"subject": "image", "background": "image"}
    assert {card["id"] for card in search_templates("anime", limit=24)} >= set(ANIME_IDS)


def test_a_camera_patch_sets_shake_and_rejects_a_bad_window(tmp_path):
    from services.world3d_scenes import World3DSceneError
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"templateId": "anime-impact-frame", "slots": [],
                "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]}}
    (folder / "w3d-00000000beef.json").write_text(json.dumps({"revision": 1, "templateId": "anime-impact-frame", "document": document,
                                                                 "warnings": []}), encoding="utf-8")
    shake = [{"start": 1.25, "end": 2.6, "amplitude": 0.09, "frequency": 20, "seed": 7, "decay": 3.2}]
    viewed = patch_scene("studio", "w3d-00000000beef", workspace_dir, {"camera": {"shake": shake}}, 1)
    assert viewed["document"]["camera"]["shake"] == shake
    assert viewed["document"]["camera"]["fov"] == 40
    for bad in ("no", [{"start": 2, "end": 1, "amplitude": 0.1, "frequency": 10}], [{"start": 0, "end": 1, "amplitude": 3, "frequency": 10}],
                [{"start": 0, "end": 1, "amplitude": 0.1, "frequency": 10, "seed": 1.5}], [{"start": 0, "end": 1, "amplitude": 0.1}],
                [{"start": 0, "end": 1, "amplitude": 0.1, "frequency": 10, "roll": 2}], [shake[0]] * 17):
        with pytest.raises(World3DSceneError) as error:
            patch_scene("studio", "w3d-00000000beef", workspace_dir, {"camera": {"shake": bad}}, 2)
        assert error.value.code == "invalid_camera_shake"
    assert inspect_scene("studio", "w3d-00000000beef", workspace_dir)["revision"] == 2
    cleared = patch_scene("studio", "w3d-00000000beef", workspace_dir, {"camera": {"shake": []}}, 2)
    assert cleared["document"]["camera"]["shake"] == []


def test_retime_stretches_shake_windows_and_backdrop_cues(tmp_path):
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"templateId": "anime-impact-frame", "duration": 3, "slots": [],
                "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0],
                           "shake": [{"start": 1.25, "end": 2.6, "amplitude": 0.09, "frequency": 20, "decay": 3}]},
                "screenBackdrop": {"color": "#251a3c", "sfx": [{"id": "lines", "kind": "speedlines", "start": 1.25, "end": 2.6}]}}
    (folder / "w3d-0000feedbeef.json").write_text(json.dumps({"revision": 1, "templateId": "anime-impact-frame", "document": document,
                                                                 "warnings": []}), encoding="utf-8")
    out = patch_scene("studio", "w3d-0000feedbeef", workspace_dir, {"duration": 6, "retime": True}, 1)["document"]
    shake = out["camera"]["shake"][0]
    assert (shake["start"], shake["end"], shake["decay"], shake["amplitude"]) == (2.5, 5.2, 1.5, 0.09)
    assert (out["screenBackdrop"]["sfx"][0]["start"], out["screenBackdrop"]["sfx"][0]["end"]) == (2.5, 5.2)
    kept = patch_scene("studio", "w3d-0000feedbeef", workspace_dir, {"duration": 3}, 2)["document"]
    assert kept["camera"]["shake"][0]["start"] == 2.5, "without retime the windows keep their seconds"


def test_a_patch_puts_the_shot_screen_effects_over_the_template_ones(tmp_path):
    from services.world3d_scenes import World3DSceneError
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"templateId": "two-shot", "slots": [], "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]},
                "sfx": [{"id": "template-lines", "kind": "speed_lines", "start": 0, "end": 2}]}
    (folder / "w3d-0000000fx001.json").write_text(json.dumps({"revision": 1, "templateId": "two-shot", "document": document, "warnings": []}), encoding="utf-8")
    viewed = patch_scene("studio", "w3d-0000000fx001", workspace_dir, {"screenFx": [
        {"id": "shot-fx-0", "kind": "manga_impact", "start": 1.2, "end": 1.6, "x": 40, "y": 30, "size": 25, "rotation": -150, "color": "#ffffff"}]}, 1)
    effects = viewed["document"]["sfx"]
    assert [cue["id"] for cue in effects] == ["template-lines", "shot-fx-0"]
    assert effects[1] == {"id": "shot-fx-0", "kind": "manga_impact", "start": 1.2, "end": 1.6, "x": 40.0, "y": 30.0, "size": 25.0,
                          "rotation": -150.0, "color": "#ffffff"}
    again = patch_scene("studio", "w3d-0000000fx001", workspace_dir, {"screenFx": [
        {"id": "shot-fx-1", "kind": "laser", "start": 1, "end": 1.3, "x": 90, "y": 20, "from": {"x": 70, "y": 40}}]}, 2)
    assert again["document"]["sfx"][1]["from"] == {"x": 70.0, "y": 40.0}, "a beam from a point of the frame"
    again = patch_scene("studio", "w3d-0000000fx001", workspace_dir, {"screenFx": []}, 3)
    assert [cue["id"] for cue in again["document"]["sfx"]] == ["template-lines"], "the shot's effects are replaced, the template's stay"
    for bad in ([{"id": "fx-0", "kind": "manga_impact", "start": 0, "end": 1}], [{"id": "shot-x", "kind": "nope", "start": 0, "end": 1}],
                [{"id": "shot-x", "kind": "manga_impact", "start": 2, "end": 1}], [{"id": "shot-x", "kind": "manga_impact", "start": 0, "end": 1, "x": 400}],
                [{"id": "shot-x", "kind": "laser", "start": 0, "end": 1, "from": {"x": 70}}],
                [{"id": "shot-x", "kind": "laser", "start": 0, "end": 1, "from": {"x": 70, "y": 900}}],
                [{"id": "shot-x", "kind": "manga_impact", "start": 0, "end": 1, "from": {"x": 70, "y": 40}}]):
        with pytest.raises(World3DSceneError) as caught:
            patch_scene("studio", "w3d-0000000fx001", workspace_dir, {"screenFx": bad}, 4)
        assert caught.value.code == "invalid_screen_fx"


def test_a_voice_over_ducks_the_music_like_a_talking_object_and_replaces_the_previous_one(tmp_path):
    from services.world3d_scenes import World3DSceneError
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"templateId": "two-shot", "slots": [], "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]},
                "soundtrack": [{"id": "scene-music", "start": 0, "offset": 0, "gain": 0.5, "audio": {"url": "/api/v1/file/m.wav?workspace=studio"}}]}
    (folder / "w3d-0000000v0ce1.json").write_text(json.dumps({"revision": 1, "templateId": "two-shot", "document": document, "warnings": []}), encoding="utf-8")
    viewed = patch_scene("studio", "w3d-0000000v0ce1", workspace_dir, {"voiceOver": [
        {"audio": "/api/v1/file/narrator.wav?workspace=studio", "start": 0.4}, {"audio": "/api/v1/file/radio.wav?workspace=studio", "start": 2.5, "gain": 0.8}]}, 1)
    tracks = viewed["document"]["soundtrack"]
    assert [track["id"] for track in tracks] == ["scene-music", "talk-voiceover-0", "talk-voiceover-1"], "talk-* tracks duck the music"
    assert (tracks[1]["start"], tracks[2]["gain"]) == (0.4, 0.8)
    again = patch_scene("studio", "w3d-0000000v0ce1", workspace_dir, {"voiceOver": [{"audio": "/api/v1/file/n2.wav?workspace=studio", "start": 1}]}, 2)
    assert [track["id"] for track in again["document"]["soundtrack"]] == ["scene-music", "talk-voiceover-0"]
    for bad in ("nope", [{"audio": "https://evil.example/a.wav", "start": 0}], [{"start": 0}] * 25):
        with pytest.raises(World3DSceneError):
            patch_scene("studio", "w3d-0000000v0ce1", workspace_dir, {"voiceOver": bad}, 3)


def test_a_patch_binds_a_clip_sequence_a_hand_hold_and_an_appearance_and_refuses_bad_ones(tmp_path):
    from services.world3d_scenes import World3DSceneError
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    slot = lambda slot_id, media="model3d", **more: {"id": slot_id, "slot": "prop", "media": media, "sourceUrl": ROBOT, "clip": None,
                                                     "position": [0, 0, 0], "rotationY": 0, "scale": 1, **more}
    document = {"templateId": "dark-still-salt-sea", "duration": 6, "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]},
                "slots": [slot("hero", clip={"index": 0, "name": "Idle"}), slot("wall", "image", surface="wall")]}
    record = {"revision": 1, "templateId": "dark-still-salt-sea", "document": document, "warnings": []}
    (folder / "w3d-0000abcd9999.json").write_text(json.dumps(record), encoding="utf-8")
    rifle = {"object_id": "rifle", "add": True, "source_url": ROBOT, "scale": 0.19,
             "hold": {"carrier": "guard", "hand": "right", "offset": [0, 0.02, 0.05], "rotation": [-1.65, 0.11, 2.76]}}
    guard = {"object_id": "guard", "add": True, "source_url": ROBOT, "appearance": {"start": 0.5},
             "clips": [{"clip": {"index": 4, "name": "Aim"}, "start": 1.5, "fade": 0.4, "loop": False}, {"clip": {"index": 0, "name": "Idle"}, "start": 0}]}
    viewed = patch_scene("studio", "w3d-0000abcd9999", workspace_dir, {"bindings": [rifle, guard]}, 1)
    slots = {item["id"]: item for item in viewed["document"]["slots"]}
    assert slots["rifle"]["hold"] == {"carrier": "guard", "hand": "right", "offset": [0.0, 0.02, 0.05], "rotation": [-1.65, 0.11, 2.76]}, \
        "a carrier added later in the same patch counts"
    assert slots["guard"]["clips"] == [{"clip": {"index": 0, "name": "Idle"}, "start": 0.0},
                                       {"clip": {"index": 4, "name": "Aim"}, "start": 1.5, "fade": 0.4, "loop": False}]
    assert slots["guard"]["appearance"] == {"start": 0.5, "duration": 0.9, "color": "#83e8ff"}
    objects = {item["id"]: item for item in viewed["objects"]}
    assert objects["rifle"]["hold"]["carrier"] == "guard" and "clips" in objects["guard"] and "hold" not in objects["hero"]
    assert {"clips", "hold", "appearance"} <= set(viewed["editable"])
    legacy = patch_scene("studio", "w3d-0000abcd9999", workspace_dir, {"bindings": [{"object_id": "hero", "clips": ["Walk"]}]}, 2)
    hero = next(item for item in legacy["document"]["slots"] if item["id"] == "hero")
    assert hero["clip"] is None and "clips" not in hero and legacy["warnings"] == ["incompatible_clip:hero:Idle"], "clip names are the old check"
    released = patch_scene("studio", "w3d-0000abcd9999", workspace_dir, {"bindings": [{"object_id": "rifle", "hold": None},
                                                                                       {"object_id": "guard", "clips": None, "appearance": None}]}, 3)
    slots = {item["id"]: item for item in released["document"]["slots"]}
    assert not {"hold", "clips", "appearance"} & (set(slots["rifle"]) | set(slots["guard"]))
    bad = [({"object_id": "rifle", "hold": {"carrier": "ghost", "hand": "right"}}, "unknown_carrier", "(models: hero, guard)"),
           ({"object_id": "rifle", "hold": {"carrier": "wall", "hand": "right"}}, "unknown_carrier", "'wall'"),
           ({"object_id": "rifle", "hold": {"carrier": "rifle", "hand": "right"}}, "invalid_hold", "cannot hold itself"),
           ({"object_id": "rifle", "hold": {"carrier": "hero", "hand": "both"}}, "invalid_hold", "left or right"),
           ({"object_id": "rifle", "hold": {"carrier": "hero", "hand": "left", "rotation": [0, 0, 7]}}, "invalid_hold", "radians"),
           ({"object_id": "wall", "hold": {"carrier": "hero", "hand": "left"}}, "invalid_hold", "can be held"),
           ({"object_id": "wall", "clips": [{"clip": {"index": 0, "name": "Idle"}, "start": 0}]}, "invalid_clips", "model3d"),
           ({"object_id": "hero", "clips": [{"clip": "Idle", "start": 0}]}, "invalid_clips", "clips[0].clip must be {index, name}"),
           ({"object_id": "hero", "clips": [{"clip": {"index": 0, "name": "Idle"}}]}, "invalid_clips", "clips[0].start"),
           ({"object_id": "hero", "clips": [{"clip": {"index": 0, "name": "Idle"}, "start": 0}, "Run"]}, "invalid_clips", "clips[1]"),
           ({"object_id": "hero", "appearance": {"start": 1, "color": "blue"}}, "invalid_appearance", "#rrggbb")]
    for binding, code, text in bad:
        with pytest.raises(World3DSceneError) as raised:
            patch_scene("studio", "w3d-0000abcd9999", workspace_dir, {"bindings": [binding]}, 4)
        assert raised.value.code == code and text in str(raised.value), (binding, raised.value.code, str(raised.value))
    assert inspect_scene("studio", "w3d-0000abcd9999", workspace_dir)["revision"] == 4, "a refused patch writes nothing"


def test_stop_motion_is_saved_in_the_published_scene_file_and_zero_takes_it_off(tmp_path):
    """motionStep and stopMotionJitter sit at the top of the document like playbackSpeed, so the scene file opens with them."""
    import jsonschema
    from services.scene_documents import get_document
    from services.world3d_scenes import World3DSceneError, publish_scene
    workspace_dir = lambda name: str(tmp_path / name)
    folder = Path(workspace_dir("studio")) / "world3d-edits"
    folder.mkdir(parents=True)
    document = {"version": 1, "units": "meters", "up": "y", "duration": 4, "width": 1280, "height": 720, "fps": 24, "templateId": "two-shot",
                "slots": [], "camera": {"family": "fixed", "fov": 40, "eye": [0, 1, 5], "look": [0, 1, 0]}, "light": {"preset": "studio"}}
    (folder / "w3d-00000000700f.json").write_text(json.dumps({"revision": 1, "templateId": "two-shot", "document": document, "warnings": []}), encoding="utf-8")
    patch = {"motionStep": 3, "stopMotionJitter": 1.5}
    schema = next(item for item in command_catalog() if item["name"] == "world3d.scene.patch")["inputSchema"]
    jsonschema.validate({"version": 1, "intent_id": "held", "input": {"workspace": "studio", "scene_id": "w3d-00000000700f", "base_revision": 1, **patch}}, schema)
    viewed = patch_scene("studio", "w3d-00000000700f", workspace_dir, patch, 1)
    assert {"motionStep", "stopMotionJitter"} <= set(viewed["editable"])
    published = publish_scene("studio", "w3d-00000000700f", workspace_dir)
    opened = get_document("studio", published["file"], workspace_dir=workspace_dir)["document"]
    assert (opened["motionStep"], opened["stopMotionJitter"]) == (3, 1.5)
    cleared = patch_scene("studio", "w3d-00000000700f", workspace_dir, {"motionStep": 0, "stopMotionJitter": 0}, 2)["document"]
    assert "motionStep" not in cleared and "stopMotionJitter" not in cleared
    for bad in ({"motionStep": 5}, {"stopMotionJitter": 3}, {"motionStep": True}):
        with pytest.raises(World3DSceneError, match="motionStep must be 2, 3 or 4|stopMotionJitter must be from 0 to 2"):
            patch_scene("studio", "w3d-00000000700f", workspace_dir, bad, 3)
