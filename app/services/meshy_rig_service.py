"""Meshy cloud rigging and animation: the ``meshy`` engine of ``/api/v1/rig``.

A rig job here is a thread that talks to the Meshy API and polls it, not a CPU or GPU lane job.
It lives in ``rig_service``'s own job registry on purpose, so status, cancel, busy-workspace
checks and the Activity panel treat it like every other rig job.

Flow: the workspace GLB goes to ``/v1/rigging`` as a data URI (5 credits; the walking and running
clips are free with it). With ``animations`` (library entries by action id or key) a second task,
``/v1/animations``, adds one clip per action (3 credits each) and its GLB is the published asset.
Everything is downloaded at once, because Meshy deletes API outputs after 3 days, and written as
normal workspace files with a manifest that records ``provider: meshy`` and the task ids.

If the animation task fails after the rig succeeded, the paid rigged GLB is still published and
the job carries a ``warnings`` entry. Cancelling publishes nothing.
"""
from __future__ import annotations

import base64
import dataclasses
import json
import os
import re
import shutil
import struct
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import execution_mode, meshy_http as http, resource_scheduler
from .asset_manifest import publish_generation_sidecar_best_effort
from .generation_output_name import canonical_file_url
from .meshy_http import MeshyError
from .procedural_3d.glb_inspector import GlbInspectorLimits, inspect_glb_bytes

RIGGING = f"{http.API_ROOT}/v1/rigging"
ANIMATIONS = f"{http.API_ROOT}/v1/animations"
LIBRARY = f"{ANIMATIONS}/library"
MAX_MODEL_BYTES = 100 * 1024 * 1024
MAX_ACTIONS = 10
DEFAULT_HEIGHT_METERS = 1.7
LIBRARY_TTL_SECONDS = 600
LIBRARY_PAGE = 100
LIBRARY_MAX_PAGE = 500
CATEGORIES = ("WalkAndRun", "BodyMovements", "DailyActions", "Fighting", "Dancing")
RIG_CREDITS, ACTION_CREDITS = 5, 3
KEY_MESSAGE = "Configure the Meshy API key in Settings → Services first"
POSE_MESSAGE = (
    "not_humanoid: Meshy could not find a humanoid pose in this model. Rig a textured, upright humanoid "
    "that faces +Z; when you generate it with Meshy, set meshy.pose_mode to a-pose or t-pose."
)
INSPECT_LIMITS = dataclasses.replace(GlbInspectorLimits(), max_file_bytes=256 * 1024 * 1024)
_PACKED = {"KHR_draco_mesh_compression": "draco", "EXT_meshopt_compression": "meshopt"}
_BASIC_CLIPS = (("walking", "walking_glb_url"), ("running", "running_glb_url"))

_library_lock = threading.Lock()
_library: dict[str, Any] = {"at": 0.0, "items": None}


def _rigs():
    from . import rig_service
    return rig_service


def api_key() -> str:
    """The user's own Meshy key: the full server's settings, or the core server's when WanGP is not bound."""
    try:
        from services.generation import RuntimeConfig
        return str(RuntimeConfig.services().get("meshy_api_key") or "").strip()
    except Exception:
        pass
    try:
        from services import core_workspace
        return str(core_workspace.services_raw().get("meshy_api_key") or "").strip()
    except Exception:
        return ""


def engine_entry() -> dict[str, Any]:
    """The ``meshy`` row of ``/api/v1/rig/capabilities``."""
    ready = bool(api_key())
    return {
        "id": "meshy",
        "label": "Meshy (cloud)",
        "description": (
            "Meshy's cloud rigging for a textured humanoid GLB that faces +Z (up to 100 MB): a rigged GLB plus free walking "
            "and running clips, and optionally clips from Meshy's animation library. Uses your own Meshy credits."
        ),
        "installed": ready,
        "install_hint": None if ready else "Add your Meshy API key in Settings → Services.",
        "remote": True,
        "max_animations": MAX_ACTIONS,
        "cost_credits": {"rig": RIG_CREDITS, "per_library_animation": ACTION_CREDITS, "walking_and_running": 0},
    }


# -- request -----------------------------------------------------------------------------------------------------

def parse_request(body: dict[str, Any]) -> dict[str, Any]:
    """``height_meters`` and the library entries (action ids or keys) of an engine ``meshy`` request."""
    height = body.get("height_meters", DEFAULT_HEIGHT_METERS)
    if isinstance(height, bool) or not isinstance(height, (int, float)) or not 0 < height <= 100:
        raise ValueError("height_meters must be a number of meters above 0 and up to 100")
    raw = body.get("animations")
    if raw is None:
        raw = []
    if not isinstance(raw, list) or any(isinstance(item, bool) or not isinstance(item, (str, int)) for item in raw):
        raise ValueError("animations must be a list of Meshy library action ids or keys")
    entries = list(dict.fromkeys(str(item).strip() for item in raw))
    if "" in entries:
        raise ValueError("animations cannot hold an empty entry")
    if len(entries) > MAX_ACTIONS:
        raise ValueError(f"Meshy adds at most {MAX_ACTIONS} animations per request")
    return {"height_meters": float(height), "animations": entries}


def start_job(
    *, body: dict[str, Any], source_path: str, output_dir: str, workspace: str = "default",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register a Meshy rig job and start its thread. Bad input and a missing key fail here, before any call."""
    execution_mode.validate_remote_provider(workspace, "meshy")
    if not api_key():
        raise ValueError(KEY_MESSAGE)
    options = parse_request(body)
    rigs = _rigs()
    job_id = uuid.uuid4().hex
    task_id = rigs._canonical_task_id(job_id)
    now = time.time()
    job = {
        "job_id": job_id, "task_id": task_id, "root_task_id": task_id,
        "status": "queued", "progress": 0.0, "phase": "queued", "message": "Queued Meshy rig job",
        "error": None, "filename": None, "url": None,
        "engine": "meshy", "workspace": str(workspace or "default"), "rig_profile": "humanoid",
        # Activity shows a cloud task, not the local rig CPU lane the other engines wait on.
        "provider": "meshy", "resource_lane": resource_scheduler.remote_lane("meshy").key,
        "source_file": os.path.basename(source_path), "created_at": now, "updated_at": now,
        "request": {"source": os.path.abspath(source_path), "output_dir": os.path.abspath(output_dir), **options},
    }
    if provenance:
        job["provenance"] = dict(provenance)
    with rigs._lock:
        rigs._prune_finished_jobs_locked()
        rigs._jobs[job_id] = job
        initial = rigs._public_job(dict(job))
    threading.Thread(target=run, args=(job_id,), daemon=True, name=f"meshy-rig-{job_id[:8]}").start()
    return initial


# -- source GLB --------------------------------------------------------------------------------------------------

def _invalid(message: str, reason: str) -> MeshyError:
    return MeshyError(f"invalid_input: {message}", 400, code="invalid_input", reason=reason)


def glb_problem(data: bytes) -> tuple[str, str] | None:
    """``(message, reason)`` when ``data`` is not a GLB Meshy can read, else None."""
    if len(data) < 20 or data[:4] != b"glTF":
        return "The file is not a binary glTF (.glb).", "not_glb"
    length, kind = struct.unpack("<II", data[12:20])
    if kind != 0x4E4F534A or 20 + length > len(data):
        return "The GLB is damaged: its JSON chunk is missing or cut short.", "not_glb"
    try:
        document = json.loads(data[20:20 + length])
    except ValueError:
        return "The GLB is damaged: its JSON chunk cannot be read.", "not_glb"
    used = set(document.get("extensionsUsed") or []) | set(document.get("extensionsRequired") or [])
    for extension, reason in _PACKED.items():
        if extension in used:
            return f"The GLB uses {reason} compression, which Meshy cannot read. Export it uncompressed.", reason
    return None


def read_source(path: Path) -> bytes:
    size = path.stat().st_size
    if size > MAX_MODEL_BYTES:
        raise _invalid(f"The GLB is {size // 1_000_000} MB and Meshy accepts at most {MAX_MODEL_BYTES // 1024 // 1024} MB. "
                       "Reduce its textures or polygons and try again.", "too_large")
    data = path.read_bytes()
    problem = glb_problem(data)
    if problem:
        raise _invalid(*problem)
    return data


# -- animation library -------------------------------------------------------------------------------------------

def _normalize_entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("action_id"), int):
        return None
    return {
        "action_id": raw["action_id"], "name": str(raw.get("name") or ""), "key": str(raw.get("key") or ""),
        "category": str(raw.get("category") or ""), "sub_category": str(raw.get("sub_category") or ""),
        "preview_url": str(raw.get("preview_url") or ""),
    }


def library_items(key: str, cancelled: Callable[[], bool] | None = None) -> tuple[list[dict[str, Any]], bool]:
    """The whole library (free to read) and whether it came from the ten-minute cache."""
    with _library_lock:
        cached = _library["items"]
        if cached is not None and time.time() - _library["at"] < LIBRARY_TTL_SECONDS:
            return cached, True
    payload = http.call("get", LIBRARY, key, cancelled=cancelled, fallback="Meshy animation library request failed", retry_reads=True)
    rows = payload if isinstance(payload, list) else (payload.get("result") or payload.get("animations") or [])
    items = [entry for entry in map(_normalize_entry, rows) if entry]
    with _library_lock:
        _library.update(at=time.time(), items=items)
    return items, False


def _page_argument(name: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be a whole number from {low} to {high}")
    return value


def animation_library(
    *, search: str = "", category: str = "", sub_category: str = "", limit: int = LIBRARY_PAGE, offset: int = 0,
) -> dict[str, Any]:
    """Meshy's animation library filtered by name/key text, category and sub-category. Costs nothing."""
    key = api_key()
    if not key:
        raise ValueError(KEY_MESSAGE)
    if category and category not in CATEGORIES:
        raise ValueError(f"category must be one of: {', '.join(CATEGORIES)}")
    limit = _page_argument("limit", limit, 1, LIBRARY_MAX_PAGE)
    offset = _page_argument("offset", offset, 0, 1_000_000)
    items, cached = library_items(key)
    needle = str(search or "").strip().lower()
    chosen = [
        item for item in items
        if (not needle or needle in item["name"].lower() or needle in item["key"].lower())
        and (not category or item["category"] == category)
        and (not sub_category or item["sub_category"] == sub_category)
    ]
    return {
        "provider": "meshy", "total": len(chosen), "offset": offset, "count": len(chosen[offset:offset + limit]),
        "animations": chosen[offset:offset + limit],
        "categories": list(CATEGORIES), "sub_categories": sorted({item["sub_category"] for item in chosen if item["sub_category"]}),
        "cached": cached,
        "note": f"Reading the library is free; each animation added to a rig costs {ACTION_CREDITS} credits. "
                "Pass action_id or key values in model3d.rig animations (engine meshy), up to 10.",
    }


def resolve_actions(key: str, entries: list[str], cancelled: Callable[[], bool] | None = None) -> list[dict[str, Any]]:
    """Library entries for ``entries`` (action ids or keys), in order. Unknown ones fail before anything is paid."""
    items, _cached = library_items(key, cancelled)
    by_id = {item["action_id"]: item for item in items}
    by_key = {item["key"].lower(): item for item in items}
    found: dict[int, dict[str, Any]] = {}
    unknown = []
    for entry in entries:
        item = by_id.get(int(entry)) if entry.isdigit() else by_key.get(entry.lower())
        if item is None:
            unknown.append(entry)
        else:
            found.setdefault(item["action_id"], item)
    if unknown:
        raise _invalid(f"Unknown Meshy animation(s): {', '.join(unknown)}. Look them up with model3d.meshy.animations.", "unknown_animation")
    return list(found.values())


# -- the job -----------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class _Rigged:
    task_id: str
    files: dict[str, bytes]
    facts: dict[str, int]


@dataclasses.dataclass
class _Animated:
    task_id: str
    glb: bytes
    facts: dict[str, int]


def _update(job_id: str, **fields: Any) -> bool:
    return _rigs()._update_job(job_id, **fields)


def _stage(job_id: str, phase: str, message: str, low: float, high: float) -> Callable[[float], None]:
    """Announce a phase and return the callback that maps Meshy's 0-100 progress into [low, high]."""
    _update(job_id, phase=phase, message=message, progress=low)
    return lambda percent: _update(job_id, progress=round(low + (high - low) * percent / 100.0, 3))


def _rig_error(error: MeshyError) -> MeshyError:
    """A pose Meshy cannot read is the same refusal the humanoid engine gives: ``not_humanoid``."""
    pose = error.status_code == 422 or (error.reason == "failed" and "pose" in str(error).lower())
    if pose:
        return MeshyError(POSE_MESSAGE, 422, code="not_humanoid", reason="meshy_pose_estimation_failed")
    return error


def _extra_clip(url: str, role: str, warnings: list[str]) -> bytes | None:
    try:
        return http.download(url)
    except MeshyError as error:
        warnings.append(f"meshy_{role}_clip_unavailable: {error}")
        return None


def _rig(key: str, model: bytes, height: float, job_id: str, cancelled, warnings: list[str], low: float, high: float) -> _Rigged:
    progress = _stage(job_id, "rigging", "Meshy is rigging the model", low, high)
    data_uri = "data:application/octet-stream;base64," + base64.b64encode(model).decode("ascii")
    try:
        created = http.call("post", RIGGING, key, body={"model_url": data_uri, "height_meters": height},
                            timeout=(15, 300), cancelled=cancelled, fallback="Meshy rigging failed")
        task_id = http.task_id(created)
        task = http.poll_task(f"{RIGGING}/{task_id}", key, cancelled=cancelled, on_progress=progress, timeout_s=10 * 60)
    except MeshyError as error:
        raise _rig_error(error) from error
    result = task.get("result") or {}
    glb_url = str(result.get("rigged_character_glb_url") or "").strip()
    if not glb_url:
        raise MeshyError("Meshy returned no rigged GLB")
    files = {"rigged": http.download(glb_url)}
    basic = result.get("basic_animations") or {}
    for role, field in _BASIC_CLIPS:
        if basic.get(field) and not cancelled():
            extra = _extra_clip(str(basic[field]), role, warnings)
            if extra:
                files[role] = extra
    return _Rigged(task_id, files, http.task_facts(task))


def _animate(key: str, rig_task: str, actions: list[dict[str, Any]], job_id: str, cancelled, low: float, high: float) -> _Animated:
    progress = _stage(job_id, "animating", f"Meshy is adding {len(actions)} animation(s)", low, high)
    body = {"rig_task_id": rig_task, "action_ids": [action["action_id"] for action in actions]}
    created = http.call("post", ANIMATIONS, key, body=body, cancelled=cancelled, fallback="Meshy animation failed")
    task_id = http.task_id(created)
    task = http.poll_task(f"{ANIMATIONS}/{task_id}", key, cancelled=cancelled, on_progress=progress, timeout_s=10 * 60)
    url = str((task.get("result") or {}).get("animation_glb_url") or "").strip()
    if not url:
        raise MeshyError("Meshy returned no animated GLB")
    return _Animated(task_id, http.download(url), http.task_facts(task))


def _loop_unknown(clip: Any) -> dict[str, Any]:
    # Meshy does not say whether a clip loops, so ``loop`` stays null instead of a guess.
    return {"index": clip.index, "name": clip.name, "duration": clip.duration_seconds, "loop": None}


def _inspect(name: str, data: bytes, actions: list[dict[str, Any]] | None, warnings: list[str]) -> dict[str, Any]:
    """Clip list and joint count of one downloaded GLB. Clip order follows ``action_ids`` for the animated file."""
    report = inspect_glb_bytes(data, limits=INSPECT_LIMITS)
    if report.status != "valid":
        warnings.append(f"glb_not_inspectable: {name} ({', '.join(issue.code for issue in report.issues) or report.status})")
    clips = [_loop_unknown(clip) for clip in report.animations]
    if actions and len(actions) == len(clips):
        for clip, action in zip(clips, actions):
            clip.update(action_id=action["action_id"], key=action["key"], library_name=action["name"])
    return {"clips": clips, "joint_count": max((skin.joint_count for skin in report.skins), default=0)}


def _write_all(folder: Path, files: dict[str, bytes]) -> None:
    """Write every file or none: each goes to a ``.part`` name first and is renamed only when all are on disk."""
    folder.mkdir(parents=True, exist_ok=True)
    parts: list[tuple[Path, Path]] = []
    try:
        for name, data in files.items():
            final = folder / name
            part = final.with_name(final.name + ".part")
            part.write_bytes(data)
            parts.append((part, final))
        for part, final in parts:
            os.replace(part, final)
    except BaseException:
        for part, final in parts:
            for leftover in (part, final):
                leftover.unlink(missing_ok=True)
        raise


def _meshy_block(job_id: str, request: dict[str, Any], rig: _Rigged, animated: _Animated | None, actions: list[dict[str, Any]]) -> dict[str, Any]:
    block: dict[str, Any] = {"rig_task_id": rig.task_id, "height_meters": request["height_meters"]}
    if animated:
        block["animation_task_id"] = animated.task_id
        block["actions"] = [{"action_id": a["action_id"], "key": a["key"], "name": a["name"]} for a in actions]
    block.update(http.combine_facts(rig.facts, animated.facts if animated else {}))
    return block


def _role_block(role: str, meshy: dict[str, Any]) -> dict[str, Any]:
    """The main file's manifest holds every task and the credits; a free walking/running clip names the rig it came with."""
    if role == "main":
        return meshy
    return {key: meshy[key] for key in ("rig_task_id", "height_meters", "expires_at") if key in meshy}


def _publish_sidecar(path: Path, job: dict[str, Any], source: Path, role: str, meshy: dict[str, Any], names: list[str], requested: list[str]) -> None:
    rigs = _rigs()
    job_id = job["job_id"]
    params = {
        "model_type": "rig-meshy", "provider": "meshy", "rigged": True, "rig_engine": "meshy", "rig_profile": "humanoid",
        "source_file": source.name, "animations": requested, "role": role,
        "prompt": f"Rigged from {source.name}", "meshy": meshy, "main_file": names[0],
        "siblings": [name for name in names if name != path.name],
    }
    publish_generation_sidecar_best_effort(
        path,
        {"generation_mode": "model3d", "mode": "model3d", "job_id": job_id, **rigs._command_id(job),
         "task_id": rigs._canonical_task_id(job_id), "root_task_id": rigs._canonical_task_id(job_id),
         "created_at": time.time(), "params": params},
        output_folder=rigs._physical_output_folder(job.get("workspace")), **rigs._sidecar_origin(job),
    )


def _publish(
    job_id: str, request: dict[str, Any], rig: _Rigged, animated: _Animated | None, actions: list[dict[str, Any]],
    warnings: list[str], cancelled: Callable[[], bool],
) -> dict[str, Any]:
    rigs = _rigs()
    source = Path(request["source"])
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", source.stem)[:48]
    stem = f"{time.strftime('%Y-%m-%d-%Hh%Mm%Ss')}_rigged_{safe}_{job_id[:8]}"
    main = f"{stem}.glb"
    files = {main: animated.glb if animated else rig.files["rigged"]}
    roles = {main: "main"}
    for role, _field in _BASIC_CLIPS:
        if rig.files.get(role):
            files[f"{stem}-{role}.glb"], roles[f"{stem}-{role}.glb"] = rig.files[role], role
    inspected = {name: _inspect(name, data, actions if animated and name == main else None, warnings) for name, data in files.items()}
    if cancelled():
        raise http.cancelled_error()
    folder = Path(request["output_dir"])
    _write_all(folder, files)
    meshy = _meshy_block(job_id, request, rig, animated, actions)
    with rigs._lock:
        job = dict(rigs._jobs.get(job_id) or {}, job_id=job_id)
    requested = [action["key"] for action in actions]
    for name, role in roles.items():
        _publish_sidecar(folder / name, job, source, role, _role_block(role, meshy), list(files), requested)
    preview = source.with_suffix(".preview.png")
    if preview.is_file():
        try:
            shutil.copyfile(preview, (folder / main).with_suffix(".preview.png"))
        except OSError:
            pass
    return {
        "filename": main, "url": canonical_file_url(main, job.get("workspace")), "size": len(files[main]),
        "animations": requested, "rig_profile": "humanoid", "joint_count": inspected[main]["joint_count"],
        "clips": inspected[main]["clips"],
        "files": [{"filename": name, "url": canonical_file_url(name, job.get("workspace")), "role": role, "clips": inspected[name]["clips"]}
                  for name, role in roles.items()],
        "meshy": meshy, "warnings": warnings,
    }


def _execute(job_id: str, request: dict[str, Any], cancelled: Callable[[], bool]) -> dict[str, Any]:
    key = http.require_key(api_key())
    _update(job_id, phase="preparing", message="Checking the model", progress=0.02)
    model = read_source(Path(request["source"]))
    wanted = request["animations"]
    actions = resolve_actions(key, wanted, cancelled) if wanted else []
    warnings: list[str] = []
    rig = _rig(key, model, request["height_meters"], job_id, cancelled, warnings, 0.05, 0.5 if actions else 0.85)
    animated = None
    if actions:
        try:
            animated = _animate(key, rig.task_id, actions, job_id, cancelled, 0.5, 0.9)
        except MeshyError as error:
            if cancelled() or error.code == "cancelled":
                raise
            warnings.append(f"meshy_animation_failed: {error}. The rigged model was saved; its animation task is not repeated.")
    _update(job_id, phase="saving", message="Saving the rigged model", progress=0.92)
    return _publish(job_id, request, rig, animated, actions if animated else [], warnings, cancelled)


def run(job_id: str) -> None:
    """The job thread: do the Meshy work, then settle the shared rig job record."""
    rigs = _rigs()

    def cancelled() -> bool:
        with rigs._lock:
            job = rigs._jobs.get(job_id, {})
            return bool(job.get("cancel_requested")) or job.get("status") in {"cancelling", "cancelled"}

    with rigs._lock:
        request = dict((rigs._jobs.get(job_id) or {}).get("request") or {})
    if not request or cancelled():
        return
    _update(job_id, status="running", phase="starting", message="Preparing the model for Meshy", progress=0.01)
    try:
        outcome = _execute(job_id, request, cancelled)
    except Exception as exc:
        if cancelled():
            rigs._settle_cancelled_job(job_id)
            return
        fields = exc.fields if isinstance(exc, MeshyError) else {}
        _update(job_id, status="failed", phase="failed", message="Rigging failed", error=str(exc), **fields)
        return
    _update(job_id, status="completed", phase="completed", message="Rigged model saved", progress=1.0, **outcome)
