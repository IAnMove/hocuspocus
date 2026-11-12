"""The 2D finishes named like the 3D grades do what the 3D grade of that name does (review P9, H11).

A finish is compiled the way an agent and production get it: ``set_finish`` with the preset id on a document.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from services.production_lyric_looks import look_for
from services.scene2d_schema import document_schema
from services.video2d_catalogs import LINES
from services.video2d_edit import Video2dEditError, edit
from services.video2d_preset_catalog import finish_presets

SHARED = Path(__file__).resolve().parents[1] / "app" / "shared"
GRADES = json.loads((SHARED / "world3d_modifiers.json").read_text(encoding="utf-8"))["grades"]
OLD = ("warmCinema", "oldDoc", "nightNeon", "paperComic", "risoPress")
# The 3D screen effect and the 2D piece that paints it.
FX_PIECES = {"vignette": "vignette", "film_grain": "grain", "light_rays": "rays", "vhs": "vhs", "scanline": "scanlines"}
SCREEN_PIECES = ("gel", "bloom", "rays", "vignette", "grain", "texture", "letterbox", "vhs", "scanlines", "riso")


def _document() -> dict:
    layer = {"id": "plate", "name": "plate", "type": "image", "source": "/examples/plate.png", "visible": True, "z": 0,
             "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1, "rotation": 0},
             "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1}, "duration": 4,
                           "curve": "linear", "spin": False}}
    return {"version": 1, "name": "finish", "width": 1280, "height": 720, "fps": 30, "duration": 4, "layers": [layer]}


def _finish(operation: dict) -> dict:
    body = edit({"version": 1, "input": {"document": _document(), "operations": [{"op": "set_finish", **operation}], "full": True}})
    return body["result"]["document"]["finish"]


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def test_the_twelve_3d_grade_names_are_finishes_next_to_the_five_old_ones():
    assert list(finish_presets()) == [*OLD, *GRADES]


@pytest.mark.parametrize("name", list(GRADES))
def test_a_grade_name_mirrors_its_3d_grade(name):
    """Same tone curve, the same gel colour as the 3D lamp tint, the same screen effects, exposure on the same side."""
    grade3d, finish = GRADES[name], _finish({"preset": name})
    assert finish["grade"]["curve"] == grade3d["look"]["toneMapping"]
    assert finish.get("gel", {}).get("color") == grade3d.get("tint")
    for cue in grade3d["fx"]:
        assert finish[FX_PIECES[cue["kind"]]]["amount"] > 0, cue["kind"]
    painted = {FX_PIECES[cue["kind"]] for cue in grade3d["fx"]}
    assert {piece for piece in FX_PIECES.values() if piece in finish} == painted
    relative = grade3d["look"]["exposure"] + 0.5  # -0.5 is the 3D library's neutral exposure
    exposure = finish["grade"]["exposure"]
    assert (exposure > 0) == (relative > 0) and (exposure < 0) == (relative < 0), (exposure, relative)


PROMISES = {
    "natural": lambda f: set(f) == {"grade"} and abs(f["grade"]["saturation"]) <= 0.05 and f["grade"]["temperature"] == 0,
    "teal_orange": lambda f: _rgb(f["gel"]["color"])[0] > _rgb(f["gel"]["color"])[2]
    and _rgb(f["gel"]["shadows"])[2] > _rgb(f["gel"]["shadows"])[0] and f["grade"]["contrast"] > 0,
    "bleach": lambda f: f["grade"]["saturation"] <= -0.4 and f["grade"]["contrast"] >= 0.25
    and max(_rgb(f["gel"]["color"])) - min(_rgb(f["gel"]["color"])) <= 8,
    "noir": lambda f: f["grade"]["saturation"] <= -0.6 and f["grade"]["contrast"] >= 0.3 and f["grade"]["exposure"] < 0
    and f["vignette"]["amount"] >= 0.6 and _rgb(f["gel"]["color"])[2] > _rgb(f["gel"]["color"])[0],
    "sepia": lambda f: f["grade"]["saturation"] <= -0.4 and _rgb(f["gel"]["color"])[0] > _rgb(f["gel"]["color"])[1] > _rgb(f["gel"]["color"])[2],
    "flashback": lambda f: f["grade"]["fade"] >= 0.2 and f["grade"]["saturation"] < 0 and f["grade"]["temperature"] > 0,
    "dream": lambda f: f["grade"]["exposure"] > 0 and f["grade"]["contrast"] < 0 and f["bloom"]["amount"] > 0
    and min(_rgb(f["gel"]["color"])[0], _rgb(f["gel"]["color"])[2]) > _rgb(f["gel"]["color"])[1],
    "giallo": lambda f: _rgb(f["gel"]["color"])[0] >= 0xF0 and max(_rgb(f["gel"]["color"])[1:]) < 0x80 and f["grade"]["saturation"] > 0,
    "cold": lambda f: f["grade"]["temperature"] < 0 and _rgb(f["gel"]["color"])[2] > _rgb(f["gel"]["color"])[0],
    "warm": lambda f: f["grade"]["temperature"] > 0 and _rgb(f["gel"]["color"])[0] > _rgb(f["gel"]["color"])[2],
    "vhs": lambda f: f["vhs"]["amount"] >= 0.8 and f["scanlines"]["amount"] > 0,
    "film": lambda f: set(f) == {"grade", "grain"} and f["grain"]["amount"] > 0,
}


@pytest.mark.parametrize("name", list(PROMISES))
def test_a_finish_does_what_its_name_and_its_line_promise(name):
    finish = _finish({"preset": name})
    assert PROMISES[name](finish), finish
    assert LINES["finish"][name]["titleEn"] and LINES["finish"][name]["lineEs"]


@pytest.mark.parametrize("name", list(finish_presets()))
def test_every_preset_is_already_the_parsed_finish_and_a_valid_document(name):
    """Raw values and the preset id give the same finish, so a reopened scene keeps it; the schema accepts it."""
    preset = finish_presets()[name]
    assert _finish({"finish": preset}) == preset == _finish({"preset": name})
    document = {**_document(), "finish": preset}
    assert list(Draft202012Validator(document_schema()).iter_errors(document)) == []


def test_the_new_pieces_clamp_and_drop_what_the_renderer_cannot_read():
    finish = _finish({"finish": {
        "grade": {"exposure": 0, "contrast": 0, "saturation": 0, "temperature": 0, "tint": 0, "fade": 0, "curve": "reinhard"},
        "gel": {"color": "#ff0000", "amount": 3, "shadows": "teal"},
        "vhs": {"amount": -1}, "scanlines": {"amount": 0.4},
    }})
    assert "curve" not in finish["grade"]
    assert finish["gel"] == {"color": "#ff0000", "amount": 1}
    assert finish["vhs"] == {"amount": 0} and finish["scanlines"] == {"amount": 0.4}
    assert "gel" not in _finish({"finish": {"gel": {"color": "red", "amount": 1}, "vhs": {"amount": 1}}})
    with pytest.raises(Video2dEditError):
        _finish({"finish": {"gel": "red"}})


@pytest.mark.parametrize("name", list(finish_presets()))
def test_production_finds_a_lyric_look_for_every_finish(name):
    assert look_for({"finish": {"preset": name}}, "verse") is not None


def test_a_finish_name_alone_keeps_every_screen_piece_it_does_not_name_off():
    for name in GRADES:
        finish = _finish({"preset": name})
        assert "riso" not in finish and "letterbox" not in finish and "texture" not in finish, name
        assert set(finish) <= {"grade", *SCREEN_PIECES}, name
