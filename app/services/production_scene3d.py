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
from urllib.parse import quote, unquote, urlparse, parse_qs

from services.production_scene_retry import receipt_action, _artifact_name
from services.world3d_look import check_document_look

ROOT = Path(__file__).resolve().parents[2]
EXPORT = "scenes.world3d.export"
RECEIPT = "scenes.world3d.export.receipt"
CONFIG_KEYS = {"template", "document", "subject", "slots", "clip", "motion", "position", "scale", "rotationY", "grounded",
               "camera", "atmos", "environment", "light", "dressing", "pixelWorld", "renderLook", "toon", "rhythm", "width", "height",
               "fps", "playbackSpeed", "cast", "background", "floor"}
CAST_FIELDS = {"source", "clip", "clips", "motion", "position", "scale", "rotationY", "grounded", "rhythm", "appearance", "add"}
SURFACES = ("cutout", "environment", "wall", "floor")
FLOOR_STYLES = ("backdrop", "none", "tiles", "mirror", "road")
BACKGROUND_FIELDS = {"source", "surface", "houses", "ground", "layout"}
MODEL_HEIGHT = 1.7      # the scene scales a model to this height times its scale


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
    _check_looks(config)
    _check_cast(config.get("cast"))
    _check_background(config)
    if "template" in config and not (config.get("subject") or config.get("slots") or config.get("cast")):
        raise ValueError("A template shot needs a subject GLB, a cast or explicit slots")
    if shot.get("sing"):
        raise ValueError("scene3d does not promise H3 lip-sync; use rigid object motion or authored GLB clips")


def _check_looks(config):
    """renderLook and toon, as overrides or inside a full document."""
    for looks in (config, config.get("document") or {}):
        try:
            check_document_look(looks)
        except ValueError as error:
            raise ValueError(f"scene3d: {error}") from error


def _source(value):
    return isinstance(value, str) and 0 < len(value) <= 2000


def _check_cast(cast):
    """cast maps a template role (subject_1, subject_2, background...) or an object id to a model or picture."""
    if cast is None:
        return
    if not isinstance(cast, dict) or not 0 < len(cast) <= 8:
        raise ValueError("scene3d.cast maps 1-8 template roles or object ids to a GLB or picture")
    for key, value in cast.items():
        entry = value if isinstance(value, dict) else {"source": value}
        if not (isinstance(key, str) and 0 < len(key) <= 64) or set(entry) - CAST_FIELDS or not _source(entry.get("source")):
            raise ValueError(f"scene3d.cast.{key}: give a source (GLB or picture URL, workspace file or stills name) "
                             f"and only {', '.join(sorted(CAST_FIELDS - {'source'}))}")


def _check_background(config):
    if "background" in config:
        entry = config["background"] if isinstance(config["background"], dict) else {"source": config["background"]}
        if set(entry) - BACKGROUND_FIELDS or not _source(entry.get("source")) or entry.get("surface", "cutout") not in SURFACES:
            raise ValueError("scene3d.background is a picture (URL, workspace file, stills name or set) or "
                             "{source, surface: cutout|environment|wall|floor}")
        if "houses" in entry or "ground" in entry:
            _check_diorama(entry)
        if entry.get("layout", "plaza") not in ("plaza", "open"):
            raise ValueError("scene3d.background.layout is plaza or open")
    if config.get("floor", "backdrop") not in FLOOR_STYLES:
        raise ValueError(f"scene3d.floor must be one of {', '.join(FLOOR_STYLES)}")


def _measure(value, low, high):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


def _check_diorama(entry):
    """A diorama set spelled out: the sky picture as source, house GLBs with their size in metres, a ground slab GLB."""
    houses, ground = entry.get("houses"), entry.get("ground")
    if not isinstance(houses, list) or not 0 < len(houses) <= 16 or not all(
            isinstance(house, dict) and set(house) == {"source", "width", "height"} and _source(house["source"])
            and _measure(house["width"], 0.5, 60) and _measure(house["height"], 0.5, 60) for house in houses):
        raise ValueError("scene3d.background.houses lists 1-16 {source, width, height} house models (metres)")
    if ground is not None and not (isinstance(ground, dict) and set(ground) == {"source", "height", "size"}
                                   and _source(ground["source"]) and _measure(ground["height"], 0.01, 5)
                                   and _measure(ground["size"], 4, 1000)):
        raise ValueError("scene3d.background.ground is {source, height, size}: a ground slab model and its size in metres")


def _rig_labels():
    from services.rig_service import ANIMATIONS
    return {item["id"]: item["label"] for item in ANIMATIONS}


def _clip_key(name):
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def resolve_media(config, *, stills, root, workspace, models=None, sets=None):
    """The shot's scene3d with every named picture or model as a URL, and clips named by name as {index, name}.

    A name is a production model (``spec.models``) or set (``spec.sets``), a stills entry, else a file in the
    workspace. URLs pass unchanged, so a spec that already gives URLs resolves to itself (and keeps its fingerprint).
    """
    from services.series_shot3d import glb_clip_names

    def url(value):
        if value.startswith(("/api/", "http://", "https://")):
            return value
        if (models or {}).get(value, {}).get("file"):
            return f"/api/v1/file/{quote(models[value]['file'])}?workspace={quote(workspace)}"
        if (sets or {}).get(value, {}).get("url"):
            return sets[value]["url"]
        if value in (stills or {}):
            return stills[value]
        path = (Path(root) / value).resolve()
        if path.is_relative_to(Path(root).resolve()) and path.is_file():
            return f"/api/v1/file/{quote(value)}?workspace={quote(workspace)}"
        raise ValueError(f"scene3d: {value!r} is not a URL, a model, a stills name or a file in the workspace")

    def clip(source, value, key):
        if not isinstance(value, str):
            return value
        address = urlparse(source)
        name = unquote(address.path.removeprefix("/api/v1/file/"))
        names = []
        if address.path.startswith("/api/v1/file/") and parse_qs(address.query).get("workspace") == [workspace]:
            names = glb_clip_names(Path(root) / name)
        # The rig asks for dance_bounce and bakes "Dance Bounce", or for wobble and bakes its label "Wobble Dance":
        # the rig id, its label or the baked name all name the clip.
        wanted = {_clip_key(value), _clip_key(_rig_labels().get(value, value))}
        found = [index for index, name in enumerate(names) if _clip_key(name) in wanted]
        if not found:
            raise ValueError(f"scene3d.cast.{key}: no clip {value!r} in its model (clips: {', '.join(names) or 'none'})")
        return {"index": found[0], "name": names[found[0]]}

    resolved = json.loads(json.dumps(config))
    if _source(resolved.get("subject")):
        resolved["subject"] = url(resolved["subject"])
    if "background" in resolved:
        entry = resolved["background"] if isinstance(resolved["background"], dict) else {"source": resolved["background"]}
        resolved["background"] = _diorama(entry, (sets or {}).get(entry["source"])) or {**entry, "source": url(entry["source"])}
    for key, value in (resolved.get("cast") or {}).items():
        entry = value if isinstance(value, dict) else {"source": value}
        height = (models or {}).get(entry["source"], {}).get("height")
        source = url(entry["source"])
        entry = {**entry, "source": source}
        # A model made at its real height ("the moto is 1.1 m") keeps it; every model is otherwise 1.7 m tall.
        if height and "scale" not in entry:
            entry["scale"] = round(height / MODEL_HEIGHT, 4)
        if "clip" in entry:
            entry["clip"] = clip(source, entry["clip"], key)
        if isinstance(entry.get("clips"), list):
            entry["clips"] = [{**cue, "clip": clip(source, cue.get("clip"), key)} if isinstance(cue, dict) else cue
                              for cue in entry["clips"]]
        resolved["cast"][key] = entry
    return resolved


def _diorama(entry, made):
    """A diorama set named as the background: its sky becomes the source, its houses and ground come along."""
    if not (made or {}).get("houses"):
        return None
    pieces = {"source": made["sky"], "houses": made["houses"], **({"ground": made["ground"]} if made.get("ground") else {})}
    return {**pieces, **{key: value for key, value in entry.items() if key in ("layout",)}}


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
    elif not record.get("intent") and record.get("attempt", 0) >= 2:
        # Two failures stop this run. A later production.run resume has no video, so
        # review is unreliable and will not pass retake; start a new attempt cycle
        # whose intent ids cannot recover the previous failed receipts.
        record.update(attempt=0, cycle=record.get("cycle", 0) + 1, admitted=False)
        exports[key] = record
    while record.get("attempt", 0) < 2 or record.get("intent"):
        if not record.get("intent"):
            attempt = record.get("attempt", 0) + 1
            identity = hashlib.sha256(key.encode()).hexdigest()[:16]
            intent = f"{production.id[:60]}-3d-{identity}-{fingerprint}-{record.get('cycle', 0)}-{attempt}"
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
    from services.music_production import ProductionError, segments
    from services.production_shot_review import is_locked

    clips = production.state.setdefault("clips", {})
    segs = segments(windows, production.score(), lambda key: key in clips, spec.get("fill") or [])
    for shot, start, end in segs:
        if shot["kind"] != "scene3d":
            continue
        key, duration = shot["key"], round(end - start, 3)
        if is_locked(production, key):
            if key in retake:
                raise ProductionError("shot_locked", "locked: " + key)
            # Stay on the cut. Skip only when a clip file already exists;
            # a lock before the first export (or after a failed one) must
            # still produce that file or scenes() raises and the run fails.
            if (clips.get(key) or {}).get("file"):
                continue
        revisions = production.state.setdefault("scene3d_revisions", {})
        if key in retake:
            revisions[key] = revisions.get(key, 0) + 1
            # The revision bump already busts the fingerprint. Keep the last good
            # clip until this export lands; a failed retake must not drop it.
            production.state.setdefault("world3d_exports", {}).pop(key, None)
        shot = {**shot, "scene3d": resolve_media(shot["scene3d"], stills=spec.get("stills"), root=production.root,
                                                 workspace=production.ws, models=production.state.get("models"),
                                                 sets=production.state.get("sets"))}
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
