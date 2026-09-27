"""Mute speech that MiniMax H3 invents in clips planned as silent.

The fused 4-step H3 models sometimes fill an ambient-only soundtrack with
made-up voices, often babble that sounds like another language. The prompt
cannot reliably prevent it, so finished clips whose plan contains no dialogue
are checked with Whisper and only the detected speech spans are muted; the
rest of the ambience is kept.
"""

from __future__ import annotations

import os
import subprocess
import threading

# Seconds added around each detected span so word onsets and tails go too.
_SPAN_PADDING = 0.15
# Whisper's own confidence that a segment is not speech; above this the
# segment is treated as ambience (rumbles, impacts) and left audible.
_MAX_NO_SPEECH_PROBABILITY = 0.6

_model = None
_model_lock = threading.Lock()


def _ffmpeg() -> str:
    return os.environ.get("FFMPEG_BINARY", "ffmpeg")


def _whisper():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            # CPU keeps the check off the GPU that the next render needs.
            _model = WhisperModel("base", device="cpu", compute_type="int8")
        return _model


def merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def detect_speech_spans(path: str) -> list[tuple[float, float, str]]:
    """Return (start, end, text) for each confidently spoken segment."""
    segments, _info = _whisper().transcribe(
        path,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    return [
        (float(segment.start), float(segment.end), segment.text.strip())
        for segment in segments
        if segment.text.strip()
        and float(segment.no_speech_prob) < _MAX_NO_SPEECH_PROBABILITY
    ]


def mute_spans(path: str, spans: list[tuple[float, float]]) -> None:
    """Silence the given time spans in place; the video stream is copied."""
    padded = merge_spans([
        (max(0.0, start - _SPAN_PADDING), end + _SPAN_PADDING)
        for start, end in spans
    ])
    enable = "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in padded)
    root, ext = os.path.splitext(path)
    temporary = f"{root}.speechguard{ext}"
    try:
        subprocess.run(
            [
                _ffmpeg(), "-y", "-v", "error", "-i", path,
                "-map", "0", "-c:v", "copy",
                "-af", f"volume=enable='{enable}':volume=0",
                "-c:a", "aac", "-b:a", "192k",
                temporary,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def mute_invented_speech(path: str) -> list[tuple[float, float, str]]:
    """Mute any speech in a clip that should be silent; returns what was muted."""
    found = detect_speech_spans(path)
    if found:
        mute_spans(path, [(start, end) for start, end, _text in found])
    return found
