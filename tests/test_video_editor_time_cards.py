"""Regression tests for Video Editor's inserted “Momentos después…” cards."""

from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from app.services import video_editor


def test_all_time_card_styles_render_original_canvas_assets(tmp_path: Path):
    for style in ("later-clock", "later-tropical", "later-cinematic"):
        destination = tmp_path / f"{style}.png"
        video_editor._draw_time_card(
            str(destination),
            style=style,
            text="Momentos después…",
            width=480,
            height=270,
        )

        with Image.open(destination) as card:
            assert card.size == (480, 270)
            assert card.mode == "RGB"
            assert len(card.getcolors(maxcolors=480 * 270) or []) > 8


def test_time_card_boundary_expands_into_a_real_inserted_segment(tmp_path: Path):
    segments = ["one.mp4", "two.mp4", "three.mp4"]
    durations = [4.0, 5.0, 6.0]
    transitions = [
        {"type": "later-tropical", "duration": 2.0, "text": "Un rato\ndespués…", "text_size": 75},
        {"type": "crossfade", "duration": 0.5, "text": ""},
    ]

    with patch.object(video_editor, "_render_time_card_segment") as render_card:
        expanded_segments, expanded_durations, expanded_transitions = (
            video_editor._materialise_time_cards(
                segments,
                durations,
                transitions,
                temp_dir=str(tmp_path),
                width=1280,
                height=720,
                fps=30,
            )
        )

    assert expanded_segments == [
        "one.mp4",
        str(tmp_path / "time_card_0000.mp4"),
        "two.mp4",
        "three.mp4",
    ]
    assert expanded_durations == [4.0, 2.0, 5.0, 6.0]
    assert expanded_transitions == [
        {"type": "none", "duration": 0.0},
        {"type": "none", "duration": 0.0},
        transitions[1],
    ]
    render_card.assert_called_once_with(
        str(tmp_path / "time_card_0000.mp4"),
        style="later-tropical",
        text="Un rato\ndespués…",
        text_size=75,
        duration=2.0,
        width=1280,
        height=720,
        fps=30,
    )


def test_time_card_transition_is_classified_as_inserted_not_overlapped():
    assert video_editor.is_interstitial_transition("later-clock")
    assert video_editor.is_interstitial_transition("later-tropical")
    assert video_editor.is_interstitial_transition("later-cinematic")
    assert not video_editor.is_interstitial_transition("crossfade")


def test_time_card_text_keeps_manual_breaks_and_wraps_long_words():
    canvas = Image.new("RGB", (640, 360))
    draw = ImageDraw.Draw(canvas)
    font = video_editor._load_time_card_font(28)

    authored_lines = video_editor._wrap_time_card_text(
        draw,
        "Primera línea\nSegunda línea",
        font,
        600,
    )
    wrapped_word = video_editor._wrap_time_card_text(
        draw,
        "palabralarguísimasinespacios1234567890",
        font,
        95,
    )

    assert authored_lines == ["Primera línea", "Segunda línea"]
    assert len(wrapped_word) > 1
    assert all(video_editor._time_card_text_width(draw, line, font) <= 95 for line in wrapped_word)


def test_time_card_text_size_changes_the_rendered_card(tmp_path: Path):
    small = tmp_path / "small.png"
    large = tmp_path / "large.png"
    settings = {
        "style": "later-cinematic",
        "text": "Un poco\nmás tarde…",
        "width": 640,
        "height": 360,
    }

    video_editor._draw_time_card(str(small), text_size=60, **settings)
    video_editor._draw_time_card(str(large), text_size=140, **settings)

    assert small.read_bytes() != large.read_bytes()


def test_time_card_text_normalisation_preserves_line_breaks():
    assert video_editor.normalise_time_card_text("  Uno  \r\n  Dos   tres  ") == "Uno\nDos tres"
