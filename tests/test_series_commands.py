"""Series Lab and Character Kits are reachable over MCP through their existing HTTP contracts."""
import asyncio
import io
import json
import urllib.error

import pytest
from fastapi import HTTPException

from routers.wangp_mcp import tool_definitions
from services.series_commands import OPERATIONS, command_catalog, command_handlers


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def harness(tmp_path, replies):
    calls = []
    workspace, uploads = tmp_path / "series", tmp_path / "uploads"
    workspace.mkdir()

    def opener(request, timeout):
        body = json.loads(request.data) if request.data else None
        if body and "uploadPath" in body:
            body["uploaded"] = open(body["uploadPath"], "rb").read().decode()
        calls.append((request.get_method(), request.full_url, body))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Response(json.dumps(reply).encode())

    handlers = command_handlers(lambda: "http://127.0.0.1:9", lambda name: str(workspace), lambda: str(uploads), opener=opener)
    return handlers, calls, workspace, uploads


def call(handlers, name, data):
    return asyncio.run(handlers[name]({"version": 1, "input": data}))


def test_every_series_tool_is_listed_with_its_mutation_hint():
    operations = command_catalog()
    tools = {tool["name"]: tool for tool in tool_definitions({operation["name"] for operation in operations}, operations)}
    assert {"characters.save", "series.create", "series.episode.update", "series.asset.import", "series.assembly.start"} <= set(tools)
    assert tools["series.get"]["annotations"]["readOnlyHint"] is True
    assert tools["characters.save"]["annotations"]["readOnlyHint"] is False


def test_saving_a_character_patches_the_library_at_its_revision(tmp_path):
    kit = {"id": "kevin", "name": "Kevin", "voice": {"model": "qwen3_tts_customvoice", "voiceId": "ryan"},
           "voicesByLanguage": {"spanish": {"model": "qwen3_tts_base", "name": "Kevin ES"}}}
    handlers, calls, _, _ = harness(tmp_path, [{"revision": 4, "kits": {"kevin": kit}}])
    result = call(handlers, "characters.save", {"workspace": "series", "character": kit, "base_revision": 3})
    method, url, body = calls[0]
    assert (method, url) == ("PATCH", "http://127.0.0.1:9/api/v1/character-kits/library/kits/kevin")
    assert body == {"workspace": "series", "kit": kit, "baseRevision": 3}
    assert result["result"]["revision"] == 4
    assert result["result"]["character"]["voicesByLanguage"] == {"spanish": "Kevin ES"}
    assert result["result"]["ignoredFields"] == []


def test_saving_a_character_lists_the_fields_the_server_dropped(tmp_path):
    # An older server drops voicesByLanguage; the agent must hear about it.
    kit = {"id": "kevin", "name": "Kevin", "notes": None, "voice": {"model": "qwen3_tts_customvoice", "pitch": 2},
           "voicesByLanguage": {"spanish": {"model": "qwen3_tts_base"}}, "poses": [{"id": "front", "extra": 1}]}
    stored = {"id": "kevin", "name": "Kevin", "voice": {"model": "qwen3_tts_customvoice"}, "poses": [{"id": "front"}]}
    handlers, _, _, _ = harness(tmp_path, [{"revision": 4, "kits": {"kevin": stored}}])
    result = call(handlers, "characters.save", {"workspace": "series", "character": kit, "base_revision": 3})
    assert result["result"]["ignoredFields"] == ["voice.pitch", "voicesByLanguage"]


def test_a_workspace_take_is_imported_through_uploads_and_its_attempt_returned(tmp_path):
    series = {"revision": 9, "episodesById": {"ep": {"shots": [{"id": "s01", "attempts": [{"id": "a1", "outputAssetIds": ["asset_1"]}]}]}}}
    handlers, calls, workspace, uploads = harness(tmp_path, [{"asset": {"id": "asset_1"}, "series": series}])
    (workspace / "shot.mp4").write_text("video")
    result = call(handlers, "series.asset.import", {"workspace": "series", "series_id": "uv", "file": "shot.mp4", "owner_type": "shot",
                                                     "owner_id": "s01", "kind": "video", "as_take": True, "metadata": {"sceneFilename": "s01.scene.json"}})
    _, url, body = calls[0]
    assert url.endswith("/api/v1/series/uv/assets/import")
    assert body["uploaded"] == "video" and body["asTake"] is True and body["metadata"] == {"sceneFilename": "s01.scene.json"}
    assert result["result"]["attempt"]["id"] == "a1"
    assert not list(uploads.rglob("*.mp4")), "the temporary upload copy is removed"


def test_files_outside_the_workspace_are_refused(tmp_path):
    handlers, calls, _, _ = harness(tmp_path, [])
    (tmp_path / "secret.mp4").write_text("x")
    with pytest.raises(HTTPException) as error:
        call(handlers, "series.asset.import", {"workspace": "series", "series_id": "uv", "file": "../secret.mp4",
                                                "owner_type": "shot", "owner_id": "s01", "kind": "video"})
    assert error.value.status_code == 404 and not calls


def test_a_stale_revision_is_reported_as_a_retryable_conflict(tmp_path):
    stale = urllib.error.HTTPError("http://x", 409, "Conflict", {}, io.BytesIO(b'{"detail": "Series revision changed to 7; reload before saving"}'))
    handlers, _, _, _ = harness(tmp_path, [stale])
    with pytest.raises(HTTPException) as error:
        call(handlers, "series.update", {"workspace": "series", "series_id": "uv", "series": {"title": "x"}, "base_revision": 6})
    assert error.value.status_code == 409
    assert error.value.detail == {"code": "conflict", "message": "Series revision changed to 7; reload before saving", "retryable": True}


def test_a_route_error_keeps_its_code_message_and_problems(tmp_path):
    body = b'{"detail": {"code": "invalid_script", "message": "shot 0: unknown effect x", "problems": ["shot 0: unknown effect x"]}}'
    bad = urllib.error.HTTPError("http://x", 400, "Bad Request", {}, io.BytesIO(body))
    handlers, _, _, _ = harness(tmp_path, [bad])
    with pytest.raises(HTTPException) as error:
        call(handlers, "series.episode.from_script", {"workspace": "series", "series_id": "uv", "script": {"shots": []}})
    assert error.value.status_code == 400
    assert error.value.detail == {"code": "invalid_script", "message": "shot 0: unknown effect x", "problems": ["shot 0: unknown effect x"],
                                  "retryable": False}


def test_unknown_input_fields_are_rejected_before_any_request(tmp_path):
    handlers, calls, _, _ = harness(tmp_path, [])
    with pytest.raises(HTTPException) as error:
        call(handlers, "series.get", {"workspace": "series", "series_id": "uv", "token": "nope"})
    assert error.value.status_code == 422 and not calls


def test_rigging_a_flat_character_posts_to_the_kit_and_summarises_it(tmp_path):
    kit = {"id": "kevin", "name": "Kevin", "base": {"source": "x"}, "poses": {}, "mouth": {"closed": {}}}
    handlers, calls, _, _ = harness(tmp_path, [{"revision": 5, "character": kit, "review": "/api/v1/file/r.png?workspace=series",
                                                "unwipedPoses": [], "poses": {"base": {"wiped": True}}}])
    result = call(handlers, "characters.rig.flat", {"workspace": "series", "character_id": "kevin", "base_revision": 4,
                                                    "style": {"smile": 0.4}})
    method, url, body = calls[0]
    assert (method, url) == ("POST", "http://127.0.0.1:9/api/v1/character-kits/library/kits/kevin/flat-rig")
    assert body == {"workspace": "series", "baseRevision": 4, "style": {"smile": 0.4}}
    assert result["result"]["revision"] == 5 and result["result"]["character"]["mouths"] == ["closed"]
    assert result["result"]["review"].endswith("r.png?workspace=series")


def test_rigging_passes_ink_mouths_and_placement_hints_to_the_kit(tmp_path):
    kit = {"id": "anselmo", "name": "Anselmo", "base": {"source": "x"}, "poses": {}, "mouth": {"closed": {}}}
    handlers, calls, _, _ = harness(tmp_path, [{"revision": 2, "character": kit, "review": "r", "unwipedPoses": [],
                                                "poses": {"base": {"wiped": False, "mouthFound": True, "face": "realistic"}}}])
    hints = {"base": {"mouth": [44.2, 17.45]}, "busto": None}
    call(handlers, "characters.rig.flat", {"workspace": "series", "character_id": "anselmo", "base_revision": 1,
                                           "style": {"mouthStyle": "ink"}, "hints": hints})
    assert calls[0][2] == {"workspace": "series", "baseRevision": 1, "style": {"mouthStyle": "ink"}, "hints": hints}
    schema = OPERATIONS["characters.rig.flat"][0]
    assert schema["style"]["properties"]["mouthStyle"] == {"enum": ["paper", "ink", "warp"]} and "hints" in schema
    assert set(schema["hints"]["additionalProperties"]["anyOf"][1]["properties"]) == {"mouth", "eyes", "mouthWidth", "exact"}


def test_previewing_warp_mouths_posts_the_line_and_asks_for_a_sheet(tmp_path):
    preview = {"pose": "busto", "mouth": [61.6, 20.48], "mouthWidth": 6.55, "found": True, "from": "hint",
               "sheet": "/api/v1/file/.kit-blas-busto-warp-preview.png?workspace=series&v=1"}
    handlers, calls, _, _ = harness(tmp_path, [preview])
    result = call(handlers, "characters.rig.flat.preview", {"workspace": "series", "character_id": "blas", "pose": "busto",
                                                            "mouth": [61.6, 20.1], "mouthWidth": 6.5})
    method, url, body = calls[0]
    assert (method, url) == ("POST", "http://127.0.0.1:9/api/v1/character-kits/library/kits/blas/flat-rig/preview")
    assert body == {"workspace": "series", "pose": "busto", "sheet": True, "mouth": [61.6, 20.1], "mouthWidth": 6.5}
    assert result["result"]["sheet"].endswith("warp-preview.png?workspace=series&v=1")
    assert OPERATIONS["characters.rig.flat.preview"][2] is False, "a preview saves nothing on the kit"


def test_the_agent_trail_names_the_rigged_kit_and_leaves_previews_out():
    from services.agent_activity import artifact_targets
    from services.series_commands import _operation_schema
    rigged = {"result": {"revision": 3, "character": {"id": "blas", "name": "Blas"}, "review": "/api/v1/file/kit-blas-rig-review-1.png"}}
    targets = artifact_targets({"input": {"workspace": "series", "character_id": "blas"}}, rigged)
    assert targets[0] == {"kind": "character_kit", "id": "blas", "title": "Blas"}
    # The dispatcher records mutating calls only: the preview's warped sheet is not something the agent made.
    preview = OPERATIONS["characters.rig.flat.preview"]
    assert _operation_schema("characters.rig.flat.preview", *preview)["mutation"] is False


def test_checking_a_pose_posts_the_rig_check_and_saves_nothing(tmp_path):
    from services.series_commands import _operation_schema
    report = {"ready": False, "reasons": ["eyes_small"], "face": {"box": [1, 2, 30, 40], "confidence": 0.4}}
    handlers, calls, _, _ = harness(tmp_path, [report])
    result = call(handlers, "characters.rig.check", {"workspace": "series", "source": "/api/v1/file/pose.png?workspace=series"})
    method, url, body = calls[0]
    assert (method, url) == ("POST", "http://127.0.0.1:9/api/v1/character-kits/rig-check")
    assert body == {"workspace": "series", "source": "/api/v1/file/pose.png?workspace=series"}
    assert result["result"] == report
    assert OPERATIONS["characters.rig.check"][2] is False
    assert _operation_schema("characters.rig.check", *OPERATIONS["characters.rig.check"])["mutation"] is False


def test_character_styles_list_presets_and_build_a_prompt_without_the_server(tmp_path):
    handlers, calls, _, _ = harness(tmp_path, [])
    listed = call(handlers, "characters.styles", {})["result"]
    assert "paper-cutout" in [style["id"] for style in listed["styles"]] and "prompt" not in listed
    rigs = {style["id"]: style["rig"] for style in listed["styles"]}
    assert rigs["graphic-novel"] == {"mouthStyle": "warp"}, "painted characters talk with their own drawing"
    built = call(handlers, "characters.styles", {"style": "paper-cutout", "kind": "character",
                                                 "description": "Ana, green jacket"})["result"]["prompt"]
    assert built["screen"] == "magenta" and "Ana, green jacket" in built["prompt"]
    assert calls == []
    with pytest.raises(HTTPException) as error:
        call(handlers, "characters.styles", {"style": "oil-painting", "kind": "character"})
    assert error.value.status_code == 404


def test_the_server_episode_render_is_reachable_over_mcp(tmp_path):
    handlers, calls, _, _ = harness(tmp_path, [{"jobId": "native-1", "status": "queued"}, {"jobId": "native-1", "status": "running"},
                                               {"jobId": "native-1", "status": "queued"}])
    started = call(handlers, "series.episode.render_native", {"workspace": "series", "series_id": "uv", "episode_id": "ep1",
                                                               "shot_ids": ["s01"], "approve": True})
    assert started["result"]["job"]["jobId"] == "native-1"
    assert calls[0][:2] == ("POST", "http://127.0.0.1:9/api/v1/series/uv/episodes/ep1/native-render")
    assert calls[0][2] == {"workspace": "series", "approve": True, "shotIds": ["s01"]}
    call(handlers, "series.episode.render_native.status", {"workspace": "series", "job_id": "native-1"})
    assert calls[1][:2] == ("GET", "http://127.0.0.1:9/api/v1/series/native-render/jobs/native-1?workspace=series")
    call(handlers, "series.episode.render_native.resume", {"workspace": "series", "job_id": "native-1"})
    assert calls[2][:2] == ("POST", "http://127.0.0.1:9/api/v1/series/native-render/jobs/native-1/resume")


def test_a_shot_is_read_and_edited_by_its_number_over_mcp(tmp_path):
    handlers, calls, _, _ = harness(tmp_path, [{"shotId": "e1s04", "number": 5}, {"shotId": "e1s04", "changed": ["fx"]}])
    read = call(handlers, "series.shot.get", {"workspace": "series", "series_id": "uv", "episode_id": "ep1", "shot": 5})
    assert calls[0][:2] == ("GET", "http://127.0.0.1:9/api/v1/series/uv/episodes/ep1/shots/5?workspace=series")
    assert read["result"]["shotId"] == "e1s04"
    edited = call(handlers, "series.shot.update", {"workspace": "series", "series_id": "uv", "episode_id": "ep1", "shot": "e1s04",
                                                   "append": {"fx": [{"kind": "confetti", "at": 1}]}, "render": True})
    assert calls[1] == ("POST", "http://127.0.0.1:9/api/v1/series/uv/episodes/ep1/shots/edit",
                        {"workspace": "series", "shot": "e1s04", "append": {"fx": [{"kind": "confetti", "at": 1}]}, "render": True})
    assert edited["result"]["changed"] == ["fx"]
    schema = next(item for item in command_catalog() if item["name"] == "series.shot.update")["inputSchema"]["properties"]["input"]
    assert schema["required"] == ["workspace", "series_id", "episode_id", "shot"] and "append" in schema["properties"]


def test_a_location_plate_with_people_warns_and_still_imports(tmp_path, monkeypatch):
    warning = {"code": "people_in_plate", "count": 1, "boxes": [[1, 2, 3, 4]]}
    series = {"revision": 3, "locations": [{"id": "plaza"}], "assets": {}}
    handlers, _, workspace, _ = harness(tmp_path, [{"asset": {"id": "asset_plate"}, "series": series, "warnings": [warning]}])
    (workspace / "plate.png").write_bytes(b"png")
    result = call(handlers, "series.asset.import", {"workspace": "series", "series_id": "uv", "file": "plate.png",
                                                    "owner_type": "location", "owner_id": "plaza", "kind": "image",
                                                    "reference_role": "environment"})
    assert result["result"]["asset"]["id"] == "asset_plate"
    assert result["result"]["warnings"] == [warning]


@pytest.mark.parametrize("reply", [{"warnings": []}, {}], ids=["clean plate", "no warnings key"])
def test_the_mcp_import_never_scans_a_plate_again(tmp_path, monkeypatch, reply):
    """The server checks the plate once. A clean one answers warnings: [], and the handler does not run the detector."""
    series = {"revision": 3, "locations": [{"id": "plaza"}], "assets": {}}
    handlers, _, workspace, _ = harness(tmp_path, [{"asset": {"id": "asset_plate"}, "series": series, **reply}])
    (workspace / "plate.png").write_bytes(b"png")
    scans = []
    monkeypatch.setattr("services.series_plate_checks.detect_people", lambda path: scans.append(path) or [[1, 2, 3, 4]])
    result = call(handlers, "series.asset.import", {"workspace": "series", "series_id": "uv", "file": "plate.png",
                                                    "owner_type": "location", "owner_id": "plaza", "kind": "image",
                                                    "reference_role": "environment"})
    assert "warnings" not in result["result"] and scans == []


def test_the_import_reply_of_a_plate_always_lists_its_warnings(monkeypatch):
    from services.series_plate_checks import with_plate_warning
    scans = []
    monkeypatch.setattr("services.series_plate_checks.detect_people", lambda path: scans.append(path) or [])
    series = {"locations": [{"id": "plaza"}]}
    body = {"referenceRole": "plate", "ownerType": "location", "ownerId": "plaza"}
    assert with_plate_warning({"asset": {"id": "a"}}, "p.png", body, series) == {"asset": {"id": "a"}, "warnings": []}
    monkeypatch.setattr("services.series_plate_checks.detect_people", lambda path: scans.append(path) or [[1, 2, 3, 4]])
    assert with_plate_warning({"asset": {"id": "a"}}, "p.png", body, series)["warnings"] == [
        {"code": "people_in_plate", "count": 1, "boxes": [[1, 2, 3, 4]]}]
    portrait = {**body, "referenceRole": "primary_portrait"}
    assert with_plate_warning({"asset": {"id": "a"}}, "p.png", portrait, series) == {"asset": {"id": "a"}}
    assert scans == ["p.png", "p.png"]


def test_plate_people_and_the_location_picture():
    from services.series_plate_checks import location_plate_url, plate_people_warning
    found = lambda _path: [[1, 2, 3, 4]]
    assert plate_people_warning("p.png", role="environment", location={}, detect=found)["count"] == 1
    assert plate_people_warning("p.png", role="environment", location={"layout2d": {"allowPeople": True}}, detect=found) is None
    assert plate_people_warning("p.png", role="primary_portrait", location={}, detect=found) is None
    assert plate_people_warning("p.png", role="environment", location={}, detect=lambda _path: []) is None
    assert plate_people_warning("p.png", role="location_reference", location=None, detect=found)["code"] == "people_in_plate"
    assets = {"plate": {"kind": "image", "uri": "assets/plate.png"}, "bg": {"kind": "image", "uri": "assets/bg.png"},
              "ref": {"kind": "image", "uri": "outputs/ref.png"}, "picked": {"kind": "image", "uri": "assets/picked.png"},
              "loop": {"kind": "video", "uri": "assets/loop.mp4"}, "night": {"kind": "image", "uri": "assets/night.png"}}
    place = {"id": "plaza", "layout2d": {"plateAssetId": "plate", "backgroundAssetId": "bg"}, "referenceAssetIds": ["ref"],
             "variants": [{"id": "dusk", "referenceAssetIds": ["night"]}]}
    library = {"locations": [place], "assets": assets}
    shot = {"locationId": "plaza", "scene3d": {"template": "user-mars", "backdrop": "location"}}
    assert location_plate_url(library, shot, "cast") == "/api/v1/file/assets/plate.png?workspace=cast"
    # A plate3d loop is a video; the backdrop slot draws a still, so the next image is used.
    place["layout2d"]["plateAssetId"] = "loop"
    assert location_plate_url(library, shot, "cast") == "/api/v1/file/assets/bg.png?workspace=cast"
    place["layout2d"].pop("backgroundAssetId")
    assert location_plate_url(library, shot, "cast") == "/api/v1/file/ref.png?workspace=cast"
    assert location_plate_url(library, {**shot, "locationVariantId": "dusk"}, "cast") == "/api/v1/file/assets/night.png?workspace=cast"
    place["referenceAssetIds"] = []
    assert location_plate_url(library, shot, "cast") is None
    picked = {"locationId": "plaza", "scene3d": {"template": "user-mars", "backdrop": {"asset": "picked"}}}
    assert location_plate_url(library, picked, "cast") == "/api/v1/file/assets/picked.png?workspace=cast"
    assert location_plate_url(library, {**picked, "scene3d": {"template": "user-mars", "backdrop": {"asset": "loop"}}}, "cast") is None
    assert location_plate_url(library, {"locationId": "plaza", "scene3d": {"template": "user-mars"}}, "cast") is None
