"""Mutable 3D sources invalidate only the shots that use their rendered content."""
import copy
import json

import pytest

from services import series_shot3d
from services.series_native_render import NativeRenderDeps, NativeRenderError, SeriesNativeRender
from services.series_review import apply_review_change
from tests.test_series_native_render import finished
from tests.test_series_shot_extras import RenderTools


def _save_source(root, kind, document):
    if kind == "scene":
        path, payload = root / "set.world3d.scene.json", document
    else:
        path = root / "world3d-user-templates.json"
        payload = {"templates": [{"id": "user-set", "title": "Set", "document": document}]}
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize("source", ["scene", "template"])
@pytest.mark.parametrize("review", ["direct", "preview"])
def test_editing_a_3d_source_invalidates_the_take_and_renders_its_current_inputs(tmp_path, source, review):
    document = {"version": 1, "duration": 2, "slots": [], "camera": {"position": [0, 1, 3]}}
    _save_source(tmp_path, source, document)
    config = {source: "set.world3d.scene.json" if source == "scene" else "user-set"}
    shot = {"id": "s", "order": 1, "productionMethod": "animation_3d", "scene3d": config, "durationSeconds": 2}
    episode = {"id": "ep", "shots": [shot]}
    series = {"id": "series", "spokenLanguage": "English", "episodesById": {"ep": episode}, "assets": {}}
    class SourceTools(RenderTools):
        def __call__(self, name, arguments):
            if name == "scenes.document.get":
                path = tmp_path / arguments["input"]["file"]
                return {"result": {"document": json.loads(path.read_text(encoding="utf-8"))}}
            return super().__call__(name, arguments)

    tools = SourceTools(tmp_path)
    render = SeriesNativeRender(NativeRenderDeps(call=tools, workspace_dir=lambda _: str(tmp_path),
        read_library=lambda _: {"seriesById": {"series": series}}, read_kits=lambda _: {}, sleep=lambda _: None))
    first = finished(render, render.start("cast", "series", "ep", approve=True)["jobId"], tmp_path)
    assert first["status"] == "completed", first
    metadata = next(args["input"]["metadata"] for name, args in tools.calls if name == "series.asset.import")
    series["assets"]["take"] = {"metadata": metadata}
    shot.update(approvedAttemptId="take", attempts=[{"id": "take", "status": "completed", "outputAssetIds": ["take"]}])
    if review == "preview":
        apply_review_change(episode, {"mode": review, "shots": [{"shotId": "s", "preview": "approved"}]}, now="now")
    assert render.stale_shots("cast", "series", "ep") == []
    source_path = tmp_path / ("set.world3d.scene.json" if source == "scene" else "world3d-user-templates.json")
    source_path.write_text(json.dumps(json.loads(source_path.read_text()), indent=4), encoding="utf-8")
    assert render.stale_shots("cast", "series", "ep") == [], "JSON formatting does not alter the rendered source"

    document["camera"]["position"][0] = 4
    _save_source(tmp_path, source, document)
    assert render.stale_shots("cast", "series", "ep") == ["s"]
    second = finished(render, render.start("cast", "series", "ep", changed=True)["jobId"], tmp_path)
    assert second["status"] == "completed", second
    imports = [args["input"]["metadata"] for name, args in tools.calls if name == "series.asset.import"]
    assert imports[-1]["renderInputs"] != metadata["renderInputs"]
    if source == "scene":
        registered = [args["input"] for name, args in tools.calls if name == "world3d.templates.user.put"]
        assert registered[-1]["document"]["camera"]["position"][0] == 4
        assert registered[0]["id"] != registered[-1]["id"]
    if review == "preview":
        assert second["items"][0]["pass"] == "final", "a changed source cannot promote the old preview"


def test_saved_scene_registration_and_instantiation_intents_follow_the_document(tmp_path):
    document = {"version": 1, "slots": [], "duration": 2}
    intents, registered, reads = {}, [], []
    tools = RenderTools(tmp_path)

    def call(name, arguments):
        if name == "scenes.document.get":
            reads.append(arguments)
            return {"result": {"document": copy.deepcopy(document)}}
        if name == "world3d.templates.user.put":
            intent, payload = arguments["intent_id"], arguments["input"]
            assert intent not in intents or intents[intent] == payload, "a changed document must not conflict with its old intent"
            intents[intent] = copy.deepcopy(payload)
            registered.append(payload["id"])
        return tools(name, arguments)

    shot = {"id": "s", "scene3d": {"scene": "set.world3d.scene.json"}}
    for duration in (2, 3, 3):
        document["duration"] = duration
        series_shot3d.build_scene(call, "cast", "same-job", shot, [], 2, {}, {}, NativeRenderError)
    assert registered[0] != registered[1] == registered[2]
    assert len(reads) == 3, "each render resolves its template once and passes it to the shared editor helper"
    instantiate = [args["intent_id"] for name, args in tools.calls if name == "world3d.scene.instantiate"]
    assert instantiate[0] != instantiate[1] == instantiate[2], "resume replays only the same source revision"


@pytest.mark.parametrize("source", ["scene", "template"])
def test_opening_the_editor_follows_source_edits_and_reads_a_saved_scene_once(tmp_path, source):
    from services.series_shot3d_editor import editor_scene
    from tests.test_series_shot3d_editor import World3D

    document = {"version": 1, "duration": 2, "slots": []}
    tools, reads = World3D(), []

    def call(name, arguments):
        if name == "scenes.document.get":
            reads.append(arguments)
            return {"result": {"document": copy.deepcopy(document)}}
        if name == "world3d.templates.user.put":
            return {"result": {"template": {"id": arguments["input"]["id"]}}}
        return tools(name, arguments)

    shot = {"id": "s", "productionMethod": "animation_3d", "durationSeconds": 2,
            "scene3d": {source: "set.world3d.scene.json" if source == "scene" else "user-set"}}
    for duration in (2, 3, 3):
        document["duration"] = duration
        _save_source(tmp_path, source, document)
        editor_scene(call, "cast", str(tmp_path), {}, {"id": "ep", "shots": [shot]}, shot)
    intents = [args["intent_id"] for name, args in tools.calls if name == "world3d.scene.instantiate"]
    assert intents[0] != intents[1] == intents[2], "the editor must not replay an older source revision"
    assert len(reads) == (3 if source == "scene" else 0)
