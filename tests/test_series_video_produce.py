"""Production's real selection, review and native worker over already imported video takes."""
import copy

import pytest

from services.series_produce import ProduceDeps, SeriesProduce
from services.series_review import apply_review_change
from services.series_take_sound import _foley_source, plan_take_sound
from tests.test_series_native_render import finished, library
from tests.test_series_script_produce import Production, finished as produced
from tests.test_series_shot_foley import AIRSHIP, FoleyTools, _video_take, foley_render


def _production(tmp_path, method, prompt, preview):
    data = library()
    shot = _video_take(data, tmp_path, foley=dict(AIRSHIP) if prompt else None)
    shot["productionMethod"] = method
    episode = data["seriesById"]["uv"]["episodesById"]["ep1"]
    episode["shots"] = [shot]
    if preview:
        shot.pop("approvedAttemptId")
        apply_review_change(episode, {"mode": "preview", "shots": [{"shotId": "s02", "preview": "approved"}]}, now="now")
        shot = episode["shots"][0]

    class Tools(FoleyTools):
        def __call__(self, name, arguments):
            if name == "series.take.approve":
                shot["approvedAttemptId"] = arguments["input"]["attempt_id"]
            return super().__call__(name, arguments)

    tools = Tools(tmp_path)
    render = foley_render(tmp_path, tools, data, [], probe=lambda _: 4.0)
    cuts = Production(fail_english=0)

    def call(name, arguments):
        payload = arguments["input"]
        if name == "series.episode.render_native":
            job = render.start(payload["workspace"], payload["series_id"], payload["episode_id"],
                               shot_ids=payload.get("shot_ids"), changed=payload.get("changed", False), approve=True)
            return {"result": {"job": job}}
        if name == "series.episode.render_native.status":
            return {"result": {"job": render.status(payload["workspace"], payload["job_id"])}}
        return cuts(name, arguments)

    service = SeriesProduce(ProduceDeps(call=call, workspace_dir=lambda _: str(tmp_path), read_library=lambda _: data,
        stale_shots=render.stale_shots, review_blockers=render.review_blockers, poll_seconds=0.001))
    return service, render, tools, shot, data


@pytest.mark.parametrize("method", ["generated_video", "imported_video"])
@pytest.mark.parametrize("prompt", [True, False])
def test_production_promotes_a_reviewed_video_and_prepares_its_optional_foley(tmp_path, method, prompt):
    service, render, tools, shot, data = _production(tmp_path, method, prompt, preview=True)
    done = produced(service, service.start("cast", "uv", "ep1")["jobId"])
    assert done["status"] == "completed", done
    assert shot["approvedAttemptId"] == "att-h3" and done["chapters"]["spanish"]["file"] == "spanish.mp4"
    assert render.stale_shots("cast", "uv", "ep1") == [], "the promotion and sound are not repeated on every production"
    assert len([name for name, _ in tools.calls if name == "generation.sfx"]) == int(prompt)
    assert not [name for name, _ in tools.calls if name in ("generation.speech", "series.asset.import")]
    if prompt:
        series = data["seriesById"]["uv"]
        clips = [{"shotId": "s02"}]
        plan_take_sound(series, series["episodesById"]["ep1"], clips)
        assert _foley_source(str(tmp_path), str(tmp_path / "assets/uv/asset_h3.mp4"), clips[0]["takeSound"]["foley"], lambda _: 1)


def test_an_explicit_video_promotion_also_makes_missing_foley(tmp_path):
    _service, render, tools, shot, _data = _production(tmp_path, "imported_video", True, preview=True)
    done = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s02"])["jobId"], tmp_path)
    assert done["status"] == "completed", done
    assert shot["approvedAttemptId"] == "att-h3"
    assert any(name == "generation.sfx" for name, _ in tools.calls)
    assert (tmp_path / done["items"][0]["foley"]["file"]).is_file()


def test_direct_production_reuses_foley_until_the_prompt_or_take_changes(tmp_path):
    service, render, tools, shot, _data = _production(tmp_path, "generated_video", True, preview=False)
    for change in (None, "volume", "prompt", "take"):
        if change == "volume":
            shot["foley"]["volume"] = 0.2
        elif change == "prompt":
            shot["foley"]["prompt"] = "rain"
        elif change == "take":
            (tmp_path / "assets/uv/asset_h3.mp4").write_bytes(b"new take")
        assert render.stale_shots("cast", "uv", "ep1") == ([] if change == "volume" else ["s02"])
        assert produced(service, service.start("cast", "uv", "ep1")["jobId"])["status"] == "completed"
    assert len([name for name, _ in tools.calls if name == "generation.sfx"]) == 3
    assert all((tmp_path / item["foley"]["file"]).is_file() for job in render.jobs("cast") for item in job["items"])


def test_promotion_foley_uses_the_newly_approved_take_and_can_retry_a_warning(tmp_path):
    service, render, tools, shot, data = _production(tmp_path, "imported_video", True, preview=True)
    shot["attempts"].insert(0, {"id": "old", "status": "completed", "outputAssetIds": ["old-asset"]})
    shot["approvedAttemptId"] = "old"
    data["seriesById"]["uv"]["assets"]["old-asset"] = {"kind": "video", "uri": "old.mp4"}
    (tmp_path / "old.mp4").write_bytes(b"old picture")
    render.deps.read_library = lambda _: copy.deepcopy(data)
    tools.sfx = "missing"
    first = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s02"])["jobId"], tmp_path)
    assert first["status"] == "completed" and "Foley left out" in first["items"][0]["warning"]
    assert shot["approvedAttemptId"] == "att-h3"
    assert render.stale_shots("cast", "uv", "ep1") == ["s02"]
    tools.sfx = "ok"
    assert produced(service, service.start("cast", "uv", "ep1")["jobId"])["status"] == "completed"
    assert render.stale_shots("cast", "uv", "ep1") == []
    requests = [args["input"]["params"] for name, args in tools.calls if name == "generation.sfx"]
    assert all(request["video_guide"].endswith("assets/uv/asset_h3.mp4?workspace=cast") for request in requests)
