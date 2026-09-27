"""CPU song shorten: phase snap, crossfade time map, and montage remap."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from services.song_shorten import remap_montage, shorten_audio, snap_time, suggest_keep, write_wav


def _clicks(seconds: float = 8.0, bpm: float = 120.0, sample_rate: int = 22050) -> np.ndarray:
    audio = np.zeros(int(seconds * sample_rate), dtype=np.float32)
    step = int(round(sample_rate * 60.0 / bpm))
    burst = np.hanning(180).astype(np.float32)
    for index in range(0, len(audio) - len(burst), step):
        audio[index:index + len(burst)] += burst
    return audio


def test_cut_snaps_to_the_click_phase_not_the_original_instant():
    sample_rate = 22050
    audio = _clicks(sample_rate=sample_rate)
    snapped = snap_time(audio, sample_rate, 2.1)
    assert abs(snapped - 2.0) < 0.08
    assert abs(snapped - 2.0) < abs(snapped - 2.1)


def test_time_map_accounts_for_the_crossfade():
    sample_rate = 8000
    audio = np.zeros(sample_rate * 4, dtype=np.float32)
    mixed, time_map = shorten_audio(audio, sample_rate, [[0.0, 1.0], [2.0, 3.0]], snap=False)
    assert time_map[0][0] == 0
    assert time_map[0][1] == 0 and time_map[0][2] == 1
    assert abs(time_map[1][0] - (1.0 - 0.012)) < 1e-6
    assert time_map[1][1] == 2 and time_map[1][2] == 1
    assert abs(len(mixed) / sample_rate - (2.0 - 0.012)) < 0.002


def test_suggest_keep_drops_a_repeated_chorus_and_stays_under_the_limit():
    analysis = {
        "duration": 200,
        "sections": [
            {"label": "verse", "start": 0, "end": 40},
            {"label": "chorus", "start": 40, "end": 70},
            {"label": "verse", "start": 70, "end": 100},
            {"label": "chorus", "start": 100, "end": 130},
            {"label": "bridge", "start": 130, "end": 160},
            {"label": "instrumental", "start": 160, "end": 200},
        ],
    }
    keep = suggest_keep(analysis, 90)
    assert sum(end - start for start, end in keep) <= 90.01
    assert all(not (100 <= start < 130) for start, end in keep)
    assert keep[0] == [0.0, 40.0]


def test_remap_drops_a_gap_and_trims_the_overlap(tmp_path: Path):
    document = {
        "clips": [{"id": "c1", "trimStart": 0, "trimEnd": 10}, {"id": "c2", "trimStart": 1, "trimEnd": 11}],
        "overlays": [{"id": "gap", "start": 12, "end": 18}, {"id": "edge", "start": 8, "end": 14}],
        "audioCues": [{"id": "vo", "start": 25}],
    }
    # Kept original time: 0–10 and 20–30. Clip c2 occupies timeline 10–20, which is the gap.
    time_map = [[0.0, 0.0, 10.0], [10.0, 20.0, 10.0]]
    updated, report = remap_montage(document, time_map)
    assert [clip["id"] for clip in updated["clips"]] == ["c1"]
    assert updated["clips"][0]["trimEnd"] == 10
    dropped = {item["id"] for item in report["dropped"]}
    assert "c2" in dropped and "gap" in dropped
    edge = updated["overlays"][0]
    assert edge["id"] == "edge"
    assert edge["start"] == 8 and edge["end"] == 10
    assert updated["audioCues"][0]["start"] == 15
    destination = tmp_path / "out.wav"
    write_wav(str(destination), np.zeros(1000, dtype=np.float32), 8000)
    assert destination.stat().st_size > 44
