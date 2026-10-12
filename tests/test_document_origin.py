"""Who saved a scene or a comic, and who created a series record."""
import ast
import base64
import copy
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.agent_activity import SERVER_CALLER, ActorHeaderMiddleware, caller_scope, external_caller
from services.document_origin import series_author, write_document_origin
from services.output_origin import output_origin
from services.scene_documents import save_document
from services.scene_library import save_world3d
from tests.test_output_completion_time import list_test_outputs

ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"
TINY_PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\npreview").decode()
SCENE_2D = {
    "version": 1, "name": "Plaza", "width": 64, "height": 36, "fps": 24, "duration": 0.25,
    "layers": [{"id": "bg", "name": "bg", "type": "image", "source": "/api/v1/file/bg.png?workspace=default",
                "visible": True, "z": 0, "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1},
                "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1},
                              "duration": 1, "curve": "ease"}}],
}
SCENE_3D = {
    "version": 1, "units": "meters", "up": "y", "width": 64, "height": 64, "fps": 30, "duration": 2 / 30,
    "templateId": "two-shot", "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
    "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
    "slots": [{"id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0, "scale": 1,
               "sourceUrl": "", "media": "model3d", "clip": None}],
}


def _workspace(tmp_path):
    return lambda _workspace: str(tmp_path)


def _sidecar(folder: Path, name: str) -> dict:
    return json.loads((folder / name).with_suffix(".meta.json").read_text(encoding="utf-8"))


def _save_scene_output(tmp_path):
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    node = copy.deepcopy(next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == "save_scene_output"))
    node.decorator_list = []
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"HTTPException": HTTPException, "base64": base64, "json": json, "os": __import__("os"),
                 "time": __import__("time"), "uuid": __import__("uuid"),
                 "_workspace_dir": lambda workspace=None: str(tmp_path)}
    exec(compile(module, str(LAUNCH), "exec"), namespace)
    return namespace["save_scene_output"]


def test_agent_and_wizard_documents_join_made_by_agents_and_a_person_does_not(tmp_path):
    folder = _workspace(tmp_path)
    with caller_scope(external_caller("sol")):
        scene = save_document("default", SCENE_2D, name="plaza", preview=None, workspace_dir=folder)
        world = save_document("default", SCENE_3D, name="duelo", preview=None, workspace_dir=folder,
                              capability="world3d.scene.publish")
        caller = {**external_caller(), "command_id": "cmd-9"}
    with caller_scope(caller):
        direct = save_world3d({"workspace": "default", "document": SCENE_3D, "name": "direct", "preview": TINY_PNG}, folder)
    mine = save_document("default", SCENE_2D, name="mine", preview=None, workspace_dir=folder)
    with caller_scope(SERVER_CALLER):
        server = save_document("default", SCENE_2D, name="render", preview=None, workspace_dir=folder)

    scene_meta = _sidecar(tmp_path, scene["name"])
    assert scene_meta["origin"] == {"actor": "agent", "tool": "external_agent", "capability": "scenes.document.save"}
    assert scene_meta["requested_by"]["tool"] == "external_agent"
    assert scene_meta["requested_by"]["mcp_profile"] == "sol"
    assert _sidecar(tmp_path, world["name"])["origin"]["capability"] == "world3d.scene.publish"
    direct_meta = _sidecar(tmp_path, direct["name"])
    assert direct_meta["command_id"] == "cmd-9" and direct_meta["requested_by"]["capability"] == "scenes.world3d.save"
    assert not (tmp_path / mine["name"]).with_suffix(".meta.json").exists()
    assert not (tmp_path / server["name"]).with_suffix(".meta.json").exists()

    names = {item["name"] for item in list_test_outputs(tmp_path, origin="agent")}
    assert {scene["name"], world["name"], direct["name"]} <= names
    assert mine["name"] not in names and server["name"] not in names
    assert output_origin(scene_meta) == {"actor": "agent", "capability": "scenes.document.save"}
    listed = {item["name"]: item["origin"] for item in list_test_outputs(tmp_path)}
    assert listed[mine["name"]] is None
    mcp = {item["name"] for item in list_test_outputs(tmp_path, origin="mcp")}
    assert scene["name"] in mcp and mine["name"] not in mcp


def test_a_wizard_http_save_is_listed_and_a_person_keeps_an_existing_origin(tmp_path):
    from routers.comics import create_comics_router
    from routers.scene_commands import create_scene_commands_router
    from types import SimpleNamespace

    app = FastAPI()
    app.add_middleware(ActorHeaderMiddleware)
    app.include_router(create_scene_commands_router(SimpleNamespace(workspace_dir=_workspace(tmp_path))))
    app.include_router(create_comics_router(
        workspace_dir=lambda workspace=None: str(tmp_path), get_active_workspace=lambda: "default",
        safe_join=lambda base, *parts: str(Path(base, *parts)) if ".." not in parts else None,
        get_services_config=lambda: {}, publish_legacy_task=None,
    ))
    client = TestClient(app)
    project = {"version": 2, "id": "comic-1", "title": "Salt", "pages": [{"id": "p1"}], "assets": {}}
    wizard = client.post("/api/v1/scenes/world3d", headers={"X-Hocus-UI-Surface": "wizard"}, json={
        "workspace": "default", "document": SCENE_3D, "name": "wizard-shot", "preview": TINY_PNG})
    assert wizard.status_code == 200, wizard.text
    wizard_meta = _sidecar(tmp_path, wizard.json()["name"])
    assert wizard_meta["origin"]["actor"] == "wizard" and "requested_by" not in wizard_meta
    assert wizard.json()["name"] in {item["name"] for item in list_test_outputs(tmp_path, origin="wizard")}
    assert wizard.json()["name"] not in {item["name"] for item in list_test_outputs(tmp_path, origin="mcp")}
    assert wizard.json()["name"] in {item["name"] for item in list_test_outputs(tmp_path, origin="agent")}

    created = client.post("/api/v1/comics", headers={"X-Hocus-Actor": "agent"}, json={"project": project, "preview": TINY_PNG})
    assert created.status_code == 200, created.text
    name = created.json()["name"]
    sidecar = tmp_path / name.replace(".comic.json", ".comic.meta.json")
    assert sidecar.is_file() and output_origin(json.loads(sidecar.read_text()))["actor"] == "agent"
    original = sidecar.read_text(encoding="utf-8")
    updated = client.put(f"/api/v1/comics/{name}", json={"project": {**project, "title": "Revised"}})
    assert updated.status_code == 200
    assert sidecar.read_text(encoding="utf-8") == original
    with caller_scope({"surface": "loopback", "internal": "loopback", "actor": "wizard"}):
        assert write_document_origin(tmp_path / name, "comics.save") is False
    assert json.loads(sidecar.read_text())["origin"]["capability"] == "comics.save"
    assert name in {item["name"] for item in list_test_outputs(tmp_path, origin="agent")}


def test_a_layer_scene_save_uses_the_same_origin(tmp_path):
    save = _save_scene_output(tmp_path)
    body = {"scene": {"version": 1, "name": "Plaza", "layers": []}, "preview": TINY_PNG}
    with caller_scope({"surface": "loopback", "internal": "loopback", "actor": "wizard"}):
        saved = save(body)
    assert _sidecar(tmp_path, saved["name"])["origin"] == {"actor": "wizard", "tool": "wizard", "capability": "scenes.save"}
    person = save(body)
    assert not (tmp_path / person["name"]).with_suffix(".meta.json").exists()


def test_series_records_name_their_author_only_when_created():
    from services.series_library import (
        create_series_episode, create_series_project, duplicate_series_project, import_story_project,
        normalize_series_project, series_put_payload, update_series_episode,
    )
    from services.series_templates import build_series, list_templates

    with caller_scope(external_caller()):
        series = create_series_project("default", title="Night")
        episode = create_series_episode(series, createdBy={"actor": "user", "tool": "series", "capability": "forged"})
        built = build_series(list_templates()[0]["id"], "default")
    assert series["createdBy"] == {"actor": "agent", "tool": "external_agent", "capability": "series.create"}
    assert episode["createdBy"]["actor"] == "agent" and episode["createdBy"]["capability"] == "series.episode.create"
    assert built["createdBy"]["actor"] == "agent"
    assert next(iter(built["episodesById"].values()))["createdBy"]["capability"] == "series.episode.create"

    old = create_series_project()
    old.pop("createdBy")
    assert series_author(normalize_series_project(old, old["id"], "default")) is None
    old["createdBy"] = "wizard"
    assert "createdBy" not in normalize_series_project(old, old["id"], "default")

    current = create_series_project()
    current["episodesById"][episode["id"]] = episode
    sent = copy.deepcopy(current)
    sent["title"] = "Renamed"
    sent["createdBy"] = {"actor": "wizard", "tool": "wizard", "capability": "forged"}
    sent["episodesById"][episode["id"]]["createdBy"] = {"actor": "wizard", "tool": "wizard"}
    sent["episodesById"]["episode_new"] = {"id": "episode_new", "title": "Extra", "createdBy": {"actor": "agent", "tool": "external_agent"}}
    payload = series_put_payload(current, sent)
    assert payload["createdBy"]["actor"] == "user" and payload["title"] == "Renamed"
    assert payload["episodesById"][episode["id"]]["createdBy"]["actor"] == "agent"
    assert "createdBy" not in payload["episodesById"]["episode_new"]
    bare = copy.deepcopy(current)
    bare.pop("createdBy")
    forged = copy.deepcopy(bare)
    forged["createdBy"] = {"actor": "agent", "tool": "external_agent"}
    assert "createdBy" not in series_put_payload(bare, forged)

    series["episodesById"][episode["id"]] = episode
    edited = update_series_episode(
        series, episode["id"], {"title": "Renamed", "createdBy": {"actor": "wizard", "tool": "wizard"}},
        base_series_revision=series["revision"],
    )
    assert edited["episodesById"][episode["id"]]["title"] == "Renamed"
    assert edited["episodesById"][episode["id"]]["createdBy"]["capability"] == "series.episode.create"

    with caller_scope({"surface": "loopback", "internal": "loopback", "actor": "wizard"}):
        imported = import_story_project({"title": "Tale"})
        copied = duplicate_series_project(series)
    assert imported["createdBy"] == {"actor": "wizard", "tool": "wizard", "capability": "series.import"}
    assert copied["createdBy"]["capability"] == "series.duplicate"
    assert normalize_series_project(copied, copied["id"], "default")["createdBy"]["actor"] == "wizard"


def test_a_posted_series_cannot_choose_its_author(tmp_path):
    from routers.series_library import _bind_series_library_runtime, create_series_library_router
    from services.series_library import create_series_episode, create_series_project, read_series_library, write_series_library

    folder = tmp_path / "library"
    folder.mkdir()
    _bind_series_library_runtime(
        resolve_workspace=lambda value: value or "default", library_lock=__import__("threading").RLock(),
        read_library=lambda workspace: read_series_library(str(folder), workspace),
        write_library=lambda workspace, value: write_series_library(str(folder), value, workspace),
        project_or_404=lambda current, series_id: current["seriesById"][series_id],
    )
    app = FastAPI()
    app.add_middleware(ActorHeaderMiddleware)
    app.include_router(create_series_library_router())
    client = TestClient(app)
    series = create_series_project("default", title="Forged")
    episode = create_series_episode(series)
    series["episodesById"] = {episode["id"]: episode}
    series["seasons"][0]["episodeOrder"] = [episode["id"]]
    series["createdBy"] = {"actor": "agent", "tool": "external_agent", "capability": "forged"}
    series["episodesById"][episode["id"]]["createdBy"] = {"actor": "wizard", "tool": "wizard", "capability": "forged"}
    made = client.post("/api/v1/series", json={"workspace": "default", "series": series})
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["createdBy"] == {"actor": "user", "tool": "series", "capability": "series.create"}
    stored = next(iter(body["episodesById"].values()))["createdBy"]
    assert stored == {"actor": "user", "tool": "series", "capability": "series.episode.create"}

    series["id"] = "series_by_agent"
    agent = client.post("/api/v1/series", headers={"X-Hocus-Actor": "agent"}, json={"workspace": "default", "series": series})
    assert agent.status_code == 200, agent.text
    assert agent.json()["createdBy"]["actor"] == "agent"
    assert agent.json()["createdBy"]["tool"] == "external_agent"
    assert next(iter(agent.json()["episodesById"].values()))["createdBy"]["actor"] == "agent"


def test_other_language_lines_an_agent_writes_are_marked_until_a_person_checks_them():
    from routers.series_language_versions import create_series_language_versions_router
    from tests.test_series_language_versions import series as series_fixture

    store = {"series": series_fixture()}

    def change(_workspace, _series_id, episode_id, apply):
        current = store["series"]
        apply(current, current["episodesById"][episode_id])
        return copy.deepcopy(current)

    app = FastAPI()
    app.add_middleware(ActorHeaderMiddleware)
    app.include_router(create_series_language_versions_router(
        change_episode=change, read_episode=lambda *_args: (store["series"], store["series"]["episodesById"]["ep1"]),
        translate=lambda *_args: {"title": "", "lines": [], "cards": []}))
    client = TestClient(app)
    path = "/api/v1/series/uv/episodes/ep1/language-versions/english"
    written = client.put(path, headers={"X-Hocus-Actor": "agent"}, json={"workspace": "cast", "version": {
        "title": "Pilot", "dialogue": {"b2": "Hi!", "b1": "  "},
        "cards": {"s0": {"title": "", "body": "One"}}, "music": {"s1": "theme.wav"}}})
    assert written.status_code == 200, written.text
    marks = written.json()["version"]["machineTranslated"]
    assert marks["dialogue"] == ["b2"] and marks["cards"] == ["s0"] and marks["title"] is True
    assert marks["requestedBy"] == "agent" and "music" not in marks

    cleared = client.put(path, json={"workspace": "cast", "version": {"dialogue": {"b2": "Hello"}}})
    kept = cleared.json()["version"]["machineTranslated"]
    assert "b2" not in kept["dialogue"] and kept["title"] is True and kept["cards"] == ["s0"]

    server = client.put(path, headers={"X-Hocus-Actor": "server"}, json={"workspace": "cast", "version": {"dialogue": {"b1": "Okay"}}})
    untouched = server.json()["version"]["machineTranslated"]
    assert untouched["dialogue"] == [] and untouched["title"] is True and "b1" not in untouched["dialogue"]

    wizard = client.put(path, headers={"X-Hocus-UI-Surface": "wizard"}, json={"workspace": "cast", "version": {"dialogue": {"b1": "Okay, Gary."}}})
    assert wizard.json()["version"]["machineTranslated"]["requestedBy"] == "wizard"
    assert "b1" in wizard.json()["version"]["machineTranslated"]["dialogue"]
