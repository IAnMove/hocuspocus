"""H3 clip jobs, take judging and the retake loop.

``Production.clip_job``, ``clips`` and ``judge_take`` delegate here. The loop
calls those methods, so a test that replaces ``production.clip_job`` or
``production.wait`` still owns the shoot. ``time.perf_counter``, ``time.sleep``,
``h3_frames_for`` and ``MAX_LOST_JOBS`` are read from ``music_production``.
"""
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


def submit_clip(production: Any, spec: dict, window: dict, seed: int, take: int = 0) -> str | None:
    """Retakes change strategy, not only the seed: even takes are driven by the full mix (best on the
    pilot, r 0.41 vs 0.16), odd takes by the isolated vocals for songs whose mix drowns the voice."""
    host = _host()
    frames = host.h3_frames_for(window["t1"] - window["t0"])
    vocals = production.score().get("vocals_file")
    source = vocals if take % 2 == 1 and vocals and window.get("sing") else production.state["song"]["file"]
    slice_name = f"{production.id}-slice-{window['key']}-{take}.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(window["t0"]), "-t", str(frames / 24), "-i", str(production.root / source),
                    "-ar", "48000", "-ac", "2", str(production.root / slice_name)], check=True)
    discard(production.state, slice_name)
    sing = " (S1) sings the lead vocal of the mapped driving audio, lips, jaw and breath in precise sync with every syllable." if window.get("sing") else ""
    prompt = (f"integrated_multimodal_description: [Shot 1] {(spec.get('style') or {}).get('video', '')} {window['action']}{sing}\n"
              "overall_soundscape: The mapped driving audio: the song.\nnon_diegetic_music: N/A")
    from services.production_resolution import clip_resolution
    params = {"prompt": prompt, "model_type": "minimax_h3_fused_turbo", "resolution": clip_resolution(spec), "seed": seed, "generation_mode": "video",
              "workspace": production.ws, "image_prompt_type": "S", "image_start": production.upload(production.state["frames"][window["key"]])[0],
              "video_length": frames, "sliding_window_size": frames, "num_inference_steps": 4, "guidance_scale": 1, "image_mode": 0,
              "input_video_strength": 1.0, "audio_prompt_type": "A", "audio_guide": production.upload(slice_name)[0]}
    # a resumed run must not collide with the journal entry of an earlier take
    reply = production.mcp("generate", {"request_id": f"{production.id}-{window['key']}-{seed}-{uuid.uuid4().hex[:8]}", "params": params})
    job = reply.get("job_id") or (reply.get("result") or {}).get("job_id")
    if not job:
        production.log(f"clip {window['key']} not admitted: {json.dumps(reply)[:140]}")
    return job


def shoot_clips(production: Any, spec: dict, windows: list[dict], retake: tuple[str, ...] = (), pause: float = 60) -> None:
    """Shoot missing clips (or retake keys). Flat lip-sync r, max_takes, or 4 recorded takes stop an automatic
    shoot; an explicit retake may pass the cap. The best r is kept. A fully failed round waits before the next."""
    host = _host()
    windows = production._unlocked(windows, retake)
    production.state.setdefault("clips", {})
    tried = production.state.setdefault("clip_takes", {})
    max_takes = int(spec.get("max_takes", 3))
    vocals = production.score().get("vocals_file")
    # A song switch leaves files on disk and flags the shot. Treat those keys
    # like an explicit retake so the new window can spend max_takes again.
    stale = tuple(key for key, clip in production.state["clips"].items() if obsolete_clip(clip))
    retake = tuple(dict.fromkeys((*retake, *stale)))
    pending = pending_windows(windows, production.state, retake)
    for window in pending:          # productions saved before clip_takes existed: count their logged takes
        tried.setdefault(window["key"], sum(1 for line in production.state.get("log") or [] if line.startswith(f"clip {window['key']} take ")))
    budget = {window["key"]: tried[window["key"]] + max_takes for window in pending}
    while pending:
        checkpoint(getattr(production, "_cancel", None))
        started = host.time.perf_counter()
        by_key = {window["key"]: window for window in pending}
        retry_keys: set[str] = set()
        landed: set[str] = set()
        lost = production.state.setdefault("clip_lost", {})

        def land(key: str, name: str | None) -> None:
            """Judge and record one clip as soon as it exists: a restart mid-round keeps the ones already shot."""
            if key in landed:
                return
            landed.add(key)
            if key in production.lost and lost.get(key, 0) < host.MAX_LOST_JOBS:
                lost[key] = lost.get(key, 0) + 1      # not a take: the job vanished, so shoot it again
                production.log(f"clip {key}: job lost (queue restarted), not counted as a take")
                retry_keys.add(key)
                return
            tried[key] += 1
            if another_take(production.judge_take(by_key[key], name, tried[key], vocals), tried[key], budget[key], key in retake):
                retry_keys.add(key)
            production.save()

        production.on_landed = land
        try:
            names = production.wait({window["key"]: production.clip_job(spec, window, 7000 + window["i"] * 10 + tried[window["key"]], tried[window["key"]]) for window in pending})
        finally:
            production.on_landed = None
        for window in pending:
            land(window["key"], names.get(window["key"]))         # a wait that reports only at the end (a stub) lands them here
        retry = [window for window in pending if window["key"] in retry_keys]
        note_seconds(production.state, pending, host.time.perf_counter() - started)
        production.save()
        if retry and not any(names.values()):
            sleep_until(getattr(production, "_cancel", None), pause, host.time.sleep)
        pending = retry
    from services.production_subject_count import note_media
    note_media(production, spec, windows, "clip")
    from services.production_smoothness import note_outputs
    note_outputs(production, "clip")


def judge_take(production: Any, window: dict, name: str | None, take: int, vocals: str | None) -> bool:
    """Record one take; True when the clip needs no more takes. Sung shots keep the best lip-sync r; other shots keep the best visual score."""
    key, failed, clips = window["key"], production.state.setdefault("clip_failures", {}), production.state.setdefault("clips", {})
    if not name:
        failed[key] = production.failures.get(key, "no output")
        production.log(f"clip {key} take {take}: failed ({failed[key]})")
        return False
    failed.pop(key, None)
    from services.production_clip_qa import clip_qa
    qa = clip_qa(str(production.root / name), bool(window.get("sing")), str(production.root / vocals) if vocals else None, window["t0"], window["t1"])
    drive = "vocals" if (take - 1) % 2 == 1 and window.get("sing") else "mix"
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
