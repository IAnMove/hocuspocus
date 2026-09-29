"""Compile native Video 3D shots and export them through recoverable MCP.

The runner consumes their MP4s as clips. An export failure stops production;
it never substitutes a still or an H3 take for a 3D shot.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from services.production_scene_retry import receipt_action, _artifact_name

ROOT = Path(__file__).resolve().parents[2]
EXPORT = "scenes.world3d.export"
RECEIPT = "scenes.world3d.export.receipt"
CONFIG_KEYS = {"template", "document", "subject", "slots", "clip", "motion", "position", "scale", "rotationY", "grounded",
               "camera", "atmos", "environment", "light", "dressing", "pixelWorld", "width", "height", "fps"}


def validate_scene3d_shot(shot):
    config = shot.get("scene3d")
    if not isinstance(config, dict) or set(config) - CONFIG_KEYS:
        raise ValueError("scene3d needs a native template or document and supported overrides")
    if ("template" in config) == ("document" in config):
        raise ValueError("scene3d needs exactly one of template or document")
    if "template" in config and (not isinstance(config["template"], str) or not config["template"].strip()):
        raise ValueError("scene3d.template must be a native template id")
    if "document" in config and not isinstance(config["document"], dict):
        raise ValueError("scene3d.document must be an object")
    if "template" in config and not (config.get("subject") or config.get("slots")):
        raise ValueError("A template shot needs a subject GLB or explicit slots")
    if shot.get("sing"):
        raise ValueError("scene3d does not promise H3 lip-sync; use rigid object motion or authored GLB clips")


def compile_document(shot, duration):
    validate_scene3d_shot(shot)
    node = shutil.which("node")
    loader = ROOT / "ui/node_modules/tsx/dist/loader.mjs"
    if not node or not loader.is_file():
        raise ValueError("Native Video 3D template compilation requires the app's installed UI dependencies")
    result = subprocess.run(
        [node, "--import", str(loader), str(ROOT / "ui/scripts/production-scene3d.mjs")],
        input=json.dumps({"scene3d": shot["scene3d"], "duration": duration}),
        capture_output=True, text=True, cwd=ROOT / "ui", timeout=30, check=False,
    )
    if result.returncode:
        raise ValueError(f"scene3d {shot['key']}: native document compilation failed: {result.stderr[-500:]}")
    document = json.loads(result.stdout)
    if not isinstance(document, dict) or "slots" not in document:
        raise ValueError("Native compiler did not return a Video 3D document")
    return document


def _export(production, key, document, fingerprint, *, sleep):
    exports = production.state.setdefault("world3d_exports", {})
    record = exports.get(key) or {}
    # Keep an admitted export across a restart; changed documents use a new intent.
    if record.get("fingerprint") != fingerprint:
        record = {"fingerprint": fingerprint, "attempt": 0}
        exports[key] = record
    while record.get("attempt", 0) < 2 or record.get("intent"):
        if not record.get("intent"):
            attempt = record.get("attempt", 0) + 1
            identity = hashlib.sha256(key.encode()).hexdigest()[:16]
            intent = f"{production.id[:60]}-3d-{identity}-{fingerprint}-{attempt}"
            record.update(attempt=attempt, intent=intent, admitted=False)
            production.save()  # Retry an uncertain admission with this exact intent.
        if not record.get("admitted"):
            production.mcp(EXPORT, {"version": 1, "intent_id": record["intent"],
                                   "input": {"workspace": production.ws, "document": document}})
            record["admitted"] = True
            production.save()
        reply = production.mcp(RECEIPT, {"version": 1, "input": {"workspace": production.ws, "intent_id": record["intent"]}})
        action = receipt_action(reply)
        if action == "ready":
            name = _artifact_name(reply)
            record["file"] = name
            production.save()
            return name
        if action == "retry":
            record.pop("intent", None)
            production.save()
            continue
        sleep(4)
    raise ValueError(f"scene3d_export_failed: {key}")


def export_scene3d_clips(production, spec, windows, retake=(), *, compiler=compile_document, sleep=time.sleep):
    # Same cut/fill rules as scenes(); import here to keep the planning module acyclic.
    from services.music_production import segments

    clips = production.state.setdefault("clips", {})
    segs = segments(windows, production.score(), lambda key: key in clips, spec.get("fill") or [])
    for shot, start, end in segs:
        if shot["kind"] != "scene3d":
            continue
        key, duration = shot["key"], round(end - start, 3)
        revisions = production.state.setdefault("scene3d_revisions", {})
        if key in retake:
            revisions[key] = revisions.get(key, 0) + 1
            clips.pop(key, None)
            production.state.setdefault("world3d_exports", {}).pop(key, None)
        source = json.dumps({"config": shot["scene3d"], "duration": duration, "revision": revisions.get(key, 0)}, sort_keys=True)
        fingerprint = hashlib.sha256(source.encode()).hexdigest()[:16]
        if clips.get(key, {}).get("fingerprint") == fingerprint and (production.root / clips[key]["file"]).is_file():
            continue
        document = compiler(shot, duration)
        started = time.perf_counter()
        name = _export(production, key, document, fingerprint, sleep=sleep)
        if not name or not (production.root / name).is_file():
            raise ValueError(f"scene3d_export_failed: {key}: published clip is missing")
        clips[key] = {"file": name, "url": f"/api/v1/file/{name}?workspace={production.ws}",
                      "qa": {"verdict": "ok", "method": "native-world3d"}, "fingerprint": fingerprint,
                      "world3d_document": document}
        production.state.setdefault("clip_seconds", {})[key] = round(time.perf_counter() - started, 3)
        production.state.setdefault("clip_takes", {})[key] = int(production.state.get("clip_takes", {}).get(key, 0)) + 1
        production.log(f"scene3d {key}: native World3D clip ready")
        production.save()
