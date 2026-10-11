"""A production owns its montage file: two productions with one title both finish, and a rerun updates its own."""
from __future__ import annotations

import json

from services.montage_documents import MontageError, MontageStore
from services.music_production import Production

SPEC = {"title": "Pilot v2", "song": {"lyrics": "", "caption": "c", "duration": 4, "bpm": 100}, "style": {}, "shots": []}


def _production(root, production_id, saves, **state):
    store = MontageStore(lambda _ws: str(root))

    def mcp(tool, arguments):
        data = arguments.get("input") or {}
        if tool == "montages.save":
            saves.append(data)
            try:
                return {"result": store.save(data["workspace"], data["montage"], file=data.get("file"),
                                             expected_revision=data.get("expected_revision"))}
            except MontageError as error:          # what the MCP envelope carries (pilot: 409 exists)
                return {"error": {"code": error.code, "message": str(error), "status": error.status}}
        if tool == "montages.export":
            return {"result": {"job": {"job_id": "export-1"}}}
        if tool == "montages.export.status":
            return {"result": {"job": {"status": "completed", "filename": f"{production_id}.mp4"}}}
        raise AssertionError(tool)

    production = Production("ws", production_id, workspace_dir=lambda _: str(root), uploads_dir=lambda: str(root), mcp=mcp)
    production.state.update(song={"file": "s.wav"}, scenes={"s0": {"file": "s0.mp4", "dur": 4}}, segments=[["s0", 0, 4]],
                            scene_docs={"s0": {"scene": f"{production_id}-s0.scene.json"}}, **state)
    production.score = lambda: {"duration": 4, "lines": [], "beat": 0.5}
    return production


def _montage(root, file):
    return json.loads((root / file).read_text(encoding="utf-8"))


def test_two_productions_with_one_title_both_finish_and_a_rerun_updates_its_own(tmp_path):
    saves = []
    first = _production(tmp_path, "pilot-v5", saves)
    first.montage(SPEC)
    second = _production(tmp_path, "pilot-v6", saves)
    second.montage(SPEC)
    assert (first.state["montage_file"], second.state["montage_file"]) == ("pilot-v5.montage.json", "pilot-v6.montage.json")
    assert _montage(tmp_path, "pilot-v6.montage.json")["name"] == "Pilot v2", "the title stays the montage's name"
    first.montage(SPEC)
    assert saves[-1]["file"] == "pilot-v5.montage.json" and saves[-1]["expected_revision"] == 1
    assert _montage(tmp_path, "pilot-v5.montage.json")["revision"] == 2 and first.state["final"] == "pilot-v5.mp4"


def test_a_file_of_another_production_is_left_alone_and_its_own_is_found_by_its_clips(tmp_path):
    saves = []
    store = MontageStore(lambda _ws: str(tmp_path))
    clip = {"source": "/api/v1/file/x.mp4?workspace=ws", "trimEnd": 2, "origin": {"kind": "scene2d", "productionId": "someone"}}
    store.save("ws", {"version": 1, "name": "Other", "clips": [clip]}, file="pilot-c.montage.json")
    stranger = _production(tmp_path, "pilot-c", saves)
    stranger.montage(SPEC)
    assert stranger.state["montage_file"] == "pilot-c-2.montage.json"
    assert _montage(tmp_path, "pilot-c.montage.json")["name"] == "Other"
    lost = _production(tmp_path, "pilot-c", saves)          # its state no longer names the file: the clips do
    lost.montage(SPEC)
    assert saves[-1]["file"] == "pilot-c-2.montage.json" and saves[-1]["expected_revision"] == 1


def test_an_older_production_keeps_the_title_named_file_its_state_points_to(tmp_path):
    saves = []
    store = MontageStore(lambda _ws: str(tmp_path))
    store.save("ws", {"version": 1, "name": "Pilot v2", "clips": [{"source": "/api/v1/file/x.mp4?workspace=ws", "trimEnd": 2}]})
    older = _production(tmp_path, "pilot-v4", saves, montage_file="Pilot-v2.montage.json")
    older.montage(SPEC)
    assert older.state["montage_file"] == "Pilot-v2.montage.json" and _montage(tmp_path, "Pilot-v2.montage.json")["revision"] == 2
