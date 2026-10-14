"""System HTTP surface moved out of the full server.

The routes are not contiguous in the launch module, so each factory is
mounted where its first route used to be. Bodies are unchanged. The core
server keeps its own torch-free copies of the routes it already had.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from services import debug_trace, resource_scheduler


def create_system_runtime_router(
    *,
    wgp,
    _save_server_config,
    _jobs,
    _gen_lock,
    _app_dir,
    minimax_h3_service,
    torch,
):
    """Runtime capabilities, hardware detect, live stats and model release."""
    router = APIRouter()

    @router.get("/api/v1/runtime-capabilities")
    def get_runtime_capabilities():
        """Installation recipes and detected hardware, without loading AI models."""
        from services.runtime_profiles import detect_profiles
        return detect_profiles()

    @router.get("/api/v1/system-detect")
    def get_system_detect():
        """Return current hardware + the auto-tune recommendation for it.

        Always succeeds — on systems without CUDA, returns a
        "no GPU detected" recommendation rather than erroring, so the UI
        can show a meaningful message instead of a blank state.
        """
        from services.hardware_detect import detect_hardware
        from services.perf_recommend import recommend_settings

        hw = detect_hardware()
        rec = recommend_settings(hw)
        services = wgp.server_config.get("services", {})
        return {
            "hardware": hw,
            "recommended": rec,
            "auto_enabled": services.get("auto_performance", True),
        }

    @router.post("/api/v1/system-detect/apply")
    async def apply_system_detect():
        """Apply the current hardware's recommended settings to wgp_config.json.

        Re-runs detection (cheap) and writes the recommended values into
        both system-level config keys AND sets services.auto_performance=True.
        Returns the applied values so the UI can update its state without
        a separate GET round-trip.

        Side effects:
          - wgp_config.json is rewritten on disk
          - In-memory wgp.server_config is updated
          - Runtime overrides are applied where possible (attention_mode,
            vae_config, compile, vram_safety_coefficient) — same as the
            manual PUT /api/v1/system-config endpoint does.
          - Profile changes (video_profile, image_profile, audio_profile)
            only take effect on next model load; the response includes a
            flag noting this so the UI can show the user.
        """
        from services.hardware_detect import detect_hardware
        from services.perf_recommend import recommend_settings, applied_keys

        hw = detect_hardware()
        rec = recommend_settings(hw)

        # Write only the actual config keys (skip _recommendation_label
        # and _recommendation_reason which are display-only metadata).
        profile_changed = False
        for key in applied_keys():
            if key in rec:
                old_value = wgp.server_config.get(key)
                new_value = rec[key]
                if old_value != new_value:
                    wgp.server_config[key] = new_value
                    if key.endswith("_profile"):
                        profile_changed = True

        # Mark auto_performance ON so future PUTs to /system-config can
        # detect "user manually changed something" and flip it OFF.
        services = wgp.server_config.setdefault("services", {})
        services["auto_performance"] = True
        # Sentinel so the first-boot auto-tune (see startup) treats this as
        # already-applied and never overwrites what the user just applied.
        services["auto_performance_applied"] = True

        # Persist to disk
        _save_server_config()

        # Apply runtime side effects where possible (matches update_system_config)
        if "attention_mode" in rec:
            wgp.attention_mode = rec["attention_mode"]
        if "vae_config" in rec:
            wgp.vae_config = rec["vae_config"]
        if "compile" in rec:
            wgp.compile = rec["compile"]
        if "vram_safety_coefficient" in rec:
            wgp.args.vram_safety_coefficient = float(rec["vram_safety_coefficient"])

        return {
            "status": "ok",
            "hardware": hw,
            "applied": {k: rec[k] for k in applied_keys() if k in rec},
            "label": rec.get("_recommendation_label", ""),
            "reason": rec.get("_recommendation_reason", ""),
            # Tells UI to show "changes take effect on next model load" toast
            "profile_changed": profile_changed,
        }

    @router.get("/api/v1/system-stats")
    def get_system_stats_live():
        """Live hardware telemetry for the status indicators.

        Cheap enough (non-blocking psutil + a couple of NVML reads) to poll
        every ~2s. Also reports the generation model currently resident in
        VRAM so the UI can show "what's loaded right now".
        """
        # Currently-loaded generation model. WGP/mmgp keeps it resident
        # between jobs. `transformer_type` tracks the live load (set at the
        # end of load_models); `wan_model is not None` means it is actually
        # in memory right now vs. just the last/selected type.
        def current_model():
            model_name = None
            model_type = None
            model_loaded = False
            try:
                model_type = getattr(wgp, "transformer_type", None)
                model_loaded = getattr(wgp, "wan_model", None) is not None
                if model_type:
                    try:
                        md = wgp.get_model_def(model_type) or {}
                        model_name = md.get("name") or model_type
                    except Exception:
                        model_name = model_type
            except Exception:
                pass
            return {
                "name": model_name,
                "model_type": model_type,
                "loaded": model_loaded,
            }

        from services.live_stats import snapshot_system_stats
        return snapshot_system_stats(
            os.path.join(os.path.dirname(_app_dir), "ui", "dist"),
            current_model,
        )

    @router.post("/api/v1/system/release-model")
    def system_release_model():
        """Manually unload resident models to free VRAM/RAM (issue #12).

        Models deliberately stay loaded between generations so a retry with
        the same model skips the load. This endpoint is the explicit opt-out
        for users who want the memory back now — wgp reloads transparently
        on the next job. Refuses while anything is generating.
        """
        for j in _jobs.values():
            if j.get("status") in {
                "queued", "waiting_resource", "running", "cancelling",
            }:
                raise HTTPException(status_code=409, detail="A generation is in progress — stop it or wait for it to finish first.")
        try:
            from services.director_pipeline import _pipelines
            if any(p.get("status") == "running" for p in _pipelines.values()):
                raise HTTPException(status_code=409, detail="A Director run is in progress — stop it first.")
        except ImportError:
            pass
        if not _gen_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="A generation is in progress — stop it or wait for it to finish first.")
        try:
            released = []
            if minimax_h3_service.is_runtime_running():
                print("[ReleaseModel] Stopping isolated H3 Legacy runtime (user request)")
                minimax_h3_service.stop_runtime()
                released.append("H3 Legacy runtime")
            if getattr(wgp, "wan_model", None) is not None or getattr(wgp, "offloadobj", None) is not None:
                print("[ReleaseModel] Unloading generation model (user request)")
                wgp.release_model()
                released.append("generation model")
            try:
                from services import llm_service
                if llm_service.is_loaded():
                    print("[ReleaseModel] Unloading LLM (user request)")
                    llm_service.unload_model()
                    released.append("LLM")
            except Exception as e:
                print(f"[ReleaseModel] LLM unload skipped: {e}")
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            return {"released": released}
        finally:
            _gen_lock.release()

    return router


def create_system_preflight_router(*, wgp):
    """Environment checks the full server runs before a generation."""
    router = APIRouter()

    @router.get("/api/v1/system/preflight")
    def system_preflight():
        """Environment sanity checks surfaced to the UI on startup.

        Catches the three things that otherwise fail deep inside a
        generation with a cryptic traceback: ffmpeg missing (every
        video/audio mux needs it), no CUDA GPU (the pipeline is CUDA-only),
        and low free disk on the output drive (a long Director run writes
        gigabytes). Each check degrades to a warning the UI can show once,
        not a hard failure — the user might genuinely be on a CPU box just
        browsing.
        """
        import shutil as _shutil

        checks = []

        # ffmpeg — hard requirement for muxing/concat/audio.
        ffmpeg_path = _shutil.which("ffmpeg")
        if not ffmpeg_path:
            checks.append({
                "id": "ffmpeg",
                "level": "error",
                "message": "ffmpeg was not found on PATH. Video and audio "
                           "export will fail. Install ffmpeg and restart HocusPocus Lab.",
            })

        # CUDA — the generation pipeline is NVIDIA-only.
        try:
            import torch as _torch
            if not _torch.cuda.is_available():
                checks.append({
                    "id": "cuda",
                    "level": "error",
                    "message": "No CUDA GPU detected. HocusPocus Lab's generation "
                               "pipeline requires an NVIDIA GPU; generation will "
                               "not work on this machine.",
                })
        except Exception:
            checks.append({
                "id": "torch",
                "level": "error",
                "message": "PyTorch failed to import — the install may be "
                           "incomplete. Try Reset then Install in Pinokio.",
            })

        # Free disk on the output drive.
        try:
            save_path = wgp.server_config.get("save_path", "outputs")
            probe_dir = save_path if os.path.isdir(save_path) else os.getcwd()
            free_gb = _shutil.disk_usage(probe_dir).free / (1024 ** 3)
            if free_gb < 5:
                checks.append({
                    "id": "disk",
                    "level": "error",
                    "message": f"Only {free_gb:.1f} GB free on the output drive. "
                               "Generation writes large files and will fail soon. "
                               "Free up space.",
                })
            elif free_gb < 20:
                checks.append({
                    "id": "disk",
                    "level": "warn",
                    "message": f"{free_gb:.0f} GB free on the output drive. Model "
                               "downloads and long runs can exhaust this — keep an "
                               "eye on free space.",
                })
        except Exception:
            pass

        return {"ok": not any(c["level"] == "error" for c in checks), "checks": checks}

    return router


def create_system_diagnostics_router(*, wgp):
    """Debug user actions and the WanGP processor list."""
    router = APIRouter()

    @router.post("/api/v1/debug/user-action")
    async def record_debug_user_action(request: Request):
        """Record non-API UI actions (buttons/navigation), never typed values."""
        if not debug_trace.is_enabled():
            return {"status": "disabled"}
        body = await request.json()
        debug_trace.trace_event(
            "user_action", "ui_control",
            control=str(body.get("control") or "")[:500],
            control_type=str(body.get("control_type") or "")[:80],
            view=str(body.get("view") or "")[:500],
        )
        return {"status": "ok"}

    @router.get("/api/v1/wangp/capabilities")
    async def wangp_capabilities():
        from shared.wangp1272.processors import capabilities
        processors = capabilities()
        for multiplier in (2, 3, 4):
            enabled = multiplier != 3 or wgp.server_config.get("rife_version", "v4") == "v4"
            processors.append(dict(value=f"rife{multiplier}", label=f"RIFE ×{multiplier}", kind="temporal", media=["video"], enabled=enabled, reason="" if enabled else "RIFE ×3 requires version 4.26"))
        return {"revision": "362c3467a70e1136ceb52eec95907205a8f88543", "processors": processors}

    # Launch's MCP processor tool calls this same function.
    create_system_diagnostics_router.wangp_capabilities = wangp_capabilities
    return router


def create_system_resources_router():
    """The coordinator's active and waiting leases."""
    router = APIRouter()

    @router.get("/api/v1/resources")
    def list_resource_lanes():
        """Expose the coordinator's real active and waiting leases for the UI."""
        return {"lanes": resource_scheduler.coordinator.snapshot()}

    return router
