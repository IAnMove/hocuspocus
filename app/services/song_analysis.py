"""Song analysis for production: tempo grid, vocals, word-timed lyrics and a quality verdict.

``audio.analyze`` writes a score file next to the song and returns a short summary.
Everything runs on the CPU with models that Install already provides (BS-RoFormer,
faster-whisper small). Nothing is downloaded.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable

import numpy as np

CKPTS = Path(__file__).resolve().parents[1] / "ckpts"
ROFORMER = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"
OPERATION = "audio.analyze"
SCORE_SUFFIX = ".score.json"
TAIL_CUT_RMS = 0.05          # last 2 s louder than this: the song stops mid-phrase
MIN_RECALL = 0.8             # share of written lyric words that ASR hears in the vocals


class AudioAnalysisError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _plain(text: str) -> str:
    """Lowercase letters and digits with accents folded, so a sung "dormía" or "niña" still matches what ASR wrote."""
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower())


def words_of(lyrics: str) -> list[str]:
    """Lyric words without [section] tags or punctuation, lowercase."""
    plain = re.sub(r"\[[^\]]*\]", " ", lyrics or "")
    return [w for w in (_plain(t) for t in plain.split()) if w]


def lyric_lines(lyrics: str) -> list[str]:
    plain = re.sub(r"\[[^\]]*\]", "", lyrics or "")
    return [line.strip() for line in plain.split("\n") if line.strip()]


def _at(onset: np.ndarray, times: np.ndarray, grid: np.ndarray) -> np.ndarray:
    idx = np.searchsorted(times, grid)
    return onset[idx[idx < len(onset)]]


def tempo_grid(onset: np.ndarray, times: np.ndarray, duration: float, low: float = 70, high: float = 180,
               tie: float = 0.97) -> tuple[float, float]:
    """(bpm, first beat) whose grid lands on the strongest onsets. Beat trackers halve or double tempo on pop
    (librosa.beat_track reported 66 BPM for a 132 BPM song); an exhaustive period x phase search does not.
    Half tempo also lands on every strong hit, so among grids within `tie` of the best the fastest wins."""
    scored = []
    for bpm in np.arange(low, high, 0.05):
        period = 60.0 / bpm
        best_phase = max(((float(_at(onset, times, np.arange(phase, duration, period)).mean() or 0), float(phase))
                          for phase in np.arange(0, period, 0.004)), default=(0.0, 0.0))
        scored.append((best_phase[0], float(bpm), best_phase[1]))
    top = max(score for score, _, _ in scored)
    score, bpm, phase = max((item for item in scored if item[0] >= tie * top), key=lambda item: item[1])
    return round(bpm, 2), round(phase, 4)


def _matched_times(ref_words: list[str], heard: list[list[Any]]) -> tuple[list[list[float] | None], int]:
    times: list[list[float] | None] = [None] * len(ref_words)
    matcher = difflib.SequenceMatcher(None, [_plain(t) for t in ref_words], [_plain(str(w[2])) for w in heard], autojunk=False)
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            times[a + k] = [float(heard[b + k][0]), float(heard[b + k][1])]
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            for k in range(i2 - i1):
                w = heard[j1 + min(k, j2 - j1 - 1)]
                times[i1 + k] = [float(w[0]), float(w[1])]
    return times, sum(block.size for block in matcher.get_matching_blocks())


def _fill_gaps(times: list[list[float] | None]) -> list[list[float]]:
    """Words ASR missed get a time between their heard neighbours."""
    known = [i for i, t in enumerate(times) if t]
    filled: list[list[float]] = []
    for i, value in enumerate(times):
        if value is not None:
            filled.append(value)
            continue
        before = max((k for k in known if k < i), default=None)
        after = min((k for k in known if k > i), default=None)
        if before is None and after is None:
            filled.append([0.0, 0.0])
        elif before is None:
            filled.append([times[after][0] - 0.2] * 2)
        elif after is None:
            filled.append([times[before][1] + 0.2] * 2)
        else:
            filled.append([(times[before][1] + times[after][0]) / 2] * 2)
    return filled


def align_lines(lines: list[str], heard: list[list[Any]]) -> tuple[list[dict], float]:
    """Word times for the written lyrics from ASR words [[start, end, text], ...]; gaps are interpolated."""
    ref = [(index, token) for index, line in enumerate(lines) for token in line.replace("(", "").replace(")", "").split()]
    raw, matched = _matched_times([token for _, token in ref], heard)
    times = _fill_gaps(raw)
    out = []
    for index, line in enumerate(lines):
        words = [{"w": t, "t0": round(times[k][0], 3), "t1": round(times[k][1], 3)} for k, (i, t) in enumerate(ref) if i == index]
        if words:
            out.append({"i": index, "text": line, "t0": words[0]["t0"], "t1": words[-1]["t1"], "words": words})
    return out, round(matched / max(1, len(ref)), 3)


def verdict(recall: float | None, tail_rms: float) -> str:
    if tail_rms > TAIL_CUT_RMS:
        return "retake"
    if recall is not None and recall < MIN_RECALL:
        return "retake"
    return "ok"


def _separate_vocals(song: str, out_dir: str) -> str:
    from audio_separator.separator import Separator
    separator = Separator(model_file_dir=str(CKPTS / "roformer"), output_dir=out_dir, output_format="WAV")
    # Separator auto-selects CUDA; this operation promises the CPU scheduler lane.
    separator.torch_device = separator.torch_device_cpu
    separator.onnx_execution_provider = ["CPUExecutionProvider"]
    separator.load_model(model_filename=ROFORMER)
    target = os.path.join(out_dir, Path(song).stem + ".vocals.wav")
    for name in separator.separate(song):
        path = os.path.join(out_dir, name)
        if "Vocals" in name:
            os.replace(path, target)
        elif os.path.exists(path):
            os.remove(path)
    return target


def _transcribe(vocals: str, prompt: str, language: str | None = None) -> list[list[Any]]:
    """Word times from faster-whisper. ``language`` None lets Whisper detect it instead of forcing English."""
    import librosa
    from faster_whisper import WhisperModel
    snapshots = CKPTS / "whisper" / "models--Systran--faster-whisper-small" / "snapshots"
    model = WhisperModel(str(next(snapshots.iterdir())), device="cpu", compute_type="int8", cpu_threads=max(2, (os.cpu_count() or 4) // 2))
    audio, _ = librosa.load(vocals, sr=16000)
    segments, _ = model.transcribe(audio, language=language or None, word_timestamps=True, initial_prompt=prompt[:800] or None)
    return [[w.start, w.end, w.word.strip()] for segment in segments for w in segment.words]


def analyze(song: str, lyrics: str = "", *, out_dir: str | None = None, language: str | None = None) -> dict[str, Any]:
    """Full analysis. Writes <song>.score.json and returns it. ``language`` is the sung one (None: Whisper detects)."""
    import librosa
    out_dir = out_dir or os.path.dirname(song)
    y, sr = librosa.load(song, sr=22050, mono=True)
    duration = len(y) / sr
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256)
    bpm, beat0 = tempo_grid(onset, librosa.times_like(onset, sr=sr, hop_length=256), duration)
    tail = float(np.sqrt(np.mean(y[-sr * 2:] ** 2))) if len(y) > sr * 2 else 0.0
    score: dict[str, Any] = {"version": 1, "duration": round(duration, 3), "bpm": bpm, "beat": round(60 / bpm, 5), "beat0": beat0,
                             "tail_rms": round(tail, 4), "lines": [], "recall": None}
    score["beats"] = [round(t, 3) for t in np.arange(beat0 % (60 / bpm), duration, 60 / bpm)]
    if lyrics.strip():
        vocals = _separate_vocals(song, out_dir)
        lines, recall = align_lines(lyric_lines(lyrics), _transcribe(vocals, re.sub(r"\[[^\]]*\]", "", lyrics), language))
        score.update(lines=lines, recall=recall, vocals_file=os.path.basename(vocals))
    score["verdict"] = verdict(score["recall"], tail)
    path = os.path.join(out_dir, Path(song).stem + SCORE_SUFFIX)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(score, handle, ensure_ascii=False)
    score["score_file"] = os.path.basename(path)
    return score


def summary(score: dict[str, Any]) -> dict[str, Any]:
    return {key: score.get(key) for key in ("score_file", "vocals_file", "duration", "bpm", "beat0", "recall", "tail_rms", "verdict")} | {"lines": len(score.get("lines") or [])}


# ---------------------------------------------------------------- MCP
def command_catalog() -> list[dict[str, Any]]:
    from services.speech_file_commands import command_catalog as speech_catalog
    from services.phoneme_commands import command_catalog as phoneme_catalog
    return [{
        "name": OPERATION,
        "mutation": True,
        "description": ("Analyze a song in the workspace on the CPU: tempo grid (period x phase search), isolated vocals and, "
                        "when lyrics are given, word-timed lines aligned to the written lyrics. Writes <song>.score.json in the "
                        "workspace and returns a short summary with a verdict (retake when the song ends mid-phrase or less "
                        "than 80 % of the lyric words are heard). No GPU, no downloads."),
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"], "properties": {
            "version": {"type": "integer", "const": 1},
            "input": {"type": "object", "additionalProperties": False, "required": ["workspace", "file"], "properties": {
                "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                "file": {"type": "string", "minLength": 1, "maxLength": 300, "description": "Song file name in the workspace"},
                "lyrics": {"type": "string", "maxLength": 20000, "description": "Written lyrics; [Section] tags are ignored"},
            }},
        }},
    }] + speech_catalog() + phoneme_catalog()


def command_handlers(workspace_dir: Callable[[str], str]) -> dict[str, Callable[[Any], Any]]:
    from services.speech_file_commands import command_handlers as speech_handlers
    from services.phoneme_commands import command_handlers as phoneme_handlers
    async def handle(arguments: Any) -> dict[str, Any]:
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool
        from services import resource_scheduler
        from services.lyrics_language import detect_language
        data = (arguments or {}).get("input") if isinstance(arguments, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("workspace"), str) or not isinstance(data.get("file"), str):
            raise HTTPException(422, {"code": "invalid_command", "message": "Use version 1 with input.workspace and input.file", "retryable": False})
        root = Path(workspace_dir(data["workspace"])).resolve()
        song = (root / data["file"]).resolve()
        if root not in song.parents or not song.is_file():
            raise HTTPException(404, {"code": "file_not_found", "message": "Song not found in the workspace", "retryable": False})

        def run() -> dict[str, Any]:
            import uuid
            with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("audio-analysis"),
                                                        task_id=f"audio-analyze-{uuid.uuid4().hex}", description="Song analysis"):
                lyrics = data.get("lyrics") or ""
                return analyze(str(song), lyrics, out_dir=str(root), language=detect_language(lyrics) or None)
        score = await run_in_threadpool(run)
        return {"version": 1, "status": "completed", "operation": OPERATION, "result": summary(score)}

    return {OPERATION: handle, **speech_handlers(workspace_dir), **phoneme_handlers(workspace_dir)}
