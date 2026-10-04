"""A style preset keeps a cast consistent and picks a screen colour the subject does not wear."""
import json
from pathlib import Path

import pytest

from services.character_styles import screen_for, style_catalog, style_prompt


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


def test_the_ui_reads_the_same_file():
    source = (Path(__file__).resolve().parents[1] / "ui" / "src" / "lib" / "characterStyles.ts").read_text(encoding="utf-8")
    assert "app/shared/character_styles.json" in source
