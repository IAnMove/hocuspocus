"""Frames sheet and group reference: the ffmpeg commands are built right, and real ffmpeg accepts them."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from services.production_sheets import compose_group, frames_sheet_command, group_command, make_frames_sheet


def _png(path, color):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360", "-frames:v", "1", str(path)], check=True)


def test_nothing_to_show_makes_no_command(tmp_path):
    assert frames_sheet_command(tmp_path, {}, "s.jpg") is None
    assert frames_sheet_command(tmp_path, {"a": "missing.png"}, "s.jpg") is None


def test_the_sheet_command_labels_each_frame_and_lays_out_a_grid(tmp_path):
    for name in ("a.png", "b.png", "c.png", "d.png", "e.png"):
        (tmp_path / name).write_bytes(b"x")
    command = frames_sheet_command(tmp_path, {"one": "a.png", "two words!": "b.png", "c": "c.png", "d": "d.png", "e": "e.png"}, "s.jpg")
    graph = command[command.index("-filter_complex") + 1]
    assert command.count("-i") == 5 and "text=two_words_" in graph and "inputs=5" in graph
    assert "0_0|426_0|852_0|1278_0|0_240" in graph                    # four columns, then a second row


def test_the_group_reference_puts_the_sheets_side_by_side(tmp_path):
    paths = [tmp_path / f"{n}.png" for n in "abc"]
    command = group_command(paths, tmp_path / "trio.png")
    graph = command[command.index("-filter_complex") + 1]
    assert command.count("-i") == 3 and "scale=426:704" in graph and "hstack=3" in graph and "pad=1280:704" in graph
    assert compose_group([], tmp_path / "x.png") is False and compose_group(paths, tmp_path / "x.png") is False   # missing files


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_ffmpeg_really_renders_both(tmp_path):
    names = {}
    for key, color in (("a", "red"), ("b", "green"), ("c", "blue")):
        _png(tmp_path / f"{key}.png", color)
        names[key] = f"{key}.png"
    assert make_frames_sheet(tmp_path, names, "sheet.jpg") == "sheet.jpg" and (tmp_path / "sheet.jpg").stat().st_size > 0
    assert compose_group([tmp_path / f"{key}.png" for key in "abc"], tmp_path / "trio.png")
    assert subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(tmp_path / "trio.png")],
                          capture_output=True, text=True).stdout.strip() == "1280,704"
