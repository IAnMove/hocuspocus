"""spec.resolution, spec.enhance, and the fit:fill crop. No GPU and no FlashVSR process."""
from __future__ import annotations

import pytest

from services.music_production import FRAME_RESOLUTIONS, ProductionError, validate_spec
from services.production_dry_run import dry_run
import services.production_enhance as enhance_module
from services.production_enhance import (
    clip_crop,
    crop_report,
    enhance_clip,
    legal_resolutions,
    resolved_resolution,
)


def _spec(**extra):
    spec = {
        "title": "t",
        "song": {"lyrics": "a\nb", "caption": "pop", "duration": 30, "bpm": 120},
        "style": {},
        "shots": [
            {"key": "intro", "kind": "still", "t0": 0, "still": "k"},
            {"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "a", "allow": ["still"]},
            {"key": "s1", "kind": "still", "line": 1, "still": "k"},
        ],
    }
    spec.update(extra)
    return spec


def test_omitted_resolution_stays_today_and_known_sizes_pass(monkeypatch):
    kept = validate_spec(_spec())
    assert "resolution" not in kept and "enhance" not in kept
    assert resolved_resolution(kept) == {"frames": "1280x704", "clips": "1280x704"}
    chosen = validate_spec(_spec(resolution={"frames": "1280x704", "clips": "1024x576"}))
    assert chosen["resolution"] == {"frames": "1280x704", "clips": "1024x576"}
    assert "1152x640" in legal_resolutions()
    for value in FRAME_RESOLUTIONS:
        assert value in legal_resolutions()
    monkeypatch.setattr("services.music_production.FRAME_RESOLUTIONS", ("1280x704",))
    assert validate_spec(_spec(resolution={"frames": "1152x640", "clips": "1152x640"}))["resolution"]["frames"] == "1152x640"
    with pytest.raises(ProductionError) as dropped:
        validate_spec(_spec(resolution={"clips": "1024x576"}))
    assert dropped.value.code == "invalid_spec"


def test_unknown_resolution_and_enhance_are_invalid_spec():
    with pytest.raises(ProductionError) as bad_size:
        validate_spec(_spec(resolution={"frames": "1920x1080"}))
    assert bad_size.value.code == "invalid_spec"
    with pytest.raises(ProductionError) as bad_shape:
        validate_spec(_spec(resolution="1280x704"))
    assert bad_shape.value.code == "invalid_spec"
    with pytest.raises(ProductionError) as bad_method:
        validate_spec(_spec(enhance={"method": "lanczos", "scale": 2}))
    assert bad_method.value.code == "invalid_spec"
    with pytest.raises(ProductionError) as bad_scale:
        validate_spec(_spec(enhance={"method": "flashvsr", "scale": 4}))
    assert bad_scale.value.code == "invalid_spec"
    assert validate_spec(_spec(enhance={"method": "rife", "scale": 2}))["enhance"]["method"] == "rife"


def test_enhance_adds_one_unmeasured_cost_line_and_leaves_minutes():
    plain = dry_run(_spec())
    boosted = dry_run(_spec(enhance={"method": "flashvsr", "scale": 2}))
    assert boosted["minutes"] == plain["minutes"]
    assert "enhance" not in {item["code"] for item in plain["warnings"]}
    line = next(item for item in boosted["warnings"] if item["code"] == "enhance")
    assert line["method"] == "flashvsr" and line["scale"] == 2 and line["measured"] is False
    assert line["clips"] == 1 and line["extra_minutes"] == 5
    ignored = dry_run(_spec(enhance={"method": "lanczos", "scale": 2}))
    assert ignored["minutes"] == plain["minutes"]
    assert "enhance" not in {item["code"] for item in ignored["warnings"]}


def test_enhance_clip_uses_the_tools_method_and_a_fake_upscaler(monkeypatch):
    seen = []

    def fake(path, method):
        seen.append((path, method))
        return path + ".up.mp4"

    assert enhance_clip("clip.mp4", _spec(), upscaler=fake) == "clip.mp4"
    assert seen == []
    calls = []
    real = enhance_module._selection_error

    def spy(spatial, temporal):
        calls.append((spatial, temporal))
        return real(spatial, temporal)

    monkeypatch.setattr(enhance_module, "_selection_error", spy)
    assert enhance_clip("clip.mp4", _spec(enhance={"method": "flashvsr", "scale": 2}), upscaler=fake) == "clip.mp4.up.mp4"
    assert enhance_clip("clip.mp4", _spec(enhance={"method": "rife", "scale": 2}), upscaler=fake) == "clip.mp4.up.mp4"
    assert calls == [("flashvsr2", ""), ("", "rife2")]
    assert seen == [("clip.mp4", "flashvsr2"), ("clip.mp4", "rife2")]
    with pytest.raises(ProductionError) as missing:
        enhance_clip("clip.mp4", _spec(enhance={"method": "flashvsr", "scale": 2}))
    assert missing.value.code == "enhance_unavailable"
    assert calls[-1] == ("flashvsr2", "")
    with pytest.raises(ProductionError) as invalid:
        enhance_clip("clip.mp4", _spec(enhance={"method": "flashvsr", "scale": 4}), upscaler=fake)
    assert invalid.value.code == "invalid_spec"
    assert seen == [("clip.mp4", "flashvsr2"), ("clip.mp4", "rife2")]


def test_crop_report_is_the_1280x704_fit_fill_into_1080p():
    report = crop_report(1280, 704, 1920, 1080)
    assert report["width"] == 1280 and report["height"] == 704
    assert report["source_aspect"] == 1.818 and report["output_aspect"] == 1.778
    assert report["crop_x"] > 0 and report["crop_y"] == 0
    same = crop_report(1920, 1080, 1920, 1080)
    assert same["crop_x"] == 0 and same["crop_y"] == 0
    tall = crop_report(704, 1280, 1920, 1080)
    assert tall["crop_x"] == 0 and tall["crop_y"] > 0
    origin = clip_crop({})
    assert origin["resolution"] == "1280x704"
    assert origin["source_aspect"] == 1.818 and origin["crop_x"] > 0
