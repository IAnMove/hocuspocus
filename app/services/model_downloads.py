"""Model catalog, checkpoint delete, pre-download and the cheap catalog reads.

The handlers are the full server's functions, moved verbatim. ``configure``
binds the caller's engine, weight-group helpers and generation registries.
The download map and its lock are the one instance the full server aliases.
"""
from __future__ import annotations

import os
import threading
import time
import traceback

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from services import minimax_h3_service, model3d_service

wgp = None
_model_weight_groups = None
_variant_group_downloaded = None
_variant_group_filenames = None
_is_legacy_h3_model = None
_jobs = None
_active_gen_states = None


def configure(
    *,
    engine,
    model_weight_groups,
    variant_group_downloaded,
    variant_group_filenames,
    is_legacy_h3_model,
    jobs,
    active_gen_states,
) -> None:
    """Bind the engine, the weight helpers that stay in the launch module, and the job registries."""
    global wgp, _model_weight_groups, _variant_group_downloaded, _variant_group_filenames
    global _is_legacy_h3_model, _jobs, _active_gen_states
    wgp = engine
    _model_weight_groups = model_weight_groups
    _variant_group_downloaded = variant_group_downloaded
    _variant_group_filenames = variant_group_filenames
    _is_legacy_h3_model = is_legacy_h3_model
    _jobs = jobs
    _active_gen_states = active_gen_states


def _folder_model_ready(model_def: dict) -> bool:
    """A model with no main URL, whose handler downloads a whole folder (VoxCPM2),
    is ready when every asset it declares is on disk."""
    assets = model_def.get("required_model_assets") or []
    return bool(assets) and all(wgp.fl.locate_file(path, error_if_none=False) is not None for path in assets)


def _check_model_downloaded(model_type: str) -> bool:
    """Check if a model's checkpoint files are downloaded.

    Models often list multiple URLs (e.g. full bf16 + quantized int8) per
    weight group; ONE variant per group is enough. Every group (main
    transformer + each weight module) must be present.
    """
    # Keep this first branch self-contained: the readiness function is also
    # used in isolated model-definition checks where launcher-only helpers are
    # intentionally not imported.
    if str(model_type or "").strip() == "minimax_h3_legacy":
        return minimax_h3_service.is_model_downloaded()
    try:
        model_def = wgp.get_model_def(model_type)
        if model_def is None:
            return False
        groups = _model_weight_groups(model_type)
        if not groups:
            return _folder_model_ready(model_def)
        if not all(_variant_group_downloaded(g) for g in groups):
            return False
        # Component-folder models can expose a tiny manifest as their primary
        # URL while the family handler downloads the actual assets separately.
        # Do not mark a partial install as ready merely because that manifest
        # arrived first (MiniMax-Music3 is the first such local audio model).
        for relative_path in model_def.get("required_model_assets", []):
            if wgp.fl.locate_file(relative_path, error_if_none=False) is None:
                return False
        # Some edit pipelines split required conditioning weights out of the
        # main transformer/text-encoder groups. Krea 2 Edit cannot run without
        # its Qwen3-VL vision tower, so do not report it as ready until that
        # preloaded companion file is actually discoverable (including through
        # linked checkpoint roots).
        vision_encoder_filename = model_def.get("vision_encoder_filename")
        if (
            vision_encoder_filename
            and wgp.fl.locate_file(vision_encoder_filename, error_if_none=False) is None
        ):
            return False
        # Def-bundled accelerator loras (e.g. SCAIL-2 Fast's lightx2v
        # distill) are loaded unconditionally at generation time, so they
        # count toward readiness too. resolve_lora_path searches linked
        # read-only roots like the generation path does.
        for url in wgp.get_model_recursive_prop(model_type, "loras", return_list=True):
            if not os.path.isfile(wgp.resolve_lora_path(model_type, url.split("/")[-1])):
                return False
        return True
    except Exception:
        return False


def list_models(detail: bool = True):
    """List available model families and model types.

    HTTP defaults to the full catalog so the Studio UI keeps working.
    Pass detail=false for the short MCP summary.
    """
    from services.director_model_compat import assess_director_model

    # Families
    families = []
    for fid, (order, label) in wgp.families_infos.items():
        if fid == "unknown":
            continue
        families.append({"id": fid, "label": label, "order": order})
    families.append({"id": "hunyuan3d", "label": "Hunyuan3D", "order": 350})
    families.sort(key=lambda f: f["order"])

    # Models
    models = []
    for mt in wgp.displayed_model_types:
        md = wgp.get_model_def(mt)
        if md is None:
            continue
        family = wgp.get_model_family(mt, for_ui=True)
        architecture = wgp.get_base_model_type(mt)
        director_compat = assess_director_model(
            mt,
            md,
            family=family,
            architecture=architecture,
        )
        models.append({
            "model_type": mt,
            "name": md.get("name", mt),
            "description": md.get("description", ""),
            "selector_help": md.get("selector_help", ""),
            "lora_compatibility_note": md.get("lora_compatibility_note", ""),
            "family": family,
            "architecture": architecture,
            "resource_requirements": md.get("resource_requirements"),
            "is_i2v": wgp.test_class_i2v(mt),
            "is_t2v": wgp.test_class_t2v(mt),
            "guidance_max_phases": md.get("guidance_max_phases", 1),
            "fps": md.get("fps", 16),
            "supports_end_frame": "E" in md.get("image_prompt_types_allowed", ""),
            "supports_audio": bool(md.get("any_audio_prompt", False) or md.get("returns_audio", False)),
            "supports_audio_input": bool(
                md.get("any_audio_prompt", False)
                or md.get("supports_reference_audio", False)
            ),
            "generates_audio": bool(md.get("returns_audio", False)),
            "supports_ref_images": bool(md.get("image_ref_choices") or md.get("omni_reference")),
            "director": director_compat,
            "is_downloaded": _check_model_downloaded(mt),
            # When True, the UI hides this model unless Mature Mode is
            # enabled. Set in the model JSON's "model" block (e.g.
            # defaults/ltx2_22B_10eros.json). The backend ALWAYS returns
            # the entry — visibility gating happens client-side so a single
            # nsfw_mode toggle can show/hide without reloading models.
            "nsfw_only": bool(md.get("nsfw_only", False)),
        })

    for model in model3d_service.MODELS:
        models.append({
            "model_type": model["id"],
            "name": model["label"],
            "family": "hunyuan3d",
            "architecture": "hunyuan3d",
            # Multi-view variants are image-only; the rest accept a prompt.
            "is_i2v": not model["supports_text"],
            "is_t2v": model["supports_text"],
            "guidance_max_phases": 1,
            "fps": 0,
            "supports_end_frame": False,
            "supports_audio": False,
            "supports_ref_images": True,
            "is_downloaded": model3d_service.is_model_downloaded(model["id"]),
            "nsfw_only": False,
            # Variants sharing one HF repo lose their weights together when
            # the cache is deleted; the UI warns using this list.
            "shared_cache_group": [item["id"] for item in model3d_service.models_sharing_repo(model["id"])],
        })

    # UniRig is a generative ML model too (autoregressive skeleton + learned
    # skinning), so its weights are managed from the same catalog. tool_only
    # keeps it out of the generation model selectors: it rigs existing
    # meshes from the Animate tab instead of generating new ones.
    from services import rig_service
    models.append({
        "model_type": "unirig",
        "name": "UniRig (AI Rigging)",
        "family": "hunyuan3d",
        "architecture": "unirig",
        "is_i2v": False,
        "is_t2v": False,
        "guidance_max_phases": 1,
        "fps": 0,
        "supports_end_frame": False,
        "supports_audio": False,
        "supports_ref_images": False,
        "is_downloaded": rig_service.is_unirig_downloaded(),
        "nsfw_only": False,
        "tool_only": True,
    })

    payload = {"families": families, "models": models}
    if detail:
        return payload
    from services.mcp_compact import summarize_model_catalog
    return summarize_model_catalog(payload)


def debug_model(model_type: str):
    """Debug: show raw model definition and download check."""
    if _is_legacy_h3_model(model_type):
        return {
            "model_type": model_type,
            "runtime_installed": minimax_h3_service.is_runtime_installed(),
            "is_downloaded": minimax_h3_service.is_model_downloaded(),
            "runtime_dir": str(minimax_h3_service.COMFY_DIR),
        }
    if model_type in model3d_service.MODEL_BY_ID:
        model = model3d_service.MODEL_BY_ID[model_type]
        return {
            "model_type": model_type,
            "keys": model,
            "is_downloaded": model3d_service.is_model_downloaded(model_type),
            "ckpts_dir": str(model3d_service.HF_CACHE_DIR),
        }
    md = wgp.get_model_def(model_type)
    if not md:
        return {"error": "Model not found"}
    # Collect keys and sample values (avoid huge nested objects)
    keys_info = {}
    for k, v in md.items():
        if isinstance(v, (str, int, float, bool)):
            keys_info[k] = v
        elif isinstance(v, list):
            keys_info[k] = f"[list len={len(v)}] {str(v[:2])[:200]}"
        elif isinstance(v, dict):
            keys_info[k] = f"[dict keys={list(v.keys())[:10]}]"
        else:
            keys_info[k] = f"[{type(v).__name__}]"
    return {
        "model_type": model_type,
        "keys": keys_info,
        "is_downloaded": _check_model_downloaded(model_type),
        "ckpts_dir": wgp.fl.get_download_location() if hasattr(wgp.fl, 'get_download_location') else "unknown",
    }


def delete_model(model_type: str):
    """Delete a model's checkpoint files from disk."""
    active_generation_ids = [
        str(job_id)
        for job_id, job in list(_jobs.items())
        if (
            str(job.get("status") or "").lower()
            in {"created", "queued", "waiting_resource", "running", "cancelling"}
            or job_id in _active_gen_states
        )
        and str((job.get("params") or {}).get("model_type") or "") == model_type
    ]
    if active_generation_ids:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete {model_type} while generation job(s) "
                f"{', '.join(active_generation_ids[:5])} are active or queued. "
                "Cancel them and wait for shutdown first."
            ),
        )
    if _is_legacy_h3_model(model_type):
        deleted = minimax_h3_service.delete_model_cache()
        return {"deleted": deleted, "model_type": model_type}
    if model_type == "unirig":
        from services import rig_service
        if rig_service.has_active_unirig_jobs():
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot delete UniRig while an AI rig job is active, "
                    "queued, or still shutting down."
                ),
            )
        deleted = rig_service.delete_unirig_cache()
        return {"deleted": deleted, "model_type": model_type, "affected_models": []}
    if model_type in model3d_service.MODEL_BY_ID:
        if model3d_service.has_active_jobs(model_type):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot delete {model_type} while a 3D job using its "
                    "shared model cache is active, queued, or shutting down."
                ),
            )
        affected = [item["id"] for item in model3d_service.models_sharing_repo(model_type)]
        deleted = model3d_service.delete_model_cache(model_type)
        return {"deleted": deleted, "model_type": model_type, "affected_models": affected if deleted else []}
    md = wgp.get_model_def(model_type)
    if not md:
        return JSONResponse({"error": "Model not found"}, status_code=404)

    # Same group resolution as _check_model_downloaded, restricted to files
    # this entry owns — a finetune's delete removes its modules but leaves a
    # shared base transformer for the base model's own delete button.
    filenames = []
    for group in _model_weight_groups(model_type, owned_only=True):
        filenames.extend(_variant_group_filenames(group))
    deleted = []
    skipped_linked = []
    errors = []
    for filename in filenames:
        filepath = wgp.fl.locate_file(filename, error_if_none=False)
        if filepath and os.path.isfile(filepath):
            # locate_file also finds checkpoints in linked (read-only) model
            # folders — deleting those would break the OTHER install. Skip
            # them and tell the UI why the model still shows as available.
            if wgp.fl.is_protected_path(filepath):
                skipped_linked.append(filename)
                print(f"[Models] Skipped delete of linked checkpoint: {filepath}")
                continue
            try:
                os.remove(filepath)
                deleted.append(filename)
                print(f"[Models] Deleted checkpoint: {filepath}")
            except Exception as e:
                errors.append(f"{filename}: {e}")
    if errors:
        return JSONResponse({"deleted": deleted, "skipped_linked": skipped_linked, "errors": errors}, status_code=207)
    return {"deleted": deleted, "skipped_linked": skipped_linked, "model_type": model_type}


# ── Model pre-download ──────────────────────────────────────────────────
# Backs the click-to-download icon in Settings → System → Enabled Models.
# Fetches everything a generation would need (transformer + second-stage +
# modules + shared assets + text encoder) without occupying the GPU, so
# the first generation starts instantly. Progress reaches the UI through
# the existing /api/v1/downloads/active feed (safe_download's tqdm hook).
_model_downloads: dict = {}
_model_downloads_lock = threading.Lock()


def _download_model_files(model_type: str):
    """Resolve and fetch every file load_models() would download.

    The file list is ``services.engine.model_files.resolve_model_files``, the
    mirror of the file-resolution block of ``wgp.load_models``. ``wgp.py`` is
    vendored and is not edited. This name stays so the pre-download route
    keeps calling it.
    """
    from services.engine.model_files import download_model_files

    download_model_files(
        model_type,
        is_legacy_h3_model=_is_legacy_h3_model,
        ensure_quality_assets=minimax_h3_service.ensure_quality_assets,
        is_h3_downloaded=minimax_h3_service.is_model_downloaded,
        get_model_def=wgp.get_model_def,
        transformer_quantization=wgp.transformer_quantization,
        transformer_dtype_policy=wgp.transformer_dtype_policy,
        get_transformer_dtype=wgp.get_transformer_dtype,
        get_model_filename=wgp.get_model_filename,
        get_model_recursive_prop=wgp.get_model_recursive_prop,
        download_models=wgp.download_models,
        get_local_model_filename=wgp.get_local_model_filename,
        text_encoder_quantization=wgp.text_encoder_quantization,
        check_model_downloaded=_check_model_downloaded,
    )


def download_model(model_type: str):
    """Start downloading a model's files in the background."""
    md = wgp.get_model_def(model_type)
    if not md:
        return JSONResponse({"error": "Model not found"}, status_code=404)
    with _model_downloads_lock:
        entry = _model_downloads.get(model_type)
        if entry and entry["status"] == "downloading":
            return {"status": "downloading", "model_type": model_type}
        _model_downloads[model_type] = {"status": "downloading", "error": None, "started": time.time()}

    def _worker():
        try:
            _download_model_files(model_type)
            _model_downloads[model_type] = {"status": "completed", "error": None, "started": _model_downloads[model_type]["started"]}
            print(f"[Models] Pre-download complete: {model_type}")
        except Exception as e:
            traceback.print_exc()
            _model_downloads[model_type] = {"status": "failed", "error": str(e), "started": _model_downloads[model_type]["started"]}
            print(f"[Models] Pre-download FAILED for {model_type}: {e}")

    threading.Thread(target=_worker, daemon=True, name=f"model-dl-{model_type}").start()
    return {"status": "downloading", "model_type": model_type}


def model_downloads_status():
    """Status of model pre-downloads started via POST .../download."""
    return {"downloads": {mt: {"status": e["status"], "error": e["error"]} for mt, e in _model_downloads.items()}}


def list_resolutions():
    """List available resolution choices."""
    choices, _ = wgp.get_resolution_choices("")
    return {
        "resolutions": [{"label": label, "value": value} for label, value in choices]
    }


def get_defaults(model_type: str):
    """Get default settings for a model type."""
    if _is_legacy_h3_model(model_type):
        return dict(minimax_h3_service.DEFAULTS)
    if wgp.get_model_def(model_type) is None:
        raise HTTPException(status_code=404, detail=f"Unknown model: {model_type}")
    defaults = wgp.get_default_settings(model_type)
    return defaults


def reload_model_definitions():
    """Re-scan defaults/ + finetunes/ so a newly-imported checkpoint (or any
    hand-added finetune) appears in the model list without restarting the
    server. Returns the new model count and any model_types that appeared."""
    try:
        before = set(wgp.displayed_model_types)
        wgp.load_model_definitions()
        after = set(wgp.displayed_model_types)
        added = sorted(after - before)
        print(f"[Models] Reloaded model definitions: {len(after)} models"
              + (f", added {added}" if added else ""))
        return {"status": "ok", "model_count": len(after), "added": added}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Model reload failed: {e}")


def get_active_downloads():
    """Return a snapshot of in-progress model file downloads.

    UI polls this during long generation prep phases to surface
    download progress and stall warnings. Each entry includes
    `seconds_since_progress` so the UI can render "stalled — waiting
    for retry" badges without doing time math itself.

    Empty list when nothing is downloading. Best-effort tracking —
    if a download path bypasses `huggingface_hub`'s tqdm progress
    bar (some upstream Wan2GP code does this for misc files), it
    won't appear here even though the safe_download timeout
    protections still apply.
    """
    from services.safe_download import get_active_downloads as _get
    return {"downloads": _get()}
