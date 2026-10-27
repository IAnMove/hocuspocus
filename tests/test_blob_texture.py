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
