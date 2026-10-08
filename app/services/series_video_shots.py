"""Generate a Series shot's video take from its script (``kind: "video"`` plus ``video``).

The clip used to be made outside and imported with ``series.asset.import``. A shot that
names ``video`` is generated here, before the native render, and attached the way that
import attaches a take: through ``attach_series_import``, not through the MCP tool.
Sound stays with ``series_take_sound`` at the cut. ``keepAudio`` false drops the model's
own track (``layout2d.clipAudio: "drop"``).

``plan`` and ``preview`` reviews do not spend a generation until that shot's plan is
approved. ``episode.videoBudget.maxShots`` is a warning on ``from_script`` and a cap
here. After each take the start frame and the take are compared (color histogram, edge
density, dHash). Crossing ``STYLE_DRIFT_THRESHOLD`` records ``style_drift`` and does
not fail the shot.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from typing import Any, Callable
from urllib.parse import quote, urlencode

from PIL import Image

from services.pose_facing import pose_asset, workspace_path
from services.series_review import episode_mode, shot_entry

# H3 publishes 24 fps and lengths 124, then +17, through 345 (minimax_h3_handler).
FRAME_RATE = 24
FRAMES_MIN = 124
FRAMES_STEP = 17
FRAMES_MAX = 345
DEFAULT_FRAMES = FRAMES_MIN
DEFAULT_MODEL = "minimax_h3"
# The model's own 480p 16:9 preset. 1080p H3 is a separate, experimental tier.
DEFAULT_RESOLUTION = "864x480"
# An unchanged plate scores 0. A flat plate recolored to the opposite hue scores about 0.67.
STYLE_DRIFT_THRESHOLD = 0.45
_TERMINAL = frozenset({"completed", "failed", "cancelled", "discarded", "error"})
_PROMPT_LIMIT = 8000


class VideoShotError(RuntimeError):
    """One scripted video shot could not be prepared or generated."""


def parse_budget(value: Any) -> dict[str, int] | None:
    """``{"maxShots": n}`` or None when the script names no budget."""
    if value is None:
        return None
    count = value.get("maxShots") if isinstance(value, dict) else None
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("videoBudget.maxShots must be a whole number")
    return {"maxShots": count}


def video_shot_count(script: dict[str, Any]) -> int:
    shots = script.get("shots") if isinstance(script.get("shots"), list) else []
    return sum(1 for shot in shots if isinstance(shot, dict) and shot.get("kind") == "video" and isinstance(shot.get("video"), dict))


def budget_warning(script: dict[str, Any], budget: dict[str, int] | None) -> dict[str, Any] | None:
    """The script asks for more video shots than its budget. It does not block."""
    if not budget:
        return None
    count = video_shot_count(script)
    if count <= budget["maxShots"]:
        return None
    return {"code": "video_budget", "maxShots": budget["maxShots"], "shots": count}


def normalize_video(raw: Any) -> dict[str, Any]:
    """The stored ``video`` object. Raises ``ValueError`` on a bad shape."""
    if not isinstance(raw, dict):
        raise ValueError("video must be an object")
    prompt = raw.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("video.prompt is required")
    start = raw.get("start", "plan")
    if not _start_shape(start):
        raise ValueError("video.start must be plan, an asset, or pose:<character>/<pose>")
    end = raw.get("end", None)
    if end is not None and end != "same" and not _source_shape(end):
        raise ValueError("video.end must be same, an asset, or null")
    frames = _frames(raw.get("frames", DEFAULT_FRAMES))
    model = raw.get("model", DEFAULT_MODEL)
    if model != DEFAULT_MODEL:
        raise ValueError("video.model must be minimax_h3")
    takes = raw.get("maxTakes", 2)
    if takes not in (1, 2, 3):
        raise ValueError("video.maxTakes must be 1, 2 or 3")
    keep = raw.get("keepAudio", False)
    if not isinstance(keep, bool):
        raise ValueError("video.keepAudio must be true or false")
    return {"prompt": prompt.strip()[:_PROMPT_LIMIT], "start": start, "end": end, "frames": frames,
            "model": model, "maxTakes": takes, "keepAudio": keep}


def reference_problems(shot: dict[str, Any], checker: Any, where: str) -> None:
    """The start and end frames name a pose, a workspace file or an image asset of the series."""
    if shot.get("kind") != "video" or not isinstance(shot.get("video"), dict):
        return
    try:
        request = normalize_video(shot["video"])
    except ValueError as error:
        checker.problems.append(f"{where}: {error}")
        return
    _known_frame(request["start"], checker, where, "start")
    if request["end"] not in (None, "same"):
        _known_frame(request["end"], checker, where, "end")
    if _duration_too_long(shot, request["frames"]):
        checker.problems.append(f"{where}: video.frames is shorter than duration")


def needs_video_step(episode: dict[str, Any]) -> bool:
    return any(isinstance(shot, dict) and isinstance(shot.get("video"), dict) for shot in episode.get("shots") or [])


def style_distance(left: Image.Image, right: Image.Image) -> float:
    """How far two frames have drifted: the larger of the color-histogram gap and the mean of that gap, the edge-density gap and dHash."""
    histogram = _histogram_distance(left, right)
    edges = abs(_edge_density(left) - _edge_density(right))
    hashed = _dhash_distance(left, right)
    return round(max(histogram, (histogram + edges + hashed) / 3), 4)


def produce_videos(job: dict[str, Any], step: dict[str, Any], deps: Any, *, cancelled: Callable[[], bool]) -> bool:
    """Generate the episode's scripted video shots. True when the job is now waiting on a plan."""
    series, episode = _episode_of(deps, job)
    allowed, overflow = _cap(episode, _scripted(episode))
    warnings = [_overflow_warning(episode, _scripted(episode))] if overflow else []
    waiting: list[dict[str, str]] = []
    done = set(step.get("doneShots") or [])
    for shot in allowed:
        if _already_made(series, shot, done):
            done.add(shot.get("id"))
            continue
        if _plan_blocks(episode, shot):
            waiting.append({"shotId": shot.get("id"), "reason": "plan"})
            continue
        _spend_one(job, step, deps, series, episode, shot, done, warnings, cancelled)
    step["warnings"] = warnings
    step["doneShots"] = sorted(item for item in done if item)
    if waiting:
        return _hold_for_plan(job, step, waiting)
    return False


def _episode_of(deps: Any, job: dict[str, Any]) -> tuple[dict, dict]:
    library = deps.read_library(job["workspace"])
    series = (library.get("seriesById") or {}).get(job["seriesId"]) or {}
    episode = (series.get("episodesById") or {}).get(job["episodeId"]) or {}
    return series, episode


def _scripted(episode: dict[str, Any]) -> list[dict[str, Any]]:
    return [shot for shot in episode.get("shots") or [] if isinstance(shot, dict) and isinstance(shot.get("video"), dict)]


def _already_made(series: dict[str, Any], shot: dict[str, Any], done: set) -> bool:
    return shot.get("id") in done or _take_matches(series, shot)


def _spend_one(job: dict, step: dict, deps: Any, series: dict, episode: dict, shot: dict, done: set,
               warnings: list, cancelled: Callable[[], bool]) -> None:
    if cancelled():
        raise VideoShotError("cancelled")
    made = _generate(job, shot, series, deps, cancelled)
    _remember(deps, job, shot, made, episode_mode(episode) != "preview")
    _note_drift(warnings, shot, made)
    done.add(shot.get("id"))
    step["doneShots"] = sorted(done)


def _note_drift(warnings: list, shot: dict[str, Any], made: dict[str, Any]) -> None:
    distance = made.get("distance")
    if distance is None or distance <= STYLE_DRIFT_THRESHOLD:
        return
    warnings.append({"code": "style_drift", "shotId": shot.get("id"), "distance": distance, "take": made["number"]})


def _hold_for_plan(job: dict[str, Any], step: dict[str, Any], waiting: list[dict[str, str]]) -> bool:
    step["status"] = "queued"
    job.update(status="waiting", waiting=waiting, finishedAt=time.time(),
               message=f"Waiting for the review: {len(waiting)} plans to approve before spending video")
    return True


def import_generated_take(series: dict[str, Any], workspace: str, root: str, shot_id: str, source_path: str,
                          metadata: dict[str, Any], *, approve: bool) -> str:
    """Copy ``source_path`` into the series assets and attach it as the shot's take. No MCP call."""
    from services.series_library import approve_shot_render_attempt
    from services.series_production import attach_series_import

    asset_id = f"asset_{uuid.uuid4().hex[:12]}"
    extension = os.path.splitext(source_path)[1].lower()[:12] or ".mp4"
    relative = f"assets/{series['id']}/{asset_id}{extension}"
    destination = os.path.join(root, *relative.split("/"))
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copy2(source_path, destination)
    asset = {"id": asset_id, "workspaceId": workspace, "kind": "video", "uri": relative, "ownerType": "shot",
             "ownerId": shot_id, "isDerivedThumbnail": False,
             "metadata": {"name": os.path.basename(source_path)[:300], "referenceRole": "reference", **metadata}}
    attach_series_import(series, asset, as_take=True, source_path=destination)
    attempt_id = str(asset["ownerId"])
    if approve:
        found = _shot_index(series, shot_id)
        if found is not None:
            episode, index, shot = found
            episode["shots"][index] = approve_shot_render_attempt(shot, attempt_id, "server")
    return attempt_id


# Shape ---------------------------------------------------------------------------------------------

def _frames(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("video.frames must be an H3 length (124, then +17 up to 345)")
    if value < FRAMES_MIN or value > FRAMES_MAX or (value - FRAMES_MIN) % FRAMES_STEP:
        raise ValueError("video.frames must be an H3 length (124, then +17 up to 345)")
    return value


def _start_shape(value: Any) -> bool:
    if value == "plan":
        return True
    if isinstance(value, str) and value.startswith("pose:") and "/" in value[5:]:
        return True
    return _source_shape(value)


def _source_shape(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 400 and "\n" not in value and ".." not in value


def _duration_too_long(shot: dict[str, Any], frames: int) -> bool:
    if shot.get("lines"):
        return False
    duration = shot.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return False
    return float(duration) > frames / FRAME_RATE + 0.05


def _known_frame(value: str, checker: Any, where: str, label: str) -> None:
    if value == "plan":
        return
    if value.startswith("pose:"):
        character, _, pose = value[5:].partition("/")
        checker.character(character, pose or "base", where)
        return
    if value in checker.files:
        return
    asset = (checker.series.get("assets") or {}).get(value)
    if isinstance(asset, dict) and asset.get("kind") in ("image", "video"):
        return
    checker.problems.append(f"{where}: video.{label} {value} is not a workspace file or an image asset")


def _plan_blocks(episode: dict[str, Any], shot: dict[str, Any]) -> bool:
    if episode_mode(episode) == "direct":
        return False
    return shot_entry(episode, str(shot.get("id")))["plan"] != "approved"


def _cap(episode: dict[str, Any], shots: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    budget = episode.get("videoBudget") if isinstance(episode.get("videoBudget"), dict) else {}
    limit = budget.get("maxShots")
    if isinstance(limit, bool) or not isinstance(limit, int):
        return shots, []
    return shots[:limit], shots[limit:]


def _overflow_warning(episode: dict[str, Any], shots: list[dict[str, Any]]) -> dict[str, Any]:
    limit = (episode.get("videoBudget") or {}).get("maxShots")
    return {"code": "video_budget", "maxShots": limit, "shots": len(shots)}


def _request_digest(request: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(request, sort_keys=True).encode()).hexdigest()[:16]


def _take_matches(series: dict[str, Any], shot: dict[str, Any]) -> bool:
    digest = _request_digest(shot["video"])
    assets = series.get("assets") or {}
    for attempt in reversed(shot.get("attempts") or []):
        if attempt.get("status") != "completed":
            continue
        for asset_id in attempt.get("outputAssetIds") or []:
            if ((assets.get(asset_id) or {}).get("metadata") or {}).get("videoRequest") == digest:
                return True
    return False


# One shot ------------------------------------------------------------------------------------------

def _generate(job: dict[str, Any], shot: dict[str, Any], series: dict[str, Any], deps: Any, cancelled: Callable[[], bool]) -> dict[str, Any]:
    request = shot["video"]
    start_path, start_ref = _start_frame(job, shot, series, deps)
    end_ref = start_ref if request.get("end") == "same" else _end_reference(job, request.get("end"), series, deps)
    best: dict[str, Any] | None = None
    for number in range(1, int(request["maxTakes"]) + 1):
        if cancelled():
            raise VideoShotError("cancelled")
        intent = f"series-{job['episodeId']}-{shot['id']}-video-{number}"[:160]
        params = {"prompt": request["prompt"], "model_type": request["model"], "resolution": DEFAULT_RESOLUTION,
                  "video_length": request["frames"], "image_start": start_ref}
        if end_ref:
            params["image_end"] = end_ref
        submitted = _call(deps, "generation.video", 3, {"workspace": job["workspace"], "params": params}, intent=intent)
        finished = _wait(deps, _job_id(submitted), cancelled)
        take_path = _output_file(finished, deps, job["workspace"])
        distance = _compare(start_path, take_path)
        if best is None or _closer(distance, best.get("distance")):
            best = {"distance": distance, "file": take_path, "intent": intent, "number": number, "request": request}
        if distance is not None and distance <= STYLE_DRIFT_THRESHOLD:
            break
    if best is None:
        raise VideoShotError(f"{shot.get('id')}: no take")
    return best


def _closer(distance: float | None, best: float | None) -> bool:
    if distance is None:
        return False
    return best is None or distance < best


def _remember(deps: Any, job: dict[str, Any], shot: dict[str, Any], made: dict[str, Any], approve: bool) -> None:
    metadata = {"productionMethod": "imported_video", "automaticDraft": True, "videoRequest": _request_digest(shot["video"]),
                "intentId": made["intent"], **({} if made.get("distance") is None else {"styleDistance": made["distance"]})}
    if not approve:
        metadata["reviewStage"] = "preview"
    if getattr(deps, "import_take", None):
        deps.import_take({"workspace": job["workspace"], "seriesId": job["seriesId"], "episodeId": job["episodeId"],
                          "shotId": shot["id"], "file": made["file"], "metadata": metadata, "approve": approve})
        return
    _persist(deps, job, shot["id"], made["file"], metadata, approve)


def _persist(deps: Any, job: dict[str, Any], shot_id: str, source: str, metadata: dict[str, Any], approve: bool) -> None:
    workspace = job["workspace"]
    if _locked_write(workspace, lambda library: _mutate(library, job, workspace, shot_id, source, metadata, approve, deps)):
        return
    library = json.loads(json.dumps(deps.read_library(workspace)))
    _mutate(library, job, workspace, shot_id, source, metadata, approve, deps)
    _save(deps, workspace, library)


def _mutate(library: dict, job: dict, workspace: str, shot_id: str, source: str, metadata: dict, approve: bool, deps: Any) -> None:
    series = (library.get("seriesById") or {}).get(job["seriesId"])
    if not isinstance(series, dict):
        raise VideoShotError("Series episode not found")
    import_generated_take(series, workspace, deps.workspace_dir(workspace), shot_id, source, metadata, approve=approve)


def _locked_write(workspace: str, mutate: Callable[[dict], None]) -> bool:
    from routers import series_library as routes
    lock, read, write, resolve = (getattr(routes, "_library_lock", None), getattr(routes, "_read_library", None),
                                  getattr(routes, "_write_library", None), getattr(routes, "_resolve_workspace", None))
    if lock is None or read is None or write is None or resolve is None:
        return False
    with lock:
        resolved = resolve(workspace)
        library = read(resolved)
        mutate(library)
        write(resolved, library)
    return True


def _save(deps: Any, workspace: str, library: dict) -> None:
    if getattr(deps, "write_library", None):
        deps.write_library(workspace, library)
        return
    from services.series_library import write_series_library
    write_series_library(deps.workspace_dir(workspace), library, workspace)


def _shot_index(series: dict[str, Any], shot_id: str) -> tuple[dict, int, dict] | None:
    for episode in (series.get("episodesById") or {}).values():
        if not isinstance(episode, dict):
            continue
        for index, shot in enumerate(episode.get("shots") or []):
            if isinstance(shot, dict) and shot.get("id") == shot_id:
                return episode, index, shot
    return None


# Tools ---------------------------------------------------------------------------------------------

def _call(deps: Any, tool: str, version: int, data: dict[str, Any], *, intent: str | None = None) -> dict[str, Any]:
    """The tool reply. ``generation.video`` matches ``game_tools``: the handler adds ``operation``."""
    envelope: dict[str, Any] = {"version": version, "input": data}
    if intent:
        envelope["intent_id"] = intent
    reply = deps.call(tool, envelope)
    if not isinstance(reply, dict) or reply.get("_is_error"):
        error = (reply or {}).get("error") if isinstance(reply, dict) else None
        message = error.get("message") if isinstance(error, dict) else reply
        raise VideoShotError(f"{tool}: {message}"[:500])
    result = reply.get("result")
    return result if isinstance(result, dict) else reply


def _job_id(payload: dict[str, Any]) -> str:
    for key in ("job_id", "jobId"):
        if payload.get(key):
            return str(payload[key])
    job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
    found = job.get("jobId") or job.get("job_id")
    if found:
        return str(found)
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    if task.get("job_id"):
        return str(task["job_id"])
    raise VideoShotError("generation.video returned no job")


def _wait(deps: Any, job_id: str, cancelled: Callable[[], bool]) -> dict[str, Any]:
    while True:
        if cancelled():
            raise VideoShotError("cancelled")
        payload = _call(deps, "jobs.wait", 1, {"job_id": job_id, "timeout_s": 30})
        status = str(payload.get("status") or "")
        if status in _TERMINAL:
            if status != "completed":
                raise VideoShotError(payload.get("error") or payload.get("message") or status)
            return payload
        if not payload.get("timed_out"):
            deps.sleep(deps.poll_seconds)


def _output_file(payload: dict[str, Any], deps: Any, workspace: str) -> str:
    files = [str(item) for item in (payload.get("output_files") or []) if item]
    name = files[0] if files else payload.get("file") or payload.get("filename")
    if not name:
        raise VideoShotError("generation.video returned no file")
    return _locate(deps, workspace, str(name))


def _locate(deps: Any, workspace: str, name: str) -> str:
    if os.path.isabs(name):
        return name
    return os.path.join(deps.workspace_dir(workspace), name.lstrip("/"))


# Start frame ---------------------------------------------------------------------------------------

def _start_frame(job: dict[str, Any], shot: dict[str, Any], series: dict[str, Any], deps: Any) -> tuple[str, str]:
    request = shot["video"]
    if request["start"] == "plan":
        return _compose_plan(job, shot, series, deps)
    return _named_frame(job, request["start"], series, deps)


def _end_reference(job: dict[str, Any], end: str | None, series: dict[str, Any], deps: Any) -> str | None:
    if not end:
        return None
    _path, reference = _named_frame(job, end, series, deps)
    return reference


def _named_frame(job: dict[str, Any], name: str, series: dict[str, Any], deps: Any) -> tuple[str, str]:
    root = deps.workspace_dir(job["workspace"])
    if name.startswith("pose:"):
        character, _, pose = name[5:].partition("/")
        relative = _pose_file(series, _kits(deps, job["workspace"]), root, character, pose)
        if not relative:
            raise VideoShotError(f"pose {name} has no image")
        return os.path.join(root, relative), _file_reference(job["workspace"], relative)
    asset = (series.get("assets") or {}).get(name)
    if isinstance(asset, dict) and asset.get("uri"):
        relative = str(asset["uri"])
        return os.path.join(root, relative), name if _asset_id(name) else _file_reference(job["workspace"], relative)
    return os.path.join(root, name), _file_reference(job["workspace"], name)


def _compose_plan(job: dict[str, Any], shot: dict[str, Any], series: dict[str, Any], deps: Any) -> tuple[str, str]:
    root = deps.workspace_dir(job["workspace"])
    layers = _plan_layers(shot, series, _kits(deps, job["workspace"]), root)
    if not layers:
        layers = [{"file": _flat_plate(root, f"{shot['id']}-plate.png"), "x": 50, "y": 50}]
    intent = f"series-{job['episodeId']}-{shot['id']}-start"[:160]
    plate = {"workspace": job["workspace"], "size": [864, 480], "background": "#c4b49a", "layers": layers,
             "output_name": f"{shot['id']}-video-start"}
    base = _location_file(series, shot)
    if base:
        plate["base"] = base
    composed = _call(deps, "media.compose", 1, plate, intent=intent)
    name = str(composed.get("file") or "")
    if not name:
        raise VideoShotError("media.compose returned no file")
    path = _locate(deps, job["workspace"], name)
    relative = name if not os.path.isabs(name) else os.path.relpath(name, root)
    return path, _file_reference(job["workspace"], relative)


def _plan_layers(shot: dict[str, Any], series: dict[str, Any], kits: dict[str, Any], root: str) -> list[dict[str, Any]]:
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    layers = []
    for entry in layout.get("cast") or []:
        if not isinstance(entry, dict):
            continue
        relative = _pose_file(series, kits, root, str(entry.get("characterId") or ""), str(entry.get("poseId") or "base"))
        if relative:
            layers.append({"file": relative, "x": entry.get("x", 50), "y": 72, "scale": 0.62, "anchor": "bottom"})
    return layers[:16]


def _pose_file(series: dict[str, Any], kits: dict[str, Any], root: str, character_id: str, pose_id: str) -> str | None:
    character = next((item for item in series.get("characters") or [] if item.get("id") == character_id), None)
    kit_id = (((character or {}).get("voiceProfile") or {}).get("characterKitRef") or {}).get("id")
    asset = pose_asset((kits or {}).get(kit_id), pose_id)
    if not isinstance(asset, dict):
        return None
    path = workspace_path(asset.get("source"), root)
    if path:
        return os.path.relpath(path, os.path.realpath(root))
    for key in ("file", "source"):
        name = asset.get(key)
        if isinstance(name, str) and name and not name.startswith("/"):
            return name
    return None


def _location_file(series: dict[str, Any], shot: dict[str, Any]) -> str | None:
    location = next((item for item in series.get("locations") or [] if item.get("id") == shot.get("locationId")), None)
    plate = ((location or {}).get("layout2d") or {}).get("plateAssetId") if isinstance((location or {}).get("layout2d"), dict) else None
    asset = (series.get("assets") or {}).get(plate) if isinstance(plate, str) else None
    uri = (asset or {}).get("uri") if isinstance(asset, dict) else None
    return str(uri) if isinstance(uri, str) and uri else None


def _flat_plate(root: str, name: str) -> str:
    folder = os.path.join(root, "series-video")
    os.makedirs(folder, exist_ok=True)
    relative = f"series-video/{name}"
    Image.new("RGB", (864, 480), (196, 180, 154)).save(os.path.join(root, "series-video", name))
    return relative


def _kits(deps: Any, workspace: str) -> dict[str, Any]:
    if getattr(deps, "read_kits", None):
        return deps.read_kits(workspace) or {}
    from services.character_kit_library import read_character_kit_library
    return read_character_kit_library(deps.workspace_dir(workspace)).get("kits") or {}


def _file_reference(workspace: str, relative: str) -> str:
    rel = str(relative).replace("\\", "/").lstrip("/")
    return f"/api/v1/file/{quote(rel)}?{urlencode({'workspace': workspace})}"


def _asset_id(value: str) -> bool:
    return value.startswith("asset_") and " " not in value


def _compare(start_path: str, take_path: str) -> float | None:
    try:
        left, right = _open_frame(start_path), _open_frame(take_path)
    except OSError:
        return None
    if left is None or right is None:
        return None
    return style_distance(left, right)


def _open_frame(path: str) -> Image.Image | None:
    if not path or not os.path.isfile(path):
        return None
    if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        with Image.open(path) as image:
            return image.convert("RGB")
    return _video_frame(path)


def _video_frame(path: str) -> Image.Image | None:
    import subprocess
    import tempfile
    folder = tempfile.mkdtemp(prefix="video-shot-")
    target = os.path.join(folder, "frame.png")
    try:
        subprocess.run(["ffmpeg", "-y", "-i", path, "-frames:v", "1", target], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if not os.path.isfile(target):
            return None
        with Image.open(target) as image:
            return image.convert("RGB")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


# Picture distance ----------------------------------------------------------------------------------

def _histogram_distance(left: Image.Image, right: Image.Image) -> float:
    first, second = _histogram(left), _histogram(right)
    total = sum(first) or 1
    return sum(abs(a - b) for a, b in zip(first, second)) / (2 * total)


def _histogram(image: Image.Image) -> list[int]:
    small = image.convert("RGB").resize((64, 64))
    bins = [0] * 24
    for red, green, blue in small.getdata():
        bins[red // 32] += 1
        bins[8 + green // 32] += 1
        bins[16 + blue // 32] += 1
    return bins


def _edge_density(image: Image.Image) -> float:
    gray = image.convert("L").resize((64, 64))
    pixels = gray.load()
    total = 0
    count = 0
    for y in range(63):
        for x in range(63):
            here = pixels[x, y]
            total += abs(here - pixels[x + 1, y]) + abs(here - pixels[x, y + 1])
            count += 2
    return (total / count) / 255 if count else 0.0


def _dhash_distance(left: Image.Image, right: Image.Image) -> float:
    return (_dhash(left) ^ _dhash(right)).bit_count() / 64


def _dhash(image: Image.Image) -> int:
    gray = list(image.convert("L").resize((9, 8)).getdata())
    bits = 0
    for y in range(8):
        row = gray[y * 9:(y + 1) * 9]
        for x in range(8):
            bits = (bits << 1) | (1 if row[x] > row[x + 1] else 0)
    return bits
