"""style.preset expands to a look that already rendered."""
from __future__ import annotations

import json
from pathlib import Path
import runpy

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


def test_preset_ids_include_the_native_backplate_look():
    assert PRESET_IDS == ("anime", "riso-zine", "omarchy-desktop", "neo-noir-realista", "ps1-backplates")


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
        "ps1-backplates": {"image_model": "qwen_image_21", "singer": False},
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


def test_desktop_and_backplates_have_no_on_screen_singing():
    from services.production_style_presets import PRESETS
    assert PRESETS["omarchy-desktop"]["singer"] is False and PRESETS["omarchy-desktop"]["content"] == "screen"
    assert PRESETS["ps1-backplates"]["singer"] is False
    assert all("singer" not in PRESETS[name] for name in PRESETS if name not in ("omarchy-desktop", "ps1-backplates"))


def _backplate_client():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / "pinokio_agent/skills/api/hocuspocus/clients/native.py"))


def _ps1_spec():
    document = _backplate_client()["backplate_document"]("/api/v1/file/plate.png?workspace=demo", "/api/v1/file/actor.glb?workspace=demo")
    spec = _spec({"preset": "ps1-backplates"})
    spec["shots"] = [{"key": "walk", "kind": "scene3d", "t0": 0, "scene3d": {"document": document}}]
    return spec


def test_ps1_native_style_validates_and_keeps_authored_shots():
    raw = _ps1_spec()
    expanded = validate_spec(raw)
    assert expanded["style"]["preset"] == "ps1-backplates"
    assert expanded["style"]["image_model"] == "qwen_image_21"
    assert expanded["style"]["image_steps"] == 40
    assert expanded["style"]["singer"] is False
    assert expanded["shots"] is raw["shots"]
    assert raw["style"] == {"preset": "ps1-backplates"}


@pytest.mark.parametrize("change", ["h3", "sing", "camera", "camera_override", "floor", "dressing",
                                    "missing_image", "missing_actor", "subject_override", "atmosphere", "pixel_world", "fill_h3", "auto_plan"])
def test_ps1_rejects_a_wrong_engine_or_set_before_any_gpu_work(change):
    spec = _ps1_spec()
    shot = spec["shots"][0]
    config = shot["scene3d"]
    doc = config["document"]
    if change == "h3": shot.update(kind="h3", frame="actor", action="walks")
    elif change == "sing": shot["sing"] = True
    elif change == "camera": doc["camera"]["family"] = "orbit"
    elif change == "camera_override": config["camera"] = {"family": "orbit"}
    elif change == "floor": config["environment"] = {"floorStyle": "grid"}
    elif change == "dressing": doc["dressing"] = "studio"
    elif change == "missing_image": doc["slots"].pop(0)
    elif change == "missing_actor": doc["slots"].pop(1)
    elif change == "subject_override": config["subject"] = "actor.glb"
    elif change == "atmosphere": config["atmos"] = {"id": "city"}
    elif change == "pixel_world": config["pixelWorld"] = {"version": 1, "objects": []}
    elif change == "fill_h3": spec["fill"] = [{"kind": "h3", "frame": "actor", "action": "walks"}]
    elif change == "auto_plan": spec["shots"] = {"verse": "walks", "chorus": "dances"}
    with pytest.raises(ProductionError) as caught:
        validate_spec(spec)
    assert caught.value.code == "invalid_backplate_shot"


def test_ps1_saved_expanded_style_keeps_the_guard_on_resume():
    expanded = validate_spec(_ps1_spec())
    assert validate_spec(expanded)["style"] == expanded["style"]
    expanded["shots"][0]["scene3d"]["document"]["camera"]["family"] = "orbit"
    with pytest.raises(ProductionError) as caught:
        validate_spec(expanded)
    assert caught.value.code == "invalid_backplate_shot"


def test_ps1_recipe_preserves_authored_clip_and_motion():
    clip = {"index": 3, "name": "WalkCycle"}
    shot = _backplate_client()["backplate_shot"]("walk", "plate.png", "actor.glb", t0=8, duration=8,
        clip=clip, start=(1, 0, 0), end=(-1, 0, -.5), scale=1.2, clip_speed=1.1)
    clip["index"] = 99
    spec = _spec({"preset": "ps1-backplates"})
    spec["shots"] = [shot]
    assert validate_spec(spec)["shots"][0]["t0"] == 8
    doc = shot["scene3d"]["document"]
    actor = next(slot for slot in doc["slots"] if slot["media"] == "model3d")
    assert actor["clip"]["index"] == 3 and actor["clip"]["name"] == "WalkCycle"
    assert actor["scale"] == 1.2 and actor["motion"]["to"] == [-1, 0, -.5]
    assert actor["clipPlayback"]["speed"] == 1.1
    assert doc["camera"]["family"] == "fixed" and doc["environment"]["floorStyle"] == "none"
    assert doc["dressing"] == "none"
    assert any(slot.get("surface") == "environment" and slot["sourceUrl"] == "plate.png" for slot in doc["slots"])


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "ui/node_modules/tsx/dist/loader.mjs").is_file(), reason="UI dependencies not installed in Python-only CI")
def test_ps1_native_compiler_and_normalized_document_keep_the_backplate_contract():
    from services.production_scene3d import compile_document
    spec = _ps1_spec()
    shot = spec["shots"][0]
    doc = compile_document(shot, 8)  # CPU schema compilation; no renderer or CUDA.
    assert doc["camera"]["family"] == "fixed"
    assert doc["environment"]["floorStyle"] == "none" and doc.get("dressing") in (None, "none")
    assert len(doc["slots"]) == 2 and doc["slots"][0]["surface"] == "environment"
    shot["scene3d"]["document"] = doc
    assert validate_spec(spec)["style"]["preset"] == "ps1-backplates"


def test_ps1_dry_run_has_no_h3_frames():
    from services.production_dry_run import dry_run
    assert dry_run(validate_spec(_ps1_spec()))["h3_frames"] == 0
