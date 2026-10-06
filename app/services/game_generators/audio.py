"""SFX, looping music, jingles and voice lines for one game asset.

Retro effects stay on the CPU. MMAudio, ACE-Step and speech go through the
tool wrappers. Peak normalisation happens after resampling so the delivered
WAV keeps the requested peak. Music loop points are sample indices; the
analyzer reports times in seconds and this module converts them.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

from services.audio_levels import integrated_lufs
from services.game_audio import (
    cut_jingle,
    fades,
    lufs_normalize,
    peak_normalize,
    render_loop,
    seam_metrics,
    to_mono,
    trim_silence,
    write_ogg_loop,
    write_wav_loop,
)
from services.game_generators.base import AttemptResult, GenContext, attempt_dir
from services.game_sfxr import generate
from services.game_tools import music, sfx, speech

_LOOP_JUMP = 0.05
_LOOP_RMS_DB = 2.0
_VOICE_LUFS = -16


def loop_warnings(sample_jump: float, rms_db: float) -> list[str]:
    """``loop_seam`` above a 0.05 sample jump or a 2 dB RMS change."""
    if float(sample_jump) > _LOOP_JUMP or abs(float(rms_db)) > _LOOP_RMS_DB:
        return ["loop_seam"]
    return []


def music_seconds(loop_seconds: float, bpm: float) -> float:
    """``loopSeconds`` plus four bars plus eight seconds of extra tail."""
    bars = 16.0 * 60.0 / float(bpm)
    return float(loop_seconds) + bars + 8.0


def _spec(asset: dict) -> dict:
    spec = asset.get("spec")
    return spec if isinstance(spec, dict) else {}


def _style_audio(game: dict) -> dict:
    audio = (game.get("style") or {}).get("audio")
    return audio if isinstance(audio, dict) else {}


def _number(value, fallback: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(fallback)
    return float(value)


def _count(asset: dict) -> int:
    try:
        return max(1, int(asset.get("candidates") or 1))
    except (TypeError, ValueError):
        return 1


def _variants(asset: dict) -> int:
    try:
        return max(1, int(_spec(asset).get("variants") or 1))
    except (TypeError, ValueError):
        return 1


def _seed(asset: dict, index: int) -> int:
    try:
        base = int(_spec(asset).get("seed") or 1)
    except (TypeError, ValueError):
        base = 1
    return base + index


def _relative(ctx: GenContext, path: Path) -> str:
    return str(path.relative_to(Path(ctx.workspace_dir(ctx.workspace))))


def _folder(ctx: GenContext) -> Path:
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _bpm(asset: dict, game: dict) -> float:
    spec = _spec(asset)
    if spec.get("bpm") is not None:
        return max(1.0, _number(spec.get("bpm"), 120))
    pair = _style_audio(game).get("bpm")
    if isinstance(pair, list) and len(pair) == 2:
        return max(1.0, (_number(pair[0], 90) + _number(pair[1], 140)) / 2.0)
    return 120.0


def _resample(y: np.ndarray, src: int, dst: int) -> np.ndarray:
    audio = np.asarray(y, dtype=np.float64)
    if audio.size == 0 or int(src) == int(dst) or int(src) <= 0 or int(dst) <= 0:
        return audio
    count = max(1, int(round(audio.size * int(dst) / int(src))))
    if count == audio.size:
        return audio
    positions = np.linspace(0.0, audio.size - 1, count)
    left = np.floor(positions).astype(np.int64)
    right = np.minimum(left + 1, audio.size - 1)
    frac = positions - left
    return (1.0 - frac) * audio[left] + frac * audio[right]


def _fit(y: np.ndarray, sr: int, seconds: float) -> np.ndarray:
    limit = int(math.floor(float(seconds) * int(sr) + 1e-9))
    return np.asarray(y, dtype=np.float64)[: max(1, limit)]


def _peak_db(y: np.ndarray):
    audio = np.asarray(y, dtype=np.float64)
    if audio.size == 0:
        return None
    peak = float(np.max(np.abs(audio)))
    if peak <= 0.0:
        return None
    return round(20.0 * math.log10(peak), 3)


def _load(path: str) -> tuple[np.ndarray, int]:
    data, sr = sf.read(path, always_2d=False)
    return np.asarray(data, dtype=np.float64), int(sr)


def _write(path: Path, y: np.ndarray, sr: int) -> None:
    audio = np.asarray(y, dtype=np.float32)
    if audio.size == 0:
        audio = np.zeros(1, dtype=np.float32)
    sf.write(path, audio, int(sr), subtype="PCM_16")


def _shape_sfx(y: np.ndarray, sr: int, seconds: float, peak_db: float, sample_rate: int) -> np.ndarray:
    trimmed = trim_silence(np.asarray(y, dtype=np.float64), int(sr))
    clipped = _fit(trimmed, int(sr), seconds)
    faded = to_mono(fades(clipped, int(sr)))
    resampled = _resample(faded, int(sr), int(sample_rate))
    # Peak last: interpolation can lift the peak above the requested dBFS.
    return peak_normalize(_fit(resampled, int(sample_rate), seconds), peak_db)


def _measure(path: Path) -> dict:
    data, sr = _load(str(path))
    return {
        "peakDb": _peak_db(data),
        "duration": round(float(data.shape[0]) / float(sr), 4) if sr else 0.0,
        "lufs": integrated_lufs(str(path)),
    }


def _prompt_text(asset: dict) -> str:
    text = str(asset.get("description") or asset.get("name") or asset.get("id") or "").strip()
    return text or str(asset.get("id") or "sound")


def _sfx_prompt(asset: dict, game: dict) -> str:
    genre = str(_style_audio(game).get("genre") or "").strip()
    text = _prompt_text(asset)
    return f"{text} {genre}".strip()


def _index(value, sr: int) -> int:
    if isinstance(value, dict):
        value = value.get("time", 0)
    elif hasattr(value, "time"):
        value = value.time
    return int(round(float(value) * int(sr)))


def _samples(values, sr: int) -> list[int]:
    if not isinstance(values, list):
        return []
    return [_index(item, sr) for item in values]


def _bar_samples(beats: list[int], downbeats: list[int]) -> int:
    for points in (downbeats, beats):
        gaps = [b - a for a, b in zip(points, points[1:]) if b > a]
        if gaps:
            mean = sum(gaps) / len(gaps)
            return max(1, int(round(mean if points is downbeats else mean * 4.0)))
    return 1


def _analyze(path: str) -> dict:
    from services.audio_analysis import analyze

    report = analyze(path, transcribe=False)
    return report if isinstance(report, dict) else {}


def _best_loop(y, sr, beats, downbeats, target_s):
    from services.game_audio import best_loop

    return best_loop(y, sr, beats, downbeats, target_s)


def _level(path: Path, target: float) -> None:
    lufs_normalize(str(path), target)


def _run_sfx(ctx: GenContext) -> AttemptResult:
    asset = ctx.asset
    spec = _spec(asset)
    engine = str(spec.get("engine") or "mmaudio")
    seconds = _number(spec.get("seconds"), 1.0)
    peak_db = _number(_style_audio(ctx.game).get("sfxPeakDb"), -1.0)
    sample_rate = int(_number(_style_audio(ctx.game).get("sampleRate"), 48000))
    folder = _folder(ctx)
    files: dict[str, str] = {}
    rows = []
    for index in range(1, _variants(asset) + 1):
        path = folder / f"{asset['id']}-{index}.wav"
        if engine == "retro":
            shaped = _retro(spec, _seed(asset, index - 1), seconds, peak_db, sample_rate)
        else:
            asked = max(1, int(math.ceil(seconds)))
            raw = sfx(ctx, f"v{index}", prompt=_sfx_prompt(asset, ctx.game), seconds=asked, seed=_seed(asset, index - 1), output_name=path.name)
            data, sr = _load(raw)
            shaped = _shape_sfx(data, sr, seconds, peak_db, sample_rate)
        _write(path, shaped, sample_rate)
        files[str(index)] = _relative(ctx, path)
        rows.append({"file": path.name, **_measure(path)})
    return AttemptResult(files, {"engine": engine, "variants": rows}, [], {"steps": list(ctx.steps)})


def _retro(spec: dict, seed: int, seconds: float, peak_db: float, sample_rate: int) -> np.ndarray:
    preset = str(spec.get("retroPreset") or "")
    if not preset:
        from services.game_tools import GameToolError
        raise GameToolError("missing_preset", "retro sfx needs retroPreset")
    data, sr = generate(preset, seed)
    return _shape_sfx(np.asarray(data, dtype=np.float64), int(sr), seconds, peak_db, sample_rate)


def _music_prompt(asset: dict, game: dict) -> str:
    audio = _style_audio(game)
    parts = [
        str(audio.get("genre") or "").strip(),
        str(audio.get("instruments") or "").strip(),
        str(_spec(asset).get("mood") or "").strip(),
        str(asset.get("description") or "").strip(),
        "seamless loopable game background music, no intro, no ending",
    ]
    return ", ".join(part for part in parts if part)


def _loop_points(path: str, audio: np.ndarray, sr: int, target: float) -> tuple[int, int, int]:
    report = _analyze(path)
    beats = _samples(report.get("beats"), sr)
    downs = _samples(report.get("downbeats"), sr)
    start, end, _score = _best_loop(audio, sr, beats, downs, target)
    return int(start), int(end), _bar_samples(beats, downs)


def _run_music(ctx: GenContext) -> AttemptResult:
    asset = ctx.asset
    spec = _spec(asset)
    bpm = _bpm(asset, ctx.game)
    target = _number(spec.get("loopSeconds"), 60)
    asked = music_seconds(target, bpm)
    folder = _folder(ctx)
    raw_path = music(
        ctx, "loop", prompt="[Instrumental]", alt_prompt=_music_prompt(asset, ctx.game),
        seconds=asked, seed=_seed(asset, 0), bpm=int(round(bpm)), output_name=f"{asset['id']}-raw.wav",
    )
    audio, sr = _load(raw_path)
    start, end, fade = _loop_points(raw_path, audio, sr, target)
    loop = render_loop(audio, sr, start, end, fade)
    wav_path = folder / f"{asset['id']}.wav"
    _write(wav_path, loop, sr)
    _level(wav_path, _number(_style_audio(ctx.game).get("musicLufs"), -16))
    leveled, leveled_sr = _load(str(wav_path))
    write_wav_loop(wav_path, leveled, leveled_sr, 0, max(0, int(leveled.shape[0]) - 1))
    ogg_path = folder / f"{asset['id']}.ogg"
    warning = write_ogg_loop(ogg_path, leveled, leveled_sr, 0, int(leveled.shape[0]))
    seam = seam_metrics(leveled, leveled_sr)
    files = {"wav": _relative(ctx, wav_path)}
    if ogg_path.is_file():
        files["ogg"] = _relative(ctx, ogg_path)
    warnings = loop_warnings(seam["sample_jump"], seam["rms_db"])
    if warning:
        warnings.append(str(warning))
    metrics = {
        "loopStart": 0,
        "loopEnd": max(0, int(leveled.shape[0]) - 1),
        "sampleJump": seam["sample_jump"],
        "rmsDb": seam["rms_db"],
        "bpm": round(bpm, 3),
        "duration": round(float(leveled.shape[0]) / float(leveled_sr), 4),
    }
    return AttemptResult(files, metrics, warnings, {"steps": list(ctx.steps)})


def _run_jingle(ctx: GenContext) -> AttemptResult:
    asset = ctx.asset
    spec = _spec(asset)
    mood = str(spec.get("mood") or "victory")
    seconds = _number(spec.get("seconds"), 4)
    folder = _folder(ctx)
    raw_path = music(
        ctx, "jingle", prompt=f"short {mood} game jingle, ends clearly",
        alt_prompt=f"short {mood} game jingle, ends clearly",
        seconds=10, seed=_seed(asset, 0), bpm=int(round(_bpm(asset, ctx.game))),
        output_name=f"{asset['id']}-raw.wav",
    )
    audio, sr = _load(raw_path)
    downs = _samples(_analyze(raw_path).get("downbeats"), sr)
    clipped = cut_jingle(audio, sr, seconds, downs)
    path = folder / f"{asset['id']}.wav"
    _write(path, clipped, sr)
    _level(path, _number(_style_audio(ctx.game).get("musicLufs"), -16))
    return AttemptResult(
        {"wav": _relative(ctx, path)},
        {"mood": mood, "seconds": seconds, **_measure(path)},
        [],
        {"steps": list(ctx.steps)},
    )


def _character(game: dict, slug: str) -> dict | None:
    for asset in game.get("assets") or []:
        if asset.get("id") == slug and asset.get("kind") == "character":
            return asset
    return None


def _kit_voice(ctx: GenContext, kit_id: str):
    from services.character_kit_library import read_character_kit_library
    from services.series_shot_plan import voice_for

    library = read_character_kit_library(ctx.workspace_dir(ctx.workspace))
    kit = (library.get("kits") or {}).get(kit_id)
    if not isinstance(kit, dict):
        return None
    return voice_for(kit, "english")


def _speech_extra(voice: dict, line: str, seed: int) -> tuple[str, dict]:
    from services.series_native_render import speech_params

    params = speech_params(voice, line, "english", seed)
    extra = {key: value for key, value in params.items() if key not in {"prompt", "model_type", "seed", "priority"}}
    return str(params.get("model_type") or voice.get("model") or ""), extra


def _speak(ctx: GenContext, index: int, line: str, voice: dict | None, traits: str) -> str:
    seed = _seed(ctx.asset, index - 1)
    name = f"{ctx.asset['id']}-{index}.wav"
    if voice:
        model, extra = _speech_extra(voice, line, seed)
        return speech(ctx, f"line-{index}", prompt=line, model=model, seed=seed, output_name=name, extra=extra)
    extra = {"alt_prompt": traits} if traits else None
    return speech(ctx, f"line-{index}", prompt=line, model="qwen3_tts_voicedesign", seed=seed, output_name=name, extra=extra)


def _run_voice(ctx: GenContext) -> AttemptResult:
    spec = _spec(ctx.asset)
    lines = [str(line) for line in spec.get("lines") or [] if str(line).strip()]
    character = _character(ctx.game, str(spec.get("character") or ""))
    kit_id = str((character or {}).get("spec", {}).get("kitId") or "")
    voice = _kit_voice(ctx, kit_id) if kit_id else None
    traits = str(spec.get("traits") or "")
    folder = _folder(ctx)
    files: dict[str, str] = {}
    for index, line in enumerate(lines, start=1):
        raw = _speak(ctx, index, line, voice if isinstance(voice, dict) else None, traits)
        data, sr = _load(raw)
        path = folder / f"{ctx.asset['id']}-{index}.wav"
        _write(path, to_mono(data), sr)
        _level(path, _VOICE_LUFS)
        files[str(index)] = _relative(ctx, path)
    return AttemptResult(files, {"lines": len(lines), "voicedesign": voice is None}, [], {"steps": list(ctx.steps)})


class SfxGenerator:
    kind = "sfx"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        return {"sfx": _variants(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run_sfx(ctx)


class MusicGenerator:
    kind = "music"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        return {"music": _count(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run_music(ctx)


class JingleGenerator:
    kind = "jingle"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        return {"music": _count(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run_jingle(ctx)


class VoiceGenerator:
    kind = "voice"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        lines = _spec(asset).get("lines") if isinstance(_spec(asset).get("lines"), list) else []
        return {"sfx": max(1, len(lines)) * _count(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run_voice(ctx)
