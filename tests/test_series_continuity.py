"""A 2D Series shot takes its crop and its camera from its neighbours: a lone character's close-up shows its side of
the room, and a shot that shows the previous shot's picture goes on from its camera instead of cutting back."""
from services.series_continuity import CAMERA_LIMIT, camera_start, focus, inputs, ordered, same_picture_warnings
from services.series_shot_plan import background_point, build_shot_spec, normalize_layout2d
from services.series_take_inputs import render_inputs


def series():
    character = lambda cid: {"id": cid, "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}", "workspace": "cast"}}}
    return {"id": "lc", "title": "Latencia", "spokenLanguage": "Español de España",
            "characters": [character("ivan"), character("nerea")],
            "locations": [{"id": "calle", "referenceAssetIds": ["asset_street"]}, {"id": "capsula", "referenceAssetIds": ["asset_room"]},
                          {"id": "altavoz", "referenceAssetIds": ["asset_speaker"]}],
            "assets": {"asset_street": {"kind": "image", "uri": "street.png"}, "asset_room": {"kind": "image", "uri": "room.png"},
                       "asset_speaker": {"kind": "image", "uri": "speaker.png"}}}


def shot(sid, order, location, framing, cast=(), camera="push", scene="a", **extra):
    layout = {"framing": framing, "camera": camera, "cast": [{"characterId": cid, **({"x": x} if x is not None else {})} for cid, x in cast]}
    return {"id": sid, "order": order, "sceneId": scene, "locationId": location, "productionMethod": "animation_2d",
            "durationSeconds": 4, "layout2d": layout, **extra}


def episode(*shots):
    return {"id": "ep1", "title": "Piloto", "shots": list(shots)}


def spec(value, ep, sid):
    return build_shot_spec(value, ep, next(item for item in ep["shots"] if item["id"] == sid), workspace="cast", recorded={})


def test_the_same_still_plate_twice_goes_on_pushing_and_warns():
    ep = episode(shot("s1", 1, "calle", "insert"), shot("s2", 2, "calle", "insert"), shot("s3", 3, "calle", "insert", camera="static"))
    first, second, third = (spec(series(), ep, sid) for sid in ("s1", "s2", "s3"))
    assert "cameraStart" not in first and first["camera"] == "push"
    assert second["cameraStart"] == {"scale": 1.07, "y": 48.5} and second["camera"] == "push", "it starts where s1's push ended"
    assert third["cameraStart"] == {"scale": 1.14, "y": 47.0} and third["camera"] == "static", "a static shot holds there"
    warnings = same_picture_warnings(series(), ep["shots"])
    assert [(item["code"], item["shots"]) for item in warnings] == [("same_picture", ["s1", "s2"]), ("same_picture", ["s2", "s3"])]
    assert "make it one shot, or frame a detail of the same plate (detail)" in warnings[0]["message"]


def test_another_plate_or_framing_starts_the_camera_at_rest():
    ep = episode(shot("s1", 1, "calle", "insert"), shot("s2", 2, "altavoz", "insert"), shot("s3", 3, "altavoz", "wide", [("ivan", None)]))
    assert [camera_start(series(), ordered(ep), item) for item in ep["shots"]] == [None, None, None]
    assert same_picture_warnings(series(), ep["shots"]) == []


def test_a_push_stops_growing_at_the_limit_and_holds():
    ep = episode(*(shot(f"s{n}", n, "calle", "insert") for n in range(1, 8)))
    starts = [camera_start(series(), ordered(ep), item) for item in ep["shots"]]
    assert all(start[0] <= CAMERA_LIMIT for start in starts[1:]) and starts[-1][2] is False
    assert starts[-1][0] == starts[-2][0], "past the limit the camera holds where it got to"


def test_a_lone_close_up_shows_its_side_of_the_room():
    two = shot("s1", 1, "capsula", "two", [("ivan", 32), ("nerea", 70)], camera="static")
    ep = episode(two, shot("s2", 2, "capsula", "close", [("nerea", 50)]), shot("s3", 3, "capsula", "close", [("ivan", 50)], scene="b"))
    shots = ordered(ep)
    assert [focus(series(), shots, item, item["layout2d"]["framing"]) for item in shots] == [51.0, 70.0, 32.0]
    nerea, ivan = spec(series(), ep, "s2"), spec(series(), ep, "s3")
    assert (nerea["background"]["focusX"], ivan["background"]["focusX"]) == (70.0, 32.0)
    assert [item["x"] for item in nerea["cast"]] == [50.0], "the cutout stays where the script put it"
    assert "cameraStart" not in ivan, "shot and reverse shot are two pictures"


def test_the_place_is_the_nearest_wider_shot_of_the_scene_else_the_home():
    value = series()
    value["locations"][1]["layout2d"] = {"homes": {"ivan": 20}}
    ep = episode(shot("s1", 1, "capsula", "wide", [("ivan", 34)], scene="other"), shot("s2", 2, "capsula", "close", [("ivan", None)]),
                 shot("s3", 3, "capsula", "two", [("ivan", 40), ("nerea", 60)]))
    assert focus(value, ordered(ep), ep["shots"][1], "close") == 40.0, "the same scene first, even after the close-up"
    alone = episode(shot("s2", 2, "capsula", "close", [("ivan", None)]))
    assert focus(value, ordered(alone), alone["shots"][0], "close") == 20.0, "no wider shot: its home"
    assert focus(series(), ordered(alone), alone["shots"][0], "close") == 50.0, "nothing known: the centre, as before"


def test_a_take_renders_again_when_its_neighbours_move_its_picture():
    value, kits = series(), {}
    ep = episode(shot("s1", 1, "calle", "insert"), shot("s2", 2, "calle", "insert"))
    alone = episode(shot("s1", 1, "calle", "insert"))
    first = ep["shots"][0]
    assert inputs(value, ep, first) == {} and render_inputs(value, first, kits, episode=ep) == render_inputs(value, first, kits), \
        "a shot that takes nothing from its neighbours keeps its digest"
    second = ep["shots"][1]
    assert inputs(value, ep, second) == {"cameraStart": [1.07, 48.5, True]}
    static_first = episode({**first, "layout2d": {**first["layout2d"], "camera": "static"}}, second)
    assert render_inputs(value, second, kits, episode=ep) != render_inputs(value, second, kits, episode=static_first)
    assert inputs(value, alone, first) == {}


def test_from_script_check_warns_about_the_same_picture_twice():
    from services.series_script import apply_script
    project = {**series(), "revision": 1, "episodesById": {}}
    script = {"title": "Latencia", "scenes": [{"id": "prologo", "location": "calle"}],
              "shots": [{"scene": "prologo", "framing": "insert", "camera": "push", "duration": 5},
                        {"scene": "prologo", "framing": "insert", "camera": "push", "duration": 5},
                        {"scene": "prologo", "framing": "insert", "camera": "push", "duration": 5, "location": "altavoz"},
                        {"scene": "prologo", "framing": "insert", "camera": "push", "duration": 5, "location": "altavoz",
                         "detail": {"x": 56, "y": 18, "zoom": 1.8}}]}
    checked = apply_script(lambda tool, data: {"result": {}}, lambda: project, {}, set(), "lc", script, check_only=True)
    found = [item for item in checked["warnings"] if item["code"] == "same_picture"]
    assert [item["shots"] for item in found] == [["e1s00", "e1s01"]], "the loudspeaker has its own location, then a detail of it"


def test_a_detail_frames_the_same_plate_closer():
    assert normalize_layout2d({"detail": {"x": 56, "y": 18, "zoom": 1.8}}) == {"detail": {"x": 56.0, "y": 18.0, "zoom": 1.8}}
    assert normalize_layout2d({"detail": {"x": 56, "y": 18}}) is None and normalize_layout2d({"detail": {"x": 56, "y": 18, "zoom": 9}}) is None
    value = series()
    value["locations"][0]["layout2d"] = {"anchors": {"kiosk": {"u": 0.6, "v": 0.3}}}
    detail = {"x": 56.0, "y": 18.0, "zoom": 1.8}
    wide = shot("s1", 1, "calle", "insert")
    close = shot("s2", 2, "calle", "insert", props=None)
    close["layout2d"].update(detail=detail, props=[{"file": "prop-sign.png", "anchor": "kiosk", "scale": 0.2}])
    ep = episode(wide, close)
    planned = spec(value, ep, "s2")
    assert planned["background"]["detail"] == detail and "cameraStart" not in planned, "a detail is another picture: its own push"
    prop = planned["props"][0]
    assert prop["scale"] == round(0.2 * 1.8, 4)
    assert (prop["x"], prop["y"] + prop["scale"] * 50) == background_point("insert", 50.0, 0.6, 0.3, detail), "it stays on its anchor"
    assert background_point("insert", 50.0, 0.56, 0.18, detail) == (50.0, 32.4), \
        "the point is centred across; near the top it stays high, the plate's edge in the frame's"
    assert same_picture_warnings(value, ep["shots"]) == []
