"""Regression coverage for the Video Editor's export-faithful monitor."""

from pathlib import Path


PANEL = (
    Path(__file__).resolve().parents[1]
    / "ui"
    / "src"
    / "features"
    / "video-editor"
    / "VideoEditorPanel.tsx"
)


def _panel_source() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_monitor_scales_one_intrinsic_export_canvas_without_distorting_it():
    source = _panel_source()

    assert "function ExportPreviewCanvas" in source
    assert "Math.min(bounds.width / width, availableHeight / height)" in source
    assert "width: `${width}px`" in source
    assert "height: `${height}px`" in source
    assert "transform: `scale(${scale})`" in source
    assert "transformOrigin: 'top left'" in source
    assert "data-export-width={width}" in source
    assert "data-export-height={height}" in source


def test_monitor_and_export_share_the_selected_resolution_and_fit_mode():
    source = _panel_source()

    assert source.count("<ExportPreviewCanvas") == 3
    assert source.count("width={resolution.width}") == 3
    assert source.count("height={resolution.height}") == 3
    assert "width: resolution.width" in source
    assert "height: resolution.height" in source
    assert "clip.fit === 'fill' ? 'object-cover' : 'object-contain'" in source
    assert "selected.fit === 'fill' ? 'object-cover' : 'object-contain'" in source
    assert "resolution.width >= resolution.height ? 'w-full' : 'h-full'" not in source


def test_monitor_identifies_the_real_raster_aspect_and_display_scale():
    source = _panel_source()

    assert "exportAspectLabel(width, height)" in source
    assert "{width}×{height} · {aspect} · {Math.round(scale * 100)}%" in source
    assert "Keep the readout outside the image so every output pixel remains visible" in source
