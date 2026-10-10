"""Song generation and analysis for one production. The runner keeps the thin methods."""
from __future__ import annotations

import json
from typing import Any

from services import song_analysis as audio_analysis
from services.lyrics_language import canonical_lyrics_language, detect_language, validate_lyrics_language
from services.music_production import ProductionError, pick_song
from services.production_song_switch import remember_candidates


def song_language(song: Any) -> str:
    """The sung language code: ``song.language`` when set, else what the lyrics show, else ``""`` (unknown)."""
    if not isinstance(song, dict):
        return ""
    if song.get("language"):
        return canonical_lyrics_language(str(song["language"]))
    lyrics = str(song.get("lyrics") or "")
    found = detect_language(lyrics)
    # A guess the music admission would refuse (mixed lines) is no guess: such songs declare song.language.
    return found if found and validate_lyrics_language(lyrics, found)["ok"] else ""


def require_song_language(song: dict) -> None:
    value = song.get("language")
    if value not in (None, "") and not (isinstance(value, str) and canonical_lyrics_language(value)):
        raise ProductionError("invalid_spec", "song.language must be a language code or name such as es, en or Spanish")


def _music_params(song: dict, seed: int, language: str) -> dict:
    model = song.get("model", "ace_step_v1_5_xl_sft_lm_4b")
    params = {"prompt": song["lyrics"] or "[Instrumental]", "alt_prompt": song["caption"], "model_type": model, "seed": seed,
              "generation_mode": "audio", "_audio_sub_mode": "music", "image_mode": 0, "video_length": 0,
              "lyrics_language": language, "duration_seconds": song["duration"]}
    if model.startswith("ace_step_v1_5"):       # only ACE-Step 1.5 declares these; MiniMax-Music3 refuses any custom_settings
        params["custom_settings"] = {"bpm": int(song["bpm"]), "keyscale": song.get("key", "A minor"),
                                     "timesignature": 4, "language": language}
    return params


def generate_song(production: Any, spec: dict) -> None:
    if production.state.get("song"):
        return
    song = spec["song"]
    if song.get("file"):
        production.state["song"] = {"file": song["file"]}
        remember_candidates(production.state, {"file": {"file": song["file"]}})
        production.log(f"song: using {song['file']}")
        return
    language = song_language(song)
    jobs = {}
    for seed in song.get("seeds") or [11, 22, 33]:
        params = _music_params(song, seed, language or "en")      # English only when nothing tells
        reply = production.mcp("generation.music", {"version": 2, "intent_id": f"{production.id}-song-{seed}",
                                                    "input": {"workspace": production.ws, "params": params}})
        jobs[str(seed)] = ((reply.get("receipt") or {}).get("result") or {}).get("job_id")
        if not jobs[str(seed)]:     # say why: an admission refusal used to surface only as "No song candidate finished"
            production.log(f"song seed {seed} not admitted: {json.dumps(reply, default=str)[:160]}")
    candidates = {}
    for seed, name in production.wait(jobs).items():
        if not name:
            continue
        score = audio_analysis.analyze(str(production.root / name), song["lyrics"], out_dir=str(production.root),
                                       language=language or None)
        candidates[seed] = {"file": name, "recall": score["recall"], "tail_rms": score["tail_rms"], "score_file": score["score_file"]}
        production.log(f"song seed {seed}: recall {score['recall']} tail {score['tail_rms']}")
    if not candidates:
        raise ProductionError("song_failed", "No song candidate finished")
    remember_candidates(production.state, candidates)
    best = pick_song(candidates)
    production.state["song"] = candidates[best]
    production.log(f"song: picked seed {best}")


def analyze_song(production: Any, spec: dict) -> None:
    if production.state.get("score"):
        return
    song = production.state["song"]
    if not song.get("score_file"):
        song["score_file"] = audio_analysis.analyze(
            str(production.root / song["file"]), spec["song"]["lyrics"], out_dir=str(production.root),
            language=song_language(spec["song"]) or None)["score_file"]
    production.state["score"] = song["score_file"]
    score = production.score()
    production.log(f"analyze: {score['bpm']} BPM, {len(score['lines'])} lines, recall {score['recall']}")
