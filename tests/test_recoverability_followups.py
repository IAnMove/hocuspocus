"""What agents and the Wizard make stays findable, openable and attributed (docs/development/MCP_RECOVERABILITY.md)."""
import asyncio
import json
import shutil
import struct
import time
import wave
import zlib
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from routers.series_produce import create_series_produce_router
from routers.wizard_activity import create_wizard_activity_router
from routers.world3d_templates import create_world3d_templates_router
from services import series_commands
from services.agent_activity import (
    SERVER_CALLER, ActorHeaderMiddleware, AgentActivity, actor_label, artifact_targets, caller_scope, current_actor,
)
from services.montage_commands import MontageCommands
from services.montage_documents import MontageStore, montage_link
from services.production_shot_review import apply_artistic, record_decision, verdict_source
from services.readable_names import ascii_slug, keep_last_label
from services.scene2d_export import OPERATION as EXPORT_2D, Scene2DExportService, command_handlers as export_2d_handlers
from services.scene_documents import save_document
from services.scene_links import INDEX, needs_preview, preview_from_frames, preview_path, saved_scene_for
from services.series_jobs import SeriesJobStore
from services.series_language_versions import set_version_take
from services.series_library import approve_episode_render_attempts, approve_shot_render_attempt, reject_shot_render_attempt
from services.series_produce import ProduceDeps, SeriesProduce
from services.task_manager import TaskRegistry
from services.tool_sidecars import rig_sidecars
from services.world3d_export import write_png
from services.world3d_scenes import publish_scene, working_scenes

AGENT = {"surface": "mcp", "tool": "external_agent"}
WORKSPACE = "show"


def _folder(tmp_path):
    def workspace_dir(name):
        path = Path(tmp_path) / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return workspace_dir


def _activity(tmp_path):
    registries = {}
    workspace_dir = _folder(tmp_path)

    def registry_for(workspace):
        if workspace not in registries:
            registries[workspace] = TaskRegistry(workspace_dir(workspace))
        return registries[workspace]
    return AgentActivity(registry_for, lambda: WORKSPACE), registry_for


def _png(width, height, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


# 1. Wizard rows in Activity ------------------------------------------------------------------------------------------

def test_a_wizard_change_without_a_job_becomes_its_own_trail_row(tmp_path):
    activity, registry_for = _activity(tmp_path)
    series = {"kind": "series_episode", "id": "ep1", "series": "pu-es", "title": "Plus Ultra · La confesión"}
    activity.record_wizard(WORKSPACE, "create_series_episode", [series], "cmd-1")
    activity.record_wizard(WORKSPACE, "update_series_episode", [series], "cmd-2")
    activity.record_wizard(WORKSPACE, "create_story", [{"kind": "story", "id": "story-1", "title": "El faro"}])
    assert activity.record_wizard(WORKSPACE, "open_tab", [{"kind": "application_section", "id": "x"}]) is None
    assert activity.record_wizard(WORKSPACE, "create_story", [{"kind": "file", "id": "a", "file": "../escape.png"}]) is None
    rows = {task["title"]: task for task in registry_for(WORKSPACE).list(limit=20) if task["kind"] == "agent"}
    episode = rows["Wizard · Plus Ultra · La confesión"]
    assert episode["metadata"]["tool"] == "wizard" and episode["metadata"]["actor"] == "wizard"
    assert episode["metadata"]["operations"] == {"create_series_episode": 1, "update_series_episode": 1}
    assert episode["metadata"]["targets"] == [series]
    assert episode["id"].startswith("task-wizard-")
    assert rows["Wizard · El faro"]["metadata"]["targets"][0]["kind"] == "story"
    # The Agents view (origin=agent) lists the Wizard's rows.
    tasks, _ = registry_for(WORKSPACE).snapshot(statuses={"completed"}, origin="agent")
    assert {task["id"] for task in tasks} >= {episode["id"]}


def test_an_agent_and_the_wizard_keep_separate_rows_for_the_same_kit(tmp_path):
    activity, registry_for = _activity(tmp_path)
    with caller_scope(AGENT):
        activity.record("characters.save", {"input": {"workspace": WORKSPACE}}, {"result": {"character": {"id": "ines", "name": "Inés"}}})
    activity.record_wizard(WORKSPACE, "update_character_kit", [{"kind": "character_kit", "id": "ines", "title": "Inés"}])
    titles = sorted(task["title"] for task in registry_for(WORKSPACE).list(limit=10) if task["kind"] == "agent")
    assert titles == ["Agent · Inés", "Wizard · Inés"]


def test_the_wizard_change_route_records_and_refuses_bad_input(tmp_path):
    activity, registry_for = _activity(tmp_path)
    app = FastAPI()
    app.include_router(create_wizard_activity_router(activity))
    client = TestClient(app)
    body = {"workspace": WORKSPACE, "capability": "create_character_kit", "commandId": "c1",
            "targets": [{"kind": "character_kit", "id": "rayo", "title": "Rayo"}]}
    recorded = client.post("/api/v1/tasks/wizard-changes", json=body)
    assert recorded.status_code == 200 and recorded.json()["recorded"] is True
    assert recorded.json()["task"]["metadata"]["command_id"] == "c1"
    assert client.post("/api/v1/tasks/wizard-changes", json={**body, "workspace": "../x"}).status_code == 422
    assert client.post("/api/v1/tasks/wizard-changes", json={**body, "targets": []}).status_code == 422
    ignored = client.post("/api/v1/tasks/wizard-changes", json={**body, "targets": [{"kind": "studio_form", "id": "x"}]})
    assert ignored.json() == {"recorded": False, "task": None}


def test_a_saved_montage_is_a_montage_target_named_after_its_document():
    saved = artifact_targets({"input": {"workspace": WORKSPACE}}, {"result": {"file": "cierre.montage.json", "revision": 2}})
    assert saved == [{"kind": "montage", "id": "cierre.montage.json", "file": "cierre.montage.json"}]
    opened = artifact_targets({}, {"result": {"file": "cierre.montage.json", "montage": {"name": "Cierre", "clips": []}}})
    assert opened == [{"kind": "montage", "id": "cierre.montage.json", "file": "cierre.montage.json", "title": "Cierre"}]


# 7. Who approved ------------------------------------------------------------------------------------------------------

def test_the_actor_header_reaches_the_route_scope():
    app = FastAPI()
    app.add_middleware(ActorHeaderMiddleware)

    @app.get("/who")
    def who():
        return {"actor": current_actor(), "label": actor_label()}

    client = TestClient(app)
    assert client.get("/who").json() == {"actor": "user", "label": "user"}
    assert client.get("/who", headers={"X-Hocus-Actor": "agent"}).json() == {"actor": "agent", "label": "agent"}
    assert client.get("/who", headers={"X-Hocus-Actor": "server"}).json() == {"actor": "server", "label": "user"}
    assert client.get("/who", headers={"X-Hocus-UI-Surface": "wizard"}).json() == {"actor": "wizard", "label": "wizard"}
    assert client.get("/who", headers={"X-Hocus-Actor": "admin"}).json()["actor"] == "user"


def test_series_loopback_calls_say_who_they_are_for(tmp_path):
    seen = []

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return b'{"id": "s1", "approvedAttemptId": "a1", "attempts": []}'

    def opener(request, timeout):
        seen.append(request.get_header("X-hocus-actor"))
        return Reply()

    handlers = series_commands.command_handlers(lambda: "http://127.0.0.1:1", _folder(tmp_path), lambda: str(tmp_path), opener=opener)
    arguments = {"version": 1, "input": {"workspace": WORKSPACE, "series_id": "s", "episode_id": "e", "shot_id": "s1", "attempt_id": "a1"}}
    asyncio.run(handlers["series.take.approve"](arguments))
    with caller_scope(AGENT):
        asyncio.run(handlers["series.take.approve"](arguments))
    with caller_scope(SERVER_CALLER):
        asyncio.run(handlers["series.take.approve"](arguments))
    with caller_scope({"surface": "wizard", "internal": "wizard"}):
        asyncio.run(handlers["series.take.approve"](arguments))
    assert seen == [None, "agent", "server", "wizard"]


def _shot():
    return {"id": "s1", "attempts": [{"id": "a1", "status": "completed", "outputAssetIds": ["v1"]},
                                     {"id": "a2", "status": "completed", "outputAssetIds": ["v2"]}]}


def test_take_approvals_record_who_approved():
    approved = approve_shot_render_attempt(_shot(), "a1", "agent")
    take = approved["attempts"][0]
    assert approved["approvedAttemptId"] == "a1"
    assert take["approvedBy"] == "agent" and take["reviewedBy"] == "agent" and take["approvedAt"] == take["reviewedAt"]
    assert approve_shot_render_attempt(_shot(), "a1")["attempts"][0]["approvedBy"] == "user"
    assert approve_shot_render_attempt(_shot(), "a1", "someone")["attempts"][0]["approvedBy"] == "user"
    bulk = approve_episode_render_attempts({"shots": [_shot()]}, [{"shotId": "s1", "attemptId": "a2"}], "wizard")
    assert bulk["shots"][0]["attempts"][1]["approvedBy"] == "wizard"
    rejected = reject_shot_render_attempt(approved, "a2", "server")
    assert rejected["attempts"][1]["reviewDecision"] == "rejected" and rejected["attempts"][1]["reviewedBy"] == "server"
    episode = {"shots": [_shot()], "languageVersions": {"english": {"approvedAttemptIds": {}}}}
    set_version_take(episode, "english", "s1", "a2", "server", now="2026-10-06T10:00:00Z")
    assert episode["languageVersions"]["english"]["approvedAttemptIds"] == {"s1": "a2"}
    take = episode["shots"][0]["attempts"][1]
    assert (take["approvedBy"], take["approvedLanguage"], take["approvedAt"]) == ("server", "english", "2026-10-06T10:00:00Z")


def test_production_reviews_record_who_decided_and_the_verdict_says_whose(tmp_path):
    record_decision(tmp_path, "p", "s0", status="approved")
    summary = {"review": {"artistic": {"verdict": "pending"}}}
    assert apply_artistic(summary, tmp_path, "p")["review"]["artistic"]["source"] == "human"
    with caller_scope(AGENT):
        decided = record_decision(tmp_path, "p", "s1", status="approved")
    assert decided["decidedBy"] == "agent"
    assert apply_artistic(summary, tmp_path, "p")["review"]["artistic"]["source"] == "mixed"
    body = json.loads((tmp_path / "p.review.json").read_text())
    assert body["shots"]["s0"]["decidedBy"] == "user" and isinstance(body["shots"]["s1"]["decidedAt"], float)
    assert verdict_source({"shots": {"a": {"status": "approved", "decidedBy": "wizard"}}}) == "agent"
    assert verdict_source({"shots": {"a": {"status": "approved"}}}) == "human"  # reviews made before decidedBy existed
    # Locking or a note keeps the decider of the decision.
    record_decision(tmp_path, "p", "s1", locked=True)
    assert json.loads((tmp_path / "p.review.json").read_text())["shots"]["s1"]["decidedBy"] == "agent"


# 4. Readable export names ----------------------------------------------------------------------------------------------

def test_export_labels_keep_the_shot_id_and_fold_accents():
    assert ascii_slug("Más allá del Plan") == "Mas-alla-del-Plan"
    assert keep_last_label("Plus Ultra: Más allá del Plan · La confesión · e1s163") == "Plus-Ultra-Mas-alla-del-Plan-La-confesion-e1s163"
    long = keep_last_label("Una serie con un título larguísimo de verdad · Un episodio también muy largo · e1s04", 40)
    assert long.endswith("-e1s04") and len(long) <= 40 and long.startswith("Una-serie")
    assert "-Un-" in long or "-Un" in long
    assert keep_last_label("Intro") == "Intro" and keep_last_label("") == ""
    service = Scene2DExportService(workspace_dir=_folder("/tmp"), registry_for=lambda _name: None)
    name = service.output_name({"document": {"name": "Plus Ultra: Más allá del Plan · La confesión · e1s163"}})
    assert "_video2d-Plus-Ultra-Mas-alla-del-Plan-La-confesion-e1s163_" in name


# 5. Montage exports name their montage ---------------------------------------------------------------------------------

def test_a_montage_export_names_the_montage_it_came_from(tmp_path):
    store = MontageStore(_folder(tmp_path))
    clip = tmp_path / WORKSPACE / "a.mp4"
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"x")
    saved = store.save(WORKSPACE, {"version": 1, "name": "Cierre", "width": 640, "height": 360, "fps": 30,
                                   "clips": [{"source": "/api/v1/file/a.mp4?workspace=show", "name": "a.mp4"}]})
    started = []
    commands = MontageCommands(store, start_export=lambda body: started.append(body) or {"job_id": "j"}, get_export=lambda _id: {})
    commands.execute("montages.export", {"version": 1, "input": {"workspace": WORKSPACE, "file": saved["file"]}})
    assert started[0]["montage"] == {"file": "Cierre.montage.json", "revision": 1}
    assert montage_link(started[0]["montage"]) == {"file": "Cierre.montage.json", "revision": 1}
    assert montage_link({"file": "../x.montage.json"}) is None and montage_link({"file": "x.mp4"}) is None
    assert montage_link({"file": "x.montage.json", "revision": True}) == {"file": "x.montage.json"}


# 6. Tool sidecars --------------------------------------------------------------------------------------------------------

def test_a_shortened_song_names_its_source_and_kept_ranges(tmp_path):
    from routers.audio_shorten import shorten_request
    workspace = tmp_path / "song"
    workspace.mkdir()
    source = workspace / "tema.wav"
    with wave.open(str(source), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes((np.sin(np.arange(8000 * 4) / 8) * 8000).astype("<i2").tobytes())
    result = shorten_request({"workspace": "song", "source": "tema.wav", "keep": [[0, 1], [2, 3]]},
                             resolve_source=lambda value, _ws: str(workspace / value), workspace_dir=lambda _ws: str(workspace))
    sidecar = json.loads((workspace / result["file"]).with_suffix(".meta.json").read_text())
    assert sidecar["params"]["source"] == "audio.shorten" and sidecar["params"]["keep"] == [[0, 1], [2, 3]]
    assert sidecar["params"]["duration_seconds"] == result["duration"]
    assert sidecar["lineage"]["parents"][0]["uri"] == "tema.wav"
    assert sidecar["lineage"]["transformations"][0]["tool"] == "audio.shorten"
    assert sidecar["origin"]["capability"] == "audio.shorten" and "requested_by" not in sidecar


def test_flat_rig_images_name_the_kit_role_and_pose_sources(tmp_path):
    folder = tmp_path / "pu"
    folder.mkdir()
    url = "/api/v1/file/{}?workspace=pu"
    for name in ("kit-ines-base-rig-1.png", "kit-ines-mouth-wide-2.png", "kit-ines-blink-3.png", "kit-ines-rig-review-4.png",
                 "kit-ines-base-mouth-open-5.png", "ines-base.png"):
        (folder / name).write_bytes(_png(1, 1, (1, 2, 3)))
    result = {"character": {"id": "ines", "name": "Inés", "base": {"source": url.format("kit-ines-base-rig-1.png")},
                            "mouth": {"wide": {"source": url.format("kit-ines-mouth-wide-2.png")}},
                            "eyes": {"blink": {"source": url.format("kit-ines-blink-3.png")}},
                            "anchors": {"base": {"mouthSources": {"open": url.format("kit-ines-base-mouth-open-5.png")}}},
                            "provenance": [{"method": "flat-rig", "sources": {"base": url.format("ines-base.png")},
                                            "style": {"mouthStyle": "warp"}, "hints": {}}]},
              "review": url.format("kit-ines-rig-review-4.png")}
    # The MCP tool reaches the rig route through a loopback that declares the agent (ActorHeaderMiddleware).
    with caller_scope({"surface": "loopback", "internal": "loopback", "actor": "agent"}):
        rig_sidecars(result, workspace="pu", kit_id="ines", folder=str(folder), request={"poses": None})
    mouth = json.loads((folder / "kit-ines-mouth-wide-2.meta.json").read_text())
    assert mouth["params"]["role"] == "mouth.wide.source" and mouth["params"]["kit_id"] == "ines"
    assert mouth["params"]["style"] == {"mouthStyle": "warp"} and mouth["params"]["source"] == "characters.rig.flat"
    [parent] = mouth["lineage"]["parents"]
    assert (parent["uri"], parent["role"], parent["kind"]) == ("ines-base.png", "pose:base", "image")
    assert mouth["origin"]["tool"] == "external_agent" and mouth["requested_by"]["capability"] == "characters.rig.flat"
    assert json.loads((folder / "kit-ines-rig-review-4.meta.json").read_text())["params"]["role"] == "review"
    pose_mouth = json.loads((folder / "kit-ines-base-mouth-open-5.meta.json").read_text())
    assert pose_mouth["params"]["role"] == "anchors.base.mouthSources.open"
    assert not (folder / "ines-base.meta.json").exists()
    # A person's rig keeps the tool's own name.
    (folder / "kit-ines-mouth-wide-2.meta.json").unlink()
    rig_sidecars(result, workspace="pu", kit_id="ines", folder=str(folder), request={"poses": ["base"]})
    mine = json.loads((folder / "kit-ines-mouth-wide-2.meta.json").read_text())
    assert mine["origin"]["tool"] == "characters.rig.flat" and "requested_by" not in mine


# 3 + 4. Saved scenes: the export names them and gives agent saves a real preview ---------------------------------------

def _scene_2d(name="Plus Ultra · La confesión · e1s04"):
    return {"version": 1, "name": name, "width": 64, "height": 36, "fps": 24, "duration": 0.25,
            "layers": [{"id": "bg", "name": "bg", "type": "image", "source": f"/api/v1/file/bg.png?workspace={WORKSPACE}",
                        "visible": True, "z": 0, "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1},
                        "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1.1},
                                      "duration": 1, "curve": "ease"}}]}


def _paint(snapshot, staging, progress, cancelled):
    plan, frames = snapshot["plan"], []
    for index in range(plan["count"]):
        path = Path(staging) / "frames" / f"frame_{index + 1:06d}.png"
        write_png(path, plan["width"], plan["height"], (200, 40 + index, 30))
        frames.append(path)
        progress(index + 1, plan["count"])
    return frames


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg is required")
def test_a_2d_export_names_the_saved_scene_and_gives_it_its_middle_frame(tmp_path):
    workspace_dir = _folder(tmp_path)
    root = Path(workspace_dir(WORKSPACE))
    write_png(root / "bg.png", 8, 8, (10, 20, 30))
    saved = save_document(WORKSPACE, _scene_2d(), name="pu-ep1-e1s04", preview=None, workspace_dir=workspace_dir)
    assert (root / INDEX).is_file() and needs_preview(root, saved["name"])
    (tmp_path / "uploads").mkdir()
    service = Scene2DExportService(workspace_dir=workspace_dir, renderer=_paint, uploads_dir=lambda: str(tmp_path / "uploads"),
                                   registry_for=lambda name: TaskRegistry(workspace_dir(name), interrupt_stale=False))
    receipt = asyncio.run(asyncio.to_thread(export_2d_handlers(service)[EXPORT_2D], {
        "version": 1, "intent_id": "shot-e1s04", "input": {"workspace": WORKSPACE, "document": _scene_2d()}}))
    registry = service._registry(WORKSPACE)
    task_id = receipt["receipt"]["taskIds"][0]
    deadline = time.time() + 20
    while time.time() < deadline and (registry.get(task_id) or {}).get("status") not in {"completed", "failed"}:
        time.sleep(0.05)
    task = registry.get(task_id)
    assert task["status"] == "completed", task
    output = task["metadata"]["output"]
    assert output["scene_file"] == saved["name"] and output["name"].count("La-confesion-e1s04") == 1
    sidecar = json.loads((root / output["name"]).with_suffix(".meta.json").read_text())
    assert sidecar["params"]["scene_file"] == saved["name"]
    with Image.open(preview_path(root, saved["name"])) as preview:
        assert preview.size == (64, 36) and preview.convert("RGB").getpixel((5, 5))[0] == 200
    assert not needs_preview(root, saved["name"])


def test_an_agent_3d_save_gets_the_export_frame_but_an_editor_preview_is_kept(tmp_path):
    workspace_dir = _folder(tmp_path)
    root = Path(workspace_dir(WORKSPACE))
    document = {"version": 1, "units": "meters", "up": "y", "width": 64, "height": 64, "fps": 30, "duration": 2 / 30,
                "templateId": "two-shot", "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
                "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
                "slots": [{"id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0, "scale": 1,
                           "sourceUrl": "", "media": "model3d", "clip": None}]}
    saved = save_document(WORKSPACE, document, name="duelo", preview=None, workspace_dir=workspace_dir)
    from services.world3d_export import _validated_document
    exported = _validated_document(json.loads((root / saved["name"]).read_text()))
    assert saved_scene_for(root, exported) == saved["name"]
    assert needs_preview(root, saved["name"])
    frame = tmp_path / "frame.png"
    write_png(frame, 720, 720, (5, 200, 5))
    assert preview_from_frames(root, saved["name"], [frame]) is True
    with Image.open(preview_path(root, saved["name"])) as preview:
        assert preview.size == (360, 360)  # fitted in 640 x 360
    assert preview_from_frames(root, saved["name"], [frame]) is False  # a real preview is never replaced
    with_preview = save_document(WORKSPACE, document, name="duelo-ui", workspace_dir=workspace_dir,
                                 preview="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC")
    assert not needs_preview(root, with_preview["name"])
    assert saved_scene_for(root, exported) == with_preview["name"]  # the newest save of the same document


def test_a_2d_save_with_a_preview_keeps_it(tmp_path):
    workspace_dir = _folder(tmp_path)
    tiny = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"
    saved = save_document(WORKSPACE, _scene_2d(), name="con-foto", preview=tiny, workspace_dir=workspace_dir)
    assert saved["thumbnail_url"].startswith("/api/v1/file/con-foto-") and not needs_preview(Path(workspace_dir(WORKSPACE)), saved["name"])


# 3. Published Video 3D scenes are named after their template; working scenes are listed ---------------------------------

def _working(root: Path, scene_id: str, revision: int, template="cine-dolly-zoom", published=None):
    record = {"revision": revision, "templateId": template, "warnings": [],
              "document": {"version": 1, "width": 64, "height": 64, "fps": 30, "duration": 1, "templateId": template,
                           "slots": [{"id": "s", "slot": "subject_1", "media": "model3d", "sourceUrl": ""}]}}
    if published:
        record["published"] = published
    (root / "world3d-edits").mkdir(parents=True, exist_ok=True)
    (root / "world3d-edits" / f"{scene_id}.json").write_text(json.dumps(record))


def test_working_scenes_list_what_was_not_published_at_its_revision(tmp_path):
    workspace_dir = _folder(tmp_path)
    root = Path(workspace_dir(WORKSPACE))
    _working(root, "w3d-000000000001", 2)
    _working(root, "w3d-000000000002", 3, published={"file": "x.world3d.scene.json", "revision": 3})
    _working(root, "w3d-000000000003", 4, published={"file": "x.world3d.scene.json", "revision": 3})
    _working(root, "w3d-000000000004", 1)
    (root / "w3d-000000000004-0f0f.world3d.scene.json").write_text("{}")  # published before the scene recorded it
    listed = {row["sceneId"]: row for row in working_scenes(WORKSPACE, workspace_dir)}
    assert set(listed) == {"w3d-000000000001", "w3d-000000000003"}
    assert listed["w3d-000000000003"]["published"]["revision"] == 3 and listed["w3d-000000000001"]["pending"] == 1
    assert len(working_scenes(WORKSPACE, workspace_dir, unpublished_only=False)) == 4
    app = FastAPI()
    app.include_router(create_world3d_templates_router(workspace_dir))
    client = TestClient(app)
    body = client.get("/api/v1/world3d/templates/working-scenes", params={"workspace": WORKSPACE}).json()
    assert [row["sceneId"] for row in body["scenes"]] and body["scenes"][0]["title"]
    assert client.get("/api/v1/world3d/templates/working-scenes", params={"workspace": "../x"}).status_code == 422
    capped = client.get("/api/v1/world3d/templates/working-scenes", params={"workspace": WORKSPACE, "all": True, "limit": 1}).json()
    assert len(capped["scenes"]) == 1 and capped["total"] == 4


def test_a_published_scene_is_named_after_its_template_and_remembered(tmp_path, monkeypatch):
    workspace_dir = _folder(tmp_path)
    root = Path(workspace_dir(WORKSPACE))
    document = {"version": 1, "units": "meters", "up": "y", "width": 64, "height": 64, "fps": 30, "duration": 1,
                "templateId": "anime-face-off", "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
                "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
                "slots": [{"id": "s", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0, "scale": 1, "sourceUrl": "",
                           "media": "model3d", "clip": None}]}
    (root / "world3d-edits").mkdir()
    (root / "world3d-edits" / "w3d-0123456789ab.json").write_text(json.dumps({"revision": 5, "templateId": "anime-face-off",
                                                                              "document": document, "warnings": []}))
    import services.world3d_scenes as scenes
    monkeypatch.setattr(scenes, "require_card", lambda template_id, **_kw: {"id": template_id, "titleEn": "Anime · Face-off"})
    published = publish_scene(WORKSPACE, "w3d-0123456789ab", workspace_dir)
    assert published["file"].startswith("Anime-Face-off-w3d-0123456789ab-") and published["file"].endswith(".world3d.scene.json")
    record = json.loads((root / "world3d-edits" / "w3d-0123456789ab.json").read_text())
    assert record["published"] == {"file": published["file"], "revision": 5} and record["revision"] == 5
    assert working_scenes(WORKSPACE, workspace_dir) == []


# 8. Produce jobs are listed --------------------------------------------------------------------------------------------

def test_produce_jobs_are_listed_newest_first_by_episode(tmp_path):
    workspace_dir = _folder(tmp_path)
    store = SeriesJobStore(workspace_dir(WORKSPACE), "produce")
    for index, (episode, status) in enumerate([("ep1", "completed"), ("ep2", "failed"), ("ep1", "cancelled")]):
        store.save({"jobId": f"produce-{index}", "workspace": WORKSPACE, "seriesId": "pu", "episodeId": episode, "status": status,
                    "createdAt": 100 + index, "steps": [{"kind": "render", "language": "spanish", "status": "done"}],
                    "chapters": {"spanish": {"file": f"cap-{index}.mp4"}}})
    service = SeriesProduce(ProduceDeps(call=lambda *_a: {}, workspace_dir=workspace_dir, read_library=lambda _w: {}))
    app = FastAPI()
    app.include_router(create_series_produce_router(service, call=lambda *_a: {}, bind_loop=lambda _loop: None,
                                                    read_library=lambda _w: {}, read_kits=lambda _w: {}, workspace_dir=workspace_dir))
    client = TestClient(app)
    every = client.get("/api/v1/series/produce/jobs", params={"workspace": WORKSPACE}).json()
    assert [job["jobId"] for job in every["jobs"]] == ["produce-2", "produce-1", "produce-0"] and every["total"] == 3
    assert all("workspace" not in job for job in every["jobs"])
    episode = client.get("/api/v1/series/produce/jobs", params={"workspace": WORKSPACE, "episode_id": "ep1", "limit": 1}).json()
    assert [job["jobId"] for job in episode["jobs"]] == ["produce-2"] and episode["total"] == 2
    assert client.get("/api/v1/series/produce/jobs/produce-0", params={"workspace": WORKSPACE}).json()["chapters"]["spanish"]["file"] == "cap-0.mp4"
