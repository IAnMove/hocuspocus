"""SFX, looping music, jingles and voice lines for one game asset.

Retro effects stay on the CPU. MMAudio, ACE-Step and speech go through the
tool wrappers; their outputs are resolved against the workspace. Peak
normalisation happens after resampling so the delivered WAV keeps the
requested peak. Music loop points are sample indices; the analyzer reports
times in seconds and this module converts them. SFX variants share one
attempt. Music, jingles and voice lines make one attempt per candidate, each
with its own seed, intent ids and raw file names.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

from services.audio_levels import integrated_lufs
from services.game_audio import (
    best_loop,
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
from services.game_generators.base import (
    AttemptResult,
    GenContext,
    attempt_dir,
    candidate_dirs,
    candidate_result,
    relative,
    spec_seed,
)
from services.game_sfxr import PRESETS, generate
from services.game_tools import GameToolError, music, resolve_path, sfx, speech

_LOOP_JUMP = 0.05
_LOOP_RMS_DB = 2.0
_VOICE_LUFS = -16
# Measured loudness further than this from the target is reported, not hidden.
_LUFS_TOLERANCE = 1.0


def loop_warnings(sample_jump: float, rms_db: float) -> list[str]:
    """``loop_seam`` above a 0.05 sample jump or a 2 dB RMS change."""
    if float(sample_jump) > _LOOP_JUMP or abs(float(rms_db)) > _LOOP_RMS_DB:
        return ["loop_seam"]
    return []


def music_seconds(loop_seconds: float, bpm: float) -> float:
    """``loopSeconds`` plus four bars plus eight seconds of extra tail."""
    bars = 16.0 * 60.0 / float(bpm)
    return float(loop_seconds) + bars + 8.0


def jingle_seconds(seconds: float) -> float:
    """Ten seconds, or six seconds past ``seconds`` so a downbeat lies beyond the cut."""
    return max(10.0, float(seconds) + 6.0)


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


def _lines(asset: dict) -> list[str]:
    lines = _spec(asset).get("lines")
    if not isinstance(lines, list):
        return []
    return [str(line).strip() for line in lines if str(line).strip()]


def _seed(asset: dict, offset: int) -> int:
    return spec_seed(asset) + int(offset)


def _folder(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _merge(into: list, items: list) -> None:
    for item in items:
        if item not in into:
            into.append(item)


def _candidates(ctx: GenContext) -> list[tuple[str, Path, str]]:
    """``(attemptId, folder, tag)`` per candidate; the tag is empty for a single one.

    The tag keeps intent ids and raw outputs apart, so a second candidate never
    gets the first candidate's job back from the journal.
    """
    dirs = candidate_dirs(ctx, _count(ctx.asset))
    single = len(dirs) == 1
    return [(attempt_id, folder, "" if single else f"a{index}") for index, (attempt_id, folder) in enumerate(dirs, start=1)]


def _step(name: str, tag: str) -> str:
    return f"{name}-{tag}" if tag else name


def _raw_name(asset: dict, tag: str, rest: str) -> str:
    return f"{asset['id']}-{tag}-{rest}" if tag else f"{asset['id']}-{rest}"


def _each_candidate(ctx: GenContext, make) -> AttemptResult:
    """``make(ctx, index, folder, tag) -> ({files, metrics}, warnings)`` per candidate."""
    written: list[dict] = []
    warnings: list[str] = []
    for index, (attempt_id, folder, tag) in enumerate(_candidates(ctx)):
        row, found = make(ctx, index, _folder(folder), tag)
        written.append({"id": attempt_id, **row})
        _merge(warnings, found)
    return candidate_result(written, warnings, ctx.steps)


def _bpm(asset: dict, game: dict) -> float:
    spec = _spec(asset)
    if spec.get("bpm") is not None:
        return max(1.0, _number(spec.get("bpm"), 120))
    pair = _style_audio(game).get("bpm")
    if isinstance(pair, list) and len(pair) == 2:
        return max(1.0, (_number(pair[0], 90) + _number(pair[1], 140)) / 2.0)
    return 120.0


def _sample_rate(game: dict) -> int:
    return max(1, int(_number(_style_audio(game).get("sampleRate"), 48000)))


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


def _load(path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), always_2d=False)
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
    data, sr = _load(path)
    return {
        "peakDb": _peak_db(data),
        "duration": round(float(data.shape[0]) / float(sr), 4) if sr else 0.0,
        "lufs": integrated_lufs(str(path)),
    }


def _leveled(path: Path, target: float) -> tuple[dict, list[str]]:
    """Level ``path`` to ``target`` LUFS and measure it.

    ``lufs_normalize`` gives up quietly (ffmpeg failed, or the gain hit its
    20 dB cap), so a result still more than 1 LU off warns ``loudness_off_target``.
    """
    lufs_normalize(str(path), target)
    measured = _measure(path)
    lufs = measured["lufs"]
    if lufs is not None and abs(float(lufs) - float(target)) > _LUFS_TOLERANCE:
        return measured, ["loudness_off_target"]
    return measured, []


def _caption(*parts) -> str:
    return ", ".join(text for text in (str(part or "").strip() for part in parts) if text)


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


def _analyze(path) -> dict:
    from services.audio_analysis import analyze

    report = analyze(str(path), transcribe=False)
    return report if isinstance(report, dict) else {}


def _retro(spec: dict, seed: int) -> tuple[np.ndarray, int]:
    preset = str(spec.get("retroPreset") or "")
    if not preset:
        raise GameToolError("missing_preset", "retro sfx needs retroPreset")
    if preset not in PRESETS:
        raise GameToolError("unknown_preset", f"retroPreset {preset!r} is not one of {', '.join(sorted(PRESETS))}")
    data, sr = generate(preset, seed)
    return np.asarray(data, dtype=np.float64), int(sr)


def _sfx_audio(ctx: GenContext, engine: str, index: int, name: str) -> np.ndarray:
    """Variant ``index`` (1-based) shaped to ``seconds``, ``sfxPeakDb`` and ``sampleRate``."""
    spec = _spec(ctx.asset)
    seconds = _number(spec.get("seconds"), 1.0)
    # Above 0 dBFS the 16-bit WAV would clip.
    peak_db = min(0.0, _number(_style_audio(ctx.game).get("sfxPeakDb"), -1.0))
    seed = _seed(ctx.asset, index - 1)
    if engine == "retro":
        data, sr = _retro(spec, seed)
    else:
        asked = max(1, int(math.ceil(seconds)))
        raw = sfx(ctx, f"v{index}", prompt=_sfx_prompt(ctx.asset, ctx.game), seconds=asked, seed=seed, output_name=name)
        data, sr = _load(resolve_path(ctx, raw))
    return _shape_sfx(data, sr, seconds, peak_db, _sample_rate(ctx.game))


def _run_sfx(ctx: GenContext) -> AttemptResult:
    asset = ctx.asset
    engine = str(_spec(asset).get("engine") or "mmaudio")
    folder = _folder(attempt_dir(ctx))
    files: dict[str, str] = {}
    rows = []
    warnings: list[str] = []
    for index in range(1, _variants(asset) + 1):
        path = folder / f"{asset['id']}-{index}.wav"
        _write(path, _sfx_audio(ctx, engine, index, path.name), _sample_rate(ctx.game))
        row = {"file": path.name, **_measure(path)}
        if row["peakDb"] is None:
            _merge(warnings, ["sfx_silent"])
        files[str(index)] = relative(ctx, path)
        rows.append(row)
    return AttemptResult(files, {"engine": engine, "variants": rows}, warnings, {"steps": list(ctx.steps)})


def _music_prompt(asset: dict, game: dict) -> str:
    audio = _style_audio(game)
    return _caption(
        audio.get("genre"), audio.get("instruments"), _spec(asset).get("mood"), asset.get("description"),
        "seamless loopable game background music, no intro, no ending",
    )


def _grid_loop(frames: int, sr: int, target: float, bpm: float) -> tuple[int, int, int]:
    """A loop from 0 on the requested tempo, for audio without usable downbeats.

    Its length is the multiple of four bars nearest ``target`` that leaves one
    more bar after it; ``render_loop`` fades that bar into the start. When not
    even four bars fit, the whole buffer comes back unfaded.
    """
    bar = 240.0 * int(sr) / float(bpm)
    phrase = 4.0 * bar
    xf = int(round(bar))
    phrases = min(max(1, int(round(float(target) * int(sr) / phrase))), int((frames - xf) // phrase))
    if phrases < 1:
        return 0, int(frames), 0
    return 0, int(round(phrases * phrase)), xf


def _loop_points(path, audio: np.ndarray, sr: int, target: float, bpm: float) -> tuple[int, int, int, list[str]]:
    """``(start, end_exclusive, crossfade, warnings)`` for the loop nearest ``target`` seconds."""
    report = _analyze(path)
    beats = _samples(report.get("beats"), sr)
    downs = _samples(report.get("downbeats"), sr)
    start, end, _score, xf = best_loop(audio, sr, beats, downs, target)
    if int(xf) > 0:
        return int(start), int(end), int(xf), []
    # best_loop found no downbeat pair and returned the whole (too long) take.
    start, end, xf = _grid_loop(int(audio.shape[0]), sr, target, bpm)
    return start, end, xf, ["loop_no_downbeats"]


def _music_files(ctx: GenContext, folder: Path, loop: np.ndarray, sr: int) -> tuple[dict, dict, list[str]]:
    """Leveled WAV with ``smpl`` 0..len-1 and an Ogg with LOOPSTART/LOOPLENGTH."""
    wav_path = folder / f"{ctx.asset['id']}.wav"
    write_wav_loop(wav_path, loop, sr, 0, max(0, int(loop.shape[0]) - 1))
    # lufs_normalize keeps the smpl chunk and the sample count.
    measured, warnings = _leveled(wav_path, _number(_style_audio(ctx.game).get("musicLufs"), -16))
    leveled, leveled_sr = _load(wav_path)
    ogg_path = wav_path.with_suffix(".ogg")
    fallback = write_ogg_loop(ogg_path, leveled, leveled_sr, 0, int(leveled.shape[0]))
    files = {"wav": relative(ctx, wav_path)}
    if ogg_path.is_file():
        files["ogg"] = relative(ctx, ogg_path)
    seam = seam_metrics(leveled, leveled_sr)
    _merge(warnings, loop_warnings(seam["sample_jump"], seam["rms_db"]))
    if fallback:
        warnings.append(str(fallback))
    metrics = {
        "loopStart": 0,
        "loopEnd": max(0, int(leveled.shape[0]) - 1),
        "sampleJump": seam["sample_jump"],
        "rmsDb": seam["rms_db"],
        **measured,
    }
    return files, metrics, warnings


def _music_candidate(ctx: GenContext, index: int, folder: Path, tag: str) -> tuple[dict, list[str]]:
    asset = ctx.asset
    bpm = _bpm(asset, ctx.game)
    tempo = max(1, int(round(bpm)))
    target = _number(_spec(asset).get("loopSeconds"), 60)
    raw = resolve_path(ctx, music(
        ctx, _step("loop", tag), prompt="[Instrumental]", alt_prompt=_music_prompt(asset, ctx.game),
        seconds=music_seconds(target, bpm), seed=_seed(asset, index), bpm=tempo,
        output_name=_raw_name(asset, tag, "raw.wav"),
    ))
    audio, sr = _load(raw)
    start, end, xf, warnings = _loop_points(raw, audio, sr, target, tempo)
    files, metrics, found = _music_files(ctx, folder, render_loop(audio, sr, start, end, xf), sr)
    _merge(warnings, found)
    return {"files": files, "metrics": {**metrics, "bpm": round(bpm, 3)}}, warnings


def _jingle_prompt(asset: dict, game: dict, mood: str) -> str:
    audio = _style_audio(game)
    return _caption(
        audio.get("genre"), audio.get("instruments"), asset.get("description"),
        f"short {mood} game jingle, ends clearly",
    )


def _jingle_candidate(ctx: GenContext, index: int, folder: Path, tag: str) -> tuple[dict, list[str]]:
    asset = ctx.asset
    spec = _spec(asset)
    mood = str(spec.get("mood") or "victory")
    seconds = _number(spec.get("seconds"), 4)
    # ACE-Step sings ``prompt`` as lyrics; the description goes in ``alt_prompt``.
    raw = resolve_path(ctx, music(
        ctx, _step("jingle", tag), prompt="[Instrumental]", alt_prompt=_jingle_prompt(asset, ctx.game, mood),
        seconds=jingle_seconds(seconds), seed=_seed(asset, index), bpm=max(1, int(round(_bpm(asset, ctx.game)))),
        output_name=_raw_name(asset, tag, "raw.wav"),
    ))
    audio, sr = _load(raw)
    downs = _samples(_analyze(raw).get("downbeats"), sr)
    path = folder / f"{asset['id']}.wav"
    _write(path, cut_jingle(audio, sr, seconds, downs), sr)
    measured, warnings = _leveled(path, _number(_style_audio(ctx.game).get("musicLufs"), -16))
    return {"files": {"wav": relative(ctx, path)}, "metrics": {"mood": mood, "seconds": seconds, **measured}}, warnings


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


def _speaker(ctx: GenContext) -> tuple[dict | None, str]:
    """The character kit's voice, else ``None``, and the ``traits`` for voice design."""
    spec = _spec(ctx.asset)
    character = _character(ctx.game, str(spec.get("character") or ""))
    kit_id = str(((character or {}).get("spec") or {}).get("kitId") or "")
    voice = _kit_voice(ctx, kit_id) if kit_id else None
    return (voice if isinstance(voice, dict) else None), str(spec.get("traits") or "")


def _speech_extra(voice: dict, line: str, seed: int) -> tuple[str, dict]:
    from services.series_native_render import speech_params

    params = speech_params(voice, line, "english", seed)
    extra = {key: value for key, value in params.items() if key not in {"prompt", "model_type", "seed", "priority"}}
    return str(params.get("model_type") or voice.get("model") or ""), extra


def _speak(ctx: GenContext, step: str, name: str, seed: int, line: str, speaker: tuple[dict | None, str]) -> str:
    voice, traits = speaker
    if voice:
        model, extra = _speech_extra(voice, line, seed)
        return speech(ctx, step, prompt=line, model=model, seed=seed, output_name=name, extra=extra)
    extra = {"alt_prompt": traits} if traits else None
    return speech(ctx, step, prompt=line, model="qwen3_tts_voicedesign", seed=seed, output_name=name, extra=extra)


def _voice_take(ctx: GenContext, index: int, folder: Path, tag: str, lines: list[str], speaker) -> tuple[dict, list[str]]:
    """Every line once. Candidate ``index`` uses the seeds after the previous candidate's."""
    asset = ctx.asset
    files: dict[str, str] = {}
    rows = []
    warnings: list[str] = []
    for number, line in enumerate(lines, start=1):
        seed = _seed(asset, index * len(lines) + number - 1)
        raw = _speak(ctx, _step(f"line-{number}", tag), _raw_name(asset, tag, f"{number}.wav"), seed, line, speaker)
        data, sr = _load(resolve_path(ctx, raw))
        path = folder / f"{asset['id']}-{number}.wav"
        _write(path, to_mono(data), sr)
        measured, found = _leveled(path, _VOICE_LUFS)
        _merge(warnings, found)
        files[str(number)] = relative(ctx, path)
        rows.append({"file": path.name, "line": line, **measured})
    metrics = {"lines": len(lines), "voicedesign": speaker[0] is None, "takes": rows}
    return {"files": files, "metrics": metrics}, warnings


def _run_voice(ctx: GenContext) -> AttemptResult:
    lines = _lines(ctx.asset)
    if not lines:
        raise GameToolError("no_lines", "the voice asset has no lines to speak")
    speaker = _speaker(ctx)
    return _each_candidate(
        ctx, lambda run, index, folder, tag: _voice_take(run, index, folder, tag, lines, speaker),
    )


class SfxGenerator:
    kind = "sfx"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        # Retro effects are synthesized on the CPU; they wait for no tool.
        if str(_spec(asset).get("engine") or "") == "retro":
            return {}
        return {"sfx": _variants(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run_sfx(ctx)


class MusicGenerator:
    kind = "music"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        return {"music": _count(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _each_candidate(ctx, _music_candidate)


class JingleGenerator:
    kind = "jingle"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        return {"music": _count(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _each_candidate(ctx, _jingle_candidate)


class VoiceGenerator:
    kind = "voice"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        return {"sfx": max(1, len(_lines(asset))) * _count(asset)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run_voice(ctx)
