"""A model wears a 2D face, then talks with the same cues as a cutout."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from services.blob_face_place import anchor_radii
from services.character_kit_library import write_character_kit_library
from services.mcp_profiles import SERIES_TOOLS
from services.series_commands import INTENT_OPERATIONS, command_handlers
from services.world3d_scenes import _write, inspect_scene
from services.world3d_talk import TalkError, apply_talk
from services.world3d_template_commands import command_catalog, execute_command


def asset(name):
    return {"id": name, "name": name, "source": f"/api/v1/file/{name}.png?workspace=studio", "reviewState": "approved",
            "kind": "image", "alphaStatus": "transparent", "width": 1024, "height": 1024}


def kit():
    mouths = ("closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue")
    mouth = {"offsetX": 0, "offsetY": 17, "scale": 0.2, "rotation": 0}
    eyes = {"offsetX": 0, "offsetY": 0, "scale": 1, "rotation": 0}
    poses = {pose: asset(pose) for pose in ("neutral", "angry", "happy")}
    return {"id": "blob", "name": "Blob", "style": "cutout", "base": asset("neutral"), "poses": poses,
            "mouth": {state: {**asset(f"m-{state}"), "kind": "overlay"} for state in mouths},
            "eyes": {"blink": {**asset("blink"), "kind": "overlay"}},
            "mouthMapping": {"rest": "closed", "A": "wide"},
            "anchors": {pose: {"mouth": mouth, "eyes": eyes, "blinkSource": asset("blink")["source"]} for pose in ("base", *poses)}}


def test_a_face_anchor_size_is_a_diameter():
    assert anchor_radii({"center": [0, 1.5, 0], "size": [0.62, 0.58, 0.55]})["radii"] == [0.31, 0.29, 0.275]


def test_binding_a_face_and_talking_keeps_the_model(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    (tmp_path / "studio").mkdir()
    write_character_kit_library(root("studio"), {"version": 1, "activeId": "blob", "kits": {"blob": kit()}}, base_revision=0)
    _write("studio", "w3d-face00000001", {"revision": 1, "templateId": "t", "warnings": [], "document": {
        "duration": 4, "camera": {}, "soundtrack": [],
        "slots": [{"id": "hero", "slot": "subject_1", "media": "model3d", "sourceUrl": ""}]}}, root)
    assert "world3d.scene.face" in {item["name"] for item in command_catalog() if item["mutation"]}
    assert "world3d.scene.face" in SERIES_TOOLS and "characters.face.make" in SERIES_TOOLS
    arguments = {"version": 1, "intent_id": "face-1", "input": {
        "workspace": "studio", "scene_id": "w3d-face00000001", "base_revision": 1, "object_id": "hero", "kit_id": "blob",
        "face_anchor": {"center": [0, 1.5, 0], "size": [0.62, 0.58, 0.55]},
        "expressions": [{"start": 2, "pose": "happy"}]}}
    reply = execute_command("world3d.scene.face", arguments, root)
    face = reply["result"]["scene"]["face"]
    assert face["radii"] == [0.31, 0.29, 0.275] and face["pose"] == "neutral"
    assert execute_command("world3d.scene.face", arguments, root)["replayed"] is True
    stored = inspect_scene("studio", "w3d-face00000001", root)
    slot = stored["document"]["slots"][0]
    assert slot["media"] == "model3d" and set(slot["faceDecal"]["art"]["mouths"]) == set(kit()["mouth"])
    assert slot["faceDecal"]["expressions"] == [{"start": 2.0, "pose": "happy"}]
    talk = {"version": 1, "intent_id": "talk-face", "input": {
        "workspace": "studio", "scene_id": "w3d-face00000001", "base_revision": 2, "object_id": "hero", "kit_id": "blob",
        "lines": [{"start": 0.2, "cues": [{"start": 0, "end": 0.3, "value": "D"}],
                   "audio": "/api/v1/file/line.wav?workspace=studio"}]}}
    spoken = execute_command("world3d.scene.talk", talk, root)["result"]["scene"]
    assert spoken["talk"]["cues"] == 1 and spoken["talk"]["tracks"] == ["talk-hero-0"]
    again = inspect_scene("studio", "w3d-face00000001", root)
    model = again["document"]["slots"][0]
    assert model["media"] == "model3d" and "screen" not in model
    assert model["faceDecal"]["art"]["cues"][0]["state"] == "wide"
    assert again["document"]["soundtrack"][0]["id"] == "talk-hero-0"


def test_rebinding_a_face_keeps_the_expression_timeline(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    (tmp_path / "studio").mkdir()
    write_character_kit_library(root("studio"), {"version": 1, "activeId": "blob", "kits": {"blob": kit()}}, base_revision=0)
    _write("studio", "w3d-face00000003", {"revision": 1, "templateId": "t", "warnings": [], "document": {
        "duration": 4, "camera": {}, "soundtrack": [],
        "slots": [{"id": "hero", "slot": "subject_1", "media": "model3d", "sourceUrl": ""}]}}, root)
    first = {"version": 1, "intent_id": "face-keep-1", "input": {
        "workspace": "studio", "scene_id": "w3d-face00000003", "base_revision": 1, "object_id": "hero", "kit_id": "blob",
        "pose": "angry", "face_anchor": {"center": [0, 1.5, 0], "size": [0.62, 0.58, 0.55]},
        "expressions": [{"start": 2, "pose": "happy"}]}}
    execute_command("world3d.scene.face", first, root)
    again = {"version": 1, "intent_id": "face-keep-2", "input": {
        "workspace": "studio", "scene_id": "w3d-face00000003", "base_revision": 2, "object_id": "hero", "kit_id": "blob",
        "size": 1.08}}
    execute_command("world3d.scene.face", again, root)
    slot = inspect_scene("studio", "w3d-face00000003", root)["document"]["slots"][0]
    assert slot["faceDecal"]["pose"] == "angry"
    assert slot["faceDecal"]["expressions"] == [{"start": 2.0, "pose": "happy"}]
    assert slot["faceDecal"]["size"] == 1.08
    cleared = {"version": 1, "intent_id": "face-keep-3", "input": {
        "workspace": "studio", "scene_id": "w3d-face00000003", "base_revision": 3, "object_id": "hero", "kit_id": "blob",
        "expressions": []}}
    execute_command("world3d.scene.face", cleared, root)
    empty = inspect_scene("studio", "w3d-face00000003", root)["document"]["slots"][0]
    assert empty["faceDecal"]["expressions"] == []
    assert empty["faceDecal"]["pose"] == "angry"


def test_a_model_without_a_face_and_a_kit_without_nine_mouths_are_refused(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    (tmp_path / "studio").mkdir()
    thin = kit()
    thin["id"] = "thin"
    del thin["mouth"]["tongue"]
    write_character_kit_library(root("studio"), {"version": 1, "activeId": "blob", "kits": {"blob": kit(), "thin": thin}}, base_revision=0)
    _write("studio", "w3d-face00000002", {"revision": 1, "templateId": "t", "warnings": [], "document": {
        "duration": 4, "slots": [{"id": "hero", "slot": "subject_1", "media": "model3d", "sourceUrl": ""},
                                 {"id": "card", "slot": "prop", "media": "image", "sourceUrl": ""}]}}, root)
    with pytest.raises(TalkError) as bare:
        apply_talk({"duration": 4}, {"id": "hero", "media": "model3d"}, kit(), [], workspace="studio")
    assert bare.value.code == "not_a_cutout"
    with pytest.raises(HTTPException) as image:
        execute_command("world3d.scene.face", {"version": 1, "intent_id": "face-img", "input": {
            "workspace": "studio", "scene_id": "w3d-face00000002", "base_revision": 1, "object_id": "card",
            "kit_id": "blob", "center": [0, 1, 0], "radii": [0.3, 0.3, 0.3]}}, root)
    assert image.value.detail["code"] == "not_a_model"
    with pytest.raises(HTTPException) as mouths:
        execute_command("world3d.scene.face", {"version": 1, "intent_id": "face-thin", "input": {
            "workspace": "studio", "scene_id": "w3d-face00000002", "base_revision": 1, "object_id": "hero",
            "kit_id": "thin", "center": [0, 1, 0], "radii": [0.3, 0.3, 0.3]}}, root)
    assert mouths.value.detail["code"] == "mouths_not_ready"


def test_characters_face_make_posts_and_replays(tmp_path):
    calls = []

    def opener(request, timeout):
        del timeout
        calls.append(request.full_url)
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
            def read(self):
                return b'{"kit_id":"blob-abc","poses":["neutral"],"preview":"/api/v1/file/preview.png?workspace=studio"}'
        return Response()

    workspace = tmp_path / "studio"
    workspace.mkdir()
    handlers = command_handlers(lambda: "http://127.0.0.1:9", lambda name: str(tmp_path / name), lambda: str(tmp_path), opener=opener)
    payload = {"version": 1, "intent_id": "face-make-1", "input": {"workspace": "studio", "traits": {"eyes": "dot"}, "name": "Punto"}}
    first = asyncio.run(handlers["characters.face.make"](payload))
    second = asyncio.run(handlers["characters.face.make"](payload))
    assert first["result"] == {"kit_id": "blob-abc", "poses": ["neutral"], "preview": "/api/v1/file/preview.png?workspace=studio"}
    assert second["result"]["replayed"] is True or second.get("replayed") is True or second["result"].get("replayed") is True
    assert calls == ["http://127.0.0.1:9/api/v1/character-kits/face"]
    assert "characters.face.make" in INTENT_OPERATIONS


def test_a_plane_face_is_opt_in_and_sized_in_head_radii(tmp_path):
    from services.blob_face_scene import PLANE_DEFAULT

    root = lambda workspace: str(tmp_path / workspace)
    (tmp_path / "studio").mkdir()
    write_character_kit_library(root("studio"), {"version": 1, "activeId": "blob", "kits": {"blob": kit()}}, base_revision=0)
    _write("studio", "w3d-face00000002", {"revision": 1, "templateId": "t", "warnings": [], "document": {
        "duration": 4, "camera": {}, "soundtrack": [],
        "slots": [{"id": "hero", "slot": "subject_1", "media": "model3d", "sourceUrl": ""}]}}, root)
    base = {"workspace": "studio", "scene_id": "w3d-face00000002", "object_id": "hero", "kit_id": "blob",
            "face_anchor": {"center": [0, 1.5, 0], "size": [0.62, 0.58, 0.55]}}
    execute_command("world3d.scene.face", {"version": 1, "intent_id": "cap", "input": {**base, "base_revision": 1}}, root)
    decal = inspect_scene("studio", "w3d-face00000002", root)["document"]["slots"][0]["faceDecal"]
    assert "shape" not in decal and "plane" not in decal
    execute_command("world3d.scene.face", {"version": 1, "intent_id": "plane", "input": {**base, "base_revision": 2, "shape": "plane"}}, root)
    decal = inspect_scene("studio", "w3d-face00000002", root)["document"]["slots"][0]["faceDecal"]
    assert decal["shape"] == "plane" and decal["plane"] == PLANE_DEFAULT
    execute_command("world3d.scene.face", {"version": 1, "intent_id": "sized", "input": {**base, "base_revision": 3, "plane": [3, 4]}}, root)
    decal = inspect_scene("studio", "w3d-face00000002", root)["document"]["slots"][0]["faceDecal"]
    assert decal["shape"] == "plane" and decal["plane"] == [3.0, 4.0, PLANE_DEFAULT[2]]
    execute_command("world3d.scene.face", {"version": 1, "intent_id": "cap-again", "input": {**base, "base_revision": 4, "shape": "cap"}}, root)
    assert "shape" not in inspect_scene("studio", "w3d-face00000002", root)["document"]["slots"][0]["faceDecal"]
    # plane alone, after a cap, selects the plane
    execute_command("world3d.scene.face", {"version": 1, "intent_id": "plane-alone", "input": {**base, "base_revision": 5, "plane": [2, 2, 0.5]}}, root)
    decal = inspect_scene("studio", "w3d-face00000002", root)["document"]["slots"][0]["faceDecal"]
    assert decal["shape"] == "plane" and decal["plane"] == [2.0, 2.0, 0.5]
    with pytest.raises(HTTPException) as bad:
        execute_command("world3d.scene.face", {"version": 1, "intent_id": "bad", "input": {**base, "base_revision": 6, "shape": "plane", "plane": [0.5, 4]}}, root)
    assert bad.value.detail["code"] == "invalid_face"


def test_a_cap_can_hug_an_egg_and_project_a_painted_head(tmp_path):
    root = lambda workspace: str(tmp_path / workspace)
    (tmp_path / "studio").mkdir()
    write_character_kit_library(root("studio"), {"version": 1, "activeId": "blob", "kits": {"blob": kit()}}, base_revision=0)
    _write("studio", "w3d-face00000003", {"revision": 1, "templateId": "t", "warnings": [], "document": {
        "duration": 4, "camera": {}, "soundtrack": [],
        "slots": [{"id": "hero", "slot": "subject_1", "media": "model3d", "sourceUrl": ""}]}}, root)
    base = {"workspace": "studio", "scene_id": "w3d-face00000003", "object_id": "hero", "kit_id": "blob",
            "face_anchor": {"center": [0, 1.5, 0], "size": [0.62, 0.58, 0.55]}}
    execute_command("world3d.scene.face", {"version": 1, "intent_id": "plain", "input": {**base, "base_revision": 1}}, root)
    decal = inspect_scene("studio", "w3d-face00000003", root)["document"]["slots"][0]["faceDecal"]
    assert "taper" not in decal and "fit" not in decal
    execute_command("world3d.scene.face", {"version": 1, "intent_id": "egg", "input": {**base, "base_revision": 2, "taper": 0.35, "fit": [0.5, 0.35, 0.3, 0.33]}}, root)
    decal = inspect_scene("studio", "w3d-face00000003", root)["document"]["slots"][0]["faceDecal"]
    assert decal["taper"] == 0.35 and decal["fit"] == [0.5, 0.35, 0.3, 0.33]
    execute_command("world3d.scene.face", {"version": 1, "intent_id": "keep", "input": {**base, "base_revision": 3, "pose": "happy"}}, root)
    decal = inspect_scene("studio", "w3d-face00000003", root)["document"]["slots"][0]["faceDecal"]
    assert decal["taper"] == 0.35 and decal["fit"] == [0.5, 0.35, 0.3, 0.33] and decal["pose"] == "happy"
    for index, bad in enumerate(({"taper": 0.9}, {"fit": [0.5, 0.5, 0, 0.3]}, {"fit": [1.2, 0.5, 0.3, 0.3]})):
        with pytest.raises(HTTPException) as refused:
            execute_command("world3d.scene.face", {"version": 1, "intent_id": f"bad-{index}", "input": {**base, "base_revision": 4, **bad}}, root)
        assert refused.value.detail["code"] == "invalid_face"


def test_cute_and_anime_head_styles_draw_different_faces_for_the_same_head_box():
    """``cute`` keeps the round mascot eyes (the old anime_head drawer); ``anime_head`` is the calibrated almond-eyed
    face. Both are head pictures: same skull box (fit), same poses, same mouth anchors, and the kit says shape mesh."""
    from services.blob_face import face_kit
    from services.blob_face_head import POSES

    cute = face_kit({"style": "cute", "skin": "#F3CBA4"})
    anime = face_kit({"style": "anime_head", "skin": "#F3CBA4", "faceShape": "sharp"})
    assert list(cute["poses"]) == list(anime["poses"]) == list(POSES) and len(POSES) == 11
    assert cute["face"]["fit"] == anime["face"]["fit"] and cute["face"]["shape"] == anime["face"]["shape"] == "mesh"
    assert cute["face"]["skin"] == anime["face"]["skin"] == "#f3cba4"
    assert cute["poses"]["neutral"].tobytes() != anime["poses"]["neutral"].tobytes()
    assert set(cute["mouths"]) == set(anime["mouths"]) and len(anime["mouths"]) == 9


def test_a_painted_bald_face_becomes_an_anime_head_kit_with_overlay_expressions():
    """face_source qwen: a keyed bald painting is measured (silhouette prior when no landmarks), warped onto the anime_head
    layout and given the eleven expressions as overlays; the kit keeps the same fit, mouths and blink as the drawn styles."""
    import os
    from PIL import Image, ImageDraw
    from services.anime_make import resolve_traits
    from services.blob_face import face_kit
    from services.blob_face_qwen import _prior, measure, qwen_kit

    os.environ["HOCUS_ANIME_FACE"] = "0"
    picture = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    draw = ImageDraw.Draw(picture)
    draw.ellipse((212, 60, 812, 760), fill=(248, 214, 184, 255))          # a bald head
    draw.rectangle((420, 700, 604, 1024), fill=(248, 214, 184, 255))        # its neck
    for cx in (392, 632):
        draw.ellipse((cx - 60, 520, cx + 60, 585), fill=(255, 255, 255, 255))
        draw.ellipse((cx - 30, 525, cx + 30, 580), fill=(40, 90, 200, 255))
    draw.line((470, 690, 554, 690), fill=(90, 40, 50, 255), width=8)
    prior = _prior(picture)
    assert 440 < prior["left"][1] < 620 and prior["left"][0] < 512 < prior["right"][0]
    m = measure(picture)
    assert abs(m["left"][1] - 552) < 70 and abs(m["mouth"][1] - 690) < 70
    look = {"style": "anime_head", "skin": "#F3CBA4"}
    kit = qwen_kit(face_kit.__globals__["face_traits"](look), picture)
    assert len(kit["poses"]) == 11 and len(kit["mouths"]) == 9 and kit["face"]["source"] == "qwen"
    assert kit["face"]["fit"] == face_kit(look)["face"]["fit"] and kit["face"]["skin"].lower() != "#f3cba4"   # the painting's own skin
    assert kit["poses"]["neutral"].tobytes() != kit["poses"]["happy"].tobytes()
    with pytest.raises(Exception) as refused:
        resolve_traits({"face_source": "qwen"})
    assert getattr(refused.value, "code", "") == "face_image_required"
    assert resolve_traits({"face_style": "cute"})["face"]["style"] == "cute"
    del os.environ["HOCUS_ANIME_FACE"]
