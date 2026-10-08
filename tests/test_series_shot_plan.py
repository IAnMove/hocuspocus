"""A Series Lab shot is planned as a Video 2D shot from what the writer or the planner already set."""
import shutil

import pytest

from services.series_shot_plan import (
    background_for, build_shot_spec, card_texts, classify_camera, classify_framing, frame_size, language_key, normalize_layout2d, plan_cast,
    plan_timing, sound_tracks, spread,
)


def series(**extra):
    character = lambda cid, **more: {"id": cid, "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}", "workspace": "cast"}}, **more}
    value = {
        "id": "uv", "title": "Valle", "spokenLanguage": "Español de España",
        "characters": [character("kevin"), character("gary", layout2d={"scale": 0.6}), {"id": "nokit"}],
        "locations": [{"id": "garage", "referenceAssetIds": ["asset_day"], "layout2d": {"homes": {"kevin": 30, "gary": 70}},
                       "variants": [{"id": "night", "referenceAssetIds": ["asset_night"]}]}],
        "assets": {"asset_day": {"kind": "image", "uri": "outputs/day.png"}, "asset_night": {"kind": "image", "uri": "assets/night 1.png"},
                   "asset_plate": {"kind": "video", "uri": "plate.mp4"}},
        "soundDesign": {"stinger": {"file": "sting.wav", "volume": 0.7}, "ambienceByLocation": {"garage": {"file": "crickets.wav"}}},
    }
    value.update(extra)
    return value


@pytest.mark.parametrize("text, count, expected", [
    ("Wide establishing shot", 2, "wide"), ("plano general del garaje", 2, "wide"), ("medium close-up", 1, "close"),
    ("Plano medio", 1, "medium"), ("two-shot over the shoulder", 2, "two"), ("inserto del móvil", 0, "insert"),
    ("", 0, "title"), ("", 1, "medium"), ("", 2, "two"), ("", 3, "wide"),
])
def test_free_text_framing_in_english_or_spanish(text, count, expected):
    assert classify_framing(text, count) == expected


def test_camera_spread_language_and_timing():
    assert classify_camera("slow push-in") == "push" and classify_camera("cámara se acerca") == "push" and classify_camera("static") == "static"
    assert spread(1) == [50.0] and spread(2) == [34.0, 66.0] and spread(3) == [15.0, 50.0, 85.0]
    assert language_key(series()) == "spanish" and language_key({"spokenLanguage": "English (US)"}) == "english"
    timing, duration = plan_timing([1.0, 2.0])
    assert timing == [(0.35, 1.35), (1.57, 3.57)] and duration == round(round(4.02 * 24) / 24, 4)
    assert plan_timing([], at_least=6)[1] == 6


def test_backgrounds_prefer_the_variant_then_the_location_and_quote_paths():
    shot = {"locationId": "garage", "locationVariantId": "night"}
    assert background_for(series(), shot, "cast") == {"source": "/api/v1/file/assets/night%201.png?workspace=cast", "kind": "image"}
    assert background_for(series(), {"locationId": "garage"}, "cast")["source"] == "/api/v1/file/day.png?workspace=cast"
    plated = series()
    plated["locations"][0]["layout2d"]["plateAssetId"] = "asset_plate"
    assert background_for(plated, shot, "cast")["kind"] == "video"
    assert background_for(series(), {"locationId": "moon"}, "cast") is None


def test_cast_uses_homes_explicit_layout_and_character_scale():
    shot = {"locationId": "garage", "visibleCharacterIds": ["kevin", "gary", "nokit"]}
    cast = plan_cast(series(), shot, "wide", 4)
    assert [(item["kitId"], item["x"], item["boost"]) for item in cast] == [("kit-kevin", 30.0, 1.0), ("kit-gary", 70.0, 0.6)]
    explicit = {"locationId": "garage", "layout2d": {"cast": [{"characterId": "kevin", "poseId": "panic", "x": 20, "motion": "shake", "enterFrom": "left",
                                                                "scale": 1.2, "transform": {"x": 20, "y": 60, "scale": 0.5}}]}}
    entry = plan_cast(series(), explicit, "two", 4)[0]
    assert entry["poseId"] == "panic" and entry["motion"] == "shake" and entry["boost"] == 1.2
    assert entry["enter"] == {"fromX": -15.0, "start": 0.2, "end": 1.4} and entry["transform"] == {"x": 20, "y": 60, "scale": 0.5}
    assert plan_cast(series(), {"visibleCharacterIds": ["kevin"]}, "close", 4)[0]["x"] == 50.0, "a lone close-up is centred"


def test_a_cast_entry_can_keep_its_cut_edges_in_the_frame():
    layout = normalize_layout2d({"cast": [{"characterId": "kevin", "x": 46, "edgeSnap": False}, {"characterId": "gary", "edgeSnap": True},
                                          {"characterId": "gary", "edgeSnap": "no"}]})
    assert layout["cast"] == [{"characterId": "kevin", "x": 46.0, "edgeSnap": False}, {"characterId": "gary"}, {"characterId": "gary"}], \
        "snapping is the default, so only false is kept"
    cast = plan_cast(series(), {"locationId": "garage", "layout2d": layout}, "medium", 4)
    assert [item.get("edgeSnap") for item in cast] == [False, None, None]


def test_cards_and_sound():
    titles = card_texts({"kind": "title", "title": "VALLE", "body": "Episodio 1"}, 5)
    assert [text["id"] for text in titles] == ["card-title", "card-body"] and titles[0]["font"] == "marker"
    assert card_texts({"kind": "disclaimer", "title": "", "body": "Parodia."}, 5)[0]["id"] == "card-body"
    tracks = sound_tracks(series(), {"locationId": "garage", "layout2d": {"music": {"file": "moral.wav", "volume": 0.4, "start": 1}}}, True)
    assert [(track["id"], track["filename"]) for track in tracks] == [("ambience", "crickets.wav"), ("stinger", "sting.wav"), ("music", "moral.wav")]
    assert [track["id"] for track in sound_tracks(series(), {"locationId": "garage"}, False)] == ["ambience"]


def test_layout_normalization_keeps_only_known_values():
    assert normalize_layout2d({"framing": "close", "camera": "zoom", "cast": [{"characterId": "a", "x": 500, "motion": "dance"}, {"x": 1}],
                               "card": {"kind": "end", "title": "Fin"}, "junk": 1}) == {
        "framing": "close", "cast": [{"characterId": "a"}], "card": {"kind": "end", "title": "Fin", "body": ""}}
    assert normalize_layout2d({"junk": 1}) is None and normalize_layout2d("x") is None


def test_the_series_library_keeps_a_shot_layout():
    from services.series_library import _normalize_shot
    shot = _normalize_shot({"id": "s1", "productionMethod": "animation_2d", "layout2d": {"framing": "two", "bad": True}}, 0)
    assert shot["layout2d"] == {"framing": "two"}
    assert "layout2d" not in _normalize_shot({"id": "s2", "productionMethod": "animation_2d", "layout2d": {}}, 1)


def test_a_full_shot_spec_with_lines_card_and_focus():
    shot = {"id": "s1", "sceneId": "a", "framing": "two-shot", "camera": "static", "locationId": "garage", "visibleCharacterIds": ["kevin", "gary"],
            "dialogueBeats": [{"id": "b1", "characterId": "kevin", "text": "Hola."}, {"id": "b2", "characterId": "boss", "text": "(off)"},
                              {"id": "b3", "characterId": "gary", "text": "  "}]}
    recorded = {"b1": {"filename": "l1.wav", "duration": 1.0, "cues": [{"start": 0, "end": 1, "value": "D"}], "driver": "wav2vec2-phoneme"},
                "b2": {"filename": "l2.wav", "duration": 0.5, "cues": []}}
    spec = build_shot_spec(series(), {"id": "ep1", "title": "Piloto"}, shot, workspace="cast", recorded=recorded, first_of_scene=True)
    assert spec["framing"] == "two" and spec["camera"] == "static" and spec["fps"] == 24
    assert [(line["id"], line["visible"], line["cues"] is None) for line in spec["lines"]] == [("ep1-b1", True, False), ("ep1-b2", False, True)]
    assert spec["background"]["focusX"] == 50.0 and spec["narrative"]["controls"] == {"seriesId": "uv", "episodeId": "ep1", "shotId": "s1"}
    card = build_shot_spec(series(), {"id": "ep1"}, {"id": "s0", "durationSeconds": 6, "layout2d": {"card": {"kind": "title", "title": "VALLE"}}},
                           workspace="cast", recorded={})
    assert card["framing"] == "title" and card["cast"] == [] and card["duration"] == 6 and card["texts"][0]["text"] == "VALLE"


def test_a_line_keeps_cast_index_only_when_the_beat_has_a_real_one():
    shot = {"id": "s1", "visibleCharacterIds": ["kevin", "kevin"], "dialogueBeats": [
        {"id": "b1", "characterId": "kevin", "text": "Hola.", "castIndex": 1},
        {"id": "b2", "characterId": "kevin", "text": "Otra.", "castIndex": True}]}
    recorded = {"b1": {"filename": "l1.wav", "duration": 1.0}, "b2": {"filename": "l2.wav", "duration": 1.0}}
    lines = build_shot_spec(series(), {"id": "ep1"}, shot, workspace="cast", recorded=recorded)["lines"]
    assert lines[0]["castIndex"] == 1 and "castIndex" not in lines[1]


def test_a_vertical_series_plans_1080x1920_with_wider_spacing_and_smaller_cards():
    vertical = {**series(), "provider": {"videoSettings": {"orientation": "portrait"}}}
    assert frame_size(vertical) == (1080, 1920) and frame_size(series()) == (1920, 1080)
    assert spread(2, portrait=True) == [25.0, 75.0] and spread(3, portrait=True) == [18.0, 50.0, 82.0]
    shot = {"id": "s1", "framing": "two-shot", "visibleCharacterIds": ["kevin", "gary"], "dialogueBeats": []}
    spec = build_shot_spec(vertical, {"id": "ep1"}, shot, workspace="cast", recorded={})
    assert (spec["width"], spec["height"]) == (1080, 1920) and [item["x"] for item in spec["cast"]] == [25.0, 75.0]
    wide = card_texts({"kind": "title", "title": "VALLE", "body": "Episodio 1"}, 5)
    tall = card_texts({"kind": "title", "title": "VALLE", "body": "Episodio 1"}, 5, portrait=True)
    assert [text["size"] for text in tall] == [round(text["size"] * 0.6, 2) for text in wide] and tall[0]["maxWidth"] == 90


@pytest.mark.skipif(shutil.which("node") is None, reason="node required")
def test_the_bridge_compiles_a_planned_shot_with_the_editor_code(tmp_path):
    from PIL import Image
    from services.series_shot_bridge import run_series_shot, with_pose_sizes
    from services.video2d_compile import TSX
    if not TSX.is_file():
        pytest.skip("ui/node_modules/tsx is not installed")
    Image.new("RGBA", (300, 600), (255, 0, 0, 255)).save(tmp_path / "k.png")
    asset = lambda aid, kind="overlay": {"id": aid, "name": aid, "source": f"/api/v1/file/{aid}.png?workspace=cast" if kind == "overlay" else "/api/v1/file/k.png?workspace=cast",
                                         "kind": kind, "alphaStatus": "transparent", "reviewState": "approved"}
    states = ["closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue"]
    kit = {"version": 1, "id": "kit-kevin", "name": "Kevin", "style": "cutout", "base": asset("base", "image"), "poses": {},
           "mouth": {state: asset(f"m-{state}") for state in states}, "eyes": {}, "provenance": [],
           "mouthMapping": {"rest": "closed", "M": "pressed", "A": "wide", "E": "medium", "I": "small", "O": "round", "U": "pucker", "F": "bite", "L": "tongue"},
           "anchors": {"base": {"mouth": {"offsetX": 0, "offsetY": -10, "scale": 0.1, "rotation": 0}}}}
    sized = with_pose_sizes(kit, str(tmp_path))
    assert (sized["base"]["width"], sized["base"]["height"]) == (300, 600)
    shot = {"id": "s1", "framing": "medium", "visibleCharacterIds": ["kevin"], "dialogueBeats": [{"id": "b1", "characterId": "kevin", "text": "Hola."}]}
    spec = build_shot_spec(series(), {"id": "ep1"}, shot, workspace="cast",
                           recorded={"b1": {"filename": "l1.wav", "duration": 1.2, "cues": [{"start": 0, "end": 0.6, "value": "D"}]}})
    document = run_series_shot({"mode": "shot", "kits": {"kit-kevin": sized}, "shot": spec})
    assert document["dialogueBeats"][0]["lipSync"]["cues"] and len(document["dialogueBeats"][0]["mouthLayerIds"]) == 9
    assert any(layer.get("characterKitRef", {}).get("id") == "kit-kevin" for layer in document["layers"])


def test_props_stand_on_background_anchors_and_follow_the_framing_zoom():
    from services.series_shot_plan import background_point, plan_props
    value = series()
    value["locations"][0]["layout2d"]["anchors"] = {"desk": {"u": 0.7, "v": 0.8}}
    value["assets"]["asset_lamp"] = {"kind": "image", "uri": "lamp.png"}
    shot = {"locationId": "garage", "layout2d": normalize_layout2d({"props": [
        {"assetId": "asset_lamp", "anchor": "desk", "scale": 0.2}, {"file": "mug.png", "x": 30, "y": 70}, {"assetId": "missing"}, {"x": 1}]})}
    wide, close = plan_props(value, shot, "wide", 50, "cast"), plan_props(value, shot, "close", 50, "cast")
    assert [prop["source"] for prop in wide] == ["/api/v1/file/lamp.png?workspace=cast", "/api/v1/file/mug.png?workspace=cast"]
    assert (wide[0]["x"], wide[0]["y"], wide[0]["scale"]) == (70.0, 80.0 - 10.0, 0.2)
    assert close[0]["scale"] == 0.3 and close[0]["x"] == background_point("close", 50, 0.7, 0.8)[0]
    assert (wide[1]["x"], wide[1]["y"]) == (30.0, 70.0)


def test_a_volume_of_zero_means_silent_not_the_default():
    layout = normalize_layout2d({"music": {"file": "music/theme.wav", "volume": 0, "start": 0}})
    assert layout["music"] == {"file": "music/theme.wav", "volume": 0, "start": 0}
    assert normalize_layout2d({"music": {"file": "theme.wav"}})["music"]["volume"] == 0.5


def test_a_document_card_keeps_its_fields_and_old_cards_stay_kinetic():
    stored = normalize_layout2d({"card": {"kind": "document", "style": "file", "reveal": "pan", "title": "Exp",
                                          "body": "Nota", "date": "1888", "signature": "Ana"}})
    assert stored["card"] == {"kind": "document", "style": "file", "reveal": "pan", "title": "Exp", "body": "Nota",
                              "date": "1888", "signature": "Ana"}
    assert normalize_layout2d({"card": {"kind": "document", "style": "poster"}}) is None
    assert card_texts({"kind": "document", "title": "Carta", "body": "Hola"}, 5) == []
    titles = card_texts({"kind": "title", "title": "VALLE", "body": "Episodio 1"}, 5)
    end = card_texts({"kind": "end", "title": "FIN", "body": "Gracias"}, 5)
    disclaimer = card_texts({"kind": "disclaimer", "title": "Aviso", "body": "Parodia."}, 5)
    assert titles[0]["font"] == "marker" and titles[1]["font"] == "hand"
    assert end[0]["font"] == "marker" and end[1]["font"] == "sans" and disclaimer[0]["font"] == "condensed"


def test_document_text_fits_down_to_the_1080p_minimum_and_the_reveal_is_exact():
    from services.series_document_card import layout_document, minimum_body_px, pan_offset, render_frame, revealed_characters
    assert minimum_body_px(1080) == 28
    short = layout_document({"style": "letter", "title": "Carta", "body": "Hoy el río iba alto.", "signature": "Ana"},
                            width=1920, height=1080)
    assert short["fits"] and short["bodyPx"] >= 28
    long = layout_document({"style": "letter", "title": "Carta", "body": ("palabra " * 200)[:1200],
                            "date": "1888", "signature": "Ana"}, width=1920, height=1080)
    assert not long["fits"] and long["bodyPx"] == 28
    assert [revealed_characters(10, frame, 10) for frame in range(10)] == list(range(1, 11))
    assert [pan_offset(80, frame, 5) for frame in range(5)] == [0, 20, 40, 60, 80]
    frame = render_frame({"style": "letter", "title": "Carta", "body": "Hola.", "reveal": "static"}, 0, 1, width=320, height=180)
    assert frame.size == (320, 180) and len(frame.getcolors(maxcolors=200000)) > 20


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")
def test_a_document_shot_hides_the_set_and_can_attach_its_plate(tmp_path):
    from services.series_document_card import document_plate
    shot = {"id": "s0", "durationSeconds": 2, "locationId": "garage", "visibleCharacterIds": ["kevin"],
            "layout2d": {"card": {"kind": "document", "style": "typed", "reveal": "static", "title": "Nota", "body": "Puente."}}}
    spec = build_shot_spec(series(), {"id": "ep1"}, shot, workspace="cast", recorded={})
    assert spec["framing"] == "title" and spec["cast"] == [] and spec["texts"] == [] and "background" not in spec
    plate = document_plate(str(tmp_path), shot, {**spec, "duration": 0.5, "width": 320, "height": 180, "fps": 8, "workspace": "cast"})
    assert plate["kind"] == "video" and plate["source"].startswith("/api/v1/file/series-documents/")
    assert list((tmp_path / "series-documents").glob("*.mp4"))
