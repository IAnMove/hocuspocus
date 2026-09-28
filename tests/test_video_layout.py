"""Blur fill and crop focus for Video Editor clips and montage documents."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from services.montage_documents import MontageError, export_body, normalize_montage
from services.video_layout import layout_filter, read_layout, stamp_layout
from services.video_editor_frames import _normalise_clip


def test_layout_filter_strings_per_mode():
    fit = layout_filter(1080, 1920, "fit")
    assert "force_original_aspect_ratio=decrease" in fit
    assert "pad=1080:1920" in fit
    assert "split" not in fit

    centered = layout_filter(1080, 1920, "fill")
    assert "force_original_aspect_ratio=increase" in centered
    assert "crop=1080:1920:max(0\\,min(iw-ow\\,(iw-ow)*0.500000)):max(0\\,min(ih-oh\\,(ih-oh)*0.500000))" in centered

    corner = layout_filter(1080, 1920, "fill", focus_x=0, focus_y=100)
    assert "(iw-ow)*0.000000" in corner
    assert "(ih-oh)*1.000000" in corner

    blur = layout_filter(1080, 1920, "blur", blur_amount=0.65, background_dim=0.4)
    assert blur.startswith("split[bg][fg];")
    assert "gblur=sigma=26.7000" in blur
    assert "eq=brightness=-0.2000" in blur
    assert "force_original_aspect_ratio=decrease" in blur
    assert "overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2" in blur

    full = layout_filter(1080, 1920, "blur", blur_amount=1, background_dim=1)
    assert "gblur=sigma=40.0000" in full
    assert "eq=brightness=-0.5000" in full


def test_stamp_layout_clamps_and_keeps_omissions():
    bare = stamp_layout({"fit": "fit", "source": "a.mp4"})
    assert bare == {"fit": "fit", "source": "a.mp4"}
    stamped = stamp_layout({
        "fit": "nope",
        "focusX": 140,
        "focus_y": -3,
        "blurAmount": 0.2,
        "backgroundDim": "no",
    })
    assert stamped["fit"] == "fit"
    assert stamped["focus_x"] == 100
    assert stamped["focus_y"] == 0
    assert stamped["blur_amount"] == 0.2
    assert "background_dim" not in stamped
    assert "focusX" not in stamped
    assert read_layout({"fit": "blur"}) == ("blur", 50.0, 50.0, 0.65, 0.4)


def _montage():
    return {
        "version": 1, "name": "Frame", "width": 1920, "height": 1080, "fps": 24,
        "clips": [{"id": "c1", "source": "wide.mp4", "fit": "blur", "focusX": 20, "blurAmount": 0.5}],
    }


def test_montage_keeps_optional_frame_fields_and_exports_them():
    document = normalize_montage(_montage())
    clip = document["clips"][0]
    assert clip["fit"] == "blur"
    assert clip["focusX"] == 20
    assert clip["blurAmount"] == 0.5
    assert "focusY" not in clip and "backgroundDim" not in clip
    body = export_body(document, "x-song")
    assert body["clips"][0]["fit"] == "blur"
    assert body["clips"][0]["focus_x"] == 20
    assert body["clips"][0]["blur_amount"] == 0.5
    assert "focus_y" not in body["clips"][0]
    plain = normalize_montage({"version": 1, "name": "Old", "width": 1920, "height": 1080, "fps": 24,
                               "clips": [{"source": "old.mp4"}]})
    assert set(plain["clips"][0]) >= {"fit", "source"}
    assert "focusX" not in plain["clips"][0]
    assert plain["clips"][0]["fit"] == "fit"
    with pytest.raises(MontageError, match="fit, fill or blur"):
        normalize_montage({"version": 1, "name": "Bad", "width": 1920, "height": 1080, "fps": 24,
                           "clips": [{"source": "bad.mp4", "fit": "stretch"}]})


def _write_wide_clip(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24",
            "-frames:v", "8",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe required")
def test_blur_export_of_wide_clip_is_portrait(tmp_path: Path):
    source = tmp_path / "wide.mp4"
    destination = tmp_path / "portrait.mp4"
    _write_wide_clip(source)
    _normalise_clip(str(source), str(destination), {"fit": "blur", "trim_start": 0, "trim_end": 0}, 1080, 1920, 24)
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0",
            str(destination),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
    )
    assert probe.stdout.strip() == "1080,1920"
