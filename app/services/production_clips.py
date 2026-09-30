"""H3 clip jobs, take judging, and the retake loop."""
from __future__ import annotations

import json
import subprocess
import uuid
from typing import Any

from services.production_control import checkpoint, sleep_until
from services.production_disk import discard
from services.production_takes import another_take, better_take, note_seconds, obsolete_clip, pending_windows, take_settled


def _host():
    import services.music_production as host
    return host


def clip_job(production: Any, spec: dict, w: dict, seed: int, take: int = 0) -> str | None:
    """Retakes change strategy, not only the seed: even takes are driven by the full mix (best on the
    pilot, r 0.41 vs 0.16), odd takes by the isolated vocals for songs whose mix drowns the voice."""
    frames = _host().h3_frames_for(w["t1"] - w["t0"])
    vocals = production.score().get("vocals_file")
    source = vocals if take % 2 == 1 and vocals and w.get("sing") else production.state["song"]["file"]
    slice_name = f"{production.id}-slice-{w['key']}-{take}.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(w["t0"]), "-t", str(frames / 24), "-i", str(production.root / source),
                    "-ar", "48000", "-ac", "2", str(production.root / slice_name)], check=True)
    discard(production.state, slice_name)
    sing = " (S1) sings the lead vocal of the mapped driving audio, lips, jaw and breath in precise sync with every syllable." if w.get("sing") else ""
    prompt = (f"integrated_multimodal_description: [Shot 1] {(spec.get('style') or {}).get('video', '')} {w['action']}{sing}\n"
              "overall_soundscape: The mapped driving audio: the song.\nnon_diegetic_music: N/A")
    params = {"prompt": prompt, "model_type": "minimax_h3_fused_turbo", "resolution": "1280x704", "seed": seed, "generation_mode": "video",
              "workspace": production.ws, "image_prompt_type": "S", "image_start": production.upload(production.state["frames"][w["key"]])[0],
              "video_length": frames, "sliding_window_size": frames, "num_inference_steps": 4, "guidance_scale": 1, "image_mode": 0,
              "input_video_strength": 1.0, "audio_prompt_type": "A", "audio_guide": production.upload(slice_name)[0]}
    # a resumed run must not collide with the journal entry of an earlier take
    r = production.mcp("generate", {"request_id": f"{production.id}-{w['key']}-{seed}-{uuid.uuid4().hex[:8]}", "params": params})
    job = r.get("job_id") or (r.get("result") or {}).get("job_id")
    if not job:
        production.log(f"clip {w['key']} not admitted: {json.dumps(r)[:140]}")
    return job


def judge_take(production: Any, w: dict, name: str | None, take: int, vocals: str | None) -> bool:
    """Record one take; True when the clip needs no more takes. Sung shots keep the best lip-sync r; other shots keep the best visual score."""
    from services.production_clip_qa import clip_qa
    key, failed, clips = w["key"], production.state.setdefault("clip_failures", {}), production.state.setdefault("clips", {})
    if not name:
        failed[key] = production.failures.get(key, "no output")
        production.log(f"clip {key} take {take}: failed ({failed[key]})")
        return False
    failed.pop(key, None)
    qa = clip_qa(str(production.root / name), bool(w.get("sing")), str(production.root / vocals) if vocals else None, w["t0"], w["t1"])
    drive = "vocals" if (take - 1) % 2 == 1 and w.get("sing") else "mix"
    production.log(f"clip {key} take {take} ({drive}): {qa.get('verdict')} r={qa.get('best_r')}")
    production.state.setdefault("takes", {}).setdefault(key, []).append(
        {"file": name, "take": take, "verdict": qa.get("verdict"), "r": qa.get("best_r"), "drive": drive})
    best = clips.get(key)
    # Obsolete r was measured on the previous song; ranking it would keep the
    # old take and throw away the clip shot against the new window.
    ranking = None if obsolete_clip(best) else best
    previous = (ranking.get("qa") or {}).get("best_r") if ranking else None
    if not ranking or better_take(qa, (ranking.get("qa") or {})):
        if ranking and ranking.get("file") and ranking["file"] != name:
            discard(production.state, ranking["file"])
        clips[key] = {"file": name, "qa": qa, "url": production.upload(name)[1]}
    else:
        discard(production.state, name)
    return take_settled(qa, previous)


def _prior_takes(state: dict, key: str) -> int:
    return sum(1 for line in state.get("log") or [] if line.startswith(f"clip {key} take "))


def _land_one(production: Any, key: str, name: str | None, by_key: dict, tried: dict, budget: dict,
              retake: tuple, vocals: str | None, lost: dict, landed: set, retry_keys: set) -> None:
    """Judge and record one clip as soon as it exists: a restart mid-round keeps the ones already shot."""
    if key in landed:
        return
    landed.add(key)
    if key in production.lost and lost.get(key, 0) < _host().MAX_LOST_JOBS:
        lost[key] = lost.get(key, 0) + 1      # not a take: the job vanished, so shoot it again
        production.log(f"clip {key}: job lost (queue restarted), not counted as a take")
        retry_keys.add(key)
        return
    tried[key] += 1
    if another_take(production.judge_take(by_key[key], name, tried[key], vocals), tried[key], budget[key], key in retake):
        retry_keys.add(key)
    production.save()


def _shoot_round(production: Any, spec: dict, pending: list, tried: dict, budget: dict,
                 retake: tuple, vocals: str | None, pause: float) -> list:
    host = _host()
    checkpoint(getattr(production, "_cancel", None))
    started = host.time.perf_counter()
    by_key = {shot["key"]: shot for shot in pending}
    retry_keys: set[str] = set()
    landed: set[str] = set()
    lost = production.state.setdefault("clip_lost", {})

    def land(key: str, name: str | None) -> None:
        _land_one(production, key, name, by_key, tried, budget, retake, vocals, lost, landed, retry_keys)

    production.on_landed = land
    try:
        jobs = {shot["key"]: production.clip_job(spec, shot, 7000 + shot["i"] * 10 + tried[shot["key"]], tried[shot["key"]]) for shot in pending}
        names = production.wait(jobs)
    finally:
        production.on_landed = None
    for shot in pending:
        land(shot["key"], names.get(shot["key"]))         # a wait that reports only at the end (a stub) lands them here
    retry = [shot for shot in pending if shot["key"] in retry_keys]
    note_seconds(production.state, pending, host.time.perf_counter() - started)
    production.save()
    if retry and not any(names.values()):
        sleep_until(getattr(production, "_cancel", None), pause, host.time.sleep)
    return retry


def clips(production: Any, spec: dict, windows: list[dict], retake: tuple[str, ...] = (), pause: float = 60) -> None:
    """Shoot missing clips (or retake keys). Flat lip-sync r, max_takes, or 4 recorded takes stop an automatic
    shoot; an explicit retake may pass the cap. The best r is kept. A fully failed round waits before the next."""
    from services.production_shot_review import without_locked
    windows = without_locked(production, windows)
    production.state.setdefault("clips", {})
    tried = production.state.setdefault("clip_takes", {})
    max_takes = int(spec.get("max_takes", 3))
    vocals = production.score().get("vocals_file")
    # A song switch leaves files on disk and flags the shot. Treat those keys
    # like an explicit retake so the new window can spend max_takes again.
    stale = tuple(key for key, clip in production.state["clips"].items() if obsolete_clip(clip))
    retake = tuple(dict.fromkeys((*retake, *stale)))
    pending = pending_windows(windows, production.state, retake)
    for shot in pending:
        tried.setdefault(shot["key"], _prior_takes(production.state, shot["key"]))
    budget = {shot["key"]: tried[shot["key"]] + max_takes for shot in pending}
    while pending:
        pending = _shoot_round(production, spec, pending, tried, budget, retake, vocals, pause)
    from services.production_subject_count import note_media
    note_media(production, spec, windows, "clip")
    from services.production_smoothness import note_outputs
    note_outputs(production, "clip")
