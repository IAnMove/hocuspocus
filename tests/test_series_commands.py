"""Series Lab and Character Kits are reachable over MCP through their existing HTTP contracts."""
import asyncio
import io
import json
import urllib.error

import pytest
from fastapi import HTTPException

from routers.wangp_mcp import tool_definitions
from services.series_commands import command_catalog, command_handlers


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


def test_character_styles_list_presets_and_build_a_prompt_without_the_server(tmp_path):
    handlers, calls, _, _ = harness(tmp_path, [])
    listed = call(handlers, "characters.styles", {})["result"]
    assert "paper-cutout" in [style["id"] for style in listed["styles"]] and "prompt" not in listed
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
