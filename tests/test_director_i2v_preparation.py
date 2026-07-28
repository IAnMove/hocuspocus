from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import director_pipeline
from app.services.director.renderers.ltx_i2v import LtxI2VRenderer
from app.services.director.policies import (
    apply_visual_style_lock,
    enforce_visual_style_on_clip_plans,
)
from app.services.hardware_detect import _classify_vram_tier


def test_ltx_resolution_is_aligned_before_image_preparation():
    assert (
        director_pipeline._normalize_video_resolution(
            "ltx2_22B_distilled_gguf_q6_k",
            "1280x720",
        )
        == "1280x704"
    )
    assert (
        director_pipeline._normalize_video_resolution(
            "ltx2_22B_distilled_fp8",
            "848x480",
        )
        == "832x448"
    )


def test_non_ltx_resolution_is_not_changed():
    assert (
        director_pipeline._normalize_video_resolution(
            "wan2_1_14B",
            "1280x720",
        )
        == "1280x720"
    )


def test_smart_fit_preserves_full_source_inside_fixed_canvas(tmp_path):
    source = tmp_path / "portrait.png"
    destination = tmp_path / "smart.png"
    image = Image.new("RGB", (100, 200), (220, 30, 20))
    # Distinct top and bottom bands make it possible to prove that contain
    # fitting did not crop either edge of the portrait.
    for y in range(10):
        for x in range(100):
            image.putpixel((x, y), (0, 255, 0))
            image.putpixel((x, 199 - y), (0, 0, 255))
    image.save(source)

    director_pipeline._fit_i2v_image(
        str(source),
        str(destination),
        "320x192",
        "smart",
    )

    with Image.open(destination) as fitted:
        assert fitted.size == (320, 192)
        # The contained portrait is 96 px wide and 192 px tall, centered.
        assert fitted.getpixel((160, 0)) == (0, 255, 0)
        assert fitted.getpixel((160, 191)) == (0, 0, 255)


def test_crop_fit_fills_requested_canvas(tmp_path):
    source = tmp_path / "portrait.png"
    destination = tmp_path / "crop.png"
    Image.new("RGB", (100, 200), (20, 30, 220)).save(source)

    director_pipeline._fit_i2v_image(
        str(source),
        str(destination),
        "320x192",
        "crop",
    )

    with Image.open(destination) as fitted:
        assert fitted.size == (320, 192)


def test_blank_black_comic_capture_is_rejected_before_video_generation(tmp_path):
    source = tmp_path / "black-panel.png"
    Image.new("RGB", (320, 192), (0, 0, 0)).save(source)

    with pytest.raises(RuntimeError, match="captured as a blank black image"):
        director_pipeline._prepare_provided_clip_images(
            "test-pipeline",
            [str(source)],
            expected_count=1,
            out_dir=str(tmp_path / "outputs"),
            resolution="320x192",
        )


def test_dark_but_detailed_comic_capture_is_not_rejected(tmp_path):
    source = tmp_path / "dark-panel.png"
    image = Image.new("RGB", (320, 192), (1, 1, 1))
    for x in range(100, 220):
        for y in range(60, 132):
            image.putpixel((x, y), (18, 12, 8))
    image.save(source)

    staged = director_pipeline._prepare_provided_clip_images(
        "test-pipeline",
        [str(source)],
        expected_count=1,
        out_dir=str(tmp_path / "outputs"),
        resolution="320x192",
    )

    assert len(staged) == 1
    assert (tmp_path / "outputs" / staged[0]).is_file()


def test_smart_comic_anchors_only_compatible_panels_on_the_same_page():
    params = {
        "comic_anchor_mode": "smart",
        "comic_shots": [
            {
                "page_number": 1,
                "characters": ["NARA"],
                "framing": "Medium shot",
            },
            {
                "page_number": 1,
                "characters": ["NARA"],
                "framing": "Close-up",
            },
            {
                "page_number": 2,
                "characters": ["KAEL"],
                "framing": "Wide establishing shot",
            },
        ],
    }

    assert director_pipeline._comic_end_image_filenames(
        params,
        ["panel-1.png", "panel-2.png", "panel-3.png"],
    ) == ["panel-2.png", "", ""]


def test_comic_anchor_manual_overrides_take_priority():
    params = {
        "comic_anchor_mode": "chain",
        "comic_shots": [
            {"transition_to_next": "cut"},
            {"transition_to_next": "interpolate"},
            {},
        ],
    }

    assert director_pipeline._comic_end_image_filenames(
        params,
        ["panel-1.png", "panel-2.png", "panel-3.png"],
    ) == ["", "panel-3.png", ""]


def test_smart_comic_anchors_do_not_guess_without_shot_metadata():
    assert director_pipeline._comic_end_image_filenames(
        {"comic_anchor_mode": "smart", "comic_shots": []},
        ["panel-1.png", "panel-2.png"],
    ) == ["", ""]


def test_faithful_comic_motion_guard_describes_both_approved_anchors():
    prompt = director_pipeline._comic_motion_prompt(
        "Her scarf moves in the breeze.",
        "faithful",
        True,
    )

    assert "subtly moving illustration" in prompt
    assert "do not invent objects or large pose changes" in prompt
    assert "next approved comic panel" in prompt


def test_i2v_prompt_always_anchors_illustrated_source_style():
    prompt = LtxI2VRenderer.ensure_source_style(
        "She turns toward camera while her coat and hair move in the wind.",
        SimpleNamespace(visual_style="2D anime, clean cel shading"),
    )

    assert "exact first frame" in prompt
    assert "do not restyle" in prompt
    assert "photorealistic" in prompt
    assert "2D anime, clean cel shading" in prompt


def test_story_anime_style_lock_rejects_live_action_recasting():
    prompt = apply_visual_style_lock(
        "The heroine turns toward the crystal tower.",
        "2D anime, clean cel shading, watercolor backgrounds",
        mode="video",
        preserve=True,
        has_reference=True,
    )

    assert prompt.startswith("VISUAL STYLE LOCK:")
    assert "2D anime" in prompt
    assert "no live action" in prompt
    assert "photorealistic people" in prompt
    assert "approved Story reference artwork" in prompt


def test_photoreal_story_lock_does_not_add_illustration_negative():
    prompt = apply_visual_style_lock(
        "A woman crosses the room.",
        "Photorealistic 35mm live-action drama",
        mode="video",
        preserve=True,
        has_reference=True,
    )

    assert "Photorealistic 35mm" in prompt
    assert "no live action" not in prompt
    assert "no 3D CGI" not in prompt


def test_story_style_lock_covers_images_windows_and_keyframes():
    plans = [{
        "image_prompt": "Opening frame.",
        "video_prompt": "",
        "window_prompts": ["First movement.", "Second movement."],
        "keyframe_prompts": ["Changed pose."],
    }]
    enforce_visual_style_on_clip_plans(
        plans,
        "European comic art, ink lines and flat color",
        preserve=True,
        has_reference=True,
    )

    assert "VISUAL STYLE LOCK:" in plans[0]["image_prompt"]
    assert plans[0]["video_prompt"] == ""
    assert all("VISUAL STYLE LOCK:" in item for item in plans[0]["window_prompts"])
    assert all("VISUAL STYLE LOCK:" in item for item in plans[0]["keyframe_prompts"])


def test_story_image_style_lock_respects_minimax_prompt_limit():
    prompt = apply_visual_style_lock(
        "Detailed opening-frame instruction " * 100,
        "2D anime, clean cel shading, watercolor backgrounds",
        mode="image",
        preserve=True,
        has_reference=True,
    )

    assert len(prompt) < 1500
    assert prompt.startswith("VISUAL STYLE LOCK:")


def test_nominal_24gb_gpu_is_not_misclassified_as_low_vram():
    assert _classify_vram_tier(True, 23.5) == "high"
    assert _classify_vram_tier(True, 22.0) == "low"
    assert _classify_vram_tier(False, 24.0) == "none"
