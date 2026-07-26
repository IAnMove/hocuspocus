from types import SimpleNamespace

from PIL import Image

from app.services import director_pipeline
from app.services.director.renderers.ltx_i2v import LtxI2VRenderer
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


def test_i2v_prompt_always_anchors_illustrated_source_style():
    prompt = LtxI2VRenderer.ensure_source_style(
        "She turns toward camera while her coat and hair move in the wind.",
        SimpleNamespace(visual_style="2D anime, clean cel shading"),
    )

    assert "exact first frame" in prompt
    assert "do not restyle" in prompt
    assert "photorealistic" in prompt
    assert "2D anime, clean cel shading" in prompt


def test_nominal_24gb_gpu_is_not_misclassified_as_low_vram():
    assert _classify_vram_tier(True, 23.5) == "high"
    assert _classify_vram_tier(True, 22.0) == "low"
    assert _classify_vram_tier(False, 24.0) == "none"
