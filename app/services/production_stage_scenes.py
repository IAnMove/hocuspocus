"""Scene documents, package, montage and the CPU animatic.

``segments``, ``scene_fingerprint``, ``contact_sheet_filter``, ``failure_reason``
and ``note_held`` stay on ``music_production`` and are read at call time.
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from services.production_control import sleep_until
from services.production_package import (
    attach_origins, clip_replacements, contrast_warnings, doc_digest, durable_document, lyric_for, manifest_rows, write_manifest,
)
from services.production_scene_retry import apply_scene_export_failure, finish_scene_exports, skip_montage
from services.video2d_edit import MAX_OPERATIONS


def _host():
    import services.music_production as host
    return host


def edit_document(production: Any, doc: dict, ops: list[dict]) -> dict:
    # scenes.video2d.edit admits 32 ops; a long still with timed lyrics exceeds that in one shot.
    host = _host()
    for index in range(0, len(ops), MAX_OPERATIONS):
        chunk = ops[index:index + MAX_OPERATIONS]
        reply = production.mcp("scenes.video2d.edit", {"version": 1, "input": {"document": doc, "operations": chunk, "full": True}})
        if "result" not in reply:
            raise host.ProductionError("scene_edit_failed", json.dumps(reply)[:300])
        doc = reply["result"]["document"]
    return doc


def scene_layer_ops(production: Any, shot: dict, start: float, end: float, dur: float, score: dict, clips: dict, style: dict, stills: dict) -> list[dict]:
    host = _host()
    ops: list[dict] = []
    clip = clips.get(shot["key"]) or (clips.get(shot.get("clip")) if shot["kind"] == "clip" else None)
    if shot["kind"] == "scene3d" and not clip:
        raise host.ProductionError("scene3d_export_failed", f"scene3d clip missing: {shot['key']}")
    if clip:
        host.note_held(production.state, shot["key"], False)
        ops.append({"op": "add_layer", "id": "bg", "source": clip["url"], "type": "video", "preset": shot.get("camera", "camera-locked")})
        skip = round(max(0.0, start - shot.get("t0", start)) + ((clip.get("qa") or {}).get("suggested_sync_s") or 0), 3) if shot["kind"] == "h3" else 0
        # the animation duration is also the video span (sceneTimeline.getSceneLayerTiming): a camera preset's
        # shorter duration would freeze the clip mid-scene, so it always covers the scene (+ the skipped head)
        anim: dict[str, Any] = {"end": {"x": 50, "y": 50, "scale": 1.0, "rotation": 0},
                                "duration": round(dur + skip, 3)}
        if skip > 0:
            anim["trimStart"] = skip
        ops.append({"op": "update_layer", "id": "bg", "patch": {"fill": True, "animation": anim}})
    elif shot["kind"] == "screen":
        desktop = {"theme": style.get("theme") or "tokyo-night", "layout": "triple", "apps": "mixed", "focus": "0", "workspace": "1",
                   "switch": "none", **{k: str(v) for k, v in (shot.get("desktop") or {}).items()}}
        ops.append({"op": "add_title", "id": "desk", "template": "desktop", "fields": desktop, "start": 0, "duration": dur})
    else:
        zoom = shot.get("zoom") or [1.0, 1.1]
        source = stills.get(shot.get("still"), shot.get("still"))
        if not source and shot["kind"] == "h3" and shot["key"] in production.state.get("frames", {}):
            source = production.upload(production.state["frames"][shot["key"]])[1]      # clip failed: hold its start frame
            host.note_held(production.state, shot["key"])
        ops += [{"op": "add_layer", "id": "bg", "source": source, "type": "image", "preset": shot.get("camera", "camera-push-in")},
                {"op": "update_layer", "id": "bg", "patch": {"fill": True, "focus": shot.get("focus", {"x": 50, "y": 50}), "animation": {
                    "start": {"x": 50, "y": 50, "scale": zoom[0], "rotation": 0}, "end": {"x": 50, "y": 50, "scale": zoom[1], "rotation": 0}}}}]
    title_ops, used = production._title_ops(shot, dur, style)
    ops.extend(title_ops)
    ops.extend(production._lyric_ops(shot, start, end, dur, score, style, used))
    ops.extend(production._footer_ops(dur, style))
    if style.get("finish"):
        ops.append({"op": "set_finish", **style["finish"]})
    return ops


def export_scenes(production: Any, spec: dict, windows: list[dict]) -> None:
    host = _host()
    score = production.score()
    from services.production_preview import ensure_caption_contrast
    ensure_caption_contrast(production, spec, windows, score)
    clips = production.state.get("clips", {})
    segs = host.segments(windows, score, lambda key: key in clips, spec.get("fill") or [])
    production.state["segments"] = [[shot["key"], start, end] for shot, start, end in segs]
    done = production.state.setdefault("scenes", {})
    style, stills = spec.get("style") or {}, spec.get("stills") or {}
    docs: dict[str, dict] = {}
    from services.production_shot_review import is_locked
    for shot, start, end in segs:
        # Stay on the cut. Do not re-export or refresh the fingerprint.
        if is_locked(production, shot["key"]):
            continue
        dur = round(end - start, 3)
        used = (clips.get(shot["key"]) or (clips.get(shot.get("clip")) if shot["kind"] == "clip" else None) or {}).get("file")
        prior = done.get(shot["key"], {})
        fingerprint = host.scene_fingerprint(shot, style, stills, score, start, end)
        if (prior.get("dur") == dur and prior.get("file") and prior.get("clip") == used
                and prior.get("fingerprint") == fingerprint):
            continue
        doc = production.scene_document(shot, start, end, score, clips, style, stills)
        docs[shot["key"]] = doc
        reply = production.mcp("scenes.video2d.export", {"version": 1, "intent_id": f"{production.id}-scene-{shot['key']}-{int(host.time.time())}",
                                               "input": {"workspace": production.ws, "document": doc}})
        done[shot["key"]] = {"intent": (reply.get("receipt") or {}).get("commandId"), "dur": dur, "clip": used,
                              "fingerprint": fingerprint, "file": None}
        production.save()
    failed = finish_scene_exports(
        production.mcp, production.ws, production.id, done, docs,
        lambda seconds: sleep_until(getattr(production, "_cancel", None), seconds, host.time.sleep), production.save, production.log)
    apply_scene_export_failure(production.state, failed)
    production.log(f"scenes: {sum(1 for item in done.values() if item.get('file'))}/{len(segs)}")
    from services.production_smoothness import note_outputs
    note_outputs(production, "scene")


def scene_document(production: Any, shot: dict, start: float, end: float, score: dict, clips: dict, style: dict, stills: dict) -> dict:
    from services.production_shot_edit import render_shot
    shot, style = render_shot(shot, style)
    dur = round(end - start, 3)
    doc = {"version": 1, "name": shot["key"], "width": 1920, "height": 1080, "fps": 24, "duration": dur, "layers": [], "texts": []}
    return production.edit(doc, production.scene_ops(shot, start, end, dur, score, clips, style, stills))


def package_shots(production: Any, spec: dict, windows: list[dict]) -> None:
    """Save what a person needs to retouch the video shot by shot: a durable scene document per shot and a manifest
    (see production_package). Never fails the run: the video is already made."""
    host = _host()
    score, clips = production.score(), production.state.get("clips", {})
    segs = host.segments(windows, score, lambda key: key in clips, spec.get("fill") or [])
    style, stills = spec.get("style") or {}, spec.get("stills") or {}
    swap, saved = clip_replacements(clips, production.ws), production.state.setdefault("scene_docs", {})
    for shot, start, end in segs:
        key = shot["key"]
        try:
            doc = durable_document(production.scene_document(shot, start, end, score, clips, style, stills), swap)
            digest = doc_digest(doc)
            if (saved.get(key) or {}).get("digest") == digest:
                continue
            result = production.mcp("scenes.document.save", {"version": 1, "intent_id": f"{production.id}-doc-{key}-{digest}",
                                                       "input": {"workspace": production.ws, "name": f"{production.id}-{key}", "document": doc}})
            name = (result.get("result") or {}).get("name")
            if not name:
                raise host.ProductionError("scene_doc_failed", json.dumps(result)[:160])
            note = " · ".join(part for part in (shot.get("action"), f"seed {shot['seed']}" if shot.get("seed") is not None else "") if part)
            saved[key] = {"scene": name, "digest": digest, "lyric": lyric_for(score.get("lines") or [], start, end), "note": note,
                          "warnings": contrast_warnings(production.mcp, doc)}
        except Exception as error:      # one shot's document must not stop the others
            production.log(f"package {key}: {type(error).__name__}: {error}"[:200])
    manifest = write_manifest(production.root, production.id, spec.get("title", production.id), manifest_rows(production.state, spec, segs, score, saved),
                              production.state.get("montage_file"))
    production.state["package"] = {"manifest": manifest, "scene_docs": len(saved),
                             "warnings": sum(len(item.get("warnings") or []) for item in saved.values())}
    production.log(f"package: {len(saved)} scene documents, manifest {manifest}")


def finish_package(production: Any, previous: str | None, previous_error: object, package_error: str | None) -> None:
    """Restore the finished status. A leftover final is not success, and this must never look running:
    auto-resume would start a full GPU production.run."""
    if package_error:
        production.state["error"] = package_error
        production.state["status"] = previous if previous in ("completed", "failed") else "failed"
    elif previous == "failed":
        production.state["status"] = "failed"
        production.state["error"] = previous_error
    elif production.state.get("final"):
        production.state.update(status="completed", error=None)
    else:
        production.state["status"] = "failed"
        if previous_error:
            production.state["error"] = previous_error
    production.state["finished"] = _host().time.time()
    production.save()


def repackage(production: Any, spec: dict) -> None:
    """Package a production that is already finished (no GPU, no export): scene documents, manifest and the
    montage clips' origins. This is how an older production becomes editable."""
    host = _host()
    previous, previous_error = production.state.get("status"), production.state.get("error")
    try:
        windows = host.shot_windows(spec, production.score())
        production.package(spec, windows)
        file = production.state.get("montage_file")
        if file:
            current = (production.mcp("montages.get", {"version": 1, "input": {"workspace": production.ws, "file": file}}).get("result") or {})
            montage = current.get("montage") or current
            if attach_origins(montage, production.state.get("scene_docs") or {}, production.id) and montage.get("clips"):
                revision = current.get("revision") or montage.get("revision")
                saved = production.mcp("montages.save", {"version": 1, "intent_id": f"{production.id}-origins-{int(host.time.time())}",
                                                   "input": {"workspace": production.ws, "montage": montage, "file": file, "expected_revision": revision}})
                if "result" not in saved:
                    raise host.ProductionError("montage_failed", json.dumps(saved)[:200])
    except Exception as error:
        production._finish_package(previous, previous_error, f"{type(error).__name__}: {error}"[:300])
        return
    production._finish_package(previous, previous_error, None)


def build_montage(production: Any, spec: dict) -> None:
    host = _host()
    if skip_montage(production.state):
        return
    score, scenes = production.score(), production.state["scenes"]
    clips = [{"id": key, "name": key, "source": f"/api/v1/file/{scenes[key]['file']}?workspace={production.ws}", "trimStart": 0, "trimEnd": scenes[key]["dur"],
              "muted": True, "fit": "fill", "transition": "none"} for key, _, _ in production.state["segments"] if scenes.get(key, {}).get("file")]
    from services.production_trailer_audio import attach as attach_trailer_audio
    montage = {"version": 1, "name": spec["title"], "width": 1920, "height": 1080, "fps": 24, "clips": clips, "audioCues": [], "overlays": [],
               "soundtrack": {"source": f"/api/v1/file/{production.state['song']['file']}?workspace={production.ws}", "trimStart": 0, "trimEnd": score["duration"], "volume": 1.0, "loop": False}}
    attach_origins(montage, production.state.get("scene_docs") or {}, production.id)
    montage = attach_trailer_audio(production, spec, montage)
    body: dict[str, Any] = {"workspace": production.ws, "montage": montage}
    if production.state.get("montage_file"):
        current = (production.mcp("montages.get", {"version": 1, "input": {"workspace": production.ws, "file": production.state["montage_file"]}}).get("result") or {})
        revision = current.get("revision") or (current.get("montage") or {}).get("revision")
        if revision:
            body.update(file=production.state["montage_file"], expected_revision=revision)
    saved = production.mcp("montages.save", {"version": 1, "intent_id": f"{production.id}-montage-{int(host.time.time())}", "input": body})
    if "result" not in saved:
        raise host.ProductionError("montage_failed", json.dumps(saved)[:300])
    production.state["montage_file"] = saved["result"]["file"]
    job = production.mcp("montages.export", {"version": 1, "intent_id": f"{production.id}-export-{int(host.time.time())}",
                                       "input": {"workspace": production.ws, "file": production.state["montage_file"]}})["result"]["job"]
    while True:
        status = production.mcp("montages.export.status", {"version": 1, "input": {"workspace": production.ws, "job_id": job["job_id"]}})
        status = (status.get("result") or status).get("job", status)
        # montages.export queues a Video Editor job. cancelled is terminal there
        # (user cancel or resource scheduler); polling only completed/failed hangs.
        if status.get("status") in ("completed", "failed", "cancelled", "discarded", "error"):
            break
        sleep_until(getattr(production, "_cancel", None), 4, host.time.sleep)
    # start_export pre-fills filename when the job is created. A failed
    # render still carries that planned name; only a completed export is a video.
    if not isinstance(status, dict) or status.get("status") != "completed" or not status.get("filename"):
        raise host.ProductionError("montage_failed", host.failure_reason(status) if isinstance(status, dict) else "export job lost")
    production.state["final"] = status["filename"]
    if production.state["final"]:
        sheet = f"{production.id}-contact.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(production.root / production.state["final"]), "-vf", host.contact_sheet_filter(score["duration"]),
                        "-frames:v", "1", str(production.root / sheet)])
        production.state["contact_sheet"] = sheet
    from services.production_smoothness import note_outputs
    note_outputs(production, "final")
    production.log(f"montage: {status.get('status')}")


def build_animatic(production: Any, spec: dict, windows: list[dict]) -> None:
    """CPU preview from the start frames. A new export is stored apart from ``final``."""
    from services.production_preview import (
        animatic_report, claim_animatic_video, completed_cut_final,
        restore_cut_artifacts, snapshot_cut_artifacts,
    )
    previous = completed_cut_final(production.state)
    kept = snapshot_cut_artifacts(production.root, production.state)
    production.state["animatic_warnings"] = animatic_report(spec, windows, production.score(), production.state)
    production.state["caption_gate"] = "warn"
    try:
        production.scenes(spec, windows)
        production.montage(spec)
    finally:
        production.state.pop("caption_gate", None)
        restore_cut_artifacts(production.root, production.state, kept)
        claim_animatic_video(production.state, previous if isinstance(previous, str) else None)
