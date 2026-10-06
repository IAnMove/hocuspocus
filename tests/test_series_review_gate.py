"""What a staged review lets the server render, produce and assemble."""
import copy

import pytest
from fastapi import HTTPException

from routers.series_assembly import SeriesAssemblyStartRequest
from services.series_native_render import NativeRenderDeps, NativeRenderError, SeriesNativeRender, render_inputs
from services.series_produce import ProduceDeps, SeriesProduce
from services.series_review import content_digest
from services.series_review_gate import actionable_shots, assembly_blockers, render_passes
from tests.test_series_assembly_router import _client, _wait_for_terminal
from tests.test_series_native_render import GARY, KEVIN_ES, Tools, finished, library
from tests.test_series_script_produce import Production, finished as produced, producer

KITS = {f"kit-{cid}": {"id": f"kit-{cid}", "name": cid, "base": {"source": "/api/v1/file/k.png", "width": 400, "height": 800},
                       "poses": {}, "voice": GARY, **({"voicesByLanguage": {"spanish": KEVIN_ES}} if cid == "kevin" else {})}
        for cid in ("kevin", "gary")}


def _decided(shot, plan="approved", preview=None, attempt=None):
    entry = {"plan": plan, "planDigest": content_digest(shot), "preview": "pending", "notes": []}
    if preview:
        entry.update(preview=preview, previewDigest=content_digest(shot), previewAttemptId=attempt)
    return entry


def _staged(mode, decide):
    """The native render's test library with a review: ``decide(shots) -> {shot id: entry}``."""
    lib = library()
    series = lib["seriesById"]["uv"]
    episode = series["episodesById"]["ep1"]
    episode["review"] = {"mode": mode, "shots": decide({shot["id"]: shot for shot in episode["shots"]}, series)}
    return lib


def _take(series, shot, attempt_id, stage=None, inputs="current"):
    """A completed take of ``shot`` whose kept render inputs are its current ones (or ``inputs``)."""
    shot.setdefault("attempts", []).append({"id": attempt_id, "status": "completed", "outputAssetIds": [f"asset-{attempt_id}"],
                                            **({"reviewStage": stage} if stage else {})})
    kept = render_inputs(series, shot, KITS) if inputs == "current" else inputs
    series["assets"][f"asset-{attempt_id}"] = {"id": f"asset-{attempt_id}", "kind": "video", "uri": f"outputs/{attempt_id}.mp4",
                                               "metadata": {"renderInputs": kept}}


def _render(tmp_path, tools, lib):
    def trim(source, target):
        with open(source, "rb") as handle, open(target, "wb") as out:
            out.write(handle.read())
        return 1.25
    return SeriesNativeRender(NativeRenderDeps(
        call=tools, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: lib, read_kits=lambda _ws: KITS,
        compile_shot=lambda payload: {"version": 1, "duration": payload["shot"]["duration"], "layers": []}, trim=trim,
        sleep=lambda _s: None, poll_seconds=0))


def _passes(lib, explicit=False, original=True):
    series = lib["seriesById"]["uv"]
    episode = series["episodesById"]["ep1"]
    shots = [shot for shot in episode["shots"] if shot["productionMethod"] == "animation_2d"]
    planned, waiting = render_passes(series, episode, shots, lambda shot: render_inputs(series, shot, KITS), explicit=explicit,
                                     original=original)
    return [(item["shot"]["id"], item["pass"], item.get("attemptId")) for item in planned], waiting


def test_a_direct_episode_is_not_gated():
    assert _passes(library()) == ([("s01", None, None), ("s03", None, None)], [])


def test_plan_mode_renders_only_approved_plans_and_reports_the_rest_as_waiting():
    lib = _staged("plan", lambda shots, _series: {"s01": _decided(shots["s01"]), "s03": _decided(shots["s03"], plan="changes")})
    assert _passes(lib) == ([("s01", None, None)], [{"shotId": "s03", "reason": "plan"}])


def test_preview_mode_gives_each_shot_its_pass():
    def decide(shots, series):
        _take(series, shots["s01"], "p1", "preview")              # a current preview nobody approved yet
        _take(series, shots["s03"], "p3", "preview")              # approved preview of a 2D shot: it is the final
        return {"s01": _decided(shots["s01"]), "s03": _decided(shots["s03"], preview="approved", attempt="p3")}
    lib = _staged("preview", decide)
    assert _passes(lib) == ([("s03", "promote", "p3")], [{"shotId": "s01", "reason": "preview"}])
    assert _passes(lib, explicit=True) == ([("s01", "preview", None), ("s03", "final", None)], []), "re-render on request"
    episode = lib["seriesById"]["uv"]["episodesById"]["ep1"]
    episode["shots"][2]["approvedAttemptId"] = "p3"
    assert _passes(lib) == ([], [{"shotId": "s01", "reason": "preview"}]), "a promoted preview is done"
    lib["seriesById"]["uv"]["assets"]["asset-p3"]["metadata"]["renderInputs"] = "older"
    assert _passes(lib)[0] == [("s03", "final", None)], "the kit changed after the approval: render the final again"
    assert _passes(lib, original=False) == ([("s03", "final", None)], [{"shotId": "s01", "reason": "preview"}])


def test_an_approved_3d_preview_at_draft_quality_still_needs_its_final():
    lib = library()
    series = lib["seriesById"]["uv"]
    shot = series["episodesById"]["ep1"]["shots"][0]
    shot.update(productionMethod="animation_3d", scene3d={"template": "deck", "quality": "final"})
    _take(series, shot, "p1", "preview")
    series["episodesById"]["ep1"]["review"] = {"mode": "preview", "shots": {"s01": _decided(shot, preview="approved", attempt="p1")}}
    planned, _waiting = render_passes(series, series["episodesById"]["ep1"], [shot], lambda item: render_inputs(series, item, KITS),
                                      explicit=False)
    assert [item["pass"] for item in planned] == ["final"]
    blockers = assembly_blockers(series["episodesById"]["ep1"])
    assert blockers[0] == {"shotId": "s01", "order": 1, "reason": "final"}
    assert [item["reason"] for item in blockers[1:]] == ["plan", "plan"], "every shot is reviewed, generated video too"
    versions = assembly_blockers(series["episodesById"]["ep1"], original=False)
    assert [item["shotId"] for item in versions] == ["s02", "s03"], "a version renders its finals directly"


def test_the_server_render_makes_previews_promotes_approved_ones_and_never_approves_a_preview(tmp_path):
    def decide(shots, series):
        _take(series, shots["s03"], "p3", "preview")
        return {"s01": _decided(shots["s01"]), "s03": _decided(shots["s03"], preview="approved", attempt="p3")}
    tools = Tools(tmp_path)
    render = _render(tmp_path, tools, _staged("preview", decide))
    job = render.start("cast", "uv", "ep1", approve=True)
    assert job["mode"] == "preview" and job["waiting"] == []
    assert [(item["shotId"], item.get("pass")) for item in job["items"]] == [("s01", "preview"), ("s03", "promote")]
    done = finished(render, job["jobId"], tmp_path)
    assert done["status"] == "completed", done
    imports = [args["input"] for tool, args in tools.calls if tool == "series.asset.import"]
    assert [(item["owner_id"], item["metadata"]["reviewStage"]) for item in imports] == [("s01", "preview")]
    approvals = [args["input"] for tool, args in tools.calls if tool == "series.take.approve"]
    assert [(item["shot_id"], item["attempt_id"]) for item in approvals] == [("s03", "p3")], "the preview waits for the user"
    speech = [args["input"]["output_name"] for tool, args in tools.calls if tool == "generation.speech"]
    assert speech and all("s03" not in name for name in speech), "a promotion renders nothing"


def test_a_final_pass_is_approved_and_marked_final(tmp_path):
    def decide(shots, series):
        _take(series, shots["s01"], "p1", "preview", inputs="before the kit changed")
        return {"s01": _decided(shots["s01"], preview="approved", attempt="p1"), "s03": _decided(shots["s03"], plan="pending")}
    tools = Tools(tmp_path)
    render = _render(tmp_path, tools, _staged("preview", decide))
    job = render.start("cast", "uv", "ep1", approve=False)
    assert [(item["shotId"], item.get("pass")) for item in job["items"]] == [("s01", "final")]
    assert job["waiting"] == [{"shotId": "s03", "reason": "plan"}]
    done = finished(render, job["jobId"], tmp_path)
    imports = [args["input"] for tool, args in tools.calls if tool == "series.asset.import"]
    assert imports[0]["metadata"]["reviewStage"] == "final" and done["items"][0]["approved"] is True


def test_a_render_with_nothing_approved_says_it_waits_for_the_review(tmp_path):
    render = _render(tmp_path, Tools(tmp_path), _staged("plan", lambda _shots, _series: {}))
    with pytest.raises(NativeRenderError) as waiting:
        render.start("cast", "uv", "ep1")
    assert waiting.value.code == "awaiting_review" and waiting.value.status == 409
    assert "2 shots wait" in str(waiting.value) and "2 plans" in str(waiting.value)


def test_a_3d_preview_is_exported_at_draft_quality(tmp_path, monkeypatch):
    from services import series_shot3d
    calls = []
    monkeypatch.setattr(series_shot3d, "build_scene", lambda *args, **kwargs: {"revision": 3, "document": {}, "file": "x.world3d.scene.json"})
    render = _render(tmp_path, lambda tool, arguments: calls.append((tool, arguments)) or {"result": {}}, library())
    shot = {"id": "s09", "order": 9, "sceneId": "scene_1", "productionMethod": "animation_3d", "dialogueBeats": [],
            "durationSeconds": 4, "scene3d": {"template": "deck", "quality": "final"}}
    series = library()["seriesById"]["uv"]
    episode = {"id": "ep1", "shots": [shot]}
    for pass_, quality in (("preview", "draft"), ("final", "final"), (None, "final")):
        item = {"shotId": "s09", "lines": {}, **({"pass": pass_} if pass_ else {})}
        render._scene3d("cast", {"jobId": "native-1", "language": "spanish"}, item, series, episode, shot, KITS)
        assert calls[-1][1]["input"]["quality"] == quality


def test_produce_waits_for_the_review_before_cutting_and_resumes_into_finals(tmp_path):
    tools = Production(fail_english=0)
    base = producer(tmp_path, tools)
    blockers = [[{"shotId": "e2s01", "order": 1, "reason": "preview"}], []]
    service = SeriesProduce(ProduceDeps(call=tools, workspace_dir=base.deps.workspace_dir, read_library=base.deps.read_library,
                                        review_blockers=lambda *_args: blockers[0], sleep=lambda _s: None, poll_seconds=0))
    waiting = produced(service, service.start("cast", "uv", "ep2", languages=["spanish"])["jobId"])
    assert waiting["status"] == "waiting" and waiting["waiting"] == blockers[0]
    assert "1 previews to approve" in waiting["message"]
    assert [step["status"] for step in waiting["steps"]] == ["queued", "queued"], "its renders run again on resume"
    assert not [tool for tool, _ in tools.calls if tool == "series.assembly.start"]
    blockers.pop(0)
    done = produced(service, service.resume("cast", waiting["jobId"])["jobId"])
    assert done["status"] == "completed" and "waiting" not in done
    assert [tool for tool, _ in tools.calls].count("series.episode.render_native") == 2
    assert [tool for tool, _ in tools.calls].count("series.assembly.start") == 1


def test_actionable_shots_follow_the_mode():
    def decide(shots, series):
        _take(series, shots["s03"], "p3", "preview")
        return {"s01": _decided(shots["s01"]), "s03": _decided(shots["s03"], preview="approved", attempt="p3")}
    lib = _staged("preview", decide)
    series = lib["seriesById"]["uv"]
    episode = series["episodesById"]["ep1"]
    shots = [shot for shot in episode["shots"] if shot["productionMethod"] == "animation_2d"]
    inputs = lambda shot: render_inputs(series, shot, KITS)
    assert actionable_shots(series, episode, shots, inputs, ["s03"]) == ["s01", "s03"], "a preview to make and one to promote"
    assert actionable_shots(series, episode, shots, inputs, ["s01", "s03"], original=False) == ["s03"]
    episode["review"]["mode"] = "plan"
    assert actionable_shots(series, episode, shots, inputs, ["s03"]) == ["s03"]
    episode["review"]["mode"] = "direct"
    assert actionable_shots(series, episode, shots, inputs, ["s01"]) == ["s01"]


def _gated(library, mode, plan):
    episode = library["seriesById"]["series-1"]["episodesById"]["episode-1"]
    episode["review"] = {"mode": mode, "shots": {shot["id"]: _decided(shot, plan=plan) for shot in episode["shots"]}}


def test_the_assembly_of_a_staged_episode_waits_for_its_review_unless_forced(tmp_path):
    endpoints, library_state = _client(tmp_path, lambda paths, output: bool(open(output, "wb").write(b"cut")))
    start = endpoints["/api/v1/series/{series_id}/episodes/{episode_id}/assembly/start"]
    _gated(library_state, "plan", "pending")
    with pytest.raises(HTTPException) as refused:
        start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "review_pending"
    assert [item["reason"] for item in refused.value.detail["blockers"]] == ["plan", "plan"]
    assert "2 shot plans to approve" in refused.value.detail["message"]
    forced = start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default", force=True))
    assert _wait_for_terminal(endpoints["/api/v1/series/assembly/jobs/{job_id}"], forced["jobId"])["status"] == "completed"
    _gated(library_state, "plan", "approved")
    approved = start("series-1", "episode-1", SeriesAssemblyStartRequest(workspace="default"))
    assert approved["status"] in {"queued", "running", "completed"}


def test_a_preview_episode_is_cut_once_every_preview_and_final_is_there():
    episode = copy.deepcopy(_staged("preview", lambda shots, _series: {})["seriesById"]["uv"]["episodesById"]["ep1"])
    assert [item["reason"] for item in assembly_blockers(episode)] == ["plan", "plan", "plan"]
    episode["review"]["mode"] = "direct"
    assert assembly_blockers(episode) == []


def test_rendering_only_changed_shots_follows_the_review(tmp_path):
    """Series Lab's "render what changed": out-of-date shots the review lets through, and an approved preview's promotion."""
    def decide(shots, series):
        _take(series, shots["s01"], "t1")
        shots["s01"]["approvedAttemptId"] = "t1"
        return {"s01": _decided(shots["s01"]), "s03": _decided(shots["s03"])}
    lib = _staged("plan", decide)
    render = _render(tmp_path, Tools(tmp_path), lib)
    job = render.start("cast", "uv", "ep1", changed=True)
    assert [item["shotId"] for item in job["items"]] == ["s03"], "s01 has an up-to-date approved take"
    finished(render, job["jobId"], tmp_path)
    lib["seriesById"]["uv"]["episodesById"]["ep1"]["review"]["shots"].pop("s03")
    with pytest.raises(NativeRenderError) as nothing:
        render.start("cast", "uv", "ep1", changed=True)
    assert nothing.value.code == "up_to_date"


def test_a_generated_take_is_promoted_once_its_preview_is_approved_and_its_cut_sound_keeps_the_review():
    from services.series_review_gate import shot_pass
    shot = {"id": "g1", "order": 1, "productionMethod": "generated_video", "layout2d": {"sfx": [{"file": "a.wav", "at": 0}]},
            "attempts": [{"id": "t1", "status": "completed", "outputAssetIds": ["x"]}, {"id": "t2", "status": "completed", "outputAssetIds": ["y"]}],
            "approvedAttemptId": "t1"}
    episode = {"id": "ep", "shots": [shot], "review": {"mode": "preview", "shots": {"g1": _decided(shot, preview="approved", attempt="t2")}}}
    assert shot_pass({}, episode, shot, lambda _shot: "x", explicit=False) == ("promote", "t2"), "the server never renders it"
    louder = {**shot, "layout2d": {"sfx": [{"file": "b.wav", "at": 1}]}}
    assert content_digest(louder) == content_digest(shot), "sound laid at the cut is not what the take shows"
    assert content_digest({**shot, "productionMethod": "animation_2d"}) != content_digest({**louder, "productionMethod": "animation_2d"})
