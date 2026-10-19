"""The stage of a 2D location plate: the perspective that sizes a person by where they stand and how tall they are."""
import json
from pathlib import Path

import pytest

from services import series_stage as stage_math

ROOT = Path(__file__).resolve().parents[1]
TABLE = json.loads((ROOT / "tests" / "fixtures" / "series_stage_table.json").read_text(encoding="utf-8"))
OFFICE = TABLE["stage"]


def test_the_formula_table_is_what_the_hand_calculation_gives():
    for row in TABLE["rows"]:
        feet, height = stage_math.standing(TABLE[row["stage"]], row["heightM"], row["depth"], row["zoom"], row["viewY"])
        assert (feet, height) == (pytest.approx(row["feetY"], abs=0.002), pytest.approx(row["height"], abs=0.002)), row


def test_the_door_is_the_unit_and_a_shorter_person_is_in_proportion():
    # Standing at the door's base, a 2 m figure is the door; 1.8 m is 0.9 of it.
    feet, door = stage_math.standing(OFFICE, 2.0, 0)
    assert feet == pytest.approx(72) and door == pytest.approx(62)
    # Same depth: Bigman (1.4 m) is 1.4 / 1.8 = 0.778 of Lucky (1.8 m).
    for depth in (0, 0.3, 1):
        lucky, bigman = (stage_math.standing(OFFICE, h, depth)[1] for h in (1.8, 1.4))
        assert bigman / lucky == pytest.approx(1.4 / 1.8, abs=1e-3)
    # A foreground adult is bigger than the door, the owner's «mas grande que la puerta».
    assert stage_math.standing(OFFICE, 1.8, 1)[1] > door


def test_a_figure_further_back_is_smaller_and_higher_in_the_frame():
    near, middle, far = (stage_math.standing(OFFICE, 1.8, depth) for depth in (1, 0.5, 0))
    assert near[0] > middle[0] > far[0] and near[1] > middle[1] > far[1]


def test_a_short_character_further_back_can_match_a_tall_one_in_front():
    """Bigman at the back wall is smaller than Lucky in front; moved forward he reaches Lucky's mid-depth height."""
    lucky_mid = stage_math.standing(OFFICE, 1.8, 0.2)[1]
    bigman = [stage_math.standing(OFFICE, 1.4, depth)[1] for depth in (0, 0.5, 1)]
    assert bigman[0] < lucky_mid < bigman[2]


def test_a_zoomed_plate_scales_the_figure_and_moves_the_feet_with_it():
    flat, zoomed = stage_math.standing(OFFICE, 1.8, 1), stage_math.standing(OFFICE, 1.8, 1, 1.12, 50)
    assert zoomed[0] == flat[0] == 94.0, "depth 1 is the framing's feet line whatever the zoom"
    # The plate is 1.12 times larger but the same feet line is further back on it (0.893 instead of 0.94): 84.1 %, not 90 %.
    assert zoomed[1] == pytest.approx(84.102, abs=0.002) and 80.352 < zoomed[1] < 80.352 * 1.12
    assert stage_math.frame_y(1.12, 50, 0.72) == pytest.approx(74.64)
    assert stage_math.plate_y(1.12, 50, 74.64) == pytest.approx(0.72)


def test_figure_height_is_the_pose_contained_in_the_frame():
    tall, wide = {"width": 450, "height": 1000}, {"width": 2400, "height": 1000}
    assert stage_math.figure_height(tall, 0.5, 16 / 9) == 50
    assert stage_math.figure_height(wide, 0.5, 16 / 9) == pytest.approx(50 * (16 / 9) / 2.4)


def test_expected_height_is_the_inverse_of_standing():
    feet, height = stage_math.standing(OFFICE, 1.6, 0.4, 1.12, 50)
    assert stage_math.expected_height(OFFICE, 1.6, feet, 1.12, 50) == pytest.approx(height, abs=0.01)


def test_a_stage_is_normalized_and_a_bad_one_is_refused():
    assert stage_math.normalize_stage({"horizon": 0.22, "ref": {"baseY": 0.72, "heightPct": 0.62}, "junk": 1}) == OFFICE
    assert stage_math.normalize_stage({**OFFICE, "floorTop": 0.9})["floorTop"] == 0.9
    for bad in ({"horizon": 0.8, "ref": {"baseY": 0.72, "heightPct": 0.62}},
                {"horizon": 0.22, "ref": {"baseY": 0.72, "heightPct": 0}},
                {"horizon": "high", "ref": {"baseY": 0.72, "heightPct": 0.62}},
                {"horizon": 0.22}, [],
                {**OFFICE, "floorTop": 0.1}):
        with pytest.raises(ValueError):
            stage_math.normalize_stage(bad)
    assert stage_math.location_stage({"layout2d": {"stage": OFFICE}}) == OFFICE
    assert stage_math.location_stage({"layout2d": {"stage": {"horizon": 2}}}) is None, "a render never stops for a bad stored stage"
    assert stage_math.location_stage({}) is None and stage_math.location_stage(None) is None


def test_depth_takes_a_number_or_a_word_and_the_rest_is_dropped():
    assert [stage_math.depth_value(value) for value in ("far", "Mid", "near", 0.25, 0, 1)] == [0.0, 0.5, 1.0, 0.25, 0.0, 1.0]
    assert [stage_math.depth_value(value) for value in ("middle", 1.5, -1, None, True)] == [None] * 5
    assert stage_math.cast_fields({"depth": "far", "heightM": 1.4, "x": 3}) == {"depth": 0.0, "heightM": 1.4}
    assert stage_math.cast_fields({"depth": 9, "heightM": 20}) == {}
    assert stage_math.cast_field_problems({"depth": 9, "heightM": 20}, "shot 1") == [
        "shot 1: depth must be a number from 0 to 1 or one of far, mid, near", "shot 1: heightM must be a number of metres from 0.2 to 6"]
    assert stage_math.cast_field_problems({"depth": "near", "heightM": 1.8}, "shot 1") == []


# The planner: what a located shot carries to the compiler ----------------------------------------------------------


def _series(stage=None, **more):
    character = lambda cid, **extra: {"id": cid, "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}", "workspace": "cast"}}, **extra}
    layout = {"homes": {"lucky": 34, "bigman": 66}, **({"stage": stage} if stage else {})}
    value = {"id": "ls", "title": "Lucky", "spokenLanguage": "Español de España",
             "characters": [character("lucky", layout2d={"heightM": 1.8}), character("bigman", layout2d={"heightM": 1.4, "scale": 0.78}),
                            character("giant", layout2d={"scale": 1.4}), character("plain")],
             "locations": [{"id": "office", "referenceAssetIds": ["asset_office"], "layout2d": layout},
                           {"id": "silos", "referenceAssetIds": ["asset_office"]}],
             "assets": {"asset_office": {"kind": "image", "uri": "office.png"}}}
    value.update(more)
    return value


def _spec(series, framing="wide", cast=None, location="office", **shot_more):
    from services.series_shot_plan import build_shot_spec
    entries = cast if cast is not None else [{"characterId": "lucky"}, {"characterId": "bigman"}]
    shot = {"id": "s1", "productionMethod": "animation_2d", "locationId": location, "visibleCharacterIds": [e["characterId"] for e in entries],
            "dialogueBeats": [], "durationSeconds": 3, "layout2d": {"framing": framing, "cast": entries}, **shot_more}
    return build_shot_spec(series, {"id": "ep1"}, shot, workspace="cast", recorded={})


def test_a_cast_entry_keeps_depth_and_height_and_drops_what_is_not_valid():
    from services.series_shot_plan import normalize_layout2d
    layout = normalize_layout2d({"cast": [{"characterId": "lucky", "depth": "far", "heightM": 1.8, "x": 30},
                                          {"characterId": "bigman", "depth": 0.4}, {"characterId": "gary", "depth": 3, "heightM": 99}]})
    assert layout["cast"] == [{"characterId": "lucky", "x": 30.0, "depth": 0.0, "heightM": 1.8}, {"characterId": "bigman", "depth": 0.4},
                              {"characterId": "gary"}]


def test_a_shot_on_a_calibrated_plate_carries_the_stage_and_each_person_s_height_and_depth():
    spec = _spec(_series(OFFICE), cast=[{"characterId": "lucky", "depth": "near"}, {"characterId": "bigman", "depth": 0.3},
                                        {"characterId": "giant"}, {"characterId": "plain", "heightM": 1.2, "scale": 0.5}])
    assert spec["stage"] == OFFICE
    lucky, bigman, giant, plain = spec["cast"]
    assert (lucky["heightM"], lucky["depth"]) == (1.8, 1.0) and (bigman["heightM"], bigman["depth"]) == (1.4, 0.3)
    assert giant["heightM"] == pytest.approx(1.75 * 1.4), "no height: an adult, times the character's own scale"
    assert "depth" not in giant and plain["heightM"] == 1.2, "an entry's own height wins"
    # The height replaces the character's own scale (Bigman's 0.78): only a scale the shot asks for still multiplies.
    assert [item["boost"] for item in (lucky, bigman, giant, plain)] == [1.0, 1.0, 1.0, 0.5]


def test_without_a_stage_or_outside_wide_and_two_the_spec_is_what_it_always_was():
    plain = _spec(_series())
    assert "stage" not in plain and all(not {"depth", "heightM"} & set(item) for item in plain["cast"])
    assert [item["boost"] for item in plain["cast"]] == [1.0, 0.78], "the character's own scale still sizes a plate without a stage"
    # Depth and height on a location without a stage change nothing in what the compiler is given.
    told = _spec(_series(), cast=[{"characterId": "lucky", "depth": 0.2, "heightM": 1.2}, {"characterId": "bigman"}])
    assert told == plain
    calibrated = _series(OFFICE)
    for framing in ("medium", "close"):
        eye_line = _spec(calibrated, framing, [{"characterId": "lucky", "depth": 0.5, "heightM": 1.2}])
        assert eye_line == _spec(_series(), framing, [{"characterId": "lucky"}]), "a medium shot or close-up keeps its eye-line framing"
    assert _spec(calibrated, location="silos") == _spec(_series(), location="silos"), "another location has no stage"
    assert _spec(calibrated, "two")["stage"] == OFFICE


def test_a_calibrated_shot_without_a_plate_has_no_stage():
    series = _series(OFFICE)
    series["locations"][0]["referenceAssetIds"] = []
    assert "stage" not in _spec(series)


# What a stage renders again --------------------------------------------------------------------------------------------


def test_a_location_stage_renders_again_only_the_2d_shots_in_it():
    from services.series_take_inputs import render_inputs
    from tests.test_series_layers import KITS, OWN, STREET, THREE, TWO, series as garage_series
    plain, staged = garage_series(), garage_series(stage=OFFICE)
    digest = lambda value, shot: render_inputs(value, shot, KITS)
    assert digest(staged, TWO) != digest(plain, TWO), "the 2D shot in the garage is sized by it"
    assert digest(staged, OWN) != digest(plain, OWN), "also a shot with its own layers: the cast is sized all the same"
    assert digest(staged, THREE) == digest(plain, THREE), "a 3D shot does not see a plate's perspective"
    assert digest(staged, STREET) == digest(plain, STREET), "nor does a shot elsewhere"
    moved = garage_series(stage={**OFFICE, "horizon": 0.3})
    assert digest(moved, TWO) not in (digest(plain, TWO), digest(staged, TWO))
    assert digest(garage_series(stage=OFFICE, layers=[{"file": "fog.webm", "depth": 0.5}]), TWO) != digest(staged, TWO), "layers still count"


def test_a_stored_location_stage_is_checked_and_normalized():
    from services.series_library import normalize_series_project
    base = {"id": "ls", "title": "Lucky", "locations": [{"id": "office", "name": "Office", "layout2d": {"stage": {
        "horizon": 0.22, "ref": {"baseY": 0.72, "heightPct": 0.62}, "junk": 1}}}]}
    stored = normalize_series_project(base, "ls", "cast")["locations"][0]["layout2d"]["stage"]
    assert stored == OFFICE
    bad = {**base, "locations": [{"id": "office", "layout2d": {"stage": {"horizon": 0.9, "ref": {"baseY": 0.72, "heightPct": 0.62}}}}]}
    with pytest.raises(ValueError, match=r"locations\[0\]\.layout2d\.stage"):
        normalize_series_project(bad, "ls", "cast")


def test_the_bible_shows_a_location_stage():
    from services.series_guide import build_bible
    from tests.test_series_layers import series as garage_series
    bible = build_bible(garage_series(stage=OFFICE), {}, ".")
    assert next(item for item in bible["locations"] if item["id"] == "garage")["stage"] == OFFICE


# The checks: figure_scale_off and stage_missing -------------------------------------------------------------------------


def _checked(cast, stage=None, framing="wide", plate=True, **shot_more):
    from services.series_script import apply_script
    from tests.test_series_script_produce import EN, FILES, SCRIPT, Series
    sized = {"base": {"width": 450, "height": 1000}, "poses": {}, **EN}
    tools = Series()
    tools.series["locations"][0] = {"id": "garage", "variants": [{"id": "night"}], "referenceAssetIds": ["asset_day"] if plate else [],
                                    "layout2d": {"stage": stage} if stage else {}}
    tools.series["assets"] = {"asset_day": {"kind": "image", "uri": "day.png"}}
    script = {**SCRIPT, "shots": [{"scene": "cold_open", "framing": framing, "cast": cast, **shot_more}]}
    kits = {"kit-kevin": sized, "kit-gary": sized}
    return apply_script(tools, tools.read, kits, FILES, "cast", script, check_only=True)["warnings"]


def _codes(warnings):
    return sorted((item["code"], item["subject"]) for item in warnings if item["code"] in ("figure_scale_off", "stage_missing"))


def test_a_plate_without_a_stage_gets_one_stage_missing_suggestion_for_all_its_wide_and_two_shots():
    from services.series_script import apply_script
    from tests.test_series_script_produce import EN, FILES, SCRIPT, Series
    tools = Series()
    tools.series["locations"][0] = {"id": "garage", "variants": [{"id": "night"}], "referenceAssetIds": ["asset_day"]}
    tools.series["assets"] = {"asset_day": {"kind": "image", "uri": "day.png"}}
    cast = [{"characterId": "kevin", "x": 30}]
    shots = [{"scene": "cold_open", "framing": framing, "cast": cast} for framing in ("wide", "two", "medium", "close")]
    shots.append({"scene": "cold_open", "framing": "title", "duration": 3, "card": {"kind": "title", "es": ["A", "B"]}})
    shots.append({"scene": "cold_open", "framing": "wide", "cast": []})
    shots.append({"scene": "cold_open", "framing": "wide", "cast": cast, "kind": "3d", "scene3d": {"scene": "mars.world3d.scene.json"}})
    kits = {"kit-kevin": {"base": {"width": 450, "height": 1000}, "poses": {}, **EN}}
    result = apply_script(tools, tools.read, kits, FILES, "cast", {**SCRIPT, "shots": shots}, check_only=True)
    missing = [item for item in result["warnings"] if item["code"] == "stage_missing"]
    assert len(missing) == 1 and missing[0]["subject"] == "garage"
    assert missing[0]["shots"] == ["e2s00", "e2s01"], "only the wide and the two-shot with a cast"
    assert "series.location.stage.check" in missing[0]["message"]


def test_no_plate_no_suggestion_and_a_calibrated_location_is_quiet():
    assert _codes(_checked([{"characterId": "kevin"}], plate=False)) == []
    assert _codes(_checked([{"characterId": "kevin"}, {"characterId": "gary", "depth": "far", "heightM": 1.4}], stage=OFFICE)) == []


def test_a_figure_off_the_perspective_is_flagged_and_one_on_it_is_not():
    # 450x1000 pose in a 16:9 frame: the image is 100 * scale tall, the figure 0.96 of it, feet 2 % of the image above its bottom.
    way_off = {"characterId": "kevin", "transform": {"x": 30, "y": 70, "scale": 0.3}}
    assert _codes(_checked([way_off], stage=OFFICE)) == [("figure_scale_off", "kevin")]
    feet, height = stage_math.standing(OFFICE, 1.75, 0.4)
    y, scale = stage_math.placement({"width": 450, "height": 1000}, feet, height, 16 / 9)
    on_it = {"characterId": "kevin", "transform": {"x": 30, "y": round(y, 3), "scale": round(scale, 3)}}
    assert _codes(_checked([on_it], stage=OFFICE)) == []
    warning = next(item for item in _checked([way_off], stage=OFFICE) if item["code"] == "figure_scale_off")
    assert warning["shots"] == ["e2s00"] and "0.43" in warning["message"] and "depth" in warning["message"]


def test_the_ratio_is_judged_with_the_limits_of_the_brief_and_a_scale_counts_too():
    assert _codes(_checked([{"characterId": "kevin", "scale": 0.7}], stage=OFFICE)) == [("figure_scale_off", "kevin")]
    assert _codes(_checked([{"characterId": "kevin", "scale": 1.4}], stage=OFFICE)) == [("figure_scale_off", "kevin")]
    assert _codes(_checked([{"characterId": "kevin", "scale": 0.8}, {"characterId": "gary", "scale": 1.3}], stage=OFFICE)) == []
    # In a two-shot the plate is shown at 1.12: the same perspective figure is drawn bigger and no warning comes of it.
    feet, height = stage_math.standing(OFFICE, 1.75, 1, 1.12, 50)
    y, scale = stage_math.placement({"width": 450, "height": 1000}, feet, height, 16 / 9)
    two = {"characterId": "kevin", "transform": {"x": 30, "y": round(y, 3), "scale": round(scale, 3)}}
    assert _codes(_checked([two], stage=OFFICE, framing="two")) == []
    assert _codes(_checked([{"characterId": "kevin", "scale": 0.3}], stage=OFFICE, framing="medium")) == []


def test_a_bad_depth_or_height_is_a_problem_of_the_script():
    from services.series_script import ScriptError
    with pytest.raises(ScriptError) as raised:
        _checked([{"characterId": "kevin", "depth": 2, "heightM": 12}], stage=OFFICE)
    assert any("depth must be a number from 0 to 1" in problem for problem in raised.value.problems)
    assert any("heightM must be a number of metres" in problem for problem in raised.value.problems)


def test_a_shot_edit_check_reports_the_same_warnings():
    import asyncio
    from routers.series_shot_edit import ShotEdit
    from tests.test_series_shot_edit import Library, _router
    import tempfile
    store = Library()
    store.series["locations"][0] = {"id": "garage", "variants": [{"id": "night"}], "referenceAssetIds": ["asset_day"]}
    store.series["assets"]["asset_day"] = {"id": "asset_day", "kind": "image", "uri": "outputs/day.png"}
    with tempfile.TemporaryDirectory() as folder:
        routes = _router(Path(folder), store)
        post = routes[("/api/v1/series/{series_id}/episodes/{episode_id}/shots/edit", "POST")]
        checked = asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=2, changes={"framing": "wide"}, check=True)))
        assert [item["code"] for item in checked["warnings"]] == ["stage_missing"] and checked["warnings"][0]["shots"] == ["e2s01"]
        store.series["locations"][0]["layout2d"] = {"stage": OFFICE}
        checked = asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=2, changes={"cast": [
            {"characterId": "kevin", "poseId": "panic", "x": 30, "scale": 0.4}, {"characterId": "gary", "x": 70}]}, check=True)))
        assert [(item["code"], item["subject"]) for item in checked["warnings"] if item["code"] != "look_room"] == [("figure_scale_off", "kevin")]
        quiet = asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=2, changes={"camera": "static"}, check=True)))
        assert not [item for item in quiet.get("warnings", []) if item["code"] in ("stage_missing", "figure_scale_off")], "only an edit that moves the picture"


# Planner to compiler, with the editor's own TypeScript -----------------------------------------------------------------


def _kit(name):
    states = ["closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue"]
    asset = lambda aid, kind="overlay", **size: {"id": aid, "name": aid, "kind": kind, "alphaStatus": "transparent", "reviewState": "approved",
                                                   "source": f"/api/v1/file/{aid}.png?workspace=cast", **size}
    return {"version": 1, "id": f"kit-{name}", "name": name, "style": "cutout", "base": asset(f"{name}-base", "image", width=450, height=1000),
            "poses": {}, "mouth": {state: asset(f"{name}-m-{state}") for state in states}, "eyes": {}, "provenance": [],
            "mouthMapping": {"rest": "closed", "M": "pressed", "A": "wide", "E": "medium", "I": "small", "O": "round", "U": "pucker", "F": "bite", "L": "tongue"},
            "anchors": {"base": {"mouth": {"offsetX": 0, "offsetY": -10, "scale": 0.1, "rotation": 0}}}}


def _compiled(series, framing="wide", cast=None):
    from services.series_shot_bridge import run_series_shot
    spec = _spec(series, framing, cast)
    document = run_series_shot({"mode": "shot", "kits": {"kit-lucky": _kit("lucky"), "kit-bigman": _kit("bigman")}, "shot": spec})
    return {name: next(layer for layer in document["layers"] if layer.get("characterKitRef", {}).get("id") == f"kit-{name}"
                       and not layer.get("faceBinding"))["transform"] for name in ("lucky", "bigman")}


@pytest.mark.skipif(__import__("shutil").which("node") is None, reason="node required")
def test_the_planned_shot_compiles_with_the_perspective_and_without_a_stage_as_before():
    from services.video2d_compile import TSX
    if not TSX.is_file():
        pytest.skip("ui/node_modules/tsx is not installed")
    staged = _compiled(_series(OFFICE), cast=[{"characterId": "lucky", "depth": 1}, {"characterId": "bigman", "depth": 1}])
    lucky, bigman = staged["lucky"]["scale"] * 96, staged["bigman"]["scale"] * 96  # the figure is 0.96 of the 450x1000 pose image
    assert lucky == pytest.approx(80.352, abs=0.06) and bigman / lucky == pytest.approx(1.4 / 1.8, abs=0.002)
    assert lucky > 62, "a foreground adult is taller than the 2 m door"
    behind = _compiled(_series(OFFICE), cast=[{"characterId": "lucky", "depth": 1}, {"characterId": "bigman", "depth": "far"}])
    assert behind["bigman"]["scale"] * 96 == pytest.approx(43.4, abs=0.06) and behind["bigman"]["y"] < behind["lucky"]["y"]
    plain = _compiled(_series())
    assert (plain["lucky"]["scale"], plain["bigman"]["scale"]) == (0.5 * 1.0, 0.5 * 0.78), "no stage: the framing and the character's scale, as ever"
    told = _compiled(_series(), cast=[{"characterId": "lucky", "depth": 0.1, "heightM": 3}, {"characterId": "bigman", "depth": 1}])
    assert told == plain, "depth and height mean nothing without a stage"


def test_python_and_the_compiler_share_the_feet_line_and_the_constants():
    source = (ROOT / "ui" / "scripts" / "seriesStage.ts").read_text(encoding="utf-8")
    assert f"FEET_LINE = {int(stage_math.FEET)}" in source and f"ADULT_M = {stage_math.ADULT_M}" in source
    assert f"FIGURE_MARGIN = {stage_math.FIGURE_MARGIN}" in source
    assert f"STAGE_FRAMINGS = {list(stage_math.FRAMINGS)!r}".replace("'", "'") in source
    assert "const FEET = FEET_LINE" in (ROOT / "ui" / "scripts" / "seriesShot.ts").read_text(encoding="utf-8")


# Calibration aids: the grid and the horizon guess ------------------------------------------------------------------------


def _converging(vanish_y, size=(640, 360)):
    """A plate of straight lines that all meet at (320, vanish_y * height): floor lines and a wall base, as in a corridor."""
    from PIL import Image, ImageDraw
    image = Image.new("RGB", size, (200, 200, 200))
    draw, (width, height) = ImageDraw.Draw(image), size
    point = (width / 2, vanish_y * height)
    for x in range(-200, width + 201, 60):
        draw.line((point[0], point[1], x, height), fill=(30, 30, 30), width=3)
    for x in range(-200, width + 201, 90):
        draw.line((point[0], point[1], x, 0), fill=(90, 90, 90), width=3)
    return image


def test_the_grid_has_a_line_every_ten_percent_and_the_stage_it_is_given():
    import numpy as np
    from PIL import Image
    from services.series_stage_grid import grid_image
    plate = Image.new("RGB", (1920, 1088), (40, 40, 40))
    grid = grid_image(plate)
    assert grid.size == (1280, 725), "at most 1280 wide, the plate's proportions"
    pixels = np.asarray(grid)
    for fraction in (0.1, 0.5, 0.9):
        row = round(fraction * 725)
        assert (pixels[row, 400] != 40).any(), f"a line at {fraction}"
    assert (pixels[round(0.55 * 725), 400] == 40).all(), "and none between"
    with_stage = np.asarray(grid_image(plate, stage=OFFICE))
    horizon = with_stage[round(0.22 * 725), 600]
    assert tuple(horizon) == (255, 0, 255), "the horizon of the stage is drawn in magenta"
    assert tuple(with_stage[round(0.72 * 725), 600]) == (60, 255, 60), "and the base of the reference in green"
    with pytest.raises(ValueError, match="step must be"):
        grid_image(plate, step=0.5)


def test_the_horizon_guess_finds_converging_lines_and_says_how_much_to_trust_it():
    from services.series_stage_grid import suggest_horizon
    pytest.importorskip("cv2")
    found = suggest_horizon(_converging(0.3))
    assert found["suggestion"]["kind"] == "converging_lines" and found["suggestion"]["confidence"] == "medium"
    assert found["suggestion"]["horizon"] == pytest.approx(0.3, abs=0.04)
    assert "not the truth" in found["note"]


def test_the_horizon_guess_of_an_open_place_is_the_strongest_horizontal_boundary_and_is_never_trusted_much():
    from PIL import Image
    from services.series_stage_grid import suggest_horizon
    sky = Image.new("RGB", (640, 360), (120, 160, 230))
    sky.paste(Image.new("RGB", (640, 360 - 198), (150, 90, 40)), (0, 198))
    found = suggest_horizon(sky)
    assert found["suggestion"]["kind"] == "horizontal_edge" and found["suggestion"]["confidence"] == "low"
    assert found["suggestion"]["horizon"] == pytest.approx(0.55, abs=0.02)
    assert suggest_horizon(Image.new("RGB", (640, 360), (90, 90, 90)))["suggestion"] is None, "a flat picture has nothing to find"


def test_without_the_line_detector_only_the_horizontal_edge_is_offered(monkeypatch):
    import builtins
    from services.series_stage_grid import suggest_horizon
    real = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError(name)) if name == "cv2" else real(name, *args, **kwargs))
    found = suggest_horizon(_converging(0.3))
    assert all(item["kind"] != "converging_lines" for item in found["candidates"])


# The operation: series.location.stage.set and .check, over HTTP, MCP and the Wizard ------------------------------------------


class _Store:
    """The series library as the routes see it: read a copy, change under a lock, bump the revision."""

    def __init__(self, series):
        self.series = series

    def read(self, _workspace):
        import copy
        return {"seriesById": {self.series["id"]: copy.deepcopy(self.series)}}

    def change(self, _workspace, series_id, change):
        import copy
        working = copy.deepcopy(self.series)
        change(working)
        working["revision"] = int(working.get("revision") or 1) + 1
        self.series = working
        return copy.deepcopy(working)


def _stage_routes(tmp_path, store):
    from routers.series_stage import create_series_stage_router
    from services.series_stage_ops import SeriesStage
    service = SeriesStage(read_library=store.read, change_series=store.change, workspace_dir=lambda _ws: str(tmp_path))
    router = create_series_stage_router(service, lambda _loop: None)
    return {(route.path, tuple(route.methods)[0]): route.endpoint for route in router.routes}


def _plate_series(tmp_path, stage=None):
    from PIL import Image
    Image.open  # noqa: B018 (Pillow is a hard dependency)
    _converging(0.3, (960, 540)).save(tmp_path / "day.png")
    value = _series(stage)
    value["revision"] = 3
    value["assets"]["asset_office"]["uri"] = "outputs/day.png"
    value["episodesById"] = {"ep1": {"id": "ep1", "shots": [
        {"id": "s1", "productionMethod": "animation_2d", "locationId": "office", "layout2d": {"framing": "wide", "cast": [{"characterId": "lucky"}]}},
        {"id": "s2", "productionMethod": "animation_2d", "locationId": "office", "layout2d": {"framing": "medium", "cast": [{"characterId": "lucky"}]}},
        {"id": "s3", "productionMethod": "animation_3d", "locationId": "office", "layout2d": {"framing": "wide", "cast": [{"characterId": "lucky"}]}},
        {"id": "s4", "productionMethod": "animation_2d", "locationId": "silos", "layout2d": {"framing": "wide", "cast": [{"characterId": "lucky"}]}}]}}
    return value


def test_setting_a_stage_stores_it_on_the_location_and_names_the_shots_it_resizes(tmp_path):
    import asyncio
    from routers.series_stage import StageSet
    store = _Store(_plate_series(tmp_path))
    set_stage = _stage_routes(tmp_path, store)[("/api/v1/series/{series_id}/locations/{location_id}/stage", "POST")]
    reply = asyncio.run(set_stage("ls", "office", StageSet(workspace="cast", horizon=0.22, ref={"baseY": 0.72, "heightPct": 0.62})))
    assert reply["stage"] == OFFICE and reply["locationId"] == "office" and reply["revision"] == 4
    assert reply["affectedShots"] == ["s1"], "the 2D wide and two-shots with people in that location"
    assert reply["eyeHeightM"] == pytest.approx(1.61, abs=0.01) and "warning" not in reply
    assert store.series["locations"][0]["layout2d"]["stage"] == OFFICE and store.series["locations"][0]["layout2d"]["homes"], "the rest is kept"
    far = asyncio.run(set_stage("ls", "office", StageSet(workspace="cast", horizon=0.2, ref={"baseY": 0.7, "heightPct": 0.6, "heightM": 2.1}, floorTop=0.65)))
    assert far["stage"]["floorTop"] == 0.65 and store.series["locations"][0]["layout2d"]["stage"]["ref"]["heightM"] == 2.1
    cleared = asyncio.run(set_stage("ls", "office", StageSet(workspace="cast", clear=True)))
    assert cleared["stage"] is None and "stage" not in store.series["locations"][0]["layout2d"]


def test_a_bad_stage_or_location_is_refused_and_nothing_is_written(tmp_path):
    import asyncio
    from fastapi import HTTPException
    from routers.series_stage import StageSet
    store = _Store(_plate_series(tmp_path))
    set_stage = _stage_routes(tmp_path, store)[("/api/v1/series/{series_id}/locations/{location_id}/stage", "POST")]
    for body, location, status in ((StageSet(workspace="cast", horizon=0.9, ref={"baseY": 0.72, "heightPct": 0.62}), "office", 422),
                                   (StageSet(workspace="cast", horizon=0.2), "office", 422),
                                   (StageSet(workspace="cast", horizon=0.2, ref={"baseY": 0.72, "heightPct": 0.62}), "nowhere", 404)):
        with pytest.raises(HTTPException) as raised:
            asyncio.run(set_stage("ls", location, body))
        assert raised.value.status_code == status, body
    assert store.series["revision"] == 3 and "stage" not in store.series["locations"][0]["layout2d"]


def test_checking_a_plate_writes_the_grid_into_the_workspace_and_answers_with_numbers_to_read_it_by(tmp_path):
    import asyncio
    from PIL import Image
    from routers.series_stage import StageCheck
    store = _Store(_plate_series(tmp_path))
    check = _stage_routes(tmp_path, store)[("/api/v1/series/{series_id}/locations/{location_id}/stage/check", "POST")]
    reply = asyncio.run(check("ls", "office", StageCheck(workspace="cast")))
    grid = reply["grid"]
    assert grid["file"].startswith("stage-check-office-") and (tmp_path / grid["file"]).is_file()
    assert grid["url"] == f"/api/v1/file/{grid['file']}?workspace=cast" and grid["step"] == 0.1
    assert Image.open(tmp_path / grid["file"]).size == (grid["width"], grid["height"]) == (960, 540)
    assert reply["plate"] == {"file": "day.png", "width": 960, "height": 540} and reply["stage"] is None and "proposal" not in reply
    assert reply["suggestion"]["note"] and "read" in reply["how"]
    assert store.series["revision"] == 3, "a check writes nothing to the series"
    again = asyncio.run(check("ls", "office", StageCheck(workspace="cast")))
    assert again["grid"]["file"] == grid["file"], "the same question names the same file"
    proposal = asyncio.run(check("ls", "office", StageCheck(workspace="cast", horizon=0.22, ref={"baseY": 0.72, "heightPct": 0.62}, step=0.05)))
    assert proposal["proposal"] == OFFICE and proposal["grid"]["file"] != grid["file"] and proposal["grid"]["step"] == 0.05
    assert proposal["eyeHeightM"] == pytest.approx(1.61, abs=0.01) and "eyeHeightM" not in reply
    odd = asyncio.run(check("ls", "office", StageCheck(workspace="cast", horizon=0.65, ref={"baseY": 0.72, "heightPct": 0.62})))
    assert odd["eyeHeightM"] < 0.3 and "camera" in odd["warning"], "a horizon read too low is told"
    store.series["locations"][0]["layout2d"]["stage"] = OFFICE
    saved = asyncio.run(check("ls", "office", StageCheck(workspace="cast")))
    assert saved["stage"] == OFFICE, "the saved stage is drawn over the grid"


def test_a_check_without_a_still_plate_says_what_is_missing(tmp_path):
    import asyncio
    from fastapi import HTTPException
    from routers.series_stage import StageCheck
    value = _plate_series(tmp_path)
    value["locations"][1]["referenceAssetIds"] = []
    check = _stage_routes(tmp_path, _Store(value))[("/api/v1/series/{series_id}/locations/{location_id}/stage/check", "POST")]
    with pytest.raises(HTTPException) as raised:
        asyncio.run(check("ls", "silos", StageCheck(workspace="cast")))
    assert raised.value.status_code == 422 and raised.value.detail["code"] == "no_plate"
    with pytest.raises(HTTPException) as raised:
        asyncio.run(check("ls", "office", StageCheck(workspace="cast", file="../secret.png")))
    assert raised.value.status_code == 422 and raised.value.detail["code"] == "bad_file"


def test_the_mcp_tools_call_the_same_routes():
    import asyncio
    from services.mcp_profiles import SERIES_TOOLS
    from services.series_commands import OPERATIONS, command_catalog
    from tests.test_series_commands import call, harness
    assert {"series.location.stage.set", "series.location.stage.check"} <= set(OPERATIONS) and {"series.location.stage.set", "series.location.stage.check"} <= SERIES_TOOLS
    assert OPERATIONS["series.location.stage.set"][2] is True and OPERATIONS["series.location.stage.check"][2] is False
    assert {item["name"] for item in command_catalog()} >= {"series.location.stage.set", "series.location.stage.check"}
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        handlers, calls, _workspace, _uploads = harness(Path(folder), [{"stage": OFFICE}, {"grid": {"file": "g.png"}}])
        call(handlers, "series.location.stage.set", {"workspace": "series", "series_id": "ls", "location_id": "office", "horizon": 0.22,
                                                     "ref": {"baseY": 0.72, "heightPct": 0.62}})
        call(handlers, "series.location.stage.check", {"workspace": "series", "series_id": "ls", "location_id": "office", "step": 0.05})
    assert [(method, url.split("9", 1)[1]) for method, url, _body in calls] == [
        ("POST", "/api/v1/series/ls/locations/office/stage"), ("POST", "/api/v1/series/ls/locations/office/stage/check")]
    assert calls[0][2] == {"workspace": "series", "horizon": 0.22, "ref": {"baseY": 0.72, "heightPct": 0.62}}
    assert calls[1][2] == {"workspace": "series", "step": 0.05}


def test_a_stage_says_how_high_it_puts_the_camera_so_a_misread_horizon_shows():
    assert stage_math.eye_height_m(OFFICE) == pytest.approx(1.61, abs=0.01)
    assert stage_math.eye_height_note(OFFICE) is None
    low = {"horizon": 0.69, "ref": {"baseY": 0.765, "heightPct": 0.145, "heightM": 1.1}}
    assert stage_math.eye_height_m(low) == pytest.approx(0.57, abs=0.01)
    assert "0.57 m high" in stage_math.eye_height_note(low) and "low angle" in stage_math.eye_height_note(low)
    assert "high angle" in stage_math.eye_height_note({"horizon": 0.1, "ref": {"baseY": 0.9, "heightPct": 0.3, "heightM": 2}})


def test_the_shot_edit_router_always_serves_the_stage_routes(tmp_path):
    """The stage routes ride on the shot edit router: mounted whenever it is, with or without the card's ``services``."""
    from routers.series_shot_edit import create_series_shot_edit_router
    router = create_series_shot_edit_router(change_series=lambda *_a: {}, read_library=lambda _w: {}, read_kits=lambda _w: {},
                                            workspace_dir=lambda _w: str(tmp_path), call=lambda *_a: {}, bind_loop=lambda _l: None)
    paths = {route.path for item in router.routes for route in (item.original_router.routes if hasattr(item, "original_router") else [item])}
    assert {"/api/v1/series/{series_id}/locations/{location_id}/stage", "/api/v1/series/{series_id}/locations/{location_id}/stage/check"} <= paths
