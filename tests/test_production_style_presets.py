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
        "neo-noir-realista": {"image_model": "qwen_image_21", "lyric_template": "social-caption"},
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


def test_style_without_a_preset_uses_qwen_with_its_own_step_count():
    assert validate_spec(_spec({}))["style"] == {"image_model": "qwen_image_21", "image_steps": 40}


def test_default_does_not_mutate_input_or_explicit_choices():
    spec = _spec({"image": "painted background", "image_steps": 28})
    expanded = validate_spec(spec)
    assert "image_model" not in spec["style"]
    assert expanded["style"]["image_model"] == "qwen_image_21"
    assert expanded["style"]["image_steps"] == 28
    explicit = {"image_model": "flux2_klein_9b", "image_steps": 4}
    assert validate_spec(_spec(explicit))["style"] == explicit


@pytest.mark.parametrize("memory,model", [(24564, "qwen_image_21"), (16384, "qwen_image_21"),
    (12288, "qwen_image_21_gguf_q4_k"), (10240, "qwen_image_21_gguf_q4_k"),
    (8192, "qwen_image_21"), (None, "qwen_image_21")])
def test_image_default_uses_capacity_without_claiming_unmeasured_quality(memory, model):
    from services.production_image_defaults import image_model_for_memory
    assert image_model_for_memory(memory) == model


def test_hardware_probe_failure_keeps_qwen_and_explicit_model_avoids_probe(monkeypatch):
    from services import production_image_defaults as defaults
    def unavailable(*args, **kwargs):
        raise OSError("nvidia-smi unavailable")
    monkeypatch.setattr(defaults.subprocess, "run", unavailable)
    defaults.default_image_model.cache_clear()
    assert defaults.default_image_model() == "qwen_image_21"
    defaults.default_image_model.cache_clear()
    monkeypatch.setattr(defaults, "default_image_model", lambda: pytest.fail("explicit choice probed hardware"))
    assert defaults.image_style_defaults({"image_model": "custom"}, {"image_model": "custom"}) == {"image_model": "custom"}


@pytest.mark.parametrize("output,model", [("12288\n", "qwen_image_21_gguf_q4_k"),
    ("24564\n", "qwen_image_21"), ("8192\n24564\n", "qwen_image_21")])
def test_capacity_probe_is_cached_and_does_not_guess_a_multi_gpu_target(monkeypatch, output, model):
    from services import production_image_defaults as defaults
    import subprocess
    calls = []
    def probe(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 2
        return subprocess.CompletedProcess(command, 0, output, "")
    monkeypatch.setattr(defaults.subprocess, "run", probe)
    defaults.default_image_model.cache_clear()
    try:
        assert defaults.default_image_model() == model
        assert defaults.default_image_model() == model
        assert len(calls) == 1
    finally:
        defaults.default_image_model.cache_clear()


def test_low_memory_default_reaches_the_validated_production_spec(monkeypatch):
    from services import production_image_defaults as defaults
    monkeypatch.setattr(defaults, "default_image_model", lambda: "qwen_image_21_gguf_q4_k")
    spec = validate_spec(_spec({"preset": "neo-noir-realista"}))
    assert spec["style"]["image_model"] == "qwen_image_21_gguf_q4_k"
    assert spec["style"]["image_steps"] == 40


@pytest.mark.parametrize("model", ["qwen_image_21", "qwen_image_21_gguf_q4_k"])
def test_explicit_qwen_does_not_inherit_flux_four_step_preset(model):
    style = {"preset": "neo-noir-realista", "image_model": model}
    assert validate_spec(_spec(style))["style"]["image_steps"] == 40
    assert validate_spec(_spec({**style, "image_steps": 28}))["style"]["image_steps"] == 28


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
