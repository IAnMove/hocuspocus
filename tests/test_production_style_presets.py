"""style.preset expands to a look that already rendered."""
from __future__ import annotations

import json

import pytest

from services.music_production import ProductionError, validate_spec
from services.production_style_presets import PRESET_IDS, expand_style_preset

# The Love the Machine look without its DHH-specific footer and lip-sync line (those live in that spec).
RISO_ZINE = json.loads(r"""
{
  "image": "Wide 16:9 cyberpunk paper zine, bold flat risograph spot inks in persimmon orange, electric pink, cobalt blue and near-black on warm paper, coarse halftone grain, tiny offset registration, torn paper collage, punchy editorial composition, hand-cut shapes, expressive caricature, zero anime, zero photorealism, no embedded words or letters.",
  "video": "Cyberpunk paper zine motion, flat risograph ink, halftone texture, paper fibers and offset registration. Handmade cutout movement and snappy editorial rhythm.",
  "image_model": "qwen_image_21",
  "image_steps": 40,
  "lyric_template": "dymo",
  "footer_style": {
    "color": "#F4EEE2",
    "box": {
      "kind": "solid",
      "color": "#1B1718",
      "opacity": 0.95,
      "padding": 0.25
    }
  },
  "finish": {
    "preset": "risoPress"
  },
  "lyric_style": {
    "y": 86,
    "size": 3.3,
    "maxWidth": 82,
    "rotation": 0,
    "color": "#1B1718",
    "box": {
      "kind": "tape",
      "color": "#F4EEE2",
      "opacity": 1,
      "padding": 0.72,
      "radius": 0.18
    },
    "trap": true
  }
}
""")


def _spec(style: dict) -> dict:
    return {
        "title": "t",
        "song": {"lyrics": "a\nb", "caption": "pop", "duration": 30, "bpm": 120},
        "style": style,
        "shots": [{"key": "s0", "kind": "still", "t0": 0, "still": "k"}],
    }


def test_preset_ids_are_the_four_rendered_looks():
    assert PRESET_IDS == ("anime", "riso-zine", "omarchy-desktop", "neo-noir-realista")


def test_riso_zine_expands_to_the_generic_zine_look():
    spec = validate_spec(_spec({"preset": "riso-zine"}))
    assert spec["style"] == RISO_ZINE
    assert "preset" not in spec["style"]


def test_each_preset_validates_and_fills_the_look():
    expect = {
        "anime": {"image": "Cinematic anime key frame", "lyric_template": "social-caption"},
        "riso-zine": {"image_model": "qwen_image_21", "lyric_template": "dymo"},
        "omarchy-desktop": {"theme": "tokyo-night", "lyric_template": "social-caption"},
        "neo-noir-realista": {"image_model": "flux2_klein_9b", "lyric_template": "social-caption"},
    }
    for preset, fields in expect.items():
        style = validate_spec(_spec({"preset": preset}))["style"]
        assert style["image"] and style["video"] and style["finish"]
        for key, value in fields.items():
            got = style[key]
            assert got == value or (isinstance(got, str) and got.startswith(value))


def test_explicit_style_fields_override_the_preset():
    style = expand_style_preset(_spec({"preset": "riso-zine", "image": "flat pink zine"}))["style"]
    assert style["image"] == "flat pink zine"
    assert style["video"] == RISO_ZINE["video"]
    assert style["finish"] == RISO_ZINE["finish"]


def test_unknown_preset_is_a_stable_production_error():
    with pytest.raises(ProductionError) as caught:
        validate_spec(_spec({"preset": "watercolor"}))
    assert caught.value.code == "unknown_style_preset"
    with pytest.raises(ProductionError) as caught:
        validate_spec(_spec({"preset": 3}))
    assert caught.value.code == "unknown_style_preset"


def test_style_without_a_preset_is_unchanged():
    assert validate_spec(_spec({}))["style"] == {}


def test_no_preset_carries_a_person_or_project_name():
    from services.production_style_presets import PRESETS
    text = json.dumps(PRESETS).lower()
    for name in ("dhh", "37signals", "musk", "openai"):
        assert name not in text
    assert all("footer" not in style or style["footer"] for style in PRESETS.values())


def test_the_desktop_preset_puts_nobody_on_screen_and_the_others_do():
    from services.production_style_presets import PRESETS
    assert PRESETS["omarchy-desktop"]["singer"] is False and PRESETS["omarchy-desktop"]["content"] == "screen"
    assert all("singer" not in PRESETS[name] for name in PRESETS if name != "omarchy-desktop")
