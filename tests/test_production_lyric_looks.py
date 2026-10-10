"""Lyric looks: designed type per piece and per song section, applied through the title templates."""
import json

import pytest

from services.production_lyric_looks import LyricLookError, check_lyric_looks, line_sections, look_for, looks, synced_enter
from services.production_scene_ops import lyric_ops
from services.video2d_edit_titles import TITLE_BUILDERS

LYRICS = "[Intro]\nla sal dormía\n\n[Verse]\nel faro guardaba\nsin un bostezo\n[Pre-Chorus]\ny se apaga\n[Chorus 2]\nmientras quede una luz\n[Bridge]\nlas estrellas\n[Outro]\nduerme tranquilo"
SCORE = {"lines": [{"i": 0, "text": "el faro guardaba", "t0": 1.0, "t1": 3.0,
                    "words": [{"w": "el", "t0": 1.0, "t1": 1.2}, {"w": "faro", "t0": 1.2, "t1": 1.8}, {"w": "guardaba", "t0": 1.9, "t1": 3.0}]},
                   {"i": 1, "text": "mientras quede una luz", "t0": 3.5, "t1": 6.0,
                    "words": [{"w": "mientras", "t0": 3.5, "t1": 4.0}, {"w": "luz", "t0": 5.2, "t1": 6.0}]}]}


def patches(ops):
    return {op["id"].split("-")[0]: op["patch"] for op in ops if op["op"] == "update_text"}


def test_every_look_is_a_valid_title_patch_and_reads_without_a_box_or_with_a_designed_one():
    from services.video2d_edit import _TEXT_BOXES, _TEXT_ENTERS, _TEXT_EXITS, _TEXT_FIELDS, _TEXT_FONTS, _TEXT_LOOPS
    assert len(looks()) >= 12
    for entry in looks().values():
        look = entry["look"]
        assert entry["template"] in TITLE_BUILDERS
        assert set(look) <= _TEXT_FIELDS, entry["id"]
        assert look["font"] in _TEXT_FONTS and look["loop"] in _TEXT_LOOPS
        assert look["enter"]["preset"] in _TEXT_ENTERS and look["exit"]["preset"] in _TEXT_EXITS
        assert look["box"]["kind"] in _TEXT_BOXES
        if look["box"]["kind"] in ("none", "underline"):
            assert look["stroke"]["width"] > 0 or look["shadow"]["blur"] > 0 or look["shadow"]["x"], f"{entry['id']} needs an outline or a shadow"
    fonts = {entry["look"]["font"] for entry in looks().values()}
    boxes = {entry["look"]["box"]["kind"] for entry in looks().values()}
    assert len(fonts) >= 6 and len(boxes) >= 3, "the catalog varies type, not only colour"


def test_sections_follow_the_written_tags_in_score_order():
    assert line_sections(LYRICS) == ["intro", "verse", "verse", "pre-chorus", "chorus", "bridge", "outro"]
    assert line_sections("sin etiquetas\notra") == ["verse", "verse"]


def test_a_section_map_picks_per_line_and_falls_back_sensibly():
    style = {"lyric_looks": {"verse": "quiet-left", "chorus": "big-word", "default": "cinema"}}
    assert look_for(style, "chorus")["id"] == "big-word"
    assert look_for(style, "pre-chorus")["id"] == "quiet-left"
    assert look_for(style, "bridge")["id"] == "cinema"
    assert look_for({"lyric_look": "neon"}, "chorus")["id"] == "neon"


def test_with_nothing_chosen_the_finish_picks_a_look_and_explicit_choices_keep_their_path():
    assert look_for({"finish": {"preset": "nightNeon"}}, "verse")["id"] == "neon"
    assert look_for({"finish": {"preset": "paperComic"}}, "verse")["id"] == "comic-caption"
    assert look_for({"finish": {"preset": "nightNeon"}, "lyric_template": "dymo"}, "verse") is None
    assert look_for({"finish": {"preset": "nightNeon"}, "theme": "tokyo-night"}, "verse") is None
    assert look_for({}, "verse") is None


def test_lyric_ops_apply_the_section_look_with_a_synced_entrance_and_lyric_style_on_top():
    style = {"lyric_looks": {"verse": "storybook", "chorus": "big-word"}, "lyric_style": {"color": "#112233"}}
    ops = lyric_ops(lambda _line: None, {"key": "s1"}, 0.0, 8.0, 8.0, SCORE, style, 0, ["verse", "chorus"])
    titles = [op for op in ops if op["op"] == "add_title"]
    assert [op["template"] for op in titles] == ["social-caption", "social-caption"]
    looked = patches(ops)
    assert looked["ly0"]["font"] == "hand" and looked["ly1"]["font"] == "display"
    assert looked["ly0"]["enter"] == {"preset": "words", "duration": 0.9}, "until 'guardaba' starts"
    assert looked["ly1"]["enter"] == {"preset": "words", "duration": 1.7}
    assert looked["ly0"]["color"] == looked["ly1"]["color"] == "#112233"


def test_without_a_look_lyrics_keep_the_template_they_always_had():
    ops = lyric_ops(lambda _line: None, {"key": "s1"}, 0.0, 8.0, 8.0, SCORE, {"lyric_template": "social-caption"}, 0, ["verse", "chorus"])
    assert all(op["op"] == "add_title" for op in ops), "no look: no patch beyond the template"


def test_unknown_looks_and_sections_are_refused():
    check_lyric_looks({"lyric_look": "cinema", "lyric_looks": {"chorus": "big-word"}})
    for bad in ({"lyric_look": "comic-sans"}, {"lyric_looks": {"hook": "neon"}}, {"lyric_looks": {"chorus": "nope"}}, {"lyric_looks": {}}):
        with pytest.raises(LyricLookError):
            check_lyric_looks(bad)


def test_a_look_patch_is_accepted_by_the_video2d_editor():
    from services.video2d_edit import edit
    for entry in looks().values():
        document = {"version": 1, "width": 1920, "height": 1080, "fps": 24, "duration": 4, "layers": [], "texts": []}
        ops = [{"op": "add_title", "id": "ly0", "template": entry["template"], "fields": {"caption": "una luz"}, "start": 0, "duration": 3}]
        ops += [{"op": "update_text", "id": f"ly0-{cue['id']}", "patch": entry["look"]}
                for cue in TITLE_BUILDERS[entry["template"]]({"caption": "una luz"}, {"start": 0, "duration": 3, "width": 1920, "height": 1080})]
        texts = edit({"version": 1, "input": {"document": document, "operations": ops, "full": True}})["result"]["document"]["texts"]
        assert texts[0]["font"] == entry["look"]["font"], entry["id"]
