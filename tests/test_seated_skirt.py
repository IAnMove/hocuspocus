"""A mould body in a skirt, seated, shows a closed skirt over the lap: no thigh skin through the cloth, no hole where the
camera looks into the hem. Measured on the posed mesh with a depth buffer, from the front and three-quarter views, at the
thigh angle of a chair (level) and of a high bed (about 27 degrees down)."""
import numpy as np
import pytest

pytest.importorskip("pygltflib")

from services.blob_builder import _layout, blob_pieces
from services.blob_loft import skirt_hem_y
from services.blob_make import build_body, resolve_request
from services.humanoid_rig.gltf_accessors import read_accessor, split_glb
from services.humanoid_rig.pose_math import sample_channel, trs_matrix, world_matrices
from services.world3d_body_pose import _PATHS, _parents

SIZE = (96, 128)


def _posed(glb: bytes, clip_name: str, seconds: float):
    document, buffers = split_glb(glb)
    nodes = document["nodes"]
    trs = [[n.get("translation") or [0.0, 0.0, 0.0], n.get("rotation") or [0.0, 0.0, 0.0, 1.0], n.get("scale") or [1.0, 1.0, 1.0]] for n in nodes]
    animation = next(a for a in document["animations"] if a.get("name") == clip_name)
    for channel in animation["channels"]:
        sampler, target = animation["samplers"][channel["sampler"]], channel["target"]
        if target.get("path") in _PATHS:
            times, values = read_accessor(document, sampler["input"], buffers), read_accessor(document, sampler["output"], buffers)
            trs[target["node"]][_PATHS[target["path"]]] = sample_channel(times, values, seconds, "LINEAR", channel=target["path"])
    worlds = world_matrices([trs_matrix(*item) for item in trs], _parents(nodes))
    skin = document["skins"][0]
    inverse = np.atleast_2d(read_accessor(document, skin["inverseBindMatrices"], buffers))
    mats = np.stack([worlds[j] @ np.asarray(inverse[k], dtype=np.float64).reshape((4, 4), order="F") for k, j in enumerate(skin["joints"])])
    parts = []
    for primitive in document["meshes"][0]["primitives"]:
        attributes = primitive["attributes"]
        rest = read_accessor(document, attributes["POSITION"], buffers).astype(np.float64)
        joints = read_accessor(document, attributes["JOINTS_0"], buffers).astype(int)
        weights = read_accessor(document, attributes["WEIGHTS_0"], buffers).astype(np.float64)
        colors = read_accessor(document, attributes["COLOR_0"], buffers)[:, :3]
        cells = np.c_[rest, np.ones(len(rest))]
        posed = sum(weights[:, k:k + 1] * np.einsum("nij,nj->ni", mats[joints[:, k]], cells)[:, :3] for k in range(4))
        material = document["materials"][primitive["material"]]
        parts.append((rest, posed, colors, bool(material.get("doubleSided")), material.get("name")))
    return parts


def _visible(parts, yaw: float, pitch: float, hem: float, legs: dict) -> tuple[int, int]:
    """(thigh skin pixels, skirt pixels) seen from a camera at ``yaw``/``pitch`` degrees, culling as the material says."""
    cy, sy, cp, sp = (f(np.radians(a)) for a, f in ((yaw, np.cos), (yaw, np.sin), (pitch, np.cos), (pitch, np.sin)))
    turn = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]) @ np.eye(3)
    tilt = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    depth, label = np.full(SIZE[::-1], -np.inf), np.zeros(SIZE[::-1], dtype=np.int8)
    for rest, posed, colors, double, _name in parts:
        p = posed @ turn.T @ tilt.T
        sx, sy_ = (p[:, 0] + 0.6) / 1.2 * SIZE[0], (1.4 - p[:, 1]) / 1.4 * SIZE[1]
        triangles = np.arange(len(p)).reshape(-1, 3)
        normals = np.cross(p[triangles[:, 1]] - p[triangles[:, 0]], p[triangles[:, 2]] - p[triangles[:, 0]])
        for index, (a, b, c) in enumerate(triangles):
            if not double and normals[index, 2] <= 0:
                continue
            xs, ys = sx[[a, b, c]], sy_[[a, b, c]]
            x0, x1, y0, y1 = max(int(xs.min()), 0), min(int(xs.max()) + 1, SIZE[0] - 1), max(int(ys.min()), 0), min(int(ys.max()) + 1, SIZE[1] - 1)
            if x0 > x1 or y0 > y1:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            area = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(area) < 1e-12:
                continue
            l0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / area
            l1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / area
            inside = (l0 >= 0) & (l1 >= 0) & (l0 + l1 <= 1)
            z = (l0 * p[a, 2] + l1 * p[b, 2] + (1 - l0 - l1) * p[c, 2])[inside]
            rows, cols = np.nonzero(inside)
            rows, cols = rows + y0, cols + x0
            closer = z > depth[rows, cols]
            depth[rows[closer], cols[closer]] = z[closer]
            rgb = colors[[a, b, c]].mean(axis=0)
            skin = rgb[0] > 0.6 and 0.3 < rgb[1] < 0.75 and rgb[2] < 0.55
            centre = rest[[a, b, c]].mean(axis=0)
            thigh = skin and hem + 0.01 < centre[1] < legs["leg_top"] and abs(centre[0]) < legs["leg_x"] + legs["leg_d"]
            navy = rgb[2] > rgb[0] * 1.5 and rgb[0] < 0.1
            label[rows[closer], cols[closer]] = 1 if thigh else 2 if navy else 0
    return int((label == 1).sum()), int((label == 2).sum())


def test_a_seated_skirt_is_closed_and_shows_no_thigh_skin():
    traits, _clips = resolve_request({"traits": {"family": "anime", "mesh": "loft", "height": 1.66, "build": "slim", "accessories": [{"kind": "skirt"}]},
                                      "clips": ["idle"]})
    built = blob_pieces(traits)
    legs = built.get("layout") or _layout(built["traits"])
    hem = skirt_hem_y(legs)
    body = build_body(traits, ["idle", "sit_down"])
    for seconds in (1.0, 0.5):                        # thighs level (a chair), and about 27 degrees down (a 0.55 m bed)
        parts = _posed(body["rigged"], "Sit Down", seconds)
        assert next(part for part in parts if part[4] == "body")[3], "the skirted body is drawn from both sides"
        for yaw, pitch in ((0, 25), (-35, 15), (-60, -5)):
            thigh, skirt = _visible(parts, yaw, pitch, hem, legs)
            assert skirt > 300 and thigh == 0, (seconds, yaw, pitch, thigh, skirt)


def test_trousers_and_bodies_without_a_skirt_draw_one_side_as_before():
    traits, _clips = resolve_request({"traits": {"family": "anime", "mesh": "loft", "height": 1.8, "accessories": []}, "clips": ["idle"]})
    parts = _posed(build_body(traits, ["idle", "sit_down"])["rigged"], "Sit Down", 1.0)
    assert not any(part[3] for part in parts)
