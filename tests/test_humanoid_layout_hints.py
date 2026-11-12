"""A mould body in a skirt is rigged from the mould's own leg layout: hips at the leg top, knees at mid-leg, not at the
hem the silhouette sees. Bodies whose legs the silhouette reads (trousers, bare legs, the compose moulds) keep exactly
the joints they had, and a GLB without hints never changes."""
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from services.blob_builder import _layout, blob_pieces
from services.blob_make import build_body, leg_hints, resolve_request
from services.humanoid_rig.animate import stored_rig
from services.humanoid_rig.clips import clip_library
from services.humanoid_rig.layout_hints import apply_leg_hints
from services.humanoid_rig.rig import rig_humanoid

GRID = [("anime", "loft", True, 1.5, "slim"), ("anime", "loft", True, 1.9, "round"), ("anime", "loft", False, 1.62, "slim"),
        ("anime", "loft", False, 1.9, "average"), ("anime", None, True, 1.7, "average"), ("blob", None, True, 1.5, "slim"),
        ("blob", None, False, 1.9, "round"), ("chibi", None, True, 1.2, "pear")]


def mould(family, mesh, skirt, height, build):
    traits = {"family": family, "height": height, "build": build, "accessories": [{"kind": "skirt"}] if skirt else []}
    if mesh:
        traits["mesh"] = mesh
    resolved, _clips = resolve_request({"traits": traits, "clips": ["idle"]})
    built = blob_pieces(resolved)
    return resolved, built.get("layout") or _layout(built["traits"])


@pytest.mark.parametrize(("family", "mesh", "skirt", "height", "build"), GRID)
def test_the_hips_sit_where_the_mould_put_the_legs_and_bodies_the_silhouette_reads_do_not_change(family, mesh, skirt, height, build):
    traits, layout = mould(family, mesh, skirt, height, build)
    body = build_body(traits, ["idle"])
    points = body["sidecar"]["landmarks"]
    hip, knee = points["left_hip"][1], points["left_knee"][1]
    meets = min(layout["leg_top"], layout["torso_bottom"])
    assert meets - 0.03 * height <= hip <= layout["leg_top"] + 0.04 * height, (hip, layout)
    assert abs(knee - layout["knee"]) <= 0.05 * height, (knee, layout["knee"])
    _glb, plain = rig_humanoid(body["glb"], ["idle"])
    moved = "legs_from_layout" in body["sidecar"]["warnings"]
    if moved:
        assert plain["landmarks"]["crotch"][1] < meets - 0.08 * height, "only a body whose silhouette read a hem moves"
        assert skirt, "legs without a skirt are never moved"
    else:
        assert plain["landmarks"] == points, "a body the silhouette reads keeps its joints exactly"
    if mesh == "loft":
        assert moved == skirt, "the loft skirt hides the legs from the silhouette; loft trousers do not"


def test_trousers_keep_the_same_joints_and_a_skirt_sits_on_a_normal_chair():
    teo, teo_layout = mould("anime", "loft", False, 1.9, "slim")
    ana, ana_layout = mould("anime", "loft", True, 1.62, "slim")
    teo_body, ana_body = build_body(teo, ["idle"]), build_body(ana, ["idle"])
    assert rig_humanoid(teo_body["glb"], ["idle"])[1]["landmarks"] == teo_body["sidecar"]["landmarks"]
    knee = ana_body["sidecar"]["landmarks"]["left_knee"][1]
    assert 0.38 < knee < 0.48, "a 1.62 m body's knees are about 0.43 m high, not at 0.26 m under the skirt's hem"


def test_hints_only_move_a_crotch_found_well_under_where_the_legs_meet_the_trunk():
    found = {"height": 1.6, "points": {"crotch": [0, 0.45, 0], "left_hip": [0.07, 0.48, 0], "right_hip": [-0.07, 0.48, 0],
                                       "left_knee": [0.07, 0.27, 0], "right_knee": [-0.07, 0.27, 0]}, "robe": None, "warnings": []}
    hints = {"leg_top": 0.88, "knee": 0.43, "leg_bottom": 0.05, "leg_d": 0.08, "torso_bottom": 0.74}
    moved = apply_leg_hints(found, hints)
    assert moved["points"]["left_hip"][1] == 0.88 and moved["points"]["right_knee"][1] == 0.43 and moved["points"]["crotch"][1] == 0.84
    assert moved["robe"] == {"hem": 0.45, "skirt": True} and "legs_from_layout" in moved["warnings"]
    near = {**found, "points": {**found["points"], "crotch": [0, 0.72, 0]}}
    assert apply_leg_hints(near, hints) is near, "a crotch at the trunk's bottom is a real crotch"
    assert apply_leg_hints(found, None) is found and leg_hints({"knee": 1}) is None
    robe = apply_leg_hints({**found, "robe": {"hem": 0.1}}, hints)
    assert robe["robe"] == {"hem": 0.1}, "a long robe keeps its own drape"


def _weights(glb: bytes):
    """Positions, and per vertex the summed skin weight of each bone, of every skinned primitive."""
    from services.humanoid_rig.gltf_accessors import read_accessor, split_glb
    document, buffers = split_glb(glb)
    names = [document["nodes"][index]["name"] for index in document["skins"][0]["joints"]]
    rows, sums = [], []
    for mesh in document["meshes"]:
        for primitive in mesh["primitives"]:
            attributes = primitive["attributes"]
            positions = read_accessor(document, attributes["POSITION"], buffers)
            joints = read_accessor(document, attributes["JOINTS_0"], buffers).astype(int)
            weights = read_accessor(document, attributes["WEIGHTS_0"], buffers)
            table = np.zeros((len(positions), len(names)))
            for slot in range(4):
                np.add.at(table, (np.arange(len(positions)), joints[:, slot]), weights[:, slot])
            rows.append(positions)
            sums.append(table)
    return np.vstack(rows), np.vstack(sums), names


def test_a_skirted_body_walks_and_sits_with_the_skirt_on_its_thighs():
    traits, layout = mould("anime", "loft", True, 1.62, "slim")
    body = build_body(traits, ["idle", "walk", "sit_down"])
    rig = stored_rig(body["rigged"])
    assert rig.rest_positions[rig.index("LeftLeg")][1] == pytest.approx(layout["knee"], abs=0.02)
    assert rig.leg > 0.75 * (layout["leg_top"] - layout["leg_bottom"]), "the legs run from the leg top, not from the hem"
    for clip_id in ("walk", "sit_down", "idle"):
        (clip,) = clip_library(120, [clip_id], rig)
        assert np.isfinite(clip["hips_translation"]).all()
    positions, table, names = _weights(body["rigged"])
    thighs = [names.index("LeftUpLeg"), names.index("RightUpLeg")]
    lower = [names.index(name) for name in ("LeftLeg", "RightLeg", "LeftFoot", "RightFoot")]
    hips = names.index("Hips")
    top, knee = layout["leg_top"], layout["knee"]
    near_hem = (positions[:, 1] > knee + 0.06) & (positions[:, 1] < knee + 0.12)
    waist = (positions[:, 1] > top - 0.04) & (positions[:, 1] < top)
    assert near_hem.any() and waist.any()
    assert table[near_hem][:, thighs].sum(axis=1).mean() > 0.6, "low on the skirt the thighs carry it, so a sit lays it on the lap"
    assert table[near_hem][:, lower].sum(axis=1).max() < 0.35, "the shins do not pull the skirt"
    assert table[waist][:, hips].mean() > 0.5, "at the waist the skirt hangs from the hips"
