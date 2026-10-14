"""Maestro Launch Server

FastAPI wrapper around WanGP (wgp.py) that:
- Serves the new React UI at /
- Mounts the classic Gradio UI at /classic
- Exposes REST API at /api/v1/*

Usage:
    python launch.py [--compile]

Environment variables:
    SERVER_NAME  - Host to bind (default: 127.0.0.1)
    SERVER_PORT  - Port to bind (default: 7860)
"""

import gc
import base64
import copy
import sys

# Before torch, because the caching allocator reads this when it initializes and ignores it afterwards.
#
# Video models allocate a handful of very large, short-lived activation tensors per block, which leaves the
# default allocator holding gigabytes of reserved-but-unallocated blocks too fragmented to reuse -- enough
# that a generation can fail to find room for a tensor while nominally having the memory free. Expandable
# segments let those regions grow and be reused instead of stranding them.
#
# `setdefault`, so anyone already tuning the allocator keeps their setting.
import os

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

_app_dir_for_identity = os.path.dirname(os.path.abspath(__file__))
if _app_dir_for_identity not in sys.path:
    sys.path.insert(0, _app_dir_for_identity)
from app_identity import read_app_version, startup_identity

APP_VERSION = read_app_version()
startup_identity()  # pin the deployed commit before anything can change the checkout

import torch
import glob
import hashlib
import json
import re
import math
import random
import time
import uuid
import asyncio
import threading
import traceback
import requests
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

# --- Bootstrap: CWD must be app/ and sys.argv must be patched before importing wgp ---
_app_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_app_dir)

# Preserve original argv, patch for wgp's argparse
_original_argv = sys.argv[:]
_launch_args = sys.argv[1:]  # Save our own args

# Build argv for wgp: keep flags it understands, always include --multiple-images
_wgp_argv = ["wgp.py", "--multiple-images"]
if "--compile" in _launch_args:
    _wgp_argv.append("--compile")
sys.argv = _wgp_argv

# Install download stall-detection BEFORE wgp imports anything that
# would download model files. The patch sets a default read timeout
# on requests calls so stalled HF CDN connections fail-fast (~30s)
# instead of hanging indefinitely; HF's resumable-download retry
# layer picks up from the partial file. Also hooks tqdm to track
# download progress for the UI's downloads-in-progress banner.
print("[HocusPocus Lab] Installing download stall protection...")
from services import safe_download  # noqa: F401 (side-effect import)

# HuggingFace token-path robustness (fixes the "Permission denied:
# .../HF_AUTH/token" crash on machines that never logged into HF).
# Pinokio points HF_TOKEN_PATH at its shared token store
# (PINOKIO_HOME/cache/HF_AUTH/token). huggingface_hub's get_token() reads
# that path but only catches FileNotFoundError — if the path exists in an
# unreadable state (e.g. a directory placeholder before any login), the
# read raises PermissionError and crashes the very first model download,
# even though ALL of Maestro's default models live on PUBLIC repos that
# need no auth. Neutralize a broken token path so downloads fall back to
# anonymous; a real token (user ran Pinokio's hf.login) stays untouched,
# so gated models + higher HF rate limits keep working.
_hf_token_path = os.environ.get("HF_TOKEN_PATH")
if _hf_token_path:
    try:
        with open(_hf_token_path, "r", encoding="utf-8"):
            pass  # readable token file → keep it (real login)
    except FileNotFoundError:
        pass  # absent → huggingface_hub handles this gracefully (anonymous)
    except OSError as _hf_err:
        print(f"[HocusPocus Lab] HF_TOKEN_PATH is set but unreadable "
              f"({type(_hf_err).__name__}) — using anonymous HuggingFace "
              "access for public models.")
        os.environ.pop("HF_TOKEN_PATH", None)
        # This guard runs before wgp imports huggingface_hub, so the pop
        # above is enough — the hub reads HF_TOKEN_PATH from the env at
        # import. But the hub FREEZES it into constants.HF_TOKEN_PATH at
        # import time, so if some earlier import already loaded it, redirect
        # that cached path to a guaranteed-absent file (→ read gives
        # FileNotFoundError, which the hub DOES catch → anonymous).
        _hf_const = sys.modules.get("huggingface_hub.constants")
        if _hf_const is not None:
            import tempfile
            _hf_const.HF_TOKEN_PATH = os.path.join(tempfile.gettempdir(), "maestro_no_hf_token")

# Reject an invalid acceptance policy before importing the heavyweight engine.
from services import execution_mode

# Now safe to import wgp - all module-level code will run with patched argv
print("[HocusPocus Lab] Importing WanGP engine...")
import wgp
from services.generation import bind_wgp, get_model_def
bind_wgp(wgp)
from services.kernel.context import build_context
ctx = build_context(
    profile="full",
    # Late-bound: these are defined further down, and the task publisher may not exist yet.
    is_legacy_h3_model=lambda model_type: _is_legacy_h3_model(model_type),
    is_minimax_h3_model=lambda model_type: _is_minimax_h3_model(model_type),
    cancel_legacy_h3=lambda: minimax_h3_service.cancel(),
    task_publisher=lambda: globals().get("_publish_generation_task"),
)

# The kernel's services (services/kernel). These names are launch's historical handles to
# the same objects: code that has not moved yet keeps using them, and a dictionary or a
# lock here is the one the context holds, never a copy.
_save_server_config = ctx.config.save
_get_active_workspace = ctx.workspaces.active
_workspace_dir = ctx.workspaces.workspace_dir
_list_workspaces = ctx.workspaces.list
_persist_active_workspace = ctx.workspaces.persist_active
_safe_join = ctx.paths.safe_join
_resolve_output_move_path = ctx.paths.resolve_output_move_path
_resolve_request_media_path = ctx.paths.resolve_request_media_path
_story_cover_reference_path = ctx.paths.story_cover_reference_path
_UPLOAD_TRANSCODE_SLOTS = ctx.paths.transcode_slots
_stream_upload = ctx.paths.stream_upload
_transcode_upload = ctx.paths.transcode_upload
_task_registry = ctx.tasks.for_workspace
_jobs = ctx.jobs.registry
_local_gpu_lane = ctx.jobs.local_gpu_lane
_gen_lock = ctx.jobs.gen_lock
_active_gen_states = ctx.jobs.active_states
_queue_recovery_lock = ctx.jobs.recovery_lock
_durable_generation_queue = ctx.jobs.durable_queue
_coordinated_generation_slot = ctx.jobs.slot
_is_durable_generation_job = ctx.jobs.is_durable_job
_persist_generation_job = ctx.jobs.persist_job
_remove_persisted_generation_job = ctx.jobs.remove_persisted_job
_new_generation_job = ctx.jobs.new_job
_register_manual_generation_job = ctx.jobs.register_manual_job
_generation_job_acceptance = ctx.jobs.job_acceptance
_public_generation_details = ctx.jobs.public_details
_pending_gpu_jobs = ctx.jobs.pending_gpu_jobs
_request_generation_cancel = ctx.jobs.cancel
from services import model3d_service, minimax_h3_service, minimax_image_service
from services import tools_upscale as tools_upscale_service
from services import debug_trace
from routers.lan_auth import create_lan_auth_router
from services.lan_auth import LanAuthMiddleware, describe_lan_auth_startup
from services.media_paths import resolve_voice_ref_paths
from shared.utils.generation_timing import GenerationTaskTimer
from shared.utils.ltx_prompt_queue import schedule_ltx_prompt_windows
from models.minimax_h3.turbo import (
    MINIMAX_H3_TURBO_LORA_FILENAME,
    MINIMAX_H3_TURBO_LORA_REPO_ID,
    MINIMAX_H3_TURBO_LORA_REVISION,
    MINIMAX_H3_TURBO_LORA_SHA256,
    MINIMAX_H3_TURBO_LORA_SIZE,
)
print(f"[HocusPocus Lab] WanGP loaded: {len(wgp.displayed_model_types)} models available")
# Base save path always comes from server_config["save_path"] (never from wgp.save_path which gets workspace-modified)

# Apply active workspace on startup
_startup_ws = wgp.server_config.get("services", {}).get("active_workspace", "default")
if _startup_ws != "default":
    _ws_dir = os.path.join(wgp.server_config.get("save_path", "outputs"), _startup_ws)
    os.makedirs(_ws_dir, exist_ok=True)
    wgp.save_path = _ws_dir
    wgp.image_save_path = _ws_dir
    print(f"[Workspace] Active workspace: {_startup_ws} ({_ws_dir})")
else:
    _default_path = wgp.server_config.get("save_path", "outputs")
    print(f"[Workspace] Active workspace: default ({_default_path})")

# Reclaim trash-renamed leftovers (deleted-but-locked files/folders from a
# previous run whose deferred cleanup didn't finish before shutdown).
try:
    from services.win_safe_files import sweep_trash as _sweep_trash
    _sweep_trash(wgp.server_config.get("save_path", "outputs"))
except Exception as _sweep_err:
    print(f"[Workspace] Trash sweep skipped: {_sweep_err}")

# Performance auto-tune migration: pre-existing installs (config file
# was loaded from disk, not freshly created) have no auto_performance
# key in services. Default those to False so we never silently overwrite
# the user's manually-tuned profile/quant/coefficient settings.
#
# Fresh installs are NOT affected — the wgp.py first-launch code path
# (config_load_filename doesn't exist) sets auto_performance=True
# explicitly before we get here.
#
# This is a one-shot migration: after the first boot post-update, the
# key is persisted, so subsequent boots are no-ops.
_services = wgp.server_config.setdefault("services", {})
if "auto_performance" not in _services:
    _services["auto_performance"] = False
    try:
        _save_server_config()
        print("[HocusPocus Lab] Migration: existing config detected, auto_performance set to False (manual mode preserved)")
    except Exception as _e:
        print(f"[HocusPocus Lab] Migration: failed to persist auto_performance default: {_e}")

# First-boot auto-tune: a fresh install has auto_performance=True but the
# recommended profile was only ever WRITTEN when the user opened Settings and
# clicked apply. Until then the first generation ran on wgp's conservative
# fallback profile — so a capable card could OOM on its very first video with
# a proactive fix sitting unused. Apply the hardware recommendation ONCE here,
# before any model loads, so the first generation already uses the right
# profile. Gated on a sentinel so it's a true one-shot and never fights a user
# who later tunes manually (that flips auto_performance off).
if _services.get("auto_performance") and not _services.get("auto_performance_applied"):
    try:
        from services.hardware_detect import detect_hardware as _detect_hw
        from services.perf_recommend import recommend_settings as _recommend, applied_keys as _applied_keys
        _hw = _detect_hw()
        if _hw.get("cuda_available"):
            _rec = _recommend(_hw)
            for _k in _applied_keys():
                if _k in _rec:
                    wgp.server_config[_k] = _rec[_k]
            _services["auto_performance_applied"] = True
            _save_server_config()
            print(f"[HocusPocus Lab] First-boot auto-tune applied: {_rec.get('_recommendation_label', 'recommended profile')} "
                  f"(video_profile={_rec.get('video_profile')}, vram_safety_coefficient={_rec.get('vram_safety_coefficient')})")
        else:
            print("[HocusPocus Lab] First-boot auto-tune skipped: no CUDA GPU detected.")
    except Exception as _e:
        print(f"[HocusPocus Lab] First-boot auto-tune skipped ({_e}); using defaults until Settings → Performance is applied.")

# Restore argv
sys.argv = _original_argv

# --- FastAPI setup ---
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from services.access_log_filter import install_quiet_access_filter

# Uvicorn's logging configuration replaces handlers but retains logger-level
# filters. Install early, then idempotently confirm it again before startup.
install_quiet_access_filter()

api = FastAPI(title="HocusPocus Lab API", version=APP_VERSION or "0.0.0")
api.state.runtime = ctx


@api.exception_handler(execution_mode.ExecutionModeError)
async def execution_mode_error_handler(
    _request: Request,
    exc: execution_mode.ExecutionModeError,
):
    """Keep policy refusals explicit across every specialist submission route."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})

debug_trace.configure(
    enabled=lambda: bool(
        wgp.server_config.get("services", {}).get("debug_trace_enabled", False)
    ),
    log_dir=lambda: os.path.join(os.path.dirname(_app_dir), "logs", "debug"),
)
debug_trace.start_session(
    workspace=wgp.server_config.get("services", {}).get("active_workspace", "default"),
    config_file=wgp.server_config_filename,
    app_version=api.version,
)

# Upload size caps — enforced in upload handlers. Tuned for real-world
# media the app actually ingests; anything larger is almost certainly
# abuse or a user mistake.
from routers.uploads import MAX_IMAGE_UPLOAD_BYTES   # 500 MB, defined with the upload route

# CORS — restricted to localhost (the Vite dev server + the bundled UI
# served from the same FastAPI process + Pinokio's HTTPS proxy at
# https://<port>.localhost). Do NOT loosen this to `*`: browser access stays
# intentionally same-origin even when LAN session authentication is enabled.
_cors_origin_regex = r"^https?://(127\.0\.0\.1|localhost|\d+\.localhost)(:\d+)?$"
from services.host_guard import install_host_guard
install_host_guard(api)
api.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)
api.include_router(create_lan_auth_router())


@api.middleware("http")
async def protect_cross_origin_mutations(request: Request, call_next):
    """Reject browser mutations from a different origin, including on LAN."""
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlsplit

            try:
                origin_host = (urlsplit(origin).netloc or "").casefold()
            except ValueError:
                origin_host = ""
            request_host = str(request.headers.get("host") or "").casefold()
            local_hosts = {"localhost", "127.0.0.1", "[::1]"}
            origin_name = origin_host.rsplit(":", 1)[0]
            request_name = request_host.rsplit(":", 1)[0]
            same_origin_host = bool(origin_host and origin_host == request_host)
            local_proxy = origin_name in local_hosts and request_name in local_hosts
            pinokio_proxy = bool(re.fullmatch(r"\d+\.localhost(?::\d+)?", origin_host))
            if not (same_origin_host or local_proxy or pinokio_proxy):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-origin API mutations are not allowed"},
                )
    return await call_next(request)


@api.middleware("http")
async def trace_user_mutations(request: Request, call_next):
    """Record reconstructible user/API actions while debug tracing is on."""
    should_trace = (
        debug_trace.is_enabled()
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path != "/api/v1/debug/user-action"
    )
    event_id = uuid.uuid4().hex if should_trace else ""
    started = time.monotonic()
    if should_trace:
        content_type = request.headers.get("content-type", "")
        request_body = None
        if "application/json" in content_type:
            try:
                raw_body = await request.body()
                request_body = json.loads(raw_body) if raw_body else None
            except Exception as exc:
                request_body = {"parse_error": str(exc)}
        elif content_type:
            request_body = f"<{content_type}; body omitted>"
        from services.task_manager import redact_sensitive_data

        debug_trace.trace_event(
            "user_action", "api_request", event_id=event_id, phase="request",
            method=request.method, path=request.url.path,
            query=redact_sensitive_data(dict(request.query_params)),
            body=redact_sensitive_data(request_body),
        )
    try:
        with debug_trace.context_scope(
            request_id=event_id or None,
            http_method=request.method,
            http_path=request.url.path,
        ):
            response = await call_next(request)
    except Exception as exc:
        if should_trace:
            debug_trace.trace_event(
                "user_action", "api_request", event_id=event_id, phase="error",
                method=request.method, path=request.url.path,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
                error={"type": type(exc).__name__, "message": str(exc)},
            )
        raise
    if should_trace:
        debug_trace.trace_event(
            "user_action", "api_request", event_id=event_id, phase="response",
            method=request.method, path=request.url.path,
            status_code=response.status_code,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
    return response


# Who a loopback call (an MCP tool through these routes) or the Wizard says it is
# for, in the caller scope: what a route records (take approvals, rig sidecars)
# names it. Attribution only (services/agent_activity.py).
from services.agent_activity import ActorHeaderMiddleware
api.add_middleware(ActorHeaderMiddleware)

# Registered after decorator-based middleware so Starlette places LAN auth at
# the outside of the stack. Unauthenticated remote requests are rejected
# before request-body tracing or endpoint work can run.
api.add_middleware(LanAuthMiddleware)

# --- Generation job tracking ---
from services.job_lifecycle import (
    GENERATED_MEDIA_EXTENSIONS,
    acknowledge_cancel,
    collect_job_outputs,
    ensure_generation_priority,
    finish_job,
    generation_queue_position,
    is_cancel_requested,
    new_media_files,
    record_job_outputs,
    register_abort_state,
    request_cancel,
    set_job_state_observer,
    snapshot_job,
    try_requeue,
    try_start,
    unregister_abort_state,
    update_job,
)
from services.asset_manifest import publish_generation_sidecar, publish_generation_sidecar_best_effort
from services import resource_scheduler

_H3_IDLE_RELEASE_SECONDS = 10.0
_h3_idle_release_timer: threading.Timer | None = None
_h3_idle_release_lock = threading.RLock()


def _prepare_local_gpu_owner(
    _lane: resource_scheduler.ResourceLane,
    _task_id: str,
    description: str,
) -> None:
    """Hand GPU 0 to one engine without retaining incompatible runtimes."""
    owner_kind = resource_scheduler.gpu_engine_kind(description)
    is_legacy_h3 = owner_kind == resource_scheduler.GPU_ENGINE_H3_LEGACY
    is_wgp_generation = owner_kind == resource_scheduler.GPU_ENGINE_WGP
    is_local_llm = owner_kind == resource_scheduler.GPU_ENGINE_LOCAL_LLM

    if not is_legacy_h3:
        minimax_h3_service.cancel_idle_shutdown()
        minimax_h3_service.stop_runtime()
    released_wgp = False
    if not is_wgp_generation and (
        getattr(wgp, "wan_model", None) is not None
        or getattr(wgp, "offloadobj", None) is not None
    ):
        print(
            f"[Resources] Releasing WGP runtime before "
            f"{description or 'the next local GPU owner'}"
        )
        wgp.release_model()
        released_wgp = True
    if not is_local_llm:
        try:
            from services import llm_service
            llm_status = llm_service.get_status()
            if (
                llm_status.get("provider") == "local"
                and str(llm_status.get("device") or "").startswith("cuda")
            ):
                llm_service.unload_model()
        except Exception as exc:
            print(f"[Resources] Local CUDA LLM cleanup skipped: {exc}")
    # release_model() already flushes Torch caches and performs collection.
    # Repeating that native teardown immediately was both redundant and, when
    # handing ACE-Step to isolated H3 ConvRot, could finalize extension-owned
    # objects twice at the exact boundary where the process previously died.
    if not released_wgp:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


resource_scheduler.coordinator.set_prepare_hook(
    _local_gpu_lane, _prepare_local_gpu_owner,
)


def _publish_generation_sidecar_for_studio_job(
    job: dict,
    output_path: str,
    sidecar: dict,
    *,
    tool: str = "studio",
) -> None:
    """Publish one Studio result with its initiating command and real location."""
    from services.asset_manifest import publish_generation_job_sidecar
    publish_generation_job_sidecar(
        job,
        output_path,
        sidecar,
        job_id_key="id",
        output_folder=job.get("workspace"),
        tool=tool,
    )


def _is_legacy_h3_model(model_type: str | None) -> bool:
    return str(model_type or "").strip() == minimax_h3_service.MODEL_ID


def _is_character_sheet_engine(body: dict | None) -> bool:
    return (
        isinstance(body, dict)
        and str(body.get("character_sheet_engine") or "").strip()
        == minimax_h3_service.CHARACTER_SHEET_ENGINE
    )


def _is_minimax_h3_model(model_type: str | None) -> bool:
    """Recognize every native H3 variant from the current model registry."""
    candidate = str(model_type or "").strip()
    if not candidate:
        return False
    try:
        model_def = wgp.get_model_def(candidate) or {}
    except Exception:
        model_def = {}
    return (
        candidate.lower().startswith("minimax_h3")
        or str(model_def.get("architecture") or "").lower().startswith("minimax_h3")
    )


def _cancel_h3_idle_release() -> None:
    """Prevent a delayed native-model release from racing newly queued work."""
    global _h3_idle_release_timer
    with _h3_idle_release_lock:
        timer = _h3_idle_release_timer
        _h3_idle_release_timer = None
        if timer is not None:
            timer.cancel()


def _release_h3_when_queue_allows(job_id: str) -> None:
    """Keep native H3 warm for its queue, then release WGP-owned memory."""
    global _h3_idle_release_timer
    pending = _pending_gpu_jobs(exclude_job_id=job_id)
    h3_pending = any(
        _is_minimax_h3_model(candidate.get("params", {}).get("model_type"))
        and not _is_legacy_h3_model(candidate.get("params", {}).get("model_type"))
        for candidate in pending
    )
    if h3_pending:
        _cancel_h3_idle_release()
        print("[MiniMax H3] Keeping runtime warm for a queued H3 job.")
        return

    _cancel_h3_idle_release()
    if pending:
        print("[MiniMax H3] Releasing native runtime for a queued non-H3 GPU job.")
        wgp.release_model()
        return

    print(
        f"[MiniMax H3] Queue idle; releasing native runtime in "
        f"{int(_H3_IDLE_RELEASE_SECONDS)}s unless another job arrives."
    )

    def _release_if_still_idle() -> None:
        global _h3_idle_release_timer
        with _h3_idle_release_lock:
            _h3_idle_release_timer = None
            if _pending_gpu_jobs(exclude_job_id=job_id) or _active_gen_states:
                return
            if not _is_minimax_h3_model(getattr(wgp, "transformer_type", None)):
                return
            wgp.release_model()
            print("[MiniMax H3] Native WGP runtime released after idle grace period.")

    with _h3_idle_release_lock:
        timer = threading.Timer(_H3_IDLE_RELEASE_SECONDS, _release_if_still_idle)
        timer.daemon = True
        _h3_idle_release_timer = timer
        timer.start()


def _release_legacy_h3_when_queue_allows(job_id: str) -> None:
    """Keep the isolated ConvRot runtime only for adjacent Legacy jobs."""
    pending = _pending_gpu_jobs(exclude_job_id=job_id)
    legacy_pending = any(
        _is_legacy_h3_model(candidate.get("params", {}).get("model_type"))
        for candidate in pending
    )
    if legacy_pending:
        minimax_h3_service.cancel_idle_shutdown()
        print("[H3 Legacy] Keeping ConvRot runtime warm for a queued Legacy job.")
        return

    if pending:
        print("[H3 Legacy] Releasing ConvRot runtime for a queued non-Legacy GPU job.")
        minimax_h3_service.stop_runtime()
        return

    print(
        f"[H3 Legacy] Queue idle; releasing ConvRot runtime in "
        f"{int(minimax_h3_service.DEFAULT_IDLE_SHUTDOWN_SECONDS)}s."
    )
    minimax_h3_service.schedule_idle_shutdown(
        minimax_h3_service.DEFAULT_IDLE_SHUTDOWN_SECONDS,
        lambda: any(
            _is_legacy_h3_model(candidate.get("params", {}).get("model_type"))
            for candidate in _pending_gpu_jobs(exclude_job_id=job_id)
        ),
    )


def _interrupt_wan_model() -> None:
    """Interrupt only the Wan run bound to the active lifecycle state."""
    model = wgp.wan_model
    if model is not None and hasattr(model, "_interrupt"):
        model._interrupt = True

# Director pipeline init lives with the planner routes. Music generation and
# quick-video batches call this same function.
from routers.director import (
    _init_pipeline,
    bind_director_runtime,
    create_director_pipeline_edit_router,
    create_director_pipeline_run_router,
    create_director_planner_router,
    director_pipeline_resume,
    director_pipeline_stop,
)


# ============================================================================
# API Routes: /api/v1/*
# ============================================================================

def _variant_group_filenames(urls) -> list:
    """Flatten one weight group (list of variant URLs / dict entries) to file names."""
    names = []
    for url_entry in urls:
        url_str = url_entry
        if isinstance(url_entry, dict):
            inner = url_entry.get("URLs", url_entry.get("url", []))
            url_str = inner[0] if isinstance(inner, list) and inner else (inner if isinstance(inner, str) else "")
        if not isinstance(url_str, str) or not url_str:
            continue
        names.append(url_str.rstrip("/").split("/")[-1])
    return names


def _variant_group_downloaded(urls) -> bool:
    """True when ANY variant (full bf16 vs quantized int8...) of one weight
    group exists locally. Resolves through the files locator so checkpoints
    in linked model folders (Settings -> System -> Linked Model Folders)
    light up too — a hardcoded ckpts_dir check misses every secondary root."""
    for filename in _variant_group_filenames(urls):
        if wgp.fl.locate_file(filename, error_if_none=False) is not None:
            return True
    return False


def _model_weight_groups(model_type: str, owned_only: bool = False) -> list:
    """All weight groups a model needs on disk: main URLs + weight modules.

    "URLs" may be a string pointer to another model type (finetunes such as
    z_image_control or scail2_14B_fast use "URLs": "<base_model>"). Resolve
    recursively like the engine does — iterating the raw value would walk
    the characters of the string and permanently report not-downloaded.

    owned_only=True returns only groups this entry itself declares (skips a
    string-pointer base). Used by delete: removing a finetune must not pull
    the shared base transformer out from under its sibling entries — the
    base is deleted from the base model's own row instead.

    String-named modules resolve through the engine's module registry and
    are intentionally left out (they were never counted here).
    """
    md = wgp.get_model_def(model_type) or {}
    groups = []
    raw_urls = md.get("URLs", None)
    if isinstance(raw_urls, str):
        if not owned_only:
            urls = wgp.get_model_recursive_prop(model_type, "URLs", return_list=True)
            if urls:
                groups.append(urls)
    elif raw_urls:
        groups.append(raw_urls)
    for module in md.get("modules", []):
        if isinstance(module, list):
            groups.append(module)
        elif isinstance(module, dict):
            group = module.get("URLs", [])
            if group:
                groups.append(group)
    return groups


def _missing_image_model_files(model_type: str) -> list[str]:
    """Explain readiness using the same checkpoint roots and variant groups."""
    missing = [" or ".join(_variant_group_filenames(group))
               for group in _model_weight_groups(model_type) if not _variant_group_downloaded(group)]
    definition = wgp.get_model_def(model_type) or {}
    required = list(definition.get("required_model_assets", []))
    if definition.get("vision_encoder_filename"):
        required.append(definition["vision_encoder_filename"])
    missing.extend(path for path in required if wgp.fl.locate_file(path, error_if_none=False) is None)
    for url in wgp.get_model_recursive_prop(model_type, "loras", return_list=True):
        filename = url.split("/")[-1]
        if not os.path.isfile(wgp.resolve_lora_path(model_type, filename)):
            missing.append(filename)
    return list(dict.fromkeys(name for name in missing if name))


# The catalog, the download check and the pre-download map. These names are
# the same objects the service holds: generation and the profile still call
# them, and the download map is the one instance.
from services.model_downloads import (  # noqa: E402
    _check_model_downloaded,
    _download_model_files,
    _folder_model_ready,
    _model_downloads,
    _model_downloads_lock,
    list_models,
    configure as _configure_model_downloads,
)
_configure_model_downloads(
    engine=wgp,
    model_weight_groups=_model_weight_groups,
    variant_group_downloaded=_variant_group_downloaded,
    variant_group_filenames=_variant_group_filenames,
    is_legacy_h3_model=_is_legacy_h3_model,
    jobs=_jobs,
    active_gen_states=_active_gen_states,
)

from routers.model_catalog import create_model_list_router  # noqa: E402

api.include_router(create_model_list_router())


def mcp_model_list(args):
    """models and models.list: summaries unless detail is true or one id is named."""
    if not isinstance(args, dict):
        args = {}
    model_type = args.get("model_type")
    if isinstance(model_type, str) and model_type.strip():
        return get_model_options(model_type)
    return list_models(detail=args.get("detail") is True)


# Model visibility, selections and the production profile. These names are the
# same objects the service holds: code that has not moved keeps calling them,
# and the write lock is the one instance.
from services.model_visibility import (  # noqa: E402
    _MODEL_SELECTION_CONFIG_KEY,
    _MODEL_VISIBILITY_CONFIG_KEY,
    _MODEL_VISIBILITY_WRITE_LOCK,
    _PRODUCTION_PROFILE_CONFIG_KEY,
    _active_production_profile,
    _default_production_profile,
    _model_selections_response,
    _model_visibility_response,
    _normalize_model_selections,
    _normalize_model_visibility_ids,
    _normalize_production_profile,
    _persist_model_visibility_config,
    _production_profile_response,
    _profile_image_model_type,
    configure as _configure_model_visibility,
)
_configure_model_visibility(engine=wgp, check_model_downloaded=_check_model_downloaded)

from routers.model_preferences import create_model_preferences_router  # noqa: E402

api.include_router(create_model_preferences_router())


def _effective_llm_routing(services: dict | None = None) -> tuple[str, str, str]:
    """Resolve generic LLM work from the production profile, not stale UI keys.

    API keys and device preferences remain in ``services``.  This separation is
    what prevents Director/prompt tools from downloading a local model while a
    new or migrated install already advertises MiniMax in its global profile.
    """
    from services import llm_routing

    return llm_routing._effective_llm_routing(
        services,
        text_profile=_active_production_profile().get("text", {}),
        default_provider="local",
    )


def _llm_provider_credentials(provider: str, services: dict, remote_url: str = "") -> tuple[str, str]:
    from services import llm_routing

    return llm_routing._llm_provider_credentials(provider, services, remote_url)



from routers.model_catalog import create_model_files_router  # noqa: E402

api.include_router(create_model_files_router())


from routers.settings import create_primary_settings_router
api.include_router(create_primary_settings_router(wgp=wgp))


from services import lora_guides  # noqa: E402
from services.lora_guides import (  # noqa: E402
    _append_lora_guide_scan_result,
    _build_lora_context,
    _generate_and_save_lora_guide,
    _lora_guide_scan_lock,
    _lora_guide_scans,
    _register_lora_guide_scan,
    _update_lora_guide_scan,
)
from routers.lora_guides import create_lora_guide_status_router  # noqa: E402

api.include_router(create_lora_guide_status_router())


from services import lora_library  # noqa: E402
from services.lora_library import (  # noqa: E402
    _linked_lora_roots,
    _lora_is_compatible_with_model,
    _resolve_lora_root,
)
from routers.loras import create_lora_library_router  # noqa: E402

api.include_router(create_lora_library_router())




# ── video_prompt_type normalization ─────────────────────────────────
# Maestro's video_prompt_type is a string of single-letter mode flags
# the wgp.py pipeline uses to decide what optional inputs are needed
# (e.g. "I" → image_refs required, "V" → video/image guide required).
# wgp.py rejects the job with a friendly UI error if a flag is set but
# the corresponding input is missing.
#
# Without this normalization, stale UI state can leave a flag set after
# its input got cleared — most commonly "I" persisting in localStorage
# after the user removed their reference image, causing every subsequent
# text-to-image gen to fail with "You must provide at least one
# Reference Image". The frontend should already be keeping the flag in
# sync with the inputs, but this defense-in-depth strip lets us recover
# from any UI bug that lets the inconsistent state through.
#
# The set is conservative — only flags where (a) we know the required
# input field name with confidence and (b) the wgp.py validation rejects
# the job rather than silently degrading. Adding too many strips here
# could mask other bugs, so we extend on demand.
_VPT_REQUIRED_INPUTS = {
    # flag → (param key in body, friendly label for log line)
    "I": ("image_refs", "image references"),
}


def _normalize_video_prompt_type(body: dict) -> None:
    """Strip video_prompt_type flags whose required input is missing.

    Mutates `body` in place. No-op when video_prompt_type isn't set or
    when all flags have their inputs.
    """
    vpt = body.get("video_prompt_type")
    if not isinstance(vpt, str) or not vpt:
        return

    new_vpt = vpt
    for flag, (input_key, label) in _VPT_REQUIRED_INPUTS.items():
        if flag not in new_vpt:
            continue
        input_val = body.get(input_key)
        # Treat missing, None, empty string, and empty list as absent.
        is_absent = (
            input_val is None
            or (isinstance(input_val, (list, tuple, str)) and len(input_val) == 0)
        )
        if is_absent:
            new_vpt = new_vpt.replace(flag, "")
            print(
                f"[Generate] Stripped '{flag}' from video_prompt_type "
                f"(no {label} attached) — was {vpt!r}, now {new_vpt!r}"
            )

    if new_vpt != vpt:
        body["video_prompt_type"] = new_vpt


# ── image_prompt_type normalization ──────────────────────────────────
# Sibling to video_prompt_type. wgp's image_prompt_type controls whether
# I2V (image-to-video) start/end frames are expected. When "S" is set
# but no image_start is attached, wgp rejects the job with "You must
# provide a Start Image" instead of falling back to T2V — even though
# Maestro's UX promises "no start image → T2V automatically."
#
# Stale UI state is the usual cause: model defaults, sidecar metadata
# from a previous re-roll, or the user clearing the start-image
# preview after the prompt_type was set. Strip the flag when its
# input is absent so the user gets the T2V fallback they expected.
_IPT_REQUIRED_INPUTS = {
    # flag → (param key in body, friendly label for log line)
    "S": ("image_start", "start image"),
    "E": ("image_end", "end image"),
}


def _normalize_image_prompt_type(body: dict) -> None:
    """Strip image_prompt_type flags whose required input is missing.

    Mutates `body` in place. No-op when image_prompt_type isn't set or
    when all flags have their inputs.

    Effect: a body with image_prompt_type='S' but no image_start gets
    its prompt_type rewritten to '' (or stripped of just 'S' if other
    flags survive), turning the job into T2V — matching Maestro's
    documented behavior of auto-falling-back to T2V when no start
    image is provided.
    """
    ipt = body.get("image_prompt_type")
    if not isinstance(ipt, str) or not ipt:
        return

    new_ipt = ipt
    for flag, (input_key, label) in _IPT_REQUIRED_INPUTS.items():
        if flag not in new_ipt:
            continue
        input_val = body.get(input_key)
        is_absent = (
            input_val is None
            or (isinstance(input_val, (list, tuple, str)) and len(input_val) == 0)
        )
        if is_absent:
            new_ipt = new_ipt.replace(flag, "")
            print(
                f"[Generate] Stripped '{flag}' from image_prompt_type "
                f"(no {label} attached) — was {ipt!r}, now {new_ipt!r}. "
                f"Falling back to {'T2V' if not new_ipt else 'I2V with remaining flags'}."
            )

    if new_ipt != ipt:
        body["image_prompt_type"] = new_ipt








def _minimax_h3_turbo_option(model_def: dict) -> dict | None:
    from services.h3_runtime_policy import turbo_option
    return turbo_option(model_def)




import services.civitai as _civitai_service  # noqa: E402
import services.checkpoints as _checkpoints_service  # noqa: E402
import services.civitai_downloads as _civitai_downloads_service  # noqa: E402
import services.hf_import as _hf_import_service  # noqa: E402
from services.civitai import (  # noqa: E402
    CIVITAI_BASE_URL,
    CIVITAI_USER_AGENT,
    _CIVITAI_CACHE,
    _CIVITAI_CACHE_LOCK,
    _build_manifest_entry,
    _civitai_fetch_model,
)
from services.civitai_downloads import (  # noqa: E402
    _civitai_download_lock,
    _civitai_downloads,
    _download_target_reservations,
)


from routers.civitai import create_civitai_filters_router  # noqa: E402

api.include_router(create_civitai_filters_router())


from routers.model_catalog import create_model_reload_router  # noqa: E402

api.include_router(create_model_reload_router())


from routers.checkpoints import create_checkpoints_library_router  # noqa: E402

api.include_router(create_checkpoints_library_router())



from routers.civitai import create_civitai_browser_router  # noqa: E402

api.include_router(create_civitai_browser_router())










from routers.huggingface import create_huggingface_import_router  # noqa: E402

api.include_router(create_huggingface_import_router())






from routers.lora_guides import create_lora_guide_router  # noqa: E402

api.include_router(create_lora_guide_router())


from routers.checkpoints import create_checkpoint_guide_router  # noqa: E402

api.include_router(create_checkpoint_guide_router())


from routers.lora_guides import create_lora_guide_scan_router  # noqa: E402

api.include_router(create_lora_guide_scan_router())



def _recommended_minimax_h3_encoder(model_type: str, model_def: dict) -> str:
    """Resolve H3's default encoder from actual kernel support and RAM."""

    variants = model_def.get("minimax_h3_text_encoder_variants") or {}
    fallback = str(model_def.get("minimax_h3_text_encoder_default") or "nvfp4_awq")
    if not variants:
        return fallback
    try:
        handler = wgp.get_model_handler(wgp.get_base_model_type(model_type))
        selected = handler.recommend_text_encoder(_get_cached_hardware(), model_def)
        if selected in variants:
            return selected
    except Exception as error:
        print(f"[MiniMax H3] Hardware-aware encoder recommendation failed: {error}")
    return fallback if fallback in variants else next(iter(variants))


def _minimax_h3_runtime_advisory(model_def: dict) -> dict | None:
    """Return a non-blocking Full-H3 hardware warning for Studio."""

    if not str((model_def or {}).get("architecture") or "").startswith(
        "minimax_h3"
    ):
        return None
    try:
        from models.minimax_h3.minimax_h3_handler import h3_runtime_preflight

        return h3_runtime_preflight(model_def, _get_cached_hardware())
    except Exception as error:
        print(f"[MiniMax H3] Runtime preflight unavailable: {error}")
        return None


from services.model_options import (  # noqa: E402
    configure as _configure_model_options,
    get_model_options,
)
_configure_model_options(
    engine=wgp,
    is_legacy_h3_model=_is_legacy_h3_model,
    recommended_minimax_h3_encoder=_recommended_minimax_h3_encoder,
    minimax_h3_turbo_option=_minimax_h3_turbo_option,
    minimax_h3_runtime_advisory=_minimax_h3_runtime_advisory,
)

from routers.model_catalog import create_model_options_router  # noqa: E402

api.include_router(create_model_options_router())


from services import settings_store
from routers.settings import create_settings_config_router
api.include_router(create_settings_config_router(
    wgp=wgp,
    _save_server_config=_save_server_config,
    launch_file=__file__,
    APP_VERSION=APP_VERSION,
))
_get_linked_model_folders = settings_store._get_linked_model_folders
lora_library.configure(
    engine=wgp,
    safe_join=_safe_join,
    is_legacy_h3_model=_is_legacy_h3_model,
    minimax_h3_turbo_option=_minimax_h3_turbo_option,
    civitai_fetch_model=_civitai_fetch_model,
    build_manifest_entry=_build_manifest_entry,
    get_linked_model_folders=_get_linked_model_folders,
)
_nsfw_allowed = settings_store._nsfw_allowed



# ============================================================================
# API Routes: Performance Auto-Tune
# ============================================================================
# Two endpoints back the Settings → System Performance "Auto" card:
#   GET  /api/v1/system-detect       — read hardware + recommendation
#   POST /api/v1/system-detect/apply — write the recommendation to config
# Recommendation logic lives in services/perf_recommend.py (pure
# function, easy to unit test); detection lives in
# services/hardware_detect.py (probes torch.cuda + psutil + kernel
# imports). Both are lazy-imported so they don't slow startup or
# break on AMD/CPU systems where torch.cuda probes might warn.

from routers.model_catalog import create_active_downloads_router  # noqa: E402

api.include_router(create_active_downloads_router())


from routers.system import (
    create_system_diagnostics_router,
    create_system_preflight_router,
    create_system_resources_router,
    create_system_runtime_router,
)
api.include_router(create_system_runtime_router(
    wgp=wgp,
    _save_server_config=_save_server_config,
    _jobs=_jobs,
    _gen_lock=_gen_lock,
    _app_dir=_app_dir,
    minimax_h3_service=minimax_h3_service,
    torch=torch,
))


# ============================================================================
# API Routes: Recipes (one-click Studio presets)
# ============================================================================




from routers.recipes import create_recipes_router
api.include_router(create_recipes_router(
    workspace_dir=_workspace_dir,
    nsfw_allowed=_nsfw_allowed,
    get_model_def=get_model_def,
    safe_join=_safe_join,
))


api.include_router(create_system_preflight_router(wgp=wgp))


# ============================================================================
# API Routes: Services config (API keys, LLM settings)
# ============================================================================

from routers.settings import create_settings_services_router
api.include_router(create_settings_services_router(
    wgp=wgp,
    _save_server_config=_save_server_config,
    _effective_llm_routing=_effective_llm_routing,
    _active_production_profile=_active_production_profile,
    _normalize_production_profile=_normalize_production_profile,
    _PRODUCTION_PROFILE_CONFIG_KEY=_PRODUCTION_PROFILE_CONFIG_KEY,
))
get_services_config = create_settings_services_router.get_services_config
_PUBLIC_LLM_PROVIDERS = settings_store._PUBLIC_LLM_PROVIDERS
_DEFAULT_LLM_REPO = settings_store._DEFAULT_LLM_REPO
_llm_default_device = settings_store._llm_default_device
_mask_key = settings_store._mask_key



api.include_router(create_system_diagnostics_router(wgp=wgp))
# The MCP processor tool calls the same handler the HTTP route does.
wangp_capabilities = create_system_diagnostics_router.wangp_capabilities


# ============================================================================
# API Routes: native Hunyuan3D generation
# ============================================================================

def _resolve_model3d_input_path(value: str, workspace: str | None = None) -> str | None:
    """Resolve a UI-provided upload/output path to a local file."""
    from services.model3d_input_path import resolve_model3d_input_path
    return resolve_model3d_input_path(
        value,
        workspace,
        safe_join=_safe_join,
        workspace_dir=_workspace_dir,
        save_path=lambda: wgp.server_config.get("save_path", "outputs"),
    )




class _LaunchCollectionLookup:
    """The collections registry is created later in this module; look it up per request."""

    def get(self, key):
        return globals()["_workspace_collection_registry"].get(key)


def _publish_moved_studio_task(record, adapter):
    """Activity publish stays the launch function, which is defined further down."""
    publisher = globals().get("_publish_generic_legacy_task")
    if callable(publisher):
        publisher(record, adapter)


def _launch_model3d_engine():
    from services import model3d_service
    return model3d_service


from routers.model3d import create_model3d_router
from routers.rig import create_rig_router

api.include_router(create_model3d_router(
    engine=_launch_model3d_engine,
    resolve_input_path=_resolve_model3d_input_path,
    workspace_dir=_workspace_dir,
    get_active_workspace=_get_active_workspace,
    validate_generation=lambda workspace: execution_mode.validate_generation(workspace),
    collection_registry=_LaunchCollectionLookup(),
    publish_task=_publish_moved_studio_task,
))
from routers.model3d import cancel_model3d_job, generate_model3d, model3d_job_status
api.include_router(create_rig_router(
    resolve_input_path=_resolve_model3d_input_path,
    workspace_dir=_workspace_dir,
    get_active_workspace=_get_active_workspace,
    safe_join=_safe_join,
    publish_task=_publish_moved_studio_task,
))
from routers.rig import cancel_rig_job, generate_rig, rig_job_status


# ============================================================================
# API Routes: Workspaces
# ============================================================================

from routers.workspace_outputs import create_workspace_router

api.include_router(create_workspace_router(
    list_workspaces=_list_workspaces,
    get_active_workspace=_get_active_workspace,
    persist_active=_persist_active_workspace,
    workspace_dir=_workspace_dir,
    generation_idle=lambda: not _active_gen_states,
    jobs=lambda: _jobs.values(),
    safe_join=_safe_join,
    save_path=lambda: wgp.server_config.get("save_path", "outputs"),
))


# ============================================================================
# API Routes: Storage (duplicate finder + usage analytics)
# ============================================================================

_STORAGE_WEIGHT_EXTS = (".safetensors", ".sft", ".gguf", ".pth", ".ckpt", ".pt", ".bin", ".onnx")
_STORAGE_MIN_DUP_BYTES = 10 * 1024 * 1024  # skip configs/tokenizers — reclaim noise


def _walk_sized(root: str) -> dict:
    """normcased relpath -> (abs_path, size) for weight files under root."""
    out: dict = {}
    root_abs = os.path.abspath(root)
    for dirpath, _dirnames, filenames in os.walk(root_abs):
        for f in filenames:
            if not f.lower().endswith(_STORAGE_WEIGHT_EXTS):
                continue
            full = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            out[os.path.normcase(os.path.relpath(full, root_abs))] = (full, size)
    return out


def _same_physical_file(a: str, b: str) -> bool:
    """True when two paths reference the same on-disk data: junctions and
    symlinks resolve via realpath; NTFS hardlinks (which realpath does NOT
    resolve) via matching (st_dev, st_ino)."""
    if os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b)):
        return True
    try:
        sa, sb = os.stat(a), os.stat(b)
        return sa.st_ino != 0 and (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)
    except OSError:
        return False


def _files_probably_identical(a: str, b: str, size: int) -> bool:
    """Sampled content comparison (1MB head/middle/tail) — same-size files
    can still be divergent weights (a retrained LoRA at the same rank is
    byte-size-identical), and reading multi-GB files fully is not viable
    per scan."""
    chunk = 1024 * 1024
    offsets = [0]
    if size > chunk * 3:
        offsets += [size // 2, max(0, size - chunk)]
    elif size > chunk:
        offsets.append(max(0, size - chunk))
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            for off in offsets:
                fa.seek(off)
                fb.seek(off)
                if fa.read(chunk) != fb.read(chunk):
                    return False
        return True
    except OSError:
        return False


def _storage_roots() -> dict:
    """Primary + linked roots for both file kinds, resolved once."""
    ckpt_roots = wgp.fl.get_checkpoints_paths()
    # The "." search root is the whole app folder — walking it would sweep
    # the entire repo; only the real primary (index 0) is the reclaim target.
    primary_ckpts = os.path.abspath(ckpt_roots[0]) if ckpt_roots else None
    linked_ckpts = [os.path.abspath(r) for r in ckpt_roots[1:] if wgp.fl.is_external_root(r)]
    lora_primary = _resolve_lora_root()
    return {
        "checkpoint": (primary_ckpts, linked_ckpts),
        "lora": (os.path.abspath(lora_primary) if lora_primary else None, _linked_lora_roots()),
    }


@api.get("/api/v1/storage/duplicates")
def storage_duplicates():
    """Primary-root files that also exist (same relative path AND size) in
    a linked install. Deleting the PRIMARY copy is pure reclaim — the
    files locator keeps resolving the linked copy afterwards. Same-path
    different-size pairs are conflicts, not duplicates: the primary copy
    currently shadows a divergent linked file and deleting it would
    silently change behavior."""
    duplicates = []
    conflicts = []
    shared_via_link = 0
    for kind, (primary_root, linked_roots) in _storage_roots().items():
        if not primary_root or not os.path.isdir(primary_root):
            continue
        primary_files = _walk_sized(primary_root)
        for linked_root in linked_roots:
            if not os.path.isdir(linked_root):
                continue
            linked_files = _walk_sized(linked_root)
            for rel, (ppath, psize) in primary_files.items():
                hit = linked_files.get(rel)
                if not hit:
                    continue
                lpath, lsize = hit
                if psize == lsize:
                    # Same physical data (junction, symlink, or hardlink)
                    # is zero reclaimable bytes — "deleting one copy"
                    # would delete the only copy.
                    if _same_physical_file(ppath, lpath):
                        shared_via_link += 1
                        continue
                # Both roots derive from <install>/app/<ckpts|loras>, so the
                # install name is two levels up from the ROOT (deriving it
                # from the file path mislabels subfoldered loras).
                row = {
                    "kind": kind, "filename": os.path.basename(ppath), "rel_path": rel,
                    "primary_path": ppath, "size_bytes": psize,
                    "linked_path": lpath, "linked_size_bytes": lsize,
                    "linked_install": os.path.basename(os.path.dirname(os.path.dirname(linked_root))),
                }
                if psize == lsize and psize >= _STORAGE_MIN_DUP_BYTES:
                    # Same size is not same content: a retrained LoRA at the
                    # same rank is byte-size-identical. Divergent pairs are
                    # conflicts (the primary is the one actually in use).
                    if _files_probably_identical(ppath, lpath, psize):
                        duplicates.append(row)
                    else:
                        conflicts.append(row)
                elif psize != lsize:
                    conflicts.append(row)
    # One primary file can match several linked installs — count it once,
    # keyed by PHYSICAL identity so a junctioned root can't double-list.
    seen = set()
    unique = []
    for d in duplicates:
        key = os.path.normcase(os.path.realpath(d["primary_path"]))
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return {
        "duplicates": sorted(unique, key=lambda d: -d["size_bytes"]),
        "conflicts": conflicts,
        "shared_via_link": shared_via_link,
        "total_reclaimable_bytes": sum(d["size_bytes"] for d in unique),
    }


@api.post("/api/v1/storage/duplicates/reclaim")
async def storage_reclaim(request: Request):
    """Delete ONE primary-root duplicate. Revalidates from scratch: the
    path must live under a primary root and a same-relpath same-size
    linked copy must exist right now — a stale scan result can't delete
    anything that isn't still redundant."""
    body = await request.json()
    path = body.get("path", "")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found.")
    target = os.path.abspath(path)
    if wgp.fl.is_protected_path(target):
        raise HTTPException(status_code=403, detail="That file is in a linked install (read-only).")
    # All comparisons happen in realpath space: a junctioned primary root
    # (e.g. ckpts linked into another install to share storage) makes
    # abspath and physical location disagree, and a "linked copy" reached
    # through the junction is the SAME file — deleting the primary would
    # delete the only copy.
    target_real = os.path.realpath(target)
    try:
        psize = os.path.getsize(target_real)
    except OSError:
        raise HTTPException(status_code=404, detail="File not found.")
    matched = False
    for kind, (primary_root, linked_roots) in _storage_roots().items():
        if not primary_root:
            continue
        proot_real = os.path.realpath(primary_root)
        if not os.path.normcase(target_real).startswith(os.path.normcase(proot_real + os.sep)):
            continue
        rel_key = os.path.relpath(target_real, proot_real)
        for linked_root in linked_roots:
            candidate = os.path.join(linked_root, rel_key)
            try:
                if not os.path.isfile(candidate) or os.path.getsize(candidate) != psize:
                    continue
                # Same physical data (junction/symlink/hardlink) is not a
                # copy, and same size is not same content — a retrained
                # LoRA at the same rank is byte-size-identical.
                if _same_physical_file(candidate, target_real):
                    continue
                if not _files_probably_identical(target_real, candidate, psize):
                    continue
                matched = candidate
                break
            except OSError:
                continue
        break
    if not matched:
        raise HTTPException(status_code=409, detail="No identical linked copy exists (anymore) — refusing to delete the only copy.")
    from services.win_safe_files import safe_delete
    result = safe_delete(target)
    if not result.get("deleted"):
        raise HTTPException(status_code=423, detail="The file is locked by another process. Try again in a moment.")
    # Audit line names the exact surviving copy — if it ever turns out to
    # be gone afterwards, this line is the forensic anchor.
    print(f"[Storage] Reclaimed duplicate: {target} ({psize} bytes; surviving copy: {matched})")
    if not os.path.isfile(matched):
        print(f"[Storage] CRITICAL: surviving copy vanished immediately after reclaim: {matched}")
    return {"status": "ok", "freed_bytes": psize, "deferred": bool(result.get("deferred")), "surviving_copy": matched}


@api.post("/api/v1/storage/duplicates/remove-linked")
async def storage_remove_linked(request: Request):
    """The inverse of reclaim: keep Maestro's copy, remove the LINKED
    install's duplicate — to the Recycle Bin, never a hard delete.

    Gated on the opt-in services.storage_allow_linked_removal flag:
    deleting from another install is the one sanctioned exception to the
    is_protected_path rule, and only with an identical different-physical
    copy verified in Maestro's primary root at this exact moment."""
    services = wgp.server_config.get("services", {})
    if not services.get("storage_allow_linked_removal", False):
        raise HTTPException(status_code=403, detail="Removing files from linked installs is disabled. Enable it in the Storage Manager first.")
    body = await request.json()
    path = body.get("path", "")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found.")
    target = os.path.abspath(path)
    if not wgp.fl.is_protected_path(target):
        raise HTTPException(status_code=400, detail="That file is not in a linked install — use Reclaim for HocusPocus Lab's own copies.")
    target_real = os.path.realpath(target)
    try:
        psize = os.path.getsize(target_real)
    except OSError:
        raise HTTPException(status_code=404, detail="File not found.")
    surviving = None
    for kind, (primary_root, linked_roots) in _storage_roots().items():
        if not primary_root:
            continue
        for linked_root in linked_roots:
            lroot_real = os.path.realpath(linked_root)
            if not os.path.normcase(target_real).startswith(os.path.normcase(lroot_real + os.sep)):
                continue
            rel_key = os.path.relpath(target_real, lroot_real)
            candidate = os.path.join(primary_root, rel_key)
            try:
                if not os.path.isfile(candidate) or os.path.getsize(candidate) != psize:
                    continue
                if _same_physical_file(candidate, target_real):
                    continue
                if not _files_probably_identical(target_real, candidate, psize):
                    continue
                surviving = os.path.abspath(candidate)
                break
            except OSError:
                continue
        if surviving:
            break
    if not surviving:
        raise HTTPException(status_code=409, detail="HocusPocus Lab does not hold an identical copy of that file — refusing to remove the linked install's only version.")
    from services.win_safe_files import recycle_file
    if not recycle_file(target):
        raise HTTPException(status_code=423, detail="Could not move the file to the Recycle Bin (it may be locked, or too large for the Bin). Nothing was deleted.")
    print(f"[Storage] Removed linked duplicate to Recycle Bin: {target} ({psize} bytes; HocusPocus Lab's copy: {surviving})")
    return {"status": "ok", "freed_bytes": psize, "recycled": True, "surviving_copy": surviving}


from services.storage_usage import configure as _configure_storage_usage
from routers.workspace_outputs import create_storage_usage_router

_configure_storage_usage(
    engine=wgp,
    list_workspaces=_list_workspaces,
    model_weight_groups=_model_weight_groups,
    variant_group_filenames=_variant_group_filenames,
    resolve_lora_root=_resolve_lora_root,
    linked_lora_roots=_linked_lora_roots,
)
api.include_router(create_storage_usage_router())


# ============================================================================
# API Routes: LLM service
# ============================================================================

import routers.llm_director as llm_director
from routers.llm_director import (
    create_character_describe_router,
    create_director_music_router,
)

_ensure_llm_loaded = llm_director._ensure_llm_loaded
_civitai_service.configure(
    engine=wgp,
    list_checkpoint_architectures=_checkpoints_service._list_checkpoint_architectures,
    guess_arch_for_base=_checkpoints_service._guess_arch_for_base,
)
_civitai_downloads_service.configure(
    engine=wgp,
    safe_join=_safe_join,
    ensure_llm_loaded=_ensure_llm_loaded,
)
_hf_import_service.configure(hf_token_path=_hf_token_path)
_checkpoints_service.configure(
    engine=wgp,
    ensure_llm_loaded=_ensure_llm_loaded,
    fetch_hf_readme_context=_hf_import_service._fetch_hf_readme_context,
)
lora_guides.configure(
    engine=wgp,
    ensure_llm_loaded=_ensure_llm_loaded,
    civitai_user_agent=CIVITAI_USER_AGENT,
    civitai_base_url=CIVITAI_BASE_URL,
    get_linked_model_folders=_get_linked_model_folders,
)

from routers.llm import (
    create_llm_router,
    create_llm_prompt_router,
)

api.include_router(create_llm_router(
    get_services_config=lambda: wgp.server_config.get("services", {}),
    effective_llm_routing=_effective_llm_routing,
    llm_provider_credentials=_llm_provider_credentials,
    llm_default_device=_llm_default_device,
    default_llm_repo=_DEFAULT_LLM_REPO,
    ensure_llm_loaded=_ensure_llm_loaded,
    comic_writing_llm=lambda body: _comic_writing_llm(body),
    resolve_visual_media=lambda value, workspace: _resolve_wangp_visual_media(value, workspace),
))


_resolve_wangp_visual_media = llm_director._resolve_wangp_visual_media

api.include_router(create_director_music_router(
    wgp=wgp,
    _get_active_workspace=_get_active_workspace,
    _workspace_dir=_workspace_dir,
    _init_pipeline=_init_pipeline,
    _effective_llm_routing=_effective_llm_routing,
    _llm_default_device=_llm_default_device,
    _DEFAULT_LLM_REPO=_DEFAULT_LLM_REPO,
))

_enhance_with_wangp = llm_director._enhance_with_wangp

# Prompt tools sit after Director generate-music so ordinals 88-91 stay put.
api.include_router(create_llm_prompt_router(
    get_services_config=lambda: wgp.server_config.get("services", {}),
    effective_llm_routing=_effective_llm_routing,
    public_llm_providers=_PUBLIC_LLM_PROVIDERS,
    ensure_llm_loaded=_ensure_llm_loaded,
    get_model_def=get_model_def,
    get_lora_dir=wgp.get_lora_dir,
    get_cached_hardware=lambda: _get_cached_hardware(),
    get_enhancer_enabled=lambda: int(wgp.server_config.get("enhancer_enabled", 0) or 0),
    enhance_with_wangp=_enhance_with_wangp,
))


api.include_router(create_character_describe_router(
    _resolve_model3d_input_path=_resolve_model3d_input_path,
))


# ============================================================================
# API Routes: Audio Analysis
# ============================================================================

from routers.audio import (
    cancel_audio_analysis_job,
    create_audio_plan_router,
    create_audio_router,
)

api.include_router(create_audio_router(
    _jobs=_jobs,
    _stream_upload=_stream_upload,
    _transcode_upload=_transcode_upload,
    _get_active_workspace=_get_active_workspace,
    _resolve_request_media_path=_resolve_request_media_path,
    _safe_join=_safe_join,
    _workspace_dir=_workspace_dir,
    wgp=wgp,
))


# ============================================================================
# API Routes: Director (Shot Planner)
# ============================================================================

from routers.director_pipeline_reads import (
    create_director_dashboard_reads_router,
    create_director_pipeline_status_router,
    create_director_plan_reads_router,
)
api.include_router(create_director_plan_reads_router(ensure_llm_loaded=_ensure_llm_loaded))


# plan-structure stays after the Director plan reads so those routes keep their order.
api.include_router(create_audio_plan_router(wgp=wgp))


api.include_router(create_director_planner_router())


api.include_router(create_director_pipeline_status_router(
    outputs_dir=lambda: wgp.server_config.get("save_path", "outputs"),
))


api.include_router(create_director_pipeline_run_router())


# ── Director Pipeline Dashboard ───────────────────────────────────────────

from routers.director_review import create_director_review_router
api.include_router(create_director_review_router(_workspace_dir))
api.include_router(create_director_dashboard_reads_router(
    outputs_dir=lambda: wgp.server_config.get("save_path", "outputs"),
    active_workspace=_get_active_workspace,
))


api.include_router(create_director_pipeline_edit_router())


from services.director_v2_plan import bind_director_v2_plan
from routers.director_v2 import create_director_v2_router

bind_director_v2_plan(
    get_active_workspace=_get_active_workspace,
    workspace_dir=_workspace_dir,
    ensure_llm_loaded=_ensure_llm_loaded,
    wgp_module=wgp,
    effective_llm_routing=_effective_llm_routing,
    is_minimax_h3_model=_is_minimax_h3_model,
    public_llm_providers=_PUBLIC_LLM_PROVIDERS,
)
api.include_router(create_director_v2_router())



def _run_generation_with_preparation(job_id: str) -> bool:
    """Finish deferred, non-GPU preparation before entering generation FIFO.

    H3 window planning may load an LLM or call a remote provider.  It must not
    block ``POST /generate`` and it must not reserve the scarce video lane
    while doing so.  The pending request is persisted inside the job params so
    crash recovery can replay this same worker before starting inference.
    """
    job = _jobs.get(job_id)
    if not isinstance(job, dict):
        return False
    try:
        native_worker = _image_generation_commands.native_worker(job)
    except HTTPException as error:
        finish_job(job, "failed", error=str(error.detail), message="Command recovery could not be verified")
        return False
    if native_worker is not None:
        return bool(native_worker(job_id))
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    pending = params.get("_h3_window_plan_pending")
    if not isinstance(pending, dict):
        return bool(_run_generation(job_id))
    if is_cancel_requested(job):
        _remove_persisted_generation_job(job)
        return False
    if not try_start(
        job,
        phase="planning",
        message="Planning H3 window-by-window prompts with the writing model…",
        acquired_resources=[],
    ):
        if is_cancel_requested(job):
            _remove_persisted_generation_job(job)
        return False

    _persist_generation_job(job)
    planner_llm = None
    try:
        from services import llm_service as planner_llm
        from services.h3_window_planner import plan_h3_sliding_windows

        def _plan_windows():
            try:
                _ensure_llm_loaded()
            except Exception as load_error:
                # The planner has a deterministic fallback, so a missing
                # optional LLM must not make an otherwise valid H3 job fail.
                print(
                    "[MiniMax H3] Planner LLM unavailable; using fallback: "
                    f"{load_error}"
                )
            services = wgp.server_config.get("services", {})
            provider = _effective_llm_routing(services)[0]
            nsfw = (
                services.get("nsfw_mode", False)
                and provider not in _PUBLIC_LLM_PROVIDERS
            )
            expected_count = int(pending.get("expected_count") or 0)
            if expected_count <= 0:
                raise RuntimeError("H3 window plan has no target windows")
            print(
                f"[MiniMax H3] Planning {expected_count} window-local prompts "
                "after VRAM-safe geometry "
                f"({int(pending.get('window_frames') or 0)} frames/window)."
            )
            result = plan_h3_sliding_windows(
                str(params.get("prompt") or ""),
                model_type=str(pending.get("model_type") or ""),
                resolution=str(pending.get("resolution") or ""),
                total_frames=int(pending.get("total_frames") or 0),
                window_frames=int(pending.get("window_frames") or 0),
                overlap_frames=int(pending.get("overlap_frames") or 0),
                discard_frames=int(pending.get("discard_frames") or 0),
                fps=float(pending.get("fps") or 24),
                has_start_image=bool(pending.get("has_start_image")),
                has_end_image=bool(pending.get("has_end_image")),
                image_paths=list(pending.get("image_paths") or []) or None,
                nsfw=bool(nsfw),
                planning_style=str(pending.get("planning_style") or "faithful"),
                h3_audio_policy=str(pending.get("h3_audio_policy") or "native"),
                reference_context=str(pending.get("reference_context") or ""),
            )
            prompts = result.get("window_prompts") if isinstance(result, dict) else None
            if (
                not isinstance(prompts, list)
                or len(prompts) != expected_count
                or not all(isinstance(item, str) and item.strip() for item in prompts)
            ):
                raise RuntimeError(
                    "H3 window planner returned an incomplete prompt plan "
                    f"({len(prompts) if isinstance(prompts, list) else 0}/"
                    f"{expected_count})"
                )
            return result, list(prompts)

        # Correlate any child LLM call with the visible generation root.  The
        # fallback keeps model-free tests and older embedded callers working.
        try:
            from services.task_manager import task_context_scope
        except Exception:
            planned, window_prompts = _plan_windows()
        else:
            with task_context_scope(
                task_id=job.get("task_id"),
                root_id=job.get("root_task_id") or job.get("task_id"),
                workspace=job.get("workspace") or "default",
                workspace_dir=job.get("out_dir")
                or _workspace_dir(job.get("workspace") or "default"),
            ):
                planned, window_prompts = _plan_windows()

        if is_cancel_requested(job):
            _remove_persisted_generation_job(job)
            return False
        prepared_params = copy.deepcopy(params)
        prepared_params.pop("_h3_window_plan_pending", None)
        prepared_params["minimax_h3_window_storyboard"] = True
        prepared_params["h3_window_prompts"] = window_prompts
        prepared_params["h3_window_plan_signature"] = str(
            pending.get("signature") or ""
        )
        prepared_params["h3_window_plan"] = planned
        if not update_job(
            job,
            params=prepared_params,
            phase="planning",
            message=(
                f"H3 prompt plan ready ({len(window_prompts)} windows); "
                "queuing video generation…"
            ),
        ):
            _remove_persisted_generation_job(job)
            return False
        _persist_generation_job(job)
        if not try_requeue(
            job,
            phase="waiting_resource",
            message="H3 prompt plan ready · waiting for the local video GPU…",
            started_at=None,
        ):
            _remove_persisted_generation_job(job)
            return False
        _persist_generation_job(job)
        return bool(_run_generation(job_id))
    except Exception as error:
        traceback.print_exc()
        if not is_cancel_requested(job):
            finish_job(
                job,
                "failed",
                error=str(error),
                message=f"H3 window planning failed: {error}",
                phase="planning",
            )
        _remove_persisted_generation_job(job)
        return False
    finally:
        # A local writing model cannot remain beside H3's 20B/33B runtime.
        if planner_llm is not None:
            try:
                if (
                    planner_llm.is_loaded()
                    and planner_llm.get_status().get("provider") == "local"
                ):
                    planner_llm.unload_model()
            except Exception as unload_error:
                print(f"[MiniMax H3] Planner LLM unload skipped: {unload_error}")
        # Deferred planning has no abort-state registration. Confirm terminal
        # cancellation only after the planner call and its model cleanup have
        # both returned.
        acknowledge_cancel(job)


from routers.studio_generate import create_studio_generate_router


def _forward_studio_cached_hardware():
    """Hardware detection is defined further down in this module."""
    return _get_cached_hardware()


api.include_router(create_studio_generate_router(
    jobs=_jobs,
    new_generation_job=_new_generation_job,
    persist_generation_job=_persist_generation_job,
    get_active_workspace=_get_active_workspace,
    workspace_dir=_workspace_dir,
    cancel_h3_idle_release=_cancel_h3_idle_release,
    is_character_sheet_engine=_is_character_sheet_engine,
    is_legacy_h3_model=_is_legacy_h3_model,
    is_minimax_h3_model=_is_minimax_h3_model,
    normalize_image_prompt_type=_normalize_image_prompt_type,
    normalize_video_prompt_type=_normalize_video_prompt_type,
    recommended_minimax_h3_encoder=_recommended_minimax_h3_encoder,
    # Defined just above. Its body looks up _run_generation when the thread runs.
    # Passing the function keeps the worker thread's name.
    run_generation_with_preparation=_run_generation_with_preparation,
    get_cached_hardware=_forward_studio_cached_hardware,
    collection_registry=_LaunchCollectionLookup(),
    ensure_generation_priority=ensure_generation_priority,
    execution_mode=execution_mode,
    minimax_h3_service=minimax_h3_service,
    wgp=wgp,
))
from services.studio_generate import generate


from routers.studio_edit_requests import create_studio_retake_router


def _forward_studio_run_generation(*args, **kwargs):
    """The generation worker is defined further down. Call it when the thread runs."""
    return _run_generation(*args, **kwargs)


# The route starts this as a thread. Python names the thread from __name__.
_forward_studio_run_generation.__name__ = "_run_generation"

api.include_router(create_studio_retake_router(
    register_manual_generation_job=_register_manual_generation_job,
    generation_job_acceptance=_generation_job_acceptance,
    get_active_workspace=_get_active_workspace,
    workspace_dir=_workspace_dir,
    run_generation=_forward_studio_run_generation,
    resolve_wangp_visual_media=_resolve_wangp_visual_media,
))
from services.studio_edit_requests import extract_frames_endpoint, retake_video_endpoint


# ── Edit Anything LoRA identifier ──────────────────────────────────────
# Hosted at https://huggingface.co/Alissonerdx/LTX-LoRAs
# Trained on 8k video pairs for Add / Remove / Replace / Style edits.
# Uses the prompt itself as the edit instruction — no spatial mask required.
# We pick the 9000-step Adam variant as the default because the card
# describes it as the more-trained checkpoint.
EDIT_ANYTHING_LORA_HF_URL = "https://huggingface.co/Alissonerdx/LTX-LoRAs"
EDIT_ANYTHING_LORA_FILENAME = "ltx23_edit_anything_global_rank128_v1_9000steps_adamw.safetensors"

from services.recast_reference_prepare import (
    _RECAST_RELIGHTING_LORA_FILENAME,
    _RECAST_RELIGHTING_LORA_REVISION,
    _RECAST_RELIGHTING_LORA_REMOTE_PATH,
    _RECAST_RELIGHTING_LORA_SHA256,
    _RECAST_RELIGHTING_LORA_SIZE,
    _normalize_recast_lora_settings,
    _resolve_recast_media,
    _RECAST_FAST_MODEL_TYPE,
    _RECAST_LEGACY_FAST_MODEL_TYPE,
    _RECAST_WARMUP_FRAMES,
    _normalize_recast_person_count,
    _normalize_recast_resolution_profile,
    _recast_window_size_for_profile,
    _build_recast_prompt,
    _recast_video_has_audio,
    _recast_resolution_for_source,
    _prepare_recast_reference_conditioning,
    _load_recast_reference_pair,
    _save_recast_reference_pair,
    _recast_video_frame_count,
)

# ── Managed auto-download LoRAs ──────────────────────────────────────────
# LoRAs that Maestro fetches on first use so a fresh install doesn't error
# out with "file not found" when the user triggers a feature that requires
# one (these are multi-hundred-MB files we don't ship in the repo). The
# frontend pre-downloads them when the relevant panel mounts; this registry
# powers the server-side safety net in _run_generation so the job waits for
# the download instead of failing if the user hits Generate first.
#
# Maps the final on-disk .safetensors filename to its HuggingFace source.
# Most entries download that same filename; converted sources can declare an
# immutable revision, remote path, expected hash/size, and converter. `label`
# is what the job status shows while the one-time setup runs.
_MANAGED_LORAS = {
    EDIT_ANYTHING_LORA_FILENAME: {
        "repo_id": "Alissonerdx/LTX-LoRAs",
        "label": "Edit Anything",
        "support_url": EDIT_ANYTHING_LORA_HF_URL,
    },
    _RECAST_RELIGHTING_LORA_FILENAME: {
        "repo_id": "zai-org/SCAIL-2",
        "revision": _RECAST_RELIGHTING_LORA_REVISION,
        "remote_path": _RECAST_RELIGHTING_LORA_REMOTE_PATH,
        "sha256": _RECAST_RELIGHTING_LORA_SHA256,
        "size": _RECAST_RELIGHTING_LORA_SIZE,
        "converter": "scail2_sat_lora",
        "label": "SCAIL-2 Relighting",
        "support_url": "https://huggingface.co/zai-org/SCAIL-2/blob/main/model/relighting-lora.pt",
    },
    MINIMAX_H3_TURBO_LORA_FILENAME: {
        "repo_id": MINIMAX_H3_TURBO_LORA_REPO_ID,
        "revision": MINIMAX_H3_TURBO_LORA_REVISION,
        "remote_path": MINIMAX_H3_TURBO_LORA_FILENAME,
        "sha256": MINIMAX_H3_TURBO_LORA_SHA256,
        "size": MINIMAX_H3_TURBO_LORA_SIZE,
        "label": "MiniMax H3 Turbo (Experimental)",
        "support_url": (
            "https://huggingface.co/"
            f"{MINIMAX_H3_TURBO_LORA_REPO_ID}"
        ),
    },
}


from services.h3_runtime_policy import managed_turbo_downloads
_MANAGED_LORAS.update(managed_turbo_downloads())

def _ensure_managed_loras_present(activated_loras, model_type, progress=None):
    """Download any managed auto-download LoRA in `activated_loras` that is
    missing from disk, blocking until each finishes.

    The file is written into the exact directory wgp loads LoRAs from for
    this model (`wgp.get_lora_dir`), so the pipeline finds it immediately
    after we return. Downloads to a .part file and atomically renames on
    success so a crashed/partial download can't masquerade as a valid LoRA.

    `progress(msg)` — optional callback used to surface a status string
    while a download is in flight (we point it at the job's `message` so the
    polling UI shows "Downloading … model").

    Returns the list of filenames downloaded this call (empty if everything
    was already present). Raises RuntimeError on download failure.
    """
    if not activated_loras:
        return []

    try:
        target_dir = wgp.get_lora_dir(model_type)
    except Exception:
        # Fall back to the configured loras_root if the model dir can't be
        # resolved (shouldn't happen for the ltx2 models these LoRAs target).
        lora_root = wgp.server_config.get("loras_root", "loras") if hasattr(wgp, "server_config") else "loras"
        if not os.path.isabs(lora_root):
            lora_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), lora_root)
        target_dir = os.path.join(lora_root, "ltx2")

    def _find_download_record(name):
        """Snapshot of the active-downloads entry for `name`, preferring an
        in-flight ("downloading") record over a finished one. Used to detect
        the frontend's proactive fetch so we wait on it instead of racing."""
        with _civitai_download_lock:
            match = None
            for rec in _civitai_downloads.values():
                if os.path.basename(str(rec.get("filename", ""))) == name:
                    if rec.get("status") == "downloading":
                        return dict(rec)
                    match = dict(rec)
            return match

    downloaded = []
    for fname in activated_loras:
        base = os.path.basename(str(fname))
        spec = _MANAGED_LORAS.get(base)
        if not spec:
            continue
        save_path = os.path.join(target_dir, base)
        label = spec.get("label", base)

        # A linked installation's verified converted file is a valid runtime
        # source too; don't reclaim another 1.2 GB in the primary install.
        try:
            resolved_path = wgp.resolve_lora_path(model_type, base)
        except Exception:
            resolved_path = save_path
        if os.path.isfile(resolved_path):
            continue

        # If another part of the app is already fetching this exact file (the
        # frontend pre-downloads it when the panel mounts), wait for that to
        # finish rather than starting a second concurrent download — on
        # Windows a parallel write / atomic rename onto the open file would
        # fail or corrupt it.
        rec = _find_download_record(base)
        if rec is not None and rec.get("status") == "downloading":
            print(f"[ManagedLoRA] {label} already downloading elsewhere — waiting for it")
            waited = 0.0
            while waited < 600:
                rec = _find_download_record(base)
                if rec is None or rec.get("status") != "downloading":
                    break
                if progress:
                    pct = int(rec.get("progress") or 0)
                    progress(f"Downloading {label} model (one-time setup)… {pct}%")
                time.sleep(2)
                waited += 2
            # A legacy or externally-created failed record may still point at
            # an in-place partial. Drop it so the presence check below can
            # re-fetch a clean copy.
            if rec is not None and rec.get("status") == "failed":
                try:
                    if os.path.isfile(save_path):
                        os.remove(save_path)
                except Exception:
                    pass

        if os.path.isfile(save_path):
            continue

        os.makedirs(target_dir, exist_ok=True)
        remote_path = spec.get("remote_path", base)
        revision = spec.get("revision", "main")
        url = f"https://huggingface.co/{spec['repo_id']}/resolve/{revision}/{remote_path}"
        # Unique temp + atomic rename: a partial/failed download can never be
        # mistaken for a valid LoRA, and we don't clobber another writer.
        tmp_path = save_path + f".{uuid.uuid4().hex[:8]}.part"
        source_tmp_path = (
            save_path + f".{uuid.uuid4().hex[:8]}.source.part"
            if spec.get("converter") else tmp_path
        )
        print(f"[ManagedLoRA] {label} not found — downloading {url} -> {save_path}")
        if progress:
            progress(f"Downloading {label} model (one-time setup)…")
        try:
            import hashlib

            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            done = 0
            last_pct = -1
            digest = hashlib.sha256()
            with open(source_tmp_path, "wb") as out:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress and total > 0:
                        pct = int(done * 100 / total)
                        if pct >= last_pct + 5:
                            last_pct = pct
                            progress(f"Downloading {label} model (one-time setup)… {pct}%")

            expected_size = spec.get("size")
            if expected_size is not None and done != int(expected_size):
                raise RuntimeError(
                    f"download size mismatch (expected {int(expected_size)} bytes, got {done})"
                )
            expected_sha256 = spec.get("sha256")
            actual_sha256 = digest.hexdigest()
            if expected_sha256 and actual_sha256.lower() != str(expected_sha256).lower():
                raise RuntimeError("download SHA-256 mismatch; the checkpoint was not published")

            if spec.get("converter") == "scail2_sat_lora":
                if progress:
                    progress(f"Converting {label} model (one-time setup)…")
                print(f"[ManagedLoRA] Converting official SAT LoRA -> {tmp_path}")
                from services.scail2_lora import convert_scail2_sat_lora
                tensor_count = convert_scail2_sat_lora(
                    source_tmp_path,
                    tmp_path,
                    expected_sha256=str(expected_sha256),
                )
                print(f"[ManagedLoRA] Converted {tensor_count} SCAIL-2 Relighting tensors")
                os.remove(source_tmp_path)
            elif source_tmp_path != tmp_path:
                os.replace(source_tmp_path, tmp_path)
            os.replace(tmp_path, save_path)
            downloaded.append(base)
            print(f"[ManagedLoRA] {label} downloaded -> {save_path}")
        except Exception as e:
            for partial_path in {tmp_path, source_tmp_path}:
                try:
                    if os.path.isfile(partial_path):
                        os.remove(partial_path)
                except Exception:
                    pass
            support_url = spec.get("support_url", f"https://huggingface.co/{spec['repo_id']}")
            if spec.get("converter"):
                recovery_hint = (
                    f"Retry the automatic setup, or download the official source from "
                    f"{support_url} and convert it with SCAIL-2's convert_lora.py."
                )
            else:
                recovery_hint = f"Try again, or import it manually from {support_url}."
            raise RuntimeError(
                f"Could not download the {label} model automatically: {e}. "
                f"Check your internet connection. {recovery_hint}"
            ) from e

    return downloaded


from routers.studio_edit_requests import create_studio_edit_anything_router

api.include_router(create_studio_edit_anything_router(
    register_manual_generation_job=_register_manual_generation_job,
    generation_job_acceptance=_generation_job_acceptance,
    get_active_workspace=_get_active_workspace,
    workspace_dir=_workspace_dir,
    # Defined above the retake routes. Python names the worker thread from this.
    run_generation=_forward_studio_run_generation,
    edit_anything_lora_filename=EDIT_ANYTHING_LORA_FILENAME,
))
from services.studio_edit_requests import edit_anything_endpoint

from services.recast_masks import (
    _RECAST_MASK_COLORS,
    _RECAST_PROTECTION_COLORS,
    _render_recast_mask_locked_video,
    _build_recast_adaptive_mask,
    _count_recast_mask_people,
    _normalize_recast_character_mappings,
    _compose_recast_character_masks,
    _recast_mask_region,
    _build_recast_character_mask,
    _recolor_recast_reference_mask,
    bind as _bind_recast_masks,
)
from services.recast_matte import bind as _bind_recast_matte
from services.recast_reference_prepare import bind as _bind_recast_reference_prepare

from services.recast_reference_compose import (
    _build_recast_source_scene_reference,
    _enable_recast_dynamic_source_scene_reference,
    _compose_recast_group_reference_frame,
    _compose_recast_cast_reference_frame,
    _build_recast_target_group_reference,
    _compose_recast_native_people_masks,
    _build_recast_native_people_conditioning,
    _recast_appearance_descriptor,
    _build_recast_mapping_appearance_prototypes,
)


# The Recast character mask calls these shot helpers, which are defined below.
# Each forwarder looks the launch name up when the mask builder calls it.
def _forward_recast_detect_shot_ranges(*args, **kwargs):
    return _detect_recast_shot_ranges(*args, **kwargs)


def _forward_recast_find_unmapped_shots(*args, **kwargs):
    return _find_recast_unmapped_shots(*args, **kwargs)


def _forward_recast_normalize_tracking_target(*args, **kwargs):
    return _normalize_recast_tracking_target(*args, **kwargs)


def _forward_recast_recover_unmapped_shots(*args, **kwargs):
    return _recover_recast_unmapped_shots(*args, **kwargs)


def _forward_recast_select_timeline_anchor(*args, **kwargs):
    return _select_recast_timeline_anchor(*args, **kwargs)


def _forward_recast_summarize_mapping_mask(*args, **kwargs):
    return _summarize_recast_mapping_mask(*args, **kwargs)


# Recast masks, mattes and reference preparation each receive the launch
# objects they read once, here.
_bind_recast_masks(
    detect_recast_shot_ranges=_forward_recast_detect_shot_ranges,
    find_recast_unmapped_shots=_forward_recast_find_unmapped_shots,
    normalize_recast_tracking_target=_forward_recast_normalize_tracking_target,
    recover_recast_unmapped_shots=_forward_recast_recover_unmapped_shots,
    select_recast_timeline_anchor=_forward_recast_select_timeline_anchor,
    summarize_recast_mapping_mask=_forward_recast_summarize_mapping_mask,
)
_bind_recast_matte(app_dir=_app_dir)
_bind_recast_reference_prepare(workspace_dir=_workspace_dir)


def _normalize_scail2_inference_steps(value, default):
    """Clamp dedicated SCAIL-2 edit jobs to the UI's supported step range."""
    try:
        steps = int(float(value))
    except (TypeError, ValueError, OverflowError):
        steps = int(default)
    return min(50, max(1, steps))


def _normalize_scail2_guidance_scale(value, default=5.0):
    """Return a finite SCAIL-2 HQ guidance value accepted by the UI."""
    import math

    try:
        guidance = float(value)
    except (TypeError, ValueError, OverflowError):
        guidance = float(default)
    if not math.isfinite(guidance):
        guidance = float(default)
    return min(20.0, max(0.0, guidance))

def _extract_output_seed(filename):
    """Return the resolved seed embedded in a generated media filename."""
    import os
    import re

    match = re.search(r"(?:^|_)seed(\d+)(?:_|$)", os.path.splitext(filename)[0])
    return int(match.group(1)) if match else None

def _recast_probe_needs_bystander_tracking(
    probe_frame, target_probe_mask, selected_count,
):
    """Cheaply decide whether Recast needs a second full SAM3 tracking pass.

    Native group preservation can only use people visible in the first frame,
    so a one-frame broad ``person`` segmentation is sufficient to determine
    whether any usable bystander exists. If the probe is ambiguous, return
    True and retain the conservative full-pass behavior.
    """
    import numpy as np
    from shared import magic_mask

    frame = np.asarray(probe_frame, dtype=np.uint8)
    target = np.asarray(target_probe_mask, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[-1] != 3 or target.shape != frame.shape:
        return True
    try:
        people = magic_mask.generate_keyword_masks(
            frame[None],
            "person",
            no_hole=True,
            colorize_objects=True,
            color_palette=_RECAST_PROTECTION_COLORS,
            max_colored_objects=len(_RECAST_PROTECTION_COLORS),
        )
        _, _, conditioning_count, _ = _compose_recast_native_people_masks(
            target[None],
            people,
            selected_count,
        )
    except Exception:
        return True
    return conditioning_count > _normalize_recast_person_count(selected_count)


def _detect_recast_shot_ranges(
    source_frames, min_shot_frames=4, absolute_cut_threshold=0.12,
):
    """Return half-open camera-shot ranges for timeline-aware SAM3 tracking.

    A hard cut needs a fresh text anchor: carrying a segmentation track
    through the cut can attach one character card to whichever person happens
    to occupy the same screen position in the next shot. The detector combines
    low-resolution pixel change with color-histogram change and uses the
    video's own motion baseline, so ordinary camera motion is not treated as a
    cut. The absolute floor remains deliberately below typical same-location
    shot/reverse-shot edits: their shared lighting and background can keep the
    combined score below 0.30 even though the subject changes completely.
    """
    import cv2
    import numpy as np

    frames = np.asarray(source_frames, dtype=np.uint8)
    if frames.ndim != 4 or frames.shape[-1] != 3:
        raise ValueError(
            "Recast shot detection needs T/H/W/RGB source frames."
        )
    frame_count = int(len(frames))
    if frame_count <= 1:
        return [(0, frame_count)] if frame_count else []

    thumbnails = []
    histograms = []
    for frame in frames:
        thumbnail = cv2.resize(
            frame,
            (64, 36),
            interpolation=cv2.INTER_AREA,
        )
        thumbnails.append(thumbnail.astype(np.float32) / 255.0)
        histogram = cv2.calcHist(
            [thumbnail],
            [0, 1],
            None,
            [16, 16],
            [0, 256, 0, 256],
        )
        cv2.normalize(histogram, histogram)
        histograms.append(histogram)

    scores = []
    for index in range(1, frame_count):
        pixel_change = float(
            np.mean(np.abs(thumbnails[index] - thumbnails[index - 1]))
        )
        histogram_change = float(
            cv2.compareHist(
                histograms[index - 1],
                histograms[index],
                cv2.HISTCMP_BHATTACHARYYA,
            )
        )
        scores.append(0.60 * pixel_change + 0.40 * histogram_change)
    score_array = np.asarray(scores, dtype=np.float32)
    median = float(np.median(score_array))
    mad = float(np.median(np.abs(score_array - median)))
    adaptive_threshold = median + max(0.10, 6.0 * mad)
    threshold = max(float(absolute_cut_threshold), adaptive_threshold)

    minimum = max(2, int(min_shot_frames))
    boundaries = [0]
    for frame_index, score in enumerate(scores, start=1):
        if score < threshold:
            continue
        previous = scores[frame_index - 2] if frame_index > 1 else -1.0
        following = (
            scores[frame_index]
            if frame_index < len(scores)
            else -1.0
        )
        if score < previous or score < following:
            continue
        if frame_index - boundaries[-1] < minimum:
            continue
        if frame_count - frame_index < minimum:
            continue
        boundaries.append(frame_index)
    boundaries.append(frame_count)
    return [
        (start, end)
        for start, end in zip(boundaries, boundaries[1:])
        if end > start
    ]


def _summarize_recast_mapping_mask(mask, fps=25.0):
    """Describe where one independently tracked mapping appears."""
    import numpy as np

    array = np.asarray(mask)
    if array.ndim == 4 and array.shape[-1] == 3:
        region = np.any(array > 30, axis=-1)
    elif array.ndim == 3:
        region = array.astype(bool)
    else:
        raise ValueError(
            f"Unsupported Recast mapping-mask shape: {array.shape}."
        )
    areas = region.reshape(len(region), -1).sum(axis=1)
    present_indices = np.flatnonzero(areas > 0)
    if not len(present_indices):
        return None

    appearance_ranges = []
    range_start = int(present_indices[0])
    previous = range_start
    for raw_index in present_indices[1:]:
        frame_index = int(raw_index)
        if frame_index > previous + 1:
            appearance_ranges.append([range_start, previous + 1])
            range_start = frame_index
        previous = frame_index
    appearance_ranges.append([range_start, previous + 1])

    anchor_index = int(np.argmax(areas))
    safe_fps = float(fps or 25.0)
    return {
        "first_frame_index": int(present_indices[0]),
        "last_frame_index": int(present_indices[-1]),
        "anchor_frame_index": anchor_index,
        "first_time_seconds": float(present_indices[0]) / safe_fps,
        "anchor_time_seconds": float(anchor_index) / safe_fps,
        "appearance_ranges": appearance_ranges,
        "anchor_area": int(areas[anchor_index]),
        "present_frame_count": int(len(present_indices)),
    }


def _select_recast_timeline_anchor(mapping_masks):
    """Choose a useful shared scene frame and report true co-occurrence."""
    import numpy as np

    if not mapping_masks:
        return None, None
    regions = []
    areas = []
    for raw_mask in mapping_masks:
        mask = np.asarray(raw_mask)
        region = (
            np.any(mask > 30, axis=-1)
            if mask.ndim == 4 and mask.shape[-1] == 3
            else mask.astype(bool)
        )
        regions.append(region)
        areas.append(region.reshape(len(region), -1).sum(axis=1))
    frame_count = len(regions[0])
    if any(len(region) != frame_count for region in regions):
        raise ValueError("Recast mapping timelines have different lengths.")

    present = np.stack([area > 0 for area in areas], axis=0)
    common_indices = np.flatnonzero(np.all(present, axis=0))
    if len(common_indices):
        common_scores = np.stack(areas, axis=0)[:, common_indices].sum(axis=0)
        common_index = int(common_indices[int(np.argmax(common_scores))])
    else:
        common_index = None

    visible_counts = present.sum(axis=0)
    total_areas = np.stack(areas, axis=0).sum(axis=0)
    scene_index = int(np.lexsort((total_areas, visible_counts))[-1])
    return common_index, scene_index


def _normalize_recast_tracking_target(target):
    """Use wording SAM3 grounds reliably without changing user metadata."""
    import re

    text = " ".join(str(target or "").split())
    # SAM3 consistently grounds "person in red/black/..." more reliably than
    # the equivalent "person wearing ..." phrasing in camera-shot close-ups.
    return re.sub(r"\bwearing\b", "in", text, flags=re.IGNORECASE)


def _find_recast_unmapped_shots(
    mapping_masks, shot_ranges, min_area_ratio=0.0001,
):
    """Return camera shots where no mapped character was grounded."""
    import numpy as np

    regions = [_recast_mask_region(mask) for mask in mapping_masks or []]
    if not regions:
        return []
    frame_count = int(len(regions[0]))
    frame_area = int(regions[0].shape[-2] * regions[0].shape[-1])
    minimum_pixels = max(
        16,
        int(round(frame_area * max(0.0, float(min_area_ratio)))),
    )
    unresolved = []
    for shot_index, (raw_start, raw_end) in enumerate(shot_ranges or []):
        start = max(0, min(frame_count, int(raw_start)))
        end = max(start, min(frame_count, int(raw_end)))
        if end <= start:
            continue
        largest = max(
            (
                int(
                    region[start:end]
                    .reshape(end - start, -1)
                    .sum(axis=1)
                    .max()
                )
                for region in regions
            ),
            default=0,
        )
        if largest < minimum_pixels:
            unresolved.append({
                "shot_index": shot_index,
                "start_frame": start,
                "end_frame": end,
            })
    return unresolved


def _recover_recast_unmapped_shots(
    source_frames, mapping_masks, shot_ranges, unresolved_shots,
    compact_people_mask, compact_ranges, *,
    minimum_similarity=0.72, minimum_margin=0.06,
):
    """Assign generic SAM people in blank shots by source appearance.

    Text grounding remains authoritative. This fallback is used only when an
    entire camera shot has no mapped target, and only accepts a generic person
    when their clothing/color descriptor clearly favors one established
    mapping prototype.
    """
    import numpy as np

    frames = np.asarray(source_frames, dtype=np.uint8)
    people = np.asarray(compact_people_mask, dtype=np.uint8)
    # These masks are private products of the current tracking job. Mutate
    # them in place instead of duplicating several full-resolution video
    # tensors (which can consume multiple gigabytes on a 20-second clip).
    output_masks = [
        np.asarray(mask, dtype=np.uint8)
        for mask in mapping_masks
    ]
    prototypes = _build_recast_mapping_appearance_prototypes(
        frames,
        output_masks,
        shot_ranges,
    )
    recovered = []

    for shot, compact_bounds in zip(
        unresolved_shots,
        compact_ranges,
    ):
        compact_start, compact_end = (
            int(compact_bounds[0]),
            int(compact_bounds[1]),
        )
        source_start, source_end = (
            int(shot["start_frame"]),
            int(shot["end_frame"]),
        )
        if (
            compact_end <= compact_start
            or source_end - source_start != compact_end - compact_start
        ):
            continue

        candidates = []
        shot_people = people[compact_start:compact_end]
        for candidate_index, color in enumerate(_RECAST_MASK_COLORS):
            color_array = np.asarray(color, dtype=np.uint8)
            region = np.all(shot_people == color_array, axis=-1)
            areas = region.reshape(len(region), -1).sum(axis=1)
            if not int(areas.max(initial=0)):
                continue
            local_anchor = int(np.argmax(areas))
            descriptor = _recast_appearance_descriptor(
                frames[source_start + local_anchor],
                region[local_anchor],
            )
            if descriptor is None:
                continue
            scores = []
            for mapping_prototypes in prototypes:
                scores.append(max(
                    (
                        float(np.dot(descriptor, prototype))
                        for prototype in mapping_prototypes
                    ),
                    default=0.0,
                ))
            candidates.append({
                "candidate_index": candidate_index,
                "region": region,
                "scores": scores,
                "area": int(areas[local_anchor]),
            })

        pairings = []
        for candidate in candidates:
            scores = list(candidate["scores"])
            for mapping_index, score in enumerate(scores):
                alternatives = [
                    other_score
                    for other_index, other_score in enumerate(scores)
                    if other_index != mapping_index
                ]
                margin = score - max(alternatives, default=0.0)
                if (
                    score >= float(minimum_similarity)
                    and margin >= float(minimum_margin)
                    and prototypes[mapping_index]
                ):
                    pairings.append((
                        score,
                        margin,
                        candidate["area"],
                        candidate["candidate_index"],
                        mapping_index,
                        candidate["region"],
                    ))
        pairings.sort(reverse=True, key=lambda item: item[:3])

        used_candidates = set()
        used_mappings = set()
        for (
            score, margin, _area, candidate_index, mapping_index, region,
        ) in pairings:
            if (
                candidate_index in used_candidates
                or mapping_index in used_mappings
            ):
                continue
            color_array = np.asarray(
                _RECAST_MASK_COLORS[mapping_index],
                dtype=np.uint8,
            )
            target = output_masks[mapping_index][source_start:source_end]
            target[region] = color_array
            used_candidates.add(candidate_index)
            used_mappings.add(mapping_index)
            recovered.append({
                "shot_index": int(shot["shot_index"]),
                "mapping_index": mapping_index,
                "similarity": round(float(score), 4),
                "margin": round(float(margin), 4),
            })
    return output_masks, recovered


def _plan_recast_shot_segments(
    mapping_masks, shot_ranges, min_area_ratio=0.0001, *,
    split_cast_transitions=False, min_cast_run_frames=4,
):
    """Resolve active mappings and the best composition anchor per segment.

    Presence is evaluated inside each detected camera shot rather than across
    a diffusion window. This prevents two characters in adjacent
    shot/reverse-shot frames from being mistaken for a simultaneous cast.

    Recast can additionally divide one camera shot when its stable set of
    mapped characters changes. SCAIL-2 then starts every generated segment
    with the same semantic colors represented by its primary reference,
    instead of asking it to introduce a second identity partway through a
    window. Short presence/dropout runs are absorbed into their neighbors so
    detector flicker and momentary occlusion do not create tiny jobs.
    """
    import numpy as np

    masks = [np.asarray(mask) for mask in mapping_masks or []]
    if not masks:
        raise ValueError("Shot-aware Recast needs tracked mapping masks.")
    frame_count = int(len(masks[0]))
    if frame_count <= 0:
        raise ValueError("Shot-aware Recast received an empty timeline.")
    if any(len(mask) != frame_count for mask in masks):
        raise ValueError("Shot-aware Recast mapping timelines differ in length.")

    regions = []
    areas = []
    for mask in masks:
        if mask.ndim == 4 and mask.shape[-1] == 3:
            region = np.any(mask > 30, axis=-1)
        elif mask.ndim == 3:
            region = mask.astype(bool)
        else:
            raise ValueError(
                f"Unsupported Recast mapping-mask shape: {mask.shape}."
            )
        regions.append(region)
        areas.append(region.reshape(frame_count, -1).sum(axis=1))

    frame_area = int(regions[0].shape[-2] * regions[0].shape[-1])
    minimum_pixels = max(
        16,
        int(round(frame_area * max(0.0, float(min_area_ratio)))),
    )
    try:
        minimum_cast_run = max(1, int(min_cast_run_frames))
    except (TypeError, ValueError):
        minimum_cast_run = 4

    def _runs(values):
        values = np.asarray(values, dtype=bool)
        if not len(values):
            return []
        result = []
        run_start = 0
        run_value = bool(values[0])
        for index in range(1, len(values)):
            value = bool(values[index])
            if value == run_value:
                continue
            result.append((run_start, index, run_value))
            run_start, run_value = index, value
        result.append((run_start, len(values), run_value))
        return result

    def _stabilize_presence(values):
        stable = np.asarray(values, dtype=bool).copy()
        if minimum_cast_run <= 1 or len(stable) <= 1:
            return stable
        while True:
            presence_runs = _runs(stable)
            if len(presence_runs) <= 1:
                return stable
            short = [
                (end - start, run_index, start, end)
                for run_index, (start, end, _value) in enumerate(
                    presence_runs
                )
                if end - start < minimum_cast_run
            ]
            if not short:
                return stable
            _length, run_index, start, end = min(short)
            if run_index == 0:
                replacement = presence_runs[1][2]
            elif run_index == len(presence_runs) - 1:
                replacement = presence_runs[-2][2]
            else:
                # Boolean runs alternate, so both neighbors normally agree.
                # The duration tie-break keeps this safe if the representation
                # ever expands beyond a single presence bit.
                left = presence_runs[run_index - 1]
                right = presence_runs[run_index + 1]
                replacement = (
                    left[2]
                    if (
                        left[2] == right[2]
                        or left[1] - left[0] >= right[1] - right[0]
                    )
                    else right[2]
                )
            stable[start:end] = replacement

    def _signature_runs(stable_presence):
        if stable_presence.shape[1] <= 0:
            return []
        signatures = [
            tuple(np.flatnonzero(stable_presence[:, frame_index]).tolist())
            for frame_index in range(stable_presence.shape[1])
        ]
        result = []
        run_start = 0
        run_signature = signatures[0]
        for frame_index in range(1, len(signatures)):
            signature = signatures[frame_index]
            if signature == run_signature:
                continue
            result.append([run_start, frame_index, run_signature])
            run_start, run_signature = frame_index, signature
        result.append([run_start, len(signatures), run_signature])

        # Two long tracks can overlap or hand off for only a frame or two even
        # after each individual presence timeline is stable. Fold that brief
        # combined signature into the most compatible neighboring segment.
        while len(result) > 1:
            short = [
                (end - start, run_index)
                for run_index, (start, end, _signature) in enumerate(result)
                if end - start < minimum_cast_run
            ]
            if not short:
                break
            _length, run_index = min(short)
            current = set(result[run_index][2])
            neighbor_indices = [
                index
                for index in (run_index - 1, run_index + 1)
                if 0 <= index < len(result)
            ]
            replacement_index = max(
                neighbor_indices,
                key=lambda index: (
                    len(current.intersection(result[index][2])),
                    -len(current.symmetric_difference(result[index][2])),
                    result[index][1] - result[index][0],
                    -abs(index - run_index),
                ),
            )
            result[run_index][2] = result[replacement_index][2]
            merged = []
            for start, end, signature in result:
                if merged and merged[-1][2] == signature:
                    merged[-1][1] = end
                else:
                    merged.append([start, end, signature])
            result = merged
        return result

    normalized_ranges = []
    for raw_start, raw_end in shot_ranges or [(0, frame_count)]:
        start = max(0, min(frame_count, int(raw_start)))
        end = max(start, min(frame_count, int(raw_end)))
        if end > start:
            normalized_ranges.append((start, end))
    if not normalized_ranges:
        normalized_ranges = [(0, frame_count)]

    plans = []
    for camera_shot_index, (shot_start, shot_end) in enumerate(
        normalized_ranges
    ):
        shot_areas = np.stack(
            [area[shot_start:shot_end] for area in areas],
            axis=0,
        )
        if split_cast_transitions:
            stable_presence = np.stack([
                _stabilize_presence(mapping_area >= minimum_pixels)
                for mapping_area in shot_areas
            ])
            local_segments = _signature_runs(stable_presence)
        else:
            active = tuple(
                index
                for index in range(len(masks))
                if int(shot_areas[index].max(initial=0)) >= minimum_pixels
            )
            local_segments = [[0, shot_end - shot_start, active]]

        for cast_segment_index, (
            local_start, local_end, active_signature,
        ) in enumerate(local_segments):
            start = shot_start + int(local_start)
            end = shot_start + int(local_end)
            active_indices = [int(index) for index in active_signature]
            segment_areas = np.stack(
                [area[start:end] for area in areas],
                axis=0,
            )
            if active_indices:
                active_areas = segment_areas[active_indices]
                visible = active_areas >= minimum_pixels
                common = np.all(visible, axis=0)
                if bool(common.any()):
                    candidates = np.flatnonzero(common)
                    first_all_active = start + int(candidates[0])
                    # Favor a frame where the least-visible active character
                    # is still large, then total area as the tie-breaker.
                    minimum_area = active_areas[:, candidates].min(axis=0)
                    total_area = active_areas[:, candidates].sum(axis=0)
                    local_anchor = int(
                        candidates[
                            np.lexsort((total_area, minimum_area))[-1]
                        ]
                    )
                    cooccurring = True
                else:
                    first_all_active = None
                    visible_count = visible.sum(axis=0)
                    total_area = active_areas.sum(axis=0)
                    local_anchor = int(
                        np.lexsort((total_area, visible_count))[-1]
                    )
                    cooccurring = False
                anchor = start + local_anchor
            else:
                anchor = start
                first_all_active = None
                cooccurring = False

            initial_active = [
                index
                for index in active_indices
                if int(areas[index][start]) >= minimum_pixels
            ]
            active_count = len(active_indices)
            plans.append({
                "shot_index": len(plans),
                "camera_shot_index": camera_shot_index,
                "cast_segment_index": cast_segment_index,
                "segment_reason": (
                    "camera_shot"
                    if cast_segment_index == 0
                    else "cast_change"
                ),
                "start_frame": start,
                "end_frame": end,
                "frame_count": end - start,
                "anchor_frame_index": anchor,
                "first_all_active_frame_index": first_all_active,
                "active_mapping_indices": active_indices,
                "initial_active_mapping_indices": initial_active,
                "starts_with_all_active_mappings": (
                    initial_active == active_indices
                ),
                "cooccurring": cooccurring,
                "mode": (
                    "passthrough"
                    if active_count == 0
                    else "solo"
                    if active_count == 1
                    else "group"
                ),
            })
    return plans


def _resample_recast_tracking_timeline(
    source_frames, mapping_masks, shot_ranges, target_frame_count,
):
    """Resample tracked frames and cuts onto Recast's generation timeline."""
    import numpy as np

    source = np.asarray(source_frames)
    source_count = int(len(source))
    target_count = int(target_frame_count)
    if source_count <= 0 or target_count <= 0:
        raise ValueError("Recast timeline frame counts must be positive.")
    masks = [np.asarray(mask) for mask in mapping_masks or []]
    if any(len(mask) != source_count for mask in masks):
        raise ValueError("Recast masks do not match the source timeline.")

    indices = np.floor(
        np.arange(target_count, dtype=np.float64)
        * float(source_count)
        / float(target_count)
    ).astype(np.int64)
    indices = np.clip(indices, 0, source_count - 1)
    resampled_source = source[indices]
    resampled_masks = [mask[indices] for mask in masks]

    ranges = list(shot_ranges or [(0, source_count)])
    if not ranges:
        ranges = [(0, source_count)]
    shot_count = min(len(ranges), target_count)
    ranges = ranges[:shot_count]
    boundaries = [0]
    for boundary_index, (_start, raw_end) in enumerate(ranges[:-1], 1):
        remaining = shot_count - boundary_index
        scaled = int(round(
            max(0, min(source_count, int(raw_end)))
            * float(target_count)
            / float(source_count)
        ))
        lower = boundaries[-1] + 1
        upper = target_count - remaining
        boundaries.append(max(lower, min(upper, scaled)))
    boundaries.append(target_count)
    resampled_ranges = [
        (start, end)
        for start, end in zip(boundaries, boundaries[1:])
        if end > start
    ]
    return resampled_source, resampled_masks, resampled_ranges


def _remap_recast_shot_mask(
    semantic_mask, active_mapping_indices,
    background_color=(255, 255, 255),
):
    """Convert global card colors to contiguous per-shot SCAIL colors."""
    import numpy as np

    mask = np.asarray(semantic_mask, dtype=np.uint8)
    if mask.ndim not in (3, 4) or mask.shape[-1] != 3:
        raise ValueError(
            f"Recast semantic mask must be H/W/RGB or T/H/W/RGB; got {mask.shape}."
        )
    output = np.empty_like(mask, dtype=np.uint8)
    output[...] = np.asarray(background_color, dtype=np.uint8)
    for local_index, mapping_index in enumerate(active_mapping_indices or []):
        global_color = np.asarray(
            _RECAST_MASK_COLORS[int(mapping_index)],
            dtype=np.uint8,
        )
        local_color = np.asarray(
            _RECAST_MASK_COLORS[local_index],
            dtype=np.uint8,
        )
        output[np.all(mask == global_color, axis=-1)] = local_color
    return output


def _quantize_recast_shot_frame_count(
    frame_count, minimum_frames, latent_size,
):
    """Return a valid model length and tail trim for one exact-length shot."""
    count = int(frame_count)
    minimum = max(1, int(minimum_frames))
    latent = max(1, int(latent_size))
    if count <= 0:
        raise ValueError("A Recast shot must contain at least one frame.")
    generated = ((count - 1 + latent - 1) // latent) * latent + 1
    generated = max(generated, minimum)
    if (generated - 1) % latent:
        generated = (
            (generated - 1 + latent - 1) // latent
        ) * latent + 1
    return generated, generated - count


def _build_recast_shot_prompt(
    active_count, *, finished_video_prompt=None, total_mapping_count=None,
):
    """Build text that cannot introduce identities absent from this shot."""
    count = max(1, min(5, int(active_count)))
    try:
        total_count = max(1, min(5, int(total_mapping_count)))
    except (TypeError, ValueError):
        total_count = None
    requested_prompt = str(finished_video_prompt or "").strip()
    if (
        count > 1
        and total_count == count
        and any(character.isalnum() for character in requested_prompt)
    ):
        # When the whole requested cast shares a shot, the user's
        # finished-video description is safe and materially helps SCAIL-2
        # retain clothing details that may be outside a portrait reference.
        # Solo/subset shots stay neutral so an absent identity cannot leak in.
        return requested_prompt
    if count == 1:
        return (
            "A clearly defined character performs naturally within the "
            "original scene. The character's face, hair, body shape, and "
            "complete outfit remain visually consistent while following the "
            "visible action and camera movement. The environment, lighting, "
            "shadows, and nearby objects form one coherent natural shot."
        )
    return (
        f"{count} clearly defined characters perform naturally within the "
        "original scene. Each character's face, hair, body shape, and complete "
        "outfit remain visually distinct and consistent while following the "
        "visible action and interactions. The environment, lighting, shadows, "
        "and nearby objects form one coherent natural shot."
    )

def _compose_recast_timeline_preview(
    source_frames, mapping_masks, mapping_results, max_tile_width=420,
):
    """Build one compact card per mapping at its best sampled anchor."""
    import numpy as np
    from PIL import Image as _PILImage, ImageDraw as _PILImageDraw

    frames = np.asarray(source_frames, dtype=np.uint8)
    if frames.ndim != 4 or frames.shape[-1] != 3:
        raise ValueError("Recast timeline preview needs T/H/W/RGB frames.")
    tiles = []
    for result, raw_mask in zip(mapping_results, mapping_masks):
        if not result.get("found"):
            continue
        sample_index = int(result["anchor_sample_index"])
        frame = frames[sample_index].copy()
        mask = np.asarray(raw_mask, dtype=np.uint8)[sample_index]
        selected = np.any(mask > 30, axis=-1)
        if bool(selected.any()):
            frame[selected] = (
                frame[selected].astype(np.float32) * 0.45
                + mask[selected].astype(np.float32) * 0.55
            ).astype(np.uint8)
        image = _PILImage.fromarray(frame)
        if image.width > int(max_tile_width):
            tile_height = max(
                1,
                int(round(image.height * int(max_tile_width) / image.width)),
            )
            image = image.resize(
                (int(max_tile_width), tile_height),
                resample=_PILImage.Resampling.LANCZOS,
            )
        header_height = 24
        tile = _PILImage.new(
            "RGB",
            (image.width, image.height + header_height),
            (22, 24, 29),
        )
        tile.paste(image, (0, header_height))
        draw = _PILImageDraw.Draw(tile)
        color = tuple(int(value) for value in result["color"])
        draw.rectangle((6, 6, 16, 16), fill=color, outline=(235, 235, 235))
        label = (
            f"Character {chr(65 + int(result['mapping_index']))} - "
            f"{float(result['anchor_time_seconds']):.1f}s"
        )
        draw.text((22, 5), label, fill=(235, 238, 244))
        tiles.append(tile)
    if not tiles:
        return _PILImage.fromarray(frames[0])
    columns = min(2, len(tiles))
    rows = (len(tiles) + columns - 1) // columns
    cell_width = max(tile.width for tile in tiles)
    cell_height = max(tile.height for tile in tiles)
    sheet = _PILImage.new(
        "RGB",
        (columns * cell_width, rows * cell_height),
        (14, 16, 20),
    )
    for index, tile in enumerate(tiles):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet.paste(tile, (x, y))
    return sheet

def _resize_recast_shot_frames(frames, canvas_size, *, semantic=False):
    """Resize T/H/W/RGB frames to the exact generation canvas."""
    import numpy as np
    from PIL import Image as _PILImage

    array = np.asarray(frames, dtype=np.uint8)
    if array.ndim != 4 or array.shape[-1] != 3:
        raise ValueError(
            f"Recast shot frames must be T/H/W/RGB; got {array.shape}."
        )
    width, height = int(canvas_size[0]), int(canvas_size[1])
    if min(width, height) <= 0:
        raise ValueError("Recast shot canvas dimensions must be positive.")
    if array.shape[1:3] == (height, width):
        return array.copy()
    resample = (
        _PILImage.Resampling.NEAREST
        if semantic
        else _PILImage.Resampling.LANCZOS
    )
    return np.stack([
        np.asarray(
            _PILImage.fromarray(frame).resize(
                (width, height),
                resample=resample,
            ),
            dtype=np.uint8,
        )
        for frame in array
    ])


def _write_recast_shot_video(path, frames, fps, *, semantic=False):
    """Persist one silent internal guide or semantic-mask clip."""
    import imageio.v2 as imageio
    import numpy as np

    array = np.asarray(frames, dtype=np.uint8)
    if array.ndim != 4 or array.shape[-1] != 3 or len(array) == 0:
        raise ValueError("Cannot write an empty or malformed Recast shot.")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if semantic:
        from shared import magic_mask

        codec_params = magic_mask._magic_mask_video_codec_params()
    else:
        codec_params = {
            "codec": "libx264",
            "quality": 9,
            "pixelformat": "yuv420p",
            "macro_block_size": 1,
        }
    writer = imageio.get_writer(
        path,
        fps=float(fps),
        ffmpeg_log_level="error",
        **codec_params,
    )
    try:
        for frame in array:
            writer.append_data(frame)
    finally:
        writer.close()
    return path

def _build_recast_shot_reference_conditioning(
    prepared_refs, active_mapping_indices, source_frame,
    local_semantic_mask, output_dir, job_id, shot_index, *,
    cooccurring, reference_canvas,
):
    """Build balanced, composition-aware references for one camera shot."""
    import numpy as np

    active = [int(index) for index in active_mapping_indices]
    if not active:
        raise ValueError("A generated Recast shot needs an active character.")
    active_count = len(active)
    all_images = list(prepared_refs.get("image_refs") or [])
    all_masks = [
        prepared_refs.get("primary_mask"),
        *list(prepared_refs.get("additional_masks") or []),
    ]
    all_colors = list(prepared_refs.get("expected_colors") or [])
    if (
        len(all_images) != len(all_masks)
        or len(all_images) != len(all_colors)
    ):
        raise ValueError("Prepared Recast reference pairs are out of sync.")

    views_by_mapping = {mapping_index: [] for mapping_index in active}
    for image_path, mask_path, raw_color in zip(
        all_images, all_masks, all_colors,
    ):
        if not image_path or not mask_path or raw_color is None:
            continue
        try:
            color = tuple(int(channel) for channel in raw_color)
        except (TypeError, ValueError):
            continue
        for mapping_index in active:
            if color == tuple(_RECAST_MASK_COLORS[mapping_index]):
                views_by_mapping[mapping_index].append(
                    (image_path, mask_path),
                )
                break

    primary_items = {
        int(item["mapping_index"]): item
        for item in prepared_refs.get("primary_target_refs") or []
        if isinstance(item, dict) and "mapping_index" in item
    }
    primary_layers = []
    for local_index, mapping_index in enumerate(active):
        item = primary_items.get(mapping_index)
        if not item:
            raise ValueError(
                f"Missing primary reference for Recast mapping "
                f"{mapping_index + 1}."
            )
        primary_layers.append(
            _load_recast_reference_pair(
                item["image"],
                item["mask"],
                mapping_index,
                local_index,
            )
        )

    primary_mode = "shot_layout"
    try:
        if active_count > 1 and not cooccurring:
            raise ValueError(
                "active characters never share one frame in this shot"
            )
        primary_image, primary_mask = (
            _compose_recast_group_reference_frame(
                source_frame,
                local_semantic_mask,
                primary_layers,
                active_count,
            )
        )
    except ValueError as composition_error:
        print(
            f"[Recast] Shot {shot_index + 1} has no usable shared layout; "
            f"using a balanced cast sheet: {composition_error}"
        )
        primary_image, primary_mask = (
            _compose_recast_cast_reference_frame(
                primary_layers,
                active_count,
                reference_canvas,
            )
        )
        primary_mode = "cast_sheet"

    stem = f"recast_shot_ref_{job_id}_{shot_index + 1}"
    primary_path, primary_mask_path = _save_recast_reference_pair(
        output_dir,
        stem,
        primary_image,
        primary_mask,
    )
    image_refs = [primary_path]
    mask_paths = [primary_mask_path]
    expected_colors = [
        list(_RECAST_MASK_COLORS[0])
        if active_count == 1
        else None
    ]

    if active_count == 1:
        mapping_index = active[0]
        for view_index, (image_path, mask_path) in enumerate(
            views_by_mapping.get(mapping_index) or [],
            1,
        ):
            _rgb, recolored_mask = _load_recast_reference_pair(
                image_path,
                mask_path,
                mapping_index,
                0,
            )
            recolored_mask_path = os.path.join(
                output_dir,
                f"{stem}_identity_{view_index}_mask.png",
            )
            from PIL import Image as _PILImage

            _PILImage.fromarray(recolored_mask).save(recolored_mask_path)
            image_refs.append(image_path)
            mask_paths.append(recolored_mask_path)
            expected_colors.append(list(_RECAST_MASK_COLORS[0]))
    else:
        # A spatial group primary already contains every active identity in
        # the tracked left/right slots. Extra side-by-side cast/detail sheets
        # can disagree with those positions when the source actors cross or
        # appear in reverse card order. SCAIL-2 then follows the sheet layout
        # instead of its semantic colors, swapping and enlarging characters.
        # Keep the native group pair singular; the dedicated source-scene
        # reference below remains the only supporting reference.
        omitted_views = sum(
            len(views_by_mapping.get(mapping_index) or [])
            for mapping_index in active
        )
        reference_kind = (
            "spatial"
            if primary_mode == "shot_layout"
            else "balanced"
        )
        print(
            f"[Recast] Shot {shot_index + 1} uses one {reference_kind} "
            f"{active_count}-character reference; omitted "
            f"{omitted_views} separate identity view(s) that could override "
            "tracked color correspondence."
        )

    scene_reference = _build_recast_source_scene_reference(
        source_frame,
        local_semantic_mask,
        active_count,
        output_dir,
        f"{job_id}_shot_{shot_index + 1}",
        output_size=tuple(reference_canvas),
    )
    return {
        "image_refs": image_refs,
        "primary_mask": mask_paths[0],
        "additional_masks": mask_paths[1:],
        "expected_colors": expected_colors,
        "clip_identity_ref": (
            (views_by_mapping.get(active[0]) or [(primary_path, None)])[0][0]
            if active_count == 1
            else primary_path
        ),
        "source_scene_reference": scene_reference,
        "primary_mode": primary_mode,
    }


def _build_recast_shot_manifest(
    base_params, mapped_tracking, prepared_refs, output_dir, job_id, *,
    reference_canvas, target_frame_count, generation_fps,
    minimum_frames, latent_size,
):
    """Create internal, exact-length generation tasks per detected shot."""
    import copy
    import numpy as np

    source_frames, mapping_masks, shot_ranges = (
        _resample_recast_tracking_timeline(
            mapped_tracking["source_frames"],
            mapped_tracking["mapping_masks"],
            mapped_tracking["shot_ranges"],
            target_frame_count,
        )
    )
    cast_transition_hold_frames = max(
        4,
        min(12, int(round(max(1.0, float(generation_fps)) * 0.2))),
    )
    transition_plans = _plan_recast_shot_segments(
        mapping_masks,
        shot_ranges,
        split_cast_transitions=True,
        min_cast_run_frames=cast_transition_hold_frames,
    )
    plans = _plan_recast_shot_segments(
        mapping_masks,
        shot_ranges,
        # Keep every camera shot continuous. Splitting at a cast entrance
        # created tiny independent clips that could leave the source actor
        # untouched and made SCAIL-2 relearn color/identity correspondence at
        # the join. A hidden identity-aware pre-roll below gives late entrants
        # an initialization frame without publishing a new boundary.
        split_cast_transitions=False,
        min_cast_run_frames=cast_transition_hold_frames,
    )
    cast_transition_count = max(
        0,
        len(transition_plans) - len(shot_ranges),
    )

    global_semantic = np.empty(
        (*source_frames.shape[:-1], 3),
        dtype=np.uint8,
    )
    global_semantic[...] = (255, 255, 255)
    occupied = np.zeros(source_frames.shape[:-1], dtype=bool)
    for mapping_index, mapping_mask in enumerate(mapping_masks):
        region = (
            np.any(mapping_mask > 30, axis=-1)
            if mapping_mask.ndim == 4
            else mapping_mask.astype(bool)
        )
        writable = region & ~occupied
        global_semantic[writable] = np.asarray(
            _RECAST_MASK_COLORS[mapping_index],
            dtype=np.uint8,
        )
        occupied |= region

    os.makedirs(output_dir, exist_ok=True)
    tasks = []
    published_plans = []
    for plan in plans:
        shot_index = int(plan["shot_index"])
        start, end = int(plan["start_frame"]), int(plan["end_frame"])
        active = list(plan["active_mapping_indices"])
        shot_frames = source_frames[start:end]
        resized_source = _resize_recast_shot_frames(
            shot_frames,
            reference_canvas,
        )
        published = dict(plan)
        published["active_mapping_indices"] = list(active)

        if not active:
            passthrough_path = os.path.join(
                output_dir,
                f"recast_{job_id}_shot_{shot_index + 1}_source.mp4",
            )
            _write_recast_shot_video(
                passthrough_path,
                resized_source,
                generation_fps,
            )
            plan["passthrough_path"] = passthrough_path
            published["generation_mode"] = "source_passthrough"
            published_plans.append(published)
            continue

        local_mask = _remap_recast_shot_mask(
            global_semantic[start:end],
            active,
        )
        resized_mask = _resize_recast_shot_frames(
            local_mask,
            reference_canvas,
            semantic=True,
        )
        anchor_index = int(plan["anchor_frame_index"])
        anchor_mask = _remap_recast_shot_mask(
            global_semantic[anchor_index],
            active,
            background_color=(0, 0, 0),
        )
        shot_refs = _build_recast_shot_reference_conditioning(
            prepared_refs,
            active,
            source_frames[anchor_index],
            anchor_mask,
            output_dir,
            job_id,
            shot_index,
            cooccurring=bool(plan["cooccurring"]),
            reference_canvas=reference_canvas,
        )

        generated_frames, trim_tail = (
            _quantize_recast_shot_frame_count(
                end - start,
                minimum_frames,
                latent_size,
            )
        )
        pad_count = generated_frames - (end - start)
        if pad_count > 0:
            resized_source = np.concatenate([
                resized_source,
                np.repeat(resized_source[-1:], pad_count, axis=0),
            ])
            resized_mask = np.concatenate([
                resized_mask,
                np.repeat(resized_mask[-1:], pad_count, axis=0),
            ])

        guide_path = os.path.join(
            output_dir,
            f"recast_{job_id}_shot_{shot_index + 1}_guide.mp4",
        )
        mask_path = os.path.join(
            output_dir,
            f"recast_{job_id}_shot_{shot_index + 1}_mask.mp4",
        )
        _write_recast_shot_video(
            guide_path,
            resized_source,
            generation_fps,
        )
        _write_recast_shot_video(
            mask_path,
            resized_mask,
            generation_fps,
            semantic=True,
        )

        custom_settings = copy.deepcopy(
            base_params.get("custom_settings") or {},
        )
        try:
            requested_warmup = max(
                0,
                int(custom_settings.get(
                    "scail2_recast_warmup_frames",
                    8,
                ) or 0),
            )
        except (TypeError, ValueError):
            requested_warmup = 8
        identity_warmup_anchor = None
        if (
            len(active) > 1
            and bool(plan.get("cooccurring"))
            and not bool(plan.get("starts_with_all_active_mappings"))
        ):
            first_all_active = plan.get("first_all_active_frame_index")
            if first_all_active is not None:
                latent = max(1, int(latent_size))
                # Keep the normal hidden-frame budget whenever possible. The
                # remote anchor supplies the missing identity; increasing the
                # budget from 8 to 16 can needlessly create another diffusion
                # window on common 5-second shots.
                desired_warmup = min(
                    16,
                    max(latent, requested_warmup or 8),
                )
                desired_warmup = min(
                    16,
                    max(
                        latent,
                        (
                            (desired_warmup + latent - 1)
                            // latent
                        ) * latent,
                    ),
                )
                identity_warmup_anchor = max(
                    1,
                    int(plan["anchor_frame_index"]) - start,
                )
                custom_settings["scail2_recast_warmup_frames"] = (
                    desired_warmup
                )
                custom_settings[
                    "scail2_recast_warmup_anchor_offset"
                ] = identity_warmup_anchor
                published["identity_warmup_frames"] = desired_warmup
                published["identity_warmup_anchor_frame_index"] = int(
                    plan["anchor_frame_index"]
                )
                print(
                    f"[Recast] Shot {shot_index + 1} stays continuous; "
                    f"a hidden {desired_warmup}-frame identity pre-roll "
                    f"starts from mapped frame "
                    f"{int(plan['anchor_frame_index'])} before returning "
                    "to the shot boundary."
                )
        custom_settings.update({
            "scail2_reference_mask_path": shot_refs["primary_mask"],
            "scail2_additional_reference_mask_paths": list(
                shot_refs["additional_masks"],
            ),
            "scail2_reference_expected_colors": list(
                shot_refs["expected_colors"],
            ),
            "scail2_clip_reference_path": shot_refs["clip_identity_ref"],
            "scail2_primary_reference_people": len(active),
            "scail2_dynamic_source_scene_reference": True,
            "scail2_timeline_source_scene_reference": False,
            "scail2_source_scene_reference_path": shot_refs[
                "source_scene_reference"
            ]["image"],
            "scail2_source_scene_mask_path": shot_refs[
                "source_scene_reference"
            ]["mask"],
            "scail2_identity_latent_reference_index": 0,
        })
        shot_prompt = _build_recast_shot_prompt(
            len(active),
            finished_video_prompt=base_params.get("prompt"),
            total_mapping_count=len(mapping_masks),
        )
        tasks.append({
            "shot_index": shot_index,
            "params": {
                "prompt": shot_prompt,
                "video_guide": guide_path,
                "video_mask": mask_path,
                "image_refs": list(shot_refs["image_refs"]),
                "video_length": generated_frames,
                "trim_tail_frames": trim_tail,
                "video_prompt_type": f"V0{len(active)}AI",
                "image_prompt_type": "",
                # Each internal clip is silent. One pristine source track is
                # attached only after exact-frame assembly.
                "audio_prompt_type": "",
                "audio_guide": None,
                "audio_source": None,
                "force_fps": "control",
                "custom_settings": custom_settings,
                "_recast_protect_bystanders": False,
                "output_filename": (
                    f"recast_{job_id}_shot_{shot_index + 1}.mp4"
                ),
            },
        })
        plan["generated_task_index"] = len(tasks) - 1
        published.update({
            "generation_mode": "scail2",
            "generated_frame_count": generated_frames,
            "trim_tail_frames": trim_tail,
            "reference_mode": shot_refs["primary_mode"],
        })
        published_plans.append(published)

    return {
        "tasks": tasks,
        "shots": plans,
        "published_shots": published_plans,
        "frame_count": int(target_frame_count),
        "fps": float(generation_fps),
        "camera_shot_count": len(shot_ranges),
        "cast_transition_count": cast_transition_count,
    }


# Repaint: planning, shot assembly, and POST /api/v1/repaint/preview + POST /api/v1/repaint. Each module takes
# the launch objects it reads once, here. The recast helpers are moving to services (C7 and C8a), so Repaint gets
# forwarders that call whatever launch exports under their names; the worker and the hardware probe are defined
# further down (the studio forwarders).
def _forward_repaint_build_recast_source_scene_reference(*args, **kwargs):
    return _build_recast_source_scene_reference(*args, **kwargs)

def _forward_repaint_compose_recast_cast_reference_frame(*args, **kwargs):
    return _compose_recast_cast_reference_frame(*args, **kwargs)

def _forward_repaint_compose_recast_character_masks(*args, **kwargs):
    return _compose_recast_character_masks(*args, **kwargs)

def _forward_repaint_compose_recast_group_reference_frame(*args, **kwargs):
    return _compose_recast_group_reference_frame(*args, **kwargs)

def _forward_repaint_detect_recast_shot_ranges(*args, **kwargs):
    return _detect_recast_shot_ranges(*args, **kwargs)

def _forward_repaint_plan_recast_shot_segments(*args, **kwargs):
    return _plan_recast_shot_segments(*args, **kwargs)

def _forward_repaint_quantize_recast_shot_frame_count(*args, **kwargs):
    return _quantize_recast_shot_frame_count(*args, **kwargs)

def _forward_repaint_recolor_recast_reference_mask(*args, **kwargs):
    return _recolor_recast_reference_mask(*args, **kwargs)

def _forward_repaint_remap_recast_shot_mask(*args, **kwargs):
    return _remap_recast_shot_mask(*args, **kwargs)

def _forward_repaint_resample_recast_tracking_timeline(*args, **kwargs):
    return _resample_recast_tracking_timeline(*args, **kwargs)

def _forward_repaint_resize_recast_shot_frames(*args, **kwargs):
    return _resize_recast_shot_frames(*args, **kwargs)

def _forward_repaint_save_recast_reference_pair(*args, **kwargs):
    return _save_recast_reference_pair(*args, **kwargs)

def _forward_repaint_summarize_recast_mapping_mask(*args, **kwargs):
    return _summarize_recast_mapping_mask(*args, **kwargs)

def _forward_repaint_write_recast_shot_video(*args, **kwargs):
    return _write_recast_shot_video(*args, **kwargs)

def _forward_repaint_recast_video_has_audio(*args, **kwargs):
    return _recast_video_has_audio(*args, **kwargs)

def _forward_repaint_recast_video_frame_count(*args, **kwargs):
    return _recast_video_frame_count(*args, **kwargs)

def _forward_repaint_normalize_recast_resolution_profile(*args, **kwargs):
    return _normalize_recast_resolution_profile(*args, **kwargs)

def _forward_repaint_recast_resolution_for_source(*args, **kwargs):
    return _recast_resolution_for_source(*args, **kwargs)

def _forward_repaint_recast_window_size_for_profile(*args, **kwargs):
    return _recast_window_size_for_profile(*args, **kwargs)

def _forward_repaint_resolve_recast_media(*args, **kwargs):
    return _resolve_recast_media(*args, **kwargs)


from services.repaint_planning import (
    _build_repaint_semantic_conditioning, _build_repaint_shot_manifest, _build_repaint_shot_prompt,
    _build_repaint_shot_reference_conditioning, _normalize_repaint_region_mappings, _prepare_repaint_target_frame,
    _repaint_preview_data_uri, _repaint_resolution_for_aspect, _validate_repaint_target_aspect,
    bind as _bind_repaint_planning,
)
from services.repaint_run import (
    _run_repaint_shot_generation, _write_repaint_shot_aware_sidecar, bind as _bind_repaint_run,
)
from routers.repaint import create_repaint_router, repaint_endpoint, repaint_preview_endpoint

_bind_repaint_planning(
    recast_mask_colors=_RECAST_MASK_COLORS,
    build_recast_source_scene_reference=_forward_repaint_build_recast_source_scene_reference,
    compose_recast_cast_reference_frame=_forward_repaint_compose_recast_cast_reference_frame,
    compose_recast_character_masks=_forward_repaint_compose_recast_character_masks,
    compose_recast_group_reference_frame=_forward_repaint_compose_recast_group_reference_frame,
    detect_recast_shot_ranges=_forward_repaint_detect_recast_shot_ranges,
    plan_recast_shot_segments=_forward_repaint_plan_recast_shot_segments,
    quantize_recast_shot_frame_count=_forward_repaint_quantize_recast_shot_frame_count,
    recolor_recast_reference_mask=_forward_repaint_recolor_recast_reference_mask,
    remap_recast_shot_mask=_forward_repaint_remap_recast_shot_mask,
    resample_recast_tracking_timeline=_forward_repaint_resample_recast_tracking_timeline,
    resize_recast_shot_frames=_forward_repaint_resize_recast_shot_frames,
    save_recast_reference_pair=_forward_repaint_save_recast_reference_pair,
    summarize_recast_mapping_mask=_forward_repaint_summarize_recast_mapping_mask,
    write_recast_shot_video=_forward_repaint_write_recast_shot_video,
)
_bind_repaint_run(
    wgp=wgp, jobs=_jobs, active_gen_states=_active_gen_states, workspace_dir=_workspace_dir,
    recast_video_has_audio=_forward_repaint_recast_video_has_audio,
    recast_video_frame_count=_forward_repaint_recast_video_frame_count,
    run_generation=_forward_studio_run_generation,
)
api.include_router(create_repaint_router(
    wgp=wgp, recast_mask_colors=_RECAST_MASK_COLORS, active_gen_states=_active_gen_states,
    coordinated_generation_slot=_coordinated_generation_slot, generation_job_acceptance=_generation_job_acceptance,
    get_active_workspace=_get_active_workspace, register_manual_generation_job=_register_manual_generation_job,
    workspace_dir=_workspace_dir, get_cached_hardware=_forward_studio_cached_hardware,
    run_generation=_forward_studio_run_generation,
    normalize_scail2_guidance_scale=_normalize_scail2_guidance_scale,
    normalize_scail2_inference_steps=_normalize_scail2_inference_steps,
    normalize_recast_resolution_profile=_forward_repaint_normalize_recast_resolution_profile,
    recast_resolution_for_source=_forward_repaint_recast_resolution_for_source,
    recast_window_size_for_profile=_forward_repaint_recast_window_size_for_profile,
    resolve_recast_media=_forward_repaint_resolve_recast_media,
))


@api.post("/api/v1/recast/preview")
async def recast_preview_endpoint(request: Request):
    """Preview mapped people across the selected Recast timeline.

    Body: { video_path: str, target?: str, person_count?: int,
            character_mappings?: list, ref_image_path?: str,
            time?: float, end_time?: float, workspace?: str }
    """
    body = await request.json()
    workspace = body.get("workspace")
    video_path = _resolve_recast_media(body.get("video_path"), workspace)
    if not video_path:
        raise HTTPException(status_code=400, detail=f"Video not found: {body.get('video_path')}")
    raw_mappings = body.get("character_mappings")
    explicit_mappings = isinstance(raw_mappings, list) and len(raw_mappings) > 0
    if explicit_mappings:
        if len(raw_mappings) > len(_RECAST_MASK_COLORS):
            raise HTTPException(
                status_code=400,
                detail="SCAIL-2 supports at most five character mappings.",
            )
        preview_mappings = []
        for index, mapping in enumerate(raw_mappings):
            if not isinstance(mapping, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Character mapping {index + 1} is invalid.",
                )
            target = str(mapping.get("target") or "").strip()
            if not target:
                raise HTTPException(
                    status_code=400,
                    detail=f"Character mapping {index + 1} needs a source-person description.",
                )
            preview_mappings.append({"target": target})
        person_count = len(preview_mappings)
    else:
        target = (body.get("target") or "person").strip() or "person"
        person_count = _normalize_recast_person_count(body.get("person_count"))
        preview_mappings = [{"target": target}]
    mask_colors = _RECAST_MASK_COLORS[:person_count]
    at_time = max(0.0, float(body.get("time", 0) or 0))
    try:
        import decord
        import numpy as np

        vr = decord.VideoReader(video_path)
        fps = vr.get_avg_fps() or 25
        total_video_frames = len(vr)
        if total_video_frames <= 0:
            raise ValueError("The selected video contains no frames.")
        start_index = min(
            total_video_frames - 1,
            max(0, int(round(at_time * fps))),
        )
        raw_end_time = body.get("end_time")
        end_time = (
            float(raw_end_time)
            if raw_end_time is not None
            else float(total_video_frames) / float(fps)
        )
        if end_time <= at_time:
            end_index = total_video_frames - 1
        else:
            end_index = min(
                total_video_frames - 1,
                max(start_index, int(round(end_time * fps)) - 1),
            )
        if explicit_mappings:
            span = end_index - start_index + 1
            sample_count = min(24, max(1, span))
            sample_indices = np.unique(
                np.rint(
                    np.linspace(start_index, end_index, sample_count),
                ).astype(np.int64)
            )
            sampled_frames = vr.get_batch(sample_indices).asnumpy()
        else:
            sample_indices = np.asarray([start_index], dtype=np.int64)
            sampled_frames = vr.get_batch(sample_indices).asnumpy()
        del vr
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read video: {e}")
    try:
        from shared import magic_mask

        mapping_results = []
        mapping_anchors = None
        if explicit_mappings:
            mapping_masks = []
            found_mapping_indices = []
            for index, mapping in enumerate(preview_mappings):
                tracking_target = _normalize_recast_tracking_target(
                    mapping["target"],
                )
                mapping_mask = magic_mask.generate_keyword_masks(
                    sampled_frames,
                    tracking_target,
                    no_hole=True,
                    colorize_objects=True,
                    color_palette=[mask_colors[index]],
                    max_colored_objects=1,
                    tracking_segments=[
                        (sample_index, sample_index + 1)
                        for sample_index in range(len(sampled_frames))
                    ],
                )
                region = np.any(mapping_mask > 30, axis=-1)
                areas = region.reshape(len(region), -1).sum(axis=1)
                present_samples = np.flatnonzero(areas > 0)
                found_mapping = bool(len(present_samples))
                result = {
                    "mapping_index": index,
                    "target": mapping["target"],
                    "found": found_mapping,
                    "color": list(mask_colors[index]),
                    "overlap_fraction": 0.0,
                    "first_frame_index": None,
                    "first_time_seconds": None,
                    "anchor_frame_index": None,
                    "anchor_time_seconds": None,
                    "anchor_sample_index": None,
                }
                if found_mapping:
                    anchor_sample_index = int(np.argmax(areas))
                    first_sample_index = int(present_samples[0])
                    anchor_frame_index = int(
                        sample_indices[anchor_sample_index]
                    )
                    first_frame_index = int(
                        sample_indices[first_sample_index]
                    )
                    result.update({
                        "first_frame_index": first_frame_index,
                        "first_time_seconds": (
                            float(first_frame_index) / float(fps)
                        ),
                        "anchor_frame_index": anchor_frame_index,
                        "anchor_time_seconds": (
                            float(anchor_frame_index) / float(fps)
                        ),
                        "anchor_sample_index": anchor_sample_index,
                    })
                    mapping_masks.append(mapping_mask)
                    found_mapping_indices.append(index)
                mapping_results.append(result)
            if mapping_masks:
                sampled_mask, overlaps = _compose_recast_character_masks(
                    mapping_masks,
                    [mask_colors[index] for index in found_mapping_indices],
                )
                for mapping_index, overlap in zip(
                    found_mapping_indices, overlaps,
                ):
                    mapping_results[mapping_index][
                        "overlap_fraction"
                    ] = overlap
                common_sample_index, scene_sample_index = (
                    _select_recast_timeline_anchor(mapping_masks)
                )
            else:
                sampled_mask = np.full(
                    sampled_frames.shape,
                    255,
                    dtype=np.uint8,
                )
                common_sample_index, scene_sample_index = None, 0
            matched_people = sum(result["found"] for result in mapping_results)
            selected_sample_index = (
                common_sample_index
                if common_sample_index is not None
                else scene_sample_index
            )
            idx = int(sample_indices[selected_sample_index])
            frame = sampled_frames[selected_sample_index]
            mask = sampled_mask[selected_sample_index]
            preview_image = _compose_recast_timeline_preview(
                sampled_frames,
                [
                    mapping_mask
                    for mapping_mask in mapping_masks
                ],
                [
                    mapping_results[mapping_index]
                    for mapping_index in found_mapping_indices
                ],
            )
            if matched_people == person_count:
                mapping_anchors = []
                tracked_by_mapping = {
                    mapping_index: mapping_mask
                    for mapping_index, mapping_mask in zip(
                        found_mapping_indices,
                        mapping_masks,
                    )
                }
                for mapping_index in range(person_count):
                    result = mapping_results[mapping_index]
                    anchor_sample_index = int(
                        result["anchor_sample_index"]
                    )
                    mapping_anchors.append({
                        "frame_index": result["anchor_frame_index"],
                        "source_frame": sampled_frames[
                            anchor_sample_index
                        ],
                        "source_mask": sampled_mask[
                            anchor_sample_index
                        ],
                        "mapping_mask": tracked_by_mapping[mapping_index][
                            anchor_sample_index
                        ],
                    })
        else:
            mask = magic_mask.generate_keyword_masks(
                sampled_frames, target, no_hole=True,
                colorize_objects=True,
                color_palette=mask_colors,
                max_colored_objects=person_count,
            )[0]
            idx = int(sample_indices[0])
            frame = sampled_frames[0]
            matched_people = _count_recast_mask_people(mask, mask_colors)
            mapping_results = [{
                "mapping_index": 0,
                "target": target,
                "found": matched_people >= person_count,
                "color": list(mask_colors[0]),
                "overlap_fraction": 0.0,
                "first_frame_index": idx if matched_people else None,
                "first_time_seconds": (
                    float(idx) / float(fps)
                    if matched_people
                    else None
                ),
                "anchor_frame_index": idx if matched_people else None,
                "anchor_time_seconds": (
                    float(idx) / float(fps)
                    if matched_people
                    else None
                ),
            }]
            selected = mask.any(axis=-1)
            overlay = frame.copy()
            if bool(selected.any()):
                overlay[selected] = (
                    overlay[selected].astype(np.float32) * 0.45
                    + mask[selected].astype(np.float32) * 0.55
                ).astype(np.uint8)
            from PIL import Image as _PILImage
            preview_image = _PILImage.fromarray(overlay)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Segmentation failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Segmentation failed: {e}")
    found = matched_people >= person_count
    import base64
    import io as _io

    buf = _io.BytesIO()
    preview_image.save(buf, format="JPEG", quality=85)
    resolution_profile = _normalize_recast_resolution_profile(
        body.get("resolution_profile"),
    )
    reference_canvas = _recast_resolution_for_source(
        frame,
        resolution_profile,
    )
    reference_previews = []
    has_reference = bool(body.get("ref_image_path"))
    if explicit_mappings:
        has_reference = all(
            isinstance(mapping, dict)
            and bool(
                mapping.get("ref_image_path")
                or mapping.get("reference_image_path")
            )
            for mapping in raw_mappings
        )
    if has_reference and found:
        try:
            import tempfile

            resolved_mappings, _ = _normalize_recast_character_mappings(
                body, workspace,
            )
            with tempfile.TemporaryDirectory(
                prefix="maestro-recast-preview-",
            ) as preview_dir:
                prepared = _prepare_recast_reference_conditioning(
                    resolved_mappings,
                    mask,
                    preview_dir,
                    "preview",
                    isolate_reference=body.get("isolate_reference") is not False,
                    selected_count=person_count,
                    auto_face_detail=body.get("auto_face_detail") is not False,
                    source_frame=frame,
                    reference_canvas=reference_canvas,
                    mapping_anchors=mapping_anchors,
                )
                reference_previews = prepared["previews"]
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Reference preview failed: {exc}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Reference preview failed: {exc}",
            )
    return {
        "found": found,
        "matched_people": matched_people,
        "requested_people": person_count,
        "frame_index": idx,
        "time_seconds": float(idx) / float(fps),
        "timeline_start_seconds": float(start_index) / float(fps),
        "timeline_end_seconds": float(end_index + 1) / float(fps),
        "sampled_frame_count": int(len(sample_indices)),
        "preview": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
        "mapping_results": mapping_results,
        "reference_previews": reference_previews,
        "resolution_profile": resolution_profile,
        "output_resolution": list(reference_canvas),
    }


@api.post("/api/v1/recast")
async def recast_endpoint(request: Request):
    """Submit a Recast job: replace a person in an existing video with the
    character from a reference image (SCAIL-2 Replace mode). The colored
    person mask is built automatically with SAM3 keyword tracking as a
    pre-step INSIDE the job thread — tracking a 10s clip takes about a
    minute, so the endpoint returns a job_id immediately and the job's
    message reflects detection progress.

    Body: {
        video_path: str, ref_image_path?: str,
        character_mappings?: [{
            target: str, ref_image_path: str,
            additional_ref_image_paths?: list[str],
        }],
        target?: str ("who to replace" keyword, default "person"),
        person_count?: int (legacy grouped replacement count, 1-5),
        additional_ref_image_paths?: list[str] (legacy same-character views),
        reference_aligned_to_source?: bool (reference is an edited first frame),
        auto_face_detail?: bool (derive a tighter identity view when no
            additional view is supplied; default true),
        protect_bystanders?: bool (strict post-composite; default false),
        preserve_bystanders?: bool (single-reference native multi-person
            identity conditioning; default true),
        isolate_reference?: bool (neutralize unrelated reference background;
            default true),
        enhance_prompt?: bool (rewrite and append identity/scene continuity
            guidance; default false),
        use_relighting?: bool (optional official SCAIL-2 Relighting LoRA;
            default false),
        resolution_profile?: str ("480p", "512p", or "704p"; changes spatial
            resolution and, at 704p, the adaptive window size; never model or
            step schedule),
        prompt?: str (describe the completed video, not an edit command),
        start_time?: float, end_time?: float  (optional trim),
        model_type?: str (default scail2_14B_recast_fast),
        negative_prompt?: str, seed?: int,
        num_inference_steps?: int, guidance_scale?: float,
        activated_loras?: list, loras_multipliers?: str,
        workspace?: str,
    }
    """
    body = await request.json()
    if body.get("model_type") == "viggle_animate":
        from services.wangp_submission import JsonRequest, prepare_viggle_recast, resolve_wangp_media, wangp_media_url
        import subprocess as viggle_subprocess
        try:
            params = await asyncio.to_thread(
                prepare_viggle_recast, body,
                lambda value, workspace: resolve_wangp_media(value, workspace, uploads_dir=os.path.join(os.getcwd(), "uploads"), workspace_dir=_workspace_dir(workspace)),
                os.path.join(os.getcwd(), "uploads"),
                lambda path: wangp_media_url(path, body.get("workspace"), uploads_dir=os.path.join(os.getcwd(), "uploads"), workspace_dir=_workspace_dir(body.get("workspace"))),
            )
        except (ValueError, OSError, viggle_subprocess.SubprocessError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await generate(JsonRequest(params, trusted_tool=getattr(request, "trusted_tool", None)))
    workspace = body.get("workspace")

    video_path = _resolve_recast_media(body.get("video_path"), workspace)
    if not video_path:
        raise HTTPException(status_code=400, detail=f"Video not found: {body.get('video_path')}")
    try:
        character_mappings, explicit_character_mappings = (
            _normalize_recast_character_mappings(body, workspace)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    ref_image_path = character_mappings[0]["ref_image_path"]
    target = character_mappings[0]["target"]
    person_count = (
        len(character_mappings)
        if explicit_character_mappings
        else _normalize_recast_person_count(body.get("person_count"))
    )
    reference_aligned_to_source = character_mappings[0][
        "reference_aligned_to_source"
    ]
    # Native SCAIL output is the default. Strict pixel lock remains available
    # as an expert fallback, but compositing source pixels over a freshly
    # rendered frame can create visible lighting/color seams.
    protect_bystanders = body.get("protect_bystanders") is True
    # Older saved jobs used ``preserve_scene_reference`` for an experimental
    # full-frame reference. Keep that input as a compatibility alias, but the
    # implementation now builds one neutral group reference containing only
    # the requested replacement and color-mapped people.
    if "preserve_bystanders" in body:
        preserve_bystanders = body.get("preserve_bystanders") is True
    elif "preserve_scene_reference" in body:
        preserve_bystanders = body.get("preserve_scene_reference") is True
    else:
        preserve_bystanders = True
    isolate_reference = body.get("isolate_reference") is not False
    auto_face_detail = body.get("auto_face_detail") is not False
    enhance_prompt = body.get("enhance_prompt") is True
    use_relighting = body.get("use_relighting") is True
    mask_colors = _RECAST_MASK_COLORS[:person_count]
    original_video_path = video_path

    # Optional trim — outpaint's frame-accurate re-encode pattern. The
    # trimmed clip becomes the canonical guide so the SAM3 mask and the
    # generation windows stay 1:1 with the frames actually used.
    trim_start = body.get("start_time")
    trim_end = body.get("end_time")
    if trim_start is not None and trim_end is not None:
        try:
            trim_start_f = float(trim_start)
            trim_end_f = float(trim_end)
            if trim_end_f - trim_start_f > 0.05 and trim_start_f >= 0:
                import subprocess
                trim_dir = os.path.join(os.getcwd(), "uploads")
                os.makedirs(trim_dir, exist_ok=True)
                trimmed_path = os.path.join(trim_dir, f"recast_trim_{uuid.uuid4().hex[:8]}.mp4")
                cmd = [
                    "ffmpeg", "-y", "-i", video_path,
                    "-ss", f"{trim_start_f:.3f}",
                    "-to", f"{trim_end_f:.3f}",
                    "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                    "-c:a", "aac", "-b:a", "192k",
                    trimmed_path,
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                if proc.returncode == 0 and os.path.isfile(trimmed_path):
                    print(f"[Recast] Trimmed source to [{trim_start_f:.2f}s, {trim_end_f:.2f}s] -> {os.path.basename(trimmed_path)}")
                    video_path = trimmed_path
                else:
                    print(f"[Recast] Trim failed (continuing with full clip): {proc.stderr[:200]}")
        except (TypeError, ValueError) as e:
            print(f"[Recast] Invalid trim params: {e}")

    try:
        import decord
        vr = decord.VideoReader(video_path)
        fps = vr.get_avg_fps() or 25
        total_frames = len(vr)
        probe_frame = vr[0].asnumpy()
        del vr
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read video: {e}")

    resolution_profile = _normalize_recast_resolution_profile(
        body.get("resolution_profile"),
    )
    recast_width, recast_height = _recast_resolution_for_source(
        probe_frame,
        resolution_profile,
    )
    recast_resolution = f"{recast_width}x{recast_height}"
    print(
        f"[Recast] Resolution profile {resolution_profile} -> "
        f"{recast_resolution}; model and step schedule remain independent."
    )
    recast_vram_gb = 0.0
    try:
        recast_vram_gb = float(
            _get_cached_hardware().get("gpu_vram_gb", 0.0),
        )
    except (TypeError, ValueError, AttributeError):
        recast_vram_gb = 0.0
    recast_window_size = _recast_window_size_for_profile(
        resolution_profile,
        recast_vram_gb,
    )
    if recast_window_size <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "704p Recast currently requires at least 16 GB of VRAM. "
                f"Detected {recast_vram_gb:.1f} GB; select 512p or 480p."
            ),
        )
    if resolution_profile == "704p":
        hardware_label = (
            f"{recast_vram_gb:.1f} GB VRAM"
            if recast_vram_gb > 0
            else "unknown VRAM"
        )
        print(
            f"[Recast] Adaptive 704p window: {hardware_label} -> "
            f"{recast_window_size} frames with 5-frame overlap."
        )

    requested_model_type = body.get("model_type") or _RECAST_FAST_MODEL_TYPE
    # Settings saved before the dedicated Recast model existed selected the
    # general I2V-accelerated SCAIL Fast model. Transparently migrate those
    # jobs to the dedicated, corrected native-replacement recipe instead of
    # recreating the incompatible hybrid that caused weak replacements.
    model_type = (
        _RECAST_FAST_MODEL_TYPE
        if requested_model_type == _RECAST_LEGACY_FAST_MODEL_TYPE
        else requested_model_type
    )
    if wgp.get_model_def(model_type) is None:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model_type}")
    recast_fast = model_type == _RECAST_FAST_MODEL_TYPE
    # Both Recast profiles use SCAIL-2's native replacement conditioning.
    # Fast differs only in the official I2V LightX operating point; the base
    # model remains available as the full 40-step comparison.
    recast_conditioning = "native_replace_fast" if recast_fast else "native_replace"
    duration_s = total_frames / fps if fps else 0

    # Cap the follow rate at 30fps (same rationale as the generate guard):
    # a 60fps source doubles frames and windows for no visible gain. wgp
    # resamples the guide (and the SAM3 mask video, which carries the
    # source fps) to the forced integer rate.
    recast_force_fps = "control"
    gen_frames = total_frames
    if fps and float(fps) > 30.5:
        recast_force_fps = "30"
        gen_frames = int(round(duration_s * 30.0))
        print(f"[Recast] fps cap: {float(fps):.6g}fps source → generating at 30fps ({gen_frames} frames)")

    raw_recast_prompt = str(body.get("prompt") or "").strip()
    try:
        prompt = _build_recast_prompt(
            raw_recast_prompt, person_count, enhance=enhance_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    activated_loras, loras_multipliers, use_relighting = (
        _normalize_recast_lora_settings(
            body.get("activated_loras"),
            body.get("loras_multipliers"),
            use_relighting,
        )
    )
    if use_relighting:
        relighting_index = next(
            index
            for index, name in enumerate(activated_loras)
            if str(name).replace("\\", "/").rsplit("/", 1)[-1].casefold()
            == _RECAST_RELIGHTING_LORA_FILENAME.casefold()
        )
        relighting_weight = loras_multipliers.split()[relighting_index]
        print(
            "[Recast] SCAIL-2 Relighting LoRA enabled with single-phase "
            f"weight {relighting_weight}."
        )

    serialized_mappings = [
        {
            "id": mapping["id"],
            "target": mapping["target"],
            "ref_image_path": mapping["ref_image_path"],
            "additional_ref_image_paths": list(
                mapping.get("additional_ref_image_paths", []),
            ),
            "reference_aligned_to_source": mapping[
                "reference_aligned_to_source"
            ],
        }
        for mapping in character_mappings
    ]
    initial_reference_paths = [
        path
        for mapping in character_mappings
        for path in [
            mapping["ref_image_path"],
            *mapping.get("additional_ref_image_paths", []),
        ]
    ]
    inference_steps = _normalize_scail2_inference_steps(
        body.get("num_inference_steps"),
        8 if recast_fast else 40,
    )
    # The Fast LightX recipe is CFG-distilled, but its denoising step count is
    # intentionally user-adjustable for quality/speed experiments.
    guidance_scale = (
        1.0
        if recast_fast
        else _normalize_scail2_guidance_scale(
            body.get("guidance_scale"),
            5.0,
        )
    )
    print(
        f"[Recast] Sampling: {inference_steps} steps, "
        f"guidance {guidance_scale:g} "
        f"({'Fast distilled' if recast_fast else 'HQ'})."
    )

    gen_params = {
        "prompt": prompt,
        "model_type": model_type,
        "negative_prompt": body.get("negative_prompt", ""),
        "seed": body.get("seed", -1),
        "activated_loras": activated_loras,
        "loras_multipliers": loras_multipliers,
        "guidance_scale": guidance_scale,
        "num_inference_steps": inference_steps,
        "flow_shift": 1 if recast_fast else 3,
        "sample_solver": "unipc",
        "generation_mode": "video",
        "edit_sub_mode": "recast",
        # The 0 is SCAIL-2's native Replace 1-5 People flag. The reference is
        # identity conditioning only; it must never become the output canvas.
        "video_prompt_type": f"V0{person_count}AI",
        "image_prompt_type": "",
        "video_guide": video_path,
        # video_mask is filled by the detection pre-step below.
        "image_refs": initial_reference_paths,
        "video_length": gen_frames,
        "_duration_seconds": duration_s,
        "resolution": recast_resolution,
        "force_fps": recast_force_fps,
        "audio_prompt_type": "R",
        "sliding_window_size": recast_window_size,
        "sliding_window_overlap": 5,
        "settings_version": 2.57,
        "custom_settings": {
            "image_ref_keyword_content": "human character",
            "scail2_animate_preprocessing": "raw",
            "scail2_recast_conditioning": "native_replace",
            # The detection pre-step prepares exact RGB/mask pairs.  Runtime
            # isolation stays off so it cannot harden the already-preserved
            # soft alpha edges a second time.
            "scail2_primary_reference_people": 1,
            "scail2_isolate_reference_background": False,
            "scail2_reference_alpha_path": "",
            # Recast gives CLIP the untouched primary image. When isolation is
            # requested, SCAIL-2 also encodes that original through the VAE and
            # retains its latent features inside the semantic subject mask;
            # the neutral reference remains outside the subject.
            "scail2_clip_reference_path": "",
            "scail2_identity_latent_isolation": isolate_reference,
            # Zero keeps the identity-preserving VAE blend on the ordinary
            # primary target reference. Native group preservation moves that
            # target reference to slot one and updates this index accordingly.
            "scail2_identity_latent_reference_index": 0,
            # Generate a disposable reverse-motion pre-roll from the first
            # control/mask frames, then remove it before output assembly.
            "scail2_recast_warmup_frames": _RECAST_WARMUP_FRAMES,
            # Establish identity and scene with all prepared references in
            # window one. Continuations use the primary SCAIL reference plus
            # clean generated overlap to avoid cumulative multi-ref artifacts.
            "scail2_primary_only_continuations": True,
        },
        # UI restore keys for the gallery Edits filter + Load Settings.
        "edit_video_path": original_video_path,
        "edit_start_time": float(trim_start) if trim_start is not None else 0.0,
        "edit_end_time": float(trim_end) if trim_end is not None else duration_s,
        "edit_recast_target": target,
        "edit_recast_person_count": person_count,
        "edit_recast_character_mappings": serialized_mappings,
        "edit_recast_conditioning_people": person_count,
        "edit_recast_ref_path": ref_image_path,
        "edit_recast_ref_aligned": reference_aligned_to_source,
        "edit_recast_isolate_reference": isolate_reference,
        "edit_recast_auto_face_detail": auto_face_detail,
        "edit_recast_enhance_prompt": enhance_prompt,
        "edit_recast_raw_prompt": raw_recast_prompt,
        "edit_recast_protect_bystanders": protect_bystanders,
        "edit_recast_preserve_bystanders": preserve_bystanders,
        "edit_recast_use_relighting": use_relighting,
        "edit_recast_resolution_profile": resolution_profile,
        "edit_recast_output_resolution": [recast_width, recast_height],
        "edit_recast_sliding_window_size": recast_window_size,
        "edit_recast_conditioning": recast_conditioning,
        "edit_recast_warmup_frames": _RECAST_WARMUP_FRAMES,
        # Consumed by _run_generation's deterministic Recast finishing pass.
        "_recast_protect_bystanders": protect_bystanders,
        "_recast_source_video": video_path,
    }

    workspace_name = workspace or _get_active_workspace()
    job_out_dir = _workspace_dir(workspace_name)
    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
        "phase": "", "message": "Queued (recast)", "created_at": time.time(),
        "params": gen_params, "output_files": [], "error": None,
        "workspace": workspace_name, "out_dir": job_out_dir,
    }
    _register_manual_generation_job(job)
    initial_probe_frame = probe_frame

    def _run_recast():
        abort_state = {"abort": False}
        shot_temp_dir = None
        shot_final_out_dir = None
        # The timeline-aware branch selects a later frame and therefore
        # reassigns ``probe_frame`` below. Initialize the resulting local from
        # the endpoint's decoded first frame before either branch reads it.
        probe_frame = initial_probe_frame
        try:
            # The SAM3 tracking pass is GPU work. Take the generation lock
            # for the detection phase so queued recasts don't run their
            # propagate_in_video passes concurrently with (and on top of)
            # the active job's denoising — user report: several queued
            # recasts all tracked at once and everything crawled. The lock
            # is released before _run_generation, which re-acquires it for
            # the generation phase; a waiting job may slip its detection in
            # between, but everything stays strictly one-GPU-task-at-a-time.
            with _coordinated_generation_slot(
                job, description="HocusPocus Lab GPU preparation · recast",
            ) as acquired:
                if not acquired:
                    return
                if not try_start(
                    job,
                    phase="Detecting target",
                    message=f"Finding {person_count} '{target}' subject{'s' if person_count != 1 else ''} in the video...",
                ):
                    return
                if not register_abort_state(
                    job, job_id, _active_gen_states, abort_state,
                ):
                    return
                from shared import magic_mask
                mapped_tracking = None
                mapping_anchors = None
                native_reference_frame_index = 0
                scene_anchor_frame = probe_frame
                scene_anchor_mask = None
                shot_aware_recast_required = False
                cast_transition_count = 0
                if explicit_character_mappings:
                    tracking_progress = {"bucket": -1}

                    def _abort_mapped_tracking():
                        if is_cancel_requested(job):
                            raise InterruptedError(
                                "Recast character tracking was cancelled",
                            )

                    def _mapped_tracking_progress(
                        mapping_index, mapping_total, done, total,
                    ):
                        percent = min(
                            100,
                            max(
                                0,
                                int(round(
                                    100
                                    * (
                                        mapping_index
                                        + float(done) / max(1, total)
                                    )
                                    / max(1, mapping_total)
                                )),
                            ),
                        )
                        bucket = percent // 5
                        if bucket == tracking_progress["bucket"]:
                            return
                        tracking_progress["bucket"] = bucket
                        if not update_job(
                            job,
                            phase="Tracking timeline",
                            message=(
                                "Finding mapped characters across shots... "
                                f"{percent}%"
                            ),
                        ):
                            raise InterruptedError(
                                "Recast character tracking was cancelled",
                            )

                    try:
                        mapped_tracking = _build_recast_character_mask(
                            video_path,
                            character_mappings,
                            os.path.join(os.getcwd(), "uploads"),
                            progress_callback=_mapped_tracking_progress,
                            abort_callback=_abort_mapped_tracking,
                        )
                    except InterruptedError:
                        return

                    tracking_fps = float(
                        mapped_tracking.get("fps") or fps or 25.0
                    )
                    cast_transition_hold_frames = max(
                        4,
                        min(
                            12,
                            int(round(max(1.0, tracking_fps) * 0.2)),
                        ),
                    )
                    cast_preview = _plan_recast_shot_segments(
                        mapped_tracking["mapping_masks"],
                        mapped_tracking["shot_ranges"],
                        split_cast_transitions=True,
                        min_cast_run_frames=cast_transition_hold_frames,
                    )
                    cast_transition_count = max(
                        0,
                        len(cast_preview) - int(mapped_tracking["shot_count"]),
                    )
                    shot_aware_recast_required = (
                        int(mapped_tracking["shot_count"]) > 1
                        or cast_transition_count > 0
                    )
                    common_index = mapped_tracking["common_frame_index"]
                    scene_index = mapped_tracking["scene_anchor_index"]
                    native_reference_frame_index = (
                        common_index
                        if common_index is not None
                        else scene_index
                    )
                    probe_frame = mapped_tracking["source_frames"][
                        native_reference_frame_index
                    ]
                    probe_mask = mapped_tracking["mask_frames"][
                        native_reference_frame_index
                    ]
                    scene_anchor_frame = mapped_tracking["source_frames"][
                        scene_index
                    ]
                    scene_anchor_mask = mapped_tracking["mask_frames"][
                        scene_index
                    ]
                    mapping_anchors = []
                    for summary in mapped_tracking["mapping_summaries"]:
                        anchor_index = summary["anchor_frame_index"]
                        mapping_anchors.append({
                            "frame_index": anchor_index,
                            "source_frame": mapped_tracking["source_frames"][
                                anchor_index
                            ],
                            "source_mask": mapped_tracking["mask_frames"][
                                anchor_index
                            ],
                        })
                    job["params"]["edit_recast_timeline_anchors"] = [
                        dict(summary)
                        for summary in mapped_tracking["mapping_summaries"]
                    ]
                    job["params"]["edit_recast_recovered_shots"] = [
                        dict(item)
                        for item in mapped_tracking.get(
                            "recovered_shots",
                            [],
                        )
                    ]
                    job["params"]["edit_recast_shot_ranges"] = [
                        list(bounds)
                        for bounds in mapped_tracking["shot_ranges"]
                    ]
                    job["params"]["edit_recast_shot_count"] = (
                        mapped_tracking["shot_count"]
                    )
                    job["params"]["edit_recast_common_frame_index"] = (
                        common_index
                    )
                    job["params"]["edit_recast_timeline_aware"] = (
                        mapped_tracking["timeline_aware"]
                    )
                    job["params"]["edit_recast_cast_transition_count"] = (
                        cast_transition_count
                    )
                    print(
                        "[Recast] Timeline discovery mapped "
                        f"{person_count} character"
                        f"{'s' if person_count != 1 else ''} across "
                        f"{mapped_tracking['shot_count']} shot"
                        f"{'s' if mapped_tracking['shot_count'] != 1 else ''}; "
                        + (
                            f"shared anchor frame={common_index}."
                            if common_index is not None
                            else "no shared frame; using per-character anchors."
                        )
                    )
                    if cast_transition_count:
                        print(
                            "[Recast] Found "
                            f"{cast_transition_count} stable cast change"
                            f"{'s' if cast_transition_count != 1 else ''} "
                            "inside a camera shot; hidden identity pre-rolls "
                            "will initialize late entrants without splitting "
                            "the visible shot."
                        )
                    matched_people = person_count
                else:
                    probe_mask = magic_mask.generate_keyword_masks(
                        probe_frame[None], target, no_hole=True,
                        colorize_objects=True,
                        color_palette=mask_colors,
                        max_colored_objects=person_count,
                    )[0]
                    matched_people = _count_recast_mask_people(
                        probe_mask, mask_colors,
                    )
                    scene_anchor_mask = probe_mask
                if matched_people < person_count:
                    finish_job(
                        job,
                        "failed",
                        error=(
                            f"Found {matched_people} of {person_count} requested "
                            f"'{target}' subjects in the first frame. Try "
                            "another description, lower the person count, or "
                            "adjust the trim start."
                        ),
                        message="Not enough targets found",
                    )
                    return
                native_group_supported = (
                    not explicit_character_mappings
                    or (
                        not shot_aware_recast_required
                        and mapped_tracking["shot_count"] == 1
                        and mapped_tracking["common_frame_index"] is not None
                    )
                )
                map_native_bystanders = (
                    preserve_bystanders
                    and native_group_supported
                    and _recast_probe_needs_bystander_tracking(
                        probe_frame,
                        probe_mask,
                        person_count,
                    )
                )
                job["params"]["edit_recast_bystander_tracking"] = (
                    "full"
                    if map_native_bystanders
                    else (
                        "timeline_scene"
                        if preserve_bystanders and not native_group_supported
                        else "not_needed"
                    )
                )
                if preserve_bystanders and not map_native_bystanders:
                    if not native_group_supported:
                        print(
                            "[Recast] Multi-shot/separate-appearance mapping "
                            "will preserve surrounding people with per-window "
                            "source-scene anchors instead of one contradictory "
                            "group reference."
                        )
                    else:
                        print(
                            "[Recast] Anchor-frame probe found no additional "
                            "bystanders; skipping the second full SAM3 pass."
                        )
                if is_cancel_requested(job):
                    return
                if not update_job(
                    job,
                    phase="Preparing references",
                    message="Preparing exact SCAIL-2 reference crops and masks...",
                ):
                    return
                prepared_refs = _prepare_recast_reference_conditioning(
                    character_mappings,
                    probe_mask,
                    os.path.join(os.getcwd(), "uploads"),
                    job_id,
                    isolate_reference=isolate_reference,
                    selected_count=person_count,
                    auto_face_detail=auto_face_detail,
                    source_frame=probe_frame,
                    reference_canvas=(recast_width, recast_height),
                    mapping_anchors=mapping_anchors,
                )
                job["params"]["image_refs"] = prepared_refs["image_refs"]
                job["params"]["custom_settings"][
                    "scail2_reference_mask_path"
                ] = prepared_refs["primary_mask"]
                job["params"]["custom_settings"][
                    "scail2_additional_reference_mask_paths"
                ] = prepared_refs["additional_masks"]
                job["params"]["custom_settings"][
                    "scail2_reference_expected_colors"
                ] = prepared_refs["expected_colors"]
                job["params"]["custom_settings"][
                    "scail2_clip_reference_path"
                ] = prepared_refs["clip_identity_ref"]
                target_group_reference = None
                if explicit_character_mappings and person_count > 1:
                    target_group_reference = (
                        _build_recast_target_group_reference(
                            prepared_refs,
                            os.path.join(os.getcwd(), "uploads"),
                            job_id,
                            person_count,
                            shared_source_frame=(
                                probe_frame
                                if common_index is not None
                                else None
                            ),
                            shared_semantic_mask=(
                                probe_mask
                                if common_index is not None
                                else None
                            ),
                        )
                    )
                    # SCAIL-2 was trained to map several semantic colors from
                    # one primary multi-person reference. Keep the individual
                    # full/detail views as supporting evidence rather than
                    # asking the experimental multi-reference path to decide
                    # which unrelated identity owns each color.
                    job["params"]["image_refs"] = [
                        target_group_reference["image"],
                        *prepared_refs["image_refs"],
                    ]
                    job["params"]["custom_settings"][
                        "scail2_reference_mask_path"
                    ] = target_group_reference["mask"]
                    job["params"]["custom_settings"][
                        "scail2_additional_reference_mask_paths"
                    ] = [
                        prepared_refs["primary_mask"],
                        *prepared_refs["additional_masks"],
                    ]
                    job["params"]["custom_settings"][
                        "scail2_reference_expected_colors"
                    ] = [
                        None,
                        *prepared_refs["expected_colors"],
                    ]
                    job["params"]["custom_settings"][
                        "scail2_primary_reference_people"
                    ] = person_count
                    job["params"]["custom_settings"][
                        "scail2_identity_latent_reference_index"
                    ] = 1
                    job["params"]["edit_recast_cast_reference"] = (
                        target_group_reference["image"]
                    )
                    job["params"]["edit_recast_cast_mask"] = (
                        target_group_reference["mask"]
                    )
                    job["params"]["edit_recast_cast_mode"] = (
                        target_group_reference["mode"]
                    )
                    job["params"]["edit_recast_conditioning_people"] = (
                        person_count
                    )
                    print(
                        "[Recast] Built one native color-mapped cast "
                        f"reference for {person_count} characters "
                        f"({target_group_reference['mode']})."
                    )
                job["params"]["edit_recast_prepared_refs"] = list(
                    prepared_refs["image_refs"],
                )
                job["params"]["edit_recast_clip_identity_ref"] = (
                    prepared_refs["clip_identity_ref"]
                )
                job["params"]["edit_recast_auto_face_detail_refs"] = list(
                    prepared_refs["auto_face_detail_refs"],
                )
                job["params"]["edit_recast_reference_canvas"] = list(
                    prepared_refs["reference_canvas"],
                )
                source_scene_reference = None

                def _ensure_source_scene_reference(reason):
                    nonlocal source_scene_reference
                    if source_scene_reference is not None:
                        return source_scene_reference
                    source_scene_reference = (
                        _enable_recast_dynamic_source_scene_reference(
                            job["params"],
                            scene_anchor_frame,
                            scene_anchor_mask,
                            person_count,
                            os.path.join(os.getcwd(), "uploads"),
                            job_id,
                        )
                    )
                    job["params"][
                        "edit_recast_source_scene_reference_reason"
                    ] = reason
                    if (
                        explicit_character_mappings
                        and mapped_tracking["timeline_aware"]
                    ):
                        job["params"]["custom_settings"][
                            "scail2_timeline_source_scene_reference"
                        ] = True
                        job["params"][
                            "edit_recast_source_scene_conditioning"
                        ] = "per_window_timeline_reference"
                    print(
                        "[Recast] Enabled source-scene anchoring "
                        f"({reason}; hidden="
                        f"{source_scene_reference['hidden_fraction']:.1%}, "
                        f"margin={source_scene_reference['expansion_pixels']}px)."
                    )
                    return source_scene_reference

                print(
                    "[Recast] Prepared "
                    f"{len(prepared_refs['image_refs'])} exact reference "
                    "view(s) with paired semantic masks and an identity-first "
                    "primary VAE/CLIP image"
                    + (
                        f", including {len(prepared_refs['auto_face_detail_refs'])} "
                        "automatic face-detail view(s)."
                        if prepared_refs["auto_face_detail_refs"]
                        else "."
                    )
                )
                if explicit_character_mappings:
                    mask_path = mapped_tracking["video_mask"]
                else:
                    if not update_job(
                        job,
                        phase="Tracking targets",
                        message=(
                            f"Tracking '{target}' across "
                            f"{total_frames} frames..."
                        ),
                    ):
                        return
                    mask_path, _ = magic_mask.generate_video_mask(
                        video_path, target,
                        colorize_objects=True,
                        color_palette=mask_colors,
                        max_colored_objects=person_count,
                        background_color=(255, 255, 255),
                        output_dir=os.path.join(os.getcwd(), "uploads"),
                    )
                if is_cancel_requested(job):
                    return
                job["params"]["video_mask"] = mask_path
                if not map_native_bystanders:
                    _ensure_source_scene_reference(
                        "no separate bystander pass needed",
                    )
                if map_native_bystanders:
                    if not update_job(
                        job,
                        message="Mapping the other people for native preservation...",
                        phase="Mapping surrounding people",
                    ):
                        return

                    mapping_progress = {"bucket": -1}

                    def _native_people_progress(done, total):
                        percent = min(
                            100,
                            max(0, int(round(100 * float(done) / max(1, total)))),
                        )
                        bucket = percent // 5
                        if bucket == mapping_progress["bucket"]:
                            return
                        mapping_progress["bucket"] = bucket
                        if not update_job(
                            job,
                            message=f"Mapping the other people... {percent}%",
                            phase="Mapping surrounding people",
                        ):
                            raise InterruptedError("Recast bystander mapping was cancelled")

                    try:
                        native_people = _build_recast_native_people_conditioning(
                            video_path,
                            mask_path,
                            person_count,
                            os.path.join(os.getcwd(), "uploads"),
                            job_id,
                            target_references=prepared_refs[
                                "primary_target_refs"
                            ],
                            progress_callback=_native_people_progress,
                            reference_frame_index=(
                                native_reference_frame_index
                            ),
                        )
                    except InterruptedError:
                        return
                    except Exception as native_error:
                        # Native preservation is an enhancement. If broad
                        # person mapping is ambiguous, retain the known-good
                        # target-only Recast instead of failing the whole job.
                        print(
                            "[Recast] Native bystander conditioning unavailable; "
                            f"continuing target-only: {native_error}"
                        )
                        traceback.print_exc()
                        _ensure_source_scene_reference(
                            "native bystander mapping unavailable",
                        )
                    else:
                        if is_cancel_requested(job):
                            return
                        if native_people["reference_image"]:
                            job["params"]["video_mask"] = native_people["video_mask"]
                            target_image_refs = list(
                                prepared_refs["image_refs"],
                            )
                            target_mask_paths = [
                                prepared_refs["primary_mask"],
                                *prepared_refs["additional_masks"],
                            ]
                            target_expected_colors = list(
                                prepared_refs["expected_colors"],
                            )
                            # The color-mapped group is now the primary
                            # reference adjacent to the video timeline. Large
                            # target and face-detail views remain as supporting
                            # references, so bystander identity no longer
                            # arrives through a contradictory target-free frame.
                            job["params"]["image_refs"] = [
                                native_people["reference_image"],
                                *target_image_refs,
                            ]
                            job["params"]["custom_settings"][
                                "scail2_reference_mask_path"
                            ] = native_people["reference_mask"]
                            job["params"]["custom_settings"][
                                "scail2_additional_reference_mask_paths"
                            ] = target_mask_paths
                            job["params"]["custom_settings"][
                                "scail2_reference_expected_colors"
                            ] = [None, *target_expected_colors]
                            job["params"]["custom_settings"][
                                "scail2_primary_reference_people"
                            ] = native_people["conditioning_count"]
                            job["params"]["custom_settings"][
                                "scail2_identity_latent_reference_index"
                            ] = 1
                            job["params"]["video_prompt_type"] = (
                                f"V0{native_people['conditioning_count']}AI"
                            )
                            job["params"]["edit_recast_conditioning_people"] = (
                                native_people["conditioning_count"]
                            )
                            job["params"]["edit_recast_group_reference"] = (
                                native_people["reference_image"]
                            )
                            job["params"]["edit_recast_group_mask"] = (
                                native_people["reference_mask"]
                            )
                            print(
                                "[Recast] Native group conditioning mapped "
                                f"{native_people['conditioning_count']} people "
                                f"(targets={person_count}, "
                                f"bystanders={len(native_people['assignments'])})"
                            )
                        else:
                            _ensure_source_scene_reference(
                                "no additional bystanders survived full tracking",
                            )
                            print(
                                "[Recast] No additional visible bystanders fit "
                                "the native five-person conditioning limit."
                            )

                if (
                    explicit_character_mappings
                    and shot_aware_recast_required
                ):
                    if not update_job(
                        job,
                        phase="Preparing cast-aware segments",
                        message=(
                            "Preparing shot and cast-specific character "
                            "references..."
                        ),
                    ):
                        return
                    import secrets
                    import shutil
                    import tempfile

                    try:
                        resolved_seed = int(job["params"].get("seed", -1))
                    except (TypeError, ValueError):
                        resolved_seed = -1
                    if resolved_seed < 0:
                        resolved_seed = secrets.randbelow(1_000_000_000)
                    job["params"]["seed"] = resolved_seed

                    generation_fps = (
                        30.0
                        if recast_force_fps == "30"
                        else float(mapped_tracking.get("fps") or fps or 25.0)
                    )
                    try:
                        minimum_frames, _frame_step, latent_size = (
                            wgp.get_model_min_frames_and_step(model_type)
                        )
                    except Exception:
                        minimum_frames, latent_size = 5, 4

                    shot_temp_dir = tempfile.mkdtemp(
                        prefix="maestro-recast-shots-",
                    )
                    try:
                        shot_manifest = _build_recast_shot_manifest(
                            job["params"],
                            mapped_tracking,
                            prepared_refs,
                            shot_temp_dir,
                            job_id,
                            reference_canvas=(
                                recast_width,
                                recast_height,
                            ),
                            target_frame_count=gen_frames,
                            generation_fps=generation_fps,
                            minimum_frames=minimum_frames,
                            latent_size=latent_size,
                        )
                    except Exception:
                        shutil.rmtree(
                            shot_temp_dir,
                            ignore_errors=True,
                        )
                        raise

                    final_out_dir = job.get("out_dir") or _workspace_dir(
                        workspace_name,
                    )
                    shot_final_out_dir = final_out_dir
                    job["params"].update({
                        "_defer_output_publication": True,
                        "_recast_shot_manifest": shot_manifest["tasks"],
                        "_recast_shot_temp_dir": shot_temp_dir,
                        "_recast_final_out_dir": final_out_dir,
                        "_recast_shot_bundle": {
                            "shots": shot_manifest["shots"],
                            "published_shots": shot_manifest[
                                "published_shots"
                            ],
                            "frame_count": shot_manifest["frame_count"],
                            "fps": shot_manifest["fps"],
                            "camera_shot_count": shot_manifest[
                                "camera_shot_count"
                            ],
                            "cast_transition_count": shot_manifest[
                                "cast_transition_count"
                            ],
                            "resolved_seed": resolved_seed,
                        },
                        "edit_recast_shot_aware": True,
                        "edit_recast_shot_plan": shot_manifest[
                            "published_shots"
                        ],
                    })
                    if job["params"].get("_recast_protect_bystanders"):
                        print(
                            "[Recast] Strict pixel-lock fallback is disabled "
                            "for shot-aware generation; native shot references "
                            "preserve the surrounding scene."
                        )
                        job["params"]["_recast_protect_bystanders"] = False
                    # Generated shots and their references are disposable.
                    # Point the normal task engine at the private directory;
                    # the finishing worker publishes only the final join.
                    job["out_dir"] = shot_temp_dir
                    generated_count = len(shot_manifest["tasks"])
                    passthrough_count = sum(
                        1
                        for shot in shot_manifest["shots"]
                        if shot["mode"] == "passthrough"
                    )
                    print(
                        "[Recast] Shot-aware plan prepared "
                        f"{len(shot_manifest['shots'])} generation segments "
                        f"from {shot_manifest['camera_shot_count']} camera "
                        "shot"
                        f"{'s' if shot_manifest['camera_shot_count'] != 1 else ''} "
                        f"with {shot_manifest['cast_transition_count']} stable "
                        "cast transition"
                        f"{'s' if shot_manifest['cast_transition_count'] != 1 else ''} "
                        f"({generated_count} generated, "
                        f"{passthrough_count} source passthrough), "
                        f"{shot_manifest['frame_count']} exact output frames "
                        f"at {shot_manifest['fps']:.6g}fps."
                    )
        except Exception as e:
            traceback.print_exc()
            if shot_temp_dir and os.path.isdir(shot_temp_dir):
                import shutil

                shutil.rmtree(shot_temp_dir, ignore_errors=True)
                if shot_final_out_dir:
                    job["out_dir"] = shot_final_out_dir
            finish_job(
                job,
                "failed",
                error=f"Target detection failed: {e}",
                message="Detection failed",
            )
            return
        finally:
            if abort_state is not None:
                unregister_abort_state(job_id, _active_gen_states, abort_state)

        if not try_requeue(job, message="Queued (recast)", phase=""):
            if shot_temp_dir and os.path.isdir(shot_temp_dir):
                import shutil

                shutil.rmtree(shot_temp_dir, ignore_errors=True)
                if shot_final_out_dir:
                    job["out_dir"] = shot_final_out_dir
            return
        if job["params"].get("_recast_shot_manifest"):
            _run_recast_shot_generation(job_id)
        else:
            _run_generation(job_id)

    thread = (
        threading.Thread(target=_run_generation, args=(job_id,), daemon=False)
        if execution_mode.policy().simulated
        else threading.Thread(target=_run_recast, daemon=False)
    )
    thread.start()

    return {
        "job_id": job_id,
        "status": "queued",
        "frames": total_frames,
        "target": target,
        "person_count": person_count,
        "resolution_profile": resolution_profile,
        "resolution": recast_resolution,
        "sliding_window_size": recast_window_size,
        "num_inference_steps": inference_steps,
        "guidance_scale": guidance_scale,
        **_generation_job_acceptance(job),
    }


# Outpaint (planning, run, POST /api/v1/outpaint) and blend (run, POST /api/v1/blend). Each module takes the launch
# objects it reads once, here. The generation worker is defined further down, so the modules get the retake routes'
# forwarder, named for the thread.
from services.outpaint_planning import (
    _OUTPAINT_PIXEL_BUDGETS, _OUTPAINT_SINGLE_STAGE_REFERENCE_FRAMES, _OUTPAINT_SINGLE_STAGE_REFERENCE_PIXELS,
    _build_outpaint_shot_filter, _build_outpaint_shot_manifest, _cap_outpaint_single_stage_window,
    _detect_outpaint_video_shot_ranges, _format_outpaint_percentage, _resolve_ltx2_outpaint_reference_model,
    _resolve_outpaint_canvas_geometry, _resolve_outpaint_sampling, _resolve_outpaint_video_timing,
    _write_outpaint_shot_guide, bind as _bind_outpaint_planning,
)
from services.outpaint_run import (
    _prepare_and_run_outpaint, _run_outpaint_shot_generation, _write_outpaint_shot_aware_sidecar,
    bind as _bind_outpaint_run,
)
from routers.outpaint import create_outpaint_router, outpaint_endpoint

_bind_outpaint_planning(
    wgp=wgp, detect_recast_shot_ranges=_detect_recast_shot_ranges,
    quantize_recast_shot_frame_count=_quantize_recast_shot_frame_count,
)
_bind_outpaint_run(
    wgp=wgp, jobs=_jobs, active_gen_states=_active_gen_states, coordinated_generation_slot=_coordinated_generation_slot,
    workspace_dir=_workspace_dir, run_generation=_forward_studio_run_generation,
)
api.include_router(create_outpaint_router(
    wgp=wgp, get_active_workspace=_get_active_workspace, workspace_dir=_workspace_dir,
    register_manual_generation_job=_register_manual_generation_job,
    generation_job_acceptance=_generation_job_acceptance, run_generation=_forward_studio_run_generation,
))


from services.blend_run import _run_blend_generation, bind as _bind_blend_run
from routers.blend import blend_endpoint, create_blend_router

_bind_blend_run(
    jobs=_jobs, active_gen_states=_active_gen_states, workspace_dir=_workspace_dir,
    run_generation=_forward_studio_run_generation,
)
api.include_router(create_blend_router(
    get_active_workspace=_get_active_workspace, workspace_dir=_workspace_dir,
    register_manual_generation_job=_register_manual_generation_job,
    generation_job_acceptance=_generation_job_acceptance, run_generation=_forward_studio_run_generation,
))


from routers.studio_segmentation import create_studio_segmentation_router

api.include_router(create_studio_segmentation_router())
from services.studio_segmentation import sam_status_endpoint, segment_preview_endpoint


from routers.studio_edit_requests import create_studio_inpaint_router

api.include_router(create_studio_inpaint_router(
    register_manual_generation_job=_register_manual_generation_job,
    generation_job_acceptance=_generation_job_acceptance,
    get_active_workspace=_get_active_workspace,
    workspace_dir=_workspace_dir,
    # Same forwarder as retake and edit-anything. The thread name stays.
    run_generation=_forward_studio_run_generation,
))
from services.studio_edit_requests import inpaint_endpoint


# The hardware probe (for total VRAM) is cached at module level — the
# answer doesn't change at runtime and detect_hardware() touches torch
# which we'd rather not call per-job.
_cached_hardware: dict | None = None


def _get_cached_hardware() -> dict:
    global _cached_hardware
    if _cached_hardware is None:
        try:
            from services.hardware_detect import detect_hardware
            _cached_hardware = detect_hardware()
        except Exception as e:
            print(f"[VRAM] hardware probe failed ({e}); per-job adjustment disabled")
            _cached_hardware = {"gpu_vram_gb": 0.0}
    return _cached_hardware


# Post-processing passes the generation worker calls by these names: the per-job
# VRAM coefficient, film grain, spatial upsampling, chunked FlashVSR and sound
# effects. Each module receives the launch objects it reads once, here.
from services.generation_coefficients import (
    _apply_per_job_coefficient,
    _restore_base_coefficient,
    bind as _bind_generation_coefficients,
)
from services.generation_flashvsr import _chunked_flashvsr_upscale, bind as _bind_generation_flashvsr
from services.generation_postprocess import (
    _apply_film_grain_to_file,
    _apply_spatial_upsampling_to_file,
    bind as _bind_generation_postprocess,
)
from services.generation_sfx import _run_sfx_generation, bind as _bind_generation_sfx

_bind_generation_coefficients(wgp=wgp, get_cached_hardware=_get_cached_hardware)
_bind_generation_flashvsr(wgp=wgp)
_bind_generation_postprocess(wgp=wgp)
_bind_generation_sfx(
    wgp=wgp,
    task_registry=_task_registry,
    publish_generation_sidecar_for_studio_job=_publish_generation_sidecar_for_studio_job,
)


# ============================================================================
# Standalone post-processing "Tools" — apply FlashVSR upscale or SeedVC
# revoice to ANY existing clip (a gallery output or an uploaded file),
# independent of a generation. These reuse the job plumbing (_jobs /
# _gen_lock / /status / /cancel) but run a thin post-processing path instead
# of the full model pipeline. (edit_video in wgp.py does the same work but is
# coupled to the Gradio gen state — send_cmd / get_gen_info / file_list — so
# we extract just the load -> upscale -> save -> remux core here.)
# See memory/project_tools_postprocessing.md.
# ============================================================================


from routers.tools import (
    create_tools_post_router,
    _resolve_tool_clip_path,
    _resolve_tool_source,
    _run_tool_revoice,
    _run_tool_upscale,
    _tool_asset_roots,
    _tool_source_kind_from_name,
    _upscale_tool_image,
    _write_tool_sidecar,
)
api.include_router(create_tools_post_router(
    wgp=wgp,
    _jobs=_jobs,
    _active_gen_states=_active_gen_states,
    _list_workspaces=_list_workspaces,
    _workspace_dir=_workspace_dir,
    _get_active_workspace=_get_active_workspace,
    _coordinated_generation_slot=_coordinated_generation_slot,
    try_start=try_start,
    register_abort_state=register_abort_state,
    unregister_abort_state=unregister_abort_state,
    is_cancel_requested=is_cancel_requested,
    update_job=update_job,
    finish_job=finish_job,
    acknowledge_cancel=acknowledge_cancel,
    record_job_outputs=record_job_outputs,
    _chunked_flashvsr_upscale=_chunked_flashvsr_upscale,
    _register_manual_generation_job=_register_manual_generation_job,
    _generation_job_acceptance=_generation_job_acceptance,
    # The real worker is defined just below this mount. The lambda looks it up
    # when a simulated upscale or revoice actually runs.
    _run_generation=lambda job_id, *, finalize=True: _run_generation(job_id, finalize=finalize),
    _resolve_request_media_path=_resolve_request_media_path,
))
# MCP and the image-command runtime call these same objects.
tools_upscale = create_tools_post_router.tools_upscale
tools_revoice = create_tools_post_router.tools_revoice




def _run_simulated_generation(job: dict, *, finalize: bool) -> bool:
    """Replace only expensive inference while retaining the real job path."""
    params = job.get("params") if isinstance(job.get("params"), dict) else {}

    def publish_progress(message: str, value: int, step: int, total: int) -> None:
        update_job(
            job,
            message=message,
            progress=value,
            step=step,
            total_steps=total,
            phase="Simulated inference",
        )

    try:
        generated_path = execution_mode.create_artifact(
            params,
            job["out_dir"],
            str(job["id"]),
            progress=publish_progress,
            cancelled=lambda: is_cancel_requested(job),
        )
    except InterruptedError:
        # Cancellation is settled by _run_generation's finally block, after
        # the simulated executor has stopped and shared cleanup has completed.
        return False
    output_name = os.path.basename(generated_path)
    record_job_outputs(job, [output_name])
    tool_job = str(params.get("_non_durable_tool") or "") in {"upscale", "revoice"}
    sidecar_params = params
    if tool_job:
        # Simulation still exercises the real queue/task/manifest path, but
        # host filesystem paths and uploaded voice references must never enter
        # the durable sidecar.
        sidecar_params = {
            key: value
            for key, value in params.items()
            if not str(key).startswith("_")
            and key not in {"source_path", "video_path", "voice_ref_paths"}
        }
    sidecar = {
        "params": sidecar_params,
        "generation_mode": params.get("generation_mode"),
        "tool": "tools" if tool_job else None,
        "capability": params.get("capability") if tool_job else None,
        "job_id": job.get("id"),
        "task_id": job.get("task_id"),
        "root_task_id": job.get("root_task_id") or job.get("task_id"),
        "output_filename": output_name,
        "generation_time": 0,
        "created_at": time.time(),
        "simulated": True,
        "execution_mode": "simulate",
    }
    if tool_job:
        sidecar["inputs"] = params.get("inputs") or []
        sidecar["parents"] = params.get("parents") or []
        sidecar["transformations"] = params.get("transformations") or []
    _publish_generation_sidecar_for_studio_job(job, generated_path, sidecar)
    if not finalize:
        return update_job(
            job,
            progress=99,
            step=0,
            total_steps=0,
            phase="Finalizing",
            message="Simulated inference complete · finalizing…",
        )
    return finish_job(
        job,
        "completed",
        progress=100,
        step=0,
        total_steps=0,
        phase="",
        message="Done · simulated artifact",
    )


# --- generation worker: moved to app/services/generation_worker (generated bind list) ---
from services.generation_worker import bind_generation_worker, run_generation as _run_generation

bind_generation_worker(
    _active_gen_states=_active_gen_states,
    _apply_film_grain_to_file=_apply_film_grain_to_file,
    _apply_per_job_coefficient=_apply_per_job_coefficient,
    _apply_spatial_upsampling_to_file=_apply_spatial_upsampling_to_file,
    _build_recast_adaptive_mask=_build_recast_adaptive_mask,
    _cancel_h3_idle_release=_cancel_h3_idle_release,
    _coordinated_generation_slot=_coordinated_generation_slot,
    _ensure_managed_loras_present=_ensure_managed_loras_present,
    _extract_output_seed=_extract_output_seed,
    _interrupt_wan_model=_interrupt_wan_model,
    _is_legacy_h3_model=_is_legacy_h3_model,
    _is_minimax_h3_model=_is_minimax_h3_model,
    _jobs=_jobs,
    _local_gpu_lane=_local_gpu_lane,
    _persist_generation_job=_persist_generation_job,
    _publish_generation_sidecar_for_studio_job=_publish_generation_sidecar_for_studio_job,
    _release_h3_when_queue_allows=_release_h3_when_queue_allows,
    _release_legacy_h3_when_queue_allows=_release_legacy_h3_when_queue_allows,
    _remove_persisted_generation_job=_remove_persisted_generation_job,
    _render_recast_mask_locked_video=_render_recast_mask_locked_video,
    # defined further down in this module: looked up when the worker calls it
    _resolve_video_editor_source=lambda *args, **kwargs: _resolve_video_editor_source(*args, **kwargs),
    _restore_base_coefficient=_restore_base_coefficient,
    _run_sfx_generation=_run_sfx_generation,
    _run_simulated_generation=_run_simulated_generation,
    _workspace_dir=_workspace_dir,
    wgp=wgp,
)
# --- end generation worker ---

def _write_recast_shot_aware_sidecar(
    job, output_path, shot_bundle, generation_time,
):
    """Persist restorable settings without leaking disposable shot paths."""
    import copy
    from services.asset_manifest import publish_generation_sidecar

    output_name = os.path.basename(output_path)
    params = copy.deepcopy(job.get("params") or {})
    for key in (
        "_defer_output_publication",
        "_recast_shot_manifest",
        "_recast_shot_temp_dir",
        "_recast_final_out_dir",
        "_recast_shot_bundle",
    ):
        params.pop(key, None)
    params["video_length"] = int(shot_bundle["frame_count"])
    params["seed"] = int(shot_bundle["resolved_seed"])
    params["edit_recast_shot_aware"] = True
    params["edit_recast_shot_plan"] = list(
        shot_bundle.get("published_shots") or [],
    )

    upload_filenames = {}
    for key in (
        "image_start", "image_end", "video_guide", "audio_guide",
        "audio_guide2", "audio_guide3", "audio_guide4",
        "audio_guide5", "audio_guide6",
    ):
        value = params.get(key)
        if isinstance(value, str) and value:
            upload_filenames[key] = os.path.basename(value)
        elif isinstance(value, list):
            upload_filenames[key] = [
                os.path.basename(item)
                if isinstance(item, str) and item else ""
                for item in value
            ]

    sidecar = {
        "params": params,
        "upload_filenames": upload_filenames,
        "generation_mode": params.get("generation_mode"),
        "job_id": job.get("id"),
        "generation_time": int(round(float(generation_time))),
        "created_at": time.time(),
        "output_filename": output_name,
    }
    publish_generation_sidecar(
        output_path,
        sidecar,
        workspace_id=job.get("workspace"),
        tool="recast",
    )


def _run_recast_shot_generation(job_id):
    """Generate cast-aware segments independently, then restore source audio."""
    import shutil

    job = _jobs[job_id]
    params = job.get("params") or {}
    shot_bundle = params.get("_recast_shot_bundle") or {}
    temp_dir = params.get("_recast_shot_temp_dir")
    final_out_dir = params.get("_recast_final_out_dir") or _workspace_dir(
        job.get("workspace"),
    )
    assembly_state = {"abort": False}
    final_path = None
    published = False
    started_at = time.time()

    try:
        if not _run_generation(job_id, finalize=False):
            return
        if not register_abort_state(
            job,
            job_id,
            _active_gen_states,
            assembly_state,
        ):
            return
        if not update_job(
            job,
            progress=99,
            step=0,
            total_steps=0,
            phase="Joining Recast segments",
            message="Joining cast-aware segments and restoring source audio...",
        ):
            return

        clip_outputs = job.get("_internal_clip_output_files") or {}
        ordered_paths = []
        for shot in shot_bundle.get("shots") or []:
            if shot.get("mode") == "passthrough":
                clip_path = shot.get("passthrough_path")
            else:
                raw_name = (
                    clip_outputs.get(int(shot["shot_index"]))
                    or clip_outputs.get(str(int(shot["shot_index"])))
                )
                clip_path = (
                    raw_name
                    if raw_name and os.path.isabs(raw_name)
                    else os.path.join(temp_dir or "", raw_name or "")
                )
            if not clip_path or not os.path.isfile(clip_path):
                raise RuntimeError(
                    "Recast assembly is missing generation segment "
                    f"{int(shot.get('shot_index', 0)) + 1}."
                )
            ordered_paths.append(clip_path)

        if not ordered_paths:
            raise RuntimeError("Recast shot assembly has no video segments.")

        os.makedirs(final_out_dir, exist_ok=True)
        seed = int(shot_bundle["resolved_seed"])
        timestamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
        extension = os.path.splitext(ordered_paths[0])[1] or ".mp4"
        final_path = wgp.get_available_filename(
            final_out_dir,
            f"{timestamp}_seed{seed}_recast_shot_aware{extension}",
        )
        source_video = params.get("_recast_source_video")
        source_audio = None
        if source_video and os.path.isfile(source_video):
            try:
                if _recast_video_has_audio(source_video):
                    source_audio = source_video
            except Exception as audio_probe_error:
                print(
                    "[Recast] Could not probe source audio; assembling "
                    f"video-only: {audio_probe_error}"
                )

        assembled = wgp.concatenate_multi_clip_videos(
            ordered_paths,
            final_path,
            source_audio,
            audio_start_sec=0.0,
            abort_callback=lambda: is_cancel_requested(job),
            pad_audio=True,
            audio_duration_sec=(
                float(shot_bundle["frame_count"])
                / float(shot_bundle["fps"])
            ),
        )
        if is_cancel_requested(job):
            if final_path and os.path.isfile(final_path):
                try:
                    os.remove(final_path)
                except OSError:
                    pass
            return
        if not assembled or not os.path.isfile(final_path):
            raise RuntimeError("Recast cast-aware assembly failed.")

        expected_frames = int(shot_bundle["frame_count"])
        actual_frames = _recast_video_frame_count(final_path)
        if actual_frames != expected_frames:
            try:
                os.remove(final_path)
            except OSError:
                pass
            raise RuntimeError(
                "Recast cast-aware assembly changed the timeline length "
                f"({actual_frames}/{expected_frames} frames)."
            )

        _write_recast_shot_aware_sidecar(
            job,
            final_path,
            shot_bundle,
            time.time() - started_at,
        )
        final_name = os.path.basename(final_path)
        job["out_dir"] = final_out_dir
        published = finish_job(
            job,
            "completed",
            output_files=[final_name],
            clip_output_files={},
            join_output_file=final_name,
            progress=100,
            step=0,
            total_steps=0,
            phase="",
            message="Done",
        )
        if not published:
            return
        print(
            "[Recast] Shot-aware assembly completed: "
            f"{len(ordered_paths)} segments, {actual_frames} frames, "
            f"{'continuous source audio' if source_audio else 'video only'}."
        )
    except Exception as error:
        traceback.print_exc()
        if not is_cancel_requested(job):
            finish_job(
                job,
                "failed",
                error=str(error),
                message=f"Recast assembly failed: {error}",
            )
    finally:
        if final_path and not published:
            for leftover in (
                final_path,
                os.path.splitext(final_path)[0] + ".meta.json",
            ):
                if os.path.isfile(leftover):
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass
        unregister_abort_state(
            job_id,
            _active_gen_states,
            assembly_state,
        )
        job["out_dir"] = final_out_dir
        job.pop("_internal_output_files", None)
        job.pop("_internal_clip_output_files", None)
        job.pop("_internal_join_output_file", None)
        if isinstance(job.get("params"), dict):
            published_shots = list(
                (shot_bundle or {}).get("published_shots") or [],
            )
            if published_shots:
                job["params"]["edit_recast_shot_aware"] = True
                job["params"]["edit_recast_shot_plan"] = published_shots
            job["params"].pop("_recast_shot_manifest", None)
            job["params"].pop("_recast_shot_temp_dir", None)
            job["params"].pop("_recast_final_out_dir", None)
            job["params"].pop("_recast_shot_bundle", None)
            job["params"].pop("_defer_output_publication", None)
        if temp_dir and os.path.isdir(temp_dir):
            resolved_temp = os.path.realpath(temp_dir)
            expected_prefix = "maestro-recast-shots-"
            if os.path.basename(resolved_temp).startswith(expected_prefix):
                shutil.rmtree(resolved_temp, ignore_errors=True)




@api.get("/api/v1/status/{job_id}")
def get_status(job_id: str):
    """Get generation job status."""
    if job_id not in _jobs:
        leftovers = globals().get("_job_leftovers")
        if leftovers is not None:
            found = leftovers.status_for(job_id)
            if found is not None:
                return found
        raise HTTPException(status_code=404, detail="Job not found")
    j = snapshot_job(_jobs[job_id])
    started_at = j.get("started_at")
    finished_at = j.get("finished_at")
    processing_time = (
        max(0.0, float(finished_at or time.time()) - float(started_at))
        if started_at else None
    )
    payload = {
        "job_id": j["id"],
        "task_id": j.get("task_id"),
        "root_task_id": j.get("root_task_id") or j.get("task_id"),
        "status": j["status"],
        "progress": j["progress"],
        "step": j.get("step", 0),
        "total_steps": j.get("total_steps", 0),
        "phase": j.get("phase", ""),
        "message": j["message"],
        "output_files": j["output_files"],
        "error": j["error"],
        "task_timings": j.get("task_timings", []),
        "created_at": j.get("created_at"),
        "started_at": started_at,
        "finished_at": finished_at,
        "processing_time_sec": (
            round(processing_time, 2) if processing_time is not None else None
        ),
        "queue_position": (
            generation_queue_position(_gen_lock, _jobs[job_id])
            if j.get("status") == "queued" else None
        ),
        "generation_details": _public_generation_details(j.get("params")),
        "h3_window_plan": (
            (j.get("params") or {}).get("h3_window_plan")
            if isinstance(j.get("params"), dict)
            else None
        ),
        # Present only on failed jobs that look like CUDA OOMs. UI
        # renders the OOM recovery banner when this is non-null.
        "oom_info": j.get("oom_info"),
    }
    from services.generation_output_name import status_output_fields
    from services.generation_memory import include_performance
    from services.output_names import annotate_generation_view
    payload.update(status_output_fields(
        payload.get("output_files"),
        workspace=str(j.get("workspace") or ""),
        workspace_dir=str(j.get("out_dir") or ""),
    ))
    return annotate_generation_view(include_performance(payload, j), j)


@api.post("/api/v1/cancel/{job_id}")
def cancel_job(job_id: str):
    """Cancel a queued or running generation job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_id.startswith("audio-analysis-"):
        return cancel_audio_analysis_job(job_id)

    job = _jobs[job_id]
    result = request_cancel(
        job,
        job_id=job_id,
        active_states=_active_gen_states,
    )
    if result.abort_signalled:
        print(f"[Cancel] Signalling abort for job {job_id}")
    if not result.was_running and job.get("status") == "cancelled":
        _remove_persisted_generation_job(job)
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "was_running": result.was_running,
    }


@api.get("/api/v1/jobs")
def list_jobs():
    """List all active/recent jobs for reconnection after browser refresh."""
    active = []
    for job in list(_jobs.values()):
        j = snapshot_job(job)
        if j["status"] in ("queued", "waiting_resource", "running", "cancelling"):
            active.append({
                "job_id": j["id"],
                "task_id": j.get("task_id"),
                "root_task_id": j.get("root_task_id") or j.get("task_id"),
                "status": j["status"],
                "progress": j["progress"],
                "step": j.get("step", 0),
                "total_steps": j.get("total_steps", 0),
                "phase": j.get("phase", ""),
                "message": j["message"],
                "output_files": j["output_files"],
                "error": j["error"],
                "oom_info": j.get("oom_info"),
                "task_timings": j.get("task_timings", []),
                "created_at": j.get("created_at", 0),
                "started_at": j.get("started_at"),
                "finished_at": j.get("finished_at"),
                "queue_position": (
                    generation_queue_position(_gen_lock, job)
                    if j.get("status") == "queued" else None
                ),
                "generation_details": _public_generation_details(
                    j.get("params")
                ),
                # Lets a refreshed browser restore the exact H3 prompts that
                # are already driving an in-flight sliding-window job. This is
                # planning metadata only; model paths and unrelated params stay
                # private.
                "h3_window_plan": (
                    (j.get("params") or {}).get("h3_window_plan")
                    if isinstance(j.get("params"), dict)
                    else None
                ),
            })
    active.sort(key=lambda x: x["created_at"])
    return {"jobs": active}


def _recovery_job_summary(record: dict) -> dict:
    params = record.get("params") if isinstance(record.get("params"), dict) else {}
    prompt = str(params.get("prompt") or params.get("lyrics") or "").strip()
    return {
        "job_id": str(record.get("id") or ""),
        "previous_status": str(record.get("status") or "queued"),
        "created_at": float(record.get("created_at") or 0),
        "workspace": str(record.get("workspace") or "default"),
        "model_type": str(params.get("model_type") or ""),
        "generation_mode": str(params.get("generation_mode") or ""),
        "prompt_preview": prompt[:240],
    }


@api.get("/api/v1/jobs/recovery")
def get_generation_queue_recovery():
    """Return crash leftovers that are not active in this server process."""
    with _queue_recovery_lock:
        _image_generation_commands.restore_recovery(item["name"] for item in _list_workspaces())
        candidates = _image_generation_commands.filter_recovery(
            _durable_generation_queue.list(exclude_ids=_jobs.keys()))
    return {"jobs": [_recovery_job_summary(record) for record in candidates]}


def _queue_recovered_generation(record: dict):
    """Put one durable leftover back on the live queue without starting it.

    Returns ``(job, created)``. ``created`` is false when that id is already
    live, so resume cannot start a second worker for the same leftover.
    """
    job_id = str(record.get("id") or "").strip()
    params = record.get("params")
    if not job_id or not isinstance(params, dict) or not params.get("model_type"):
        if job_id:
            _durable_generation_queue.remove(job_id)
        return None, False
    existing = _jobs.get(job_id)
    if existing is not None:
        return existing, False
    workspace = str(record.get("workspace") or "default")
    _reset_canonical_task_for_resume(
        workspace,
        f"task-generation-{job_id}",
    )
    job = _new_generation_job(
        params,
        workspace,
        job_id=job_id,
        created_at=float(record.get("created_at") or time.time()),
        recovered=True,
        reserve_generation=not isinstance(
            params.get("_h3_window_plan_pending"), dict,
        ),
        provenance=record.get("provenance") if isinstance(record.get("provenance"), dict) else None,
    )
    _jobs[job_id] = job
    _persist_generation_job(job)
    _cancel_h3_idle_release()
    return job, True


@api.post("/api/v1/jobs/recovery/resume")
def resume_generation_queue():
    """Requeue persisted requests in their original submission order.

    An interrupted running request restarts from its beginning: model runtimes
    do not expose a portable mid-diffusion checkpoint.
    """
    resumed: list[dict] = []
    threads: list[threading.Thread] = []
    with _queue_recovery_lock:
        _image_generation_commands.restore_recovery(item["name"] for item in _list_workspaces())
        candidates = _image_generation_commands.filter_recovery(
            _durable_generation_queue.list(exclude_ids=_jobs.keys()))
        for record in candidates:
            job, created = _queue_recovered_generation(record)
            if not created or job is None:
                continue
            threads.append(threading.Thread(
                target=_run_generation_with_preparation,
                args=(job["id"],),
                name=f"recovered-generation-{job['id']}",
                daemon=False,
            ))
            resumed.append(_recovery_job_summary(record))

        # Populate the complete in-memory queue before any worker can finish,
        # then start in saved order so the existing GPU mutex serialises it.
        for thread in threads:
            thread.start()
    return {"resumed": resumed, "count": len(resumed)}


@api.post("/api/v1/jobs/recovery/discard")
def discard_generation_queue():
    """Clear only inactive recovery candidates; never cancel live work."""
    with _queue_recovery_lock:
        _image_generation_commands.restore_recovery(item["name"] for item in _list_workspaces())
        _image_generation_commands.discard_recovery(
            _durable_generation_queue.list(exclude_ids=_jobs.keys()))
        removed = _durable_generation_queue.discard(exclude_ids=_jobs.keys())
    return {"discarded": removed}


# ============================================================================
# API Routes: Favorites
# ============================================================================

from services.scene_favorites import (
    _character_kit_conflict,
    _character_kit_for_scene,
    _character_kit_workspace,
    _load_favorites,
    _save_favorites,
)
from routers.scenes_favorites import (
    create_favorites_router,
    create_scene_output_router,
    create_scene_recording_router,
    save_scene_output,
    save_scene_recording,
)

api.include_router(create_favorites_router(
    _workspace_dir=_workspace_dir,
    _get_active_workspace=_get_active_workspace,
))
api.include_router(create_scene_output_router(save_scene=save_scene_output))

from routers.character_kit_library import (
    _bind_character_kit_library_runtime,
    create_character_kit_library_router,
)

_bind_character_kit_library_runtime(
    workspace_dir=lambda workspace: _workspace_dir(_character_kit_workspace(workspace)),
    conflict=_character_kit_conflict,
)
api.include_router(create_character_kit_library_router())


from routers.character_kit_face import create_character_kit_face_router

api.include_router(create_character_kit_face_router(
    workspace_dir=lambda workspace: _workspace_dir(_character_kit_workspace(workspace)),
    uploads_root=lambda: os.path.join(os.getcwd(), "uploads"),
))



import routers.scenes_favorites as _scenes_favorites
_scenes_favorites._workspace_dir = _workspace_dir
_scenes_favorites._stream_upload = _stream_upload
_scenes_favorites._UPLOAD_TRANSCODE_SLOTS = _UPLOAD_TRANSCODE_SLOTS
_scenes_favorites._safe_join = _safe_join
api.include_router(create_scene_recording_router(publish_recording=save_scene_recording))


# ============================================================================
# Comics — native projects and MiniMax images
# ============================================================================

from routers.comics import (
    cancel_comic_minimax_job,
    create_comics_router,
    list_minimax_image_jobs,
)

api.include_router(create_comics_router(
    workspace_dir=_workspace_dir,
    get_active_workspace=_get_active_workspace,
    safe_join=_safe_join,
    get_services_config=lambda: wgp.server_config.get("services") or {},
    publish_legacy_task=lambda job, adapter: _publish_generic_legacy_task(job, adapter),
))


from services.comic_helpers import (
    _comic_page_problem,
    _comic_writing_llm,
    bind_comic_helpers,
)

bind_comic_helpers(wgp_module=wgp)


from services.comic_director_json import (
    _generate_comic_director_json,
    _parse_comic_director_json,
    _repair_comic_text_encoding,
)




_series_library_lock = threading.RLock()


def _series_library_workspace(value) -> str:
    from services.series_library import validate_workspace_id

    try:
        return validate_workspace_id(value or _get_active_workspace())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _read_series_workspace(workspace: str) -> dict:
    from services.series_library import read_series_library

    return read_series_library(_workspace_dir(workspace), workspace)


def _write_series_workspace(workspace: str, library: dict) -> dict:
    from services.series_library import write_series_library

    return write_series_library(_workspace_dir(workspace), library, workspace)


def _series_project_or_404(library: dict, series_id: str) -> dict:
    series = library.get("seriesById", {}).get(series_id)
    if not isinstance(series, dict):
        raise HTTPException(status_code=404, detail="Series Lab project not found")
    return series




from routers.series_library import (
    _bind_series_library_runtime,
    _series_iso_now,
    _story_import_upload_path,
    create_series_attempt_approval_router,
    create_series_attempt_reject_router,
    create_series_library_router,
    create_series_shot_duration_router,
)

_bind_series_library_runtime(
    resolve_workspace=_series_library_workspace,
    library_lock=_series_library_lock,
    read_library=_read_series_workspace,
    write_library=_write_series_workspace,
    project_or_404=_series_project_or_404,
    workspace_dir=_workspace_dir,
    safe_join=_safe_join,
)
api.include_router(create_series_library_router())




from services.series_plan_jobs import (
    _llm_abort_outcome,
    _planning_cancel_message,
    _series_plan_jobs,
    _series_plan_jobs_lock,
)
from routers.series_plan import (
    _bind_series_plan_runtime, cancel_series_episode_plan, create_series_plan_apply_router,
    create_series_plan_router, resume_series_episode_plan,
)


def _forward_series_plan_publish(job, adapter):
    return _publish_series_task(job, adapter)


def _forward_series_plan_reset(workspace, task_id):
    return _reset_canonical_task_for_resume(workspace, task_id)


_bind_series_plan_runtime(
    resolve_workspace=_series_library_workspace,
    library_lock=_series_library_lock,
    read_library=_read_series_workspace,
    write_library=_write_series_workspace,
    project_or_404=_series_project_or_404,
    workspace_dir=_workspace_dir,
    list_workspaces=_list_workspaces,
    ensure_llm_loaded=_ensure_llm_loaded,
    writing_override=_comic_writing_llm,
    publish_task=_forward_series_plan_publish,
    reset_task=_forward_series_plan_reset,
)
api.include_router(create_series_plan_router())
api.include_router(create_series_shot_duration_router())
api.include_router(create_series_plan_apply_router())


from services.series_render_jobs import (
    _series_asset_local_path,
    _series_render_active_jobs,
    _series_render_jobs,
    _series_render_jobs_lock,
    series_render_task_adapter,
)
from routers.series_render import (
    _bind_series_render_runtime,
    cancel_series_render_job,
    create_series_render_router,
    resume_series_render_job,
)


def _forward_series_render_publish(job, adapter):
    return _publish_series_task(job, adapter)


def _forward_series_render_reset(workspace, task_id):
    return _reset_canonical_task_for_resume(workspace, task_id)


_bind_series_render_runtime(
    resolve_workspace=_series_library_workspace,
    library_lock=_series_library_lock,
    read_library=_read_series_workspace,
    write_library=_write_series_workspace,
    project_or_404=_series_project_or_404,
    workspace_dir=_workspace_dir,
    list_workspaces=_list_workspaces,
    iso_now=_series_iso_now,
    jobs=_jobs,
    new_generation_job=_new_generation_job,
    request_generation_cancel=_request_generation_cancel,
    run_generation=_run_generation,
    is_legacy_h3_model=_is_legacy_h3_model,
    is_minimax_h3_model=_is_minimax_h3_model,
    release_legacy_h3=_release_legacy_h3_when_queue_allows,
    release_h3=_release_h3_when_queue_allows,
    publish_task=_forward_series_render_publish,
    reset_task=_forward_series_render_reset,
)
ctx.tasks.register_adapter("series-render", series_render_task_adapter)
api.include_router(create_series_render_router())




api.include_router(create_series_attempt_approval_router())


from routers.series_assembly import control_series_assembly_job, create_series_assembly_router
from services.core_series_assembly import with_transitions as _series_join_with_transitions

api.include_router(create_series_assembly_router(
    resolve_workspace=_series_library_workspace,
    workspace_dir=_workspace_dir,
    list_workspaces=_list_workspaces,
    library_lock=_series_library_lock,
    read_library=_read_series_workspace,
    write_library=_write_series_workspace,
    find_series=_series_project_or_404,
    asset_local_path=_series_asset_local_path,
    available_filename=wgp.get_available_filename,
    concatenate_clips=_series_join_with_transitions(wgp.concatenate_multi_clip_videos),
    iso_now=_series_iso_now,
))


def _quick_video_batch_reference_path(source: str, workspace: str) -> str | None:
    """Resolve only HocusPocus-owned image URLs used by a Quick Video batch."""
    from urllib.parse import unquote, urlparse

    parsed_path = urlparse(str(source or "")).path
    if parsed_path.startswith("/api/v1/file/"):
        filename = unquote(parsed_path.split("/api/v1/file/", 1)[1])
        candidate = _safe_join(_workspace_dir(workspace), filename)
    elif parsed_path.startswith("/api/v1/uploads/"):
        filename = unquote(parsed_path.split("/api/v1/uploads/", 1)[1])
        candidate = _safe_join(os.path.join(os.getcwd(), "uploads"), filename)
    else:
        return None
    return candidate if candidate and os.path.isfile(candidate) else None


from routers.quick_video_batches import (
    control_quick_video_batch_job,
    create_quick_video_batch_router,
)
from services.director_pipeline import (
    get_pipeline_status as _quick_batch_pipeline_status,
    resume_pipeline as _quick_batch_resume_pipeline,
    start_pipeline as _quick_batch_start_pipeline,
    stop_pipeline as _quick_batch_stop_pipeline,
)

api.include_router(create_quick_video_batch_router(
    resolve_workspace=_series_library_workspace,
    workspace_dir=_workspace_dir,
    list_workspaces=_list_workspaces,
    ensure_pipeline_ready=_init_pipeline,
    start_pipeline=_quick_batch_start_pipeline,
    get_pipeline_status=_quick_batch_pipeline_status,
    stop_pipeline=_quick_batch_stop_pipeline,
    resume_pipeline=_quick_batch_resume_pipeline,
    get_model_def=wgp.get_model_def,
    get_model_defaults=wgp.get_default_settings,
    resolve_reference=_quick_video_batch_reference_path,
))

from routers.style_library import create_style_library_router
from services.style_library import (
    StyleLibrary,
    migrate_legacy_style_library,
    resolve_style_library_root,
)

_style_library_legacy_root = os.path.join(os.path.dirname(__file__), "style_library")
_style_library_root, _style_storage_notice = migrate_legacy_style_library(
    _style_library_legacy_root,
    resolve_style_library_root(os.path.dirname(__file__)),
)
if _style_storage_notice:
    print(f"[Style Library] {_style_storage_notice}")
_style_library = StyleLibrary(_style_library_root, storage_notice=_style_storage_notice)
api.include_router(create_style_library_router(_style_library))


api.include_router(create_series_attempt_reject_router())


_story_library_lock = threading.Lock()


def _story_library_workspace(value) -> str:
    workspace = str(value or _get_active_workspace()).strip()
    if workspace != "default" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", workspace):
        raise HTTPException(status_code=400, detail="Invalid Story Lab workspace")
    return workspace


def _story_library_revision_conflict(exc) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "story_library_revision_conflict",
            "message": str(exc),
            "expectedRevision": exc.expected,
            "currentRevision": exc.current,
        },
    )


from routers.wizard_persistence import create_wizard_persistence_router
api.include_router(create_wizard_persistence_router(
    workspace_dir=lambda value: _workspace_dir(_story_library_workspace(value)),
    lock=_story_library_lock,
))


from routers.story_library import (
    _bind_story_library_runtime,
    create_story_library_router,
)

_bind_story_library_runtime(
    workspace_dir=lambda workspace: _workspace_dir(_story_library_workspace(workspace)),
    library_lock=_story_library_lock,
    conflict=_story_library_revision_conflict,
)
api.include_router(create_story_library_router())




from services.story_lab_jobs import (
    _story_plan_jobs,
    _story_plan_jobs_lock,
)
from routers.story_lab import (
    _bind_story_lab_runtime,
    cancel_story_lab_generation,
    create_story_lab_assets_router,
    create_story_lab_generation_router,
    resume_story_lab_generation,
)


def _forward_story_plan_publish(record, adapter):
    return _publish_generic_legacy_task(record, adapter)


def _forward_story_plan_reset(workspace, task_id):
    return _reset_canonical_task_for_resume(workspace, task_id)


_bind_story_lab_runtime(
    comic_writing_llm=_comic_writing_llm,
    ensure_llm_loaded=_ensure_llm_loaded,
    workspace_dir=_workspace_dir,
    list_workspaces=_list_workspaces,
    get_active_workspace=_get_active_workspace,
    story_import_upload_path=_story_import_upload_path,
    publish_task=_forward_story_plan_publish,
    reset_task=_forward_story_plan_reset,
)
api.include_router(create_story_lab_assets_router())


from services.story_music_jobs import bind_story_music_jobs

_story_music_jobs = bind_story_music_jobs(
    workspace_dir=_workspace_dir,
    list_workspaces=_list_workspaces,
    wgp_module=wgp,
    publish_legacy_task=lambda record, adapter: _publish_generic_legacy_task(record, adapter),
)
_minimax_music_jobs = _story_music_jobs.minimax_music_jobs
_minimax_music_jobs_lock = _story_music_jobs.minimax_music_jobs_lock
_publish_minimax_music_job = _story_music_jobs.publish_minimax_music_job

from routers.story_music import (
    cancel_story_music_candidates_job,
    create_story_music_router,
)

api.include_router(create_story_music_router(
    _story_music_jobs,
    get_active_workspace=_get_active_workspace,
    story_cover_reference_path=_story_cover_reference_path,
    wgp_module=wgp,
))




api.include_router(create_story_lab_generation_router())


from services.director_comic_jobs import (
    _comic_plan_active_jobs,
    _comic_plan_jobs,
    _comic_plan_jobs_lock,
)
from routers.director_comic import (
    bind_director_comic_runtime,
    create_director_comic_router,
    resume_director_comic_plan,
)

bind_director_comic_runtime(
    wgp_module=wgp,
    ensure_llm_loaded=_ensure_llm_loaded,
    effective_llm_routing=_effective_llm_routing,
    workspace_dir=_workspace_dir,
    get_active_workspace=_get_active_workspace,
    publish_legacy_task=lambda snapshot, adapter: _publish_generic_legacy_task(snapshot, adapter),
    reset_task=lambda workspace, task_id: _reset_canonical_task_for_resume(workspace, task_id),
)
api.include_router(create_director_comic_router())


from services.output_listing import (
    _OUTPUT_SCAN_CACHE_MAX_AGE_SECONDS,
    _output_scan_cache,
    _output_scan_cache_lock,
    _resolve_output_file,
    configure as _configure_output_listing,
    serve_file,
)
_configure_output_listing(
    workspace_dir=_workspace_dir,
    load_favorites=_load_favorites,
    safe_join=_safe_join,
    engine=wgp,
)
_scenes_favorites._output_scan_cache = _output_scan_cache
_scenes_favorites._output_scan_cache_lock = _output_scan_cache_lock
from services.output_ops import (  # noqa: E402
    _MEDIA_THUMBNAIL_CACHE_DIR,
    _resolve_gallery_file,
    configure as _configure_output_ops,
)
_configure_output_ops(
    workspace_dir=_workspace_dir,
    safe_join=_safe_join,
    extract_output_seed=_extract_output_seed,
    load_favorites=_load_favorites,
    save_favorites=_save_favorites,
    resolve_output_move_path=_resolve_output_move_path,
    ensure_llm_loaded=_ensure_llm_loaded,
)
from services.media_dimensions import configure as _configure_media_facts  # noqa: E402

_configure_media_facts(_MEDIA_THUMBNAIL_CACHE_DIR)

from routers.workspace_outputs import create_list_outputs_router  # noqa: E402

api.include_router(create_list_outputs_router())

from routers.output_facts import create_output_facts_router  # noqa: E402

api.include_router(create_output_facts_router(_resolve_gallery_file))

from routers.outputs_ops import (  # noqa: E402
    create_output_extra_router,
    create_output_metadata_router,
    create_output_move_router,
    create_output_thumbnail_router,
)

api.include_router(create_output_thumbnail_router())

from routers.workspace_outputs import create_serve_file_router  # noqa: E402

api.include_router(create_serve_file_router())

api.include_router(create_output_metadata_router())


from services.alternative_songs import (  # noqa: E402
    _alternative_song_sidecar_lock,  # same lock the handlers take; this module keeps the alias
    configure_editor as _configure_alternative_song_editor,
    configure_workspace as _configure_alternative_songs,
)
_configure_alternative_songs(
    workspace_dir=_workspace_dir,
    safe_join=_safe_join,
    get_active_workspace=_get_active_workspace,
)
from routers.alternative_songs import create_alternative_songs_router  # noqa: E402

api.include_router(create_alternative_songs_router())


api.include_router(create_output_extra_router())


# ============================================================================
# API Routes: lightweight video editor
# ============================================================================

# The editor router (routers/video_editor.py) owns the only job registry; the
# comic animatic, alternative songs, Activity sync and canonical cancel below
# share it through these names.
from routers.video_editor import (
    _VIDEO_EDITOR_FFMPEG_LANE,
    _VIDEO_EDITOR_TERMINAL,
    _finish_video_editor_cancelled,
    _public_video_editor_job,
    _register_video_editor_job,
    _remove_video_editor_output_bundle,
    _resolve_video_editor_audio_source,
    _resolve_video_editor_source,
    _start_video_editor_export as start_video_editor_export,
    _video_editor_cancel_requested,
    _video_editor_job_snapshot,
    _video_editor_job_update,
    _video_editor_task_identity,
    cancel_video_editor_export,
    create_video_editor_jobs_router,
    create_video_editor_router,
    get_video_editor_export,
    list_video_editor_jobs,
)

# The registry above is the only one. Alternative songs were registered
# earlier, before this import existed, and read these names at call time.
_configure_alternative_song_editor(
    video_editor_job_snapshot=_video_editor_job_snapshot,
    video_editor_job_update=_video_editor_job_update,
    video_editor_cancel_requested=_video_editor_cancel_requested,
    finish_video_editor_cancelled=_finish_video_editor_cancelled,
    remove_video_editor_output_bundle=_remove_video_editor_output_bundle,
    resolve_video_editor_audio_source=_resolve_video_editor_audio_source,
    register_video_editor_job=_register_video_editor_job,
    video_editor_task_identity=_video_editor_task_identity,
    ffmpeg_lane=_VIDEO_EDITOR_FFMPEG_LANE,
    terminal=_VIDEO_EDITOR_TERMINAL,
)
from services.comic_animatic import _run_comic_animatic, bind_comic_animatic

bind_comic_animatic(
    resolve_model3d_input_path=_resolve_model3d_input_path,
    video_editor_ffmpeg_lane=_VIDEO_EDITOR_FFMPEG_LANE,
    video_editor_terminal=_VIDEO_EDITOR_TERMINAL,
    finish_video_editor_cancelled=_finish_video_editor_cancelled,
    remove_video_editor_output_bundle=_remove_video_editor_output_bundle,
    video_editor_cancel_requested=_video_editor_cancel_requested,
    video_editor_job_snapshot=_video_editor_job_snapshot,
    video_editor_job_update=_video_editor_job_update,
)


# Probe, thumbnail, screenshot and export: the routes keep their place in the table.
api.include_router(create_video_editor_router(
    workspace_dir=_workspace_dir,
    get_active_workspace=_get_active_workspace,
    resolve_input_path=_resolve_model3d_input_path,
    # Defined further down: looked up on each publish, as the inline routes did.
    publish_legacy_task=lambda snapshot, adapter: _publish_generic_legacy_task(snapshot, adapter),
    thumbnail_cache_dir=_MEDIA_THUMBNAIL_CACHE_DIR,
))


from routers.comics import create_comics_animatic_router

api.include_router(create_comics_animatic_router(
    workspace_dir=_workspace_dir,
    get_active_workspace=_get_active_workspace,
    video_editor_task_identity=_video_editor_task_identity,
    register_video_editor_job=_register_video_editor_job,
    video_editor_job_update=_video_editor_job_update,
    public_video_editor_job=_public_video_editor_job,
    ffmpeg_lane_key=_VIDEO_EDITOR_FFMPEG_LANE.key,
    run_comic_animatic=_run_comic_animatic,
))


# Export status and cancel follow the comic animatic, as before.
api.include_router(create_video_editor_jobs_router())


api.include_router(create_output_move_router())


from routers.uploads import create_uploads_router
from services.upload_video_metadata import probe_with_decoder

api.include_router(create_uploads_router(
    uploads_dir=lambda: os.path.join(os.getcwd(), "uploads"),
    stream_upload=_stream_upload,
    transcode_upload=_transcode_upload,
    probe_video_metadata=probe_with_decoder,
    safe_join=_safe_join,
    output_fallback=serve_file,
))


# ============================================================================
# Canonical task registry and compatibility adapters
# ============================================================================

def _reset_canonical_task_for_resume(workspace: str, task_id: str) -> None:
    """Explicitly reopen a terminal adapter task before its worker publishes."""
    if not task_id:
        return
    try:
        registry = _task_registry(workspace)
        existing = registry.get(task_id)
        if existing and str(existing.get("status") or "") in {
            "failed", "cancelled", "interrupted",
        }:
            registry.update(
                task_id,
                status="queued",
                phase="queued",
                message="Resume requested",
                error=None,
                completed_at=None,
                event_type="task.resume_requested",
                force=True,
            )
    except Exception as exc:
        print(f"[Task registry] Could not reopen {task_id}: {exc}")


def _task_legacy_id(record: dict) -> str:
    return str(record.get("jobId") or record.get("job_id") or record.get("id") or "")


def _task_status(value: object) -> str:
    from services.canonical_task_helpers import task_status
    return task_status(value)


def _task_timestamp(record: dict, *keys: str) -> float | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def _canonical_legacy_progress(current: object, total: object, progress: object) -> float:
    """Convert legacy counters/percentages to the canonical 0..1 scale."""
    try:
        total_value = float(total)
    except (TypeError, ValueError):
        total_value = 0.0
    if math.isfinite(total_value) and total_value > 0:
        try:
            current_value = float(current)
        except (TypeError, ValueError):
            current_value = 0.0
        value = current_value / total_value if math.isfinite(current_value) else 0.0
    else:
        try:
            percent_value = float(progress)
        except (TypeError, ValueError):
            percent_value = 0.0
        value = percent_value / 100.0 if math.isfinite(percent_value) else 0.0
    return max(0.0, min(1.0, value))


def _upsert_canonical_task(
    workspace: str,
    task_id: str,
    *,
    event_exclude_fields: set[str] | frozenset[str] | None = None,
    **fields,
) -> dict:
    from services.canonical_task_helpers import upsert_canonical_task
    return upsert_canonical_task(
        _task_registry(workspace),
        workspace,
        task_id,
        event_exclude_fields=event_exclude_fields,
        **fields,
    )


def _generation_task_fields(job: dict) -> dict:
    from services.activity_media import activity_reference_images
    legacy_id = str(job.get("id") or "")
    workspace = str(job.get("workspace") or "default")
    details = _public_generation_details(job.get("params"))
    mode = str(details.get("generation_mode") or "generation")
    model_type = str(details.get("model_type") or "")
    is_remote = model_type.startswith("minimax:")
    task_id = f"task-generation-{legacy_id}"
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    owner_id = str(params.get("_director_pipeline_id") or "")
    provenance = job.get("provenance") if isinstance(job.get("provenance"), dict) else {}
    command = provenance.get("command") if isinstance(provenance.get("command"), dict) else {}
    from services.generation_provenance import task_fields_from_provenance
    from services.generation_memory import performance_fields

    task_identity = task_fields_from_provenance(
        provenance,
        pipeline_id=owner_id if owner_id and not owner_id.startswith("series:") else None,
    )
    task_metadata = {
        "adapter": "generation", "generation_details": details,
        "display_prompt": details.get("prompt", ""),
        "reference_images": activity_reference_images(params, workspace,
            uploads_dir=os.path.join(os.getcwd(), "uploads"), workspace_dir=_workspace_dir(workspace)),
        "inference_started_at": job.get("inference_started_at"),
        "inference_start_step": job.get("inference_start_step"),
        "owner_pipeline_id": owner_id,
        "actor": provenance.get("actor") or "unknown",
        "tool": provenance.get("tool") or "studio",
        "capability": provenance.get("capability"),
        "command_id": command.get("command_id"),
        "workflow_id": command.get("workflow_id"),
        "run_id": command.get("run_id"),
        "output_name_requested": params.get("output_filename") or params.get("output_name") or None,
    }
    task_metadata.update(task_identity.pop("metadata", {}))
    task_metadata.update(performance_fields(job.get("performance")))
    if owner_id.startswith("series:"):
        series_job_id = owner_id.split(":", 1)[1]
        parent_task_id = f"task-series-render-{series_job_id}"
    elif owner_id:
        parent_task_id = f"task-director-{owner_id}"
    else:
        parent_task_id = None
    root_task_id = parent_task_id or task_id
    status = _task_status(job.get("status"))
    current = int(job.get("step") or 0)
    total = int(job.get("total_steps") or 0)
    error = job.get("error")
    if status in {"completed", "failed", "cancelled", "interrupted"}:
        acquired_resources = []
    elif "acquired_resources" in job:
        acquired_resources = list(job.get("acquired_resources") or [])
    else:
        # Compatibility for older in-memory tool jobs. Newly-created jobs
        # always carry the field, which lets planning remain visibly distinct
        # from actual GPU ownership.
        acquired_resources = (
            [] if status in {"created", "queued", "waiting_resource"}
            else ["remote:https://api.minimax.io" if is_remote else _local_gpu_lane.key]
        )
    task_title = {
        "image": "Image generation", "video": "Video generation",
        "audio": "Audio generation", "music": "Music generation",
        "model3d": "3D generation", "avatar": "Video edit",
    }.get(mode, "Generation job")
    if str(provenance.get("capability") or "") == "remove_background":
        task_title = "Tools · Remove background"
    elif str(provenance.get("capability") or "") in {"upscale", "tools.upscale"}:
        task_title = "Tools · Upscale"
    elif str(provenance.get("capability") or "") == "revoice":
        task_title = "Tools · Revoice"
    return dict(
        workspace=workspace,
        id=task_id,
        root_id=root_task_id,
        parent_id=parent_task_id,
        kind=mode,
        workflow="generation",
        title=task_title,
        status=status,
        phase=str(job.get("phase") or status),
        message=str(job.get("message") or status.replace("_", " ").title()),
        current=current,
        total=total,
        progress=_canonical_legacy_progress(current, total, job.get("progress")),
        created_at=_task_timestamp(job, "created_at") or time.time(),
        started_at=_task_timestamp(job, "started_at"),
        completed_at=_task_timestamp(job, "finished_at"),
        provider="minimax" if is_remote else "local",
        model=str(details.get("model_name") or model_type),
        server_origin="https://api.minimax.io" if is_remote else "local",
        resource_requirements=["remote:https://api.minimax.io" if is_remote else "local_gpu:0"],
        acquired_resources=acquired_resources,
        backend_job_id=legacy_id,
        cancelable=(
            status in {"created", "queued", "waiting_resource", "running"}
            and str(job.get("status") or "").lower() != "cancelling"
        ),
        recoverable=_is_durable_generation_job(job),
        error=({"message": str(error), "retryable": True} if error else None),
        result_refs=list(job.get("output_files") or []),
        **task_identity,
        metadata=task_metadata,
    )


def _publish_generation_task(job: dict) -> dict:
    fields = _generation_task_fields(job)
    workspace, task_id = fields.pop("workspace"), fields.pop("id")
    return _upsert_canonical_task(workspace, task_id, **fields)


def _observe_generation_job_state(record: dict) -> None:
    """Forward atomic lifecycle changes to the canonical task event stream."""
    job = dict(record)
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    if not str(params.get("model_type") or "").strip():
        return
    _publish_generation_task(job)


set_job_state_observer(_observe_generation_job_state)


def _publish_series_task(job: dict, adapter: str) -> dict:
    legacy_id = _task_legacy_id(job)
    workspace = str(job.get("workspace") or "default")
    is_render = adapter == "series-render"
    is_known = job.get("bootstrapKnownSeries") is True
    status = _task_status(job.get("status"))
    provider = job.get("provider") if isinstance(job.get("provider"), dict) else {}
    request_body = job.get("request") if isinstance(job.get("request"), dict) else {}
    model = str(job.get("model") or request_body.get("writingModel") or provider.get("videoModel") or "")
    provider_name = str(request_body.get("writingProvider") or "local")
    server = "local" if is_render else str(request_body.get("writingBaseUrl") or "")
    lane = (
        resource_scheduler.local_gpu_lane(0)
        if is_render
        else resource_scheduler.llm_lane(
            provider_name,
            base_url=server,
            device=str(request_body.get("writingDevice") or "cpu"),
        )
    )
    task_id = f"task-{adapter}-{legacy_id}"
    return _upsert_canonical_task(
        workspace,
        task_id,
        root_id=task_id,
        kind="video" if is_render else "llm-planning",
        workflow=adapter,
        title=("Series Lab · Video generation" if is_render else
               "Series Lab · Known-series bible" if is_known else
               "Series Lab · Canon" if job.get("jobType") == "canon" else
               "Series Lab · Episode planning"),
        status=status,
        phase=str(job.get("stage") or status),
        message=str(job.get("message") or "Series Lab is working…"),
        detail=str(job.get("validationError") or ""),
        current=int(job.get("current") or 0),
        total=int(job.get("total") or 0),
        created_at=_task_timestamp(job, "createdAt") or time.time(),
        completed_at=_task_timestamp(job, "finishedAt"),
        provider="local" if is_render else provider_name,
        model=model,
        server_origin=server,
        resource_requirements=[lane.key],
        # Parent workflows span parsing/checkpoint phases as well as provider
        # calls. Only observable child operations publish an acquired lease;
        # inferring one from the parent's broad "running" state is misleading.
        acquired_resources=[],
        attempt=max(1, int(job.get("retryCount") or job.get("validationAttempt") or 0) + 1),
        project_id=str(job.get("seriesId") or ""),
        entity_type="episode",
        entity_id=str(job.get("episodeId") or ""),
        backend_job_id=legacy_id,
        cancelable=status in {"created", "queued", "waiting_resource", "running"},
        resumable=True,
        recoverable=True,
        error=({"message": str(job.get("error")), "retryable": True} if job.get("error") else None),
        result_refs=list(job.get("outputAssetIds") or []),
        metadata={"adapter": adapter, "settings": job.get("settings") or {}},
    )


def _publish_series_assembly_task(job: dict) -> dict:
    """Publish persisted Series Assembly checkpoints to canonical Activity."""
    legacy_id = _task_legacy_id(job)
    if not legacy_id:
        return {}
    workspace = str(job.get("workspace") or "default")
    raw_status = str(job.get("status") or "queued")
    status = "running" if raw_status == "cancelling" else _task_status(raw_status)
    task_id = str(job.get("taskId") or f"task-series-assembly-{legacy_id}")
    return _upsert_canonical_task(
        workspace, task_id,
        root_id=task_id,
        kind="assembly", workflow="series-assembly",
        title="Series Lab · Episode assembly",
        status=status, phase=str(job.get("stage") or status),
        message=str(job.get("message") or "Joining approved Series clips…"),
        current=int(job.get("current") or 0), total=int(job.get("total") or 0),
        created_at=_task_timestamp(job, "createdAt") or time.time(),
        started_at=_task_timestamp(job, "startedAt"),
        completed_at=_task_timestamp(job, "finishedAt"),
        provider="local", model="FFmpeg", server_origin="local",
        resource_requirements=["cpu:ffmpeg"],
        acquired_resources=["cpu:ffmpeg"] if status == "running" else [],
        project_id=str(job.get("seriesId") or ""), entity_type="episode",
        entity_id=str(job.get("episodeId") or ""), backend_job_id=legacy_id,
        cancelable=status in {"created", "queued", "waiting_resource", "running"},
        resumable=status in {"failed", "cancelled", "interrupted"},
        recoverable=True,
        error=({"message": str(job.get("error")), "retryable": True}
               if job.get("error") else None),
        result_refs=[str(job["assetId"])] if job.get("assetId") else [],
        metadata={"adapter": "series-assembly"},
    )


_GENERIC_TASK_CONFIG = {
    "story-plan": ("Story Lab planning", "llm-planning", True),
    "comic-plan": ("Comic planning", "llm-planning", True),
    "video-editor": ("Video editor", "ffmpeg", False),
    "model3d": ("3D generation", "model3d", False),
    "rig": ("Character rigging", "rig", False),
    "minimax-image": ("MiniMax Image-01", "image", False),
    "audio-analysis": ("Audio analysis", "audio-analysis", False),
    "minimax-music": ("MiniMax Music", "music", False),
    "minimax-music-candidate": ("MiniMax Music candidate", "music", False),
}


def _publish_generic_legacy_task(record: dict, adapter: str) -> dict | None:
    legacy_id = _task_legacy_id(record)
    if not legacy_id:
        return None
    workspace = str(record.get("workspace") or "default")
    title, kind, resumable = _GENERIC_TASK_CONFIG.get(adapter, (adapter.replace("-", " ").title(), adapter, False))
    status = _task_status(record.get("status"))
    phase = str(record.get("stage") or record.get("phase") or record.get("status") or status)
    task_id = str(
        record.get("task_id")
        or record.get("taskId")
        or f"task-{adapter}-{legacy_id}"
    )
    root_task_id = str(
        record.get("root_task_id")
        or record.get("rootTaskId")
        or task_id
    )
    parent_task_id = str(
        record.get("parent_task_id")
        or record.get("parentTaskId")
        or ""
    ) or None
    request_body = record.get("request") if isinstance(record.get("request"), dict) else {}
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    command = provenance.get("command") if isinstance(provenance.get("command"), dict) else {}
    provider = str(
        record.get("provider")
        or request_body.get("writingProvider")
        or "local"
    )
    model = str(record.get("model") or record.get("model_id") or record.get("modelId") or "")
    explicit_lane = str(record.get("resource_lane") or "").strip()
    if explicit_lane:
        lane_key = explicit_lane
    elif adapter == "model3d":
        lane_key = resource_scheduler.local_gpu_lane(0).key
    elif adapter == "rig":
        lane_key = (
            resource_scheduler.local_gpu_lane(0).key
            if str(record.get("engine") or request_body.get("engine") or "").lower() == "unirig"
            else resource_scheduler.cpu_lane("rig").key
        )
    elif adapter in {"story-plan", "comic-plan"}:
        lane_key = resource_scheduler.llm_lane(
            provider,
            base_url=str(
                record.get("writingBaseUrl")
                or request_body.get("writingBaseUrl")
                or ""
            ),
            device=str(
                record.get("writingDevice")
                or request_body.get("writingDevice")
                or "cpu"
            ),
        ).key
    elif adapter == "video-editor":
        lane_key = resource_scheduler.cpu_lane("ffmpeg").key
    else:
        lane_key = resource_scheduler.cpu_lane(adapter).key
    current = int(record.get("current") or record.get("step") or 0)
    total = int(record.get("total") or record.get("total_steps") or 0)
    return _upsert_canonical_task(
        workspace, task_id,
        root_id=root_task_id, parent_id=parent_task_id,
        kind=kind, workflow=adapter, title=title,
        status=status, phase=phase,
        message=str(record.get("message") or phase.replace("_", " ").title()),
        current=current,
        total=total,
        progress=_canonical_legacy_progress(current, total, record.get("progress")),
        detail_current=int(record.get("detailCurrent") or 0),
        detail_total=int(record.get("detailTotal") or 0),
        created_at=_task_timestamp(record, "createdAt", "created_at") or time.time(),
        started_at=_task_timestamp(record, "startedAt", "started_at"),
        completed_at=_task_timestamp(record, "finishedAt", "finished_at"),
        provider=provider, model=model,
        server_origin=str(record.get("server_origin") or record.get("writingBaseUrl") or "local"),
        resource_requirements=[lane_key],
        acquired_resources=list(record.get("acquired_resources") or []),
        backend_job_id=legacy_id,
        cancelable=(status in {"created", "queued", "waiting_resource", "running"}
                    and str(record.get("status") or "").lower() != "cancelling"
                    and adapter != "comic-plan"),
        resumable=resumable, recoverable=resumable,
        error=({"message": str(record.get("error")), "retryable": resumable} if record.get("error") else None),
        result_refs=list(record.get("output_files") or (
            [record["output"]] if record.get("output") else
            [record["filename"]] if record.get("filename") else []
        )),
        metadata={
            "adapter": adapter,
            "cancel_mode": record.get("cancel_mode"),
            "safe_boundary": record.get("safe_boundary"),
            "actor": provenance.get("actor") or "unknown",
            "tool": provenance.get("tool") or adapter,
            "capability": provenance.get("capability"),
            "command_id": (
                command.get("command_id")
                or record.get("commandId")
                or record.get("command_id")
            ),
            "workflow_id": command.get("workflow_id"),
            "run_id": command.get("run_id"),
            "generation_id": record.get("generationId") or record.get("generation_id"),
            "candidate_id": record.get("candidateId") or record.get("candidate_id"),
            "idempotency_key": record.get("idempotencyKey") or record.get("idempotency_key"),
        },
    )


import services.audio_jobs as _audio_jobs_service
_audio_jobs_service._publish_generic_legacy_task = _publish_generic_legacy_task


def _publish_director_task(pipeline: dict, workspace: str) -> dict | None:
    pipeline_id = str(pipeline.get("id") or pipeline.get("pipeline_id") or "")
    if not pipeline_id:
        return None
    progress = pipeline.get("progress") if isinstance(pipeline.get("progress"), dict) else {}
    details = pipeline.get("generation_details") if isinstance(pipeline.get("generation_details"), dict) else {}
    snapshot = pipeline.get("_params_snapshot") if isinstance(pipeline.get("_params_snapshot"), dict) else {}
    params = pipeline.get("params") if isinstance(pipeline.get("params"), dict) else {}
    provenance = pipeline.get("provenance") if isinstance(pipeline.get("provenance"), dict) else {}
    if not provenance:
        provenance = snapshot.get("provenance") if isinstance(snapshot.get("provenance"), dict) else {}
    if not provenance:
        provenance = params.get("provenance") if isinstance(params.get("provenance"), dict) else {}
    from services.generation_provenance import task_fields_from_provenance

    task_identity = task_fields_from_provenance(
        provenance,
        pipeline_id=pipeline_id,
    )
    canonical_pipeline_id = task_identity.pop("pipeline_id", pipeline_id)
    schedule = pipeline.get("resource_schedule") if isinstance(pipeline.get("resource_schedule"), dict) else {}
    schedule_lanes = schedule.get("lanes") if isinstance(schedule.get("lanes"), dict) else {}
    resource_requirements = list(dict.fromkeys(
        str(lane.get("key") or "")
        for lane in schedule_lanes.values()
        if isinstance(lane, dict) and str(lane.get("key") or "")
    ))
    command = provenance.get("command") if isinstance(provenance.get("command"), dict) else {}
    task_metadata = {
        "adapter": "director", "generation_details": details,
        "resource_schedule": schedule,
        "actor": provenance.get("actor") or "unknown",
        "tool": provenance.get("tool") or "director",
        "capability": provenance.get("capability"),
        "command_id": command.get("command_id"),
        "workflow_id": command.get("workflow_id"),
        "run_id": command.get("run_id"),
    }
    task_metadata.update(task_identity.pop("metadata", {}))
    raw_status = str(pipeline.get("status") or "").strip().lower()
    status = {
        "crashed": "interrupted",
        "preview_ready": "completed",
    }.get(raw_status, _task_status(raw_status))
    task_id = f"task-director-{pipeline_id}"
    # Director checkpoints survive Activity dismissal.  Do not recreate a
    # terminal card on every snapshot just because its source JSON still
    # exists; an explicit resume creates a new task event and makes it visible
    # again.
    if status in {"completed", "failed", "cancelled", "interrupted"}:
        try:
            if _task_registry(workspace).is_dismissed(task_id):
                return None
        except Exception:
            # A task registry failure must not hide the underlying pipeline.
            pass
    completed_at = _task_timestamp(
        pipeline,
        "finished_at",
        "_completed_at",
        "completed_at",
    )
    if completed_at is None and status in {
        "completed", "failed", "cancelled", "interrupted",
    }:
        completed_at = _task_timestamp(pipeline, "updated_at")
    return _upsert_canonical_task(
        workspace, task_id,
        root_id=task_id, kind="director", workflow="director",
        title="Music video" if pipeline.get("pipeline_type") == "music_video" else "Director pipeline",
        status=status, phase=str(pipeline.get("phase") or status),
        message=str(pipeline.get("error") or progress.get("message") or "Director is working…"),
        current=int(progress.get("current") or progress.get("step") or 0),
        total=int(progress.get("total") or progress.get("total_steps") or 0),
        detail_current=int(progress.get("detail_current") or 0),
        detail_total=int(progress.get("detail_total") or 0),
        created_at=_task_timestamp(pipeline, "created_at") or time.time(),
        started_at=_task_timestamp(pipeline, "phase_started_at", "created_at"),
        completed_at=completed_at,
        provider=str(details.get("text_provider") or ""),
        model=str(details.get("text_model") or details.get("video_model_name") or ""),
        server_origin=str(details.get("text_server") or ""),
        resource_requirements=resource_requirements,
        pipeline_id=canonical_pipeline_id, backend_job_id=pipeline_id,
        cancelable=status in {"created", "queued", "waiting_resource", "running"},
        resumable=True, recoverable=True,
        error=({"message": str(pipeline.get("error")), "retryable": True} if pipeline.get("error") else None),
        result_refs=list(pipeline.get("output_files") or []),
        **task_identity,
        metadata=task_metadata,
    )


def _sync_canonical_tasks(workspace: str) -> None:
    for job in list(_jobs.values()):
        if str(job.get("workspace") or "default") == workspace:
            snapshot = snapshot_job(job)
            if str(job.get("id") or "").startswith("audio-analysis-"):
                _publish_generic_legacy_task(snapshot, "audio-analysis")
            else:
                _publish_generation_task(snapshot)
    try:
        from services.director_pipeline import list_recent_pipelines
        director_base = wgp.server_config.get("save_path", "outputs")
        for pipeline in list_recent_pipelines(director_base, workspace):
            _publish_director_task(pipeline, workspace)
    except Exception:
        pass
    with _series_plan_jobs_lock:
        series_plans = [copy.deepcopy(job) for job in _series_plan_jobs.values()]
    with _series_render_jobs_lock:
        series_renders = [copy.deepcopy(job) for job in _series_render_jobs.values()]
    for job in series_plans:
        if str(job.get("workspace") or "default") == workspace:
            _publish_series_task(job, "series-plan")
    for job in series_renders:
        if str(job.get("workspace") or "default") == workspace:
            _publish_series_task(job, "series-render")
    try:
        from services.series_jobs import SeriesJobStore
        assembly_jobs = SeriesJobStore(_workspace_dir(workspace), "assembly").list()
    except (OSError, ValueError, json.JSONDecodeError):
        assembly_jobs = []
    for job in assembly_jobs:
        if str(job.get("workspace") or workspace) == workspace:
            _publish_series_assembly_task(job)
    with _story_plan_jobs_lock:
        story_jobs = [copy.deepcopy(job) for job in _story_plan_jobs.values()]
    with _comic_plan_jobs_lock:
        comic_jobs = [copy.deepcopy(job) for job in _comic_plan_jobs.values()]
    for job in story_jobs:
        if str(job.get("workspace") or "default") == workspace:
            _publish_generic_legacy_task(job, "story-plan")
    for job in comic_jobs:
        if str(job.get("workspace") or "default") == workspace:
            _publish_generic_legacy_task(job, "comic-plan")
    video_editor_jobs = list_video_editor_jobs()
    for job in video_editor_jobs:
        if str(job.get("workspace") or "default") == workspace:
            _publish_generic_legacy_task(job, "video-editor")
    for job in list_minimax_image_jobs():
        if str(job.get("workspace") or "default") == workspace:
            _publish_generic_legacy_task(job, "minimax-image")
    with _minimax_music_jobs_lock:
        minimax_music_jobs = [copy.deepcopy(job) for job in _minimax_music_jobs.values()]
    for job in minimax_music_jobs:
        if str(job.get("workspace") or "default") == workspace:
            _publish_minimax_music_job(job)
    try:
        with model3d_service._lock:
            model3d_jobs = [copy.deepcopy(job) for job in model3d_service._jobs.values()]
        for job in model3d_jobs:
            if str(job.get("workspace") or "default") == workspace:
                _publish_generic_legacy_task(job, "model3d")
    except Exception:
        pass
    try:
        from services import rig_service
        with rig_service._lock:
            rig_jobs = [copy.deepcopy(job) for job in rig_service._jobs.values()]
        for job in rig_jobs:
            if str(job.get("workspace") or "default") == workspace:
                _publish_generic_legacy_task(job, "rig")
    except Exception:
        pass


api.include_router(create_system_resources_router())


def _control_canonical_task(task: dict, action: str):
    adapter = str((task.get("metadata") or {}).get("adapter") or "")
    legacy_id = str(task.get("backend_job_id") or task.get("pipeline_id") or "")
    if action == "cancel":
        if adapter == "generation": return cancel_job(legacy_id)
        if adapter == "director": return director_pipeline_stop(legacy_id)
        if adapter == "series-plan": return cancel_series_episode_plan(legacy_id)
        if adapter == "series-render": return cancel_series_render_job(legacy_id)
        if adapter == "story-plan": return cancel_story_lab_generation(legacy_id)
        if adapter == "video-editor": return cancel_video_editor_export(legacy_id)
        if adapter == "model3d": return cancel_model3d_job(legacy_id)
        if adapter == "rig": return cancel_rig_job(legacy_id)
        if adapter == "minimax-image": return cancel_comic_minimax_job(legacy_id)
        if adapter == "audio-analysis": return cancel_audio_analysis_job(legacy_id)
        if adapter == "minimax-music": return cancel_story_music_candidates_job(legacy_id)
        if adapter == "minimax-music-candidate":
            root_backend_id = str(task.get("root_id") or "").removeprefix(
                "task-minimax-music-"
            )
            return cancel_story_music_candidates_job(root_backend_id)
        if adapter == "series-assembly":
            return control_series_assembly_job(_workspace_dir(str(task.get("workspace") or "default")), legacy_id, "cancel")
        if adapter == "quick-video-batch":
            return control_quick_video_batch_job(
                _workspace_dir(str(task.get("workspace") or "default")),
                legacy_id,
                "cancel",
            )
    if action in {"retry", "resume"}:
        if adapter == "director": return director_pipeline_resume(legacy_id)
        if adapter == "series-plan": return resume_series_episode_plan(legacy_id)
        if adapter == "series-render": return resume_series_render_job(legacy_id)
        if adapter == "story-plan": return resume_story_lab_generation(legacy_id)
        if adapter == "comic-plan": return resume_director_comic_plan(legacy_id)
        if adapter == "series-assembly":
            return control_series_assembly_job(_workspace_dir(str(task.get("workspace") or "default")), legacy_id, "resume")
        if adapter == "quick-video-batch":
            return control_quick_video_batch_job(
                _workspace_dir(str(task.get("workspace") or "default")),
                legacy_id,
                "resume",
            )
    if action == "discard" and adapter == "series-assembly":
        return control_series_assembly_job(
            _workspace_dir(str(task.get("workspace") or "default")),
            legacy_id,
            "discard",
        )
    raise HTTPException(status_code=409, detail=f"Task does not support {action}")


from routers.canonical_tasks import create_canonical_tasks_router

api.include_router(create_canonical_tasks_router(
    get_active_workspace=_get_active_workspace,
    validate_workspace=_workspace_dir,
    registry_for_workspace=lambda workspace: _task_registry(workspace),
    sync_tasks=_sync_canonical_tasks,
    task_status=_task_status,
    upsert_task=_upsert_canonical_task,
    control_task=_control_canonical_task,
))

from routers.assets import create_assets_router

api.include_router(create_assets_router(
    list_workspaces=_list_workspaces,
    workspace_dir=_workspace_dir,
    uploads_dir=lambda: os.path.join(os.getcwd(), "uploads"),
))

from routers.tools import create_tools_router
from shared.tools.background_removal_job import (
    BackgroundRemovalJobHooks,
    run_remove_background_job,
)


def _start_remove_background_job(job: dict) -> None:
    """Start the Tools worker with the shared generation lifecycle seams."""
    def worker() -> None:
        hooks = BackgroundRemovalJobHooks(
            generation_slot=lambda current: _coordinated_generation_slot(
                current,
                description="HocusPocus Lab GPU tool · background removal",
            ),
            try_start=try_start,
            update_job=update_job,
            finish_job=finish_job,
            is_cancel_requested=is_cancel_requested,
            record_job_outputs=record_job_outputs,
            register_abort_state=register_abort_state,
            unregister_abort_state=unregister_abort_state,
            acknowledge_cancel=acknowledge_cancel,
            active_states=_active_gen_states,
            publish_sidecar=lambda current, path, sidecar: _publish_generation_sidecar_for_studio_job(
                current,
                path,
                sidecar,
                tool="tools",
            ),
            simulated_artifact=execution_mode.create_artifact,
        )
        run_remove_background_job(job, hooks=hooks)

    threading.Thread(
        target=worker,
        name=f"remove-background-{job.get('id', 'job')}",
        daemon=False,
    ).start()


api.include_router(create_tools_router(
    get_active_workspace=_get_active_workspace,
    list_workspaces=_list_workspaces,
    workspace_dir=_workspace_dir,
    uploads_dir=lambda: os.path.join(os.getcwd(), "uploads"),
    register_job=_register_manual_generation_job,
    start_remove_background=_start_remove_background_job,
))

from routers.projects import create_projects_router

api.include_router(create_projects_router(
    list_workspaces=_list_workspaces,
    workspace_dir=_workspace_dir,
))

from routers.productions import create_productions_router

def _list_canonical_production_pipelines(workspace: str):
    from services.director_pipeline import list_pipeline_states
    return list_pipeline_states(wgp.server_config.get("save_path", "outputs"), workspace)

api.include_router(create_productions_router(
    list_workspaces=_list_workspaces,
    list_pipelines=_list_canonical_production_pipelines,
))

from routers.production_projects import create_production_projects_router

api.include_router(create_production_projects_router(workspace_dir=_workspace_dir))

from routers.workspace_collections import create_workspace_collections_router
from services.workspace_registry import WorkspaceRegistry

_workspace_collection_registry = WorkspaceRegistry(os.path.join(
    wgp.server_config.get("save_path", "outputs"), "_hocuspocus", "workspaces-v1.json",
))
llm_director._workspace_collection_registry = _workspace_collection_registry
api.include_router(create_workspace_collections_router(
    registry=lambda: _workspace_collection_registry,
))

bind_director_runtime(
    jobs=_jobs,
    run_generation=_run_generation,
    wgp_module=wgp,
    gen_lock=_gen_lock,
    request_generation_cancel=_request_generation_cancel,
    active_gen_states=_active_gen_states,
    publish_director_task=_publish_director_task,
    get_cached_hardware=_get_cached_hardware,
    ensure_llm_loaded=_ensure_llm_loaded,
    is_minimax_h3_model=_is_minimax_h3_model,
    get_active_workspace=_get_active_workspace,
    workspace_dir=_workspace_dir,
    workspace_collection_registry=_workspace_collection_registry,
    reset_canonical_task_for_resume=_reset_canonical_task_for_resume,
    execution_mode_module=execution_mode,
)


# ============================================================================
# Mount Gradio classic UI at /classic
# ============================================================================

# Bare /classic 404s (the Gradio submount only answers under /classic/).
# Registered BEFORE the mount so the exact path wins routing; everything
# under /classic/ still reaches Gradio.
@api.get("/classic", include_in_schema=False)
def _classic_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/classic/")


try:
    import gradio as gr
    from shared.utils.plugins import WAN2GPApplication
    # create_ui() references a global `app` (WAN2GPApplication) for plugin support
    wgp.app = WAN2GPApplication()
    _demo = wgp.create_ui()
    api = gr.mount_gradio_app(
        api, _demo, path="/classic",
        allowed_paths=[wgp.save_path, wgp.image_save_path, "icons"],
    )
    print("[HocusPocus Lab] Gradio classic UI mounted at /classic")
except Exception as e:
    print(f"[HocusPocus Lab] WARNING: Could not mount Gradio UI at /classic: {e}")
    traceback.print_exc()


# Optional external agents use exactly the same admission endpoints and task IDs.
from routers.wangp_mcp import create_wangp_mcp_router
from services.lips_creator_commands import command_catalog as lips_creator_catalog, command_handlers as lips_creator_handlers
from services.wangp_agent_adapters import application_handlers as wangp_agent_handlers
from services.image_generation_runtime import create_image_generation_commands
from routers.image_generation_commands import (
    create_image_generation_commands_router, image_command_catalog, image_command_handlers,
)
from services.workspace_commands import catalog as workspace_command_catalog

from services.scene_commands import SceneCommands, command_catalog as scene_command_catalog
from routers.scene_commands import create_scene_commands_router
_scene_commands = SceneCommands(_workspace_dir)
api.include_router(create_scene_commands_router(_scene_commands))
from routers.world3d_export import create_world3d_export_router, bind_world3d_renderer_origin
from services.world3d_export import World3DExportService, command_catalog as world3d_export_catalog, command_handlers as world3d_export_handlers
from routers.world3d_templates import create_world3d_templates_router
from services.world3d_template_commands import command_catalog as world3d_template_catalog, command_handlers as world3d_template_handlers
_world3d_export = World3DExportService(
    workspace_dir=_workspace_dir,
    registry_for=_task_registry,
    app_url=os.environ.get("HOCUS_APP_URL", ""),
    uploads_dir=lambda: os.path.join(os.getcwd(), "uploads"),
)
bind_world3d_renderer_origin(api, _world3d_export)
api.include_router(create_world3d_export_router(_world3d_export))
api.include_router(create_world3d_templates_router(_workspace_dir))
from services.scene2d_export import Scene2DExportService, command_catalog as scene2d_export_catalog, command_handlers as scene2d_export_handlers
from routers.scene2d_export import create_scene2d_export_router
_scene2d_export = Scene2DExportService(workspace_dir=_workspace_dir, registry_for=_task_registry,
                                       app_url=os.environ.get("HOCUS_APP_URL", ""),
                                       uploads_dir=lambda: os.path.join(os.getcwd(), "uploads"))
bind_world3d_renderer_origin(api, _scene2d_export)
api.include_router(create_scene2d_export_router(_scene2d_export))
from services.montage_documents import MontageStore
from services.montage_commands import MontageCommands, command_catalog as montage_command_catalog
from routers.montages import create_montages_router
from services.montage_shots import ShotBoard
from services.wangp_submission import JsonRequest as _ShotRequest
_montage_store = MontageStore(_workspace_dir)


async def _submit_shot_generation(params: dict) -> dict:
    return await generate(_ShotRequest(params))


def _shot_job_status(job_id: str) -> dict | None:
    return snapshot_job(_jobs[job_id]) if job_id in _jobs else None


_montage_commands = MontageCommands(_montage_store, start_export=start_video_editor_export,
                                    get_export=get_video_editor_export,
                                    shots=ShotBoard(_montage_store, workspace_dir=_workspace_dir,
                                                    submit=_submit_shot_generation, job_status=_shot_job_status))
api.include_router(create_montages_router(_montage_commands))
from services.scene_packages import make_workspace_reader as _template_reader
from services.template_library import TemplateLibrary, resolve_template_library_root
from services.template_commands import TemplateCommands, command_catalog as template_command_catalog
from routers.templates import create_templates_router
from services.media_options import command_catalog as media_options_catalog, command_handlers as media_options_handlers


def _media_options_sources():
    return list_models(detail=True)["models"], get_services_config(), _production_profile_response()


from services.template_community import CommunityIndex
_template_library = TemplateLibrary(
    resolve_template_library_root(_app_dir), workspace_dir=_workspace_dir,
    reader=_template_reader(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads")))
_template_commands = TemplateCommands(_template_library, CommunityIndex(_template_library))
api.include_router(create_templates_router(_template_commands))
from services.scene_documents import command_catalog as scene_document_catalog, command_handlers as scene_document_handlers
from services.scene2d_validate import command_catalog as scene2d_validate_catalog, command_handlers as scene2d_validate_handlers
from services.video2d_catalogs import command_catalog as video2d_catalog, command_handlers as video2d_catalog_handlers
from services.video2d_catalogs import query_operations as video2d_query_operations, query_handlers as video2d_query_handlers
from routers.video2d_catalog import create_video2d_catalog_router, create_video2d_template_commands_router
api.include_router(create_video2d_catalog_router())
api.include_router(create_video2d_template_commands_router(lambda: _mcp_handlers))
from services.video2d_compile import command_catalog as video2d_compile_catalog, command_handlers as video2d_compile_handlers
from services.video2d_preview import command_catalog as video2d_preview_catalog, command_handlers as video2d_preview_handlers
from services.video2d_edit import command_catalog as video2d_edit_catalog, command_handlers as video2d_edit_handlers
from routers.video2d_edit import create_video2d_edit_router
api.include_router(create_video2d_edit_router())
from services.scene_asset_facts import command_catalog as scene_asset_facts_catalog, command_handlers as scene_asset_facts_handlers

from services.mcp_access import McpAccess
from routers.mcp_access import create_mcp_access_router
_mcp_access = McpAccess(os.path.join(os.path.dirname(__file__), 'settings', 'mcp-access.json'))
# Clients that only speak OAuth (ChatGPT connectors) sign in once with the same key; see services/mcp_oauth.py.
from services.mcp_oauth import McpOAuth
from services.mcp_profiles import PROFILES as _MCP_PROFILES
from routers.mcp_oauth import create_mcp_oauth_router
_mcp_oauth = McpOAuth(os.path.join(os.path.dirname(__file__), 'settings', 'mcp-oauth.json'), _mcp_access.token, set(_MCP_PROFILES))
api.include_router(create_mcp_access_router(_mcp_access, on_change=_mcp_oauth.revoke_all))
api.include_router(create_mcp_oauth_router(_mcp_oauth))
from routers.music_productions import create_music_productions_router
from services.local_mcp import LocalMcp
_local_mcp = LocalMcp(lambda: _mcp_handlers)

async def _bind_local_mcp() -> None:
    _local_mcp.bind_loop(asyncio.get_running_loop())

api.add_event_handler("startup", _bind_local_mcp)
api.include_router(create_music_productions_router(
    workspace_dir=_workspace_dir,
    uploads_dir=lambda: os.path.join(os.getcwd(), "uploads"),
    app_url=lambda: _scene2d_export.app_url or "",
    token=_mcp_access.token,
    mcp=_local_mcp.call,
))

_image_generation_commands = create_image_generation_commands(globals())
api.include_router(create_image_generation_commands_router(_image_generation_commands))
from routers.wizard_workflow_executor import create_wizard_workflow_executor_router
from services.wizard_workflow_executor import WizardWorkflowExecutor, catalog as wizard_workflow_catalog, command_handlers as wizard_workflow_command_handlers
_wizard_workflow_executor = WizardWorkflowExecutor(
    workspace_dir=_workspace_dir,
    submit_command=_image_generation_commands.submit,
    command_receipt=_image_generation_commands.receipt,
    get_task=lambda workspace, task_id: _task_registry(workspace).get(task_id),
)
api.include_router(create_wizard_workflow_executor_router(_wizard_workflow_executor, list_workspaces=_list_workspaces))
from routers.audio_shorten import (
    command_catalog as audio_shorten_catalog,
    command_handlers as audio_shorten_handlers,
    create_audio_shorten_router,
)
from services.job_leftovers import (
    JobLeftovers,
    command_catalog as job_leftover_catalog,
    command_handlers as job_leftover_handlers,
)

def _resolve_shorten_source(source: str, workspace: str) -> str:
    return _resolve_request_media_path(source, workspace=workspace, kinds=("audio",))

_audio_shorten_handlers = audio_shorten_handlers(_resolve_shorten_source, _workspace_dir)
api.include_router(create_audio_shorten_router(
    resolve_source=_resolve_shorten_source,
    workspace_dir=_workspace_dir,
))
from services.assets_upload import command_catalog as assets_upload_catalog
from services.assets_upload import command_handlers as assets_upload_handlers

_assets_upload_handlers = assets_upload_handlers(
    _workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"),
)
from routers.publish_presets import create_publish_router
api.include_router(create_publish_router(
    resolve_source=lambda source, workspace: _resolve_request_media_path(source, workspace=workspace, kinds=("video", "audio")),
    workspace_dir=_workspace_dir,
))
from services.jobs_wait import command_catalog as jobs_wait_catalog, command_handlers as jobs_wait_handlers
from services.jobs_cancel import command_catalog as jobs_cancel_catalog, command_handlers as jobs_cancel_handlers
from services.song_analysis import command_catalog as audio_analysis_catalog, command_handlers as audio_analysis_handlers
from services.lipsync_qa import command_catalog as lipsync_qa_catalog, command_handlers as lipsync_qa_handlers
from services.speech_qa import command_catalog as speech_qa_catalog, command_handlers as speech_qa_handlers
from services.qa_accent import command_catalog as qa_accent_catalog, command_handlers as qa_accent_handlers
_qa_accent_handlers = qa_accent_handlers(_workspace_dir)
from services.export_qa import command_catalog as export_qa_catalog, command_handlers as export_qa_handlers
from services.export_qa import remember_on_task as remember_export_qa

def _remember_export_qa(workspace, intent_id, report):
    return remember_export_qa(_world3d_export._registry(workspace), intent_id, report)

_export_qa_handlers = export_qa_handlers(_workspace_dir, _remember_export_qa)
from services.music_production import command_catalog as music_production_catalog, command_handlers as music_production_handlers
from services.production_review import command_catalog as production_review_catalog, command_handlers as production_review_handlers
from services.series_commands import command_catalog as series_command_catalog, command_handlers as series_command_handlers
from services.game_commands import command_catalog as game_command_catalog, command_handlers as game_command_handlers
_jobs_wait_handlers = jobs_wait_handlers(get_status, lambda job_id: _jobs.get(job_id))
_jobs_cancel_handlers = jobs_cancel_handlers(_control_canonical_task, _task_registry, _list_workspaces, lambda job_id: _jobs.get(job_id), _sync_canonical_tasks)
from services.studio_key import command_catalog as studio_key_catalog, command_handlers as studio_key_handlers
_studio_key_handlers = studio_key_handlers(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"))
# media.frame, media.compose, audio.trim, assets.import_from_workspace (services/production_media_commands.py).
from services.production_media_commands import command_catalog as production_media_catalog, command_handlers as production_media_handlers
_production_media_handlers = production_media_handlers(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"))
from routers.production_media import create_production_media_router
api.include_router(create_production_media_router({**_production_media_handlers, "studio.key": _studio_key_handlers["studio.key"]}))
from routers.character_tools import create_character_tools_router

api.include_router(create_character_tools_router(
    studio_key=_studio_key_handlers["studio.key"], speech_qa=speech_qa_handlers(_workspace_dir)["qa.speech"],
    accent=_qa_accent_handlers["qa.accent"],
))
from services.clip_align import command_catalog as clip_align_catalog, command_handlers as clip_align_handlers
_clip_align_handlers = clip_align_handlers(_workspace_dir)
from services.montage_preview import command_catalog as montage_preview_catalog
from services.montage_preview import command_handlers as montage_preview_handlers
_montage_preview_handlers = montage_preview_handlers(_montage_store, lambda: _scene2d_export.app_url)


def _prepare_generation_leftovers(records):
    _image_generation_commands.restore_recovery(item["name"] for item in _list_workspaces())
    return _image_generation_commands.filter_recovery(records)


def _start_recovered_generation(job):
    threading.Thread(
        target=_run_generation_with_preparation,
        args=(job["id"],),
        name=f"recovered-generation-{job['id']}",
        daemon=False,
    ).start()


def _discard_generation_leftover(record):
    _image_generation_commands.discard_recovery([record])
    _durable_generation_queue.remove(str(record.get("id") or ""))


from services.scene_export_leftovers import SceneExportLeftovers

_job_leftovers = JobLeftovers(
    queue=_durable_generation_queue,
    jobs=_jobs,
    lock=_queue_recovery_lock,
    prepare=_prepare_generation_leftovers,
    rehydrate=_queue_recovered_generation,
    start=_start_recovered_generation,
    discard_record=_discard_generation_leftover,
    exports=SceneExportLeftovers(
        services=[_world3d_export, _scene2d_export], list_workspaces=_list_workspaces, registry_for=_task_registry,
    ),
)
_image_generation_commands.leftover_receipt_lookup = _job_leftovers.receipt_for
# generate() reads _job_leftovers from its own module globals.
import services.studio_generate as _studio_generate
_studio_generate._job_leftovers = _job_leftovers


def _release_intermediates_at_startup() -> None:
    """Frames of published exports, raw voice takes and stale temp folders go; live and resumable work is kept."""
    from services.workspace_cleanup import startup_cleanup
    from services.world3d_export import staging_token
    names = [item.get("name") for item in _list_workspaces() if isinstance(item, dict) and item.get("name")]
    startup_cleanup(names, _workspace_dir, _task_registry, {_world3d_export.operation, _scene2d_export.operation}, staging_token)


threading.Thread(target=_release_intermediates_at_startup, name="workspace-cleanup", daemon=True).start()
_job_leftover_handlers = job_leftover_handlers(_job_leftovers)
# qa.people C3 duplicate-person flag: register beside the MCP router (feat/qa-people).
from services.qa_people import command_catalog as qa_people_catalog, command_handlers as qa_people_handlers
_qa_people_handlers = qa_people_handlers(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"))
from services.model3d_commands import command_catalog as model3d_command_catalog, command_handlers as model3d_command_handlers
_model3d_command_handlers = model3d_command_handlers(
    generate=generate_model3d, status=model3d_job_status,
    journal_path=os.path.join(os.getcwd(), "settings", "model3d-mcp-requests.sqlite3"),
)
from services.model3d_rig_commands import command_catalog as model3d_rig_catalog, command_handlers as model3d_rig_handlers
_model3d_rig_handlers = model3d_rig_handlers(
    generate=generate_rig, status=rig_job_status,
    journal_path=os.path.join(os.getcwd(), "settings", "model3d-rig-mcp-requests.sqlite3"),
)
from routers.model3d_compose import command_catalog as model3d_compose_catalog, command_handlers as model3d_compose_handlers, create_model3d_compose_router
_model3d_compose_handlers = model3d_compose_handlers(_workspace_dir, os.path.join(os.getcwd(), "settings", "model3d-compose.sqlite3"))
api.include_router(create_model3d_compose_router(_model3d_compose_handlers))
from routers.model3d_animate import command_catalog as model3d_animate_catalog, command_handlers as model3d_animate_handlers, create_model3d_animate_router
_model3d_animate_handlers = model3d_animate_handlers(_workspace_dir, os.path.join(os.getcwd(), "settings", "model3d-animate.sqlite3"))
api.include_router(create_model3d_animate_router(_model3d_animate_handlers, _workspace_dir))
from services.series_native_render import NativeRenderDeps, SeriesNativeRender
from routers.series_native_render import create_series_native_render_router
from services.character_kit_library import read_character_kit_library as _read_kit_library

def _change_series(workspace: str, series_id: str, change) -> dict:
    """Apply ``change(series)`` under the library lock and return the stored series (KeyError if missing)."""
    resolved = _series_library_workspace(workspace)
    with _series_library_lock:
        library = _read_series_workspace(resolved)
        series = library["seriesById"][series_id]
        change(series)
        series["revision"] = int(series.get("revision") or 1) + 1
        series["updatedAt"] = _series_iso_now()
        stored = _write_series_workspace(resolved, library)
    return stored["seriesById"][series_id]


def _change_series_episode(workspace: str, series_id: str, episode_id: str, change) -> dict:
    """Apply ``change(series, episode)`` under the library lock and return the stored series (KeyError if missing)."""
    return _change_series(workspace, series_id, lambda series: change(series, series["episodesById"][episode_id]))


def _read_series_episode(workspace: str, series_id: str, episode_id: str) -> tuple[dict, dict]:
    series = _read_series_workspace(_series_library_workspace(workspace))["seriesById"][series_id]
    return series, series["episodesById"][episode_id]


def _set_series_shot_duration(workspace: str, series_id: str, episode_id: str, shot_id: str, seconds: float) -> None:
    """A server-rendered take sets its shot's length, as the editor does before importing."""
    def change(_series: dict, episode: dict) -> None:
        for shot in episode["shots"]:
            if shot["id"] == shot_id:
                shot["durationSeconds"] = round(seconds, 3)
    _change_series_episode(workspace, series_id, episode_id, change)


def _set_series_version_take(workspace: str, series_id: str, episode_id: str, language: str, shot_id: str, attempt_id: str) -> None:
    """Approve a take in a language version; the original's approval is untouched."""
    from services.series_language_versions import set_version_take
    # Only the server render approves through here (``approve: true``): the take says so.
    _change_series_episode(workspace, series_id, episode_id,
                           lambda _series, episode: set_version_take(episode, language, shot_id, attempt_id, "server"))


def _set_series_version_duration(workspace: str, series_id: str, episode_id: str, language: str, shot_id: str, seconds: float) -> None:
    """A version's server take sets that version's shot length; the original keeps its own."""
    from services.series_language_versions import set_version_duration
    _change_series_episode(workspace, series_id, episode_id, lambda _series, episode: set_version_duration(episode, language, shot_id, seconds))


def _translate_series_version(prompt: str, system_prompt: str, schema: dict):
    return _generate_comic_director_json(prompt=prompt, system_prompt=system_prompt, schema=schema, max_new_tokens=8000,
                                         stage="Series Lab translation", llm_override=None)


from routers.series_language_versions import create_series_language_versions_router
api.include_router(create_series_language_versions_router(
    change_episode=_change_series_episode, read_episode=_read_series_episode, translate=_translate_series_version,
))
from routers.series_review import create_series_review_router
api.include_router(create_series_review_router(
    resolve_workspace=_series_library_workspace, lock=_series_library_lock, read_library=_read_series_workspace,
    write_library=_write_series_workspace, iso_now=_series_iso_now,
))


import services.scene_favorites as _scene_favorites_service
_scene_favorites_service._read_kit_library = _read_kit_library


from services.video2d_character_ops import bind_kit_reader as _bind_scene_kit_reader
_bind_scene_kit_reader(_character_kit_for_scene)

# Server jobs call the same tool handlers as MCP clients, in process (no token needed).
_series_native_render = SeriesNativeRender(NativeRenderDeps(
    call=_local_mcp.call, workspace_dir=_workspace_dir,
    read_library=lambda workspace: _read_series_workspace(_series_library_workspace(workspace)),
    read_kits=lambda workspace: _read_kit_library(_workspace_dir(workspace)).get("kits") or {},
    set_shot_duration=_set_series_shot_duration,
    set_version_take=_set_series_version_take,
    set_version_duration=_set_series_version_duration,
))
api.include_router(create_series_native_render_router(_series_native_render, _local_mcp.bind_loop))
from routers.series_shot_edit import create_series_shot_edit_router
api.include_router(create_series_shot_edit_router(
    change_series=_change_series, read_library=lambda workspace: _read_series_workspace(_series_library_workspace(workspace)),
    read_kits=lambda workspace: _read_kit_library(_workspace_dir(workspace)).get("kits") or {}, workspace_dir=_workspace_dir,
    call=_local_mcp.call, bind_loop=_local_mcp.bind_loop,
    plan_changes=lambda prompt, system, schema: _generate_comic_director_json(
        prompt=prompt, system_prompt=system, schema=schema, max_new_tokens=3000, stage="Series Lab shot edit", llm_override=None)))
from services.series_line_voice import SeriesLineVoice
from routers.series_shot_inspector import create_series_shot_inspector_router
api.include_router(create_series_shot_inspector_router(
    voices=SeriesLineVoice(_series_native_render, read_library=lambda workspace: _read_series_workspace(_series_library_workspace(workspace)),
                           read_kits=lambda workspace: _read_kit_library(_workspace_dir(workspace)).get("kits") or {}),
    read_library=lambda workspace: _read_series_workspace(_series_library_workspace(workspace)), workspace_dir=_workspace_dir,
    call=_local_mcp.call, bind_loop=_local_mcp.bind_loop))
from routers.series_guide import create_series_guide_router
api.include_router(create_series_guide_router(
    read_library=lambda workspace: _read_series_workspace(_series_library_workspace(workspace)),
    read_kits=lambda workspace: _read_kit_library(_workspace_dir(workspace)).get("kits") or {}, workspace_dir=_workspace_dir,
))
from services.series_produce import ProduceDeps, SeriesProduce
from routers.series_produce import create_series_produce_router
api.include_router(create_series_produce_router(
    SeriesProduce(ProduceDeps(call=_local_mcp.call, workspace_dir=_workspace_dir,
                              read_library=lambda workspace: _read_series_workspace(_series_library_workspace(workspace)),
                              stale_shots=_series_native_render.stale_shots, review_blockers=_series_native_render.review_blockers)),
    call=_local_mcp.call, bind_loop=_local_mcp.bind_loop,
    read_library=lambda workspace: _read_series_workspace(_series_library_workspace(workspace)),
    read_kits=lambda workspace: _read_kit_library(_workspace_dir(workspace)).get("kits") or {}, workspace_dir=_workspace_dir,
))


def _read_world3d_scene(workspace: str, name: str) -> dict:
    """A saved Video 3D gallery scene, or a ``w3d-`` working scene, by name."""
    from services.world3d_scenes import World3DSceneError, inspect_scene
    if name.startswith("w3d-"):
        try:
            return inspect_scene(workspace, name, _workspace_dir)["document"]
        except World3DSceneError as error:
            raise KeyError(name) from error
    from services.scene_documents import SceneDocumentError, get_document
    try:
        return get_document(workspace, name, workspace_dir=_workspace_dir)["document"]
    except SceneDocumentError as error:
        raise KeyError(name) from error


from routers.series_plates import create_series_plates_router
from services.series_plates import PlateDeps, SeriesPlates
api.include_router(create_series_plates_router(SeriesPlates(PlateDeps(
    call=_local_mcp.call, read_series=lambda workspace, series_id: _read_series_workspace(_series_library_workspace(workspace))["seriesById"][series_id],
    change_series=_change_series, read_scene=_read_world3d_scene,
)), _local_mcp.bind_loop))

from services.image_remove_background import command_catalog as remove_bg_catalog, command_handlers as remove_bg_handlers
from routers.image_remove_background import create_image_remove_background_router
api.include_router(create_image_remove_background_router(remove_bg_handlers(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"), _start_remove_background_job, _register_manual_generation_job)))
from routers.series_sets import create_series_sets_router, SeriesSets, command_catalog as series_sets_catalog
_series_sets = SeriesSets(_workspace_dir, lambda workspace, series_id: _read_series_workspace(_series_library_workspace(workspace))["seriesById"][series_id], _change_series, _local_mcp.call)
api.include_router(create_series_sets_router(_series_sets, _local_mcp.bind_loop))
from routers.props import create_props_router, PropService, command_catalog as prop_catalog
_props = PropService(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"), _local_mcp.call)
api.include_router(create_props_router(_props))
from routers.scene3d_items import create_scene3d_items_router, ItemService, command_catalog as item_catalog
_items = ItemService(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"), _local_mcp.call)
api.include_router(create_scene3d_items_router(_items))
from services.set_commands import command_catalog as set_catalog, command_handlers as set_handlers
from routers.set_catalog import create_set_catalog_router
api.include_router(create_set_catalog_router())
from services.agent_activity import AgentActivity
from routers.wizard_activity import create_wizard_activity_router
_agent_activity = AgentActivity(_task_registry, _get_active_workspace)
api.include_router(create_wizard_activity_router(_agent_activity))
api.include_router(create_wangp_mcp_router(
    token_getter=_mcp_access.token, on_mutation=_agent_activity.record, local_mcp=_local_mcp,
    handlers=(_mcp_handlers := {"models": mcp_model_list, "models.list": mcp_model_list, "processors": wangp_capabilities, "status": get_status,
              "generate": generate, "recast": recast_endpoint, "upscale": tools_upscale,
              **remove_bg_handlers(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"), _start_remove_background_job, _register_manual_generation_job), **_series_sets.handlers(), **_items.handlers(), **_props.handlers(), **set_handlers(), **wangp_agent_handlers(api), **lips_creator_handlers(_workspace_dir), **image_command_handlers(_image_generation_commands), **wizard_workflow_command_handlers(_wizard_workflow_executor), **world3d_export_handlers(_world3d_export), **world3d_template_handlers(_workspace_dir), **_scene_commands.handlers(), **_montage_commands.handlers(), **_template_commands.handlers(), **media_options_handlers(_media_options_sources), **scene_document_handlers(_workspace_dir), **scene_asset_facts_handlers(_workspace_dir), **scene2d_export_handlers(_scene2d_export), **scene2d_validate_handlers(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads")), **video2d_catalog_handlers(), **video2d_query_handlers(), **video2d_compile_handlers(_workspace_dir), **video2d_preview_handlers(lambda: _scene2d_export.app_url, _workspace_dir), **video2d_edit_handlers(), **_audio_shorten_handlers, **_assets_upload_handlers, **_job_leftover_handlers, **_jobs_wait_handlers, **_jobs_cancel_handlers, **_qa_people_handlers, **_studio_key_handlers, **_production_media_handlers, **_clip_align_handlers, **_montage_preview_handlers, **audio_analysis_handlers(_workspace_dir), **lipsync_qa_handlers(_workspace_dir), **speech_qa_handlers(_workspace_dir), **_qa_accent_handlers, **_export_qa_handlers,
              **music_production_handlers(_workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"), lambda: _scene2d_export.app_url or "", _mcp_access.token, mcp=_local_mcp.call), **production_review_handlers(_workspace_dir), **series_command_handlers(lambda: _scene2d_export.app_url or "", _workspace_dir, lambda: os.path.join(os.getcwd(), "uploads")), **game_command_handlers(lambda: _scene2d_export.app_url or "", _workspace_dir, lambda: os.path.join(os.getcwd(), "uploads")), **_model3d_command_handlers, **_model3d_rig_handlers, **_model3d_compose_handlers, **_model3d_animate_handlers}),
    journal_path=os.path.join(os.path.dirname(__file__), "settings", "wangp-mcp-requests.sqlite3"),
    profiles=_MCP_PROFILES, oauth=_mcp_oauth,
    command_operations=[*series_sets_catalog(), *item_catalog(), *prop_catalog(), *remove_bg_catalog(), *set_catalog(), *lips_creator_catalog(), *scene_command_catalog(), *workspace_command_catalog()["operations"], *image_command_catalog(
        adapter.catalog for adapter in _image_generation_commands.operations.values()), *wizard_workflow_catalog(), *world3d_export_catalog(), *world3d_template_catalog(), *montage_command_catalog(), *template_command_catalog(), *media_options_catalog(), *scene_document_catalog(), *scene_asset_facts_catalog(), *scene2d_export_catalog(), *scene2d_validate_catalog(), *video2d_catalog(), *video2d_query_operations(), *video2d_compile_catalog(), *video2d_preview_catalog(), *video2d_edit_catalog(), *audio_shorten_catalog(), *assets_upload_catalog(), *job_leftover_catalog(), *jobs_wait_catalog(), *jobs_cancel_catalog(), *qa_people_catalog(), *studio_key_catalog(), *production_media_catalog(), *clip_align_catalog(), *montage_preview_catalog(), *audio_analysis_catalog(), *lipsync_qa_catalog(), *speech_qa_catalog(), *qa_accent_catalog(), *export_qa_catalog(), *music_production_catalog(), *production_review_catalog(), *series_command_catalog(), *game_command_catalog(), *model3d_command_catalog(), *model3d_rig_catalog(), *model3d_compose_catalog(), *model3d_animate_catalog()],
))
from routers.system_capabilities import create_system_capabilities_router
api.include_router(create_system_capabilities_router())
from routers.about import create_about_router
api.include_router(create_about_router(os.path.normpath(os.path.join(_app_dir, "..", "ui", "dist"))))
from routers.game_library import create_game_library_router
_game_library_lock = threading.RLock()
api.include_router(create_game_library_router(workspace_dir=_workspace_dir, lock=_game_library_lock))
from services.game_produce import build_produce
from routers.game_produce import create_game_produce_router
_game_produce = build_produce(_local_mcp.call, lambda: _scene2d_export.app_url or "", _mcp_access.token, _workspace_dir, _game_library_lock)
api.include_router(create_game_produce_router(_game_produce, call=_local_mcp.call, bind_loop=_local_mcp.bind_loop, read_game=_game_produce.deps.read_game))

from routers.example_assets import create_example_assets_router
api.include_router(create_example_assets_router())
from routers.asset_library import create_asset_library_router
api.include_router(create_asset_library_router())
from routers.writing_guide import create_writing_guide_router
api.include_router(create_writing_guide_router(
    ensure_llm_loaded=_ensure_llm_loaded, writing_override=_comic_writing_llm,
))

# Optional production renderer: pass a callable that drives the existing
# Video 3D exportFlow through a process-owned headless browser. Closing a
# user tab must not join or kill that worker.

# ============================================================================
# Serve React build at /
# ============================================================================

# Force correct MIME types for the module bundle. Python's mimetypes
# module reads the WINDOWS REGISTRY, and machines where an installer
# hijacked `.js` to text/plain make StaticFiles serve the bundle with a
# type the browser's strict ES-module MIME check refuses — assets return
# 200 but never execute, and the UI is a silent black screen (community
# report: assets 200/304 in the terminal, zero API calls after).
# add_type() runs after mimetypes' lazy init, so these entries override
# whatever the registry says, on every machine.
import mimetypes as _mimetypes
_mimetypes.add_type("text/javascript", ".js")
_mimetypes.add_type("text/javascript", ".mjs")
_mimetypes.add_type("text/css", ".css")
_mimetypes.add_type("image/svg+xml", ".svg")

_ui_dist = os.path.normpath(os.path.join(_app_dir, "..", "ui", "dist"))
from services.ui_distribution import build_status as _ui_build_status, recovery_html as _ui_recovery_html
_ui_ready = _ui_build_status()["ready"]
if _ui_ready:
    api.mount("/", StaticFiles(directory=_ui_dist, html=True))
    print(f"[HocusPocus Lab] React UI serving from {_ui_dist}")
else:
    @api.get("/")
    def index():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(_ui_recovery_html(), status_code=503, headers={"Cache-Control": "no-store"})
    print(f"[HocusPocus Lab] React UI missing or incomplete at {_ui_dist}. Use Repair Web UI, then restart. Serving API only.")


# ============================================================================
# Entry point
# ============================================================================

def run_server():
    def prepare(display_host, port):
        # Confirm the polling filter immediately before Uvicorn configures logging.
        install_quiet_access_filter()
        from services.production_resume import resume_on_startup
        # Local tool coroutines need the serving event loop, bound by _bind_local_mcp first.
        api.add_event_handler("startup", lambda: resume_on_startup(
            _list_workspaces, _workspace_dir, lambda: os.path.join(os.getcwd(), "uploads"),
            lambda: _scene2d_export.app_url or f"http://{display_host}:{port}", _mcp_access.token, mcp=_local_mcp.call))

    from services.server_entry import run
    run(
        api,
        ui_ready=_ui_ready,
        endpoint_path=os.path.join(os.path.dirname(__file__), "settings", "server-endpoint.json"),
        prepare=prepare,
        lan_messages=describe_lan_auth_startup(),
    )



# ``app/launch.py`` loads this module with ``runpy`` and sets its name to
# ``__main__`` for the Pinokio server entry point.  Keep the executable guard
# here so that the deferred runtime does not merely import, print setup logs,
# and exit before emitting the URL that Pinokio captures.
if __name__ == "__main__":
    run_server()
