"""Engine ``meshy`` of /api/v1/rig: rigging, library animations, errors and the animation library. No network."""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.rig import create_rig_router
from services import meshy_http, meshy_rig_service, rig_service
from services.model3d_rig_commands import command_catalog, command_handlers
from tests.support.fake_meshy import FakeMeshy, error, glb

LIBRARY = [
    {"action_id": 92, "name": "Walk Forward", "key": "walk_forward", "category": "WalkAndRun", "sub_category": "Walking", "preview_url": "https://x/92.gif"},
    {"action_id": 14, "name": "Idle Breathing", "key": "idle_breathing", "category": "DailyActions", "sub_category": "Idle", "preview_url": "https://x/14.gif"},
    {"action_id": 7, "name": "Hip Hop Spin", "key": "hip_hop_spin", "category": "Dancing", "sub_category": "HipHop", "preview_url": "https://x/7.gif"},
]


class _RunNow:
    def __init__(self, target=None, args=(), **_kw):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


@pytest.fixture
def meshy(monkeypatch, tmp_path):
    fake = FakeMeshy().install(monkeypatch)
    fake.library = list(LIBRARY)
    monkeypatch.setattr(meshy_http.time, "sleep", lambda _s: None)
    monkeypatch.setattr(rig_service, "_jobs", {})
    monkeypatch.setattr(meshy_rig_service, "api_key", lambda: "msy-key")
    monkeypatch.setattr(meshy_rig_service.execution_mode, "validate_remote_provider", lambda *_a, **_k: None)
    monkeypatch.setattr(meshy_rig_service.threading, "Thread", _RunNow)
    monkeypatch.setattr(meshy_rig_service, "_library", {"at": 0.0, "items": None})
    folder = tmp_path / "movie"
    folder.mkdir()
    (folder / "hero.glb").write_bytes(glb())
    fake.folder = folder
    return fake


def rig(meshy, **body):
    job = rig_service.start_job(
        body={"engine": "meshy", **body}, source_path=str(meshy.folder / "hero.glb"),
        output_dir=str(meshy.folder), workspace="movie")
    return rig_service.get_job(job["job_id"])


def written(meshy):
    return sorted(path.name for path in meshy.folder.iterdir() if not path.name.endswith(".meta.json"))


def manifest(meshy, name):
    return json.loads((meshy.folder / name).with_suffix(".meta.json").read_text(encoding="utf-8"))


def test_a_rig_without_animations_saves_the_rigged_glb_and_the_free_clips(meshy):
    done = rig(meshy)
    assert done["status"] == "completed", done
    body = meshy.posts("rig")[0]
    assert body["model_url"].startswith("data:application/octet-stream;base64,") and body["height_meters"] == 1.7
    assert meshy.posts("anim") == []
    names = written(meshy)
    assert len(names) == 4 and "hero.glb" in names, names
    assert (meshy.folder / "hero.glb").read_bytes() == glb(), "the source is kept"
    main = done["filename"]
    assert main.endswith(".glb") and "_rigged_hero_" in main
    assert done["clips"] == [] and done["engine"] == "meshy" and done["joint_count"] == 0
    assert done["provider"] == "meshy" and done["resource_lane"].startswith("remote:")
    assert [(item["role"], [clip["name"] for clip in item["clips"]]) for item in done["files"]] == [
        ("main", []), ("walking", ["Walking"]), ("running", ["Running"])]
    assert done["files"][1]["filename"] == main.replace(".glb", "-walking.glb")
    assert done["files"][1]["clips"] == [{"index": 0, "name": "Walking", "duration": 1.0, "loop": None}]
    assert done["url"].endswith("?workspace=movie") and done["meshy"]["consumed_credits"] == 5
    assert done["meshy"]["rig_task_id"] == "rig-1" and done["meshy"]["expires_at"] == 1_900_000_000_000


def test_library_animations_become_one_glb_with_one_clip_each(meshy):
    done = rig(meshy, animations=["walk_forward", 14, "92"], height_meters=1.8)
    assert done["status"] == "completed", done
    assert meshy.posts("rig")[0]["height_meters"] == 1.8
    assert meshy.posts("anim") == [{"rig_task_id": "rig-1", "action_ids": [92, 14]}]
    assert [(clip["index"], clip["name"], clip["action_id"], clip["key"]) for clip in done["clips"]] == [
        (0, "Action 92", 92, "walk_forward"), (1, "Action 14", 14, "idle_breathing")]
    assert done["animations"] == ["walk_forward", "idle_breathing"]
    assert done["meshy"]["animation_task_id"] == "anim-2" and done["meshy"]["consumed_credits"] == 11
    assert done["meshy"]["actions"][0] == {"action_id": 92, "key": "walk_forward", "name": "Walk Forward"}
    assert [item["role"] for item in done["files"]] == ["main", "walking", "running"]
    assert done["files"][0]["clips"] == done["clips"] and done["warnings"] == []


def test_the_manifest_records_meshy_and_names_the_sibling_files(meshy):
    done = rig(meshy, animations=["walk_forward"])
    main = manifest(meshy, done["filename"])
    assert main["params"]["provider"] == "meshy" and main["params"]["rig_engine"] == "meshy"
    assert main["params"]["meshy"]["rig_task_id"] == "rig-1"
    assert main["params"]["meshy"]["animation_task_id"] == "anim-2"
    assert main["params"]["meshy"]["consumed_credits"] == 8 and main["params"]["meshy"]["height_meters"] == 1.7
    assert main["params"]["source_file"] == "hero.glb" and main["params"]["siblings"] == [
        done["files"][1]["filename"], done["files"][2]["filename"]]
    walking = manifest(meshy, done["files"][1]["filename"])
    assert walking["params"]["role"] == "walking" and walking["params"]["main_file"] == done["filename"]
    assert "consumed_credits" not in walking["params"]["meshy"]
    assert "Expires" not in json.dumps(main), "no signed link is kept"


def test_a_failed_animation_still_saves_the_rig_that_was_paid_for(meshy):
    meshy.errors["POST /v1/animations"] = [error(402, "Insufficient credits")]
    done = rig(meshy, animations=["walk_forward"])
    assert done["status"] == "completed" and done["clips"] == []
    assert len(done["warnings"]) == 1 and done["warnings"][0].startswith("meshy_animation_failed") and "credits" in done["warnings"][0]
    assert done["meshy"]["consumed_credits"] == 5 and "animation_task_id" not in done["meshy"]
    assert len(written(meshy)) == 4


def test_an_animation_task_that_fails_after_it_started_still_names_its_task(meshy):
    meshy.script["anim"] = [{"status": "FAILED", "task_error": {"message": "boom"}, "consumed_credits": 0}]
    done = rig(meshy, animations=["walk_forward"])
    assert done["status"] == "completed" and "boom" in done["warnings"][0] and "anim-2" in done["warnings"][0]


def test_a_glb_that_needs_an_extension_still_lists_its_clips_quietly(meshy):
    meshy.files["https://assets.meshy.ai/rig-1-walk.glb"] = glb((("Walking", 1.0),), extensions=("KHR_mesh_quantization",))
    done = rig(meshy)
    assert done["files"][1]["clips"][0]["name"] == "Walking" and done["warnings"] == []


def test_a_pose_meshy_cannot_read_is_the_not_humanoid_refusal(meshy):
    meshy.errors["POST /v1/rigging"] = [error(422, "Pose estimation failed.")]
    done = rig(meshy)
    assert done["status"] == "failed" and done["error_code"] == "not_humanoid"
    assert done["error_reason"] == "meshy_pose_estimation_failed" and "pose_mode" in done["error"]
    assert written(meshy) == ["hero.glb"]
    meshy.script["rig"] = [{"status": "FAILED", "task_error": {"message": "Pose estimation failed"}, "consumed_credits": 0}]
    again = rig(meshy)
    assert again["error_code"] == "not_humanoid" and again["error_reason"] == "meshy_pose_estimation_failed"


def test_no_credits_and_a_bad_key_have_their_own_codes(meshy):
    meshy.errors["POST /v1/rigging"] = [error(402, "Insufficient credits")]
    assert rig(meshy)["error_code"] == "meshy_insufficient_credits"
    meshy.errors["POST /v1/rigging"] = [error(401, "Unauthorized")]
    assert rig(meshy)["error_code"] == "meshy_invalid_key"
    assert written(meshy) == ["hero.glb"]


def test_a_model_over_100_mb_is_refused_before_any_request(meshy):
    with open(meshy.folder / "hero.glb", "r+b") as handle:
        handle.truncate(101 * 1024 * 1024)
    done = rig(meshy)
    assert done["status"] == "failed" and done["error_code"] == "invalid_input" and done["error_reason"] == "too_large"
    assert "100 MB" in done["error"] and meshy.calls == []


def test_the_100_mb_limit_counts_the_encoded_upload(meshy):
    with open(meshy.folder / "hero.glb", "r+b") as handle:
        handle.truncate(80 * 1024 * 1024)       # 80 MB of GLB is about 107 MB once base64 encoded
    done = rig(meshy)
    assert done["error_reason"] == "too_large" and "75 MB" in done["error"] and meshy.calls == []
    mb = 1024 * 1024
    assert meshy_rig_service.encoded_size(74 * mb) <= meshy_rig_service.MAX_MODEL_BYTES < meshy_rig_service.encoded_size(76 * mb)


@pytest.mark.parametrize("data,reason", [
    (glb(extensions=("KHR_draco_mesh_compression",)), "draco"),
    (glb(extensions=("EXT_meshopt_compression",)), "meshopt"),
    (b"not a glb at all, just text", "not_glb"),
])
def test_a_glb_meshy_cannot_read_is_invalid_input(meshy, data, reason):
    (meshy.folder / "hero.glb").write_bytes(data)
    done = rig(meshy)
    assert done["status"] == "failed" and done["error_code"] == "invalid_input" and done["error_reason"] == reason
    assert meshy.calls == [] and written(meshy) == ["hero.glb"]


def test_an_unknown_library_entry_fails_before_anything_is_paid(meshy):
    done = rig(meshy, animations=["walk_forward", "moonwalk"])
    assert done["status"] == "failed" and done["error_reason"] == "unknown_animation" and "moonwalk" in done["error"]
    assert meshy.created == [] and written(meshy) == ["hero.glb"]


@pytest.mark.parametrize("body,message", [
    ({"animations": ["a"] * 2 + [str(n) for n in range(11)]}, "at most 10"),
    ({"animations": "walk"}, "list of Meshy"),
    ({"animations": [""]}, "empty entry"),
    ({"height_meters": 0}, "height_meters"),
    ({"height_meters": "tall"}, "height_meters"),
])
def test_bad_requests_are_refused_before_a_job_exists(meshy, body, message):
    with pytest.raises(ValueError, match=message):
        rig(meshy, **body)
    assert rig_service._jobs == {}


def test_a_missing_key_points_at_settings_and_starts_no_job(meshy, monkeypatch):
    monkeypatch.setattr(meshy_rig_service, "api_key", lambda: "")
    with pytest.raises(ValueError, match="Settings"):
        rig(meshy)
    assert rig_service._jobs == {} and meshy.calls == []


def test_cancelling_while_meshy_is_still_queued_refunds_the_rig_and_writes_nothing(meshy):
    meshy.script["rig"] = [{"status": "PENDING", "progress": 0}]
    meshy.on_poll = lambda _task: rig_service.cancel_job(next(iter(rig_service._jobs)))
    done = rig(meshy)
    assert done["status"] == "cancelled"
    assert meshy.deleted == ["/v1/rigging/rig-1"] and written(meshy) == ["hero.glb"]


def test_cancelling_a_running_rig_keeps_the_task_and_writes_nothing(meshy):
    meshy.script["rig"] = [{"status": "IN_PROGRESS", "progress": 30}]
    meshy.on_poll = lambda _task: rig_service.cancel_job(next(iter(rig_service._jobs)))
    done = rig(meshy)
    assert done["status"] == "cancelled" and meshy.deleted == [] and written(meshy) == ["hero.glb"]


def test_the_engine_is_listed_with_the_key_state(meshy, monkeypatch):
    entry = [engine for engine in rig_service.capabilities()["engines"] if engine["id"] == "meshy"][0]
    assert entry["installed"] is True and entry["remote"] is True and entry["max_animations"] == 10
    assert entry["cost_credits"] == {"rig": 5, "per_library_animation": 3, "walking_and_running": 0}
    monkeypatch.setattr(meshy_rig_service, "api_key", lambda: "")
    entry = [engine for engine in rig_service.capabilities()["engines"] if engine["id"] == "meshy"][0]
    assert entry["installed"] is False and "Settings" in entry["install_hint"]


@pytest.fixture
def client(meshy, tmp_path):
    root = tmp_path
    app = FastAPI()
    app.include_router(create_rig_router(
        resolve_input_path=lambda name, workspace=None: None,
        workspace_dir=lambda workspace: str(root / (workspace or "movie")),
        get_active_workspace=lambda: "movie",
        safe_join=lambda base, name: str(Path(base) / name),
        publish_task=None,
    ))
    return TestClient(app)


def test_the_library_route_filters_and_caches(meshy, client):
    everything = client.get("/api/v1/rig/meshy/animations").json()
    assert everything["total"] == 3 and everything["cached"] is False
    assert everything["animations"][0] == {**LIBRARY[0]}
    walking = client.get("/api/v1/rig/meshy/animations", params={"search": "WALK"}).json()
    assert [item["key"] for item in walking["animations"]] == ["walk_forward"] and walking["cached"] is True
    dancing = client.get("/api/v1/rig/meshy/animations", params={"category": "Dancing"}).json()
    assert [item["action_id"] for item in dancing["animations"]] == [7] and dancing["sub_categories"] == ["HipHop"]
    idle = client.get("/api/v1/rig/meshy/animations", params={"sub_category": "Idle", "limit": 1, "offset": 0}).json()
    assert idle["count"] == 1 and idle["animations"][0]["key"] == "idle_breathing"
    assert sum(1 for call in meshy.calls if call[1] == "/v1/animations/library") == 1, "one request fills the cache"


def test_the_library_route_refuses_bad_filters_and_reports_meshy_errors(meshy, client):
    assert client.get("/api/v1/rig/meshy/animations", params={"category": "Cooking"}).status_code == 400
    assert client.get("/api/v1/rig/meshy/animations", params={"limit": 0}).status_code == 400
    meshy.errors["GET /v1/animations/library"] = [error(401, "bad key")]
    refused = client.get("/api/v1/rig/meshy/animations")
    assert refused.status_code == 401 and "API key" in refused.json()["detail"]


def test_the_rest_route_runs_a_meshy_rig_job(meshy, client, monkeypatch):
    started = client.post("/api/v1/rig/generate", json={
        "workspace": "movie", "source": "hero.glb", "engine": "meshy", "animations": ["walk_forward"]})
    assert started.status_code == 200, started.text
    done = client.get(f"/api/v1/rig/status/{started.json()['job_id']}").json()
    assert done["status"] == "completed" and done["clips"][0]["key"] == "walk_forward"
    monkeypatch.setattr(meshy_rig_service, "api_key", lambda: "")
    refused = client.post("/api/v1/rig/generate", json={"workspace": "movie", "source": "hero.glb", "engine": "meshy"})
    assert refused.status_code == 400 and "Settings" in refused.json()["detail"]


def test_the_mcp_catalog_offers_the_engine_and_the_free_library_read(meshy, client, tmp_path):
    entries = {item["name"]: item for item in command_catalog()}
    assert set(entries) == {"model3d.rig", "model3d.rig.status", "model3d.meshy.animations"}
    fields = entries["model3d.rig"]["inputSchema"]["properties"]["input"]["properties"]
    assert "meshy" in fields["engine"]["enum"] and fields["height_meters"]["maximum"] == 100
    assert "meshy" in entries["model3d.rig"]["description"] and "+Z" in entries["model3d.rig"]["description"]
    library = entries["model3d.meshy.animations"]
    assert library["mutation"] is False and "journal" not in json.dumps(library)
    json.dumps(list(entries.values()))
    handlers = command_handlers(generate=None, status=None, journal_path=tmp_path / "requests.db")
    found = asyncio.run(handlers["model3d.meshy.animations"]({"version": 1, "input": {"search": "idle"}}))
    assert found["operation"] == "model3d.meshy.animations" and found["result"]["animations"][0]["key"] == "idle_breathing"
    with pytest.raises(ValueError, match="Unknown input"):
        asyncio.run(handlers["model3d.meshy.animations"]({"version": 1, "input": {"colour": "red"}}))


def test_mcp_rig_requests_carry_the_meshy_fields_to_the_rest_body(meshy, tmp_path):
    calls = []

    async def generate(request):
        calls.append(await request.json())
        return {"workspace": "movie", "job_id": "rig-1", "status": "queued"}

    handlers = command_handlers(generate=generate, status=None, journal_path=tmp_path / "requests.db")
    result = asyncio.run(handlers["model3d.rig"]({"version": 1, "intent_id": "m1", "input": {
        "workspace": "movie", "source": "hero.glb", "engine": "meshy", "animations": ["walk_forward", 14], "height_meters": 1.6}}))
    assert result["status"] == "queued"
    assert calls[0]["engine"] == "meshy" and calls[0]["animations"] == ["walk_forward", 14] and calls[0]["height_meters"] == 1.6
