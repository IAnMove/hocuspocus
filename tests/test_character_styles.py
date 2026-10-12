"""A style preset keeps a cast consistent and picks a screen colour the subject does not wear."""
import json
from pathlib import Path

import pytest

from services.character_styles import character_style, preset_rig, screen_for, style_catalog, style_prompt
from services.flat_rig_look import rig_style


def test_the_catalog_is_complete_for_every_style():
    catalog = style_catalog()
    for style in catalog["styles"]:
        assert {"en", "es"} <= set(style["label"]) and {"en", "es"} <= set(style["summary"])
        for key in ("character", "pose", "prop"):
            assert "{description}" in style[key]
        assert "{screen}" in style["background"]
        assert style["kitStyle"] in {"cutout", "children-illustration", "anime-2d"}
    assert set(catalog["screens"]) == {"green", "blue", "magenta"}


def test_green_subjects_get_a_magenta_screen():
    assert screen_for("A nervous founder in an orange hoodie") == "green"
    assert screen_for("Una chica con chaqueta verde") == "magenta"
    assert screen_for("Emerald armour") == "magenta"
    assert screen_for("Evergreen tree") == "green", "only whole words starting with a green word count"


def test_a_prompt_fills_the_description_and_the_screen():
    built = style_prompt("paper-cutout", "character", "  Kevin,  messy red hair  ")
    assert "Kevin, messy red hair" in built["prompt"] and "chroma-key green" in built["prompt"]
    assert built["screen"] == "green" and "watermark" in built["negative"]
    assert "magenta" in style_prompt("paper-cutout", "prop", "a lime laptop")["prompt"]
    with pytest.raises(ValueError):
        style_prompt("paper-cutout", "scene", "x")
    with pytest.raises(KeyError):
        style_prompt("unknown", "character", "x")


def test_the_graphic_novel_style_asks_for_what_the_warp_rig_finds():
    style = character_style("graphic-novel")
    assert style["rig"] == preset_rig("graphic-novel") == {"mouthStyle": "warp"} and preset_rig("nope") == {}
    for kind in ("character", "pose"):
        built = style_prompt("graphic-novel", kind, "  Brother Anselmo,  a tall monk  ")
        # The rig finds the eyes by their white and the mouth as the painted line under them.
        assert "WHITE sclera" in built["prompt"] and "closed mouth painted as one short dark line" in built["prompt"]
        assert "never" in built["prompt"] and "Brother Anselmo, a tall monk" in built["prompt"]
        assert "chroma-key green" in built["prompt"] and "no cast shadow" in built["prompt"]
    assert {"open mouth", "eyes in shadow", "cast shadow"} <= {part.strip() for part in style["negative"].split(",")}
    assert "cropped body" not in style["negative"], "a bust pose is asked for by its description"


def test_the_agent_guide_shows_the_painted_path():
    from services.series_guide import guide_text
    guide = guide_text()
    section = guide[guide.index("## Painted / graphic-novel characters that talk"):guide.index("## The script")]
    for token in ('`style: "graphic-novel"`', '{"mouthStyle": "warp"}', "character-style-create", "mouth_line_guessed",
                  "mouth_line_unsure", "characters.rig.flat.preview", "mouthWidth", "Mouth line", "bust"):
        assert token in section, token


def test_every_style_rig_is_a_flat_rig_look():
    for style in style_catalog()["styles"]:
        assert rig_style(style["rig"])["mouthStyle"] in {"paper", "ink", "warp"}


def test_the_ui_reads_the_same_file():
    source = (Path(__file__).resolve().parents[1] / "ui" / "src" / "lib" / "characterStyles.ts").read_text(encoding="utf-8")
    assert "app/shared/character_styles.json" in source
