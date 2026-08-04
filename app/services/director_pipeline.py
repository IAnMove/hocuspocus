"""Server-side Director pipeline.

Orchestrates the full Director flow (LLM planning → image gen → video gen)
in a background thread so it can run without the browser being open.

Supports two planning backends:
  - Legacy: direct calls to llm_service (old monolithic approach)
  - New:    DirectorOrchestrator with layered architecture (planners → renderers → validators)

Controlled by feature flags in params or server config.
"""

import os
import time
import json
import uuid
import threading
import copy
import hashlib
import secrets
import subprocess
import re
import unicodedata
from typing import Optional

# These will be set by launch.py on startup
_jobs: dict = None          # reference to launch._jobs
_run_generation = None      # reference to launch._run_generation
_cancel_generation = None   # reference to launch._request_generation_cancel
_wgp = None                 # reference to wgp module
_gen_lock = None            # reference to launch._gen_lock

_pipelines: dict = {}
_pipeline_lock = threading.Lock()
_PRE_ACTIVE_CHILD_STATUSES = frozenset({
    "running",
    "queued",
    "paused",
})


class PipelineCancelled(RuntimeError):
    """Raised after a Director cancellation has stopped its active worker."""

# ── Pipeline State Persistence ─────────────────────────────────────────────

PIPELINE_STATE_VERSION = 2
_PIPELINE_FILE_PREFIX = "_director_pipeline_"


def _json_fingerprint(value) -> str:
    """Return a stable, compact fingerprint for resumable contracts."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_bool(value, *, default: bool = False) -> bool:
    """Parse API booleans without treating the string ``"false"`` as true."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    return bool(value)


def _file_identity(path: str) -> dict:
    """Identify a source without persisting its absolute path."""
    path = str(path or "")
    if not path or not os.path.isfile(path):
        return {"name": os.path.basename(path), "missing": True}
    stat = os.stat(path)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        digest.update(handle.read(65536))
        if stat.st_size > 65536:
            handle.seek(max(0, stat.st_size - 65536))
            digest.update(handle.read(65536))
    return {
        "name": os.path.basename(path),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "edge_sha256": digest.hexdigest(),
    }


def _normalise_master_seed(params: dict) -> int:
    """Choose once and persist the production's master seed."""
    candidates = (
        params.get("master_seed"),
        params.get("seed"),
        (params.get("video_params") or {}).get("seed"),
    )
    for candidate in candidates:
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            params["master_seed"] = value
            return value
    value = secrets.randbelow(2**31 - 1)
    params["master_seed"] = value
    return value


def _comic_shot(params: dict, index: int) -> dict:
    shots = params.get("comic_shots") or []
    return (
        shots[index]
        if index < len(shots) and isinstance(shots[index], dict)
        else {}
    )


def _stable_comic_shot_id(
    params: dict,
    index: int,
    plan: Optional[dict] = None,
) -> str:
    """Resolve the stable identity used for seeds, edits and PRE diffs."""
    plan = plan or {}
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    shot = _comic_shot(params, index)
    for source in (plan, metadata, shot):
        for key in ("shot_id", "primary_source_panel_id", "panel_id", "id"):
            value = str(source.get(key) or "").strip()
            if value:
                return value
        panel_ids = source.get("source_panel_ids")
        if isinstance(panel_ids, list) and panel_ids:
            values = [
                str(item).strip()
                for item in panel_ids
                if str(item).strip()
            ]
            if values:
                return "+".join(values)
    page = shot.get("page_number")
    panel = shot.get("panel_number")
    return f"comic-shot-{page or 0}-{panel or index + 1}"


def _comic_shot_seed(
    params: dict,
    index: int,
    plan: Optional[dict] = None,
) -> int:
    """Derive a reproducible seed from master seed and stable shot ID."""
    plan = plan or {}
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    shot = _comic_shot(params, index)
    for source in (plan, metadata, shot):
        try:
            explicit = int(source.get("seed"))
        except (TypeError, ValueError):
            continue
        if explicit >= 0:
            return explicit
    master = _normalise_master_seed(params)
    shot_id = _stable_comic_shot_id(params, index, plan)
    digest = hashlib.sha256(f"{master}:{shot_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _is_ltx_distilled(video_model: str) -> bool:
    value = str(video_model or "").lower()
    return "ltx2" in value and "distilled" in value


def _effective_ltx_runtime(video_model: str, video_params: dict) -> dict:
    """Expose what the local LTX route really executes."""
    requested_steps = int(video_params.get("num_inference_steps", 8) or 8)
    requested_guidance = float(video_params.get("guidance_scale", 1) or 1)
    requested_stage2 = int(video_params.get("stage2_steps", 3) or 3)
    if _is_ltx_distilled(video_model):
        return {
            "recipe": "ltx-distilled-two-stage",
            "num_inference_steps": 8,
            "stage2_steps": 3,
            "guidance_scale": 1.0,
            "requested_num_inference_steps": requested_steps,
            "requested_stage2_steps": requested_stage2,
            "requested_guidance_scale": requested_guidance,
            "guidance_note": (
                "Distilled uses its trained 8+3 schedule; conventional CFG "
                "is fixed at 1."
            ),
        }
    return {
        "recipe": "standard",
        "num_inference_steps": requested_steps,
        "stage2_steps": requested_stage2,
        "guidance_scale": requested_guidance,
        "requested_num_inference_steps": requested_steps,
        "requested_stage2_steps": requested_stage2,
        "requested_guidance_scale": requested_guidance,
        "guidance_note": "",
    }


def _comic_preflight_fingerprint(
    params: dict,
    clip_plans: list[dict],
    planned_clips: list[dict],
    clip_images: Optional[list[str]] = None,
    out_dir: Optional[str] = None,
) -> str:
    """Fingerprint every input that can change what Comic PRE promises."""
    source_paths = params.get("provided_clip_image_paths") or []
    prepared = [
        _file_identity(os.path.join(out_dir or "", str(filename or "")))
        for filename in (clip_images or [])
    ]
    contract = {
        "comic_id": params.get("comic_id"),
        "master_seed": _normalise_master_seed(params),
        "video_model": params.get("video_model"),
        "video_params": params.get("video_params") or {},
        "video_loras": params.get("video_loras") or {},
        "video_image_fit": params.get("video_image_fit"),
        "comic_motion_fidelity": params.get("comic_motion_fidelity"),
        "comic_end_frame_mode": params.get("comic_end_frame_mode"),
        "comic_shots": params.get("comic_shots") or [],
        "clip_plans": clip_plans,
        "planned_clips": planned_clips,
        "sources": [_file_identity(path) for path in source_paths],
        "prepared": prepared,
    }
    return _json_fingerprint(contract)


def _save_pipeline_state(pid: str) -> bool:
    """Serialize pipeline state to JSON on disk. Called at phase boundaries.

    Returning a success flag matters for PRE edits: superseded prepared images
    may only be deleted after the replacement checkpoint has reached disk.
    Legacy callers may continue to ignore the result.
    """
    with _pipeline_lock:
        p = _pipelines.get(pid)
        if not p:
            return False
        p = dict(p)  # shallow copy for safe access outside lock

    out_dir = p.get("out_dir") or (_wgp.save_path if _wgp else "outputs")
    params = p.get("params", {})

    # Build per-clip state
    clip_plans = p.get("clip_plans", [])
    clip_images = p.get("clip_images", [])
    clip_end_images = p.get("_clip_end_images", [])
    clip_source_images = p.get("_clip_source_images", [])
    clip_source_sizes = p.get("_clip_source_sizes", [])
    clip_fit_details = p.get("_clip_fit_details", [])
    pre_polish = p.get("_clip_plans_pre_polish", [])
    clip_timings = p.get("_clip_timings", {})
    clip_validations = p.get("_clip_validations", [])
    h3_reference_manifest = p.get("h3_reference_manifest", [])

    clips = []
    for i, plan in enumerate(clip_plans):
        clip_state = {
            "index": i,
            "planned_clip": p.get("_planned_clips", [{}] * (i + 1))[i] if i < len(p.get("_planned_clips", [])) else None,
            "image_prompt": plan.get("image_prompt", ""),
            "video_prompt": plan.get("video_prompt", ""),
            "visual_changes": plan.get("visual_changes", []) or [],
            "image_source": plan.get("image_source", "original"),
            "keyframe_prompts": plan.get("keyframe_prompts", []) or [],
            "window_prompts": plan.get("window_prompts", []) or [],
            "window_count": plan.get("window_count", 1),
            "effective_video_prompt": plan.get("_effective_video_prompt"),
            "effective_video_frames": plan.get("_effective_video_frames"),
            "image_prompt_pre_polish": pre_polish[i].get("image_prompt", "") if i < len(pre_polish) else None,
            "video_prompt_pre_polish": pre_polish[i].get("video_prompt", "") if i < len(pre_polish) else None,
            # Per-window and per-keyframe pre-polish snapshots so the
            # Dashboard can show before/after diffs for windowed shots
            # (≥21s) and for keyframe prompts. Without these, windowed
            # shots showed no polish diff because video_prompt is
            # skipped by Pass 3 when window_prompts exist (its content
            # is unused at generation time anyway).
            "window_prompts_pre_polish": pre_polish[i].get("window_prompts", []) if i < len(pre_polish) else None,
            "keyframe_prompts_pre_polish": pre_polish[i].get("keyframe_prompts", []) if i < len(pre_polish) else None,
            "start_image_filename": clip_images[i] if i < len(clip_images) else None,
            "source_image_filename": (
                clip_source_images[i] if i < len(clip_source_images) else None
            ),
            "source_size": (
                clip_source_sizes[i] if i < len(clip_source_sizes) else None
            ),
            "fit_details": (
                clip_fit_details[i] if i < len(clip_fit_details) else None
            ),
            "end_image_filename": clip_end_images[i] if i < len(clip_end_images) else None,
            "keyframe_filenames": (p.get("_clip_keyframes", []) or [])[i] if i < len(p.get("_clip_keyframes", [])) else [],
            "video_filename": (p.get("_clip_video_files", []) or [])[i] if i < len(p.get("_clip_video_files", [])) else None,
            "tag": (p.get("_clip_tags", []) or [])[i] if i < len(p.get("_clip_tags", [])) else None,
            "image_gen_time_sec": clip_timings.get(f"image_{i}"),
            "video_gen_time_sec": clip_timings.get(f"video_{i}"),
            "validation": (
                clip_validations[i] if i < len(clip_validations) else None
            ),
            "h3_references": (
                h3_reference_manifest[i]
                if i < len(h3_reference_manifest)
                else None
            ),
            "h3_segment_prompts": plan.get("h3_segment_prompts", []) or [],
            "h3_prompt_validation": (
                plan.get("metadata", {}).get("h3_prompt_validation")
                if isinstance(plan.get("metadata"), dict)
                else None
            ),
            "shot_id": _stable_comic_shot_id(params, i, plan),
            "seed": _comic_shot_seed(params, i, plan),
            "renderer": _comic_renderer(params, i, plan),
            "effective_renderer": _comic_effective_renderer(
                params,
                i,
                plan,
            ),
        }
        clips.append(clip_state)

    state = {
        "version": PIPELINE_STATE_VERSION,
        "pipeline_id": pid,
        "created_at": p.get("created_at"),
        "completed_at": p.get("_completed_at"),
        "status": p.get("status", "unknown"),
        "pipeline_type": params.get("pipeline_type", "music_video"),
        "comic_id": params.get("comic_id"),
        "scene_description": params.get("scene_description", ""),
        "reference_image_path": params.get("reference_image_path"),
        "character_ref_paths": params.get("character_ref_paths", []),
        "location_ref_paths": params.get("location_ref_paths", []),
        "auto_mode": params.get("auto_mode", True),
        "seamless": params.get("seamless", True),
        "image_model": params.get("image_model", ""),
        "video_model": params.get("video_model", ""),
        "image_loras": params.get("image_loras", {}),
        "video_loras": params.get("video_loras", {}),
        "image_params": params.get("image_params", {}),
        "video_params": params.get("video_params", {}),
        "h3_reference_manifest": h3_reference_manifest,
        "h3_prompt_validation": p.get("h3_prompt_validation"),
        "preview_clips": p.get("preview_clips", []),
        "preview_fingerprint": p.get("_comic_preflight_fingerprint"),
        "preview_revision": p.get("_preview_revision", 1),
        "preview_approved_fingerprint": p.get(
            "_preview_approved_fingerprint"
        ),
        "preview_approved": bool(
            p.get("_comic_preflight_fingerprint")
            and p.get("_preview_approved_fingerprint")
            == p.get("_comic_preflight_fingerprint")
        ),
        "quality_gate": p.get("_quality_gate") or {
            "status": "pending",
            "fingerprint": p.get("_comic_preflight_fingerprint"),
            "required_test_indices": [],
            "tested_indices": [],
            "results": {},
            "failures": [],
        },
        "clip_source_sizes": clip_source_sizes,
        "clip_fit_details": clip_fit_details,
        "clip_validations": clip_validations,
        "llm_log": p.get("_llm_log"),
        # Persist the complete dictionaries as well as the backwards-compatible
        # flattened clip summaries.  Metadata carries stable panel identities,
        # renderer choices and source mappings required to recompute the same
        # PRE fingerprint after a restart.
        "clip_plans": clip_plans,
        "planned_clips": p.get("_planned_clips", []),
        "clips": clips,
        "output_files": p.get("output_files", []),
        "workspace": p.get("workspace") or "default",
        "total_time_sec": (time.time() - p["created_at"]) if p.get("created_at") else None,
        # Full original request params, verbatim (it's the JSON dict the
        # endpoint received, so it's serializable). This is what makes a
        # crashed pipeline faithfully resumable — music-video mode in
        # particular depends on the analyzed audio track, character list, and
        # per-clip frame counts that the flattened per-clip state above does
        # not carry. resume_pipeline() rehydrates from here.
        "_params_snapshot": params,
    }

    filepath = os.path.join(out_dir, f"{_PIPELINE_FILE_PREFIX}{pid}.json")
    temp_path = f"{filepath}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False, default=str)
        os.replace(temp_path, filepath)
        return True
    except Exception as e:
        print(f"[Pipeline] Failed to save state for {pid}: {e}")
        return False
    finally:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def _pipeline_media_for_job(pid: str, out_dir: str, expected_clips: int) -> Optional[dict]:
    """Find a finished multi-clip job that belongs to a Director pipeline.

    A generation job writes one metadata sidecar per output.  The Director
    supervisor used to time out independently of the still-running generation
    thread, so a valid final movie could exist while the pipeline checkpoint
    still said ``failed``.  Grouping sidecars by generation job lets us adopt
    that completed work instead of submitting every clip again.
    """
    if not os.path.isdir(out_dir):
        return None

    groups: dict[str, list[tuple[float, str]]] = {}
    for filename in os.listdir(out_dir):
        if not filename.endswith(".meta.json"):
            continue
        meta_path = os.path.join(out_dir, filename)
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        except Exception:
            continue
        if metadata.get("director_pipeline_id") != pid:
            continue

        stem = filename[:-len(".meta.json")]
        media_name = next(
            (
                f"{stem}{extension}"
                for extension in (".mp4", ".webm", ".mkv", ".mov")
                if os.path.isfile(os.path.join(out_dir, f"{stem}{extension}"))
                and os.path.getsize(os.path.join(out_dir, f"{stem}{extension}")) > 1024
            ),
            None,
        )
        if not media_name:
            continue
        job_id = str(metadata.get("job_id") or "")
        if not job_id:
            continue
        created_at = float(metadata.get("created_at") or 0)
        groups.setdefault(job_id, []).append((created_at, media_name))

    candidates = []
    for job_id, entries in groups.items():
        final_entries = [entry for entry in entries if "_multiclip" in entry[1]]
        clip_entries = [entry for entry in entries if "_multiclip" not in entry[1]]
        if not final_entries or len(clip_entries) < expected_clips:
            continue
        final_created, final_name = max(final_entries)
        clip_names = [
            name for _, name in sorted(clip_entries, key=lambda item: (item[0], item[1]))
        ][:expected_clips]
        candidates.append({
            "job_id": job_id,
            "created_at": final_created,
            "final": final_name,
            "clips": clip_names,
        })

    return max(candidates, key=lambda item: item["created_at"]) if candidates else None


def _reconcile_pipeline_state_file(filepath: str, data: dict) -> dict:
    """Promote a timed-out checkpoint when its generation actually finished."""
    pid = str(data.get("pipeline_id") or "")
    clips = data.get("clips") if isinstance(data.get("clips"), list) else []
    if not pid or not clips:
        return data
    recovered = _pipeline_media_for_job(pid, os.path.dirname(filepath), len(clips))
    if not recovered:
        return data

    already_reconciled = (
        data.get("status") == "completed"
        and recovered["final"] in (data.get("output_files") or [])
        and all(
            clip.get("video_filename") == recovered["clips"][index]
            for index, clip in enumerate(clips)
        )
    )
    if already_reconciled:
        return data

    for index, clip in enumerate(clips):
        clip["video_filename"] = recovered["clips"][index]
    data["status"] = "completed"
    data["output_files"] = [recovered["final"]]
    data["completed_at"] = max(
        float(data.get("completed_at") or 0),
        float(recovered["created_at"] or 0),
    )
    data["recovered_at"] = time.time()
    data["recovery_note"] = (
        "Recovered completed generation outputs after the Director supervisor "
        "timed out."
    )

    temp_path = f"{filepath}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, default=str)
        os.replace(temp_path, filepath)
        print(
            f"[Pipeline {pid}] Recovered {len(clips)} clip videos and final "
            f"movie {recovered['final']} from job {recovered['job_id']}"
        )
    finally:
        try:
            if os.path.isfile(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
    return data


def list_pipeline_states(out_dir: str, workspace: Optional[str] = None) -> list[dict]:
    """Scan saved pipeline state files for one workspace.

    Older code always descended into every workspace, despite the API claiming
    to return the active workspace. Besides leaking unrelated history into the
    dashboard, that made comic PRE auto-recovery select another project's run.
    """
    results = []
    if not os.path.isdir(out_dir):
        return results
    normalized_workspace = workspace or "default"
    if normalized_workspace == "default":
        dirs_to_scan = [out_dir]
    else:
        workspace_dir = os.path.join(out_dir, normalized_workspace)
        dirs_to_scan = [workspace_dir] if os.path.isdir(workspace_dir) else []

    for scan_dir in dirs_to_scan:
        for fname in os.listdir(scan_dir):
            if fname.startswith(_PIPELINE_FILE_PREFIX) and fname.endswith(".json"):
                try:
                    filepath = os.path.join(scan_dir, fname)
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data = _reconcile_pipeline_state_file(filepath, data)
                    # Detect stale "running" pipelines — if the JSON says running
                    # but there's no active in-memory pipeline, it crashed
                    status = data.get("status", "unknown")
                    pid = data.get("pipeline_id", "")
                    if status == "running" and pid not in _pipelines:
                        status = "crashed"
                        data["status"] = "crashed"
                        try:
                            with open(filepath, "w", encoding="utf-8") as fw:
                                json.dump(data, fw, indent=2, ensure_ascii=False, default=str)
                        except Exception:
                            pass
                    results.append({
                        "id": pid,
                        "status": status,
                        "pipeline_type": data.get("pipeline_type", ""),
                        "created_at": data.get("created_at"),
                        "clip_count": len(data.get("clips", [])),
                        "output_count": len(data.get("output_files", [])),
                        "scene_description": (data.get("scene_description", "") or "")[:100],
                        "comic_id": data.get("comic_id"),
                        "preview_fingerprint": data.get("preview_fingerprint"),
                        "preview_revision": data.get("preview_revision", 1),
                        "workspace": os.path.basename(scan_dir) if scan_dir != out_dir else "default",
                        "_filepath": filepath,
                    })
                except Exception:
                    pass
    results.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
    return results


def load_pipeline_state(out_dir: str, pid: str) -> Optional[dict]:
    """Load a saved pipeline state by ID. Searches out_dir and subdirectories."""
    target = f"{_PIPELINE_FILE_PREFIX}{pid}.json"
    # Search top-level
    filepath = os.path.join(out_dir, target)
    if os.path.isfile(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return _reconcile_pipeline_state_file(filepath, json.load(f))
    # Search subdirectories (workspaces)
    if os.path.isdir(out_dir):
        for name in os.listdir(out_dir):
            sub = os.path.join(out_dir, name, target)
            if os.path.isfile(sub):
                with open(sub, "r", encoding="utf-8") as f:
                    return _reconcile_pipeline_state_file(sub, json.load(f))
    return None


def update_clip_tag(out_dir: str, pid: str, clip_index: int, tag: Optional[str]) -> bool:
    """Update the tag on a specific clip in a saved pipeline state."""
    state = load_pipeline_state(out_dir, pid)
    if not state:
        return False
    clips = state.get("clips", [])
    if clip_index < 0 or clip_index >= len(clips):
        return False
    clips[clip_index]["tag"] = tag

    # Find and overwrite the file
    target = f"{_PIPELINE_FILE_PREFIX}{pid}.json"
    for search_dir in [out_dir] + [os.path.join(out_dir, d) for d in os.listdir(out_dir) if os.path.isdir(os.path.join(out_dir, d))]:
        filepath = os.path.join(search_dir, target)
        if os.path.isfile(filepath):
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False, default=str)
            return True
    return False


def _find_pipeline_file(out_dir: str, pid: str) -> Optional[str]:
    """Find the JSON file path for a saved pipeline."""
    target = f"{_PIPELINE_FILE_PREFIX}{pid}.json"
    filepath = os.path.join(out_dir, target)
    if os.path.isfile(filepath):
        return filepath
    if os.path.isdir(out_dir):
        for name in os.listdir(out_dir):
            sub = os.path.join(out_dir, name, target)
            if os.path.isfile(sub):
                return sub
    return None


def _update_saved_pipeline(out_dir: str, pid: str, updater) -> Optional[dict]:
    """Load a saved pipeline, apply an updater function, save back, and return the state."""
    filepath = _find_pipeline_file(out_dir, pid)
    if not filepath:
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        state = json.load(f)
    updater(state)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)
    return state


def rerun_clip_image(out_dir: str, pid: str, clip_index: int, prompt_override: str = None) -> dict:
    """Re-generate the start image for a single clip. Returns {job_id, filename} or raises."""
    state = load_pipeline_state(out_dir, pid)
    if not state:
        raise ValueError(f"Pipeline {pid} not found")
    clips = state.get("clips", [])
    if clip_index < 0 or clip_index >= len(clips):
        raise ValueError(f"Clip index {clip_index} out of range (0-{len(clips)-1})")

    clip = clips[clip_index]
    prompt = prompt_override or clip.get("image_prompt", "")
    if not prompt:
        raise ValueError("No image prompt for this clip")

    # Get image gen params from the saved pipeline state
    image_model = state.get("image_model") or "flux2_klein_9b"
    image_loras = state.get("image_loras") or {}
    image_params = state.get("image_params") or {}
    ref_path = state.get("reference_image_path") or ""

    # Build refs: main + character + location
    all_refs = []
    if ref_path and os.path.isfile(ref_path):
        all_refs.append(ref_path)
    for cp in (state.get("character_ref_paths") or []):
        if cp and os.path.isfile(cp):
            all_refs.append(cp)
    for lp in (state.get("location_ref_paths") or []):
        if lp and os.path.isfile(lp):
            all_refs.append(lp)

    # Determine the output directory from where the pipeline file lives
    pipeline_file = _find_pipeline_file(out_dir, pid)
    clip_out_dir = os.path.dirname(pipeline_file) if pipeline_file else out_dir

    try:
        rerun_seed = int(clip.get("seed", -1))
    except (TypeError, ValueError):
        rerun_seed = -1
    if image_model == "minimax:image-01":
        new_filename = _generate_minimax_director_image(
            prompt=prompt,
            resolution=image_params.get("resolution", "1280x720"),
            output_dir=clip_out_dir,
            reference_paths=[
                *(state.get("character_ref_paths") or []),
                ref_path,
            ],
        )
    else:
        gen_params = {
            "model_type": image_model,
            "prompt": prompt,
            "image_refs": all_refs if all_refs else [ref_path],
            "image_mode": 1,
            "image_prompt_type": "",
            "num_inference_steps": image_params.get("num_inference_steps", 8),
            "guidance_scale": image_params.get("guidance_scale", 1),
            "video_prompt_type": "KI",
            "resolution": image_params.get("resolution", "1280x720"),
            "seed": rerun_seed,
            "settings_version": 2.52,
            "generation_mode": "image",
            "repeat_generation": 1,
            "negative_prompt": "",
            "video_length": 1,
            "activated_loras": image_loras.get("activated_loras", []),
            "loras_multipliers": " ".join(
                m.split(";")[0]
                for m in (image_loras.get("loras_multipliers", "") or "").split(" ")
                if m
            ),
            "_director_pipeline_id": pid,
        }

        output_files = _submit_and_wait(gen_params, timeout_s=600, out_dir=clip_out_dir)
        new_filename = output_files[0] if output_files else ""

    if new_filename:
        # Update the saved pipeline state
        def _update(s):
            s["clips"][clip_index]["start_image_filename"] = new_filename
            if prompt_override:
                s["clips"][clip_index]["image_prompt"] = prompt_override
        _update_saved_pipeline(out_dir, pid, _update)

    return {"filename": new_filename, "clip_index": clip_index}


def rerun_clip_video(out_dir: str, pid: str, clip_index: int, prompt_override: str = None) -> dict:
    """Re-generate the video for a single clip. Returns {job_id, filename} or raises."""
    state = load_pipeline_state(out_dir, pid)
    if not state:
        raise ValueError(f"Pipeline {pid} not found")
    clips = state.get("clips", [])
    if clip_index < 0 or clip_index >= len(clips):
        raise ValueError(f"Clip index {clip_index} out of range (0-{len(clips)-1})")

    clip = clips[clip_index]
    prompt = prompt_override or clip.get("video_prompt", "")
    if not prompt:
        raise ValueError("No video prompt for this clip")

    video_model = state.get("video_model") or "ltx2_22B_distilled_1_1"
    video_loras = state.get("video_loras") or {}
    video_params = state.get("video_params") or {}

    # Determine the output directory
    pipeline_file = _find_pipeline_file(out_dir, pid)
    clip_out_dir = os.path.dirname(pipeline_file) if pipeline_file else out_dir

    # Build start image path
    start_img = clip.get("start_image_filename")
    start_path = os.path.join(clip_out_dir, start_img) if start_img else ""
    has_start = start_path and os.path.isfile(start_path)
    end_img = clip.get("end_image_filename")
    end_path = os.path.join(clip_out_dir, end_img) if end_img else ""
    has_end = end_path and os.path.isfile(end_path)

    # Use planned_clip for duration
    planned = clip.get("planned_clip") or {}
    duration_sec = planned.get("duration_sec", planned.get("end", 20) - planned.get("start", 0))
    if duration_sec <= 0:
        duration_sec = 20
    fps = 25  # LTX-2 default
    video_length = int(duration_sec * fps)
    if has_end:
        try:
            _, trim_step, _ = _wgp.get_model_min_frames_and_step(video_model)
        except Exception:
            trim_step = 8
        # launch.py trims the end-conditioned tail. Generate one extra latent
        # step so a rerun keeps the original panel duration.
        video_length += trim_step

    resolution = _normalize_video_resolution(
        video_model,
        video_params.get("resolution", "1280x720"),
    )
    snapshot = state.get("_params_snapshot") or {}
    is_comic_movie = (
        state.get("pipeline_type") == "comic_movie"
        or snapshot.get("pipeline_type") == "comic_movie"
    )
    if is_comic_movie:
        raise ValueError(
            "Comic shots must be regenerated from their approved PRE. "
            "Use Generate only this clip there so renderer, fit, seed, "
            "negative prompt and frame contract remain exact."
        )
    try:
        rerun_seed = int(clip.get("seed", -1))
    except (TypeError, ValueError):
        rerun_seed = -1
    camera_locked = is_comic_movie and _comic_camera_is_locked(snapshot, clip_index)
    negative_prompt = str(video_params.get("negative_prompt") or "").strip()
    if camera_locked:
        negative_prompt = _append_negative_prompt(
            negative_prompt,
            _COMIC_LOCKED_CAMERA_NEGATIVE,
        )
    if is_comic_movie:
        negative_prompt = _append_negative_prompt(
            negative_prompt,
            _COMIC_REFERENCE_NEGATIVE,
        )
    runtime = _effective_ltx_runtime(video_model, video_params)
    gen_params = {
        "model_type": video_model,
        "prompt": _comic_motion_prompt(
            prompt,
            snapshot.get("comic_motion_fidelity", "faithful"),
            bool(has_end),
            camera_locked=camera_locked,
            motion_mode=_comic_motion_mode(snapshot, clip_index),
        ),
        "image_mode": 0,
        "image_prompt_type": "SE" if has_start and has_end else ("S" if has_start else ("E" if has_end else "")),
        "num_inference_steps": runtime["num_inference_steps"],
        "guidance_scale": runtime["guidance_scale"],
        "resolution": resolution,
        "video_length": video_length,
        "seed": rerun_seed,
        "settings_version": 2.52,
        "generation_mode": "video",
        "repeat_generation": 1,
        "negative_prompt": negative_prompt,
        "activated_loras": video_loras.get("activated_loras", []),
        "loras_multipliers": " ".join(
            m.split(";")[0] for m in (video_loras.get("loras_multipliers", "") or "").split(" ") if m
        ),
        "_director_pipeline_id": pid,
    }
    gen_params["stage2_steps"] = runtime["stage2_steps"]
    if has_start:
        gen_params["image_start"] = start_path
        gen_params["input_video_strength"] = video_params.get(
            "input_video_strength",
            0.7 if "distilled" in str(video_model).lower() else 1.0,
        )
        fidelity = str(
            (state.get("_params_snapshot") or {}).get(
                "comic_motion_fidelity",
                "faithful",
            )
        ).lower()
        if fidelity == "faithful":
            gen_params["input_video_strength"] = max(
                0.9,
                float(gen_params["input_video_strength"]),
            )
        elif has_end:
            gen_params["input_video_strength"] = max(
                0.8,
                float(gen_params["input_video_strength"]),
            )
    if has_end:
        gen_params["image_end"] = end_path
    for runtime_key in (
        "single_stage_pipeline",
        "progressive_pipeline",
        "stage2_steps",
        "progressive_stage1_image_weight",
        "progressive_stage2_steps",
        "progressive_stage2_sigma",
        "progressive_stage3_steps",
        "progressive_stage3_sigma",
        "progressive_stage3_image_weight",
    ):
        if runtime_key in video_params:
            if (
                runtime_key == "stage2_steps"
                and _is_ltx_distilled(video_model)
            ):
                continue
            gen_params[runtime_key] = video_params[runtime_key]

    output_files = _submit_and_wait(gen_params, timeout_s=3600, out_dir=clip_out_dir)
    new_filename = output_files[0] if output_files else ""

    if new_filename:
        def _update(s):
            s["clips"][clip_index]["video_filename"] = new_filename
            if prompt_override:
                s["clips"][clip_index]["video_prompt"] = prompt_override
        _update_saved_pipeline(out_dir, pid, _update)

    return {"filename": new_filename, "clip_index": clip_index}


def rejoin_clips(out_dir: str, pid: str) -> dict:
    """Re-join all clips from a saved pipeline using current best versions. Returns {filename}."""
    state = load_pipeline_state(out_dir, pid)
    if not state:
        raise ValueError(f"Pipeline {pid} not found")

    pipeline_file = _find_pipeline_file(out_dir, pid)
    clip_out_dir = os.path.dirname(pipeline_file) if pipeline_file else out_dir

    clips = state.get("clips", [])
    video_files = []
    for clip in clips:
        vf = clip.get("video_filename")
        if vf:
            full_path = os.path.join(clip_out_dir, vf)
            if os.path.isfile(full_path):
                video_files.append(full_path)

    if len(video_files) < 2:
        raise ValueError(f"Need at least 2 video clips to rejoin, found {len(video_files)}")

    # Use wgp's concatenation
    import time as _time
    timestamp = _time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    output_name = f"{timestamp}_rejoin_multiclip.mp4"
    output_path = os.path.join(clip_out_dir, output_name)

    try:
        _wgp.concatenate_videos(video_files, output_path)
        print(f"[Pipeline] Rejoined {len(video_files)} clips → {output_name}")

        # Update pipeline state
        def _update(s):
            if output_name not in s.get("output_files", []):
                s.setdefault("output_files", []).append(output_name)
        _update_saved_pipeline(out_dir, pid, _update)

        return {"filename": output_name}
    except Exception as e:
        raise RuntimeError(f"Rejoin failed: {e}")


def init(
    jobs_dict,
    run_gen_fn,
    wgp_module,
    gen_lock=None,
    cancel_gen_fn=None,
):
    """Called by launch.py to wire up shared references."""
    global _jobs, _run_generation, _cancel_generation, _wgp, _gen_lock
    _jobs = jobs_dict
    _run_generation = run_gen_fn
    _cancel_generation = cancel_gen_fn
    _wgp = wgp_module
    _gen_lock = gen_lock


def _pipeline_cancel_requested(pid: Optional[str]) -> bool:
    if not pid:
        return False
    with _pipeline_lock:
        pipeline = _pipelines.get(pid)
        return bool(
            pipeline
            and (
                pipeline.get("_cancel_requested")
                or pipeline.get("status") == "cancelled"
                or pipeline.get("phase") == "cancelling"
            )
        )


def _clear_active_generation_job(pid: Optional[str], job_id: str) -> None:
    """Clear only the job this waiter owns, preserving a newer worker."""
    if not pid:
        return
    with _pipeline_lock:
        pipeline = _pipelines.get(pid)
        if (
            pipeline
            and pipeline.get("_active_generation_job_id") == job_id
        ):
            pipeline.pop("_active_generation_job_id", None)


def _submit_and_wait(params: dict, timeout_s: float = 600, workspace: str = None, out_dir: str = None) -> list[str]:
    """Submit a generation job and block until it completes.

    ``timeout_s`` is an inactivity timeout, not an absolute wall-clock limit.
    A 96-panel comic can legitimately take longer than two hours; it should
    only fail when the underlying job has stopped reporting progress.

    Returns list of output filenames. Raises on failure/timeout.
    """
    _dir_pid = params.get("_director_pipeline_id")
    if _pipeline_cancel_requested(_dir_pid):
        raise PipelineCancelled("Director pipeline was cancelled.")

    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "step": 0,
        "total_steps": 0,
        "phase": "",
        "message": "Queued",
        "created_at": time.time(),
        "params": params,
        "output_files": [],
        "error": None,
        "workspace": workspace,
        "out_dir": out_dir,
        "last_progress_at": time.time(),
    }
    _jobs[job_id] = job

    if _dir_pid:
        with _pipeline_lock:
            pipeline = _pipelines.get(_dir_pid)
            if pipeline:
                pipeline["_active_generation_job_id"] = job_id
        _save_pipeline_state(_dir_pid)

    # Close the race between registering the worker and a simultaneous Stop.
    if _pipeline_cancel_requested(_dir_pid):
        job["_cancel_requested"] = True
        job["status"] = "cancelled"
        job["message"] = "Cancelled"
        _clear_active_generation_job(_dir_pid, job_id)
        raise PipelineCancelled("Director pipeline was cancelled.")

    # Run generation in a separate thread (it acquires _gen_lock internally)
    # Non-daemon so the process stays alive if browser disconnects mid-generation
    thread = threading.Thread(target=_run_generation, args=(job_id,), daemon=False)
    thread.start()

    # Wait for completion, mirroring job progress to pipeline status
    last_activity_at = time.time()
    last_signature = None
    last_saved_clip_outputs: tuple = ()
    cancel_dispatched = False
    while True:
        j = _jobs.get(job_id)
        if not j:
            _clear_active_generation_job(_dir_pid, job_id)
            raise RuntimeError("Job disappeared")

        if _pipeline_cancel_requested(_dir_pid) and not cancel_dispatched:
            cancel_dispatched = True
            if _cancel_generation is not None:
                _cancel_generation(job_id)
            else:
                # Tests and standalone callers may initialize Director without
                # launch.py's abort callback. Preserve the same queued-job
                # semantics and expose an explicit request to cooperative
                # workers instead of pretending an active GPU job has stopped.
                j["_cancel_requested"] = True
                if j.get("status") == "queued":
                    j["status"] = "cancelled"
                    j["message"] = "Cancelled"

        signature = (
            j.get("status"),
            j.get("progress"),
            j.get("step"),
            j.get("total_steps"),
            j.get("phase"),
            j.get("message"),
            tuple(j.get("clip_output_files") or ()),
        )
        if signature != last_signature:
            last_signature = signature
            last_activity_at = time.time()
        progress_at = float(j.get("last_progress_at") or 0)
        if progress_at > last_activity_at:
            last_activity_at = progress_at

        clip_outputs = tuple(j.get("clip_output_files") or ())
        if _dir_pid and clip_outputs and clip_outputs != last_saved_clip_outputs:
            last_saved_clip_outputs = clip_outputs
            with _pipeline_lock:
                pipeline = _pipelines.get(_dir_pid)
                if pipeline:
                    expected = len(pipeline.get("clip_plans") or [])
                    index_map = params.get("_director_clip_index_map")
                    if isinstance(index_map, list) and index_map:
                        merged = list(
                            pipeline.get("_clip_video_files")
                            or [None] * expected
                        )
                        if len(merged) < expected:
                            merged.extend([None] * (expected - len(merged)))
                        for local_index, name in enumerate(clip_outputs):
                            if local_index >= len(index_map):
                                break
                            try:
                                global_index = int(index_map[local_index])
                            except (TypeError, ValueError):
                                continue
                            if 0 <= global_index < expected:
                                merged[global_index] = name
                        pipeline["_clip_video_files"] = merged
                    else:
                        pipeline["_clip_video_files"] = list(
                            clip_outputs[:expected]
                        )
                    completed = sum(
                        bool(name)
                        for name in pipeline.get("_clip_video_files", [])[:expected]
                    )
                    if "progress" in pipeline:
                        pipeline["progress"]["current"] = completed
                        pipeline["progress"]["total"] = expected
                        pipeline["progress"]["message"] = (
                            f"Generated clip {completed}/{expected}; checkpoint saved"
                        )
            _save_pipeline_state(_dir_pid)

        if j["status"] == "completed":
            _clear_active_generation_job(_dir_pid, job_id)
            if _pipeline_cancel_requested(_dir_pid):
                _update_pipeline(
                    _dir_pid,
                    status="cancelled",
                    phase="cancelled",
                )
                _save_pipeline_state(_dir_pid)
                raise PipelineCancelled("Director pipeline was cancelled.")
            return j.get("output_files", [])
        if j["status"] == "failed":
            _clear_active_generation_job(_dir_pid, job_id)
            err = j.get("error") or "Generation failed"
            print(f"[Pipeline] Job {job_id} failed: {err}")
            raise RuntimeError(err)
        if j["status"] == "cancelled":
            _clear_active_generation_job(_dir_pid, job_id)
            if _dir_pid:
                _update_pipeline(
                    _dir_pid,
                    status="cancelled",
                    phase="cancelled",
                    progress={
                        "current": 0,
                        "total": 0,
                        "message": "Cancelled",
                        "step": 0,
                        "total_steps": 0,
                    },
                )
                _save_pipeline_state(_dir_pid)
            raise PipelineCancelled("Director pipeline was cancelled.")
        # Mirror denoising step progress to pipeline status
        # Only update step/total_steps and message — preserve current/total for pipeline-level counts
        if _dir_pid and (j.get("step", 0) > 0 or j.get("total_steps", 0) > 0):
            with _pipeline_lock:
                p = _pipelines.get(_dir_pid)
                if p and "progress" in p:
                    p["progress"]["step"] = j.get("step", 0)
                    p["progress"]["total_steps"] = j.get("total_steps", 0)
                    p["progress"]["message"] = j.get("phase") or j.get("message") or "Generating..."
        if time.time() - last_activity_at >= timeout_s:
            raise RuntimeError(
                f"Generation stalled: no progress was reported for "
                f"{max(1, round(timeout_s / 60))} minutes"
            )
        time.sleep(1)


def _update_pipeline(pid: str, **kwargs):
    """Thread-safe update of pipeline state."""
    with _pipeline_lock:
        if pid in _pipelines:
            _pipelines[pid].update(kwargs)


def start_pipeline(params: dict) -> str:
    """Start a new director pipeline. Returns pipeline_id."""
    pid = uuid.uuid4().hex[:8]
    params = dict(params)
    _normalise_master_seed(params)

    # Capture workspace at submission time — not at execution time
    workspace = params.pop("workspace", None)
    if workspace:
        # Resolve the output directory now, while we know the intended workspace
        from launch import _workspace_dir
        out_dir = _workspace_dir(workspace)
        print(f"[Pipeline] Workspace={workspace}, out_dir={out_dir}, wgp.save_path={_wgp.save_path}")
    else:
        out_dir = _wgp.save_path
        workspace = None
        print(f"[Pipeline] No workspace, using wgp.save_path={out_dir}")

    pipeline = {
        "id": pid,
        "status": "running",
        "phase": "planning",
        "auto_mode": params.get("auto_mode", True),
        "progress": {"current": 0, "total": 0, "message": "Starting...", "step": 0, "total_steps": 0},
        "clip_plans": [],
        "clip_images": [],         # filenames of generated start images
        "output_files": [],
        "error": None,
        "created_at": time.time(),
        "params": params,
        "pause_reason": None,
        "workspace": workspace,
        "out_dir": out_dir,
        # For LLM streaming: the frontend polls /api/v1/llm/stream-status
        "llm_streaming": False,
    }

    with _pipeline_lock:
        _pipelines[pid] = pipeline

    # Non-daemon so pipeline survives browser disconnect during overnight runs
    thread = threading.Thread(target=_run_pipeline, args=(pid,), daemon=False)
    thread.start()

    return pid


def get_pipeline(pid: str) -> Optional[dict]:
    with _pipeline_lock:
        p = _pipelines.get(pid)
        return dict(p) if p else None


def continue_pipeline(pid: str, updates: Optional[dict] = None):
    """Resume a paused pipeline, optionally with updated clip_plans."""
    with _pipeline_lock:
        p = _pipelines.get(pid)
        if not p or p["status"] != "paused":
            return False
        if updates:
            if "clip_plans" in updates:
                p["clip_plans"] = updates["clip_plans"]
        p["status"] = "running"
        p["pause_reason"] = None
    return True


def start_preview_generation(
    pid: str,
    clip_index: Optional[int] = None,
    out_dir: Optional[str] = None,
    clip_indices: Optional[list[int]] = None,
    expected_fingerprint: Optional[str] = None,
    run_type: Optional[str] = None,
) -> tuple[bool, str, Optional[str]]:
    """Generate all or one clip from a completed comic PRE checkpoint.

    The PRE pipeline remains immutable and reusable.  A child pipeline gets
    the exact polished prompts, prepared I2V images and effective frame counts
    that were shown to the user, then resumes immediately at video generation.
    """
    import copy

    with _pipeline_lock:
        source = _pipelines.get(pid)

    # PRE checkpoints are deliberately durable. Rehydrate a preview_ready
    # checkpoint after a backend restart instead of requiring the user to
    # press the generic Resume action first.
    if not source and out_dir:
        recovered, message = resume_pipeline(pid, out_dir)
        if not recovered:
            return False, message, None

    with _pipeline_lock:
        source = _pipelines.get(pid)
        if not source:
            return False, "PRE pipeline not found.", None
        if source.get("status") != "preview_ready":
            return False, "The comic PRE is not ready yet.", None
        source = copy.deepcopy(source)

    stored_fingerprint = str(
        source.get("_comic_preflight_fingerprint")
        or (source.get("params") or {}).get("_comic_preflight_fingerprint")
        or ""
    )
    if not stored_fingerprint:
        return (
            False,
            "This is a legacy PRE without a verifiable fingerprint. Rebuild "
            "PRE before generating any test clip or film.",
            None,
        )
    if stored_fingerprint and not expected_fingerprint:
        return (
            False,
            "expected_fingerprint is required to generate from PRE.",
            None,
        )
    if expected_fingerprint and stored_fingerprint != str(expected_fingerprint):
        return (
            False,
            "This PRE is stale because its film plan or settings changed. "
            "Open the current PRE tab and review it again.",
            None,
        )
    if stored_fingerprint:
        current_fingerprint = _comic_preflight_fingerprint(
            source.get("params") or {},
            source.get("clip_plans") or [],
            source.get("_planned_clips") or [],
            source.get("clip_images") or [],
            source.get("out_dir") or out_dir,
        )
        if current_fingerprint != stored_fingerprint:
            return (
                False,
                "This PRE is stale because a source image or generation "
                "setting changed. Rebuild PRE before generating video.",
                None,
            )

    clip_plans = source.get("clip_plans") or []
    clip_images = source.get("clip_images") or []
    planned_clips = source.get("_planned_clips") or []
    if not clip_plans or len(clip_images) != len(clip_plans):
        return False, "The comic PRE has incomplete clip data.", None

    if clip_indices is not None:
        if not isinstance(clip_indices, list) or not clip_indices:
            return False, "clip_indices must be a non-empty array.", None
        selected = []
        seen = set()
        for raw_index in clip_indices:
            try:
                normalized_index = int(raw_index)
            except (TypeError, ValueError):
                return False, "Every clip index must be an integer.", None
            if normalized_index < 0 or normalized_index >= len(clip_plans):
                return False, "A selected PRE clip does not exist.", None
            if normalized_index not in seen:
                selected.append(normalized_index)
                seen.add(normalized_index)
    elif clip_index is None:
        preview_clips = source.get("preview_clips") or []
        selected = [
            index
            for index in range(len(clip_plans))
            if index >= len(preview_clips)
            or preview_clips[index].get("included", True) is not False
        ]
        if not selected:
            return False, "PRE has no enabled shots.", None
    else:
        try:
            normalized_index = int(clip_index)
        except (TypeError, ValueError):
            return False, "clip_index must be an integer.", None
        if normalized_index < 0 or normalized_index >= len(clip_plans):
            return False, "The selected PRE clip does not exist.", None
        selected = [normalized_index]

    preview_clips = source.get("preview_clips") or []
    excluded = [
        index + 1
        for index in selected
        if index < len(preview_clips)
        and preview_clips[index].get("included", True) is False
    ]
    if excluded:
        return (
            False,
            "Shots "
            + ", ".join(str(value) for value in excluded)
            + " are disabled in PRE.",
            None,
        )
    blocked = [
        index + 1
        for index in selected
        if index < len(preview_clips)
        and preview_clips[index].get("needs_reframe")
        and not (
            preview_clips[index].get("reframe_approved")
            and preview_clips[index].get("used_prepared_keyframe")
        )
    ]
    if blocked:
        return (
            False,
            "Shots "
            + ", ".join(str(value) for value in blocked)
            + " need a video-safe reframe. Choose Cover/Contain or approve "
              "a prepared keyframe in PRE first.",
            None,
        )

    effective_run_type = str(
        run_type
        or (
            "test"
            if clip_index is not None or clip_indices is not None
            else "full"
        )
    ).strip().lower()
    if effective_run_type not in {"test", "full"}:
        return False, "run_type must be 'test' or 'full'.", None
    approved = bool(
        stored_fingerprint
        and source.get("_preview_approved_fingerprint")
        == stored_fingerprint
    )
    if effective_run_type == "test" and stored_fingerprint and not approved:
        return (
            False,
            "Approve this exact PRE revision before running its quality test.",
            None,
        )
    if effective_run_type == "full":
        enabled_indices = [
            index
            for index in range(len(clip_plans))
            if index >= len(preview_clips)
            or preview_clips[index].get("included", True) is not False
        ]
        if selected != enabled_indices:
            return (
                False,
                "A full PRE generation must include every enabled shot in "
                "its approved editorial order.",
                None,
            )
        gate = source.get("_quality_gate") or {}
        gate_ready = bool(
            gate.get("fingerprint") == stored_fingerprint
            and gate.get("status") in {"passed", "waived"}
        )
        if not approved:
            return (
                False,
                "Approve this exact PRE revision before generating the film.",
                None,
            )
        if not gate_ready:
            return (
                False,
                "Run and pass a representative PRE quality test first, or "
                "record an explicit quality waiver.",
                None,
            )

    # Treat launching a frozen PRE as an idempotent operation. Fast double
    # clicks and remounted UI panels must reconnect to the active child rather
    # than submit another expensive GPU job with identical inputs. A different
    # request from the same PRE is rejected while any child is active: two LTX
    # children from separate tabs would otherwise compete for VRAM and can OOM.
    with _pipeline_lock:
        active_children = [
            candidate
            for candidate in _pipelines.values()
            if candidate.get("_source_preview_pipeline_id") == pid
            and candidate.get("_source_preview_fingerprint")
            == stored_fingerprint
            and candidate.get("status") in _PRE_ACTIVE_CHILD_STATUSES
        ]
        for candidate in active_children:
            if (
                candidate.get("_source_preview_clip_indices") == selected
                and candidate.get("_preview_run_type") == effective_run_type
            ):
                return True, "already_running", candidate.get("id")
        if active_children:
            return (
                False,
                "Another generation from this PRE revision is active. Wait "
                "for it to finish or cancel it before starting different clips.",
                active_children[0].get("id"),
            )

    params = copy.deepcopy(source.get("params") or {})
    params["comic_preflight_only"] = False
    params["auto_mode"] = True
    params["comic_shots"] = [
        (params.get("comic_shots") or [])[index]
        for index in selected
        if index < len(params.get("comic_shots") or [])
    ]
    provided_paths = params.get("provided_clip_image_paths") or []
    params["provided_clip_image_paths"] = [
        provided_paths[index]
        for index in selected
        if index < len(provided_paths)
    ]
    frozen_negatives = params.get("_effective_video_negative_prompts")
    if isinstance(frozen_negatives, list):
        params["_effective_video_negative_prompts"] = [
            frozen_negatives[index]
            for index in selected
            if index < len(frozen_negatives)
        ]

    prepared_end_images = source.get("_clip_end_images") or []
    selected_end_images = [
        prepared_end_images[index] if index < len(prepared_end_images) else ""
        for index in selected
    ]
    # A single-clip child no longer has the following panel in its local
    # sequence, so carry the PRE's already-resolved end-frame explicitly.
    params["_comic_prepared_end_images"] = selected_end_images
    params["_source_preview_pipeline_id"] = pid
    params["_source_preview_clip_indices"] = selected
    params["_source_preview_fingerprint"] = stored_fingerprint
    params["_preview_run_type"] = effective_run_type

    child_pid = uuid.uuid4().hex[:8]
    child_plans = [copy.deepcopy(clip_plans[index]) for index in selected]
    child_images = [clip_images[index] for index in selected]
    child_source_images_all = source.get("_clip_source_images") or []
    child_source_images = [
        child_source_images_all[index]
        if index < len(child_source_images_all)
        else ""
        for index in selected
    ]
    child_planned = [
        copy.deepcopy(planned_clips[index])
        if index < len(planned_clips)
        else {}
        for index in selected
    ]
    child_keyframes_source = source.get("_clip_keyframes") or []
    child_keyframes = [
        copy.deepcopy(child_keyframes_source[index])
        if index < len(child_keyframes_source)
        else []
        for index in selected
    ]
    reusable_video_files = [None] * len(selected)
    if effective_run_type == "full":
        gate = source.get("_quality_gate") or {}
        gate_results = (
            gate.get("results")
            if gate.get("status") == "passed"
            and gate.get("fingerprint") == stored_fingerprint
            and isinstance(gate.get("results"), dict)
            else {}
        )
        source_out_dir = source.get("out_dir") or out_dir or ""
        for local_index, original_index in enumerate(selected):
            result = gate_results.get(str(original_index))
            if not isinstance(result, dict) or not result.get("passed"):
                continue
            filename = str(result.get("video_filename") or "").strip()
            candidate = (
                filename
                if os.path.isabs(filename)
                else os.path.join(source_out_dir, filename)
            )
            if filename and os.path.isfile(candidate):
                reusable_video_files[local_index] = filename
    child = {
        "id": child_pid,
        "status": "running",
        "phase": "resuming",
        "auto_mode": True,
        "progress": {
            "current": 0,
            "total": len(selected),
            "message": (
                f"Starting PRE clip {selected[0] + 1}…"
                if len(selected) == 1
                else f"Starting {len(selected)} PRE clips…"
            ),
            "step": 0,
            "total_steps": 0,
        },
        "clip_plans": child_plans,
        "_planned_clips": child_planned,
        "clip_images": child_images,
        "_clip_source_images": child_source_images,
        "_clip_source_sizes": [
            (source.get("_clip_source_sizes") or [])[index]
            if index < len(source.get("_clip_source_sizes") or [])
            else None
            for index in selected
        ],
        "_clip_fit_details": [
            copy.deepcopy((source.get("_clip_fit_details") or [])[index])
            if index < len(source.get("_clip_fit_details") or [])
            else {}
            for index in selected
        ],
        "_clip_end_images": selected_end_images,
        "_clip_keyframes": child_keyframes,
        # A visually accepted representative clip was generated from this
        # exact frozen fingerprint. Reuse it in the full film instead of
        # spending time and credits creating an identical shot again.
        "_clip_video_files": reusable_video_files,
        "output_files": [],
        "error": None,
        "created_at": time.time(),
        "params": params,
        "pause_reason": None,
        "workspace": source.get("workspace"),
        "out_dir": source.get("out_dir"),
        "llm_streaming": False,
        "_source_preview_pipeline_id": pid,
        "_source_preview_clip_indices": selected,
        "_source_preview_fingerprint": stored_fingerprint,
        "_preview_run_type": effective_run_type,
        "_comic_preflight_fingerprint": stored_fingerprint,
        "_preview_revision": source.get("_preview_revision", 1),
    }
    # Reserve the PRE revision atomically. The first check above avoids doing
    # needless copying, while this second check closes the race between two
    # browser tabs reaching child construction at the same time.
    with _pipeline_lock:
        active_children = [
            candidate
            for candidate in _pipelines.values()
            if candidate.get("_source_preview_pipeline_id") == pid
            and candidate.get("_source_preview_fingerprint")
            == stored_fingerprint
            and candidate.get("status") in _PRE_ACTIVE_CHILD_STATUSES
        ]
        for candidate in active_children:
            if (
                candidate.get("_source_preview_clip_indices") == selected
                and candidate.get("_preview_run_type") == effective_run_type
            ):
                return True, "already_running", candidate.get("id")
        if active_children:
            return (
                False,
                "Another generation from this PRE revision is active. Wait "
                "for it to finish or cancel it before starting different clips.",
                active_children[0].get("id"),
            )
        _pipelines[child_pid] = child

    if not _save_pipeline_state(child_pid):
        with _pipeline_lock:
            if _pipelines.get(child_pid) is child:
                _pipelines.pop(child_pid, None)
        return (
            False,
            "Could not save the generation checkpoint; no GPU work was started.",
            None,
        )
    thread = threading.Thread(
        target=_run_pipeline,
        args=(child_pid,),
        kwargs={"resume": True},
        daemon=False,
    )
    thread.start()
    return True, "started", child_pid


def update_comic_preview(
    pid: str,
    clips: Optional[list[dict]],
    out_dir: Optional[str] = None,
    expected_fingerprint: Optional[str] = None,
    approve_preview: bool = False,
    quality_waiver: bool = False,
    waiver_reason: str = "",
    accept_quality_test: bool = False,
) -> tuple[bool, str]:
    """Atomically apply durable PRE edits and rebuild prepared inputs.

    PRE edits never mutate the comic artwork.  Reframing starts from the
    pipeline's lossless source copies, then the complete frozen contract gets
    a new revision and fingerprint so an older browser tab cannot launch it.
    """
    with _pipeline_lock:
        source = _pipelines.get(pid)
    if not source and out_dir:
        recovered, message = resume_pipeline(pid, out_dir)
        if not recovered:
            return False, message
    with _pipeline_lock:
        source = _pipelines.get(pid)
        if not source:
            return False, "PRE pipeline not found."
        if source.get("status") != "preview_ready":
            return False, "The comic PRE is not ready for editing."
        active_child = next(
            (
                candidate
                for candidate in _pipelines.values()
                if candidate.get("_source_preview_pipeline_id") == pid
                and candidate.get("status") in _PRE_ACTIVE_CHILD_STATUSES
            ),
            None,
        )
        if active_child:
            return (
                False,
                "A test or film generation is using this PRE. Wait for it to "
                "finish or cancel it before changing, approving or waiving "
                "this revision.",
            )
        source = copy.deepcopy(source)
    stored_fingerprint = str(
        source.get("_comic_preflight_fingerprint")
        or (source.get("params") or {}).get("_comic_preflight_fingerprint")
        or ""
    )
    if stored_fingerprint and not expected_fingerprint:
        return False, "expected_fingerprint is required for every PRE change."
    if expected_fingerprint and str(expected_fingerprint) != stored_fingerprint:
        return False, "This PRE revision is stale; reload it before saving."
    normalized_waiver_reason = str(waiver_reason or "").strip()
    if quality_waiver and not normalized_waiver_reason:
        return (
            False,
            "A quality waiver requires a reason for the production record.",
        )
    if stored_fingerprint:
        current_fingerprint = _comic_preflight_fingerprint(
            source.get("params") or {},
            source.get("clip_plans") or [],
            source.get("_planned_clips") or [],
            source.get("clip_images") or [],
            source.get("out_dir") or out_dir,
        )
        if current_fingerprint != stored_fingerprint:
            return (
                False,
                "This PRE is stale because a source image or setting changed.",
            )

    def persist_metadata(updates: dict) -> tuple[bool, str]:
        """Commit gate/approval metadata or restore it when disk replace fails."""
        missing = object()
        with _pipeline_lock:
            live = _pipelines.get(pid)
            if (
                not live
                or live.get("status") != "preview_ready"
                or live.get("_comic_preflight_fingerprint")
                != stored_fingerprint
            ):
                return False, "PRE changed while metadata was being saved."
            previous = {
                key: (
                    copy.deepcopy(live[key])
                    if key in live
                    else missing
                )
                for key in updates
            }
            live.update(copy.deepcopy(updates))
        if _save_pipeline_state(pid):
            return True, ""

        rolled_back = False
        with _pipeline_lock:
            current = _pipelines.get(pid)
            if current and all(
                current.get(key) == value
                for key, value in updates.items()
            ):
                for key, value in previous.items():
                    if value is missing:
                        current.pop(key, None)
                    else:
                        current[key] = value
                rolled_back = True
        return (
            False,
            "Could not save PRE metadata; the change was rolled back."
            if rolled_back
            else (
                "Could not save PRE metadata and it changed concurrently. "
                "Reload PRE before continuing."
            ),
        )

    if accept_quality_test:
        gate = source.get("_quality_gate") or {}
        if (
            not stored_fingerprint
            or source.get("_preview_approved_fingerprint")
            != stored_fingerprint
        ):
            return False, "Approve this PRE revision before accepting its test."
        if (
            gate.get("fingerprint") != stored_fingerprint
            or gate.get("status") != "review_required"
        ):
            return (
                False,
                "All required test clips must pass automatic checks before "
                "visual acceptance.",
            )
        gate = {
            **gate,
            "status": "passed",
            "accepted_at": time.time(),
        }
        saved, message = persist_metadata({"_quality_gate": gate})
        if not saved:
            return False, message
        return True, "quality_test_accepted"
    if not clips and (approve_preview or quality_waiver):
        previews = source.get("preview_clips") or []
        if not stored_fingerprint or not previews:
            return False, "The PRE contract is incomplete and cannot be approved."
        blocked = [
            int(preview.get("index", index)) + 1
            for index, preview in enumerate(previews)
            if preview.get("included", True) is not False
            and preview.get("needs_reframe")
            and not (
                preview.get("reframe_approved")
                and preview.get("used_prepared_keyframe")
            )
        ]
        if approve_preview and blocked:
            return (
                False,
                "Shots "
                + ", ".join(str(value) for value in blocked)
                + " still need a real prepared reframe, Cover or Contain.",
            )
        was_approved = (
            source.get("_preview_approved_fingerprint")
            == stored_fingerprint
        )
        if quality_waiver and not (approve_preview or was_approved):
            return False, "Approve this PRE revision before waiving its test."
        required_test_indices = [
            int(preview.get("index", index))
            for index, preview in enumerate(previews)
            if preview.get("included", True) is not False
            and preview.get("test_selected")
        ]
        if not required_test_indices:
            first_enabled = next(
                (
                    int(preview.get("index", index))
                    for index, preview in enumerate(previews)
                    if preview.get("included", True) is not False
                ),
                None,
            )
            if first_enabled is not None:
                required_test_indices = [first_enabled]
        gate = {
            "status": "waived" if quality_waiver else "pending",
            "fingerprint": stored_fingerprint,
            "required_test_indices": required_test_indices,
            "tested_indices": [],
            "results": {},
            "failures": [],
        }
        if quality_waiver:
            gate.update({
                "waiver_reason": normalized_waiver_reason,
                "waived_at": time.time(),
            })
        saved, message = persist_metadata(
            {
                "_preview_approved_fingerprint": stored_fingerprint,
                "_quality_gate": gate,
            }
        )
        if not saved:
            return False, message
        return (
            True,
            "quality_test_waived" if quality_waiver else "preview_approved",
        )
    if not isinstance(clips, list) or not clips:
        return False, "clips must be a non-empty array."

    clip_plans = list(source.get("clip_plans") or [])
    planned_clips = list(source.get("_planned_clips") or [])
    params = copy.deepcopy(source.get("params") or {})
    shots = [
        item if isinstance(item, dict) else {}
        for item in (params.get("comic_shots") or [])
    ]
    source_images = list(source.get("_clip_source_images") or [])
    source_sizes = list(source.get("_clip_source_sizes") or [])
    fit_details = list(source.get("_clip_fit_details") or [])
    clip_images = list(source.get("clip_images") or [])
    keyframes = list(source.get("_clip_keyframes") or [])
    if not clip_plans or len(clip_images) != len(clip_plans):
        return False, "The PRE checkpoint has incomplete clip data."

    count = len(clip_plans)
    updates: dict[int, dict] = {}
    for item in clips:
        if not isinstance(item, dict):
            return False, "Every PRE clip update must be an object."
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            return False, "Every PRE clip update needs a valid index."
        if index < 0 or index >= count or index in updates:
            return False, "A PRE clip index is invalid or duplicated."
        updates[index] = item

    records: list[dict] = []
    for index in range(count):
        plan = copy.deepcopy(clip_plans[index])
        planned = copy.deepcopy(
            planned_clips[index] if index < len(planned_clips) else {}
        )
        shot = copy.deepcopy(shots[index] if index < len(shots) else {})
        edit = updates.get(index, {})

        if "included" in edit:
            shot["included"] = bool(edit["included"])
        renderer = str(edit.get("renderer") or _comic_renderer(
            params, index, plan
        )).strip().lower()
        if renderer not in {"hold", "parallax", "cinemagraph", "ltx"}:
            return False, f"Unsupported renderer for shot {index + 1}."
        shot["renderer"] = renderer
        plan["renderer"] = renderer

        if "prompt" in edit:
            prompt = " ".join(str(edit.get("prompt") or "").split())
            if not prompt and renderer in {"cinemagraph", "ltx"}:
                return False, f"Shot {index + 1} needs a motion prompt."
            previous_previews = source.get("preview_clips") or []
            previous_prompt = (
                " ".join(
                    str(previous_previews[index].get("prompt") or "").split()
                )
                if index < len(previous_previews)
                and isinstance(previous_previews[index], dict)
                else ""
            )
            # The cards submit their displayed effective prompt on every Save.
            # Treat it as a manual override only when the user actually changed
            # the text; otherwise camera/motion/renderer edits must be allowed
            # to re-compose the prompt from its undecorated story action.
            explicit_prompt_override = edit.get("prompt_override")
            if explicit_prompt_override is False:
                plan.pop("_preflight_prompt_override", None)
            elif bool(explicit_prompt_override) or prompt != previous_prompt:
                plan["_preflight_prompt_override"] = prompt[:1200]
        elif edit.get("prompt_override") is False:
            plan.pop("_preflight_prompt_override", None)
        elif edit.get("prompt_override") is True:
            return False, f"Shot {index + 1} needs the overridden prompt text."

        try:
            duration = float(
                edit.get(
                    "duration_seconds",
                    planned.get("duration_sec")
                    or planned.get("end", 3) - planned.get("start", 0),
                )
            )
        except (TypeError, ValueError):
            return False, f"Shot {index + 1} has an invalid duration."
        planned["duration_sec"] = max(0.8, min(20.0, duration))

        camera = str(
            edit.get("camera_move")
            or shot.get("camera_move")
            or shot.get("camera")
            or "none"
        ).strip().lower()
        shot["camera_move"] = camera
        plan["camera_move"] = camera

        fit_mode = str(
            edit.get("fit_mode")
            or shot.get("fit_mode")
            or params.get("video_image_fit")
            or "contain"
        ).strip().lower()
        fit_mode = {
            "crop": "cover",
            "smart": "contain",
            "preserve": "contain",
            "reframe-ai": "reframe",
        }.get(fit_mode, fit_mode)
        if fit_mode not in {"reframe", "cover", "contain"}:
            return False, f"Unsupported fit mode for shot {index + 1}."
        shot["fit_mode"] = fit_mode
        if "subject_focus" in edit:
            shot["subject_focus"] = copy.deepcopy(edit["subject_focus"])
        elif "focus" in edit:
            shot["subject_focus"] = copy.deepcopy(edit["focus"])
        previous_fit_detail = (
            copy.deepcopy(fit_details[index])
            if index < len(fit_details)
            and isinstance(fit_details[index], dict)
            else {}
        )
        previous_fit_mode = str(
            previous_fit_detail.get("requested_fit_mode")
            or _comic_shot(params, index).get("fit_mode")
            or params.get("video_image_fit")
            or "contain"
        ).strip().lower()
        previous_fit_mode = {
            "crop": "cover",
            "smart": "contain",
            "preserve": "contain",
            "reframe-ai": "reframe",
        }.get(previous_fit_mode, previous_fit_mode)
        existing_clip_name = (
            str(clip_images[index] or "")
            if index < len(clip_images)
            else ""
        )
        existing_clip_path = (
            existing_clip_name
            if os.path.isabs(existing_clip_name)
            else os.path.join(
                source.get("out_dir") or out_dir or "",
                existing_clip_name,
            )
        )
        needs_restage = bool(
            fit_mode != previous_fit_mode
            or "subject_focus" in edit
            or "focus" in edit
            or not os.path.isfile(existing_clip_path)
        )

        if "seed" in edit:
            try:
                seed = int(edit["seed"])
            except (TypeError, ValueError):
                return False, f"Shot {index + 1} has an invalid seed."
            if seed >= 0:
                shot["seed"] = seed
                plan["seed"] = seed
            else:
                shot.pop("seed", None)
                plan.pop("seed", None)
        if "test_selected" in edit:
            shot["test_selected"] = bool(edit["test_selected"])
        if "motion_level" in edit:
            try:
                motion_level = int(edit["motion_level"])
            except (TypeError, ValueError):
                return False, f"Shot {index + 1} has an invalid motion level."
            if motion_level < 0 or motion_level > 3:
                return (
                    False,
                    f"Shot {index + 1} motion level must be between 0 and 3.",
                )
        else:
            motion_level = _comic_motion_level(params, index, plan)
        if renderer == "hold":
            motion_level = 0
        elif renderer in {"parallax", "cinemagraph"}:
            motion_level = 1
        shot["motion_level"] = motion_level
        plan["motion_level"] = motion_level
        metadata = (
            dict(plan.get("metadata"))
            if isinstance(plan.get("metadata"), dict)
            else {}
        )
        metadata["motion_level"] = motion_level
        if motion_level <= 1:
            shot["camera_move"] = "none"
            plan["camera_move"] = "none"
            metadata["camera"] = "none"
            metadata["camera_move"] = "none"
        plan["metadata"] = metadata
        if "reframe_approved" in edit:
            prepared = str(
                shot.get("prepared_keyframe_path")
                or shot.get("video_keyframe_path")
                or ""
            )
            prepared_exists = bool(
                prepared
                and (
                    os.path.isfile(prepared)
                    or os.path.isfile(
                        os.path.join(
                            source.get("out_dir") or out_dir or "",
                            prepared,
                        )
                    )
                )
            )
            shot["reframe_approved"] = bool(
                edit["reframe_approved"] and prepared_exists
            )

        try:
            order = int(edit.get("order", index))
        except (TypeError, ValueError):
            order = index
        records.append({
            "old_index": index,
            "order": order,
            "plan": plan,
            "planned": planned,
            "shot": shot,
            "source_image": (
                source_images[index] if index < len(source_images) else ""
            ),
            "clip_image": clip_images[index],
            "source_size": (
                source_sizes[index] if index < len(source_sizes) else None
            ),
            "fit_detail": previous_fit_detail,
            "needs_restage": needs_restage,
            "keyframes": (
                copy.deepcopy(keyframes[index])
                if index < len(keyframes)
                else []
            ),
        })

    records.sort(key=lambda item: (item["order"], item["old_index"]))
    clip_plans = [item["plan"] for item in records]
    planned_clips = [item["planned"] for item in records]
    shots = [item["shot"] for item in records]
    keyframes = [item["keyframes"] for item in records]

    pipeline_out_dir = source.get("out_dir") or out_dir
    if not pipeline_out_dir:
        pipeline_out_dir = _wgp.save_path if _wgp else "outputs"
    safe_sources: list[str] = []
    for item in records:
        filename = str(item["source_image"] or "")
        path = (
            filename
            if os.path.isabs(filename)
            else os.path.join(pipeline_out_dir, filename)
        )
        if not os.path.isfile(path):
            return (
                False,
                "A lossless PRE source copy is missing. Rebuild PRE from the "
                "comic before changing its fit.",
            )
        safe_sources.append(path)

    for shot in shots:
        prepared = str(shot.get("prepared_keyframe_path") or "")
        if prepared and not os.path.isabs(prepared):
            candidate = os.path.join(pipeline_out_dir, prepared)
            if os.path.isfile(candidate):
                shot["prepared_keyframe_path"] = candidate

    params["comic_shots"] = shots
    params["provided_clip_image_paths"] = safe_sources
    params["video_image_fit"] = str(
        params.get("video_image_fit") or "contain"
    )
    params["_preview_revision"] = int(
        source.get("_preview_revision") or 1
    ) + 1

    cumulative = 0.0
    for planned in planned_clips:
        duration = float(planned.get("duration_sec") or 3.0)
        planned["start"] = cumulative
        planned["end"] = cumulative + duration
        cumulative += duration
    resolution = (params.get("video_params") or {}).get(
        "resolution", "1280x720"
    )
    new_images: list[str] = []
    new_source_images: list[str] = []
    new_source_sizes: list = []
    new_fit_details: list[dict] = []
    created_files: list[str] = []
    staging_pid = f"{pid}:preview-staging:{uuid.uuid4().hex[:8]}"
    try:
        for index, item in enumerate(records):
            source_filename = str(item["source_image"] or "")
            if item["needs_restage"]:
                (
                    staged,
                    staged_sources,
                    staged_sizes,
                    staged_fit,
                ) = _prepare_provided_clip_images(
                    staging_pid,
                    [safe_sources[index]],
                    expected_count=1,
                    out_dir=pipeline_out_dir,
                    resolution=resolution,
                    fit_mode=params["video_image_fit"],
                    protect_composition=True,
                    shots=[shots[index]],
                    reuse_source_filenames=[source_filename],
                    update_pipeline_state=False,
                    return_details=True,
                )
                new_images.append(staged[0])
                new_source_images.append(staged_sources[0])
                new_source_sizes.append(staged_sizes[0])
                new_fit_details.append(staged_fit[0])
                created_files.append(
                    os.path.join(pipeline_out_dir, staged[0])
                )
            else:
                new_images.append(str(item["clip_image"] or ""))
                new_source_images.append(source_filename)
                new_source_sizes.append(item["source_size"])
                detail = copy.deepcopy(item["fit_detail"] or {})
                detail["requested_fit_mode"] = shots[index].get(
                    "fit_mode",
                    detail.get("requested_fit_mode", "contain"),
                )
                if "reframe_approved" in shots[index]:
                    detail["reframe_approved"] = bool(
                        shots[index]["reframe_approved"]
                    )
                new_fit_details.append(detail)

        # Build the new frozen contract against an isolated staging pipeline.
        # The live PRE remains untouched until image preparation, prompt
        # composition and fingerprinting have all succeeded.
        with _pipeline_lock:
            _pipelines[staging_pid] = {
                "id": staging_pid,
                "status": "preview_staging",
                "params": params,
                "clip_plans": clip_plans,
                "_planned_clips": planned_clips,
                "clip_images": new_images,
                "_clip_source_images": new_source_images,
                "_clip_source_sizes": new_source_sizes,
                "_clip_fit_details": new_fit_details,
                "_preview_revision": params["_preview_revision"],
            }
        preview_clips, end_images = _build_comic_video_previews(
            staging_pid,
            params,
            clip_plans,
            planned_clips,
            new_images,
            out_dir=pipeline_out_dir,
        )
        fingerprint = str(
            (_pipelines.get(staging_pid) or {}).get(
                "_comic_preflight_fingerprint"
            )
            or params.get("_comic_preflight_fingerprint")
            or ""
        )
    except Exception as exc:
        for path in created_files:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
        with _pipeline_lock:
            _pipelines.pop(staging_pid, None)
        return False, f"Could not stage PRE changes safely: {exc}"
    finally:
        with _pipeline_lock:
            _pipelines.pop(staging_pid, None)

    approval_blocked = [
        int(preview.get("index", index)) + 1
        for index, preview in enumerate(preview_clips)
        if preview.get("included", True) is not False
        and preview.get("needs_reframe")
        and not (
            preview.get("reframe_approved")
            and preview.get("used_prepared_keyframe")
        )
    ]
    approval_allowed = bool(approve_preview and not approval_blocked)
    approved_fingerprint = fingerprint if approval_allowed else None
    required_test_indices = [
        int(preview["index"])
        for preview in preview_clips
        if preview.get("included", True) is not False
        and preview.get("test_selected")
    ]
    if approve_preview and not required_test_indices:
        first_enabled = next(
            (
                int(preview["index"])
                for preview in preview_clips
                if preview.get("included", True) is not False
            ),
            None,
        )
        if first_enabled is not None:
            required_test_indices = [first_enabled]
    effective_quality_waiver = bool(quality_waiver and approval_allowed)
    quality_gate = {
        "status": "waived" if effective_quality_waiver else "pending",
        "fingerprint": fingerprint,
        "required_test_indices": required_test_indices,
        "tested_indices": [],
        "results": {},
        "failures": [],
    }
    if effective_quality_waiver:
        quality_gate.update({
            "waiver_reason": normalized_waiver_reason,
            "waived_at": time.time(),
        })
    with _pipeline_lock:
        live = _pipelines.get(pid)
        if (
            not live
            or live.get("status") != "preview_ready"
            or live.get("_comic_preflight_fingerprint")
            != stored_fingerprint
        ):
            for path in created_files:
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass
            return False, "PRE changed while edits were being staged; reload it."
        live.update({
            "params": params,
            "clip_plans": clip_plans,
            "_planned_clips": planned_clips,
            "clip_images": new_images,
            "_clip_source_images": new_source_images,
            "_clip_source_sizes": new_source_sizes,
            "_clip_fit_details": new_fit_details,
            "_clip_keyframes": keyframes,
            "_clip_end_images": end_images,
            "_clip_video_files": [None] * count,
            "_clip_validations": [None] * count,
            "_preview_revision": params["_preview_revision"],
            "_comic_preflight_fingerprint": fingerprint,
            "preview_clips": preview_clips,
            "_preview_approved_fingerprint": approved_fingerprint,
            "_quality_gate": quality_gate,
            "progress": {
                "current": len(preview_clips),
                "total": len(preview_clips),
                "message": (
                    "Comic PRE changes saved — review before generation"
                ),
                "step": 0,
                "total_steps": 0,
            },
        })
    if not _save_pipeline_state(pid):
        rolled_back = False
        with _pipeline_lock:
            current = _pipelines.get(pid)
            if (
                current
                and current.get("_comic_preflight_fingerprint")
                == fingerprint
            ):
                current.clear()
                current.update(copy.deepcopy(source))
                rolled_back = True
        if rolled_back:
            for path in created_files:
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                except OSError:
                    pass
        return (
            False,
            "Could not save the PRE checkpoint; all edits were rolled back."
            if rolled_back
            else (
                "Could not save the PRE checkpoint, and PRE changed "
                "concurrently. Reload it before continuing."
            ),
        )

    # Only after the atomic swap may superseded prepared panels be removed.
    # Lossless comic_source_* files are deliberately retained and reused.
    new_image_set = {str(value) for value in new_images}
    for old_name in clip_images:
        old_name = str(old_name or "")
        if old_name in new_image_set:
            continue
        basename = os.path.basename(old_name)
        if not basename.startswith("comic_panel_"):
            continue
        old_path = os.path.join(pipeline_out_dir, basename)
        try:
            if os.path.isfile(old_path):
                os.remove(old_path)
        except OSError:
            pass
    if approve_preview and approval_blocked:
        return (
            True,
            "updated_approval_blocked: shots "
            + ", ".join(str(value) for value in approval_blocked)
            + " cannot be approved until they use Cover, Contain or a real "
              "prepared reframe.",
        )
    return True, "updated"


def _find_pipeline_state_file(pid: str, out_dir: str) -> Optional[str]:
    """Locate a saved pipeline JSON by id under out_dir or a workspace subdir."""
    fname = f"{_PIPELINE_FILE_PREFIX}{pid}.json"
    candidates = [os.path.join(out_dir, fname)]
    try:
        for name in os.listdir(out_dir):
            sub = os.path.join(out_dir, name)
            if os.path.isdir(sub):
                candidates.append(os.path.join(sub, fname))
    except OSError:
        pass
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def resume_pipeline(pid: str, out_dir: str) -> tuple[bool, str]:
    """Rehydrate a crashed pipeline from disk and re-run it.

    Reuses the planning (and start images, when their files still exist)
    that completed before the crash; only the video phase re-runs. Returns
    (ok, message). Requires a state file that carries the full params
    snapshot (written since the resume feature shipped) — older crash files
    can't be resumed faithfully and report so.
    """
    with _pipeline_lock:
        existing = _pipelines.get(pid)
        if existing and existing.get("status") in ("running", "queued", "planning"):
            return False, "Pipeline is already running."

    state_path = _find_pipeline_state_file(pid, out_dir)
    if not state_path:
        return False, "No saved state found for this pipeline."
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, f"Could not read saved pipeline state: {e}"
    data = _reconcile_pipeline_state_file(state_path, data)

    params = data.get("_params_snapshot")
    if not isinstance(params, dict):
        return False, (
            "This pipeline was created before resume support and can't be "
            "resumed — start a new generation."
        )

    # Rebuild the generation-driving structures from the saved per-clip state.
    saved_clips = data.get("clips", []) or []
    flattened_clip_plans = [{
        "image_prompt": c.get("image_prompt", ""),
        "video_prompt": c.get("video_prompt", ""),
        "visual_changes": c.get("visual_changes", []) or [],
        "image_source": c.get("image_source", "original"),
        "keyframe_prompts": c.get("keyframe_prompts", []) or [],
        "window_prompts": c.get("window_prompts", []) or [],
        "window_count": c.get("window_count", 1),
        "_effective_video_prompt": c.get("effective_video_prompt"),
        "_effective_video_frames": c.get("effective_video_frames"),
        "shot_id": c.get("shot_id"),
        "seed": c.get("seed"),
        "renderer": c.get("renderer"),
    } for c in saved_clips]
    clip_plans = (
        copy.deepcopy(data.get("clip_plans"))
        if isinstance(data.get("clip_plans"), list)
        and len(data.get("clip_plans")) == len(saved_clips)
        else flattened_clip_plans
    )
    flattened_planned_clips = []
    for clip in saved_clips:
        planned = clip.get("planned_clip") or {}
        if clip.get("effective_video_frames"):
            planned["_effective_video_frames"] = clip["effective_video_frames"]
        flattened_planned_clips.append(planned)
    planned_clips = (
        copy.deepcopy(data.get("planned_clips"))
        if isinstance(data.get("planned_clips"), list)
        and len(data.get("planned_clips")) == len(saved_clips)
        else flattened_planned_clips
    )
    clip_images = [c.get("start_image_filename") for c in saved_clips]
    clip_source_images = [c.get("source_image_filename") for c in saved_clips]
    clip_end_images = [c.get("end_image_filename") for c in saved_clips]
    clip_keyframes = [c.get("keyframe_filenames", []) or [] for c in saved_clips]
    clip_video_files = [c.get("video_filename") for c in saved_clips]

    workspace = data.get("workspace") if data.get("workspace") not in ("default", None) else None
    resume_out_dir = os.path.dirname(state_path)

    pipeline = {
        "id": pid,
        "status": "running",
        "phase": "resuming",
        "auto_mode": params.get("auto_mode", True),
        "progress": {"current": 0, "total": 0, "message": "Resuming…", "step": 0, "total_steps": 0},
        "clip_plans": clip_plans,
        "_planned_clips": planned_clips,
        "clip_images": clip_images,
        "_clip_source_images": clip_source_images,
        "_clip_source_sizes": (
            data.get("clip_source_sizes")
            or [c.get("source_size") for c in saved_clips]
        ),
        "_clip_fit_details": (
            data.get("clip_fit_details")
            or [c.get("fit_details") or {} for c in saved_clips]
        ),
        "_clip_end_images": clip_end_images,
        "_clip_keyframes": clip_keyframes,
        "_clip_video_files": clip_video_files,
        "_clip_validations": [
            c.get("validation") for c in saved_clips
        ],
        "_comic_preflight_fingerprint": data.get("preview_fingerprint"),
        "_preview_revision": data.get("preview_revision", 1),
        "_preview_approved_fingerprint": data.get(
            "preview_approved_fingerprint"
        ),
        "_quality_gate": data.get("quality_gate") or {
            "status": "pending",
            "fingerprint": data.get("preview_fingerprint"),
            "required_test_indices": [],
            "tested_indices": [],
            "results": {},
            "failures": [],
        },
        "preview_clips": data.get("preview_clips", []) or [],
        "h3_reference_manifest": data.get("h3_reference_manifest", []) or [],
        "h3_prompt_validation": data.get("h3_prompt_validation"),
        "output_files": data.get("output_files", []) or [],
        "_llm_log": data.get("llm_log"),
        "error": None,
        "created_at": data.get("created_at") or time.time(),
        "params": params,
        "pause_reason": None,
        "workspace": workspace,
        "out_dir": resume_out_dir,
        "llm_streaming": False,
        "_source_preview_pipeline_id": params.get(
            "_source_preview_pipeline_id"
        ),
        "_source_preview_clip_indices": params.get(
            "_source_preview_clip_indices"
        ),
        "_source_preview_fingerprint": params.get(
            "_source_preview_fingerprint"
        ),
        "_preview_run_type": params.get("_preview_run_type"),
    }
    with _pipeline_lock:
        _pipelines[pid] = pipeline

    if data.get("status") == "preview_ready" and data.get("preview_clips"):
        _update_pipeline(
            pid,
            status="preview_ready",
            phase="preview_ready",
            progress={
                "current": len(data["preview_clips"]),
                "total": len(data["preview_clips"]),
                "message": "Recovered comic PRE — no video has been generated",
                "step": 0,
                "total_steps": 0,
            },
        )
        return True, "recovered_preview"

    if data.get("status") == "completed" and data.get("output_files"):
        _update_pipeline(
            pid,
            status="completed",
            phase="completed",
            _completed_at=data.get("completed_at") or time.time(),
            progress={
                "current": len(saved_clips),
                "total": len(saved_clips),
                "message": "Recovered completed movie",
                "step": 0,
                "total_steps": 0,
            },
        )
        return True, "recovered"

    thread = threading.Thread(target=_run_pipeline, args=(pid,), kwargs={"resume": True}, daemon=False)
    thread.start()
    return True, "resumed"


def stop_pipeline(pid: str):
    active_job_id = None
    with _pipeline_lock:
        p = _pipelines.get(pid)
        if p:
            p["_cancel_requested"] = True
            active_job_id = p.get("_active_generation_job_id")
            if active_job_id:
                # Do not publish a terminal pipeline state until the
                # generation worker confirms that it released the GPU.
                p["status"] = "running"
                p["phase"] = "cancelling"
                progress = dict(p.get("progress") or {})
                progress["message"] = "Cancelling active generation…"
                p["progress"] = progress
            else:
                p["status"] = "cancelled"
                p["phase"] = "cancelled"
    _save_pipeline_state(pid)
    if active_job_id and _cancel_generation is not None:
        _cancel_generation(active_job_id)
    return "cancelling" if active_job_id else "cancelled"


def _run_pipeline(pid: str, resume: bool = False):
    """Main pipeline thread — runs the full Director flow.

    When resume=True the pipeline was rehydrated from a crashed state
    (see resume_pipeline): planning + prompt-polish are skipped when the
    saved clip_plans are present, and start-image generation is skipped
    when the saved images still exist on disk. Only the (atomic) video
    generation phase re-runs — so a crash 2 hours into a run doesn't
    throw away the LLM planning that already succeeded.
    """
    try:
        p = _pipelines[pid]
        params = p["params"]
        pipeline_out_dir = p.get("out_dir") or _wgp.save_path
        pipeline_workspace = p.get("workspace")

        # Work already completed before a crash (empty on a fresh run).
        resume_plans = (p.get("clip_plans") or None) if resume else None
        resume_images = (p.get("clip_images") or None) if resume else None

        pipeline_type = params.get("pipeline_type", "music_video")  # music_video | short_film_audio | short_film_story
        auto_mode = params.get("auto_mode", True)

        # ── Disk preflight ─────────────────────────────────────────────
        # A Director run writes gigabytes (per-clip images + video + the
        # final concat). Fail fast with a clear message instead of dying
        # halfway through with a truncated "No space left on device" write.
        try:
            import shutil as _shutil
            free_gb = _shutil.disk_usage(pipeline_out_dir).free / (1024 ** 3)
            if free_gb < 3:
                raise RuntimeError(
                    f"Only {free_gb:.1f} GB free on the output drive — not "
                    f"enough for a Director run. Free up space and try again."
                )
        except RuntimeError:
            raise
        except Exception:
            pass  # disk_usage can fail on odd mounts; don't block on the check itself

        # ── Wait for GPU if jobs are running ────────────────────────────
        # LLM needs GPU (CUDA), so we must wait for generation queue to drain.
        # In auto mode this is expected (fire-and-forget). In non-auto mode
        # the user is waiting interactively, so we still wait but they can cancel.
        if not _wait_for_gpu(pid):
            return  # cancelled while waiting

        # ── Phase 1: LLM Planning ──────────────────────────────────────
        _update_pipeline(pid, phase="planning", llm_streaming=True,
                         progress={"current": 0, "total": 1, "message": "Planning with LLM...", "step": 0, "total_steps": 0})

        planning_start = time.time()
        if resume_plans:
            # Reuse the planning that already succeeded before the crash.
            clip_plans = resume_plans
            planned_clips = p.get("_planned_clips") or []
            print(f"[Pipeline {pid}] Resume: reusing {len(clip_plans)} planned clips — skipping LLM planning + polish")
        else:
            try:
                clip_plans, planned_clips = _run_planning(pid, params, pipeline_type)
            except Exception as plan_err:
                print(f"[Pipeline] Planning error: {plan_err}")
                import traceback
                traceback.print_exc()
                raise
        planning_time = time.time() - planning_start

        if not clip_plans:
            raise RuntimeError("Planning produced no clip plans")

        # Store planned clips for persistence
        _update_pipeline(pid, _planned_clips=planned_clips)

        # Capture LLM logs — collect all passes from the pipeline's accumulated log
        try:
            from services import llm_service
            # The pipeline accumulates logs via _append_llm_log during planning
            accumulated = _pipelines.get(pid, {}).get("_llm_passes", [])
            # Also capture the final state as a fallback
            if not accumulated:
                accumulated = [{
                    "pass": "planning",
                    "system_prompt": getattr(llm_service, '_last_system_prompt', '') or '',
                    "user_prompt": getattr(llm_service, '_last_user_prompt', '') or '',
                    "response_text": getattr(llm_service, '_stream_buffer', '') or '',
                    "thinking_text": getattr(llm_service, '_last_thinking_text', None),
                }]
            llm_log = {
                "provider": (
                    params.get("writing_provider")
                    if params.get("writing_provider") not in (None, "", "maestro")
                    else params.get("llm_provider", "local")
                ),
                "model_id": (
                    params.get("writing_model")
                    if params.get("writing_provider") not in (None, "", "maestro")
                    else params.get("llm_model_id", "")
                ),
                "passes": accumulated,
                # Keep flat fields for backward compat — use last pass
                "system_prompt": accumulated[-1].get("system_prompt", "") if accumulated else "",
                "response_text": accumulated[-1].get("response_text", "") if accumulated else "",
                "thinking_text": accumulated[-1].get("thinking_text") if accumulated else None,
                "planning_time_sec": round(planning_time, 2),
            }
            # On resume, keep the rehydrated original log instead of clobbering
            # it with an empty re-capture (there was no fresh planning stream).
            if not resume_plans:
                _update_pipeline(pid, _llm_log=llm_log)
        except Exception:
            pass

        # ── Optional: Third-pass prompt polish ────────────────────────
        services = _wgp.server_config.get("services", {}) if _wgp else {}
        # Default "third_pass" — Pass 3 polish runs each generated prompt
        # through a model-specific dialect pass after planning, which
        # produces materially better output than relying on Pass 2 alone
        # with a single hardcoded dialect.
        polish_mode = services.get("director_prompt_polish", "third_pass")

        # Snapshot pre-polish prompts for comparison
        import copy
        _update_pipeline(pid, _clip_plans_pre_polish=copy.deepcopy(clip_plans))

        # On resume the saved clip_plans are ALREADY polished — re-polishing
        # would compound edits and drift the prompts, so skip the whole block.
        scoped_writing_provider = str(
            params.get("writing_provider") or "maestro"
        ).strip().lower() not in ("", "maestro", "internal", "local")
        if resume_plans:
            pass
        elif (
            polish_mode == "third_pass"
            and clip_plans
            and pipeline_type != "comic_movie"
            and not scoped_writing_provider
        ):
            _update_pipeline(pid, phase="polishing_prompts", llm_streaming=False,
                             progress={"current": 0, "total": len(clip_plans), "message": "Polishing prompts (3rd pass)...", "step": 0, "total_steps": 0})
            try:
                from services.director.prompt_polish import polish_prompts_third_pass
                provider = services.get("llm_provider", "local")
                nsfw = services.get("nsfw_mode", False) and provider not in {"openai", "anthropic"}
                video_model = params.get("video_model", "")
                image_model = params.get("image_model", "")
                video_loras = (params.get("video_loras") or {}).get("activated_loras", [])
                image_loras = (params.get("image_loras") or {}).get("activated_loras", [])
                ref_paths = []
                rip = params.get("reference_image_path")
                if rip:
                    ref_paths.append(rip)
                for cp in (params.get("character_ref_paths") or []):
                    if cp:
                        ref_paths.append(cp)
                # Pass character profiles into polish so the LLM has a
                # definitive name → descriptor mapping. Without this, polish
                # silently substitutes generic "the woman" / "the man" for
                # any character name it encounters — catastrophic for
                # non-human characters (Lumi the unicorn became "the woman"
                # in test 03). characters comes from params.characters,
                # the same list passed to the planner.
                characters = params.get("characters", []) or []
                clip_plans = polish_prompts_third_pass(
                    clip_plans, video_model, image_model, nsfw,
                    video_loras=video_loras, image_loras=image_loras,
                    image_paths=ref_paths or None,
                    characters=characters,
                )
                _capture_llm_pass(pid, "third_pass_polish")
                print(f"[Pipeline] Third-pass polish completed for {len(clip_plans)} clips")
            except Exception as e:
                print(f"[Pipeline] Prompt polish failed (non-fatal): {e}")
        elif polish_mode in ("full_guide", "light_guide"):
            # For inject modes, polish happened inside the planner — note it in the log
            _update_pipeline(pid, _polish_mode_used=polish_mode)
        elif scoped_writing_provider:
            # The selected Story/Comic provider already wrote the final prompts.
            # Do not silently run the global Maestro LLM as a second author.
            _update_pipeline(pid, _polish_mode_used="scoped_writing_provider")

        # Prompt polish is allowed to improve model dialect, never to erase the
        # Story's authored medium.  This deterministic final pass also covers
        # remote writing providers, for which third-pass polish is skipped.
        from services.director.policies import enforce_visual_style_on_clip_plans
        clip_plans = enforce_visual_style_on_clip_plans(
            clip_plans,
            params.get("visual_style", ""),
            preserve=bool(params.get("preserve_visual_style", False)),
            has_reference=_has_visual_references(params),
        )
        _update_pipeline(pid, clip_plans=clip_plans, llm_streaming=False)
        _save_pipeline_state(pid)  # Save after planning

        # Check cancellation
        if _pipelines[pid]["status"] == "cancelled":
            return

        # In non-auto mode, pause for user review after planning
        if not auto_mode:
            _update_pipeline(pid, status="paused", pause_reason="review_prompts",
                             progress={"current": 1, "total": 3, "message": "Review prompts", "step": 0, "total_steps": 0})
            _save_pipeline_state(pid)  # Save paused state so Dashboard shows it
            _wait_for_resume(pid)
            if _pipelines[pid]["status"] == "cancelled":
                return
            # Reload clip_plans in case user edited them
            clip_plans = _pipelines[pid]["clip_plans"]
            clip_plans = enforce_visual_style_on_clip_plans(
                clip_plans,
                params.get("visual_style", ""),
                preserve=bool(params.get("preserve_visual_style", False)),
                has_reference=_has_visual_references(params),
            )
            _update_pipeline(pid, clip_plans=clip_plans)

        # H3 consumes shorter temporal segments than the Story planner writes.
        # Validate the exact post-split prompts while the selected writing LLM
        # is still available, then unload it before image/video generation.
        if not resume_plans and params.get("video_model") == "minimax_h3":
            _update_pipeline(
                pid,
                phase="validating_h3_prompts",
                llm_streaming=False,
                progress={
                    "current": 0,
                    "total": len(clip_plans),
                    "message": "Validating prompts for MiniMax H3...",
                    "step": 0,
                    "total_steps": 0,
                },
            )
            try:
                clip_plans = _optimize_minimax_h3_story_prompts(
                    pid,
                    params,
                    clip_plans,
                    planned_clips,
                )
                _update_pipeline(
                    pid,
                    clip_plans=clip_plans,
                    h3_prompt_validation={
                        "status": "optimized",
                        "segments": sum(
                            len(plan.get("h3_segment_prompts") or [])
                            for plan in clip_plans
                        ),
                    },
                )
            except Exception as error:
                print(f"[Pipeline] H3 prompt validation failed; using deterministic prompts: {error}")
                for plan in clip_plans:
                    metadata = plan.setdefault("metadata", {})
                    if isinstance(metadata, dict):
                        metadata["h3_prompt_validation"] = "deterministic_fallback"
                _update_pipeline(
                    pid,
                    clip_plans=clip_plans,
                    h3_prompt_validation={
                        "status": "deterministic_fallback",
                        "error": str(error),
                    },
                )
            _save_pipeline_state(pid)

        # ── Phase 2: Prepare or Generate Start Images ────────────────────
        # Normal Director productions generate start frames here. Comic
        # movies already have one approved artwork image per shot, so those
        # files are copied into the recoverable pipeline output directory and
        # fed directly to I2V without spending image-generation credits.
        provided_clip_image_paths = params.get("provided_clip_image_paths") or []
        _update_pipeline(pid, phase="generating_images",
                         progress={
                             "current": 0,
                             "total": len(clip_plans),
                             "message": "Preparing comic panels..." if provided_clip_image_paths else "Generating start images...",
                             "step": 0,
                             "total_steps": 0,
                         })

        # Unload LLM to free VRAM
        from services import llm_service
        try:
            if llm_service.is_loaded():
                llm_service.unload_model()
        except Exception as e:
            print(f"[Pipeline] LLM unload warning (non-fatal): {e}")

        # On resume, reuse the start images that already generated before the
        # crash — but only if every file still exists (a wiped/half-written
        # output dir falls back to regenerating them, which is safer than
        # feeding missing paths into video generation).
        _resume_imgs_ok = bool(resume_images) and all(
            f and os.path.isfile(os.path.join(pipeline_out_dir, f)) for f in resume_images
        )
        if _resume_imgs_ok:
            clip_images = resume_images
            clip_keyframes = p.get("_clip_keyframes") or [[] for _ in clip_images]
            print(f"[Pipeline {pid}] Resume: reusing {len(clip_images)} start images — skipping image generation")
        elif provided_clip_image_paths:
            video_params = dict(params.get("video_params") or {})
            video_params["resolution"] = _normalize_video_resolution(
                params.get("video_model", ""),
                video_params.get("resolution", "1280x720"),
            )
            params["video_params"] = video_params
            (
                clip_images,
                durable_source_names,
                source_sizes,
                fit_details,
            ) = _prepare_provided_clip_images(
                pid,
                provided_clip_image_paths,
                expected_count=len(clip_plans),
                out_dir=pipeline_out_dir,
                resolution=video_params["resolution"],
                fit_mode=params.get("video_image_fit", "contain"),
                protect_composition=params.get("pipeline_type") == "comic_movie",
                shots=params.get("comic_shots") or [],
                return_details=True,
            )
            # The browser upload may live in a temporary directory. PRE must
            # fingerprint and persist the lossless copies beside its checkpoint
            # so a restart or upload cleanup cannot make an approved contract
            # spuriously stale.
            params["provided_clip_image_paths"] = [
                (
                    name
                    if os.path.isabs(str(name or ""))
                    else os.path.join(pipeline_out_dir, str(name or ""))
                )
                for name in durable_source_names
            ]
            _update_pipeline(
                pid,
                params=params,
                _clip_source_images=durable_source_names,
                _clip_source_sizes=source_sizes,
                _clip_fit_details=fit_details,
            )
            clip_keyframes = [[] for _ in clip_images]
        else:
            if resume_images:
                print(f"[Pipeline {pid}] Resume: saved start images missing on disk — regenerating")
            clip_images, clip_keyframes = _run_image_generation(pid, params, clip_plans, out_dir=pipeline_out_dir, workspace=pipeline_workspace)

        _update_pipeline(pid, clip_images=clip_images, _clip_keyframes=clip_keyframes)
        _save_pipeline_state(pid)  # Save after image generation

        if _pipelines[pid]["status"] == "cancelled":
            return

        if params.get("comic_preflight_only"):
            preview_clips, prepared_end_images = _build_comic_video_previews(
                pid,
                params,
                clip_plans,
                planned_clips,
                clip_images,
                out_dir=pipeline_out_dir,
            )
            _update_pipeline(
                pid,
                status="preview_ready",
                phase="preview_ready",
                preview_clips=preview_clips,
                _clip_end_images=prepared_end_images,
                progress={
                    "current": len(preview_clips),
                    "total": len(preview_clips),
                    "message": "Comic PRE ready — no video has been generated",
                    "step": 0,
                    "total_steps": 0,
                },
            )
            _save_pipeline_state(pid)
            return

        # In non-auto mode, pause for image review
        if not auto_mode:
            _update_pipeline(pid, status="paused", pause_reason="review_images",
                             progress={"current": 2, "total": 3, "message": "Review images", "step": 0, "total_steps": 0})
            _wait_for_resume(pid)
            if _pipelines[pid]["status"] == "cancelled":
                return

        # ── Phase 3: Generate Video ─────────────────────────────────────
        _update_pipeline(pid, phase="generating_video",
                         progress={"current": 0, "total": 1, "message": "Generating video...", "step": 0, "total_steps": 0})

        output_files = _run_video_generation(pid, params, clip_plans, planned_clips, clip_images, clip_keyframes, out_dir=pipeline_out_dir, workspace=pipeline_workspace)

        if _pipeline_cancel_requested(pid):
            raise PipelineCancelled("Director pipeline was cancelled.")

        _update_pipeline(pid,
                         status="completed",
                         phase="completed",
                         output_files=output_files,
                         _completed_at=time.time(),
                         progress={"current": 3, "total": 3, "message": "Done!", "step": 0, "total_steps": 0})
        _save_pipeline_state(pid)  # Save on completion

    except PipelineCancelled:
        _update_pipeline(
            pid,
            status="cancelled",
            phase="cancelled",
            _completed_at=time.time(),
            progress={
                "current": 0,
                "total": 0,
                "message": "Cancelled",
                "step": 0,
                "total_steps": 0,
            },
        )
        _save_pipeline_state(pid)
        return
    except Exception as e:
        import traceback
        # Special-case the safety scanner. Don't print a stack trace for
        # safety violations — they're a clean refusal, not a crash, and
        # the user-visible message is purpose-built. Other exceptions
        # keep the existing traceback dump for debugging.
        try:
            from services.director.safety_scan import SafetyViolationError
        except Exception:
            SafetyViolationError = None  # type: ignore
        if SafetyViolationError is not None and isinstance(e, SafetyViolationError):
            print(
                f"[Pipeline {pid}] Safety scan blocked generation. "
                f"source={e.source} matched={e.matched_terms}"
            )
            user_msg = (
                "Generation aborted: the input contained content involving "
                f"minors in a prohibited context (matched terms: "
                f"{', '.join(e.matched_terms)}). The system refuses to "
                f"generate this category of content. Please revise your "
                f"concept to use only adult characters (18+)."
            )
            _update_pipeline(
                pid, status="failed", error=user_msg,
                _completed_at=time.time(),
                progress={"current": 0, "total": 0,
                          "message": "Generation aborted (safety policy)",
                          "step": 0, "total_steps": 0},
            )
            _save_pipeline_state(pid)
            return
        traceback.print_exc()
        # Tag with OOM info if applicable so the UI can surface the
        # OOM recovery banner. detect_oom returns None for non-OOM
        # failures, in which case oom_info stays absent.
        _oom_info = None
        try:
            from services.oom_detect import detect_oom
            import wgp as _wgp_mod
            _coef = float(_wgp_mod.server_config.get("vram_safety_coefficient", 0.80))
            _oom_info = detect_oom(e, _coef)
        except Exception:
            pass  # Never fail a failure handler
        _update_pipeline(pid, status="failed", error=str(e),
                         oom_info=_oom_info,
                         _completed_at=time.time(),
                         progress={"current": 0, "total": 0, "message": f"Error: {e}", "step": 0, "total_steps": 0})
        failed_pipeline = _pipelines.get(pid) or {}
        if (
            failed_pipeline.get("_preview_run_type") == "test"
            and not failed_pipeline.get("_quality_recorded")
        ):
            safe_error = " ".join(str(e).split())
            for sensitive_path in (
                failed_pipeline.get("out_dir"),
                os.path.expanduser("~"),
            ):
                if sensitive_path:
                    safe_error = safe_error.replace(
                        str(sensitive_path),
                        "[path]",
                    )
            safe_error = safe_error[:400] or "generation-failed"
            selected = list(
                failed_pipeline.get("_source_preview_clip_indices") or []
            )
            _record_comic_preview_quality(
                pid,
                [
                    {
                        "passed": False,
                        "failures": [f"generation-failed:{safe_error}"],
                        "warnings": [],
                        "metrics": {
                            "child_pipeline_id": pid,
                            "phase": failed_pipeline.get("phase"),
                        },
                    }
                    for _index in selected
                ],
            )
        _save_pipeline_state(pid)  # Save on failure too


def _wait_for_resume(pid: str, poll_interval: float = 1.0):
    """Block until pipeline is resumed, cancelled, or removed."""
    while True:
        with _pipeline_lock:
            p = _pipelines.get(pid)
            if not p:
                return
            if p["status"] != "paused":
                return
        time.sleep(poll_interval)


def _wait_for_gpu(pid: str, poll_interval: float = 2.0):
    """Block until no generation jobs are actively running on GPU.

    Checks both _gen_lock availability and active job statuses.
    Returns False if pipeline was cancelled while waiting.
    """
    _update_pipeline(pid, progress={
        "current": 0, "total": 1,
        "message": "Waiting for GPU (generation queue)...",
        "step": 0, "total_steps": 0,
    })

    while True:
        if _pipelines.get(pid, {}).get("status") == "cancelled":
            return False

        # Check if any jobs are currently running
        active_jobs = [j for j in _jobs.values()
                       if j.get("status") in ("queued", "running")]
        if not active_jobs:
            return True

        time.sleep(poll_interval)


# ── Planning Phase ──────────────────────────────────────────────────────

def _ensure_llm_loaded(params: dict):
    """Load/reload LLM if needed. Shared between legacy and new planning."""
    from . import llm_service

    services_cfg = _wgp.server_config.get("services", {}) if _wgp else {}
    desired_model = params.get("llm_model_id") or services_cfg.get("llm_model_id", "Abhiray/gemma-4-E4B-it-heretic-GGUF")
    desired_device = params.get("llm_device") or services_cfg.get("llm_device", "cpu")
    desired_provider = params.get("llm_provider") or services_cfg.get("llm_provider", "local")
    desired_remote_url = services_cfg.get("llm_remote_url", "")
    desired_api_key = ""
    if desired_provider == "openai":
        desired_api_key = services_cfg.get("openai_api_key", "")
    elif desired_provider == "anthropic":
        desired_api_key = services_cfg.get("anthropic_api_key", "")

    if llm_service.is_loaded():
        status = llm_service.get_status()
        if status.get("model_id") != desired_model or status.get("provider") != desired_provider:
            llm_service.unload_model()
            llm_service.load_model(model_id=desired_model, device=desired_device, provider=desired_provider, remote_url=desired_remote_url, api_key=desired_api_key)
    else:
        llm_service.load_model(model_id=desired_model, device=desired_device, provider=desired_provider, remote_url=desired_remote_url, api_key=desired_api_key)


def _scoped_writing_llm(params: dict) -> dict | None:
    """Resolve a Story/Comic production-only writing provider.

    Credentials always come from the trusted server settings.  The browser
    sends only the profile name, model and (for the custom profile) the URL it
    expects; this keeps API keys out of comic/story files and pipeline state.
    """
    provider = str(
        params.get("writing_provider")
        or params.get("writingProvider")
        or "maestro"
    ).strip().lower()
    if provider in ("", "maestro", "internal", "local"):
        return None
    if provider not in ("deepseek", "minimax", "openai", "openai-compatible"):
        raise RuntimeError("Unsupported production writing provider")

    services = _wgp.server_config.get("services", {}) if _wgp else {}
    requested_url = str(
        params.get("writing_base_url")
        or params.get("writingBaseUrl")
        or ""
    ).strip()[:1000]
    requested_model = str(
        params.get("writing_model")
        or params.get("writingModel")
        or ""
    ).strip()[:200]

    if provider == "openai-compatible":
        from urllib.parse import urlparse
        legacy_host = (urlparse(requested_url).hostname or "").lower()
        if legacy_host == "api.deepseek.com":
            provider = "deepseek"
        elif legacy_host == "api.openai.com":
            provider = "openai"

    if provider == "deepseek":
        model = requested_model or "deepseek-v4-pro"
        if model in ("deepseek-chat", "deepseek-reasoner"):
            model = "deepseek-v4-pro"
        if model not in {"deepseek-v4-pro", "deepseek-v4-flash"}:
            raise RuntimeError("Choose DeepSeek V4 Pro or V4 Flash")
        base_url = "https://api.deepseek.com"
        api_key = str(services.get("deepseek_api_key") or "")
        missing = "Configure the DeepSeek API key in Settings → Services first"
    elif provider == "minimax":
        model = requested_model or "MiniMax-M3"
        if model not in {"MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"}:
            raise RuntimeError("Choose MiniMax M3, M2.7, or M2.7 Highspeed")
        base_url = "https://api.minimax.io/v1"
        api_key = str(services.get("minimax_api_key") or "")
        missing = "Configure the MiniMax API key in Settings → Services first"
    elif provider == "openai":
        model = requested_model or "gpt-4.1"
        base_url = "https://api.openai.com"
        api_key = str(services.get("openai_api_key") or "")
        missing = "Configure the OpenAI API key in Settings → Services first"
    else:
        model = requested_model
        base_url = str(services.get("compatible_base_url") or "").strip().rstrip("/")
        configured_key = str(services.get("compatible_api_key") or "")
        if not base_url:
            raise RuntimeError(
                "Configure the custom compatible URL in Settings → Services first"
            )
        if requested_url and requested_url.rstrip("/") != base_url:
            raise RuntimeError(
                "The production's custom URL does not match the trusted compatible profile"
            )
        api_key = configured_key
        missing = ""

    if not model:
        raise RuntimeError("Choose an OpenAI-compatible writing model")
    if not base_url.startswith(("http://", "https://")):
        raise RuntimeError("OpenAI-compatible URL must start with http:// or https://")
    if provider != "openai-compatible" and not api_key:
        raise RuntimeError(missing)
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
    }


def _capture_llm_pass(pid: str, pass_name: str):
    """Capture the current LLM state as a pass and append to the pipeline's log.

    Captures both system_prompt AND user_prompt so the Director Dashboard
    can render the full LLM input. Previously the dashboard only stored
    system_prompt, which made it look like the user's story description
    was missing from Pass 1's input — but it was always being sent as
    a separate user message; the dashboard just wasn't capturing it.
    """
    try:
        from services import llm_service
        pass_entry = {
            "pass": pass_name,
            "system_prompt": getattr(llm_service, '_last_system_prompt', '') or '',
            "user_prompt": getattr(llm_service, '_last_user_prompt', '') or '',
            "response_text": getattr(llm_service, '_stream_buffer', '') or '',
            "thinking_text": getattr(llm_service, '_last_thinking_text', None),
        }
        with _pipeline_lock:
            p = _pipelines.get(pid)
            if p:
                passes = p.get("_llm_passes", [])
                passes.append(pass_entry)
                p["_llm_passes"] = passes
    except Exception:
        pass


def _run_planning(pid: str, params: dict, pipeline_type: str):
    """Run LLM planning and return (clip_plans, planned_clips).

    Uses the new DirectorOrchestrator when use_director_v2 flag is set,
    otherwise falls back to legacy llm_service calls.
    """
    writing_llm = _scoped_writing_llm(params)
    if not writing_llm:
        _ensure_llm_loaded(params)

    # Default v2 — see launch.py services-config comment for rationale.
    # The params dict is built from servicesConfig in the frontend, so
    # this default only fires for direct API callers that didn't pass
    # the flag at all. Keeping it consistent with the services-config
    # default here so the legacy path isn't accidentally hit.
    # Comic-movie is implemented only in the layered planner and always uses
    # that path even when a legacy global toggle is off.
    use_v2 = (
        True
        if pipeline_type == "comic_movie" or writing_llm
        else params.get("use_director_v2", True)
    )

    if use_v2:
        return _run_planning_v2(pid, params, pipeline_type)
    else:
        return _run_planning_legacy(pid, params, pipeline_type)


def _has_visual_references(params: dict) -> bool:
    """True for a main frame or any labelled character/location reference."""
    return bool(
        params.get("reference_image_path")
        or params.get("character_ref_paths")
        or params.get("location_ref_paths")
        or params.get("provided_clip_image_paths")
    )


def _clip_metadata(value: dict) -> dict:
    metadata = value.get("metadata") if isinstance(value, dict) else None
    return dict(metadata) if isinstance(metadata, dict) else {}


def _align_comic_plan_sources(
    params: dict,
    clip_plans: list[dict],
    planned_clips: list[dict],
) -> None:
    """Map adapted film shots back to their primary comic panels.

    Film planning may omit or fuse panels.  Positional zipping therefore
    sends the wrong artwork to LTX; stable source IDs/indices are authoritative.
    """
    original_shots = [
        item if isinstance(item, dict) else {}
        for item in (params.get("comic_shots") or [])
    ]
    original_paths = list(params.get("provided_clip_image_paths") or [])
    by_id: dict[str, int] = {}
    for index, shot in enumerate(original_shots):
        for key in ("shot_id", "panel_id", "id", "primary_source_panel_id"):
            value = str(shot.get(key) or "").strip()
            if value:
                by_id[value] = index

    aligned_shots: list[dict] = []
    aligned_paths: list[str] = []
    for index, plan in enumerate(clip_plans):
        planned = planned_clips[index] if index < len(planned_clips) else {}
        metadata = {
            **_clip_metadata(planned),
            **_clip_metadata(plan),
        }
        for source in (planned, plan):
            for key in (
                "shot_id",
                "renderer",
                "source_panel_ids",
                "source_panel_indices",
                "primary_source_panel_id",
                "primary_source_index",
                "provided_image_path",
                "prepared_keyframe_path",
                "action",
                "camera",
                "motion_level",
                "fit_mode",
                "test_selected",
                "seed",
                "end_beat",
                "risk_tags",
            ):
                if key in source and key not in metadata:
                    metadata[key] = source[key]

        source_index = metadata.get("primary_source_index")
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            source_index = None
        if source_index is None:
            source_id = str(
                metadata.get("primary_source_panel_id") or ""
            ).strip()
            if not source_id:
                panel_ids = metadata.get("source_panel_ids")
                if isinstance(panel_ids, list) and panel_ids:
                    source_id = str(panel_ids[0] or "").strip()
            source_index = by_id.get(source_id)
        if source_index is None and len(clip_plans) == len(original_shots):
            source_index = index
        if source_index is None:
            indices = metadata.get("source_panel_indices")
            if isinstance(indices, list) and indices:
                try:
                    source_index = int(indices[0])
                except (TypeError, ValueError):
                    source_index = None

        base_shot = (
            original_shots[source_index]
            if isinstance(source_index, int)
            and 0 <= source_index < len(original_shots)
            else {}
        )
        aligned = {**base_shot, **metadata}
        aligned.setdefault(
            "shot_id",
            str(
                metadata.get("shot_id")
                or metadata.get("primary_source_panel_id")
                or base_shot.get("panel_id")
                or base_shot.get("id")
                or f"film-shot-{index + 1}"
            ),
        )
        aligned.setdefault("included", True)
        aligned_shots.append(aligned)

        # The primary source remains the original panel. A prepared keyframe
        # is an optional video-safe derivative consumed by image preparation;
        # it must never replace the provenance/source thumbnail in PRE.
        direct_path = str(metadata.get("provided_image_path") or "")
        if direct_path and os.path.isfile(direct_path):
            aligned_paths.append(direct_path)
        elif (
            isinstance(source_index, int)
            and 0 <= source_index < len(original_paths)
        ):
            aligned_paths.append(original_paths[source_index])
        elif index < len(original_paths):
            aligned_paths.append(original_paths[index])
        else:
            aligned_paths.append("")

        if not isinstance(plan.get("metadata"), dict):
            plan["metadata"] = {}
        plan["metadata"].update(metadata)
        plan["shot_id"] = aligned["shot_id"]
        if index < len(planned_clips):
            if not isinstance(planned_clips[index].get("metadata"), dict):
                planned_clips[index]["metadata"] = {}
            planned_clips[index]["metadata"].update(metadata)
            planned_clips[index]["shot_id"] = aligned["shot_id"]

    params["comic_shots"] = aligned_shots
    params["provided_clip_image_paths"] = aligned_paths


def _run_planning_v2(pid: str, params: dict, pipeline_type: str):
    """New architecture: DirectorOrchestrator with planners + renderers."""
    from services import llm_service
    from services.director.orchestrator import DirectorOrchestrator, DirectorFlags

    # Build feature flags from params
    flags_dict = params.get("director_flags", {})
    flags = DirectorFlags.from_dict(flags_dict) if flags_dict else DirectorFlags()

    writing_llm = _scoped_writing_llm(params)

    # Wrap LLM functions to capture each pass for the dashboard log
    _pass_counter = [0]
    def _capture_external(
        pass_name: str,
        prompt: str,
        system_prompt: str,
        response_text: str,
    ):
        with _pipeline_lock:
            pipeline = _pipelines.get(pid)
            if not pipeline:
                return
            passes = pipeline.get("_llm_passes", [])
            passes.append({
                "pass": pass_name,
                "provider": writing_llm["provider"] if writing_llm else "",
                "model_id": writing_llm["model"] if writing_llm else "",
                "system_prompt": system_prompt,
                "user_prompt": prompt,
                "response_text": response_text,
                "thinking_text": None,
            })
            pipeline["_llm_passes"] = passes

    def _external_generate(*args, **kwargs):
        # Director planners share the local-LLM signature.  The isolated
        # compatible client intentionally ignores local-only controls such as
        # thinking_budget, enable_thinking and image_paths.
        prompt = str(kwargs.get("prompt") or (args[0] if args else ""))
        system_prompt = str(kwargs.get("system_prompt") or "")
        response = llm_service.generate_openai_compatible(
            prompt=prompt,
            system_prompt=system_prompt,
            model_id=writing_llm["model"],
            base_url=writing_llm["base_url"],
            api_key=writing_llm["api_key"],
            max_new_tokens=int(kwargs.get("max_new_tokens") or 4096),
            temperature=float(kwargs.get("temperature") or 0.2),
            top_p=float(kwargs.get("top_p") or 0.9),
            frequency_penalty=float(kwargs.get("frequency_penalty") or 0.0),
            presence_penalty=float(kwargs.get("presence_penalty") or 0.0),
            json_schema=kwargs.get("json_schema"),
        )
        _pass_counter[0] += 1
        _capture_external(
            f"scoped_{writing_llm['provider']}_{_pass_counter[0]}",
            prompt,
            system_prompt,
            response,
        )
        return response

    def _logged_generate(*args, **kwargs):
        result = llm_service.generate(*args, **kwargs)
        _pass_counter[0] += 1
        _capture_llm_pass(pid, f"generate_{_pass_counter[0]}")
        return result

    def _logged_streaming(*args, **kwargs):
        result = llm_service.generate_streaming(*args, **kwargs)
        _pass_counter[0] += 1
        _capture_llm_pass(pid, f"streaming_{_pass_counter[0]}")
        return result

    # Create orchestrator with logged LLM functions
    selected_generate = _external_generate if writing_llm else _logged_generate
    selected_streaming = _external_generate if writing_llm else _logged_streaming
    director = DirectorOrchestrator(
        llm_generate=selected_generate,
        llm_generate_streaming=selected_streaming,
        flags=flags,
    )

    # Map pipeline_type to skill_type
    skill_map = {
        "music_video": "music_video",
        "short_film_audio": "short_film",
        "short_film_story": "short_film",
        "podcast": "podcast",
        "viral_video": "viral_video",
        "comic_movie": "comic_movie",
    }
    skill_type = skill_map.get(pipeline_type, "music_video")

    # Build planner kwargs
    scene_description = params.get("scene_description", "")
    reference_image_path = params.get("reference_image_path")
    planned_clips = params.get("planned_clips", [])

    # Read NSFW from server config (persisted setting, not per-request)
    services_cfg = _wgp.server_config.get("services", {}) if _wgp else {}
    nsfw = services_cfg.get("nsfw_mode", False)
    # Multi-shot LoRA mode — passes through to Pass 2 so it can emit
    # storyboard-format video_prompts for medium-length shots. See
    # the toggle's comment in launch.py for behavior details.
    multishot_lora_mode = services_cfg.get("director_multishot_lora_mode", False)

    seamless = params.get("seamless", True)
    # Pass video_model and image_model to every planner so Pass 2 can
    # route its prompt guides correctly. Previously these only flowed
    # into polish_block construction (when polish_mode was on); now the
    # planner gets them unconditionally so it can pick the right
    # dialect-aware guide files (ltx2_shot_breakdown.md for LTX-2,
    # flux_image_edit_pass2.md for Flux.2 Klein, etc.).
    planner_kwargs = {
        "reference_image_path": reference_image_path,
        "speaker_mappings": params.get("speaker_mappings"),
        "characters": params.get("characters", []),
        "nsfw": nsfw,
        "seamless": seamless,
        "video_model": params.get("video_model", ""),
        "image_model": params.get("image_model", ""),
        "multishot_lora_mode": multishot_lora_mode,
        "visual_style": params.get("visual_style", ""),
        "preserve_visual_style": params.get("preserve_visual_style", False),
    }

    if pipeline_type == "comic_movie":
        planner_kwargs.update({
            "comic_context": scene_description,
            "comic_shots": params.get("comic_shots", []),
            "adapt_to_film": _as_bool(
                params.get("comic_adapt_to_film"),
                default=True,
            ),
            "target_shots": params.get("comic_target_shots"),
        })
    elif pipeline_type == "short_film_story":
        planner_kwargs.update({
            "story_description": scene_description,
            "target_duration": params.get("target_duration", 60),
            "target_scenes": params.get("target_scenes"),
            "narrative_mode": params.get("narrative_mode", False),
            "fps": params.get("fps", 16),
            "frames_steps": params.get("frames_steps", 8),
            "frames_minimum": params.get("frames_minimum", 41),
        })
    elif pipeline_type == "short_film_audio":
        planner_kwargs.update({
            "clips": planned_clips,
            "story_description": scene_description,
            "audio_path": params.get("audio_path"),
            "lyrics": params.get("lyrics"),
        })
    elif pipeline_type in ("podcast", "viral_video"):
        planner_kwargs.update({
            "clips": planned_clips if planned_clips else None,
            "transcript": params.get("lyrics"),
            "audio_path": params.get("audio_path"),
            "concept": scene_description,
            "visual_style": params.get("visual_style", ""),
            "target_duration": params.get("target_duration", 30),
            "platform": params.get("platform", "general"),
            "style": params.get("style", "cinematic"),
        })
    else:
        # Music video
        planner_kwargs.update({
            "clips": planned_clips,
            "scene_description": scene_description,
            "lyrics": params.get("lyrics"),
            "bpm": params.get("bpm", 120),
        })

    # Inject LoRA guides + model dialect guides into the planner only for
    # the full/light_guide inject modes (legacy paths). Default mode
    # "third_pass" deliberately skips this — model dialect is applied
    # per-prompt after planning by polish_prompts_third_pass(), which
    # avoids stacking conflicting dialect guidance into Pass 2's already
    # crowded system prompt.
    polish_mode = services_cfg.get("director_prompt_polish", "third_pass")
    if polish_mode in ("full_guide", "light_guide"):
        from services.director.prompt_polish import build_polish_block
        guide_mode = "full" if polish_mode == "full_guide" else "light"
        video_model = params.get("video_model", "")
        image_model = params.get("image_model", "")
        video_loras = (params.get("video_loras") or {}).get("activated_loras", [])
        image_loras = (params.get("image_loras") or {}).get("activated_loras", [])
        polish_block = build_polish_block(video_model, image_model, guide_mode,
                                          video_loras=video_loras, image_loras=image_loras)
        if polish_block:
            planner_kwargs["polish_block"] = polish_block
            print(f"[Pipeline {pid}] Injected {guide_mode} polish block ({len(polish_block)} chars)")

    # Also pass character/location ref labels and paths for image prompt rules
    planner_kwargs["character_ref_paths"] = params.get("character_ref_paths", [])
    planner_kwargs["character_ref_labels"] = params.get("character_ref_labels", [])
    planner_kwargs["location_ref_paths"] = params.get("location_ref_paths", [])
    planner_kwargs["location_ref_labels"] = params.get("location_ref_labels", [])

    # Plan
    print(f"[Pipeline {pid}] Planning with DirectorOrchestrator (skill={skill_type})...")
    plan = director.plan(skill_type, **planner_kwargs)

    # Store the production plan in pipeline state for later reference
    _update_pipeline(pid, production_plan=plan.to_dict())

    # Render prompts
    has_reference = _has_visual_references(params)
    rendered = director.render_plan(plan, prompt_type="both", has_reference=has_reference)
    clip_plans = director.plan_to_clip_plans(rendered)

    # Build planned_clips from shot data (for story mode which creates clips)
    if pipeline_type in ("short_film_story", "comic_movie"):
        cumulative = 0.0
        # Get FPS from model definition for accurate frame count
        fps = params.get("fps", 16)
        try:
            vm = params.get("video_model", "")
            md = _wgp.get_model_def(vm) if vm else None
            if md and md.get("fps"):
                fps = md["fps"]
        except Exception:
            pass
        new_clips = []
        for shot in plan.shots:
            duration_frames = shot.metadata.get("duration_frames") if shot.metadata else int(shot.duration_sec * fps)
            shot_metadata = dict(shot.metadata or {})
            new_clips.append({
                "start": cumulative,
                "end": cumulative + shot.duration_sec,
                "duration_sec": shot.duration_sec,
                "duration_frames": duration_frames,
                "label": shot.narrative_role or shot.scene_type or "scene",
                "beat_count": 0,
                "shot_id": shot.shot_id,
                "metadata": shot_metadata,
            })
            cumulative += shot.duration_sec
        planned_clips = new_clips

    # Normalize
    if clip_plans and isinstance(clip_plans[0], str):
        clip_plans = [{"video_prompt": p, "image_prompt": ""} for p in clip_plans]
    if pipeline_type == "comic_movie":
        _align_comic_plan_sources(params, clip_plans, planned_clips)

    # Debug: log shot structure
    for idx, cp in enumerate(clip_plans):
        kf_count = len(cp.get("keyframe_prompts", []) or [])
        wc = cp.get("window_count", 1)
        pc = planned_clips[idx] if idx < len(planned_clips) else {}
        dur = pc.get("duration_sec", pc.get("duration_frames", "?"))
        print(f"[Pipeline] Shot {idx+1}: duration={dur}s, windows={wc}, keyframes={kf_count}, prompt_len={len(cp.get('video_prompt',''))}")

    return clip_plans, planned_clips


def _run_planning_legacy(pid: str, params: dict, pipeline_type: str):
    """Legacy planning: direct calls to llm_service functions."""
    from services import llm_service

    scene_description = params.get("scene_description", "")
    reference_image_path = params.get("reference_image_path")
    speaker_mappings = params.get("speaker_mappings", [])
    characters = params.get("characters", [])
    audio_path = params.get("audio_path")
    planned_clips = params.get("planned_clips", [])
    fps = params.get("fps", 16)
    frames_steps = params.get("frames_steps", 8)
    frames_minimum = params.get("frames_minimum", 41)

    if pipeline_type == "short_film_story":
        # Path C: Full story-based planning
        target_duration = params.get("target_duration", 60)
        narrative_mode = params.get("narrative_mode", False)

        result = llm_service.plan_short_film_from_story(
            story_description=scene_description,
            characters=characters,
            reference_image_path=reference_image_path,
            character_ref_paths=params.get("character_ref_paths"),
            character_ref_labels=params.get("character_ref_labels"),
            location_ref_paths=params.get("location_ref_paths"),
            location_ref_labels=params.get("location_ref_labels"),
            target_duration=target_duration,
            narrative_mode=narrative_mode,
            fps=fps,
            frames_steps=frames_steps,
            frames_minimum=frames_minimum,
            visual_style=params.get("visual_style", ""),
            preserve_visual_style=params.get("preserve_visual_style", False),
        )
        planned_clips = result.get("clips", [])
        clip_plans = result.get("clip_plans", [])

    elif pipeline_type == "short_film_audio":
        # Path B: Short film with uploaded dialogue audio
        result = llm_service.plan_short_film_prompts(
            clips=planned_clips,
            scene_description=scene_description,
            lyrics=params.get("lyrics", ""),
            reference_image_path=reference_image_path,
            character_ref_paths=params.get("character_ref_paths"),
            character_ref_labels=params.get("character_ref_labels"),
            location_ref_paths=params.get("location_ref_paths"),
            location_ref_labels=params.get("location_ref_labels"),
            speaker_mappings=speaker_mappings,
            characters=characters,
            prompt_type="both",
        )
        clip_plans = result if isinstance(result, list) else result.get("clip_plans", [])

    else:
        # Music video flow
        result = llm_service.plan_clip_prompts_and_images(
            clips=planned_clips,
            scene_description=scene_description,
            lyrics=params.get("lyrics", ""),
            bpm=params.get("bpm"),
            reference_image_path=reference_image_path,
            speaker_mappings=speaker_mappings,
            prompt_type="both",
        )
        clip_plans = result if isinstance(result, list) else result.get("clip_plans", [])

    # Normalize clip_plans to list of dicts
    if clip_plans and isinstance(clip_plans[0], str):
        clip_plans = [{"video_prompt": p, "image_prompt": ""} for p in clip_plans]

    from services.director.policies import enforce_visual_style_on_clip_plans
    clip_plans = enforce_visual_style_on_clip_plans(
        clip_plans,
        params.get("visual_style", ""),
        preserve=bool(params.get("preserve_visual_style", False)),
        has_reference=_has_visual_references(params),
    )
    return clip_plans, planned_clips


# ── Image Generation Phase ──────────────────────────────────────────────

def _normalize_video_resolution(video_model: str, resolution: str) -> str:
    """Return the effective canvas size the video backend will actually use.

    LTX's local VAE works on 64-pixel blocks.  Passing common display sizes
    such as 1280x720 silently became 1280x704 later in wgp.py, after Director
    had already prepared its source image and persisted misleading metadata.
    Normalize it once at the Director boundary so fitting, generation and
    saved state all agree.
    """
    value = str(resolution or "1280x720").lower().replace("×", "x")
    parts = value.split("x")
    if len(parts) != 2:
        return value
    try:
        width, height = int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return value

    is_ltx = "ltx2" in str(video_model or "").lower()
    if not is_ltx and _wgp is not None:
        try:
            model_def = _wgp.get_model_def(video_model) or {}
            is_ltx = str(model_def.get("architecture") or "").lower().startswith("ltx2")
        except Exception:
            pass
    if not is_ltx:
        return f"{width}x{height}"

    block = 64
    normalized_width = max(256, width // block * block)
    normalized_height = max(256, height // block * block)
    normalized = f"{normalized_width}x{normalized_height}"
    if normalized != f"{width}x{height}":
        print(
            f"[Director] LTX canvas aligned {width}x{height} → {normalized} "
            "(64-pixel VAE blocks)"
        )
    return normalized


def _fit_i2v_image(
    source: str,
    destination: str,
    resolution: str,
    fit_mode: str,
    focus: Optional[tuple[float, float]] = None,
) -> None:
    """Prepare a first frame without stretching it.

    ``cover``/``reframe`` create a full-bleed editorial crop around an optional
    normalized focus point. ``contain`` preserves the full panel on a quiet
    solid matte. Legacy ``crop`` and ``smart`` aliases remain readable, but
    new PREs never synthesize the blurred "poster card" that encouraged LTX
    to zoom into the inset panel. ``source`` copies an already prepared
    keyframe untouched.
    """
    import shutil
    from PIL import Image, ImageOps, ImageStat

    fit_mode = str(fit_mode or "contain").strip().lower()
    fit_mode = {
        "crop": "cover",
        "smart": "contain",
        "preserve": "contain",
        "fit": "contain",
    }.get(fit_mode, fit_mode)
    if fit_mode == "source":
        shutil.copy2(source, destination)
        return

    try:
        target_width, target_height = (
            int(part) for part in str(resolution).lower().split("x", 1)
        )
    except (TypeError, ValueError):
        shutil.copy2(source, destination)
        return

    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
        if image.size == (target_width, target_height):
            image.save(destination, format="PNG")
            return

        center = focus or (0.5, 0.5)
        center = (
            max(0.0, min(1.0, float(center[0]))),
            max(0.0, min(1.0, float(center[1]))),
        )
        if fit_mode in {"cover", "reframe", "reframe-ai"}:
            result = ImageOps.fit(
                image,
                (target_width, target_height),
                method=Image.Resampling.LANCZOS,
                centering=center,
            )
        else:
            sample = image.copy()
            sample.thumbnail((64, 64))
            mean = ImageStat.Stat(sample).mean
            matte = tuple(
                max(0, min(255, round(channel * 0.22)))
                for channel in mean[:3]
            )
            background = Image.new(
                "RGB",
                (target_width, target_height),
                matte,
            )
            foreground = ImageOps.contain(
                image,
                (target_width, target_height),
                method=Image.Resampling.LANCZOS,
            )
            result = background
            result.paste(
                foreground,
                (
                    (target_width - foreground.width) // 2,
                    (target_height - foreground.height) // 2,
                ),
            )
        result.save(destination, format="PNG")


def _crop_retained_fraction(
    source_size: tuple[int, int],
    resolution: str,
) -> float:
    """Estimate how much of the source survives a centered cover crop."""
    source_width, source_height = source_size
    try:
        target_width, target_height = (
            int(part) for part in str(resolution).lower().split("x", 1)
        )
    except (TypeError, ValueError):
        return 1.0
    if min(source_width, source_height, target_width, target_height) <= 0:
        return 1.0
    source_ratio = source_width / source_height
    target_ratio = target_width / target_height
    return min(source_ratio / target_ratio, target_ratio / source_ratio)


def _prepare_provided_clip_images(
    pid: str,
    image_paths: list[str],
    expected_count: int,
    out_dir: str,
    resolution: str = "1280x720",
    fit_mode: str = "contain",
    protect_composition: bool = False,
    shots: Optional[list[dict]] = None,
    reuse_source_filenames: Optional[list[str]] = None,
    update_pipeline_state: bool = True,
    return_details: bool = False,
):
    """Stage caller-supplied I2V frames in one consistent video canvas."""

    from PIL import Image, ImageOps, ImageStat

    if len(image_paths) != expected_count:
        raise RuntimeError(
            f"Comic movie received {len(image_paths)} panel images for "
            f"{expected_count} planned shots. Reopen the comic and try again."
        )
    os.makedirs(out_dir, exist_ok=True)
    staged: list[str] = []
    source_copies: list[str] = []
    fit_details: list[dict] = []
    source_sizes: list[tuple[int, int]] = []
    for index, source in enumerate(image_paths):
        shot = (
            shots[index]
            if shots and index < len(shots) and isinstance(shots[index], dict)
            else {}
        )
        source = str(source or "")
        if not source or not os.path.isfile(source):
            raise RuntimeError(
                f"Comic panel image {index + 1} is missing. "
                "The completed panels are still preserved in the comic."
            )
        try:
            with Image.open(source) as opened:
                transposed = ImageOps.exif_transpose(opened)
                source_size = transposed.size
                source_sizes.append(source_size)
                sample = transposed.convert("RGB")
                sample.thumbnail((96, 96))
                extrema = sample.getextrema()
                statistics = ImageStat.Stat(sample)
                maximum = max(high for _low, high in extrema)
                dynamic_range = max(high - low for low, high in extrema)
                mean = sum(statistics.mean) / len(statistics.mean)
                effectively_black = maximum <= 3 or (
                    dynamic_range <= 2 and mean <= 5
                )
        except Exception as exc:
            raise RuntimeError(
                f"Comic panel image {index + 1} could not be read: {exc}. "
                "The comic and its completed artwork are still preserved."
            ) from exc
        if effectively_black:
            raise RuntimeError(
                f"Comic panel {index + 1} was captured as a blank black image. "
                "Video generation was stopped before using it. Reopen the comic "
                "and convert it to a movie again; the artwork itself is preserved."
            )
        prepared_keyframe = str(
            shot.get("prepared_keyframe_path")
            or shot.get("video_keyframe_path")
            or ""
        )
        source_for_fit = (
            prepared_keyframe
            if prepared_keyframe and os.path.isfile(prepared_keyframe)
            else source
        )
        requested_fit_mode = str(
            shot.get("fit_mode") or fit_mode or "contain"
        ).strip().lower()
        effective_fit_mode = {
            "crop": "cover",
            "smart": "contain",
            "preserve": "contain",
        }.get(requested_fit_mode, requested_fit_mode)
        retained_fraction = _crop_retained_fraction(source_size, resolution)
        has_prepared_keyframe = source_for_fit != source
        needs_reframe = bool(
            protect_composition
            and effective_fit_mode in {"reframe", "reframe-ai"}
            and retained_fraction < 0.58
            and not has_prepared_keyframe
        )
        if (
            effective_fit_mode in {"reframe", "reframe-ai"}
            and not has_prepared_keyframe
            and retained_fraction < 0.58
        ):
            # Never spend image-model credits or substitute a blur silently.
            # PRE exposes the risk and lets the user choose an explicit crop,
            # contain fit, or approved edited keyframe.
            effective_fit_mode = "contain"
            needs_reframe = True

        focus_value = shot.get("subject_focus") or shot.get("focus")
        focus = None
        if isinstance(focus_value, dict):
            try:
                focus = (
                    float(focus_value.get("x", 0.5)),
                    float(focus_value.get("y", 0.5)),
                )
            except (TypeError, ValueError):
                focus = None
        elif isinstance(focus_value, (list, tuple)) and len(focus_value) >= 2:
            try:
                focus = (float(focus_value[0]), float(focus_value[1]))
            except (TypeError, ValueError):
                focus = None

        reusable_source = (
            str(reuse_source_filenames[index] or "")
            if reuse_source_filenames
            and index < len(reuse_source_filenames)
            else ""
        )
        source_filename = reusable_source or (
            f"comic_source_{index + 1:04d}_{uuid.uuid4().hex[:8]}.png"
        )
        if not reusable_source:
            source_destination = os.path.join(out_dir, source_filename)
            with Image.open(source) as opened:
                ImageOps.exif_transpose(opened).convert("RGB").save(
                    source_destination,
                    format="PNG",
                )
        source_copies.append(source_filename)

        extension = (
            os.path.splitext(source_for_fit)[1].lower()
            if str(effective_fit_mode).lower() == "source"
            else ".png"
        )
        if extension not in (".png", ".jpg", ".jpeg", ".webp"):
            extension = ".png"
        filename = f"comic_panel_{index + 1:04d}_{uuid.uuid4().hex[:8]}{extension}"
        destination = os.path.join(out_dir, filename)
        _fit_i2v_image(
            source_for_fit,
            destination,
            resolution,
            effective_fit_mode,
            focus=focus,
        )
        staged.append(filename)
        fit_details.append({
            "requested_fit_mode": requested_fit_mode,
            "effective_fit_mode": effective_fit_mode,
            "retained_fraction": round(retained_fraction, 4),
            "needs_reframe": needs_reframe,
            "reframe_approved": bool(
                shot.get("reframe_approved") or has_prepared_keyframe
            ),
            "used_prepared_keyframe": has_prepared_keyframe,
            "focus": list(focus) if focus else [0.5, 0.5],
        })
        if update_pipeline_state:
            _update_pipeline(
                pid,
                progress={
                    "current": index + 1,
                    "total": expected_count,
                    "message": (
                        f"Preparing comic panel {index + 1}/{expected_count}"
                    ),
                    "step": 0,
                    "total_steps": 0,
                },
            )
    print(
        f"[Pipeline {pid}] Prepared {len(staged)} supplied comic panel start "
        f"images at {resolution} (fit={fit_mode}, "
        f"needs_reframe={sum(item['needs_reframe'] for item in fit_details)})"
    )
    if update_pipeline_state:
        _update_pipeline(
            pid,
            _clip_source_sizes=source_sizes,
            _clip_source_images=source_copies,
            _clip_fit_details=fit_details,
        )
    if return_details:
        return staged, source_copies, source_sizes, fit_details
    return staged

def _generate_minimax_director_image(
    *,
    prompt: str,
    resolution: str,
    output_dir: str,
    reference_paths: list[str],
) -> str:
    """Generate one Director frame with the external MiniMax Image-01 API."""
    from services import minimax_image_service

    api_key = ((_wgp.server_config.get("services") or {}).get("minimax_api_key") or "")
    if not api_key:
        raise RuntimeError("Set the MiniMax API key in Settings → Services")
    subject_reference = ""
    for path in reference_paths:
        if path and os.path.isfile(path):
            subject_reference = minimax_image_service.local_image_data_uri(path)
            break
    try:
        generated = minimax_image_service.generate_image(
            api_key=api_key,
            prompt=prompt,
            aspect_ratio=minimax_image_service.aspect_ratio_for_resolution(resolution),
            output_dir=output_dir,
            subject_reference=subject_reference,
            filename_prefix="minimax-director",
        )
    except minimax_image_service.MiniMaxImageError as exc:
        raise RuntimeError(str(exc)) from exc
    return str(generated.get("name") or "")


_LOCATION_MATCH_STOP_WORDS = frozenset({
    "and", "at", "de", "del", "el", "en", "la", "las", "los", "of",
    "the", "un", "una", "y", "world", "scene", "location", "setting",
})

_LOCATION_TOKEN_ALIASES = {
    # Conservative bilingual aliases used only for resumable plans created
    # before location_ref_label existed. New plans always carry the exact
    # user-supplied label and never need this heuristic.
    "arbol": "tree",
    "camara": "chamber",
    "cielo": "sky",
    "claro": "clearing",
    "cristal": "crystal",
    "cristales": "crystal",
    "desierto": "desert",
    "flotante": "floating",
    "flotantes": "floating",
    "horizonte": "horizon",
    "linea": "line",
    "meseta": "plateau",
    "playa": "beach",
    "ruina": "ruin",
    "ruinas": "ruin",
    "semilla": "seed",
    "siembra": "planting",
    "transformacion": "transformation",
    "ultimo": "last",
}


def _normalize_location_match_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _canonical_location_tokens(value: object) -> set[str]:
    return {
        _LOCATION_TOKEN_ALIASES.get(token, token)
        for token in _normalize_location_match_text(value).split()
        if len(token) >= 4 and token not in _LOCATION_MATCH_STOP_WORDS
    }


def _director_location_ref_for_plan(plan: dict, params: dict) -> tuple[str, str]:
    """Resolve at most one labelled Story location reference for a shot.

    New plans carry an exact ``metadata.location_ref_label`` chosen by the
    planner. Resumed plans created before that field existed get a conservative
    text match; an ambiguous result returns no location instead of conditioning
    a shot on every unrelated place.
    """
    paths = [str(path or "").strip() for path in (params.get("location_ref_paths") or [])]
    labels = [str(label or "").strip() for label in (params.get("location_ref_labels") or [])]
    pairs = [
        (paths[index], labels[index] if index < len(labels) else "")
        for index in range(len(paths))
        if paths[index]
    ]
    if not pairs:
        return "", ""
    if len(pairs) == 1:
        return pairs[0]

    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    requested_label = str(
        plan.get("location_ref_label")
        or metadata.get("location_ref_label")
        or ""
    ).strip()
    normalized_requested = _normalize_location_match_text(requested_label)
    if normalized_requested:
        for path, label in pairs:
            if _normalize_location_match_text(label) == normalized_requested:
                return path, label

    requested_index = plan.get("location_ref_index", metadata.get("location_ref_index"))
    try:
        index = int(requested_index)
    except (TypeError, ValueError):
        index = -1
    if 0 <= index < len(pairs):
        return pairs[index]

    searchable_parts = [
        plan.get("image_prompt"),
        plan.get("video_prompt"),
        plan.get("scene_goal"),
        plan.get("environment"),
        metadata.get("title"),
        *(plan.get("window_prompts") or []),
    ]
    searchable = _normalize_location_match_text(" ".join(
        str(item.get("prompt", item.get("text", ""))) if isinstance(item, dict) else str(item or "")
        for item in searchable_parts
    ))
    searchable_tokens = _canonical_location_tokens(searchable)
    scored: list[tuple[int, int, str, str]] = []
    for pair_index, (path, label) in enumerate(pairs):
        normalized_label = _normalize_location_match_text(label)
        label_tokens = _canonical_location_tokens(normalized_label)
        exact_phrase = bool(normalized_label and normalized_label in searchable)
        token_hits = sum(token in searchable_tokens for token in label_tokens)
        prefix_hits = sum(
            1 for token in label_tokens
            if any(len(candidate) >= 5 and token[:5] == candidate[:5] for candidate in searchable_tokens)
        )
        score = (100 if exact_phrase else 0) + token_hits * 10 + prefix_hits
        if score:
            scored.append((score, -pair_index, path, label))
    if not scored:
        return "", ""
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return "", ""
    return scored[0][2], scored[0][3]


def _run_image_generation(pid: str, params: dict, clip_plans: list[dict], out_dir: str = None, workspace: str = None) -> tuple[list[str], list[list[str]]]:
    """Generate start images and keyframe images per clip.

    Returns:
        (clip_images, clip_keyframes) where:
        - clip_images[i] = start image filename for clip i
        - clip_keyframes[i] = list of keyframe image filenames for clip i (may be empty)
    """
    ref_image_path = params.get("reference_image_path")
    character_ref_paths = params.get("character_ref_paths", []) or []
    location_ref_paths = params.get("location_ref_paths", []) or []
    image_model = params.get("image_model", "flux2_klein_9b")
    use_minimax_image_api = image_model == "minimax:image-01"
    image_params = params.get("image_params", {})
    image_loras = params.get("image_loras", {})

    # Diagnostic-only log: report what the frontend sent so a future
    # "I selected N LoRAs but only K were applied" report has data we
    # can correlate against the [LoRA] Loading line wgp prints.
    _activated_in = list(image_loras.get("activated_loras", []) or [])
    _mults_in = image_loras.get("loras_multipliers", "") or ""
    if _activated_in and use_minimax_image_api:
        print(
            f"[Pipeline {pid}] Ignoring {len(_activated_in)} local image LoRA(s): "
            "MiniMax Image-01 runs through the external API."
        )
        _activated_in = []
        _mults_in = ""
        image_loras = {"activated_loras": [], "loras_multipliers": ""}
    elif _activated_in:
        print(
            f"[Pipeline {pid}] Image LoRAs received: {len(_activated_in)} | "
            f"model={image_model} | "
            f"names={[os.path.basename(n) for n in _activated_in]} | "
            f"multipliers={_mults_in!r}"
        )

    # ── Filter image LoRAs to those that exist in the image model's dir ──
    # The frontend's DirectorLoraSelector filters available LoRAs by
    # model directory, but `savedLoraPerMode.image` persists across
    # sessions and can hold stale activations from a previous model
    # selection (e.g. an LTX-2 LoRA name that's never been in the
    # flux2_klein_9b/ directory). Without this filter, wgp.validate_task
    # rejects the entire task with "The following Loras files are missing
    # or invalid: [...]" and image gen never starts.
    #
    # This is a file-EXISTENCE check only — no architecture detection,
    # no dim peeking. Just: is the .safetensors actually in the right
    # directory? If not, drop it with a clear warning so the user knows
    # to re-select their image LoRAs for the active model.
    try:
        if _activated_in and not use_minimax_image_api:
            try:
                _lora_dir = _wgp.get_lora_dir(image_model)
            except Exception:
                _lora_dir = ""
            if _lora_dir and os.path.isdir(_lora_dir):
                _existing = {
                    f for f in os.listdir(_lora_dir)
                    if f.lower().endswith((".safetensors", ".sft"))
                }
                _mult_tokens = _mults_in.split()
                _kept: list[str] = []
                _kept_mults: list[str] = []
                _skipped: list[str] = []
                for _idx, _name in enumerate(_activated_in):
                    _basename = os.path.basename(_name)
                    if _basename in _existing:
                        _kept.append(_name)
                        if _idx < len(_mult_tokens):
                            _kept_mults.append(_mult_tokens[_idx])
                    else:
                        _skipped.append(_basename)
                if _skipped:
                    _warn = (
                        f"Skipped {len(_skipped)} image LoRA(s) not present in "
                        f"{os.path.basename(_lora_dir)}/: {_skipped}. These were "
                        f"likely activated when a different image model was selected, "
                        f"and the saved selection persisted across sessions. Re-select "
                        f"the LoRAs you want for {image_model} in the Director image "
                        f"LoRA panel to clear the stale entries."
                    )
                    print(f"[Pipeline {pid}] {_warn}")
                    _existing_warnings = _pipelines.get(pid, {}).get("lora_warnings", []) or []
                    _update_pipeline(pid, lora_warnings=[*_existing_warnings, _warn])
                _activated_in = _kept
                _mults_in = " ".join(_kept_mults)
                image_loras = {
                    "activated_loras": _activated_in,
                    "loras_multipliers": _mults_in,
                }
                print(
                    f"[Pipeline {pid}] Image LoRAs after existence filter: "
                    f"{len(_kept)} kept, {len(_skipped)} skipped"
                )
    except Exception as _e:
        print(f"[Pipeline {pid}] LoRA file-existence filter skipped: {_e}")

    resolution = image_params.get("resolution", "1280x720")
    steps = image_params.get("num_inference_steps", 8)
    guidance = image_params.get("guidance_scale", 1)
    spatial_upsampling = params.get("image_spatial_upsampling", "")
    film_grain_intensity = params.get("image_film_grain_intensity", 0)
    film_grain_saturation = params.get("image_film_grain_saturation", 0.5)

    # Character identity is global; location conditioning is selected per shot.
    # Sending every Story location to every image was both wasteful and
    # contradictory when the locations had different visual identities.
    character_refs = [p for p in character_ref_paths if p and os.path.isfile(p)]
    print(
        f"[Pipeline {pid}] Image refs: main={ref_image_path}, "
        f"chars={len(character_ref_paths)}, available_locs={len(location_ref_paths)}"
    )

    if not out_dir:
        out_dir = _wgp.save_path

    if use_minimax_image_api and not ((_wgp.server_config.get("services") or {}).get("minimax_api_key")):
        raise RuntimeError("Set the MiniMax API key in Settings → Services before starting Director")

    # Count total images to generate (start images + keyframes)
    total_images = len(clip_plans)
    for plan in clip_plans:
        kf = plan.get("keyframe_prompts", [])
        if kf:
            total_images += len(kf)

    clip_images: list[str] = []
    clip_keyframes: list[list[str]] = []
    image_count = 0

    def _gen_image(
        prompt: str,
        source_ref: str,
        shot_extra_refs: list[str] | None = None,
    ) -> str:
        """Generate a single image using source_ref + optional extra refs."""
        nonlocal image_count
        all_refs: list[str] = []
        for candidate in [source_ref, *(shot_extra_refs or [])]:
            if candidate and candidate not in all_refs:
                all_refs.append(candidate)
        # WanGP treats newlines as separate queue prompts. Director prompts are
        # prose and may contain a multi-line story bible, so flatten them
        # before submission to guarantee one requested image means one job.
        prompt = " ".join(str(prompt or "").split())
        print(f"[Pipeline {pid}] _gen_image: {len(all_refs)} refs: {[os.path.basename(r) for r in all_refs]}")
        if use_minimax_image_api:
            # Image-01 accepts one character identity reference. Prioritise the
            # Story cast reference, then fall back to the current continuity
            # frame. Location references are descriptive context, not identity.
            filename = _generate_minimax_director_image(
                prompt=prompt,
                resolution=resolution,
                output_dir=out_dir,
                reference_paths=[
                    *[p for p in character_ref_paths if p and os.path.isfile(p)],
                    source_ref,
                ],
            )
            image_count += 1
            return filename
        gen_params: dict = {
            "model_type": image_model,
            "prompt": prompt,
            "image_refs": all_refs,
            "image_mode": 1,
            "image_prompt_type": "",
            "num_inference_steps": steps,
            "guidance_scale": guidance,
            # 'I' carries an image reference; a ref-less anchor is plain T2I.
            "video_prompt_type": "KI" if all_refs else "",
            "resolution": resolution,
            "seed": -1,
            "settings_version": 2.52,
            "generation_mode": "image",
            "repeat_generation": 1,
            "negative_prompt": "",
            "video_length": 1,
            "activated_loras": image_loras.get("activated_loras", []),
            "loras_multipliers": image_loras.get("loras_multipliers", ""),
            "_director_pipeline_id": pid,
        }
        if spatial_upsampling:
            gen_params["spatial_upsampling"] = spatial_upsampling
        if film_grain_intensity > 0:
            gen_params["film_grain_intensity"] = film_grain_intensity
            gen_params["film_grain_saturation"] = film_grain_saturation

        output_files = _submit_and_wait(gen_params, timeout_s=600, workspace=workspace, out_dir=out_dir)
        image_count += 1
        return output_files[0] if output_files else ""

    # If no reference image was provided, generate the first shot as the
    # establishing anchor and reuse that exact file for clip 1. Previously the
    # entire multi-line production brief was sent as a separate image prompt,
    # then clip 1 was generated again: one redundant GPU generation and, since
    # WanGP splits newline prompts, potentially dozens of accidental prompts.
    first_clip_anchor = ""
    first_clip_anchor_elapsed = 0.0
    if not (ref_image_path and os.path.isfile(ref_image_path)):
        scene_desc = " ".join(str(params.get("scene_description") or "").split())
        anchor_prompt = (
            (clip_plans[0].get("image_prompt", "") if clip_plans else "")
            or scene_desc[:1800]
            or "cinematic establishing shot"
        )
        _update_pipeline(pid, progress={
            "current": 0,
            "total": total_images,
            "message": "Generating first shot and visual anchor",
            "step": 0, "total_steps": 0,
        })
        print(f"[Pipeline {pid}] No reference image — generating clip 1 as the shared visual anchor.")
        anchor_started = time.time()
        anchor_location, anchor_location_label = _director_location_ref_for_plan(
            clip_plans[0] if clip_plans else {}, params
        )
        anchor_extras = [*character_refs, *([anchor_location] if anchor_location else [])]
        if anchor_location:
            print(
                f"[Pipeline {pid}] Shot 1 location ref: "
                f"{anchor_location_label or os.path.basename(anchor_location)}"
            )
        anchor_file = _gen_image(anchor_prompt, "", anchor_extras)
        first_clip_anchor_elapsed = time.time() - anchor_started
        anchor_path = os.path.join(out_dir, anchor_file) if anchor_file else ""
        if anchor_path and os.path.isfile(anchor_path):
            ref_image_path = anchor_path
            first_clip_anchor = anchor_file
            print(f"[Pipeline {pid}] Adopted establishing image as shared reference: {anchor_file}")
        else:
            # The normal per-shot loop will retry clip 1, so do not count a
            # missing anchor as a completed image in progress reporting.
            image_count = max(0, image_count - 1)

    for i, plan in enumerate(clip_plans):
        if _pipelines[pid]["status"] == "cancelled":
            return clip_images, clip_keyframes

        # ── Determine image source: original reference or previous scene's output ──
        image_source = plan.get("image_source", "original")
        source_ref = ref_image_path  # default: user's original reference
        location_ref, location_label = _director_location_ref_for_plan(plan, params)
        shot_extra_refs = [*character_refs, *([location_ref] if location_ref else [])]
        if location_ref:
            print(
                f"[Pipeline {pid}] Shot {i + 1} location ref: "
                f"{location_label or os.path.basename(location_ref)}"
            )
        elif len(location_ref_paths) > 1:
            print(
                f"[Pipeline {pid}] Shot {i + 1}: no unambiguous location "
                "reference; sending none instead of all locations."
            )

        if image_source == "previous" and i > 0 and clip_images[i - 1]:
            prev_img_path = os.path.join(out_dir, clip_images[i - 1])
            if os.path.isfile(prev_img_path):
                source_ref = prev_img_path
                print(f"[Pipeline {pid}] Shot {i+1}: using previous scene output as source ({clip_images[i-1]})")

        _update_pipeline(pid, progress={
            "current": image_count,
            "total": total_images,
            "message": f"Shot {i + 1}: generating start image ({image_source})",
            "step": 0, "total_steps": 0,
        })

        prompt = str(plan.get("image_prompt") or "")
        ref_exists = os.path.isfile(source_ref) if source_ref else False
        print(f"[Pipeline {pid}] Shot {i+1} start image: source={image_source}, ref={source_ref} (exists={ref_exists}), prompt='{prompt[:60]}...'")

        img_t0 = time.time()
        try:
            if i == 0 and first_clip_anchor:
                start_img = first_clip_anchor
                print(
                    f"[Pipeline {pid}] Shot 1: reusing its establishing "
                    f"image ({first_clip_anchor})"
                )
            elif image_source == "previous" and source_ref != ref_image_path:
                # Dual reference: previous scene output as primary + original reference for character identity
                start_img = _gen_image(
                    prompt,
                    source_ref,
                    [ref_image_path, *shot_extra_refs],
                )
            else:
                start_img = _gen_image(prompt, ref_image_path, shot_extra_refs)
            clip_images.append(start_img)
        except Exception as e:
            print(f"[Pipeline {pid}] Shot {i+1} start image failed: {e}")
            if use_minimax_image_api:
                raise
            clip_images.append("")
        # Record per-clip image timing
        timings = _pipelines.get(pid, {}).get("_clip_timings", {})
        timings[f"image_{i}"] = round(
            first_clip_anchor_elapsed
            if i == 0 and first_clip_anchor
            else time.time() - img_t0,
            2,
        )
        _update_pipeline(pid, _clip_timings=timings)

        # ── Generate keyframes (chained from previous output) ──
        keyframe_prompts = plan.get("keyframe_prompts", []) or []
        shot_keyframes: list[str] = []

        if keyframe_prompts and clip_images[-1]:
            # Chain: each keyframe edits from the previous image
            chain_ref = os.path.join(out_dir, clip_images[-1])  # start from the start image

            for ki, kf_prompt in enumerate(keyframe_prompts):
                if _pipelines[pid]["status"] == "cancelled":
                    break

                # Ensure kf_prompt is a string (LLM may return dicts or other types)
                if isinstance(kf_prompt, dict):
                    kf_prompt = kf_prompt.get("prompt", kf_prompt.get("image_prompt", str(kf_prompt)))
                elif not isinstance(kf_prompt, str):
                    kf_prompt = str(kf_prompt)
                if not kf_prompt or not kf_prompt.strip():
                    continue

                _update_pipeline(pid, progress={
                    "current": image_count,
                    "total": total_images,
                    "message": f"Shot {i + 1}: keyframe {ki + 1}/{len(keyframe_prompts)}",
                    "step": 0, "total_steps": 0,
                })

                print(f"[Pipeline {pid}] Shot {i+1} keyframe {ki+1}: chain_ref='{os.path.basename(chain_ref)}', prompt='{str(kf_prompt)[:60]}...'")

                try:
                    kf_img = _gen_image(kf_prompt, chain_ref, shot_extra_refs)
                    shot_keyframes.append(kf_img)
                    # Chain: next keyframe edits from this one
                    if kf_img:
                        chain_ref = os.path.join(out_dir, kf_img)
                except Exception as e:
                    print(f"[Pipeline {pid}] Shot {i+1} keyframe {ki+1} failed: {e}")
                    if use_minimax_image_api:
                        raise
                    shot_keyframes.append("")

        clip_keyframes.append(shot_keyframes)

    _update_pipeline(pid, progress={
        "current": total_images,
        "total": total_images,
        "message": "All images generated",
        "step": 0, "total_steps": 0,
    })

    return clip_images, clip_keyframes


# ── Video Generation Phase ──────────────────────────────────────────────

def _comic_framing_band(value: str) -> int:
    """Coarse framing distance used to avoid implausible panel morphs."""
    text = str(value or "").lower()
    if any(token in text for token in ("extreme close", "close-up", "close up", "detail", "macro")):
        return 0
    if any(token in text for token in ("wide", "long shot", "establishing", "aerial", "panorama")):
        return 2
    return 1


def _comic_shots_can_interpolate(current: dict, following: dict) -> bool:
    """Conservative automatic rule for using the next panel as an end frame."""
    if not current or not following:
        return False
    if current.get("page_number") is None or following.get("page_number") is None:
        return False
    try:
        same_page = int(current.get("page_number")) == int(following.get("page_number"))
    except (TypeError, ValueError):
        same_page = current.get("page_number") == following.get("page_number")
    if not same_page:
        return False

    current_characters = {
        str(value).strip().casefold()
        for value in (current.get("characters") or [])
        if str(value).strip()
    }
    following_characters = {
        str(value).strip().casefold()
        for value in (following.get("characters") or [])
        if str(value).strip()
    }
    if current_characters != following_characters:
        return False

    framing_jump = abs(
        _comic_framing_band(current.get("framing", ""))
        - _comic_framing_band(following.get("framing", ""))
    )
    return framing_jump <= 1


def _comic_end_image_filenames(params: dict, clip_images: list[str]) -> list[str]:
    """Resolve optional per-shot end-frame conditioning.

    This deliberately has nothing to do with edit transitions. Each generated
    clip is assembled later with a hard cut; these images only constrain the
    final frame *inside* an individual I2V generation.
    """
    prepared = params.get("_comic_prepared_end_images")
    if isinstance(prepared, list):
        return [
            str(prepared[index] or "") if index < len(prepared) else ""
            for index in range(len(clip_images))
        ]

    raw_mode = params.get("comic_end_frame_mode")
    if raw_mode is None:
        # Backward compatibility for resumable pipelines made before the
        # end-frame/transition concepts were separated.
        raw_mode = params.get("comic_anchor_mode") or "start_only"
    mode = {
        "start_only": "none",
        "chain": "all",
    }.get(str(raw_mode).strip().lower(), str(raw_mode).strip().lower())
    shots = params.get("comic_shots") or []
    resolved = [""] * len(clip_images)
    for index in range(max(0, len(clip_images) - 1)):
        current = shots[index] if index < len(shots) and isinstance(shots[index], dict) else {}
        following = shots[index + 1] if index + 1 < len(shots) and isinstance(shots[index + 1], dict) else {}
        override_raw = current.get("end_frame_mode")
        if override_raw is None:
            # Legacy saved comic shots used transition terminology even though
            # the value always controlled I2V end-image conditioning.
            override_raw = current.get("transition_to_next") or "auto"
        override = {
            "cut": "none",
            "interpolate": "next-panel",
        }.get(str(override_raw).strip().lower(), str(override_raw).strip().lower())
        if override == "none":
            should_anchor = False
        elif override == "next-panel":
            should_anchor = True
        elif mode == "all":
            should_anchor = True
        elif mode == "smart":
            should_anchor = _comic_shots_can_interpolate(current, following)
        else:
            should_anchor = False
        if should_anchor and clip_images[index + 1]:
            resolved[index] = clip_images[index + 1]
    return resolved


_COMIC_LOCKED_CAMERA_NEGATIVE = (
    "camera zoom, push-in, pull-out, dolly, pan, tilt, crane, pedestal, "
    "camera roll, reframing, drifting crop, top-to-bottom camera movement"
)

_COMIC_REFERENCE_NEGATIVE = (
    "new subject, appearing character, disappearing character, replacement "
    "character, scene replacement, background replacement, restyling, "
    "photorealistic conversion, identity change, costume change, palette "
    "change, linework change, redraw"
)


def _comic_renderer(
    params: dict,
    index: int,
    plan: Optional[dict] = None,
) -> str:
    """Return the effective shot renderer with legacy aliases."""
    plan = plan or {}
    metadata = _clip_metadata(plan)
    shot = _comic_shot(params, index)
    raw = str(
        plan.get("renderer")
        or metadata.get("renderer")
        or shot.get("renderer")
        or "ltx"
    ).strip().lower()
    return {
        "still": "hold",
        "static": "hold",
        "image": "hold",
        "2.5d": "parallax",
        "2_5d": "parallax",
        "living-still": "cinemagraph",
        "living_still": "cinemagraph",
        "contextual": "ltx",
        "action": "ltx",
        "i2v": "ltx",
    }.get(raw, raw if raw in {"hold", "parallax", "cinemagraph", "ltx"} else "ltx")


def _comic_motion_level(
    params: dict,
    index: int,
    plan: Optional[dict] = None,
) -> int:
    """Resolve the authored 0–3 motion intensity for one shot."""
    plan = plan or {}
    metadata = _clip_metadata(plan)
    shot = _comic_shot(params, index)
    requested_renderer = _comic_renderer(params, index, plan)
    if requested_renderer == "hold":
        return 0
    if requested_renderer in {"parallax", "cinemagraph"}:
        return 1
    default = (
        1
        if _comic_motion_mode(params, index) == "living-still"
        else 2
    )
    for source in (plan, metadata, shot):
        if "motion_level" not in source:
            continue
        try:
            return max(0, min(3, int(source["motion_level"])))
        except (TypeError, ValueError):
            continue
    return default


def _comic_effective_renderer(
    params: dict,
    index: int,
    plan: Optional[dict] = None,
) -> str:
    """Apply motion-level policy without erasing the requested renderer."""
    renderer = _comic_renderer(params, index, plan)
    # Level zero is a true deterministic hold.  Sending an allegedly static
    # shot through diffusion wastes time and is exactly how unwanted zoom,
    # redraw and character drift entered earlier comic films.
    if _comic_motion_level(params, index, plan) == 0:
        return "hold"
    return renderer


def _comic_motion_mode(params: dict, index: int) -> str:
    """Return a backwards-compatible per-panel comic motion treatment."""
    shot = _comic_shot(params, index)
    raw = str(
        shot.get("motion_mode")
        or params.get("comic_motion_treatment")
        or "action"
    ).strip().lower()
    if raw in {"living-still", "living_still", "still"}:
        return "living-still"
    if raw in {"contextual", "context", "directed"}:
        return "contextual"
    return "action"


def _comic_camera_is_locked(
    params: dict,
    index: int,
    plan: Optional[dict] = None,
) -> bool:
    """Treat absent comic camera instructions as an intentional static shot."""
    if _comic_motion_mode(params, index) == "living-still":
        return True
    if _comic_motion_level(params, index, plan) <= 1:
        return True
    plan = plan or {}
    metadata = _clip_metadata(plan)
    shot = _comic_shot(params, index)
    camera = str(
        plan.get("camera_move")
        or plan.get("camera")
        or metadata.get("camera_move")
        or metadata.get("camera")
        or shot.get("camera_move")
        or shot.get("camera")
        or "none"
    ).strip().lower()
    return camera in {"", "none", "static", "locked", "locked-off", "locked-off camera"}


def _append_negative_prompt(current: str, addition: str) -> str:
    parts = [str(current or "").strip(), str(addition or "").strip()]
    return ", ".join(part for part in parts if part)


def _comic_motion_prompt(
    prompt: str,
    fidelity: str,
    has_end: bool,
    camera_locked: bool = False,
    motion_mode: str = "action",
    motion_level: Optional[int] = None,
) -> str:
    """Build a concise LTX I2V change prompt.

    The approved first frame already defines subjects, style and composition.
    Repeating a visual bible and a wall of prohibitions makes scene
    replacement more likely; this contract describes only change plus a small
    preservation clause.
    """
    fidelity = str(fidelity or "faithful").strip().lower()
    motion_mode = str(motion_mode or "action").strip().lower()
    if motion_level is None:
        motion_level = (
            1
            if motion_mode in {"living-still", "living_still", "still"}
            else 2
        )
    motion_level = max(0, min(3, int(motion_level)))
    base = " ".join(str(prompt or "").split())
    if len(base) > 640:
        base = base[:637].rsplit(" ", 1)[0] + "..."
    additions: list[str] = []
    if motion_level == 0:
        additions.append(
            "No subject or camera motion; hold the approved frame."
        )
    elif motion_level == 1:
        additions.append(
            "Only subtle supported motion: a blink or breath "
            "and slight hair, cloth, dust, light or reflection movement."
        )
    elif motion_level == 2:
        additions.append(
            "Use one contained, readable performance near the approved pose "
            "and staging."
        )
    else:
        additions.append(
            "Perform one clear, readable action with a continuous beginning "
            "and end; do not add a cut or a second event."
        )
    if motion_mode in {"contextual", "context", "directed"}:
        additions.append(
            "Perform only this action, chronologically and without an internal cut."
        )
    if fidelity == "faithful":
        additions.append(
            "Preserve identity, anatomy, costume, linework, palette "
            "and background geometry."
        )
    elif fidelity == "balanced":
        additions.append(
            "Preserve character identity, drawing medium and scene geometry."
        )
    if camera_locked:
        additions.append(
            "Locked camera; keep the exact crop, horizon, perspective and field "
            "of view."
        )
    if has_end:
        additions.append(
            "Finish at the supplied approved end keyframe without a cut."
        )
    return " ".join(part for part in (base, *additions) if part).strip()


def _build_comic_video_previews(
    pid: str,
    params: dict,
    clip_plans: list[dict],
    planned_clips: list[dict],
    clip_images: list[str],
    out_dir: str,
) -> tuple[list[dict], list[str]]:
    """Freeze the effective per-shot inputs shown by Comic PRE.

    The effective prompt and frame count are written back into the plans that
    video generation consumes.  This makes the PRE a contract rather than an
    estimate: generating one clip later cannot silently re-plan or reinterpret
    what the user approved.
    """
    video_model = str(params.get("video_model") or "ltx2_22B_distilled")
    video_params = dict(params.get("video_params") or {})
    resolution = _normalize_video_resolution(
        video_model,
        video_params.get("resolution", "1280x720"),
    )
    video_params["resolution"] = resolution
    params["video_params"] = video_params

    fps = int(params.get("fps") or 16)
    try:
        model_def = _wgp.get_model_def(video_model) or {}
        fps = int(model_def.get("fps") or fps)
    except Exception:
        pass
    try:
        minimum_frames, _frame_step, latent_step = (
            _wgp.get_model_min_frames_and_step(video_model)
        )
    except Exception:
        minimum_frames, latent_step = 17, 8

    def quantize_nearest(frame_count: float) -> int:
        return max(
            round((frame_count - 1) / latent_step) * latent_step + 1,
            minimum_frames,
        )

    raw_frames: list[int] = []
    requested_durations: list[float] = []
    for index, plan in enumerate(clip_plans):
        planned = planned_clips[index] if index < len(planned_clips) else {}
        duration = planned.get("duration_sec") or (
            planned.get("end", 0) - planned.get("start", 0)
        )
        if not duration:
            duration_frames = planned.get("duration_frames")
            duration = (
                float(duration_frames) / fps
                if duration_frames
                else 3.0
            )
        duration = max(0.8, min(20.0, float(duration)))
        requested_durations.append(duration)
        frame_count = max(round(duration * fps), minimum_frames)
        raw_frames.append(frame_count)

    effective_frames: list[int] = []
    carry = 0.0
    for frame_count in raw_frames:
        target = frame_count + carry
        quantized = quantize_nearest(target)
        carry = target - quantized
        effective_frames.append(quantized)

    end_images = _comic_end_image_filenames(params, clip_images)
    fidelity = str(params.get("comic_motion_fidelity") or "faithful")
    pipeline = _pipelines.get(pid, {})
    source_sizes = pipeline.get("_clip_source_sizes") or []
    source_images = pipeline.get("_clip_source_images") or []
    fit_details = pipeline.get("_clip_fit_details") or []
    runtime = _effective_ltx_runtime(video_model, video_params)
    steps = int(runtime["num_inference_steps"])
    stage2_steps = int(runtime["stage2_steps"])
    guidance = float(runtime["guidance_scale"])
    input_strength = float(
        video_params.get(
            "input_video_strength",
            0.7 if "distilled" in video_model.lower() else 1.0,
        )
    )
    if fidelity.lower() == "faithful":
        input_strength = max(0.9, input_strength)
    elif any(end_images):
        input_strength = max(0.8, input_strength)

    base_negative_prompt = _append_negative_prompt(
        str(video_params.get("negative_prompt") or "").strip(),
        _COMIC_REFERENCE_NEGATIVE,
    )
    per_clip_negative_prompts = [
        _append_negative_prompt(
            base_negative_prompt,
            _COMIC_LOCKED_CAMERA_NEGATIVE,
        )
        if _comic_camera_is_locked(params, index, plan)
        else base_negative_prompt
        for index, plan in enumerate(clip_plans)
    ]
    # Keep the scalar field for old checkpoints and non multi-clip callers,
    # but freeze the exact per-shot values that PRE displays.  A locked hold
    # must not accidentally force "static camera" into an authored pan.
    params["_effective_video_negative_prompt"] = base_negative_prompt
    params["_effective_video_negative_prompts"] = (
        per_clip_negative_prompts
    )

    previews: list[dict] = []
    for index, plan in enumerate(clip_plans):
        metadata = _clip_metadata(plan)
        shot = _comic_shot(params, index)
        windows = plan.get("window_prompts") or []
        windows = [
            window.get("prompt", window.get("text", str(window)))
            if isinstance(window, dict)
            else str(window)
            for window in windows
        ]
        metadata_motion = metadata.get("motion_only_prompt")
        plan_motion = plan.get("motion_only_prompt")
        base_prompt = str(
            (
                metadata_motion
                if isinstance(metadata_motion, str)
                else ""
            )
            or (
                plan_motion
                if isinstance(plan_motion, str)
                else ""
            )
            or (
                "\n".join(windows)
                if len(windows) > 1
                else plan.get("video_prompt")
            )
            or shot.get("action")
            or metadata.get("action")
            or ""
        )
        camera_locked = _comic_camera_is_locked(params, index, plan)
        motion_mode = _comic_motion_mode(params, index)
        renderer = _comic_renderer(params, index, plan)
        effective_renderer = _comic_effective_renderer(
            params,
            index,
            plan,
        )
        motion_level = _comic_motion_level(params, index, plan)
        requested_camera_move = str(
            plan.get("camera_move")
            or plan.get("camera")
            or metadata.get("camera_move")
            or metadata.get("camera")
            or shot.get("camera_move")
            or shot.get("camera")
            or "none"
        )
        effective_camera_move = (
            "none" if camera_locked else requested_camera_move
        )
        prompt_override = plan.get("_preflight_prompt_override")
        prompt_overridden = prompt_override is not None
        effective_prompt = (
            " ".join(str(prompt_override).split())[:1200]
            if prompt_override is not None
            else _comic_motion_prompt(
                base_prompt,
                fidelity,
                bool(end_images[index] if index < len(end_images) else ""),
                camera_locked=camera_locked,
                motion_mode=motion_mode,
                motion_level=motion_level,
            )
        )
        plan["_effective_video_prompt"] = effective_prompt
        plan["_effective_video_frames"] = effective_frames[index]
        plan["renderer"] = renderer
        plan["seed"] = _comic_shot_seed(params, index, plan)
        planned = planned_clips[index] if index < len(planned_clips) else {}
        planned["_effective_video_frames"] = effective_frames[index]
        planned["duration_sec"] = requested_durations[index]
        duration_seconds = requested_durations[index]
        source_size = (
            source_sizes[index]
            if index < len(source_sizes)
            else None
        )
        fit_detail = (
            fit_details[index]
            if index < len(fit_details)
            and isinstance(fit_details[index], dict)
            else {}
        )
        shot_id = _stable_comic_shot_id(params, index, plan)
        source_panel_ids = (
            metadata.get("source_panel_ids")
            or shot.get("source_panel_ids")
            or [shot.get("panel_id") or shot.get("id")]
        )
        source_panel_ids = [
            str(value)
            for value in source_panel_ids
            if value not in (None, "")
        ]
        risk_tags = list(
            dict.fromkeys(
                [
                    *(
                        metadata.get("risk_tags")
                        if isinstance(metadata.get("risk_tags"), list)
                        else []
                    ),
                    *(
                        shot.get("risk_tags")
                        if isinstance(shot.get("risk_tags"), list)
                        else []
                    ),
                    *(
                        ["aspect-mismatch"]
                        if fit_detail.get("needs_reframe")
                        else []
                    ),
                ]
            )
        )
        previews.append({
            "index": index,
            "order": index,
            "included": shot.get("included", True) is not False,
            "shot_id": shot_id,
            "panel_id": (
                shot.get("panel_id")
                or metadata.get("primary_source_panel_id")
            ),
            "source_panel_ids": source_panel_ids,
            "page_number": (
                (params.get("comic_shots") or [{}])[index].get("page_number")
                if index < len(params.get("comic_shots") or [])
                else None
            ),
            "panel_number": (
                (params.get("comic_shots") or [{}])[index].get("panel_number")
                if index < len(params.get("comic_shots") or [])
                else None
            ),
            "label": (
                planned.get("section_label")
                or planned.get("label")
                or f"Clip {index + 1}"
            ),
            "image_filename": (
                clip_images[index] if index < len(clip_images) else ""
            ),
            "source_image_filename": (
                source_images[index] if index < len(source_images) else ""
            ),
            "end_image_filename": (
                end_images[index] if index < len(end_images) else ""
            ),
            "source_resolution": (
                f"{source_size[0]}x{source_size[1]}"
                if isinstance(source_size, (list, tuple))
                and len(source_size) == 2
                else ""
            ),
            "input_resolution": resolution,
            "output_resolution": resolution,
            "video_model": video_model,
            "base_prompt": " ".join(base_prompt.split()),
            "prompt": effective_prompt,
            "prompt_overridden": prompt_overridden,
            "negative_prompt": per_clip_negative_prompts[index],
            "num_inference_steps": steps,
            "stage2_steps": stage2_steps,
            "guidance_scale": guidance,
            "runtime_recipe": runtime["recipe"],
            "requested_num_inference_steps": runtime[
                "requested_num_inference_steps"
            ],
            "requested_stage2_steps": runtime[
                "requested_stage2_steps"
            ],
            "requested_guidance_scale": runtime[
                "requested_guidance_scale"
            ],
            "guidance_note": runtime["guidance_note"],
            "input_video_strength": input_strength,
            "seed": _comic_shot_seed(params, index, plan),
            "fps": fps,
            "frames": effective_frames[index],
            "output_frames": max(1, round(duration_seconds * fps)),
            "duration_seconds": round(duration_seconds, 3),
            "image_prompt_type": (
                "SE"
                if index < len(end_images) and end_images[index]
                else "S"
            ),
            "fit_mode": (
                fit_detail.get("requested_fit_mode")
                or shot.get("fit_mode")
                or params.get("video_image_fit", "contain")
            ),
            "effective_fit_mode": fit_detail.get("effective_fit_mode"),
            "retained_fraction": fit_detail.get("retained_fraction"),
            "needs_reframe": bool(fit_detail.get("needs_reframe")),
            "reframe_approved": bool(fit_detail.get("reframe_approved")),
            "used_prepared_keyframe": bool(
                fit_detail.get("used_prepared_keyframe")
            ),
            "renderer": renderer,
            "effective_renderer": effective_renderer,
            "motion_level": motion_level,
            "action": str(
                shot.get("action") or metadata.get("action") or base_prompt
            ),
            # Keep the complete editorial line in PRE even though the compact
            # LTX motion prompt may include only a bounded spoken excerpt.
            # This is script metadata, not a promise of deterministic TTS.
            "dialogue": str(
                shot.get("dialogue") or metadata.get("dialogue") or ""
            ),
            "requested_camera_move": requested_camera_move,
            "camera_move": effective_camera_move,
            "end_beat": str(
                shot.get("end_beat") or metadata.get("end_beat") or ""
            ),
            "test_selected": bool(
                shot.get("test_selected")
                or metadata.get("test_selected")
            ),
            "risk_tags": risk_tags,
            "motion_mode": motion_mode,
            "camera_locked": camera_locked,
            "fidelity": fidelity,
            "self_refiner": params.get("video_self_refiner", 0),
            "spatial_upsampling": params.get("video_spatial_upsampling", ""),
            "film_grain_intensity": params.get(
                "video_film_grain_intensity",
                0,
            ),
            "film_grain_saturation": params.get(
                "video_film_grain_saturation",
                0.5,
            ),
            "single_stage_pipeline": video_params.get(
                "single_stage_pipeline",
                0,
            ),
            "progressive_pipeline": video_params.get(
                "progressive_pipeline",
                0,
            ),
            "activated_loras": (
                (params.get("video_loras") or {}).get(
                    "activated_loras",
                    [],
                )
            ),
            "lora_multipliers": (
                (params.get("video_loras") or {}).get(
                    "loras_multipliers",
                    "",
                )
            ),
        })

    # Planning chooses representative tests before the real source dimensions
    # and fit loss are known. Re-select once PRE has measured them so at least
    # one destructive aspect mismatch is exercised. Explicit per-shot user
    # overrides remain authoritative.
    has_test_override = any(
        bool(
            (_comic_shot(params, index) or {}).get(
                "test_selected_override"
            )
            or (
                _clip_metadata(plan).get("test_selected_override")
                if isinstance(plan, dict)
                else False
            )
        )
        for index, plan in enumerate(clip_plans)
    )
    if previews and not has_test_override:
        try:
            from .director.planners.comic_movie import (
                select_representative_shot_indices,
            )

            first_mismatch = next(
                (
                    index
                    for index, preview in enumerate(previews)
                    if preview.get("needs_reframe")
                    or (
                        preview.get("retained_fraction") is not None
                        and float(preview["retained_fraction"]) < 0.65
                    )
                ),
                None,
            )
            selected_indices = (
                [first_mismatch] if first_mismatch is not None else []
            )
            selected_indices.extend(
                select_representative_shot_indices(
                    previews,
                    max_count=6,
                )
            )
            selected_indices = list(dict.fromkeys(selected_indices))[:6]
        except Exception:
            selected_indices = [
                index
                for index, preview in enumerate(previews)
                if preview.get("test_selected")
            ][:6]
        selected_set = set(selected_indices)
        for index, (preview, plan) in enumerate(
            zip(previews, clip_plans)
        ):
            selected = index in selected_set
            preview["test_selected"] = selected
            shot = _comic_shot(params, index)
            shot["test_selected"] = selected
            metadata = (
                dict(plan.get("metadata"))
                if isinstance(plan.get("metadata"), dict)
                else {}
            )
            metadata["test_selected"] = selected
            plan["metadata"] = metadata

    fingerprint = _comic_preflight_fingerprint(
        params,
        clip_plans,
        planned_clips,
        clip_images,
        out_dir,
    )
    params["_comic_preflight_fingerprint"] = fingerprint
    for preview in previews:
        preview["preflight_fingerprint"] = fingerprint
    _update_pipeline(
        pid,
        _comic_preflight_fingerprint=fingerprint,
        _preview_revision=int(pipeline.get("_preview_revision") or 1),
    )
    return previews, end_images


def _comic_ffmpeg_binary() -> str:
    return os.environ.get("FFMPEG_BINARY", "ffmpeg")


def _comic_ffprobe_binary() -> str:
    configured = os.environ.get("FFPROBE_BINARY")
    if configured:
        return configured
    ffmpeg = _comic_ffmpeg_binary()
    basename = os.path.basename(ffmpeg)
    if basename == "ffmpeg":
        return os.path.join(os.path.dirname(ffmpeg), "ffprobe") or "ffprobe"
    return "ffprobe"


def _comic_source_has_audio(path: str) -> bool:
    """Return whether the source has an audio stream; malformed means no."""
    try:
        result = subprocess.run(
            [
                _comic_ffprobe_binary(),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _comic_resolution_tuple(resolution: str) -> tuple[int, int]:
    try:
        width, height = (
            int(value)
            for value in str(resolution).lower().split("x", 1)
        )
    except (TypeError, ValueError):
        return 1280, 704
    return max(2, width - width % 2), max(2, height - height % 2)


def _run_comic_ffmpeg(command: list[str], label: str) -> None:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{label} failed: {(result.stderr or result.stdout)[-800:]}"
        )


def _render_deterministic_comic_clip(
    image_path: str,
    output_path: str,
    renderer: str,
    duration_seconds: float,
    fps: int,
    resolution: str,
) -> None:
    """Render exact still/parallax shots without invoking a diffusion model."""
    width, height = _comic_resolution_tuple(resolution)
    output_frames = max(1, round(duration_seconds * fps))
    if renderer == "parallax":
        # Intentionally tiny and centered: at most 1.5% over the full shot.
        # This gives a deterministic 2.5D-like breath without the giant
        # push-ins and vertical drift that made earlier comic films unusable.
        increment = 0.015 / max(1, output_frames - 1)
        video_filter = (
            f"scale={width}:{height}:flags=lanczos,"
            f"zoompan=z='min(zoom+{increment:.9f},1.015)':"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:s={width}x{height}:fps={fps},format=yuv420p"
        )
    else:
        video_filter = (
            f"scale={width}:{height}:flags=lanczos,"
            f"fps={fps},format=yuv420p"
        )
    temporary = f"{output_path}.{uuid.uuid4().hex[:8]}.tmp.mp4"
    try:
        _run_comic_ffmpeg(
            [
                _comic_ffmpeg_binary(),
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(fps),
                "-i",
                image_path,
                "-vf",
                video_filter,
                "-frames:v",
                str(output_frames),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "17",
                "-pix_fmt",
                "yuv420p",
                temporary,
            ],
            f"Comic {renderer} render",
        )
        os.replace(temporary, output_path)
    finally:
        if os.path.isfile(temporary):
            os.remove(temporary)


def _normalize_comic_clip_duration(
    source_path: str,
    output_path: str,
    duration_seconds: float,
    fps: int,
    resolution: str,
) -> None:
    """Make every clip match duration/canvas and carry a uniform AAC stream.

    Generated LTX clips may contain dialogue or ambience while deterministic
    hold/parallax shots are silent.  Every normalized segment gets stereo AAC:
    existing audio is preserved, padded and trimmed; otherwise a silent stream
    is synthesized.  This makes mixed-renderer hard-cut concatenation reliable
    without erasing LTX audio.
    """
    width, height = _comic_resolution_tuple(resolution)
    output_frames = max(1, round(duration_seconds * fps))
    temporary = f"{output_path}.{uuid.uuid4().hex[:8]}.tmp.mp4"
    has_audio = _comic_source_has_audio(source_path)
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease:"
        "flags=lanczos,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"fps={fps},tpad=stop_mode=clone:stop_duration=20,"
        f"trim=duration={duration_seconds:.6f},"
        f"setpts=N/({fps}*TB),format=yuv420p"
    )
    audio_filter = (
        "aresample=48000:async=1:first_pts=0,"
        f"apad,atrim=duration={duration_seconds:.6f},"
        "asetpts=N/SR/TB"
    )
    command = [
        _comic_ffmpeg_binary(),
        "-y",
        "-i",
        source_path,
    ]
    if not has_audio:
        command.extend([
            "-f",
            "lavfi",
            "-t",
            f"{duration_seconds:.6f}",
            "-i",
            "anullsrc=r=48000:cl=stereo",
        ])
    command.extend([
        "-map",
        "0:v:0",
        "-map",
        "0:a:0" if has_audio else "1:a:0",
        "-vf",
        video_filter,
        "-af",
        audio_filter,
        "-frames:v",
        str(output_frames),
        "-t",
        f"{duration_seconds:.6f}",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "17",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        temporary,
    ])
    try:
        _run_comic_ffmpeg(
            command,
            "Comic exact-duration normalization",
        )
        os.replace(temporary, output_path)
    finally:
        if os.path.isfile(temporary):
            os.remove(temporary)


def _comic_frame_signature(frame) -> str:
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    tiny = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
    return hashlib.sha256(tiny.tobytes()).hexdigest()


def _validate_comic_clip(
    video_path: str,
    source_image_path: str,
    renderer: str,
    requested_frames: int,
    fps: int,
    resolution: str,
    camera_locked: bool,
) -> dict:
    """Run inexpensive first-frame, duration and drift checks without GPU."""
    import cv2
    import numpy as np

    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict = {}
    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        return {
            "passed": False,
            "failures": ["unreadable-output"],
            "warnings": [],
            "metrics": {},
        }
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    actual_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    sample_indices = [0, max(0, frame_count // 2), max(0, frame_count - 1)]
    frames = []
    for frame_index in sample_indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        frames.append(frame if ok else None)
    capture.release()

    target_width, target_height = _comic_resolution_tuple(resolution)
    metrics.update({
        "frames": frame_count,
        "fps": round(actual_fps, 4),
        "width": width,
        "height": height,
    })
    if abs(frame_count - requested_frames) > 1:
        failures.append(
            f"duration-mismatch:{frame_count}!={requested_frames}"
        )
    if (width, height) != (target_width, target_height):
        failures.append(
            f"canvas-mismatch:{width}x{height}!="
            f"{target_width}x{target_height}"
        )
    if not frames[0] is None and os.path.isfile(source_image_path):
        source = cv2.imread(source_image_path)
        if source is not None:
            source = cv2.resize(
                source,
                (frames[0].shape[1], frames[0].shape[0]),
                interpolation=cv2.INTER_AREA,
            )
            mae = float(
                np.mean(
                    np.abs(
                        source.astype(np.float32)
                        - frames[0].astype(np.float32)
                    )
                )
                / 255.0
            )
            metrics["first_frame_mae"] = round(mae, 5)
            if renderer in {"hold", "parallax"} and mae > 0.08:
                failures.append(f"first-frame-drift:{mae:.3f}")
            elif renderer in {"ltx", "cinemagraph"} and mae > 0.48:
                failures.append(f"probable-scene-replacement:{mae:.3f}")
            elif mae > 0.28:
                warnings.append(f"first-frame-change:{mae:.3f}")

            if camera_locked and frames[-1] is not None:
                source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
                final_gray = cv2.cvtColor(frames[-1], cv2.COLOR_BGR2GRAY)
                detector = cv2.ORB_create(nfeatures=800)
                source_keys, source_desc = detector.detectAndCompute(
                    source_gray, None
                )
                final_keys, final_desc = detector.detectAndCompute(
                    final_gray, None
                )
                if (
                    source_desc is not None
                    and final_desc is not None
                    and len(source_keys) >= 8
                    and len(final_keys) >= 8
                ):
                    matches = cv2.BFMatcher(
                        cv2.NORM_HAMMING, crossCheck=True
                    ).match(source_desc, final_desc)
                    matches = sorted(matches, key=lambda item: item.distance)[
                        :80
                    ]
                    if len(matches) >= 6:
                        source_points = np.float32([
                            source_keys[item.queryIdx].pt for item in matches
                        ])
                        final_points = np.float32([
                            final_keys[item.trainIdx].pt for item in matches
                        ])
                        matrix, _mask = cv2.estimateAffinePartial2D(
                            source_points,
                            final_points,
                            method=cv2.RANSAC,
                        )
                        if matrix is not None:
                            scale = float(
                                np.sqrt(
                                    matrix[0, 0] ** 2
                                    + matrix[0, 1] ** 2
                                )
                            )
                            translation = max(
                                abs(float(matrix[0, 2]))
                                / max(1, width),
                                abs(float(matrix[1, 2]))
                                / max(1, height),
                            )
                            metrics["estimated_scale"] = round(scale, 4)
                            metrics["estimated_translation"] = round(
                                translation, 4
                            )
                            if scale < 0.62 or scale > 1.58:
                                failures.append(
                                    f"locked-camera-scale:{scale:.3f}"
                                )
                            elif scale < 0.80 or scale > 1.24:
                                warnings.append(
                                    f"camera-scale:{scale:.3f}"
                                )
                            if translation > 0.36:
                                failures.append(
                                    "locked-camera-translation:"
                                    f"{translation:.3f}"
                                )
                            elif translation > 0.18:
                                warnings.append(
                                    f"camera-translation:{translation:.3f}"
                                )
    signatures = [
        _comic_frame_signature(frame)
        for frame in frames
        if frame is not None
    ]
    metrics["frame_signatures"] = signatures
    return {
        "passed": not failures,
        "failures": failures,
        "warnings": warnings,
        "metrics": metrics,
    }


def _record_comic_preview_quality(
    child_pid: str,
    validations: list[dict],
) -> None:
    """Propagate a test child's validation result into its durable PRE."""
    child = _pipelines.get(child_pid) or {}
    if child.get("_preview_run_type") != "test":
        return
    parent_pid = child.get("_source_preview_pipeline_id")
    fingerprint = child.get("_source_preview_fingerprint")
    selected = list(child.get("_source_preview_clip_indices") or [])
    if not parent_pid or not fingerprint:
        return
    _update_pipeline(child_pid, _quality_recorded=True)
    if not _pipelines.get(parent_pid):
        parent_out_dir = child.get("out_dir")
        if parent_out_dir:
            try:
                resume_pipeline(parent_pid, parent_out_dir)
            except Exception as exc:
                print(
                    f"[Pipeline {child_pid}] Could not rehydrate PRE "
                    f"{parent_pid} for quality propagation: {exc}"
                )
    with _pipeline_lock:
        parent = _pipelines.get(parent_pid)
        if (
            not parent
            or parent.get("_comic_preflight_fingerprint") != fingerprint
        ):
            return
        previous = (
            dict(parent.get("_quality_gate"))
            if isinstance(parent.get("_quality_gate"), dict)
            and parent.get("_quality_gate", {}).get("fingerprint")
            == fingerprint
            else {}
        )
        required = []
        for value in previous.get("required_test_indices") or selected:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if index >= 0 and index not in required:
                required.append(index)
        results = (
            copy.deepcopy(previous.get("results"))
            if isinstance(previous.get("results"), dict)
            else {}
        )
        validated_at = time.time()
        for local_index, validation in enumerate(validations):
            if local_index >= len(selected):
                break
            original_index = int(selected[local_index])
            item = validation if isinstance(validation, dict) else {}
            item_failures = [
                str(value)
                for value in (item.get("failures") or [])
            ]
            passed = bool(item.get("passed")) and not item_failures
            if not passed and not item_failures:
                item_failures = ["validation-failed"]
            results[str(original_index)] = {
                "passed": passed,
                "failures": item_failures,
                "warnings": [
                    str(value)
                    for value in (item.get("warnings") or [])
                ],
                "metrics": copy.deepcopy(item.get("metrics") or {}),
                "renderer": item.get("renderer"),
                "video_filename": item.get("video_filename"),
                "output_files": (
                    [str(item.get("video_filename"))]
                    if item.get("video_filename")
                    else []
                ),
                "validated_at": validated_at,
            }

        tested_indices = sorted(
            {
                int(key)
                for key in results
                if str(key).lstrip("-").isdigit() and int(key) >= 0
            }
        )
        required_results = [
            results.get(str(index))
            for index in required
        ]
        required_failures: list[str] = []
        for index, result in zip(required, required_results):
            if isinstance(result, dict) and not result.get("passed"):
                failures = result.get("failures") or ["validation-failed"]
                required_failures.extend(
                    f"shot {index + 1}: {failure}"
                    for failure in failures
                )
        if required_failures:
            status = "failed"
        elif required and all(
            isinstance(result, dict) and result.get("passed")
            for result in required_results
        ):
            # Automatic checks are necessary but not sufficient.  The user
            # must inspect the representative clips and explicitly accept
            # them before the expensive full run is unlocked.
            status = "review_required"
        else:
            status = "pending"
        parent["_quality_gate"] = {
            **previous,
            "status": status,
            "fingerprint": fingerprint,
            "required_test_indices": required,
            "tested_indices": tested_indices,
            "results": results,
            "failures": required_failures,
            "validated_at": validated_at,
        }
    _save_pipeline_state(parent_pid)


def _run_comic_renderer_pipeline(
    pid: str,
    params: dict,
    clip_plans: list[dict],
    planned_clips: list[dict],
    clip_images: list[str],
    clip_keyframes: Optional[list[list[str]]],
    out_dir: str,
    workspace: Optional[str],
) -> list[str]:
    """Dispatch comic shots to deterministic or generative renderers."""
    video_model = str(
        params.get("video_model") or "ltx2_22B_distilled_1_1"
    )
    video_params = dict(params.get("video_params") or {})
    resolution = _normalize_video_resolution(
        video_model,
        video_params.get("resolution", "1280x720"),
    )
    video_params["resolution"] = resolution
    runtime = _effective_ltx_runtime(video_model, video_params)
    video_params["num_inference_steps"] = runtime["num_inference_steps"]
    video_params["guidance_scale"] = runtime["guidance_scale"]
    video_params["stage2_steps"] = runtime["stage2_steps"]
    params["video_params"] = video_params

    fps = int(params.get("fps") or 25)
    try:
        fps = int((_wgp.get_model_def(video_model) or {}).get("fps") or fps)
    except Exception:
        pass
    count = len(clip_plans)
    existing = list(
        (_pipelines.get(pid) or {}).get("_clip_video_files")
        or [None] * count
    )
    if len(existing) < count:
        existing.extend([None] * (count - len(existing)))
    renderers = [
        _comic_effective_renderer(params, index, plan)
        for index, plan in enumerate(clip_plans)
    ]
    durations = []
    for index in range(count):
        planned = planned_clips[index] if index < len(planned_clips) else {}
        duration = planned.get("duration_sec") or (
            planned.get("end", 0) - planned.get("start", 0)
        )
        durations.append(max(0.8, min(20.0, float(duration or 3.0))))

    generative_indices: list[int] = []
    for index, renderer in enumerate(renderers):
        if _pipeline_cancel_requested(pid):
            raise PipelineCancelled("Director pipeline was cancelled.")
        current = str(existing[index] or "")
        current_path = (
            current
            if os.path.isabs(current)
            else os.path.join(out_dir, current)
        )
        if current and os.path.isfile(current_path):
            continue
        if renderer in {"hold", "parallax"}:
            image_path = os.path.join(out_dir, clip_images[index])
            output_name = (
                f"comic_{pid}_{index + 1:04d}_{renderer}.mp4"
            )
            _render_deterministic_comic_clip(
                image_path,
                os.path.join(out_dir, output_name),
                renderer,
                durations[index],
                fps,
                resolution,
            )
            existing[index] = output_name
            _update_pipeline(pid, _clip_video_files=list(existing))
            _save_pipeline_state(pid)
        else:
            generative_indices.append(index)

    if generative_indices:
        selected_plans = [
            copy.deepcopy(clip_plans[index])
            for index in generative_indices
        ]
        selected_planned = [
            copy.deepcopy(
                planned_clips[index]
                if index < len(planned_clips)
                else {}
            )
            for index in generative_indices
        ]
        selected_images = [clip_images[index] for index in generative_indices]
        selected_keyframes = [
            copy.deepcopy(
                clip_keyframes[index]
                if clip_keyframes and index < len(clip_keyframes)
                else []
            )
            for index in generative_indices
        ]
        selected_shots = [
            copy.deepcopy(_comic_shot(params, index))
            for index in generative_indices
        ]
        for local_index, global_index in enumerate(generative_indices):
            if renderers[global_index] == "cinemagraph":
                selected_shots[local_index]["motion_mode"] = "living-still"
                selected_shots[local_index]["camera_move"] = "none"
        all_end_images = _comic_end_image_filenames(params, clip_images)
        subparams = copy.deepcopy(params)
        subparams.update({
            "seamless": False,
            "_comic_renderer_orchestrated": True,
            "_director_clip_index_map": generative_indices,
            "comic_shots": selected_shots,
            "_comic_prepared_end_images": [
                all_end_images[index] for index in generative_indices
            ],
            "provided_clip_image_paths": [
                (params.get("provided_clip_image_paths") or [])[index]
                if index < len(params.get("provided_clip_image_paths") or [])
                else ""
                for index in generative_indices
            ],
        })
        frozen_negatives = params.get("_effective_video_negative_prompts")
        if isinstance(frozen_negatives, list):
            subparams["_effective_video_negative_prompts"] = [
                frozen_negatives[index]
                for index in generative_indices
                if index < len(frozen_negatives)
            ]
        _run_video_generation(
            pid,
            subparams,
            selected_plans,
            selected_planned,
            selected_images,
            selected_keyframes,
            out_dir=out_dir,
            workspace=workspace,
        )
        existing = list(
            (_pipelines.get(pid) or {}).get("_clip_video_files")
            or existing
        )

    normalized_files: list[str] = []
    validations: list[dict] = []
    signature_owners: dict[tuple[str, ...], int] = {}
    for index in range(count):
        if _pipeline_cancel_requested(pid):
            raise PipelineCancelled("Director pipeline was cancelled.")
        raw_name = str(existing[index] or "")
        raw_path = (
            raw_name
            if os.path.isabs(raw_name)
            else os.path.join(out_dir, raw_name)
        )
        if not os.path.isfile(raw_path):
            raise RuntimeError(
                f"Comic shot {index + 1} has no completed video checkpoint."
            )
        normalized_name = (
            f"comic_{pid}_{index + 1:04d}_{renderers[index]}_exact.mp4"
        )
        normalized_path = os.path.join(out_dir, normalized_name)
        if os.path.abspath(raw_path) != os.path.abspath(normalized_path):
            _normalize_comic_clip_duration(
                raw_path,
                normalized_path,
                durations[index],
                fps,
                resolution,
            )
        source_path = os.path.join(out_dir, clip_images[index])
        validation = _validate_comic_clip(
            normalized_path,
            source_path,
            renderers[index],
            max(1, round(durations[index] * fps)),
            fps,
            resolution,
            _comic_camera_is_locked(params, index, clip_plans[index]),
        )
        signature = tuple(
            validation.get("metrics", {}).get("frame_signatures") or []
        )
        if (
            signature
            and signature in signature_owners
            and renderers[index] in {"ltx", "cinemagraph"}
        ):
            validation["passed"] = False
            validation.setdefault("failures", []).append(
                "duplicate-generated-output:"
                f"{signature_owners[signature] + 1}"
            )
        else:
            signature_owners[signature] = index
        validation.update({
            "index": index,
            "renderer": renderers[index],
            "video_filename": normalized_name,
        })
        validations.append(validation)
        normalized_files.append(normalized_name)
        existing[index] = normalized_name
        _update_pipeline(
            pid,
            _clip_video_files=list(existing),
            _clip_validations=list(validations),
            progress={
                "current": index + 1,
                "total": count,
                "message": f"Validated comic shot {index + 1}/{count}",
                "step": 0,
                "total_steps": 0,
            },
        )
        _save_pipeline_state(pid)

    _record_comic_preview_quality(pid, validations)
    failed = [
        validation
        for validation in validations
        if not validation.get("passed")
    ]
    if failed:
        # Preserve failed media on disk for diagnosis, but clear only those
        # checkpoint slots. Resume will regenerate the failed shots while
        # reusing neighbours that already passed validation.
        resumable_files = list(existing)
        for validation in failed:
            failed_index = int(validation.get("index", -1))
            if 0 <= failed_index < len(resumable_files):
                resumable_files[failed_index] = None
        _update_pipeline(
            pid,
            _clip_video_files=resumable_files,
            _clip_validations=list(validations),
        )
        _save_pipeline_state(pid)
        details = "; ".join(
            f"shot {item['index'] + 1}: "
            + ", ".join(item.get("failures") or ["validation failed"])
            for item in failed
        )
        raise RuntimeError(
            "Comic clip validation blocked final assembly. Completed clips "
            f"remain resumable. {details}"
        )

    if len(normalized_files) == 1:
        return normalized_files
    final_name = (
        f"comic_{pid}_r"
        f"{int((_pipelines.get(pid) or {}).get('_preview_revision') or 1)}"
        "_movie.mp4"
    )
    final_path = os.path.join(out_dir, final_name)
    clip_paths = [os.path.join(out_dir, name) for name in normalized_files]
    if _pipeline_cancel_requested(pid):
        raise PipelineCancelled("Director pipeline was cancelled.")
    concatenate = getattr(
        _wgp,
        "concatenate_multi_clip_videos",
        None,
    )
    if not callable(concatenate) or not concatenate(
        clip_paths,
        final_path,
        None,
    ):
        raise RuntimeError(
            "All comic shots passed validation, but final hard-cut assembly "
            "failed. Individual clip checkpoints were preserved."
        )
    return [final_name]


def _minimax_h3_frame_segments(
    duration_sec: float,
    fps: int = 24,
    target_frames: int = 124,
) -> list[int]:
    """Split a requested duration into H3's 17n+5 frame lattice.

    Open H3 accepts 107..362 frames per request. Director targets the model's
    recommended 124-frame (~5.2 s) clip length instead of filling the 15 s
    maximum: shorter segments follow a small sequence of actions much more
    reliably and make continuity failures cheaper to reroll.
    """
    minimum, maximum, step, offset = 107, 362, 17, 5
    requested = max(minimum, round(max(0.0, float(duration_sec)) * fps))
    target_frames = max(minimum, min(maximum, int(target_frames or 124)))
    count = max(1, round(requested / target_frames))
    count = min(count, max(1, requested // minimum))
    target = requested / count

    def quantize(value: float) -> int:
        aligned = round((value - offset) / step) * step + offset
        return max(minimum, min(maximum, aligned))

    segments = [quantize(target) for _ in range(count)]
    # Adjust by whole latent steps until the total is within half a step of
    # the request (or no segment can move further).
    while requested - sum(segments) > step / 2:
        candidates = [index for index, value in enumerate(segments) if value + step <= maximum]
        if not candidates:
            break
        index = max(candidates, key=lambda item: target - segments[item])
        segments[index] += step
    while sum(segments) - requested > step / 2:
        candidates = [index for index, value in enumerate(segments) if value - step >= minimum]
        if not candidates:
            break
        index = max(candidates, key=lambda item: segments[item] - target)
        segments[index] -= step
    return segments


def _minimax_h3_audio_direction(
    plan: dict,
    global_direction: str = "",
    segment_index: int = 0,
    segment_count: int = 1,
) -> str:
    """Render Director's structured per-shot sound plan for H3."""
    audio_plan = plan.get("audio_plan") if isinstance(plan.get("audio_plan"), dict) else {}
    parts: list[str] = []

    ambience = " ".join(str(audio_plan.get("ambience") or "").split())
    if ambience:
        parts.append(f"Ambience: {ambience}.")

    raw_effects = audio_plan.get("effects") or []
    if isinstance(raw_effects, str):
        raw_effects = [raw_effects]
    effects = [" ".join(str(effect).split()) for effect in raw_effects if str(effect).strip()]
    if effects:
        parts.append(f"Sound effects: {', '.join(effects)}.")

    dialogue_lines: list[str] = []
    all_dialogue_beats = list(plan.get("dialogue_beats") or [])
    if segment_count > 1 and all_dialogue_beats:
        start = segment_index * len(all_dialogue_beats) // segment_count
        end = (segment_index + 1) * len(all_dialogue_beats) // segment_count
        dialogue_beats = all_dialogue_beats[start:end]
    else:
        dialogue_beats = all_dialogue_beats
    for beat in dialogue_beats:
        if not isinstance(beat, dict):
            continue
        spoken = " ".join(str(beat.get("spoken_text") or beat.get("text") or "").split())
        if not spoken:
            continue
        speaker = " ".join(str(beat.get("speaker_name") or beat.get("speaker_id") or "").split())
        delivery = " ".join(str(beat.get("delivery") or "").split())
        cue = f'{speaker + " says " if speaker else "Spoken dialogue "}"{spoken}"'
        if delivery:
            cue += f" ({delivery})"
        dialogue_lines.append(cue)
    if dialogue_lines:
        parts.append("; ".join(dialogue_lines) + ".")

    vocal_style = " ".join(str(audio_plan.get("vocal_style") or "").split())
    if vocal_style:
        parts.append(f"Vocal style: {vocal_style}.")
    if audio_plan.get("lip_sync_critical"):
        parts.append("Natural, precise lip sync for every spoken line.")

    mode = str(audio_plan.get("mode") or "").strip().lower()
    if mode == "ambient_only" and not dialogue_lines:
        parts.append("No spoken dialogue; use natural scene ambience and synchronized action sounds.")
    elif mode == "dialogue_driven" and not dialogue_lines:
        parts.append("Clear foreground speech with natural lip sync over restrained ambience.")

    global_audio = " ".join(str(global_direction or "").split())
    if global_audio:
        parts.append(global_audio)
    return " ".join(parts)


def _h3_sentence_windows(prompt: str, segment_count: int) -> list[str]:
    """Split a long Story prompt into non-repeating action windows."""
    text = re.sub(r"\s*\bAudio\s*:.*$", "", str(prompt or "").strip(), flags=re.I | re.S)
    if segment_count <= 1 or not text:
        return [text]

    marker = "Animate the artwork without changing its visual medium."
    marker_index = text.casefold().find(marker.casefold())
    if marker_index >= 0:
        split_at = marker_index + len(marker)
        prefix, action_text = text[:split_at].strip(), text[split_at:].strip()
    else:
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]
        prefix_parts: list[str] = []
        action_parts: list[str] = []
        for sentence in sentences:
            lower = sentence.casefold()
            if not action_parts and any(token in lower for token in (
                "exact first frame", "preserve its visual medium", "visual style lock:",
                "match this authored medium", "do not restyle",
            )):
                prefix_parts.append(sentence)
            else:
                action_parts.append(sentence)
        prefix = " ".join(prefix_parts)
        action_text = " ".join(action_parts) if action_parts else text

    actions = [item.strip() for item in re.split(r"(?<=[.!?])\s+", action_text) if item.strip()]
    if not actions:
        actions = [action_text]
    windows: list[str] = []
    for index in range(segment_count):
        start = index * len(actions) // segment_count
        end = (index + 1) * len(actions) // segment_count
        selected = actions[start:end]
        if not selected:
            selected = [actions[min(index, len(actions) - 1)]]
        continuity = (
            "Continue directly from the supplied continuity frame; do not repeat "
            "actions from earlier segments. " if index else ""
        )
        action_window = " ".join(selected)
        windows.append(
            " ".join(part for part in (
                prefix,
                continuity + "Perform only these actions in this segment:",
                action_window,
            ) if part).strip()
        )
    return windows


def _h3_apply_reference_contract(prompt: str, reference_mode: str) -> str:
    text = str(prompt or "").strip()
    exact = "Use the supplied image as the exact first frame."
    exact_pattern = r"use the supplied images? as the exact first frame\."
    if reference_mode == "references":
        replacement = (
            "Use the supplied images as visual references for identity, wardrobe, "
            "environment and style. Compose a new opening frame from that reference set."
        )
        text, replacements = re.subn(exact_pattern, replacement, text, flags=re.I)
        if not replacements and "compose a new opening frame" not in text.casefold():
            text = f"{replacement} {text}".strip()
        return text
    authority = (
        "The visible wardrobe and environment in that first frame are authoritative; "
        "ignore later wording that conflicts with their colors or design."
    )
    if "visible wardrobe and environment" not in text.casefold():
        remainder = re.sub(exact_pattern, "", text, flags=re.I).strip()
        text = f"{exact} {authority} {remainder}".strip()
    return text


def _h3_authored_segment_windows(prompts: list[str], segment_count: int) -> list[str]:
    """Split authored windows across H3 segments without replaying whole windows."""
    if not prompts:
        return []
    if segment_count <= 1:
        return [" ".join(prompts)]

    assignments = [
        min(len(prompts) - 1, index * len(prompts) // segment_count)
        for index in range(segment_count)
    ]
    windows: list[str] = []
    for index, source_index in enumerate(assignments):
        assigned_indices = [
            candidate
            for candidate, assignment in enumerate(assignments)
            if assignment == source_index
        ]
        local_index = assigned_indices.index(index)
        local_windows = _h3_sentence_windows(
            prompts[source_index],
            len(assigned_indices),
        )
        windows.append(local_windows[local_index])
    return windows


def _minimax_h3_segment_prompt(
    plan: dict,
    segment_index: int,
    segment_count: int,
    global_audio_direction: str = "",
    reference_mode: str = "first_frame",
) -> str:
    """Choose the authored continuation and attach its explicit audio plan."""
    optimized = plan.get("h3_segment_prompts") or []
    if len(optimized) == segment_count and segment_index < len(optimized):
        prompt = str(optimized[segment_index] or "").strip()
        prompt = _h3_apply_reference_contract(prompt, reference_mode)
        try:
            from services import minimax_h3_service
        except ImportError:  # pytest imports this module through app.services
            from app.services import minimax_h3_service
        return minimax_h3_service.ensure_audio_prompt(
            prompt,
            _minimax_h3_audio_direction(
                plan,
                global_audio_direction,
                segment_index,
                segment_count,
            ),
        )

    window_prompts = plan.get("window_prompts") or []
    normalized = [
        str(item.get("prompt", item.get("text", ""))) if isinstance(item, dict) else str(item)
        for item in window_prompts
    ]
    normalized = [item for item in normalized if item.strip()]
    if normalized:
        prompt = _h3_authored_segment_windows(normalized, segment_count)[segment_index]
    else:
        source = str(plan.get("video_prompt") or "")
        prompt = _h3_sentence_windows(source, segment_count)[segment_index]
    prompt = _h3_apply_reference_contract(prompt, reference_mode)

    try:
        from services import minimax_h3_service
    except ImportError:  # pytest imports this module through app.services
        from app.services import minimax_h3_service
    return minimax_h3_service.ensure_audio_prompt(
        prompt,
        _minimax_h3_audio_direction(
            plan,
            global_audio_direction,
            segment_index,
            segment_count,
        ),
    )


def _h3_parse_optimized_prompts(response: str) -> list[dict]:
    """Parse the grammar-constrained H3 validator response defensively."""
    text = re.sub(r"```(?:json)?\s*|```", "", str(response or ""), flags=re.I).strip()
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(parsed, dict):
        parsed = parsed.get("segments") or []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _h3_preserve_audio_contract(candidate: str, draft: str) -> str:
    """Accept visual phrasing from the validator while keeping authored audio verbatim."""
    draft_parts = re.split(r"\bAudio\s*:", draft, maxsplit=1, flags=re.I)
    if len(draft_parts) != 2:
        return candidate.strip()
    visual = re.split(r"\bAudio\s*:", candidate, maxsplit=1, flags=re.I)[0].strip()
    return f"{visual}\nAudio: {draft_parts[1].strip()}".strip()


def _h3_validated_candidate(candidate: str, draft: str, reference_mode: str) -> str:
    """Reject optimizer drift and reapply contracts the LLM is not allowed to alter."""
    candidate = _h3_preserve_audio_contract(str(candidate or ""), draft)
    candidate = _h3_apply_reference_contract(candidate, reference_mode)
    if len(candidate) < max(40, len(draft) // 3) or len(candidate) > max(6000, len(draft) * 2):
        return ""
    if "audio:" not in candidate.casefold():
        return ""
    if "visual style lock:" in draft.casefold() and "visual style lock:" not in candidate.casefold():
        return ""
    for quoted in re.findall(r'"([^"\n]+)"', draft):
        if quoted not in candidate:
            return ""
    if reference_mode == "references" and "exact first frame" in candidate.casefold():
        return ""
    if reference_mode == "first_frame" and "exact first frame" not in candidate.casefold():
        return ""
    return candidate


def _optimize_minimax_h3_story_prompts(
    pid: str,
    params: dict,
    clip_plans: list[dict],
    planned_clips: list[dict],
) -> list[dict]:
    """Run one guarded LLM pass over the exact segment prompts H3 will receive."""
    if params.get("video_model") != "minimax_h3" or not clip_plans:
        return clip_plans

    video_params = params.get("video_params") or {}
    reference_mode = str(video_params.get("h3_reference_mode") or "first_frame").strip().lower()
    reference_mode = {
        "fl2va": "first_frame",
        "ref2va": "references",
        "reference": "references",
    }.get(reference_mode, reference_mode)
    if reference_mode not in {"first_frame", "references"}:
        reference_mode = "first_frame"

    entries: list[dict] = []
    counts: list[int] = []
    for shot_index, plan in enumerate(clip_plans):
        planned = planned_clips[shot_index] if shot_index < len(planned_clips) else {}
        duration = planned.get("duration_sec") or (
            float(planned.get("end", 0) or 0) - float(planned.get("start", 0) or 0)
        )
        if duration <= 0:
            duration_frames = planned.get("duration_frames")
            duration = float(duration_frames) / 24 if duration_frames else 5.0
        count = len(_minimax_h3_frame_segments(duration, 24))
        counts.append(count)
        draft_plan = {**plan, "h3_segment_prompts": []}
        for segment_index in range(count):
            entries.append({
                "shot_index": shot_index,
                "segment_index": segment_index,
                "prompt": _minimax_h3_segment_prompt(
                    draft_plan,
                    segment_index,
                    count,
                    str(video_params.get("h3_audio_prompt") or ""),
                    reference_mode,
                ),
            })

    schema = {
        "type": "array",
        "minItems": len(entries),
        "maxItems": len(entries),
        "items": {
            "type": "object",
            "properties": {
                "shot_index": {"type": "integer"},
                "segment_index": {"type": "integer"},
                "prompt": {"type": "string"},
            },
            "required": ["shot_index", "segment_index", "prompt"],
            "additionalProperties": False,
        },
    }
    system_prompt = (
        "You validate and optimize prompts specifically for MiniMax H3 video with native audio. "
        "Return only the JSON array required by the schema, with exactly the same shot_index and "
        "segment_index pairs. Make motion chronological, concrete and visually executable; use at "
        "most one coherent camera move per segment. Never add, remove, reorder or repeat story "
        "events, characters, props, wardrobe, colors or locations. Preserve style-lock language, "
        "all quoted dialogue and the complete Audio clause verbatim. FL2VA exact-first-frame and "
        "Ref2VA new-opening-frame contracts are immutable. Do not copy actions from another segment."
    )
    user_prompt = (
        f"Conditioning mode: {reference_mode}. Optimize these exact H3 segment prompts:\n"
        + json.dumps(entries, ensure_ascii=False)
    )

    from . import llm_service
    writing_llm = _scoped_writing_llm(params)
    if writing_llm:
        response = llm_service.generate_openai_compatible(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model_id=writing_llm["model"],
            base_url=writing_llm["base_url"],
            api_key=writing_llm["api_key"],
            max_new_tokens=min(12288, max(2048, sum(len(item["prompt"]) for item in entries) // 2)),
            temperature=0.15,
            top_p=0.9,
            frequency_penalty=0.2,
            presence_penalty=0.0,
            json_schema=schema,
        )
        with _pipeline_lock:
            pipeline = _pipelines.get(pid)
            if pipeline:
                pipeline.setdefault("_llm_passes", []).append({
                    "pass": "minimax_h3_prompt_validation",
                    "provider": writing_llm["provider"],
                    "model_id": writing_llm["model"],
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "response_text": response,
                    "thinking_text": None,
                })
    else:
        response = llm_service.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            max_new_tokens=min(12288, max(2048, sum(len(item["prompt"]) for item in entries) // 2)),
            temperature=0.15,
            top_p=0.9,
            thinking_budget=0,
            enable_thinking=False,
            frequency_penalty=0.2,
            json_schema=schema,
        )
        _capture_llm_pass(pid, "minimax_h3_prompt_validation")

    parsed = _h3_parse_optimized_prompts(response)
    by_key = {
        (item.get("shot_index"), item.get("segment_index")): str(item.get("prompt") or "")
        for item in parsed
    }
    if len(by_key) != len(entries):
        raise ValueError("H3 prompt validator returned an incomplete segment set")

    per_shot: list[list[str]] = [[] for _ in clip_plans]
    for entry in entries:
        key = (entry["shot_index"], entry["segment_index"])
        validated = _h3_validated_candidate(by_key.get(key, ""), entry["prompt"], reference_mode)
        if not validated:
            raise ValueError(f"H3 prompt validator changed protected content at {key}")
        per_shot[entry["shot_index"]].append(validated)
    for shot_index, prompts in enumerate(per_shot):
        if len(prompts) != counts[shot_index]:
            raise ValueError("H3 prompt validator changed segment ordering")
        if len({re.sub(r"\s+", " ", item).casefold() for item in prompts}) != len(prompts):
            raise ValueError("H3 prompt validator repeated a segment")
        clip_plans[shot_index]["h3_segment_prompts"] = prompts
        metadata = clip_plans[shot_index].setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["h3_prompt_validation"] = "optimized"
    return clip_plans


def _run_minimax_h3_story_video(
    pid: str,
    params: dict,
    clip_plans: list[dict],
    planned_clips: list[dict],
    clip_images: list[str],
    video_params: dict,
    resolution: str,
    out_dir: str,
    workspace: str = None,
) -> list[str]:
    """Render a complete Story short film as sequential native-audio H3 clips."""
    fps = 24
    reference_mode = str(
        video_params.get("h3_reference_mode") or "first_frame"
    ).strip().lower()
    reference_mode = {
        "fl2va": "first_frame",
        "ref2va": "references",
        "reference": "references",
    }.get(reference_mode, reference_mode)
    if reference_mode not in {"first_frame", "references"}:
        reference_mode = "first_frame"
    global_image_refs: list[str] = []
    for candidate in [
        params.get("reference_image_path"),
        *(params.get("character_ref_paths") or []),
        *(video_params.get("image_refs") or []),
    ]:
        path = str(candidate or "").strip()
        if path and path not in global_image_refs:
            global_image_refs.append(path)
    video_refs = [str(path) for path in (video_params.get("h3_ref_videos") or []) if path]
    audio_refs = [str(path) for path in (video_params.get("h3_ref_audios") or []) if path]
    if len(video_refs) > 3 or len(audio_refs) > 3:
        raise ValueError("MiniMax H3 Ref2VA accepts at most 3 videos and 3 audio files.")
    if reference_mode == "first_frame" and (video_refs or audio_refs):
        raise ValueError(
            "MiniMax H3 video/audio references require Ref2VA References mode."
        )

    # Ref2VA has 12 slots total and H3 Story reserves one for each generated
    # shot's continuity frame. Build the remaining image references per shot:
    # identity references stay global, while exactly one matching location is
    # eligible for that shot.
    image_budget = max(0, min(8, 11 - len(video_refs) - len(audio_refs)))
    shot_image_refs: list[list[str]] = []
    reference_manifest: list[dict] = []
    for shot_index, plan in enumerate(clip_plans):
        location_ref, location_label = _director_location_ref_for_plan(plan, params)
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        requested_location = str(
            plan.get("location_ref_label")
            or metadata.get("location_ref_label")
            or ""
        ).strip()
        selected: list[str] = []
        if reference_mode == "references":
            base_budget = image_budget - 1 if location_ref and image_budget > 0 else image_budget
            for candidate in global_image_refs[:base_budget]:
                if candidate and candidate not in selected:
                    selected.append(candidate)
            if location_ref and image_budget > 0 and location_ref not in selected:
                selected.append(location_ref)
        available = list(dict.fromkeys([
            *[candidate for candidate in global_image_refs if candidate],
            *([location_ref] if location_ref else []),
        ]))
        if reference_mode == "references" and len(available) > len(selected):
            dropped = len(available) - len(selected)
            print(
                f"[Pipeline {pid}] MiniMax H3 shot {shot_index + 1} omitted "
                f"{dropped} lower-priority image reference(s) to fit the "
                "Ref2VA 12-slot limit."
            )
        if reference_mode == "references" and location_ref and location_ref in selected:
            print(
                f"[Pipeline {pid}] MiniMax H3 shot {shot_index + 1} location ref: "
                f"{location_label or os.path.basename(location_ref)}"
            )
        elif reference_mode == "references" and len(params.get("location_ref_paths") or []) > 1:
            print(
                f"[Pipeline {pid}] MiniMax H3 shot {shot_index + 1}: no "
                "unambiguous location reference; sending none instead of all locations."
            )
        shot_image_refs.append(selected)
        reference_manifest.append({
            "shot_index": shot_index,
            "mode": reference_mode,
            "shot_frame": (
                clip_images[shot_index]
                if shot_index < len(clip_images)
                else ""
            ),
            "image_references": selected,
            "location_reference": location_ref if location_ref in selected else "",
            "location_label": location_label if location_ref in selected else "",
            "requested_location_label": requested_location,
            "video_references": video_refs if reference_mode == "references" else [],
            "audio_references": audio_refs if reference_mode == "references" else [],
            "note": (
                "FL2VA exact first frame; character and location references were used "
                "to author the shot frame but are not sent to the video model."
                if reference_mode == "first_frame"
                else "Ref2VA composes a new shot from these references; no exact first-frame guarantee."
            ),
            "warnings": ([
                f'No reference matched the requested location "{requested_location}".'
            ] if reference_mode == "references" and requested_location and not location_ref else []),
        })

    _update_pipeline(pid, h3_reference_manifest=reference_manifest)
    _save_pipeline_state(pid)

    jobs: list[tuple[int, int, int, int, str]] = []
    for shot_index, plan in enumerate(clip_plans):
        planned = planned_clips[shot_index] if shot_index < len(planned_clips) else {}
        duration = planned.get("duration_sec") or (
            float(planned.get("end", 0) or 0) - float(planned.get("start", 0) or 0)
        )
        if duration <= 0:
            duration_frames = planned.get("duration_frames")
            duration = float(duration_frames) / fps if duration_frames else 5.0
        frame_segments = _minimax_h3_frame_segments(duration, fps)
        for segment_index, frames in enumerate(frame_segments):
            jobs.append((
                shot_index,
                segment_index,
                len(frame_segments),
                frames,
                _minimax_h3_segment_prompt(
                    plan,
                    segment_index,
                    len(frame_segments),
                    str(video_params.get("h3_audio_prompt") or ""),
                    reference_mode,
                ),
            ))

    if not jobs:
        raise RuntimeError("MiniMax H3 received no planned Story shots to render.")

    outputs: list[str] = []
    continuation_frames: list[str] = []
    current_shot = -1
    segment_start = ""
    try:
        for job_index, (shot_index, segment_index, segment_count, frames, prompt) in enumerate(jobs):
            if _pipeline_cancel_requested(pid):
                raise PipelineCancelled("Director pipeline was cancelled.")

            if shot_index != current_shot:
                current_shot = shot_index
                image_name = clip_images[shot_index] if shot_index < len(clip_images) else ""
                candidate = image_name if os.path.isabs(image_name) else os.path.join(out_dir, image_name)
                segment_start = candidate if image_name and os.path.isfile(candidate) else ""

            gen_params: dict = {
                "model_type": "minimax_h3",
                "prompt": prompt,
                "image_mode": 0,
                "image_prompt_type": "S" if segment_start else "",
                "num_inference_steps": video_params.get("num_inference_steps", 20),
                "guidance_scale": video_params.get("guidance_scale", 1),
                "resolution": resolution,
                "video_length": frames,
                "seed": -1,
                "settings_version": 2.52,
                "generation_mode": "video",
                "repeat_generation": 1,
                "negative_prompt": "",
                "flow_shift": video_params.get("flow_shift", 12),
                "h3_audio_shift": video_params.get("h3_audio_shift", 3),
                "h3_audio_prompt": video_params.get("h3_audio_prompt", ""),
                "h3_ref_image_size": video_params.get("h3_ref_image_size", "match"),
                "h3_model_profile": video_params.get("h3_model_profile", "quality"),
                "h3_reference_mode": reference_mode,
                "_director_pipeline_id": pid,
            }
            user_image_refs = (
                shot_image_refs[shot_index]
                if shot_index < len(shot_image_refs)
                else list(global_image_refs[:image_budget])
            )
            uses_ref2va = reference_mode == "references"
            if uses_ref2va:
                image_refs = [segment_start, *user_image_refs] if segment_start else list(user_image_refs)
                gen_params["image_refs"] = [path for path in image_refs if path]
                gen_params["h3_ref_videos"] = video_refs
                gen_params["h3_ref_audios"] = audio_refs
            elif segment_start:
                gen_params["image_start"] = segment_start

            print(
                f"[Pipeline {pid}] MiniMax H3 shot {shot_index + 1}, "
                f"segment {segment_index + 1}/{segment_count}: {frames} frames"
            )
            generated = _submit_and_wait(
                gen_params,
                timeout_s=7200,
                workspace=workspace,
                out_dir=out_dir,
            )
            if not generated:
                raise RuntimeError(
                    f"MiniMax H3 returned no video for shot {shot_index + 1}, "
                    f"segment {segment_index + 1}."
                )
            outputs.extend(generated)
            generated_path = generated[-1] if os.path.isabs(generated[-1]) else os.path.join(out_dir, generated[-1])

            if segment_index + 1 < segment_count:
                from services.video_editor import extract_frame, probe_media
                continuation_path = os.path.join(
                    out_dir,
                    f".minimax_h3_{pid}_{shot_index + 1}_{segment_index + 1}_continuation.png",
                )
                media = probe_media(generated_path)
                extract_frame(generated_path, continuation_path, float(media["duration"]))
                continuation_frames.append(continuation_path)
                segment_start = continuation_path

            _update_pipeline(
                pid,
                progress={
                    "current": job_index + 1,
                    "total": len(jobs),
                    "message": f"Generated MiniMax H3 segment {job_index + 1}/{len(jobs)}",
                    "step": 0,
                    "total_steps": 0,
                },
            )
            _save_pipeline_state(pid)
    finally:
        for path in continuation_frames:
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass

    if len(outputs) == 1:
        return outputs

    final_name = f"minimax_h3_{pid}_multiclip.mp4"
    final_path = os.path.join(out_dir, final_name)
    clip_paths = [name if os.path.isabs(name) else os.path.join(out_dir, name) for name in outputs]
    if not _wgp.concatenate_multi_clip_videos(clip_paths, final_path, None):
        raise RuntimeError(
            "MiniMax H3 rendered every segment, but final short-film assembly failed. "
            "The individual clips were preserved."
        )
    sidecar = {
        "params": {
            "model_type": "minimax_h3",
            "resolution": resolution,
            "source_clips": [os.path.basename(path) for path in clip_paths],
            "director_pipeline_id": pid,
        },
        "generation_mode": "video",
        "created_at": time.time(),
    }
    with open(os.path.splitext(final_path)[0] + ".meta.json", "w", encoding="utf-8") as handle:
        json.dump(sidecar, handle, indent=2)
    return [*outputs, final_name]


def _run_video_generation(pid: str, params: dict, clip_plans: list[dict],
                          planned_clips: list[dict], clip_images: list[str],
                          clip_keyframes: Optional[list[list[str]]] = None,
                          out_dir: str = None, workspace: str = None) -> list[str]:
    """Generate multi-clip video with optional keyframe injection. Returns list of output filenames."""
    if (
        params.get("pipeline_type") == "comic_movie"
        and not params.get("_comic_renderer_orchestrated")
    ):
        if not out_dir:
            out_dir = _wgp.save_path
        return _run_comic_renderer_pipeline(
            pid,
            params,
            clip_plans,
            planned_clips,
            clip_images,
            clip_keyframes,
            out_dir,
            workspace,
        )
    video_model = params.get("video_model")
    if not video_model:
        # Fallback: use first available video model from server config
        available = _wgp.get_models_list() if _wgp else []
        video_models = [m for m in available if m.get("is_t2v") or m.get("is_i2v")]
        video_model = video_models[0]["model_type"] if video_models else "ltx2_22B_distilled"
        print(f"[Pipeline] No video_model in params, using fallback: {video_model}")
    video_params = params.get("video_params", {})
    video_loras = params.get("video_loras", {})
    # Mirror of the image-LoRA file-existence filter — see _run_image_generation
    # for the rationale. Filter video_loras to those actually present in
    # video_model's LoRA directory so a stale activation from a different
    # video model doesn't crash wgp validation upfront.
    try:
        _vid_activated = list(video_loras.get("activated_loras", []) or [])
        _vid_mults = video_loras.get("loras_multipliers", "") or ""
        if _vid_activated:
            print(
                f"[Pipeline {pid}] Video LoRAs received: {len(_vid_activated)} | "
                f"model={video_model} | "
                f"names={[os.path.basename(n) for n in _vid_activated]} | "
                f"multipliers={_vid_mults!r}"
            )
            try:
                _vid_lora_dir = _wgp.get_lora_dir(video_model)
            except Exception:
                _vid_lora_dir = ""
            if _vid_lora_dir and os.path.isdir(_vid_lora_dir):
                _vid_existing = {
                    f for f in os.listdir(_vid_lora_dir)
                    if f.lower().endswith((".safetensors", ".sft"))
                }
                _vid_mult_tokens = _vid_mults.split()
                _vid_kept: list[str] = []
                _vid_kept_mults: list[str] = []
                _vid_skipped: list[str] = []
                for _idx, _name in enumerate(_vid_activated):
                    _basename = os.path.basename(_name)
                    if _basename in _vid_existing:
                        _vid_kept.append(_name)
                        if _idx < len(_vid_mult_tokens):
                            _vid_kept_mults.append(_vid_mult_tokens[_idx])
                    else:
                        _vid_skipped.append(_basename)
                if _vid_skipped:
                    _warn = (
                        f"Skipped {len(_vid_skipped)} video LoRA(s) not present in "
                        f"{os.path.basename(_vid_lora_dir)}/: {_vid_skipped}. These "
                        f"were likely activated when a different video model was "
                        f"selected. Re-select your video LoRAs for {video_model}."
                    )
                    print(f"[Pipeline {pid}] {_warn}")
                    _exw = _pipelines.get(pid, {}).get("lora_warnings", []) or []
                    _update_pipeline(pid, lora_warnings=[*_exw, _warn])
                video_loras = {
                    "activated_loras": _vid_kept,
                    "loras_multipliers": " ".join(_vid_kept_mults),
                }
                print(
                    f"[Pipeline {pid}] Video LoRAs after existence filter: "
                    f"{len(_vid_kept)} kept, {len(_vid_skipped)} skipped"
                )
    except Exception as _e:
        print(f"[Pipeline {pid}] Video LoRA file-existence filter skipped: {_e}")

    audio_path = params.get("audio_path")
    seamless = params.get("seamless", True)
    pipeline_type = params.get("pipeline_type", "music_video")
    # Get FPS from model definition (reliable) — don't trust frontend default of 16
    fps = params.get("fps", 16)
    try:
        model_def = _wgp.get_model_def(video_model)
        if model_def and model_def.get("fps"):
            fps = model_def["fps"]
    except Exception:
        pass
    print(f"[Pipeline] Video gen: fps={fps}, video_model={video_model}")

    resolution = _normalize_video_resolution(
        video_model,
        video_params.get("resolution", "1280x720"),
    )
    if video_params.get("resolution") != resolution:
        video_params = dict(video_params)
        video_params["resolution"] = resolution
        params["video_params"] = video_params
    runtime = _effective_ltx_runtime(video_model, video_params)
    if pipeline_type == "comic_movie":
        video_params = dict(video_params)
        video_params.update({
            "num_inference_steps": runtime["num_inference_steps"],
            "guidance_scale": runtime["guidance_scale"],
            "stage2_steps": runtime["stage2_steps"],
        })
        params["video_params"] = video_params
    steps = video_params.get("num_inference_steps", 8)
    guidance = video_params.get("guidance_scale", 1)
    spatial_upsampling = params.get("video_spatial_upsampling", "")
    film_grain_intensity = params.get("video_film_grain_intensity", 0)
    film_grain_saturation = params.get("video_film_grain_saturation", 0.5)
    self_refiner = params.get("video_self_refiner", 0)

    if not out_dir:
        out_dir = _wgp.save_path

    # H3's open model renders one native-audio clip per request and has no
    # WanGP multi-clip/sliding-window contract. Story mode therefore runs its
    # planned shots explicitly and assembles them with their embedded audio.
    if video_model == "minimax_h3" and pipeline_type == "short_film_story":
        return _run_minimax_h3_story_video(
            pid,
            params,
            clip_plans,
            planned_clips,
            clip_images,
            video_params,
            resolution,
            out_dir,
            workspace,
        )

    # Quantize helper
    try:
        _min_f, _fs, _latent = _wgp.get_model_min_frames_and_step(video_model)
    except Exception:
        _min_f, _fs, _latent = 17, 8, 8

    def _quantize_frames(cf):
        return max((cf - 1) // _latent * _latent + 1, _min_f)

    def _quantize_frames_nearest(cf):
        # Round to the NEAREST valid (latent*n + 1) length instead of
        # flooring — used with a carry term for per-clip sequences where
        # floor-truncation would compound (see below).
        return max(round((cf - 1) / _latent) * _latent + 1, _min_f)

    # ── SEAMLESS MODE: one continuous rolling window generation ──────
    # Instead of separate per-clip jobs, build ONE generation that looks like
    # Studio mode: rolling windows with per-window prompts + keyframe injection.
    comic_seeds = (
        [
            _comic_shot_seed(params, index, plan)
            for index, plan in enumerate(clip_plans)
        ]
        if pipeline_type == "comic_movie"
        else []
    )
    generation_seed = (
        comic_seeds[0] if comic_seeds else -1
    )

    if seamless:
        window_prompts_all = []  # One prompt per rolling window
        keyframe_images = []     # All keyframe images in order
        keyframe_frame_positions = []  # Absolute frame numbers (1-indexed for wgp parser)

        # Track cumulative frame position as we go through scenes
        cumulative_frames = 0

        for i, plan in enumerate(clip_plans):
            pc = planned_clips[i] if i < len(planned_clips) else {}
            dur_sec = pc.get("duration_sec", pc.get("end", 0) - pc.get("start", 0))
            if dur_sec <= 0:
                dur_sec = 20
            scene_frames = round(dur_sec * fps)

            wp = plan.get("window_prompts") or []
            wp = [w.get("prompt", w.get("text", str(w))) if isinstance(w, dict) else str(w) for w in wp]
            if len(wp) > 1:
                for w_prompt in wp:
                    window_prompts_all.append(w_prompt)
            else:
                vp = plan.get("video_prompt", "")
                if vp:
                    window_prompts_all.append(vp)

            # Mid-scene keyframes from the LLM (injected at mid-point of this scene)
            if clip_keyframes and i < len(clip_keyframes):
                kf_list = clip_keyframes[i]
                if kf_list:
                    # Distribute mid-scene keyframes evenly across the scene
                    num_kf = len(kf_list)
                    for ki, kf_file in enumerate(kf_list):
                        if kf_file:
                            kf_path = os.path.join(out_dir, kf_file)
                            if os.path.isfile(kf_path):
                                # Position: evenly spaced within the scene
                                kf_pos = cumulative_frames + int(scene_frames * (ki + 1) / (num_kf + 1))
                                keyframe_images.append(kf_path)
                                keyframe_frame_positions.append(kf_pos + 1)  # 1-indexed for wgp parser

            # Scene boundary keyframe: inject next scene's start image at the end of this scene
            if i < len(clip_plans) - 1:
                next_img = clip_images[i + 1] if i + 1 < len(clip_images) else ""
                if next_img:
                    next_path = os.path.join(out_dir, next_img)
                    if os.path.isfile(next_path):
                        boundary_frame = cumulative_frames + scene_frames
                        keyframe_images.append(next_path)
                        keyframe_frame_positions.append(boundary_frame)  # 1-indexed (approx)

            cumulative_frames += scene_frames

        total_frames = _quantize_frames(cumulative_frames)
        sliding_window_frames = _quantize_frames(round(20 * fps))

        # First scene's start image
        first_start = ""
        if clip_images and clip_images[0]:
            first_path = os.path.join(out_dir, clip_images[0])
            if os.path.isfile(first_path):
                first_start = first_path

        prompt_text = "\n".join(window_prompts_all)

        print(f"[Pipeline {pid}] Seamless mode: {len(window_prompts_all)} windows, "
              f"{len(keyframe_images)} keyframes at frames {keyframe_frame_positions}, "
              f"{total_frames} total frames ({total_frames/fps:.1f}s)")

    # ── STANDARD MODE: separate per-clip generation ─────────────────
    else:
        prompts = []
        image_start_paths = []
        image_end_paths = []
        per_clip_frames = []
        has_sliding_window = False
        comic_end_images = (
            _comic_end_image_filenames(params, clip_images)
            if pipeline_type == "comic_movie"
            else [""] * len(clip_images)
        )
        comic_fidelity = str(params.get("comic_motion_fidelity") or "faithful")
        if pipeline_type == "comic_movie":
            requested_edit_transition = str(
                params.get("comic_edit_transition") or "none"
            ).strip().lower()
            if requested_edit_transition not in {"", "none", "cut", "hard-cut"}:
                print(
                    f"[Pipeline {pid}] Ignoring comic edit transition "
                    f"{requested_edit_transition!r}: the generation pipeline "
                    "always assembles I2V shots with hard cuts. Add transitions "
                    "later in Video Editor."
                )
            # Save this explicitly in the resumable checkpoint so the assembly
            # contract is inspectable and cannot be confused with end frames.
            params["comic_edit_transition"] = "none"
            _update_pipeline(
                pid,
                _clip_end_images=comic_end_images,
                _comic_edit_transition="none",
            )
            _save_pipeline_state(pid)
            print(
                f"[Pipeline {pid}] Comic end-frame conditioning: "
                f"{sum(bool(item) for item in comic_end_images)} end frame(s), "
                f"mode={params.get('comic_end_frame_mode', params.get('comic_anchor_mode', 'none'))}, "
                "assembly=hard-cuts, "
                f"fidelity={comic_fidelity}"
            )

        for i, plan in enumerate(clip_plans):
            wp = plan.get("window_prompts") or []
            wp = [w.get("prompt", w.get("text", str(w))) if isinstance(w, dict) else str(w) for w in wp]
            end_file = comic_end_images[i] if i < len(comic_end_images) else ""
            if len(wp) > 1:
                prompt_value = "\n".join(wp)
            else:
                vp = plan.get("video_prompt", "")
                pc = planned_clips[i] if i < len(planned_clips) else {}
                dur = pc.get("duration_sec", pc.get("end", 0) - pc.get("start", 0))
                if dur > 32 and vp:
                    print(f"[Pipeline] WARNING: Clip {i+1} is {dur:.0f}s but has no window_prompts")
                prompt_value = vp
            if pipeline_type == "comic_movie":
                prompt_value = str(
                    plan.get("_effective_video_prompt")
                    or _comic_motion_prompt(
                        prompt_value,
                        comic_fidelity,
                        bool(end_file),
                        camera_locked=_comic_camera_is_locked(params, i, plan),
                        motion_mode=_comic_motion_mode(params, i),
                        motion_level=_comic_motion_level(params, i, plan),
                    )
                )
            prompts.append(prompt_value)

            img_file = clip_images[i] if i < len(clip_images) else ""
            if img_file:
                img_path = os.path.join(out_dir, img_file)
                image_start_paths.append(img_path if os.path.isfile(img_path) else "")
            else:
                image_start_paths.append("")
            if end_file:
                end_path = os.path.join(out_dir, end_file)
                image_end_paths.append(end_path if os.path.isfile(end_path) else "")
            else:
                image_end_paths.append("")

            pc = planned_clips[i] if i < len(planned_clips) else {}
            window_prompts = plan.get("window_prompts", []) or []
            window_count = plan.get("window_count", 1) or 1
            if len(window_prompts) > 1 and window_count <= 1:
                window_count = len(window_prompts)
            has_keyframes = bool(plan.get("keyframe_prompts"))
            num_keyframes = len(plan.get("keyframe_prompts", []) or [])

            if window_count > 1 or has_keyframes:
                shot_duration = pc.get("duration_sec", pc.get("end", 0) - pc.get("start", 0))
                if shot_duration <= 0:
                    shot_duration = 20 * max(window_count, num_keyframes + 1)
                clip_frames = max(round(shot_duration * fps), round(5 * fps))
                per_clip_frames.append(clip_frames)
                has_sliding_window = True
            else:
                # SECONDS are the fps-agnostic ground truth. planned_clips
                # from plan_clip_structure carry start/end (+duration_frames)
                # but NO duration_sec — the old `get("duration_sec", 0)`
                # fell straight through to duration_frames, which the
                # frontend may have had computed at the WRONG model's fps
                # (modelOptions belongs to the Studio-selected model, e.g.
                # ACE-Step right after generating the track → fps 16). A
                # 26s clip became 26x16=416 frames, rendered at LTX-2's 25
                # fps = 16.6s — every music-video clip silently shortened
                # by 16/25.
                frozen_frames = (
                    plan.get("_effective_video_frames")
                    or pc.get("_effective_video_frames")
                )
                dur_sec = pc.get("duration_sec") or (pc.get("end", 0) - pc.get("start", 0))
                clip_frames = (
                    int(frozen_frames)
                    if frozen_frames
                    else (
                        round(dur_sec * fps)
                        if dur_sec > 0
                        else pc.get("duration_frames", round(20 * fps))
                    )
                )
                if clip_frames > round(32 * fps):
                    has_sliding_window = True
                # Comic/storyboard shots are often intentionally 2–4 seconds.
                # The old generic five-second floor ignored the UI duration,
                # forcing LTX to invent extra motion and drift away from the
                # approved artwork. Other Director modes keep their historical
                # five-second minimum.
                minimum_frames = _min_f if pipeline_type == "comic_movie" else round(5 * fps)
                per_clip_frames.append(max(clip_frames, minimum_frames))

        # Quantize to the model's (latent*n + 1) frame lattice WITHOUT letting
        # the error compound. Floor-snapping each clip independently lost 0-7
        # frames per clip (an 8s clip = 200 frames @25fps floors to 193 —
        # exactly the "7 frames short" the user measured), while the song
        # plays on at true time — so cuts drifted off the planned musical
        # break points by seconds near the end of a song. Instead, round each
        # clip to the NEAREST valid length and carry the residual into the
        # next clip: every cumulative boundary stays within half a latent
        # step (±4 frames ≈ 0.16s) of the planned beat, forever.
        _carried: list[int] = []
        _carry = 0.0
        for _cf in per_clip_frames:
            _target = _cf + _carry
            _q = _quantize_frames_nearest(_target)
            _carry = _target - _q
            _carried.append(_q)
        per_clip_frames = _carried
        total_frames = sum(per_clip_frames)
        max_clip_frames = max(per_clip_frames) if per_clip_frames else round(5 * fps)
        # Single-window case: sliding_window_frames must be STRICTLY
        # greater than max_clip_frames after wgp's internal quantization
        # (line ~6725 of wgp.py), or wgp interprets `video_length >
        # sliding_window_size` and splits the clip into multiple
        # windows. Add `_latent + 1` frames of safety margin — one full
        # latent step plus one to guarantee strict-greater after the
        # `(x - 1) // latent * latent + 1` rounding. Multi-window
        # case (has_sliding_window=True) stays at 20s because the
        # whole point is to slide.
        #
        # Single-window clips are allowed up to 32s (was 22s): LTX-2.3
        # holds up well past its nominal ~20s window — user-validated at
        # 26s with the window sized to the clip — and one window beats
        # mid-clip window seams for music sync. plan_clip_structure caps
        # planned clips at MAX_CLIP_SECONDS=26 (the 75%-merge rule can
        # stretch a section to ~32s, hence the threshold).
        sliding_window_frames = (
            round(20 * fps) if has_sliding_window
            else max_clip_frames + _latent + 1
        )

        for ci, cf in enumerate(per_clip_frames):
            wp_count = len((clip_plans[ci].get("window_prompts") or []) if ci < len(clip_plans) else [])
            wc = clip_plans[ci].get("window_count", 1) if ci < len(clip_plans) else 1
            print(f"[Pipeline {pid}] Clip {ci+1}: {cf} frames ({cf/fps:.1f}s), windows={wc}, window_prompts={wp_count}")

    # Build audio params
    audio_params: dict = {}
    if pipeline_type == "short_film_story":
        audio_params["audio_prompt_type"] = ""
    elif audio_path:
        audio_params["audio_prompt_type"] = "A"
        audio_params["audio_guide"] = audio_path
        audio_scale = params.get("audio_scale")
        if audio_scale is not None:
            audio_params["audio_scale"] = audio_scale

    # ── Build gen_params based on mode ──────────────────────────────
    lora_params = {
        "activated_loras": video_loras.get("activated_loras", []),
        "loras_multipliers": " ".join(
            m.split(";")[0] for m in (video_loras.get("loras_multipliers", "") or "").split(" ") if m
        ),
    }
    frozen_negative_prompt = params.get("_effective_video_negative_prompt")
    frozen_negative_prompts = params.get(
        "_effective_video_negative_prompts"
    )
    per_clip_negative_prompts: list[str] = []
    if pipeline_type == "comic_movie":
        base_negative_prompt = (
            str(frozen_negative_prompt)
            if isinstance(frozen_negative_prompt, str)
            else _append_negative_prompt(
                str(video_params.get("negative_prompt") or "").strip(),
                _COMIC_REFERENCE_NEGATIVE,
            )
        )
        if (
            isinstance(frozen_negative_prompts, list)
            and len(frozen_negative_prompts) == len(clip_plans)
        ):
            per_clip_negative_prompts = [
                str(value or "") for value in frozen_negative_prompts
            ]
        else:
            per_clip_negative_prompts = [
                _append_negative_prompt(
                    base_negative_prompt,
                    _COMIC_LOCKED_CAMERA_NEGATIVE,
                )
                if _comic_camera_is_locked(params, index, plan)
                else base_negative_prompt
                for index, plan in enumerate(clip_plans)
            ]
        # Comic shots are normally separate hard-cut jobs.  Keep a scalar for
        # old direct/seamless callers while the standard route consumes the
        # exact PRE value per clip.
        negative_prompt = (
            per_clip_negative_prompts[0]
            if per_clip_negative_prompts
            else base_negative_prompt
        )
    else:
        negative_prompt = str(video_params.get("negative_prompt") or "").strip()

    if seamless:
        # Seamless: ONE generation job with rolling windows + keyframe injection
        gen_params: dict = {
            "model_type": video_model,
            "prompt": prompt_text,
            "image_mode": 0,
            "multi_prompts_gen_type": 0,  # Rolling window mode (one prompt per window)
            "image_prompt_type": "S" if first_start else "",
            "video_prompt_type": "",
            "num_inference_steps": steps,
            "guidance_scale": guidance,
            "resolution": resolution,
            "video_length": total_frames,
            "sliding_window_size": sliding_window_frames,
            "seed": generation_seed,
            "settings_version": 2.52,
            "generation_mode": "video",
            "repeat_generation": 1,
            "negative_prompt": negative_prompt,
            "self_refiner_setting": self_refiner,
            "_director_pipeline_id": pid,
            **lora_params,
            **audio_params,
        }
        if first_start:
            gen_params["image_start"] = first_start
        # Keyframe injection via image_refs + frames_positions (numeric absolute positions)
        if keyframe_images:
            gen_params["image_refs"] = keyframe_images
            gen_params["frames_positions"] = " ".join(str(p) for p in keyframe_frame_positions)
            existing_vpt = gen_params.get("video_prompt_type", "")
            if "KFI" not in existing_vpt:
                gen_params["video_prompt_type"] = existing_vpt + "KFI"
            print(f"[Pipeline {pid}] Seamless keyframes: {len(keyframe_images)} images at frames {keyframe_frame_positions}")

    else:
        # Standard: separate per-clip generation jobs
        CLIP_SEPARATOR = "\n---CLIP_BOUNDARY---\n"
        prompt_text = CLIP_SEPARATOR.join(prompts)

        has_any_start = any(p for p in image_start_paths)
        has_any_end = any(p for p in image_end_paths)
        if not has_any_start:
            image_start_paths = []
        if not has_any_end:
            image_end_paths = []

        ipt = "SE" if has_any_start and has_any_end else ("S" if has_any_start else "")

        gen_params: dict = {
            "model_type": video_model,
            "prompt": prompt_text,
            "image_mode": 0,
            "multi_prompts_gen_type": 3,  # Multi-clip mode
            "image_prompt_type": ipt,
            "num_inference_steps": steps,
            "guidance_scale": guidance,
            "resolution": resolution,
            "video_length": total_frames,
            "sliding_window_size": sliding_window_frames,
            "per_clip_frames": per_clip_frames,
            "seed": generation_seed,
            "settings_version": 2.52,
            "generation_mode": "video",
            "repeat_generation": 1,
            "negative_prompt": negative_prompt,
            "self_refiner_setting": self_refiner,
            "_director_pipeline_id": pid,
            **lora_params,
            **audio_params,
        }
        if comic_seeds:
            gen_params["per_clip_seeds"] = comic_seeds
        if per_clip_negative_prompts:
            gen_params["per_clip_negative_prompts"] = (
                per_clip_negative_prompts
            )
        index_map = params.get("_director_clip_index_map")
        if isinstance(index_map, list):
            gen_params["_director_clip_index_map"] = list(index_map)
        if has_any_start:
            gen_params["image_start"] = image_start_paths
        if has_any_end:
            gen_params["image_end"] = image_end_paths
            if pipeline_type == "comic_movie":
                # Each SE clip is generated one latent step longer, then the
                # distorted conditioning tail is removed. This preserves the
                # requested duration per panel and avoids one enormous
                # compensation clip after a long storyboard.
                gen_params["_se_preserve_duration_per_clip"] = True
        # Per-clip keyframe injection
        if clip_keyframes:
            per_clip_kf_paths: list[list[str]] = []
            for i, kf_list in enumerate(clip_keyframes):
                paths = []
                for kf_file in kf_list:
                    if kf_file:
                        kf_path = os.path.join(out_dir, kf_file)
                        if os.path.isfile(kf_path):
                            paths.append(kf_path)
                per_clip_kf_paths.append(paths)
            if any(paths for paths in per_clip_kf_paths):
                gen_params["per_clip_keyframes"] = per_clip_kf_paths
                print(f"[Pipeline {pid}] Keyframe injection: {[len(p) for p in per_clip_kf_paths]} keyframes per clip")

    # Common params
    # Forward LTX pipeline controls selected in Studio/Advanced settings.
    # Director previously copied these into video_params and then silently
    # dropped them while constructing gen_params, so changing Stage 2 steps or
    # pipeline mode had no effect on Director/comic-movie jobs.
    for runtime_key in (
        "single_stage_pipeline",
        "progressive_pipeline",
        "stage2_steps",
        "input_video_strength",
        "progressive_stage1_image_weight",
        "progressive_stage2_steps",
        "progressive_stage2_sigma",
        "progressive_stage3_steps",
        "progressive_stage3_sigma",
        "progressive_stage3_image_weight",
    ):
        if runtime_key in video_params:
            gen_params[runtime_key] = video_params[runtime_key]

    has_i2v_start = bool(first_start) if seamless else bool(has_any_start)
    if has_i2v_start and "input_video_strength" not in gen_params:
        # Match Studio's tested LTX distilled I2V default: enough anchoring to
        # preserve the frame/style, but not the motion-killing 1.0 default.
        gen_params["input_video_strength"] = (
            0.7 if "distilled" in str(video_model).lower() else 1.0
        )
    if pipeline_type == "comic_movie":
        fidelity = str(params.get("comic_motion_fidelity") or "faithful").lower()
        if fidelity == "faithful":
            gen_params["input_video_strength"] = max(
                0.9,
                float(gen_params.get("input_video_strength", 0.9)),
            )
        elif not seamless and any(image_end_paths):
            gen_params["input_video_strength"] = max(
                0.8,
                float(gen_params.get("input_video_strength", 0.8)),
            )

    voice_ref = params.get("voice_reference")
    if voice_ref:
        gen_params["voice_reference"] = voice_ref
        gen_params["identity_guidance_scale"] = params.get("identity_guidance_scale", 3.0)
        print(f"[Pipeline {pid}] Voice reference: {voice_ref}, identity_scale={gen_params['identity_guidance_scale']}")
    if spatial_upsampling:
        gen_params["spatial_upsampling"] = spatial_upsampling
    if film_grain_intensity > 0:
        gen_params["film_grain_intensity"] = film_grain_intensity
        gen_params["film_grain_saturation"] = film_grain_saturation

    # Track progress by monitoring the generation job
    output_files = _submit_and_wait(gen_params, timeout_s=7200, workspace=workspace, out_dir=out_dir)  # 2hr timeout for long videos
    return output_files
