"""Generated and imported takes get their shot's sound and the episode's frame at the cut; cues can play part of a file."""
from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from services.series_shot_extras import normalize_clip_fields, sfx_entry, sfx_tracks
from services.series_shot_plan import normalize_layout2d
from services.series_sound_cuts import cut_fields, materialize_cuts
from services.series_take_sound import (
    episode_frame, fit_mode, needs_conform, plan_take_sound, prepare_clips, prepared_note, probe_clip, sound_tracks,
    video_filter,
)

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="ffmpeg required")
SMALL = {"width": 160, "height": 90, "fps": 24}


def _clip(path: Path, size: str = "320x176", rate: int = 30, seconds: float = 2.0, tone: bool = True) -> Path:
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration={seconds}"]
    if tone:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}:sample_rate=44100"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", *(["-c:a", "aac", "-shortest"] if tone else []), str(path)]
    subprocess.run(command, check=True, capture_output=True)
    return path


def _beep(path: Path, seconds: float = 1.0, rate: int = 48000, channels: int = 1) -> Path:
    samples = (np.sin(np.linspace(0, 2 * np.pi * 880 * seconds, int(rate * seconds))) * 20000).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(np.repeat(samples, channels).tobytes())
    return path


def _levels(path: Path, seconds: float) -> np.ndarray:
    """Mean absolute level of the mixed audio in 0.1 s windows."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         check=True, capture_output=True).stdout
    audio = np.abs(np.frombuffer(raw, dtype="<i2").astype(np.float32))
    windows = int(seconds * 10)
    return np.array([audio[i * 800:(i + 1) * 800].mean() if audio[i * 800:(i + 1) * 800].size else 0 for i in range(windows)])


def _episode():
    return {"shots": [
        {"id": "e1s00", "productionMethod": "animation_2d", "layout2d": {"sfx": [{"file": "boom.wav", "at": 0.5}]}},
        {"id": "e1s01", "productionMethod": "generated_video",
         "layout2d": {"sfx": [{"file": "boom.wav", "at": 0.5, "volume": 0.8}], "clipAudio": "drop", "clipFit": "contain"}},
        {"id": "e1s02", "productionMethod": "imported_video", "layout2d": {"clipAudio": "keep", "clipVolume": 1.0}},
    ]}


def test_layout_keeps_clip_fields_and_sfx_cuts():
    layout = normalize_layout2d({"sfx": [{"file": "steps.wav", "at": 1, "in": 2.5, "length": 0.4}, {"file": "x.wav", "in": -1}],
                                 "clipAudio": "drop", "clipVolume": 0.5, "clipFit": "contain"})
    assert layout["sfx"][0] == {"file": "steps.wav", "at": 1.0, "volume": 0.8, "in": 2.5, "length": 0.4}
    assert "in" not in layout["sfx"][1]
    assert normalize_clip_fields({"clipAudio": "mute", "clipVolume": 3, "clipFit": "stretch"}) == {}
    assert cut_fields({"in": 0, "length": 0.001}) == {}
    tracks = sfx_tracks({"sfx": [sfx_entry({"file": "steps.wav", "at": 1, "in": 2.5, "length": 0.4})]}, [], 5.0)
    assert tracks[0]["trimStart"] == 2.5 and tracks[0]["trimLength"] == 0.4


def test_only_video_shots_get_their_sound_at_the_cut():
    clips = [{"shotId": "e1s00"}, {"shotId": "e1s01"}, {"shotId": "e1s02"}]
    frame = plan_take_sound({"provider": {"videoSettings": {"orientation": "portrait"}}}, _episode(), clips)
    assert frame == {"width": 1080, "height": 1920, "fps": 24}
    assert "takeSound" not in clips[0]
    assert clips[1]["takeSound"] == {"sfx": [{"file": "boom.wav", "at": 0.5, "volume": 0.8}], "clipAudio": "drop"}
    assert clips[1]["clipFit"] == "contain"
    assert "takeSound" not in clips[2], "keeping the clip's own sound at volume 1 is nothing to do"
    assert episode_frame({}) == {"width": 1920, "height": 1080, "fps": 24}


def test_effects_play_at_their_second_and_music_from_its_start():
    tracks = sound_tracks({"sfx": [{"file": "a.wav", "line": 2, "anchor": "end", "offset": 0.25},
                                   {"file": "b.wav", "at": 1.5, "in": 1.0, "length": 0.3}],
                           "music": {"file": "m.wav", "volume": 0.4, "start": 0}}, 4.0)
    assert [(item["filename"], item["startTime"]) for item in tracks] == [("a.wav", 0.25), ("b.wav", 1.5), ("m.wav", 0.0)]
    assert tracks[1]["trimStart"] == 1.0 and tracks[1]["trimLength"] == 0.3


def test_conform_decisions():
    info = {"width": 1280, "height": 704, "sar": 1.0, "fps": 30.0}
    frame = {"width": 1920, "height": 1080, "fps": 24}
    assert needs_conform(info, frame)
    assert not needs_conform({"width": 1920, "height": 1080, "sar": 1.0, "fps": 24.0}, frame)
    assert fit_mode(info, frame) == "cover"  # 1.82 vs 1.78: crop a sliver instead of bars
    assert fit_mode({"width": 1080, "height": 1920, "sar": 1.0}, frame) == "contain"
    assert fit_mode(info, frame, "contain") == "contain"
    anamorphic = video_filter({"width": 1440, "height": 1080, "sar": 4 / 3}, frame, "cover")
    assert anamorphic.startswith("scale=trunc(iw*sar/2)*2:ih,") and "setsar=1,fps=24" in anamorphic


@needs_ffmpeg
def test_a_generated_take_is_conformed_and_gets_its_effect_without_its_own_sound(tmp_path):
    clip = _clip(tmp_path / "h3.mp4")
    _beep(tmp_path / "boom.wav", seconds=0.3)
    clips = [{"shotId": "e1s01", "takeSound": {"sfx": [{"file": "boom.wav", "at": 1.0, "volume": 0.8}], "clipAudio": "drop"}}]
    paths, report = prepare_clips([str(clip)], clips, SMALL, str(tmp_path), str(tmp_path / "prep"), gain=lambda _path: 1.0)
    assert paths[0] != str(clip) and Path(paths[0]).is_file()
    info = probe_clip(paths[0])
    assert (info["width"], info["height"], round(info["fps"])) == (160, 90, 24) and info["audio"]
    assert abs(info["duration"] - 2.0) < 0.1
    assert report == [{"shotId": "e1s01", "conformed": True, "from": "320x176@30", "fit": "cover", "sounds": 1,
                       "clipAudio": "drop", "mixedInputs": 1}]
    levels = _levels(Path(paths[0]), 2.0)
    assert levels[2:8].max() < 50, "the clip's own tone is dropped"
    assert levels[10:13].min() > 500, "the effect plays at 1.0 s"
    assert "1 clip conformed" in prepared_note(report) and "1 video take with its shot's sound" in prepared_note(report)


@needs_ffmpeg
def test_a_clip_in_the_episode_format_without_sound_is_joined_as_it_is(tmp_path):
    clip = _clip(tmp_path / "native.mp4", size="160x90", rate=24)
    paths, report = prepare_clips([str(clip)], [{"shotId": "e1s00"}], SMALL, str(tmp_path), str(tmp_path / "prep"))
    assert paths == [str(clip)] and report == [] and not (tmp_path / "prep").exists()


@needs_ffmpeg
def test_kept_clip_sound_is_mixed_under_the_effect_and_video_is_copied(tmp_path):
    clip = _clip(tmp_path / "imported.mp4", size="160x90", rate=24)
    _beep(tmp_path / "boom.wav", seconds=0.2)
    clips = [{"shotId": "e1s02", "takeSound": {"sfx": [{"file": "boom.wav", "at": 0.2}], "clipVolume": 0.5}}]
    paths, report = prepare_clips([str(clip)], clips, SMALL, str(tmp_path), str(tmp_path / "prep"), gain=lambda _path: 1.0)
    assert report[0]["conformed"] is False and report[0]["clipAudio"] == "keep" and report[0]["mixedInputs"] == 2
    assert _levels(Path(paths[0]), 2.0)[12:18].min() > 200, "the clip's tone is still there"


@needs_ffmpeg
def test_a_missing_sound_file_fails_with_its_name(tmp_path):
    clip = _clip(tmp_path / "h3.mp4", size="160x90", rate=24)
    with pytest.raises(ValueError, match="nope.wav"):
        prepare_clips([str(clip)], [{"shotId": "s", "takeSound": {"sfx": [{"file": "nope.wav", "at": 0}]}}], SMALL,
                      str(tmp_path), str(tmp_path / "prep"))


def test_an_unreadable_clip_is_left_to_the_join(tmp_path):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not a video")
    paths, report = prepare_clips([str(fake)], [{"shotId": "s", "takeSound": {"clipAudio": "drop"}}], SMALL, str(tmp_path),
                                  str(tmp_path / "prep"))
    assert paths == [str(fake)] and "sound left out" in report[0]["warning"]


@needs_ffmpeg
def test_a_cue_part_is_cut_once_with_its_provenance(tmp_path):
    _beep(tmp_path / "steps.wav", seconds=2.0, rate=44100, channels=2)
    tracks = [{"id": "sfx-0", "filename": "steps.wav", "startTime": 0.5, "trimStart": 0.5, "trimLength": 0.4},
              {"id": "sfx-1", "filename": "steps.wav", "startTime": 1.0}]
    made = materialize_cuts(tmp_path, tracks)
    name = tracks[0]["filename"]
    assert name.startswith("steps-cut-") and name.endswith(".wav") and len(made) == 1
    assert tracks[0]["cutFrom"] == {"file": "steps.wav", "in": 0.5, "length": 0.4} and "trimStart" not in tracks[0]
    assert tracks[1] == {"id": "sfx-1", "filename": "steps.wav", "startTime": 1.0}
    with wave.open(str(tmp_path / name)) as handle:
        assert handle.getframerate() == 44100 and handle.getnchannels() == 2
        assert abs(handle.getnframes() / 44100 - 0.4) < 0.01
    sidecar = json.loads((tmp_path / name).with_suffix(".meta.json").read_text())
    assert sidecar["origin"]["tool"] == "series-sound-cut" and sidecar["lineage"]["parents"][0]["uri"] == "steps.wav"
    stamp = (tmp_path / name).stat().st_mtime_ns
    again = [{"filename": "steps.wav", "trimStart": 0.5, "trimLength": 0.4}]
    materialize_cuts(tmp_path, again)
    assert again[0]["filename"] == name and (tmp_path / name).stat().st_mtime_ns == stamp


@needs_ffmpeg
def test_a_video_takes_foley_is_laid_when_made_and_named_when_not(tmp_path):
    from services.series_video_foley import sound_name
    clip = _clip(tmp_path / "h3.mp4", size="160x90", rate=24, tone=False)
    foley = {"prompt": "waves", "volume": 0.5, "episodeId": "ep1", "shotId": "e1s04"}
    clips = [{"shotId": "e1s04", "takeSound": {"foley": foley}}]
    _paths, report = prepare_clips([str(clip)], clips, SMALL, str(tmp_path), str(tmp_path / "prep"), gain=lambda _path: 1.0)
    assert report[0]["foley"] is False and "foley not made yet" in report[0]["warning"]
    _beep(tmp_path / sound_name(str(clip), "ep1", "e1s04", foley), seconds=2.0)
    paths, report = prepare_clips([str(clip)], clips, SMALL, str(tmp_path), str(tmp_path / "prep2"), gain=lambda _path: 1.0)
    assert report[0]["foley"] is True and "warning" not in report[0] and report[0]["mixedInputs"] == 1
    assert _levels(Path(paths[0]), 2.0)[2:15].min() > 200, "the foley plays under the silent clip"
