"""A cloned voice hears its reference with long pauses shortened; the user's file is never changed."""
from __future__ import annotations

import ast
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import wave

import pytest

from services import speech_reference_pauses as pauses
from services.speech_reference_pauses import (
    keep_filter,
    parse_duration,
    parse_peak,
    parse_silences,
    plan_keep,
    silence_threshold,
    tighten_clone_references,
    tightened_reference,
)

ROOT = Path(__file__).resolve().parents[1]
HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

# silencedetect at -35 dB on a 12.6 s reference whose short lines came back empty.
MEASURED_LOG = """Input #0, wav, from 'voice.wav':
  Duration: 00:00:12.62, bitrate: 384 kb/s
[Parsed_silencedetect_0 @ 0x1] silence_start: 2.821625
[Parsed_silencedetect_0 @ 0x1] silence_end: 3.424708 | silence_duration: 0.603083
[Parsed_silencedetect_0 @ 0x1] silence_start: 4.820042
[Parsed_silencedetect_0 @ 0x1] silence_end: 5.632 | silence_duration: 0.811958
[Parsed_silencedetect_0 @ 0x1] silence_start: 8.618042
[Parsed_silencedetect_0 @ 0x1] silence_end: 9.560333 | silence_duration: 0.942292
[Parsed_silencedetect_0 @ 0x1] silence_start: 10.665417
[Parsed_silencedetect_0 @ 0x1] silence_end: 11.190708 | silence_duration: 0.525292
[Parsed_silencedetect_0 @ 0x1] silence_start: 12.360333
[Parsed_silencedetect_0 @ 0x1] silence_end: 12.616875 | silence_duration: 0.256542
"""
LEVEL_LOG = "  Duration: 00:00:12.62, bitrate: 384 kb/s\n[Parsed_volumedetect_0 @ 0x1] max_volume: -2.9 dB\n"


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_REFERENCE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("FFMPEG_BINARY", "ffmpeg")


def _total(keep, duration):
    return sum((duration if end is None else end) - start for start, end in keep)


# --- The decision ---------------------------------------------------------


def test_every_long_pause_is_shortened_to_a_quarter_second_without_cutting_speech():
    duration = 12.616875
    keep = plan_keep(parse_silences(MEASURED_LOG), duration)
    assert keep is not None
    # Half of the kept pause stays after the speech before it, half before the speech after it.
    assert keep[0] == (0.0, pytest.approx(2.821625 + 0.125))
    assert keep[1][0] == pytest.approx(3.424708 - 0.125)
    removed = sum(end - start - 0.25 for start, end in [(2.821625, 3.424708), (4.820042, 5.632),
                                                        (8.618042, 9.560333), (10.665417, 11.190708)])
    assert _total(keep, duration) == pytest.approx(duration - removed)
    assert _total(keep, duration) == pytest.approx(10.734, abs=1e-3)
    # The trailing 0.26 s is within tolerance: the last span runs to the end of the file.
    assert keep[-1][1] is None


def test_a_reference_without_long_pauses_is_used_as_it_is():
    silences = [(0.0, 0.2), (1.4, 1.7), (3.0, 3.29), (4.71, 5.0)]
    assert plan_keep(silences, 5.0) is None
    assert plan_keep([], 5.0) is None


def test_silence_before_and_after_the_speech_is_trimmed_to_the_same_short_pad():
    keep = plan_keep([(0.0, 1.5), (3.0, 3.2), (4.0, None)], 6.0)
    assert keep == [(pytest.approx(1.25), pytest.approx(4.25))]
    keep = plan_keep([(-0.002, 0.9), (4.0, 6.0)], 6.0)  # silencedetect may start a hair before zero
    assert keep == [(pytest.approx(0.65), pytest.approx(4.25))]


def test_a_reading_that_would_leave_almost_nothing_keeps_the_original():
    assert plan_keep([(0.0, 3.0)], 3.0) is None
    assert plan_keep([(0.0, 2.0), (2.4, 5.0)], 5.0) is None


def test_silence_is_judged_against_the_recording_level():
    assert silence_threshold(-2.9) == -35.0
    assert silence_threshold(0.0) == -35.0
    assert silence_threshold(-20.0) == -50.0  # a quiet recording keeps its quiet speech
    assert silence_threshold(-70.0) is None
    assert silence_threshold(float("-inf")) is None
    assert silence_threshold(float("nan")) is None


def test_ffmpeg_logs_are_read():
    assert parse_duration(MEASURED_LOG) == pytest.approx(12.62)
    assert parse_duration("Duration: N/A") is None
    assert parse_peak(LEVEL_LOG) == -2.9
    assert parse_peak("max_volume: -inf dB") == float("-inf")
    assert parse_peak("") is None
    assert parse_silences("silence_start: 1.5\nsilence_end: 2 | silence_duration: 0.5\nsilence_start: 4.25") == [
        (1.5, 2.0), (4.25, None)]


def test_the_kept_spans_are_joined_sample_accurately():
    graph = keep_filter([(0.0, 1.5), (2.0, None)])
    assert graph == ("[0:a]asplit=2[s0][s1];[s0]atrim=start=0.000000:end=1.500000,asetpts=PTS-STARTPTS[k0];"
                     "[s1]atrim=start=2.000000,asetpts=PTS-STARTPTS[k1];[k0][k1]concat=n=2:v=0:a=1[out]")


# --- The cache, with ffmpeg mocked ---------------------------------------


class FakeFfmpeg:
    def __init__(self, silences=MEASURED_LOG, level=LEVEL_LOG, fail_render=False):
        self.silences, self.level, self.fail_render = silences, level, fail_render
        self.calls: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        assert kwargs.get("timeout")
        if "-filter_complex" in command:
            if self.fail_render:
                raise subprocess.CalledProcessError(1, command, stderr=b"broken")
            Path(command[-1]).write_bytes(b"RIFF" + b"\0" * 400)
            return subprocess.CompletedProcess(command, 0, b"", b"")
        audio_filter = command[command.index("-af") + 1]
        log = self.level if audio_filter == "volumedetect" else self.silences
        return subprocess.CompletedProcess(command, 0, "", log)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "voice.wav"
    path.write_bytes(b"RIFF-reference-bytes")
    return path


def test_the_shortened_copy_is_cached_beside_other_caches_and_reused(source, tmp_path, monkeypatch):
    fake = FakeFfmpeg()
    monkeypatch.setattr(pauses.subprocess, "run", fake)
    first = tightened_reference(str(source))
    assert Path(first).parent == tmp_path / "cache" and first.endswith(".wav")
    assert len(fake.calls) == 3
    assert "silencedetect=noise=-35.0dB:d=0.25" in fake.calls[1]
    assert source.read_bytes() == b"RIFF-reference-bytes"  # the user's file is untouched
    assert tightened_reference(str(source)) == first
    assert len(fake.calls) == 3  # repeated lines reuse the copy without ffmpeg


def test_the_default_cache_lives_with_the_other_runtime_caches(monkeypatch):
    monkeypatch.delenv("VOICE_REFERENCE_CACHE_DIR")
    assert pauses.cache_dir() == ROOT / "cache" / "voice-references"


def test_a_changed_reference_gets_a_new_copy(source, monkeypatch):
    monkeypatch.setattr(pauses.subprocess, "run", FakeFfmpeg())
    first = tightened_reference(str(source))
    source.write_bytes(b"RIFF-another-take")
    assert tightened_reference(str(source)) != first


def test_the_no_change_decision_is_remembered(source, tmp_path, monkeypatch):
    fake = FakeFfmpeg(silences="  Duration: 00:00:05.00\nsilence_start: 2\nsilence_end: 2.29\n")
    monkeypatch.setattr(pauses.subprocess, "run", fake)
    assert tightened_reference(str(source)) == str(source)
    assert len(fake.calls) == 2
    assert [path.suffix for path in (tmp_path / "cache").iterdir()] == [".keep"]
    assert tightened_reference(str(source)) == str(source)
    assert len(fake.calls) == 2


def test_a_silent_recording_is_not_analysed_further(source, monkeypatch):
    fake = FakeFfmpeg(level="  Duration: 00:00:05.00\nmax_volume: -91.0 dB\n")
    monkeypatch.setattr(pauses.subprocess, "run", fake)
    assert tightened_reference(str(source)) == str(source)
    assert len(fake.calls) == 1


@pytest.mark.parametrize("failure", ["render", "missing", "timeout", "unreadable"])
def test_any_ffmpeg_failure_uses_the_original_and_is_not_cached(source, tmp_path, monkeypatch, failure):
    fake = FakeFfmpeg(fail_render=failure == "render")
    if failure == "missing":
        monkeypatch.delenv("FFMPEG_BINARY")
        monkeypatch.setattr(pauses.shutil, "which", lambda _name: None)
    if failure == "timeout":
        def fake(command, **_kwargs):
            raise subprocess.TimeoutExpired(command, 120)
    if failure == "unreadable":
        fake = FakeFfmpeg(level="ffmpeg could not open the file")
    monkeypatch.setattr(pauses.subprocess, "run", fake)
    assert tightened_reference(str(source)) == str(source)
    cache = tmp_path / "cache"
    assert not cache.exists() or not list(cache.iterdir())
    monkeypatch.setattr(pauses.subprocess, "run", FakeFfmpeg())
    monkeypatch.setattr(pauses.shutil, "which", lambda _name: "ffmpeg")
    assert tightened_reference(str(source)) != str(source)  # a later run tries again


def test_a_missing_reference_is_left_for_the_model_to_report(tmp_path):
    missing = str(tmp_path / "gone.wav")
    assert tightened_reference(missing) == missing


def test_old_entries_are_pruned(tmp_path, monkeypatch):
    monkeypatch.setattr(pauses.subprocess, "run", FakeFfmpeg())
    monkeypatch.setattr(pauses, "MAX_ENTRIES", 2)
    paths = []
    for index in range(3):
        source = tmp_path / f"voice{index}.wav"
        source.write_bytes(f"take {index}".encode())
        paths.append(Path(tightened_reference(str(source))))
        if index < 2:
            os.utime(paths[-1], (1000 + index, 1000 + index))  # older than the next entry
    assert [path.exists() for path in paths] == [False, True, True]


# --- Which references are shortened --------------------------------------


def test_only_cloned_voice_references_are_swapped(source, monkeypatch):
    monkeypatch.setattr(pauses.subprocess, "run", FakeFfmpeg())
    second = source.with_name("second.wav")
    second.write_bytes(b"RIFF-second-speaker")
    params = {"model_type": "my_qwen3_base_finetune", "audio_guide": str(source), "audio_guide2": str(second),
              "audio_guide3": str(source), "alt_prompt": "the transcript"}
    tighten_clone_references(params, base_model_type={"my_qwen3_base_finetune": "qwen3_tts_base"}.get)
    assert params["audio_guide"] != str(source) and params["audio_guide2"] != str(second)
    assert params["audio_guide3"] == str(source)
    assert params["alt_prompt"] == "the transcript"
    for model in ("auk", "chatterbox", "ace_step_v1", "ltx2_19B"):
        other = {"model_type": model, "audio_guide": str(source)}
        assert tighten_clone_references(other, base_model_type=lambda name: name) == {
            "model_type": model, "audio_guide": str(source)}


def test_a_resolver_error_or_an_empty_reference_changes_nothing(source, monkeypatch):
    monkeypatch.setattr(pauses.subprocess, "run", FakeFfmpeg())

    def broken(_name):
        raise KeyError("unknown model")

    params = {"model_type": "qwen3_tts_base", "audio_guide": str(source), "audio_guide2": None}
    tighten_clone_references(params, base_model_type=broken)
    assert params["audio_guide"] != str(source)
    assert params["audio_guide2"] is None
    assert tighten_clone_references({"model_type": "qwen3_tts_base", "audio_guide": ""}) == {
        "model_type": "qwen3_tts_base", "audio_guide": ""}


def test_the_generation_worker_shortens_references_before_the_model_reads_them():
    tree = ast.parse((ROOT / "app" / "_launch_runtime.py").read_text(encoding="utf-8"))
    handler = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "error_handler"
                   and "generate_video" in ast.unparse(node))
    calls = [ast.unparse(node.func) for node in sorted((node for node in ast.walk(handler) if isinstance(node, ast.Call)),
                                                        key=lambda node: (node.lineno, node.col_offset))]
    order = [name for name in calls if name in {"tighten_clone_references", "wgp.generate_video"}]
    assert order == ["tighten_clone_references", "wgp.generate_video"]
    hook = next(node for node in ast.walk(handler) if isinstance(node, ast.Call)
                and ast.unparse(node.func) == "tighten_clone_references")
    assert ast.unparse(hook) == "tighten_clone_references(filtered_params, base_model_type=wgp.get_base_model_type)"


# --- Real ffmpeg on a synthetic reference --------------------------------


def _write_reference(path: Path, plan: list[tuple[str, float]], rate: int = 24000) -> None:
    frames = bytearray()
    for kind, seconds in plan:
        for index in range(int(seconds * rate)):
            value = 0.5 * math.sin(2 * math.pi * 220 * index / rate) if kind == "tone" else 0.0
            frames += struct.pack("<h", int(value * 32767))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(bytes(frames))


def _silences(path: str) -> tuple[float, list[float]]:
    log = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "silencedetect=noise=-35dB:d=0.1",
                          "-f", "null", "-"], capture_output=True, text=True, check=True).stderr
    duration = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                    capture_output=True, text=True, check=True).stdout)
    return duration, [round((duration if end is None else end) - start, 3) for start, end in parse_silences(log)]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_real_ffmpeg_shortens_pauses_and_edges_and_keeps_every_tone(tmp_path, monkeypatch):
    monkeypatch.delenv("FFMPEG_BINARY")
    source = tmp_path / "reference.wav"
    _write_reference(source, [("silence", 0.6), ("tone", 1.0), ("silence", 0.9), ("tone", 0.8),
                              ("silence", 0.2), ("tone", 0.7), ("silence", 1.2)])
    original = source.read_bytes()
    result = tightened_reference(str(source))
    assert result != str(source) and source.read_bytes() == original
    duration, silences = _silences(result)
    # 0.6 s lead -> 0.25, 0.9 s pause -> 0.25, the 0.2 s pause is kept, 1.2 s tail -> 0.25.
    assert silences == pytest.approx([0.25, 0.25, 0.2, 0.25], abs=0.01)
    assert duration == pytest.approx(2.5 + 0.25 * 3 + 0.2, abs=0.01)
    with wave.open(result, "rb") as output:
        assert (output.getframerate(), output.getnchannels()) == (24000, 1)
    assert tightened_reference(str(source)) == result


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required")
def test_real_ffmpeg_leaves_a_tight_reference_alone(tmp_path, monkeypatch):
    monkeypatch.delenv("FFMPEG_BINARY")
    source = tmp_path / "tight.wav"
    _write_reference(source, [("tone", 1.0), ("silence", 0.25), ("tone", 1.0), ("silence", 0.1)])
    assert tightened_reference(str(source)) == str(source)
