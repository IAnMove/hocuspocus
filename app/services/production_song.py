"""Song generation, analysis, and which candidate wins."""
from __future__ import annotations

from typing import Any

from services.production_song_switch import remember_candidates


def _host():
    import services.music_production as host
    return host


def pick_song(candidates: dict[str, dict]) -> str:
    audio = _host().audio_analysis
    good = {k: v for k, v in candidates.items() if v.get("tail_rms", 1) <= audio.TAIL_CUT_RMS} or candidates
    return max(good, key=lambda k: good[k].get("recall") or 0)


def song(production: Any, spec: dict) -> None:
    if production.state.get("song"):
        return
    sp = spec["song"]
    if sp.get("file"):
        production.state["song"] = {"file": sp["file"]}
        remember_candidates(production.state, {"file": {"file": sp["file"]}})
        return production.log(f"song: using {sp['file']}")
    jobs = {}
    for seed in sp.get("seeds") or [11, 22, 33]:
        params = {"prompt": sp["lyrics"] or "[Instrumental]", "alt_prompt": sp["caption"], "model_type": sp.get("model", "ace_step_v1_5_xl_sft_lm_4b"), "seed": seed,
                  "generation_mode": "audio", "_audio_sub_mode": "music", "image_mode": 0, "video_length": 0, "lyrics_language": "en",
                  "duration_seconds": sp["duration"], "custom_settings": {"bpm": int(sp["bpm"]), "keyscale": sp.get("key", "A minor"), "timesignature": 4, "language": "en"}}
        r = production.mcp("generation.music", {"version": 2, "intent_id": f"{production.id}-song-{seed}", "input": {"workspace": production.ws, "params": params}})
        jobs[str(seed)] = ((r.get("receipt") or {}).get("result") or {}).get("job_id")
    candidates = {}
    audio = _host().audio_analysis
    for seed, name in production.wait(jobs).items():
        if not name:
            continue
        score = audio.analyze(str(production.root / name), sp["lyrics"], out_dir=str(production.root))
        candidates[seed] = {"file": name, "recall": score["recall"], "tail_rms": score["tail_rms"], "score_file": score["score_file"]}
        production.log(f"song seed {seed}: recall {score['recall']} tail {score['tail_rms']}")
    if not candidates:
        from services.music_production import ProductionError
        raise ProductionError("song_failed", "No song candidate finished")
    remember_candidates(production.state, candidates)
    best = pick_song(candidates)
    production.state["song"] = candidates[best]
    production.log(f"song: picked seed {best}")


def analyze(production: Any, spec: dict) -> None:
    if production.state.get("score"):
        return
    song_state = production.state["song"]
    if not song_state.get("score_file"):
        audio = _host().audio_analysis
        song_state["score_file"] = audio.analyze(str(production.root / song_state["file"]), spec["song"]["lyrics"], out_dir=str(production.root))["score_file"]
    production.state["score"] = song_state["score_file"]
    score = production.score()
    production.log(f"analyze: {score['bpm']} BPM, {len(score['lines'])} lines, recall {score['recall']}")


def score(production: Any) -> dict:
    import json
    return json.loads((production.root / production.state["score"]).read_text())
