"""A realistic mould and its texture atlas: UVs, guides, the texture written into a rigged GLB."""
import io
import json
import struct

from PIL import Image

from services.anime_make import resolve_traits
from services.blob_builder import blob_pieces
from services.blob_loft import loft_parts
from services.blob_texture import ATLAS, HALF_SIZE, attach_texture, guide_png, stack_atlas


def _real(gender="man", **traits):
    resolved = resolve_traits({"style": "real", "gender": gender, "hair_style": "none", **traits})
    lofted = blob_pieces({**resolved["body"], "mesh": "loft"})
    return lofted, loft_parts(lofted["traits"], lofted["layout"])


def _json(glb: bytes) -> dict:
    length = struct.unpack_from("<I", glb, 12)[0]
    return json.loads(glb[20:20 + length])


def test_a_real_mould_has_atlas_uvs_inside_the_picture_and_the_head_in_its_tiles():
    lofted, parts = _real()
    named = {name: (mesh, uvs) for mesh, name, uvs in parts}
    assert lofted["traits"]["realism"] == "real" and lofted["traits"]["outfit"] == "plain"
    for name in ("body", "face"):
        mesh, uvs = named[name]
        assert len(uvs) == len(mesh.vertices) > 0
        assert all(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 for u, v in uvs)
    body, uvs = named["body"]
    head_rows = [uv for uv in uvs if uv[1] >= 0.5]
    body_rows = [uv for uv in uvs if uv[1] < 0.5]
    assert head_rows and body_rows, "the head has its tiles below the body views"
    assert {int(u * 3) for u, _v in head_rows} == {0, 1, 2}, "front, side and back tiles are all used"
    face, face_uvs = named["face"]
    assert all(uv[1] >= 0.5 and uv[0] < 1 / 3 for uv in face_uvs), "the face patch is the front tile, whole"


def test_the_guides_are_two_pictures_of_the_halves_and_an_anime_body_has_no_atlas():
    lofted, parts = _real()
    for part in ("body", "head"):
        image = Image.open(io.BytesIO(guide_png(parts, lofted["layout"], part)))
        assert image.size == HALF_SIZE
        assert len(set(image.convert("L").getdata())) > 20, "the guide shows a shaded figure, not an empty picture"
    anime = blob_pieces({**resolve_traits({"gender": "girl"})["body"], "mesh": "loft"})
    assert all(uvs is None for mesh, name, uvs in loft_parts(anime["traits"], anime["layout"]) if name == "body")


def test_a_real_man_is_broader_than_a_real_woman_and_both_are_not_anime_proportioned():
    man, _ = _real("man")
    woman, _ = _real("woman")
    anime = blob_pieces({**resolve_traits({"gender": "boy"})["body"], "mesh": "loft"})
    assert man["layout"]["torso_w"] > woman["layout"]["torso_w"] > anime["layout"]["torso_w"] * 0.95
    assert man["layout"]["head_kind"] == "man" and woman["layout"]["head_kind"] == "boy"


def test_the_texture_goes_into_the_rigged_glb_and_the_vertex_colours_stop_tinting_it():
    from services.blob_make import build_body

    resolved = resolve_traits({"style": "real", "gender": "man", "hair_style": "short"})
    body = build_body(resolved["body"], ["idle"])
    before = _json(body["rigged"])
    names = [m["name"] for m in before["materials"]]
    assert "body" in names and "face" in names and "hair" in names
    painted = Image.new("RGB", ATLAS, (200, 120, 60))
    out = io.BytesIO()
    painted.save(out, format="PNG")
    from services.blob_texture import atlas_frame

    lofted = blob_pieces({**resolved["body"], "mesh": "loft"})
    parts = loft_parts(lofted["traits"], lofted["layout"])
    glb = attach_texture(body["rigged"], out.getvalue(), frame=atlas_frame([parts[0][0]], lofted["layout"]))
    after = _json(glb)
    for name in ("body", "face"):
        extras = after["materials"][names.index(name)]["extras"]["atlas"]
        assert len(extras["body"]) == 3 and len(extras["head"]) == 3 and extras["body"][2] > 1.0, "a viewer can project the atlas per pixel"
    assert len(after["images"]) == 1 and len(after["textures"]) == 1
    for name in ("body", "face"):
        material = after["materials"][names.index(name)]
        assert material["pbrMetallicRoughness"]["baseColorTexture"] == {"index": 0}
    assert "baseColorTexture" not in after["materials"][names.index("hair")]["pbrMetallicRoughness"]
    for mesh in after["meshes"]:
        for primitive in mesh["primitives"]:
            if after["materials"][primitive["material"]]["name"] in ("body", "face"):
                assert "COLOR_0" not in primitive["attributes"] and "TEXCOORD_0" in primitive["attributes"]
            assert "JOINTS_0" in primitive["attributes"], "the skin survives"
    assert after["skins"] == before["skins"] and after["animations"] == before["animations"]


def test_stack_atlas_puts_the_body_over_the_head_and_enlarges_nothing_it_does_not_have():
    top = Image.new("RGB", (1024, 512), (255, 0, 0))
    bottom = Image.new("RGB", (2048, 1024), (0, 255, 0))
    atlas = Image.open(io.BytesIO(stack_atlas(top, bottom)))
    assert atlas.size == ATLAS
    assert atlas.getpixel((10, 10)) == (255, 0, 0) and atlas.getpixel((10, ATLAS[1] - 10)) == (0, 255, 0)


def test_bleed_keeps_the_painted_figure_and_fills_the_ring_around_the_silhouette():
    from services.blob_texture import bleed

    ground = (30, 32, 40)
    guide = Image.new("RGB", (200, 100), (40, 40, 44))
    painted = Image.new("RGB", (200, 100), ground)
    for x in range(60, 140):
        for y in range(20, 80):
            guide.putpixel((x, y), (200, 200, 205))
    for x in range(70, 130):                       # the painting is narrower than the mould by ten pixels each side
        for y in range(30, 70):
            painted.putpixel((x, y), (200, 120, 60))
    for x in range(100, 110):                      # a dark jacket inside the silhouette stays dark
        for y in range(35, 65):
            painted.putpixel((x, y), (28, 30, 38))
    guide_png_bytes = io.BytesIO()
    guide.save(guide_png_bytes, format="PNG")
    result = bleed(painted, guide_png_bytes.getvalue(), radius=14, band=12)
    assert result.getpixel((65, 50))[0] > 150, "the ring between the painting and the mould's edge takes the figure's colour, not the ground"
    assert result.getpixel((105, 50))[0] < 40, "a dark patch well inside the silhouette is left alone"


def test_the_style_catalogue_is_in_the_presets_and_every_style_says_where_it_stands():
    from services.blob_builder import trait_catalog
    from services.character_3d_styles import STATUS, STYLES

    styles = trait_catalog()["styles"]
    assert set(styles) == set(STYLES) and {"blob", "chibi", "anime", "real", "voxel", "roblox"} <= set(styles)
    for key, style in styles.items():
        assert style["status"] in STATUS, key
        assert style["operation"].startswith("model3d.") and style["make"] and style["next"] is not None
        assert style["limits"] is not None and style["doc"].startswith("docs/agents/")
    assert styles["real"]["status"] != "planned" and styles["ps1"]["status"] == "planned"


def _bump_depth():
    import numpy as np

    h, w = 1024, 683
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    head = np.exp(-(((x - w / 2) / 190) ** 2 + ((y - 480) / 330) ** 2))              # a round head: the skull's own roundness
    nose = 0.35 * np.exp(-(((x - w / 2) / 28) ** 2 + ((y - 560) / 55) ** 2))          # a nose standing out of it
    d = head + nose
    return (d / d.max()).astype(np.float32)


def test_relief_keeps_only_what_stands_out_of_the_roundness_of_the_head():
    from services.blob_face_relief import NOSE_SHARE, relief_sampler

    lofted, parts = _real()
    from services.blob_texture import atlas_frame

    frame = atlas_frame([parts[0][0]], lofted["layout"])
    relief = relief_sampler(_bump_depth(), frame, lofted["layout"]["sy"])
    cy, span_y, _cut = frame["head"]
    nose_y = cy + (0.5 - 560 / 1024) * span_y
    cheek_x = 0.9 * (span_y / 1.5) * (110 / 683)
    tip, cheek = relief(0.0, nose_y), relief(cheek_x, cy + (0.5 - 480 / 1024) * span_y)
    assert tip > 0.7 * NOSE_SHARE * lofted["layout"]["sy"], "the nose protrudes"
    assert cheek < 0.15 * tip, "the roundness of the head is the skull's, not the relief's"
    assert relief(5.0, 5.0) == 0.0, "outside the picture there is no relief"


def test_the_relief_patch_moves_along_z_only_and_melts_into_the_skull_at_its_border():
    from services.blob_face_relief import relief_sampler
    from services.blob_loft import face_relief_patch
    from services.blob_texture import atlas_frame

    lofted, parts = _real()
    layout = lofted["layout"]
    frame = atlas_frame([parts[0][0]], layout)
    relief = relief_sampler(_bump_depth(), frame, layout["sy"])
    flat, flat_uvs = face_relief_patch(layout, lambda x, y: 0.0, frame, steps=24)
    raised, raised_uvs = face_relief_patch(layout, relief, frame, steps=24)
    assert flat_uvs == raised_uvs, "the picture stays exactly on its place"
    moved = [(a, b) for a, b in zip(flat.vertices, raised.vertices) if a != b]
    assert moved and all(abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9 and b[2] > a[2] for a, b in moved), "only +Z"
    assert max(b[2] - a[2] for a, b in moved) > 0.004
    x_limit = max(abs(v[0]) for v in flat.vertices)
    rim = [(a, b) for a, b in zip(flat.vertices, raised.vertices) if abs(abs(a[0]) - x_limit) < 0.003]
    assert all(abs(b[2] - a[2]) < 0.002 for a, b in rim), "at the border the relief has faded"
    assert all(0.0 <= u <= 1.0 and 0.0 <= v <= 1.0 for u, v in raised_uvs), "the kit canvas"


def test_a_head_with_a_relief_has_no_modelled_nose_and_without_the_depth_model_the_face_stays_flat(monkeypatch):
    from services import blob_face_relief
    from services.blob_loft import loft_parts

    lofted, _ = _real()
    plain = {name: len(mesh.vertices) for mesh, name, _u in loft_parts(lofted["traits"], lofted["layout"])}
    with_relief = {name: len(mesh.vertices) for mesh, name, _u in loft_parts(lofted["traits"], lofted["layout"], None, lambda x, y: 0.0)}
    assert with_relief["body"] < plain["body"], "the painted nose replaces the modelled one"
    assert with_relief["face"] > plain["face"], "the face is a dense patch"
    monkeypatch.setattr(blob_face_relief, "CHECKPOINT", blob_face_relief.CHECKPOINT.with_name("not_there.pth"))
    assert blob_face_relief.relief_from_picture(Image.new("RGB", (60, 30)), {"head": (1.0, 0.4, 1.4)}, 0.2) is None


def test_the_neck_skin_and_the_hair_colour_are_read_from_the_head_picture():
    from services.blob_texture import hair_of, neck_skin

    picture = Image.new("RGB", (2048, 1024), (30, 30, 36))
    tile = Image.new("RGB", (683, 1024), (30, 30, 36))
    for x in range(683):
        for y in range(1024):
            tile.putpixel((x, y), (60, 40, 28) if y < 200 else (205, 150, 120) if y > 700 else (190, 140, 110))
    picture.paste(tile, (0, 0))
    skin = neck_skin(picture)
    assert all(abs(a - b / 255) < 0.02 for a, b in zip(skin, (205, 150, 120))), "the row under the chin, on the neck"
    assert hair_of(picture) == "#3C281C", "the crown of the front tile"


def test_a_head_with_a_painted_face_gets_a_hair_cap_and_no_fringe_or_ear_hiding_locks():
    from services.blob_hair import hair_mesh

    lofted, _ = _real(hair_style="short", hair_color="#3C281C")
    layout = lofted["layout"]
    plain = hair_mesh(layout, {"style": "short", "color": "#3C281C"})
    capped = hair_mesh({**layout, "relief": True}, {"style": "short", "color": "#3C281C"})
    assert 0 < len(capped.vertices) < len(plain.vertices) / 2, "a cap, not a fringe and a ring of locks"
    ear_y = layout["head_y"] + layout["sy"] / 2 * -0.28
    side = [v for v in capped.vertices if abs(abs(v[0]) - layout["sx"] / 2 * 1.04) < layout["sx"] * 0.02]
    assert all(v[1] > ear_y + layout["sy"] * 0.1 for v in side), "the flanks stay above the ears"


def test_matching_moves_the_side_and_back_tiles_to_the_front_tiles_tones_and_leaves_the_front_alone():
    import numpy as np

    from services.blob_texture import match_tiles

    picture = Image.new("RGB", (900, 600), (30, 30, 36))
    for index, tone in enumerate(((200, 150, 120), (235, 200, 160), (170, 120, 90))):
        for x in range(index * 300 + 60, index * 300 + 240):
            for y in range(60, 400):
                picture.putpixel((x, y), tone)
    matched = np.asarray(match_tiles(picture)).astype(int)
    original = np.asarray(picture).astype(int)
    assert (matched[:, :300] == original[:, :300]).all(), "the front tile is the reference"
    front, side, back = (matched[200, index * 300 + 150] for index in range(3))
    assert abs(side - front).max() < abs(np.array((235, 200, 160)) - np.array((200, 150, 120))).max() * 0.6, "the side tile came toward the front's tone"
    assert abs(back - front).max() < abs(np.array((170, 120, 90)) - np.array((200, 150, 120))).max() * 0.6


def test_factor_at_interpolates_and_ramps_to_one():
    from app.services.blob_head_fit import factor_at
    table = [[-30, 0.9], [0, 1.0], [30, 0.8]]
    assert abs(factor_at(table, -30) - 0.9) < 1e-9
    assert abs(factor_at(table, 15) - 0.9) < 1e-9
    assert abs(factor_at(table, 99) - 1.0) < 1e-9    # back to 1 well outside the fitted heights
    assert abs(factor_at(table, -99) - 1.0) < 1e-9
    assert factor_at(None, 10) == 1.0


def test_frame_extras_carry_the_band_split_only_when_asked():
    from app.services.blob_texture import frame_extras
    frame = {"body": [0.0, 0.9, 2.0]}
    assert "bandDetail" not in frame_extras(frame)
    assert frame_extras(frame, bands=0.0)["bandDetail"] == 0.0
    assert frame_extras(frame, bands=0.5)["bandDetail"] == 0.5


def test_head_bands_default_on_and_validated():
    import pytest
    from services.blob_builder import BlobTraitsError
    base = {"style": "real", "gender": "man", "hair_style": "none"}
    assert resolve_traits(base)["head_bands"] == 1.0
    assert resolve_traits({**base, "head_bands": False})["head_bands"] is None
    assert resolve_traits({**base, "head_bands": 0})["head_bands"] == 0.0
    for bad in ("yes", 2, -0.1):
        with pytest.raises(BlobTraitsError) as refused:
            resolve_traits({**base, "head_bands": bad})
        assert "head_bands" in str(refused.value)
