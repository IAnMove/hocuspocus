"""A cutout's pixels say which edges its figure is cut by and where a prop's feet are."""
import os
import shutil

import pytest
from PIL import Image, ImageDraw

from services.series_cutouts import cut_edges, ground_props, measure
from services.series_shot_bridge import measure_props, with_pose_sizes
from services.series_shot_plan import build_shot_spec, normalize_layout2d


def image(path, size=(200, 400), boxes=(), mode="RGBA"):
    """A transparent image with opaque rectangles (x0, y0, x1, y1), inclusive pixel boxes."""
    picture = Image.new(mode, size, (0, 0, 0, 0) if mode == "RGBA" else (0, 0, 0))
    draw = ImageDraw.Draw(picture)
    for box in boxes:
        draw.rectangle(box, fill=(200, 120, 80, 255) if mode == "RGBA" else (200, 120, 80))
    picture.save(path)
    return path


def test_a_bust_cut_at_the_chest_and_on_one_side_reports_those_edges(tmp_path):
    # Shoulders run off the left border from 60 % of the height down, and the chest off the bottom.
    bust = image(tmp_path / "bust.png", boxes=[(0, 240, 150, 399), (40, 40, 140, 240)])
    assert cut_edges(bust) == {"left": [[0.6, 1.0]], "bottom": [[0.0, 0.755]]}
    mirrored = tmp_path / "mirrored.png"
    Image.open(bust).transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(mirrored)
    assert cut_edges(mirrored) == {"right": [[0.6, 1.0]], "bottom": [[0.245, 1.0]]}, "a mirrored pose is cut on the other side"


def test_stray_pixels_hair_strands_and_feet_on_the_border_are_not_cuts(tmp_path):
    standing = image(tmp_path / "standing.png", boxes=[
        (0, 0, 0, 0), (199, 399, 199, 399),  # keyed corner pixels
        (0, 100, 1, 110),  # a strand of hair touching the side: under 8 % of the height
        (60, 20, 140, 370), (70, 370, 90, 399), (110, 370, 130, 399),  # two feet resting on the bottom: each under 15 %
    ])
    assert cut_edges(standing) == {}
    # A soft keyed border one pixel in still counts, and a dark seam a pixel wide does not split a cut.
    soft = image(tmp_path / "soft.png", boxes=[(1, 100, 80, 200), (1, 202, 80, 299)])
    assert cut_edges(soft) == {"left": [[0.25, 0.75]]}


def test_a_picture_or_an_image_without_alpha_is_not_a_cutout(tmp_path):
    assert cut_edges(image(tmp_path / "plate.png", boxes=[(0, 0, 199, 399)])) == {}
    assert cut_edges(image(tmp_path / "flat.png", mode="RGB", boxes=[(0, 200, 100, 399)])) == {}
    assert cut_edges(tmp_path / "missing.png") == {} and measure(tmp_path / "missing.png") is None
    (tmp_path / "broken.png").write_bytes(b"not a png")
    assert measure(tmp_path / "broken.png") is None


def test_the_lowest_opaque_row_ignores_corner_pixels_and_a_new_file_is_read_again(tmp_path):
    alien = image(tmp_path / "alien.png", boxes=[(80, 20, 120, 359), (199, 399, 199, 399)])
    assert measure(alien) == ((200, 400), {}, 0.9)
    stat = os.stat(alien)
    image(alien, boxes=[(80, 20, 120, 379)])
    os.utime(alien, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert measure(alien)[2] == 0.95, "the cache follows the file version"
    found = measure(alien)
    found[1]["left"] = [[0, 1]]
    assert measure(alien)[1] == {}, "callers get their own copy"


def test_kits_get_their_cut_edges_and_keep_stored_sizes(tmp_path):
    image(tmp_path / "bust.png", boxes=[(0, 240, 150, 399), (40, 40, 140, 240)])
    image(tmp_path / "whole.png", boxes=[(40, 20, 160, 380)])
    kit = {"id": "kit-b", "base": {"source": "/api/v1/file/whole.png?workspace=cast"},
           "poses": {"bust": {"source": "/api/v1/file/bust.png?workspace=cast", "width": 900, "height": 1800},
                     "lost": {"source": "/api/v1/file/nowhere.png?workspace=cast"}}}
    sized = with_pose_sizes(kit, str(tmp_path))
    assert sized["base"] == {"source": kit["base"]["source"], "width": 200, "height": 400}, "an uncut figure gets no cut"
    assert sized["poses"]["bust"]["cut"] == {"left": [[0.6, 1.0]], "bottom": [[0.0, 0.755]]}
    assert (sized["poses"]["bust"]["width"], sized["poses"]["bust"]["height"]) == (900, 1800), "stored sizes are kept"
    assert sized["poses"]["lost"] == kit["poses"]["lost"] and "cut" not in kit["poses"]["bust"], "the library kit is not changed"


def test_grounded_props_are_measured_and_an_unreadable_one_keeps_its_y(tmp_path):
    image(tmp_path / "alien.png", boxes=[(80, 20, 120, 359)])
    series = {"id": "s", "characters": [], "locations": [{"id": "hall", "layout2d": {"anchors": {"door": {"u": 0.2, "v": 0.7}}}}]}
    layout = normalize_layout2d({"props": [{"file": "alien.png", "x": 30, "y": 50, "scale": 0.7, "ground": True},
                                           {"file": "alien.png", "anchor": "door", "grounded": True},
                                           {"file": "gone.png", "x": 60, "y": 50, "ground": True},
                                           {"file": "alien.png", "x": 80, "y": 50}]})
    assert [prop.get("ground") for prop in layout["props"]] == [True, True, True, None]
    spec = build_shot_spec(series, {"id": "e"}, {"id": "s1", "locationId": "hall", "durationSeconds": 3, "layout2d": {"framing": "wide", **layout}},
                           workspace="cast", recorded={})
    assert [prop.get("ground") for prop in spec["props"]] == [{}, {"floor": 70.0}, {}, None]
    measure_props(spec, str(tmp_path))
    assert spec["props"][0]["ground"] == {"width": 200, "height": 400, "bottom": 0.9}
    assert spec["props"][1]["ground"] == {"floor": 70.0, "width": 200, "height": 400, "bottom": 0.9}
    assert "ground" not in spec["props"][2] and spec["props"][2]["y"] == 50.0
    empty = {"props": [{"source": "x", "ground": {}}]}
    ground_props(empty, lambda _source: None)
    assert empty == {"props": [{"source": "x"}]}


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_the_compiler_moves_a_cut_bust_to_its_frame_edge_and_stands_a_grounded_prop_on_the_floor(tmp_path):
    from services.series_shot_bridge import run_series_shot
    from services.video2d_compile import TSX
    if not TSX.is_file():
        pytest.skip("ui/node_modules/tsx is not installed")
    image(tmp_path / "bust.png", size=(900, 1200), boxes=[(0, 500, 700, 1199), (200, 100, 600, 500)])
    image(tmp_path / "alien.png", boxes=[(80, 20, 120, 359)])
    states = ["closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue"]
    overlay = lambda aid: {"id": aid, "name": aid, "source": f"/api/v1/file/{aid}.png?workspace=cast", "kind": "overlay",
                           "alphaStatus": "transparent", "reviewState": "approved"}
    kit = {"version": 1, "id": "kit-b", "name": "B", "style": "cutout", "poses": {}, "eyes": {}, "provenance": [],
           "base": {**overlay("bust"), "kind": "image"}, "mouth": {state: overlay(f"m-{state}") for state in states},
           "mouthMapping": {"rest": "closed", "M": "pressed", "A": "wide", "E": "medium", "I": "small", "O": "round", "U": "pucker", "F": "bite", "L": "tongue"},
           "anchors": {"base": {"mouth": {"offsetX": 0, "offsetY": -10, "scale": 0.1, "rotation": 0}}}}
    series = {"id": "s", "characters": [{"id": "b", "voiceProfile": {"characterKitRef": {"id": "kit-b", "workspace": "cast"}}}], "locations": []}

    def pose_and_prop(cast):
        shot = {"id": "s1", "durationSeconds": 2, "layout2d": {"framing": "medium", "cast": [cast],
                                                               "props": [{"file": "alien.png", "x": 80, "y": 30, "scale": 0.5, "ground": True}]}}
        shot["layout2d"] = normalize_layout2d(shot["layout2d"])
        spec = build_shot_spec(series, {"id": "e"}, shot, workspace="cast", recorded={})
        measure_props(spec, str(tmp_path))
        document = run_series_shot({"mode": "shot", "kits": {"kit-b": with_pose_sizes(kit, str(tmp_path))}, "shot": spec})
        layers = {layer["id"]: layer["transform"] for layer in document["layers"]}
        return layers["kit-kit-b-pose-base"], layers["prop-1"]

    pose, prop = pose_and_prop({"characterId": "b", "x": 46})
    width = pose["scale"] * 100 * 0.75 / (16 / 9)
    assert abs(pose["x"] - width / 2 + 2) < 0.01, "the left cut sits past the left frame edge"
    kept, _ = pose_and_prop({"characterId": "b", "x": 46, "edgeSnap": False})
    assert kept["x"] == 46
    height = 0.5 * 1.28 * 100  # a medium shot zooms the set, and its props, by 1.28
    assert abs(prop["y"] + 0.4 * height - (50 + 44 * 1.28)) < 0.01, "feet on the set's floor through the medium zoom"
