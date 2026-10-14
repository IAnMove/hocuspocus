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


# Preparation, simulation and the local GPU handoff live in
# services/generation_preparation.py. The hook is installed here; bind() runs
# after the image-command service exists, before any request.
from services.generation_preparation import (
    _prepare_local_gpu_owner,
    _run_generation_with_preparation,
    _run_simulated_generation,
    bind as bind_generation_preparation,
)


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


# Native and legacy H3 release, and the Wan interrupt, live in
# services/generation_h3_release.py. The lock alias is the holder's one RLock.
from services.generation_h3_release import (
    _cancel_h3_idle_release,
    _h3_idle_release,
    _interrupt_wan_model,
    _release_h3_when_queue_allows,
    _release_legacy_h3_when_queue_allows,
    bind as bind_generation_h3_release,
)

bind_generation_h3_release(
    _active_gen_states=_active_gen_states,
    _is_legacy_h3_model=_is_legacy_h3_model,
    _is_minimax_h3_model=_is_minimax_h3_model,
    _pending_gpu_jobs=_pending_gpu_jobs,
    wgp=wgp,
)
_h3_idle_release_lock = _h3_idle_release.lock

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

# Official replacement-specific SCAIL-2 Relighting LoRA. Upstream publishes a
# SAT/PyTorch checkpoint, so Maestro downloads the immutable revision, verifies
# its official hash, and converts it once to Wan safetensors on first use.
_RECAST_RELIGHTING_LORA_FILENAME = "scail2_relighting_lora.safetensors"
_RECAST_RELIGHTING_LORA_REVISION = "150cc0ca4e98e50e60b9295dacde39442fdccab2"
_RECAST_RELIGHTING_LORA_REMOTE_PATH = "model/relighting-lora.pt"
_RECAST_RELIGHTING_LORA_SHA256 = "80d338a7969c1b286c8f5c4996b37eb198d0864837fecb6c87c106ca74571a2b"
_RECAST_RELIGHTING_LORA_SIZE = 1_227_381_060


def _normalize_recast_lora_settings(
    activated_loras, loras_multipliers, use_relighting,
):
    """Return aligned, single-phase LoRA settings for a Recast run.

    Wan exposes as many as three LoRA phases in the shared Studio UI, while
    SCAIL-2 Recast deliberately runs one guidance phase. Old/stale UI state
    can therefore contain ``1;1;1`` even when Recast has only one selected
    LoRA. Pair multipliers with their LoRA *before* appending the managed
    relighting LoRA, discard orphan multipliers, and retain only the first
    phase for every selected LoRA.

    Selecting the official relighting LoRA directly in Advanced is also an
    explicit opt-in. The main Recast toggle adds it at 1.0 only when Advanced
    has not already supplied it, preserving a user-adjusted Advanced weight.
    """

    if isinstance(activated_loras, (list, tuple)):
        source_loras = [
            str(item).strip()
            for item in activated_loras
            if isinstance(item, str) and item.strip()
        ]
    else:
        source_loras = []

    if isinstance(loras_multipliers, (list, tuple)):
        source_multipliers = [
            str(item).strip() for item in loras_multipliers
        ]
    else:
        source_multipliers = []
        for line in str(loras_multipliers or "").replace("\r", "").split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            source_multipliers.extend(line.replace("|", " ").split())

    def _single_phase_multiplier(index):
        if index >= len(source_multipliers):
            return "1.0"
        first_phase = source_multipliers[index].split(";", 1)[0].strip()
        return first_phase or "1.0"

    def _lora_key(value):
        return str(value).replace("\\", "/").rsplit("/", 1)[-1].casefold()

    normalized_loras = []
    normalized_multipliers = []
    seen = set()
    for index, name in enumerate(source_loras):
        key = _lora_key(name)
        if key in seen:
            continue
        seen.add(key)
        normalized_loras.append(name)
        normalized_multipliers.append(_single_phase_multiplier(index))

    relighting_key = _lora_key(_RECAST_RELIGHTING_LORA_FILENAME)
    if use_relighting and relighting_key not in seen:
        normalized_loras.append(_RECAST_RELIGHTING_LORA_FILENAME)
        normalized_multipliers.append("1.0")
        seen.add(relighting_key)

    return (
        normalized_loras,
        " ".join(normalized_multipliers),
        relighting_key in seen,
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


def _resolve_recast_media(raw, workspace):
    """Resolve a media reference the way edit endpoints do: absolute path
    first, then workspace outputs, then uploads/, then outputs/."""
    if not raw:
        return None
    raw = str(raw)
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    for base in (
        _workspace_dir(workspace),
        os.path.join(os.getcwd(), "uploads"),
        os.path.join(os.getcwd(), "outputs"),
    ):
        cand = os.path.join(base, os.path.basename(raw))
        if os.path.isfile(cand):
            return cand
    if os.path.isfile(raw):
        return raw
    return None


_RECAST_MASK_COLORS = [
    (0, 0, 255),
    (255, 0, 0),
    (0, 255, 0),
    (255, 0, 255),
    (0, 255, 255),
]

# Extra SAM3 tracking colors used by native bystander mapping and the adaptive
# protection fallback. SCAIL-2 can condition at most five people, but the
# source or generated scene may contain additional people that must remain
# distinguishable while Maestro selects the relevant tracks.
_RECAST_PROTECTION_COLORS = _RECAST_MASK_COLORS + [
    (255, 255, 0),
    (255, 128, 0),
    (128, 0, 255),
    (0, 192, 128),
    (255, 64, 128),
]

_RECAST_FAST_MODEL_TYPE = "scail2_14B_recast_fast"
_RECAST_LEGACY_FAST_MODEL_TYPE = "scail2_14B_fast"
_RECAST_RESOLUTION_PROFILES = {
    # Width/height describe the landscape budget. The source video's
    # orientation and aspect ratio are applied below on a 32px boundary.
    "480p": (832, 480),
    "512p": (896, 512),
    "704p": (1280, 704),
}
_RECAST_WARMUP_FRAMES = 8
_RECAST_U2NET_CACHE_LIMIT = 8
_recast_u2net_session = None
_recast_u2net_session_lock = threading.Lock()
_recast_u2net_run_lock = threading.Lock()
_recast_u2net_cache_lock = threading.Lock()
_recast_u2net_cache = {}


def _normalize_recast_person_count(value):
    """Clamp the SCAIL-2 person slot count to its supported 1-5 range."""
    try:
        return min(5, max(1, int(value)))
    except (TypeError, ValueError):
        return 1


def _normalize_recast_resolution_profile(value):
    """Return a supported SCAIL-2 edit resolution without changing models."""
    normalized = str(value or "").strip().lower().replace(" ", "")
    aliases = {
        "480": "480p",
        "832x480": "480p",
        "fast": "480p",
        "512": "512p",
        "896x512": "512p",
        "quality": "512p",
        "704": "704p",
        "1280x704": "704p",
        "high": "704p",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in _RECAST_RESOLUTION_PROFILES:
        return "480p"
    return normalized


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


def _recast_window_size_for_profile(resolution_profile, total_vram_gb):
    """Choose a VAE-aligned SCAIL-2 edit window without changing model steps.

    SCAIL-2 activation pressure scales approximately with spatial pixels times
    frames in the active window. A 1280x704 frame has almost twice the pixels
    of 896x512, so retaining the ordinary 81-frame window would nearly double
    the non-streamable attention workspace. Shorter 4n+1 windows keep 704p
    practical while MMGP independently streams model weights.

    A zero return means the detected GPU is below the currently supported
    704p floor. Unknown hardware uses the conservative middle window rather
    than rejecting a valid NVIDIA setup because a probe was unavailable.
    """
    profile = _normalize_recast_resolution_profile(resolution_profile)
    if profile != "704p":
        return 81
    try:
        vram_gb = float(total_vram_gb)
    except (TypeError, ValueError):
        vram_gb = 0.0
    if vram_gb <= 0:
        return 41
    if vram_gb >= 24.0:
        return 49
    if vram_gb >= 20.0:
        return 41
    if vram_gb >= 16.0:
        return 33
    return 0


def _build_recast_prompt(raw_prompt, person_count, enhance=True):
    """Return an idempotent finished-video description for SCAIL-2.

    Upstream explicitly asks for a description of the completed video, not an
    editing command. Convert the most common ``replace X with Y`` phrasing and
    append descriptive continuity language without imperative "keep" clauses.
    When enhancement is disabled, preserve the user's prompt verbatim apart
    from surrounding whitespace so A/B tests can isolate the model behavior.
    """
    import re

    prompt = str(raw_prompt or "").strip()
    if not enhance:
        if not prompt:
            raise ValueError(
                "Enter a Recast prompt when automatic prompt enhancement is disabled."
            )
        return prompt

    detail_marker = "The surrounding people, environment, camera framing"
    count = _normalize_recast_person_count(person_count)
    plural = count != 1
    if prompt:
        instruction_patterns = (
            r"^(?:please\s+)?(?:replace|swap)\s+.+?\s+(?:with|for)\s+(.+)$",
            r"^(?:please\s+)?change\s+.+?\s+(?:into|to)\s+(.+)$",
        )
        for pattern in instruction_patterns:
            match = re.match(pattern, prompt, flags=re.IGNORECASE | re.DOTALL)
            if match:
                prompt = match.group(1).strip()
                break
    if not prompt:
        prompt = (
            "Several clearly defined characters perform naturally within the scene"
            if plural else
            "A clearly defined character performs naturally within the scene"
        )
    prompt = prompt[0].upper() + prompt[1:] if prompt else prompt
    if detail_marker in prompt:
        return prompt
    prompt = prompt.rstrip()
    if prompt[-1:] not in ".!?":
        prompt += "."
    identity = (
        "The characters' faces, hair, body shapes, and complete outfits remain "
        "visually consistent as they follow the visible action and interactions."
        if plural else
        "The character's face, hair, body shape, and complete outfit remain "
        "visually consistent as the character follows the visible action and interactions."
    )
    return (
        f"{prompt} {identity} {detail_marker}, lighting, shadows, and nearby "
        "objects form one coherent, naturally lit scene throughout the video."
    )


def _extract_output_seed(filename):
    """Return the resolved seed embedded in a generated media filename."""
    import os
    import re

    match = re.search(r"(?:^|_)seed(\d+)(?:_|$)", os.path.splitext(filename)[0])
    return int(match.group(1)) if match else None


def _recast_video_has_audio(video_path):
    """Return whether ffprobe finds an audio stream in a video."""
    import subprocess

    probe = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0",
            video_path,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return probe.returncode == 0 and bool(probe.stdout.strip())


def _build_recast_mask_lock_command(source_video, mask_video, generated_video, output_path):
    """Build the ffmpeg pass that restores every pixel outside the target.

    The SCAIL target is selected by a colored tracking mask. ``colorkey``
    converts the native Replace mask's white background to transparency;
    two tiny dilations plus a soft edge keep the replacement seam clean
    without giving the model room to alter neighboring people.
    """
    import json
    import subprocess

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json",
            generated_video,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        stream = (json.loads(probe.stdout).get("streams") or [])[0]
        width, height = int(stream["width"]), int(stream["height"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        width, height = 0, 0
    if width <= 0 or height <= 0:
        raise ValueError(f"Could not read generated Recast dimensions: {generated_video}")
    filter_graph = (
        f"[0:v]scale={width}:{height}:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[base];"
        f"[1:v]scale={width}:{height}:flags=neighbor,format=rgba,"
        "colorkey=0xFFFFFF:0.18:0.04,alphaextract,dilation,dilation,"
        "gblur=sigma=1.2[alpha];"
        "[2:v]format=rgba,setpts=PTS-STARTPTS[generated];"
        "[generated][alpha]alphamerge[foreground];"
        "[base][foreground]overlay=shortest=1:format=auto[outv]"
    )
    command = [
        "ffmpeg", "-y",
        "-i", source_video,
        "-i", mask_video,
        "-i", generated_video,
        "-filter_complex", filter_graph,
        "-map", "[outv]",
        # Preserve the generated file's embedded prompt and resolved seed.
        "-map_metadata", "2",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p",
    ]
    if _recast_video_has_audio(generated_video):
        command += ["-map", "2:a:0", "-c:a", "copy"]
    elif _recast_video_has_audio(source_video):
        command += ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"]
    else:
        command += ["-an"]
    return command + ["-shortest", "-movflags", "+faststart", output_path]


def _render_recast_mask_locked_video(source_video, mask_video, generated_video):
    """Render a protected sibling file and return its path."""
    import subprocess

    stem, extension = os.path.splitext(generated_video)
    protected_path = f"{stem}.recast-protected{extension}"
    command = _build_recast_mask_lock_command(
        source_video, mask_video, generated_video, protected_path,
    )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if result.returncode != 0 or not os.path.isfile(protected_path):
        if os.path.isfile(protected_path):
            try:
                os.remove(protected_path)
            except OSError:
                pass
        raise RuntimeError(
            "Recast target-mask protection failed: "
            + (result.stderr[-500:] if result.stderr else "ffmpeg produced no output")
        )
    return protected_path


def _recast_color_region(mask_frames, color, tolerance=90):
    """Return pixels close to an RGB tracking color after lossy video decode."""
    import numpy as np

    frames = np.asarray(mask_frames, dtype=np.int16)
    target = np.asarray(color, dtype=np.int16).reshape(1, 1, 1, 3)
    return np.max(np.abs(frames - target), axis=-1) <= int(tolerance)


def _matte_recast_reference_frame(reference_frame, semantic_mask, neutral_value=127):
    """Remove pixels that an additional SCAIL reference must not describe.

    SCAIL-2 encodes reference RGB and its semantic mask separately. A black
    semantic region therefore does not stop identity detail in the original
    RGB image from reaching the reference latent. Replace hidden pixels with
    model-neutral gray so a bystander reference cannot reintroduce the old
    target or condition the surrounding scene.
    """
    import numpy as np

    frame = np.asarray(reference_frame, dtype=np.uint8)
    mask = np.asarray(semantic_mask, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[-1] != 3:
        raise ValueError(
            f"Recast reference frame must have H/W/RGB dimensions; got {frame.shape}."
        )
    if mask.shape != frame.shape:
        raise ValueError(
            "Recast reference frame and semantic mask must have matching "
            f"H/W/RGB dimensions; got frame={frame.shape}, mask={mask.shape}."
        )
    try:
        neutral = int(neutral_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Recast reference neutral value must be an integer.") from exc
    if not 0 <= neutral <= 255:
        raise ValueError("Recast reference neutral value must be between 0 and 255.")

    visible = np.any(mask > 30, axis=-1)
    matted = np.full_like(frame, neutral, dtype=np.uint8)
    matted[visible] = frame[visible]
    return matted


def _recast_reference_canvas_size(
    source_frame, base_width=832, base_height=480, block_size=32,
):
    """Choose a SCAIL output/reference canvas for the control orientation.

    Recast profiles advertise a landscape resolution budget, but SCAIL-2
    reallocates that budget to follow the control video's aspect ratio.
    Preparing hidden references at a literal landscape size makes portrait
    controls consume references that are cropped again later. Preserve the
    source orientation on SCAIL-2's documented 32px boundary.
    """
    import math
    import numpy as np

    frame = np.asarray(source_frame)
    if frame.ndim != 3 or frame.shape[-1] != 3:
        raise ValueError(
            "Recast reference canvas needs an H/W/RGB source frame; "
            f"got {frame.shape}."
        )
    try:
        base_width = int(base_width)
        base_height = int(base_height)
        block_size = int(block_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("Recast reference canvas dimensions must be integers.") from exc
    if min(base_width, base_height, block_size) <= 0:
        raise ValueError("Recast reference canvas dimensions must be positive.")

    source_height, source_width = frame.shape[:2]
    aspect = float(source_width) / float(max(1, source_height))
    short_edge = min(base_width, base_height)
    long_edge = max(base_width, base_height)

    def _floor_block(value):
        return max(
            block_size,
            int(math.floor(float(value) / block_size)) * block_size,
        )

    if aspect >= 1.0:
        height = short_edge
        width = min(long_edge, _floor_block(height * aspect))
    else:
        width = short_edge
        height = min(long_edge, _floor_block(width / max(aspect, 1e-6)))
    return int(width), int(height)


def _recast_resolution_for_source(source_frame, resolution_profile=None):
    """Resolve a SCAIL-2 edit profile to the source-oriented output size."""
    profile = _normalize_recast_resolution_profile(resolution_profile)
    base_width, base_height = _RECAST_RESOLUTION_PROFILES[profile]
    return _recast_reference_canvas_size(
        source_frame,
        base_width=base_width,
        base_height=base_height,
        block_size=32,
    )


def _build_recast_source_scene_layers(
    source_frame, target_mask, selected_count, output_size=None,
):
    """Return a target-free scene image and its official visibility mask."""
    import cv2
    import numpy as np
    from PIL import Image as _PILImage
    from PIL import ImageFilter as _PILImageFilter

    frame = np.asarray(source_frame, dtype=np.uint8)
    mask = np.asarray(target_mask, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[-1] != 3:
        raise ValueError(
            "Recast source-scene reference needs an H/W/RGB source frame; "
            f"got {frame.shape}."
        )
    if mask.shape != frame.shape:
        raise ValueError(
            "Recast source frame and target-anchor mask must have "
            f"matching dimensions; got frame={frame.shape}, mask={mask.shape}."
        )
    if output_size is not None:
        try:
            output_width, output_height = (
                int(output_size[0]),
                int(output_size[1]),
            )
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(
                "Recast source-scene output size must contain width and height."
            ) from exc
        if output_width <= 0 or output_height <= 0:
            raise ValueError(
                "Recast source-scene output dimensions must be positive."
            )
        frame = np.asarray(
            _PILImage.fromarray(frame).resize(
                (output_width, output_height),
                resample=_PILImage.Resampling.LANCZOS,
            ),
            dtype=np.uint8,
        )
        mask = np.asarray(
            _PILImage.fromarray(mask).resize(
                (output_width, output_height),
                resample=_PILImage.Resampling.NEAREST,
            ),
            dtype=np.uint8,
        )

    requested_count = _normalize_recast_person_count(selected_count)
    target_region = np.zeros(frame.shape[:2], dtype=bool)
    mask_frames = mask[None]
    for color in _RECAST_MASK_COLORS[:requested_count]:
        target_region |= _recast_color_region(mask_frames, color)[0]
    if not bool(target_region.any()):
        raise ValueError(
            "Could not build the Recast source-scene reference because the "
            "selected target is missing from the anchor mask."
        )

    # Hide a small margin around the old target. The semantic mask is exact,
    # but VAE receptive fields can otherwise retain hair, clothing, or edge
    # pixels just outside the segmentation boundary.
    expansion = max(
        2,
        min(16, int(round(min(frame.shape[:2]) * 0.01))),
    )
    expanded = _PILImage.fromarray(
        target_region.astype(np.uint8) * 255,
    ).filter(_PILImageFilter.MaxFilter(expansion * 2 + 1))
    hidden_region = np.asarray(expanded, dtype=np.uint8) > 127

    # A neutral gray hole is not truly invisible to the VAE; the reference
    # mask is learned conditioning rather than a hard RGB gate. Inpaint the
    # hidden pixels from their surrounding scene so any latent leakage carries
    # compatible scene color/texture instead of replacing the whole background
    # with the matte color. The black semantic mask still tells SCAIL-2 not to
    # treat the synthesized hole as authoritative visible content.
    inpaint_mask = hidden_region.astype(np.uint8) * 255
    reference_frame = cv2.inpaint(
        frame,
        inpaint_mask,
        max(3, expansion * 2),
        cv2.INPAINT_TELEA,
    )
    reference_mask = np.full_like(frame, 255, dtype=np.uint8)
    reference_mask[hidden_region] = 0
    return {
        "image": reference_frame,
        "mask": reference_mask,
        "hidden_fraction": float(hidden_region.mean()),
        "expansion_pixels": expansion,
    }


def _build_recast_source_scene_reference(
    source_frame, target_mask, selected_count, output_dir, job_id,
    neutral_value=127, output_size=None,
):
    """Build an official-style clean-background reference for Recast.

    SCAIL-2's multi-reference mask semantics use white for source content that
    should remain visible and black for content that must be ignored. Preserve
    the selected source frame everywhere except the old target, then inpaint
    and black-mask that target so neither its identity nor a gray matte can
    leak through the VAE. This reuses one target anchor from Recast's tracked
    timeline; it does not add another SAM3 tracking pass.
    """
    import os
    from PIL import Image as _PILImage
    layers = _build_recast_source_scene_layers(
        source_frame,
        target_mask,
        selected_count,
        output_size=output_size,
    )
    try:
        int(neutral_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Recast source-scene neutral value must be an integer."
        ) from exc
    if not 0 <= int(neutral_value) <= 255:
        raise ValueError(
            "Recast source-scene neutral value must be between 0 and 255."
        )

    os.makedirs(output_dir, exist_ok=True)
    reference_path = os.path.join(
        output_dir, f"recast_source_scene_ref_{job_id}.png",
    )
    reference_mask_path = os.path.join(
        output_dir, f"recast_source_scene_mask_{job_id}.png",
    )
    _PILImage.fromarray(layers["image"]).save(reference_path)
    _PILImage.fromarray(layers["mask"]).save(reference_mask_path)
    return {
        "image": reference_path,
        "mask": reference_mask_path,
        "hidden_fraction": layers["hidden_fraction"],
        "expansion_pixels": layers["expansion_pixels"],
    }


def _enable_recast_dynamic_source_scene_reference(
    params, source_frame, target_mask, selected_count, output_dir, job_id,
):
    """Enable target-free source-scene conditioning for Recast.

    The historical helper/flag names say ``dynamic`` for saved-project
    compatibility. Dedicated single-shot Recast reuses this persisted pair.
    Timeline-aware jobs retain it as a fallback and ask SCAIL-2 to rebuild the
    pair from each current control window.
    """
    if not isinstance(params, dict):
        raise ValueError("Recast generation parameters must be a dictionary.")
    image_refs = params.get("image_refs")
    custom_settings = params.get("custom_settings")
    if not isinstance(image_refs, list) or not image_refs:
        raise ValueError(
            "Recast needs a primary identity reference before adding the "
            "source-scene reference."
        )
    if not isinstance(custom_settings, dict):
        raise ValueError("Recast custom settings are missing.")
    additional_masks = custom_settings.get(
        "scail2_additional_reference_mask_paths",
    )
    expected_colors = custom_settings.get(
        "scail2_reference_expected_colors",
    )
    if not isinstance(additional_masks, list):
        raise ValueError("Recast additional reference masks are missing.")
    if not isinstance(expected_colors, list):
        raise ValueError("Recast expected reference colors are missing.")
    if len(additional_masks) != len(image_refs) - 1:
        raise ValueError(
            "Recast image references and additional masks are out of sync."
        )
    if len(expected_colors) != len(image_refs):
        raise ValueError(
            "Recast image references and expected colors are out of sync."
        )

    output_size = params.get("edit_recast_reference_canvas")
    if (
        not isinstance(output_size, (list, tuple))
        or len(output_size) != 2
    ):
        output_size = _recast_reference_canvas_size(source_frame)
    else:
        try:
            output_size = tuple(int(value) for value in output_size)
        except (TypeError, ValueError):
            output_size = _recast_reference_canvas_size(source_frame)
        if min(output_size) <= 0:
            output_size = _recast_reference_canvas_size(source_frame)
    scene_reference = _build_recast_source_scene_reference(
        source_frame,
        target_mask,
        selected_count,
        output_dir,
        job_id,
        output_size=output_size,
    )
    # Keep this pair out of ``image_refs`` so it does not become a user-facing
    # character slot.  The dedicated conditioner loads it as a separate,
    # stable additional reference for every segment.
    custom_settings["scail2_dynamic_source_scene_reference"] = True
    custom_settings["scail2_source_scene_reference_path"] = (
        scene_reference["image"]
    )
    custom_settings["scail2_source_scene_mask_path"] = (
        scene_reference["mask"]
    )
    params["edit_recast_source_scene_reference"] = scene_reference["image"]
    params["edit_recast_source_scene_mask"] = scene_reference["mask"]
    params["edit_recast_source_scene_hidden_fraction"] = scene_reference[
        "hidden_fraction"
    ]
    params["edit_recast_reference_canvas"] = list(output_size)
    params["edit_recast_source_scene_conditioning"] = (
        "stable_official_reference"
    )
    return scene_reference


def _compose_recast_group_reference_frame(
    source_frame, semantic_mask, target_reference_layers, selected_count,
    neutral_value=127,
):
    """Build one native multi-person SCAIL reference on a neutral canvas.

    The selected shared frame supplies only the tracked bystanders. Each selected
    source target is replaced by the corresponding prepared replacement
    cutout, positioned inside that target's shared-frame slot. The returned
    semantic mask therefore describes every visible conditioned person in one
    ordinary multi-color reference instead of making bystanders compete as a
    separate, target-free multi-reference image.
    """
    import numpy as np
    from PIL import Image as _PILImage

    source = np.asarray(source_frame, dtype=np.uint8)
    group_mask = np.asarray(semantic_mask, dtype=np.uint8)
    if (
        source.ndim != 3
        or source.shape[-1] != 3
        or group_mask.shape != source.shape
    ):
        raise ValueError(
            "Recast group reference needs matching H/W/RGB source and mask "
            f"arrays; got source={source.shape}, mask={group_mask.shape}."
        )
    layers = list(target_reference_layers or [])
    if not layers:
        raise ValueError("Recast group reference needs a prepared target layer.")
    try:
        neutral = int(neutral_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Recast group neutral value must be an integer.") from exc
    if not 0 <= neutral <= 255:
        raise ValueError("Recast group neutral value must be between 0 and 255.")

    normalized_layers = []
    canvas_width = canvas_height = None
    for layer_index, layer in enumerate(layers):
        if not isinstance(layer, (list, tuple)) or len(layer) != 2:
            raise ValueError(
                "Each Recast group target layer must contain an RGB image and "
                "its semantic mask."
            )
        layer_rgb = np.asarray(layer[0], dtype=np.uint8)
        layer_mask = np.asarray(layer[1], dtype=np.uint8)
        if (
            layer_rgb.ndim != 3
            or layer_rgb.shape[-1] != 3
            or layer_mask.shape != layer_rgb.shape
        ):
            raise ValueError(
                f"Recast group target layer {layer_index + 1} has mismatched "
                f"RGB/mask dimensions: image={layer_rgb.shape}, "
                f"mask={layer_mask.shape}."
            )
        if canvas_width is None:
            canvas_height, canvas_width = layer_rgb.shape[:2]
        elif layer_rgb.shape[:2] != (canvas_height, canvas_width):
            layer_rgb = np.asarray(
                _PILImage.fromarray(layer_rgb).resize(
                    (canvas_width, canvas_height),
                    resample=_PILImage.Resampling.LANCZOS,
                ),
                dtype=np.uint8,
            )
            layer_mask = np.asarray(
                _PILImage.fromarray(layer_mask).resize(
                    (canvas_width, canvas_height),
                    resample=_PILImage.Resampling.NEAREST,
                ),
                dtype=np.uint8,
            )
        normalized_layers.append((layer_rgb, layer_mask))

    if source.shape[:2] != (canvas_height, canvas_width):
        source = np.asarray(
            _PILImage.fromarray(source).resize(
                (canvas_width, canvas_height),
                resample=_PILImage.Resampling.LANCZOS,
            ),
            dtype=np.uint8,
        )
        group_mask = np.asarray(
            _PILImage.fromarray(group_mask).resize(
                (canvas_width, canvas_height),
                resample=_PILImage.Resampling.NEAREST,
            ),
            dtype=np.uint8,
        )

    requested_count = _normalize_recast_person_count(selected_count)
    composite = np.full_like(source, neutral, dtype=np.uint8)
    composite_mask = np.zeros_like(group_mask, dtype=np.uint8)

    # Retain source pixels only for the explicitly color-mapped bystanders.
    # The old selected subject and the surrounding scene never enter this RGB
    # reference, so neither can compete with the requested replacement.
    for color in _RECAST_MASK_COLORS[requested_count:]:
        color_array = np.asarray(color, dtype=np.uint8)
        region = np.all(group_mask == color_array, axis=-1)
        if bool(region.any()):
            composite[region] = source[region]
            composite_mask[region] = color_array

    for target_index, color in enumerate(
        _RECAST_MASK_COLORS[:requested_count],
    ):
        color_array = np.asarray(color, dtype=np.uint8)
        target_region = np.all(group_mask == color_array, axis=-1)
        target_ys, target_xs = np.nonzero(target_region)
        if len(target_xs) == 0:
            raise ValueError(
                "Could not place replacement target "
                f"{target_index + 1}: its first-frame color is missing."
            )

        # Legacy "replace N people" reuses one identity for every selected
        # slot; explicit character mappings provide one primary layer each.
        layer_rgb, layer_mask = normalized_layers[
            min(target_index, len(normalized_layers) - 1)
        ]
        subject = np.any(layer_mask > 30, axis=-1)
        subject_ys, subject_xs = np.nonzero(subject)
        if len(subject_xs) == 0:
            raise ValueError(
                f"Prepared replacement target {target_index + 1} is empty."
            )
        sx0, sx1 = int(subject_xs.min()), int(subject_xs.max()) + 1
        sy0, sy1 = int(subject_ys.min()), int(subject_ys.max()) + 1
        subject_rgb = layer_rgb[sy0:sy1, sx0:sx1]
        subject_alpha = (
            subject[sy0:sy1, sx0:sx1].astype(np.uint8) * 255
        )

        tx0, tx1 = int(target_xs.min()), int(target_xs.max()) + 1
        ty0, ty1 = int(target_ys.min()), int(target_ys.max()) + 1
        target_width, target_height = max(1, tx1 - tx0), max(1, ty1 - ty0)
        scale = min(
            target_width / max(1, subject_rgb.shape[1]),
            target_height / max(1, subject_rgb.shape[0]),
        )
        placed_width = max(
            1,
            min(canvas_width, int(round(subject_rgb.shape[1] * scale))),
        )
        placed_height = max(
            1,
            min(canvas_height, int(round(subject_rgb.shape[0] * scale))),
        )
        placed_rgb = np.asarray(
            _PILImage.fromarray(subject_rgb).resize(
                (placed_width, placed_height),
                resample=_PILImage.Resampling.LANCZOS,
            ),
            dtype=np.uint8,
        )
        placed_alpha = np.asarray(
            _PILImage.fromarray(subject_alpha).resize(
                (placed_width, placed_height),
                resample=_PILImage.Resampling.BILINEAR,
            ),
            dtype=np.float32,
        ) / 255.0

        left = int(round((tx0 + tx1 - placed_width) / 2.0))
        top = ty1 - placed_height
        left = max(0, min(left, canvas_width - placed_width))
        top = max(0, min(top, canvas_height - placed_height))
        right, bottom = left + placed_width, top + placed_height

        alpha = placed_alpha[..., None]
        destination = composite[top:bottom, left:right].astype(np.float32)
        composite[top:bottom, left:right] = np.rint(
            placed_rgb.astype(np.float32) * alpha
            + destination * (1.0 - alpha)
        ).clip(0, 255).astype(np.uint8)
        visible = placed_alpha > 0.05
        mask_destination = composite_mask[top:bottom, left:right]
        mask_destination[visible] = color_array

    return composite, composite_mask


def _compose_recast_cast_reference_frame(
    target_reference_layers, selected_count, canvas_size, neutral_value=127,
):
    """Arrange independently prepared characters in one native SCAIL cast.

    SCAIL-2's trained multi-person path expects all mapped identities and their
    semantic colors in one primary reference.  A timeline may never show every
    requested character at once, so this neutral cast sheet is the fallback
    when no shared source frame can provide natural target positions.
    """
    import numpy as np
    from PIL import Image as _PILImage

    layers = list(target_reference_layers or [])
    requested_count = _normalize_recast_person_count(selected_count)
    if len(layers) < requested_count:
        raise ValueError(
            "Recast cast reference needs one prepared target layer per "
            f"character ({len(layers)}/{requested_count})."
        )
    try:
        canvas_width, canvas_height = (
            int(canvas_size[0]),
            int(canvas_size[1]),
        )
        neutral = int(neutral_value)
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError(
            "Recast cast reference needs a valid canvas and neutral value."
        ) from exc
    if min(canvas_width, canvas_height) <= 0:
        raise ValueError("Recast cast reference canvas must be positive.")
    if not 0 <= neutral <= 255:
        raise ValueError(
            "Recast cast reference neutral value must be between 0 and 255."
        )

    composite = np.full(
        (canvas_height, canvas_width, 3),
        neutral,
        dtype=np.uint8,
    )
    composite_mask = np.zeros_like(composite)
    outer_margin = max(4, int(round(min(canvas_width, canvas_height) * 0.025)))
    gap = max(4, int(round(canvas_width * 0.012)))
    available_width = max(
        requested_count,
        canvas_width - 2 * outer_margin - gap * (requested_count - 1),
    )
    cell_width = float(available_width) / float(requested_count)
    maximum_height = max(1, canvas_height - 2 * outer_margin)

    for target_index in range(requested_count):
        layer = layers[target_index]
        if not isinstance(layer, (list, tuple)) or len(layer) != 2:
            raise ValueError(
                "Each Recast cast target layer must contain an RGB image and "
                "its semantic mask."
            )
        layer_rgb = np.asarray(layer[0], dtype=np.uint8)
        layer_mask = np.asarray(layer[1], dtype=np.uint8)
        if (
            layer_rgb.ndim != 3
            or layer_rgb.shape[-1] != 3
            or layer_mask.shape != layer_rgb.shape
        ):
            raise ValueError(
                f"Recast cast target layer {target_index + 1} has mismatched "
                f"RGB/mask dimensions: image={layer_rgb.shape}, "
                f"mask={layer_mask.shape}."
            )
        color_array = np.asarray(
            _RECAST_MASK_COLORS[target_index],
            dtype=np.uint8,
        )
        subject = np.all(layer_mask == color_array, axis=-1)
        if not bool(subject.any()):
            # Prepared PNG masks are normally exact, but tolerate masks from
            # older saved jobs whose semantic color was not persisted.
            subject = np.any(layer_mask > 30, axis=-1)
        subject_ys, subject_xs = np.nonzero(subject)
        if len(subject_xs) == 0:
            raise ValueError(
                f"Prepared replacement target {target_index + 1} is empty."
            )
        sx0, sx1 = int(subject_xs.min()), int(subject_xs.max()) + 1
        sy0, sy1 = int(subject_ys.min()), int(subject_ys.max()) + 1
        subject_rgb = layer_rgb[sy0:sy1, sx0:sx1]
        subject_alpha = (
            subject[sy0:sy1, sx0:sx1].astype(np.uint8) * 255
        )

        maximum_width = max(1, int(round(cell_width * 0.90)))
        scale = min(
            maximum_width / max(1, subject_rgb.shape[1]),
            maximum_height / max(1, subject_rgb.shape[0]),
        )
        placed_width = max(1, int(round(subject_rgb.shape[1] * scale)))
        placed_height = max(1, int(round(subject_rgb.shape[0] * scale)))
        placed_rgb = np.asarray(
            _PILImage.fromarray(subject_rgb).resize(
                (placed_width, placed_height),
                resample=_PILImage.Resampling.LANCZOS,
            ),
            dtype=np.uint8,
        )
        placed_alpha = np.asarray(
            _PILImage.fromarray(subject_alpha).resize(
                (placed_width, placed_height),
                resample=_PILImage.Resampling.BILINEAR,
            ),
            dtype=np.float32,
        ) / 255.0

        cell_left = outer_margin + target_index * (cell_width + gap)
        left = int(round(cell_left + (cell_width - placed_width) / 2.0))
        top = int(round((canvas_height - placed_height) / 2.0))
        left = max(0, min(left, canvas_width - placed_width))
        top = max(0, min(top, canvas_height - placed_height))
        right, bottom = left + placed_width, top + placed_height

        alpha = placed_alpha[..., None]
        destination = composite[top:bottom, left:right].astype(np.float32)
        composite[top:bottom, left:right] = np.rint(
            placed_rgb.astype(np.float32) * alpha
            + destination * (1.0 - alpha)
        ).clip(0, 255).astype(np.uint8)
        visible = placed_alpha > 0.05
        mask_destination = composite_mask[top:bottom, left:right]
        mask_destination[visible] = color_array

    return composite, composite_mask


def _build_recast_target_group_reference(
    prepared_refs, output_dir, job_id, selected_count, *,
    shared_source_frame=None, shared_semantic_mask=None,
):
    """Persist one primary multi-character reference for SCAIL-2 Recast."""
    import numpy as np
    from PIL import Image as _PILImage

    target_layers = []
    for item in prepared_refs.get("primary_target_refs", []):
        if (
            not isinstance(item, dict)
            or not item.get("image")
            or not item.get("mask")
        ):
            raise ValueError(
                "Multi-character Recast needs prepared target image/mask "
                "pairs."
            )
        with _PILImage.open(item["image"]) as target_image:
            target_rgb = np.asarray(
                target_image.convert("RGB"),
                dtype=np.uint8,
            )
        with _PILImage.open(item["mask"]) as target_mask:
            target_semantic = np.asarray(
                target_mask.convert("RGB"),
                dtype=np.uint8,
            )
        target_layers.append((target_rgb, target_semantic))

    mode = "cast_sheet"
    if shared_source_frame is not None and shared_semantic_mask is not None:
        try:
            reference_frame, reference_mask = (
                _compose_recast_group_reference_frame(
                    shared_source_frame,
                    shared_semantic_mask,
                    target_layers,
                    selected_count,
                )
            )
        except ValueError as shared_error:
            print(
                "[Recast] Shared-frame cast layout was unavailable; "
                f"using a neutral cast sheet: {shared_error}"
            )
            reference_frame, reference_mask = (
                _compose_recast_cast_reference_frame(
                    target_layers,
                    selected_count,
                    prepared_refs["reference_canvas"],
                )
            )
        else:
            mode = "shared_timeline_frame"
    else:
        reference_frame, reference_mask = (
            _compose_recast_cast_reference_frame(
                target_layers,
                selected_count,
                prepared_refs["reference_canvas"],
            )
        )

    os.makedirs(output_dir, exist_ok=True)
    reference_path = os.path.join(
        output_dir,
        f"recast_cast_ref_{job_id}.png",
    )
    reference_mask_path = os.path.join(
        output_dir,
        f"recast_cast_mask_{job_id}.png",
    )
    _PILImage.fromarray(reference_frame).save(reference_path)
    _PILImage.fromarray(reference_mask).save(reference_mask_path)
    return {
        "image": reference_path,
        "mask": reference_mask_path,
        "mode": mode,
        "character_count": _normalize_recast_person_count(selected_count),
    }


def _compose_recast_native_people_masks(
    target_mask_frames, all_people_masks, selected_count,
    reference_frame_index=0,
):
    """Build native SCAIL-2 masks for targets plus visible bystanders.

    The user's selected targets retain the first SCAIL colors. Other people
    visible in the selected shared frame are assigned the remaining colors (up
    to SCAIL-2's five-person limit). The driving mask carries all of those
    correspondences, while the shared-frame reference mask identifies every
    target and bystander for one ordinary multi-person reference.
    """
    import numpy as np

    targets = np.asarray(target_mask_frames, dtype=np.uint8)
    people = np.asarray(all_people_masks, dtype=np.uint8)
    if targets.shape != people.shape or targets.ndim != 4 or targets.shape[-1] != 3:
        raise ValueError(
            "Native Recast people masks must have matching T/H/W/RGB dimensions; "
            f"got targets={targets.shape}, people={people.shape}."
        )
    try:
        reference_index = int(reference_frame_index)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Native Recast reference frame index must be an integer."
        ) from exc
    if not 0 <= reference_index < len(targets):
        raise ValueError(
            "Native Recast reference frame index is outside the mask timeline."
        )

    requested_count = _normalize_recast_person_count(selected_count)
    target_regions = []
    for color in _RECAST_MASK_COLORS[:requested_count]:
        region = _recast_color_region(targets, color)
        if bool(region.any()):
            target_regions.append(region)
    if len(target_regions) != requested_count:
        raise ValueError(
            "Could not recover every selected target from the tracked Recast mask "
            f"({len(target_regions)}/{requested_count})."
        )

    candidates = []
    for color_index, color in enumerate(_RECAST_PROTECTION_COLORS):
        region = np.all(people == np.asarray(color, dtype=np.uint8), axis=-1)
        area = int(region.sum())
        reference_frame_area = int(region[reference_index].sum())
        if area and reference_frame_area:
            candidates.append({
                "source_color_index": color_index,
                "region": region,
                "area": area,
                "reference_frame_area": reference_frame_area,
            })
    if not candidates:
        raise ValueError("SAM3 found no people to map for native Recast preservation.")

    # Match the broad "person" tracks back to the user's more specific target
    # tracks. Anything matched here must never be reused as a bystander ref.
    pairings = []
    for target_index, target_region in enumerate(target_regions):
        target_area = max(1, int(target_region.sum()))
        for candidate_index, candidate in enumerate(candidates):
            overlap = int(np.logical_and(target_region, candidate["region"]).sum())
            score = overlap / np.sqrt(float(target_area * candidate["area"]))
            pairings.append((score, overlap, target_index, candidate_index))
    pairings.sort(key=lambda item: (item[0], item[1]), reverse=True)

    used_targets = set()
    target_candidate_indices = set()
    for score, overlap, target_index, candidate_index in pairings:
        if target_index in used_targets or candidate_index in target_candidate_indices:
            continue
        if overlap <= 0 or score < 0.02:
            continue
        used_targets.add(target_index)
        target_candidate_indices.add(candidate_index)
        if len(used_targets) == len(target_regions):
            break
    if len(used_targets) != len(target_regions):
        raise ValueError(
            "Could not match every selected target to the source person tracks "
            f"({len(used_targets)}/{len(target_regions)})."
        )

    target_union = np.logical_or.reduce(target_regions)
    bystanders = []
    for candidate_index, candidate in enumerate(candidates):
        if candidate_index in target_candidate_indices:
            continue
        overlap = int(np.logical_and(target_union, candidate["region"]).sum())
        overlap_fraction = overlap / max(
            1, min(candidate["area"], int(target_union.sum())),
        )
        # Avoid treating a fragmented duplicate of a target track as another
        # person when SAM's broad prompt splits loose clothing or an occlusion.
        # A high threshold deliberately retains real dancers who pass behind
        # or partly overlap the selected subject.
        if overlap_fraction > 0.65:
            continue
        bystanders.append(candidate)
    bystanders.sort(
        key=lambda candidate: (
            candidate["area"],
            candidate["reference_frame_area"],
        ),
        reverse=True,
    )
    capacity = max(0, len(_RECAST_MASK_COLORS) - len(target_regions))
    bystanders = bystanders[:capacity]

    driving_mask = np.full_like(targets, 255, dtype=np.uint8)
    group_ref_mask = np.zeros(targets.shape[1:], dtype=np.uint8)
    assignments = []
    for offset, candidate in enumerate(bystanders):
        assigned_index = len(target_regions) + offset
        assigned_color = _RECAST_MASK_COLORS[assigned_index]
        driving_mask[candidate["region"]] = np.asarray(assigned_color, dtype=np.uint8)
        group_ref_mask[candidate["region"][reference_index]] = np.asarray(
            assigned_color, dtype=np.uint8,
        )
        assignments.append((
            candidate["source_color_index"],
            assigned_index,
            candidate["area"],
        ))

    # The explicit target mask wins wherever people overlap or cross.
    for target_index, target_region in enumerate(target_regions):
        driving_mask[target_region] = np.asarray(
            _RECAST_MASK_COLORS[target_index], dtype=np.uint8,
        )
    # A broad bystander track can overlap the selected subject in the shared
    # frame. The selected target wins there, keeping one unambiguous color per
    # pixel in the native group reference.
    group_ref_mask[target_union[reference_index]] = 0
    for target_index, target_region in enumerate(target_regions):
        group_ref_mask[target_region[reference_index]] = np.asarray(
            _RECAST_MASK_COLORS[target_index], dtype=np.uint8,
        )
    return (
        driving_mask,
        group_ref_mask,
        len(target_regions) + len(bystanders),
        assignments,
    )


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


def _build_recast_native_people_conditioning(
    source_video, target_mask_video, selected_count, output_dir, job_id,
    target_references=None, progress_callback=None, reference_frame_index=0,
):
    """Track source bystanders and write one SCAIL-native group reference."""
    import cv2
    import numpy as np
    from PIL import Image as _PILImage
    from shared import magic_mask

    source_path, source_frames, fps = magic_mask.prepare_video_mask_input(source_video)
    _, target_masks, _ = magic_mask.prepare_video_mask_input(target_mask_video)
    frame_count, height, width = source_frames.shape[:3]
    if len(target_masks) != frame_count:
        indices = np.rint(
            np.linspace(0, len(target_masks) - 1, frame_count),
        ).astype(np.int64)
        target_masks = target_masks[indices]
    if target_masks.shape[1:3] != (height, width):
        target_masks = np.stack([
            cv2.resize(frame, (width, height), interpolation=cv2.INTER_NEAREST)
            for frame in target_masks
        ])

    all_people_masks = magic_mask.generate_keyword_masks(
        source_frames,
        "person",
        no_hole=True,
        colorize_objects=True,
        color_palette=_RECAST_PROTECTION_COLORS,
        max_colored_objects=len(_RECAST_PROTECTION_COLORS),
        progress_callback=progress_callback,
    )
    driving_mask, group_ref_mask, conditioning_count, assignments = (
        _compose_recast_native_people_masks(
            target_masks,
            all_people_masks,
            selected_count,
            reference_frame_index=reference_frame_index,
        )
    )
    if conditioning_count <= _normalize_recast_person_count(selected_count):
        return {
            "video_mask": target_mask_video,
            "reference_image": None,
            "reference_mask": None,
            "conditioning_count": conditioning_count,
            "assignments": assignments,
        }

    os.makedirs(output_dir, exist_ok=True)
    driving_mask_path = magic_mask.save_mask_video(
        source_path,
        driving_mask,
        fps,
        ["recast people"],
        output_dir=output_dir,
    )
    reference_path = os.path.join(
        output_dir, f"recast_group_ref_{job_id}.png",
    )
    reference_mask_path = os.path.join(
        output_dir, f"recast_group_mask_{job_id}.png",
    )
    target_layers = []
    for item in target_references or []:
        if not isinstance(item, dict) or not item.get("image") or not item.get("mask"):
            raise ValueError(
                "Native Recast preservation needs prepared target image/mask pairs."
            )
        with _PILImage.open(item["image"]) as target_image:
            target_rgb = np.asarray(target_image.convert("RGB"), dtype=np.uint8)
        with _PILImage.open(item["mask"]) as target_mask:
            target_semantic = np.asarray(
                target_mask.convert("RGB"), dtype=np.uint8,
            )
        target_layers.append((target_rgb, target_semantic))
    reference_frame, reference_mask = _compose_recast_group_reference_frame(
        source_frames[int(reference_frame_index)],
        group_ref_mask,
        target_layers,
        selected_count,
    )
    _PILImage.fromarray(reference_frame).save(reference_path)
    _PILImage.fromarray(reference_mask).save(reference_mask_path)
    return {
        "video_mask": driving_mask_path,
        "reference_image": reference_path,
        "reference_mask": reference_mask_path,
        "conditioning_count": conditioning_count,
        "assignments": assignments,
    }


def _select_recast_generated_regions(
    source_mask_frames, generated_people_masks, person_count,
):
    """Select generated person tracks that correspond to source targets.

    The source mask identifies who the user approved. SAM3 assigns stable
    colors to every person in the generated video. Spatiotemporal overlap
    matches those generated tracks back to the approved targets even when
    replacement changes body size or silhouette substantially.
    """
    import numpy as np

    source = np.asarray(source_mask_frames, dtype=np.uint8)
    generated = np.asarray(generated_people_masks, dtype=np.uint8)
    if source.shape != generated.shape or source.ndim != 4 or source.shape[-1] != 3:
        raise ValueError(
            "Adaptive Recast masks must have matching T/H/W/RGB dimensions; "
            f"got source={source.shape}, generated={generated.shape}."
        )

    source_white = np.all(source > 225, axis=-1)
    source_black = np.all(source < 30, axis=-1)
    source_union = ~source_white & ~source_black
    if not bool(source_union.any()):
        raise ValueError("The approved Recast target mask is empty.")

    requested_count = min(5, max(1, int(person_count or 1)))
    target_regions = []
    for color in _RECAST_MASK_COLORS[:requested_count]:
        region = _recast_color_region(source, color)
        if bool(region.any()):
            target_regions.append(region)
    if not target_regions:
        target_regions = [source_union]

    candidates = []
    for color_index, color in enumerate(_RECAST_PROTECTION_COLORS):
        region = np.all(generated == np.asarray(color, dtype=np.uint8), axis=-1)
        area = int(region.sum())
        if area:
            candidates.append((color_index, region, area))
    if not candidates:
        raise ValueError("SAM3 found no people in the generated Recast video.")

    pairings = []
    for target_index, target_region in enumerate(target_regions):
        target_area = max(1, int(target_region.sum()))
        for color_index, generated_region, generated_area in candidates:
            overlap = int(np.logical_and(target_region, generated_region).sum())
            score = overlap / np.sqrt(float(target_area * generated_area))
            pairings.append(
                (score, overlap, target_index, color_index, generated_region)
            )
    pairings.sort(key=lambda item: (item[0], item[1]), reverse=True)

    used_targets = set()
    used_colors = set()
    selected_regions = []
    selected_scores = []
    for score, overlap, target_index, color_index, generated_region in pairings:
        if target_index in used_targets or color_index in used_colors:
            continue
        # A tiny incidental crossing should not attach an unrelated bystander.
        if overlap <= 0 or score < 0.02:
            continue
        used_targets.add(target_index)
        used_colors.add(color_index)
        selected_regions.append(generated_region)
        selected_scores.append((color_index, float(score), overlap))
        if len(used_targets) == len(target_regions):
            break

    if len(used_targets) != len(target_regions):
        raise ValueError(
            "Could not match every generated replacement to its approved "
            f"source target ({len(used_targets)}/{len(target_regions)} matched)."
        )

    adaptive = source_union.copy()
    for region in selected_regions:
        adaptive |= region
    return adaptive, selected_scores


def _build_recast_adaptive_mask(
    generated_video, source_mask_video, person_count, output_dir,
    progress_callback=None,
):
    """Trace generated replacement silhouettes and return a mask-video path."""
    import cv2
    import numpy as np
    from shared import magic_mask

    generated_path, generated_frames, fps = magic_mask.prepare_video_mask_input(
        generated_video,
    )
    _, source_masks, _ = magic_mask.prepare_video_mask_input(source_mask_video)
    frame_count, height, width = generated_frames.shape[:3]
    if len(source_masks) != frame_count:
        indices = np.rint(
            np.linspace(0, len(source_masks) - 1, frame_count)
        ).astype(np.int64)
        source_masks = source_masks[indices]
    if source_masks.shape[1:3] != (height, width):
        source_masks = np.stack([
            cv2.resize(frame, (width, height), interpolation=cv2.INTER_NEAREST)
            for frame in source_masks
        ])

    generated_people = magic_mask.generate_keyword_masks(
        generated_frames,
        "person",
        no_hole=True,
        colorize_objects=True,
        color_palette=_RECAST_PROTECTION_COLORS,
        max_colored_objects=len(_RECAST_PROTECTION_COLORS),
        progress_callback=progress_callback,
    )
    adaptive, selected_scores = _select_recast_generated_regions(
        source_masks, generated_people, person_count,
    )

    # Close tiny segmentation gaps and leave a narrow safety rim for hair,
    # fingers, motion blur, and compression. The ffmpeg compositor feathers it.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    adaptive = np.stack([
        cv2.dilate(
            cv2.morphologyEx(frame.astype(np.uint8), cv2.MORPH_CLOSE, kernel),
            kernel,
        ) != 0
        for frame in adaptive
    ])
    output_masks = np.zeros((frame_count, height, width, 3), dtype=np.uint8)
    output_masks[adaptive] = np.asarray(_RECAST_MASK_COLORS[0], dtype=np.uint8)
    mask_path = magic_mask.save_mask_video(
        generated_path,
        output_masks,
        fps,
        ["adaptive recast target"],
        output_dir=output_dir,
        background_color=(255, 255, 255),
    )
    score_text = ", ".join(
        f"track {color_index}: {score:.3f} ({overlap} px)"
        for color_index, score, overlap in selected_scores
    )
    print(f"  [Recast] Adaptive protection selected {score_text}")
    return mask_path


def _count_recast_mask_people(mask, colors):
    """Count SCAIL-2 palette colors present in a colorized SAM3 mask."""
    import numpy as np

    array = np.asarray(mask)
    if array.ndim < 3 or array.shape[-1] != 3:
        return 0
    return sum(
        bool(np.all(array == np.asarray(color, dtype=array.dtype), axis=-1).any())
        for color in colors
    )


def _align_recast_reference_mask(source_mask, reference_mask, target_colors, candidate_colors):
    """Match people in an edited first frame to source targets by overlap.

    SAM3 segments every person in the edited reference.  Spatial overlap
    with the already-previewed source mask then tells us which new person
    belongs to each SCAIL slot, even when the edit changed "woman" to "man".
    """
    import itertools
    import numpy as np
    from PIL import Image as _PILImage

    source = np.asarray(source_mask, dtype=np.uint8)
    reference = np.asarray(reference_mask, dtype=np.uint8)
    if source.shape[:2] != reference.shape[:2]:
        source = np.asarray(
            _PILImage.fromarray(source, mode="RGB").resize(
                (reference.shape[1], reference.shape[0]),
                resample=_PILImage.Resampling.NEAREST,
            ),
            dtype=np.uint8,
        )

    target_regions = [
        np.all(source == np.asarray(color, dtype=np.uint8), axis=-1)
        for color in target_colors
    ]
    present_candidates = []
    for color in candidate_colors:
        region = np.all(reference == np.asarray(color, dtype=np.uint8), axis=-1)
        if bool(region.any()):
            present_candidates.append(region)

    scores = np.zeros((len(target_regions), len(present_candidates)), dtype=np.float64)
    for target_idx, target_region in enumerate(target_regions):
        for candidate_idx, candidate_region in enumerate(present_candidates):
            union = np.logical_or(target_region, candidate_region).sum()
            if union:
                scores[target_idx, candidate_idx] = np.logical_and(target_region, candidate_region).sum() / union

    assignment = ()
    if present_candidates:
        assignment_size = min(len(target_regions), len(present_candidates))
        assignment = max(
            itertools.permutations(range(len(present_candidates)), assignment_size),
            key=lambda candidate_ids: sum(
                scores[target_idx, candidate_id]
                for target_idx, candidate_id in enumerate(candidate_ids)
            ),
        )

    output = np.zeros_like(reference, dtype=np.uint8)
    matched = 0
    for target_idx, (target_color, target_region) in enumerate(zip(target_colors, target_regions)):
        selected_region = target_region
        if target_idx < len(assignment):
            candidate_idx = assignment[target_idx]
            if scores[target_idx, candidate_idx] > 0.01:
                selected_region = present_candidates[candidate_idx]
                matched += 1
        output[selected_region] = np.asarray(target_color, dtype=np.uint8)
    return output, matched


def _normalize_recast_character_mappings(body, workspace):
    """Resolve explicit Recast character mappings while retaining legacy API input.

    New clients send one mapping per source person.  Older clients send a
    single target/reference plus ``person_count``; that form is intentionally
    left grouped so existing saved settings remain loadable.
    """
    raw_mappings = body.get("character_mappings")
    explicit = isinstance(raw_mappings, list) and len(raw_mappings) > 0
    if explicit:
        if len(raw_mappings) > len(_RECAST_MASK_COLORS):
            raise ValueError("SCAIL-2 supports at most five character mappings.")
        mappings = []
        for index, raw_mapping in enumerate(raw_mappings):
            if not isinstance(raw_mapping, dict):
                raise ValueError(f"Character mapping {index + 1} is invalid.")
            target = str(raw_mapping.get("target") or "").strip()
            if not target:
                raise ValueError(
                    f"Character mapping {index + 1} needs a source-person description."
                )
            raw_reference = (
                raw_mapping.get("ref_image_path")
                or raw_mapping.get("reference_image_path")
            )
            reference_path = _resolve_recast_media(raw_reference, workspace)
            if not reference_path:
                raise ValueError(
                    f"Character mapping {index + 1} reference was not found: "
                    f"{raw_reference}"
                )
            additional_paths = []
            raw_additional = (
                raw_mapping.get("additional_ref_image_paths")
                or raw_mapping.get("additional_reference_paths")
                or []
            )
            if not isinstance(raw_additional, list):
                raise ValueError(
                    f"Character mapping {index + 1} additional views must be a list."
                )
            for raw_path in raw_additional[:4]:
                resolved = _resolve_recast_media(raw_path, workspace)
                if not resolved:
                    raise ValueError(
                        f"Character mapping {index + 1} additional view was not found: "
                        f"{raw_path}"
                    )
                additional_paths.append(resolved)
            mappings.append({
                "id": str(raw_mapping.get("id") or f"recast-{index + 1}"),
                "target": target,
                "ref_image_path": reference_path,
                "additional_ref_image_paths": additional_paths,
                "reference_aligned_to_source": (
                    raw_mapping.get("reference_aligned_to_source") is True
                ),
            })
        if len(mappings) > 1 and any(
            mapping["reference_aligned_to_source"] for mapping in mappings
        ):
            raise ValueError(
                "An edited full-frame reference can currently map one replacement. "
                "Use standalone primary references for multi-character mapping."
            )
        return mappings, True

    raw_reference = body.get("ref_image_path")
    reference_path = _resolve_recast_media(raw_reference, workspace)
    if not reference_path:
        raise ValueError(f"Reference image not found: {raw_reference}")
    additional_paths = []
    raw_additional = body.get("additional_ref_image_paths") or []
    if not isinstance(raw_additional, list):
        raise ValueError("Additional reference views must be a list.")
    for raw_path in raw_additional[:4]:
        resolved = _resolve_recast_media(raw_path, workspace)
        if not resolved:
            raise ValueError(f"Additional reference view was not found: {raw_path}")
        additional_paths.append(resolved)
    return [{
        "id": "recast-1",
        "target": str(body.get("target") or "person").strip() or "person",
        "ref_image_path": reference_path,
        "additional_ref_image_paths": additional_paths,
        "reference_aligned_to_source": (
            body.get("reference_aligned_to_source") is True
        ),
    }], False


def _compose_recast_character_masks(
    mapping_masks, colors, overlap_limit=0.35,
    background_color=(255, 255, 255),
):
    """Merge separately tracked people into deterministic SCAIL color slots."""
    import numpy as np

    if not mapping_masks or len(mapping_masks) != len(colors):
        raise ValueError("Recast needs one tracked mask per character color.")
    shape = np.asarray(mapping_masks[0]).shape
    if len(shape) not in (3, 4):
        raise ValueError(f"Unsupported Recast character-mask shape: {shape}.")
    region_shape = shape[:-1] if shape[-1] == 3 else shape
    background = np.asarray(background_color, dtype=np.uint8)
    if background.shape != (3,):
        raise ValueError("Character-mask background must be one RGB color.")
    output = np.empty((*region_shape, 3), dtype=np.uint8)
    output[...] = background
    occupied = np.zeros(region_shape, dtype=bool)
    overlaps = []
    for index, (raw_mask, color) in enumerate(zip(mapping_masks, colors)):
        mask = np.asarray(raw_mask)
        if mask.shape != shape:
            raise ValueError("Every Recast character mask must have matching dimensions.")
        region = np.any(mask > 30, axis=-1) if mask.shape[-1] == 3 else mask.astype(bool)
        area = int(region.sum())
        if area <= 0:
            raise ValueError(f"Character mapping {index + 1} matched no pixels.")
        overlap = np.logical_and(region, occupied)
        overlap_fraction = float(overlap.sum()) / float(max(1, area))
        overlaps.append(overlap_fraction)
        if overlap_fraction > float(overlap_limit):
            raise ValueError(
                f"Character mapping {index + 1} overlaps an earlier mapping by "
                f"{overlap_fraction:.0%}. Use more specific source descriptions."
            )
        # Earlier cards win the occasional occlusion pixel, making color
        # assignment stable regardless of SAM's internal object ordering.
        writable = region & ~occupied
        output[writable] = np.asarray(color, dtype=np.uint8)
        occupied |= region
    return output, overlaps


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


def _recast_mask_region(mask):
    """Return a boolean T/H/W or H/W region from a Recast mask."""
    import numpy as np

    array = np.asarray(mask)
    if array.ndim in (3, 4) and array.shape[-1] == 3:
        return np.any(array > 30, axis=-1)
    if array.ndim in (2, 3):
        return array.astype(bool)
    raise ValueError(f"Unsupported Recast mask shape: {array.shape}.")


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


def _recast_appearance_descriptor(source_frame, subject_region):
    """Build a compact clothing/appearance descriptor for shot reacquisition."""
    import cv2
    import numpy as np

    frame = np.asarray(source_frame, dtype=np.uint8)
    region = np.asarray(subject_region).astype(bool)
    if (
        frame.ndim != 3
        or frame.shape[-1] != 3
        or region.shape != frame.shape[:2]
        or not bool(region.any())
    ):
        return None

    # Erode away SAM's boundary pixels so the descriptor represents the
    # person rather than the changing background around their silhouette.
    edge = max(3, int(round(min(region.shape) * 0.012)))
    if edge % 2 == 0:
        edge += 1
    core = cv2.erode(
        region.astype(np.uint8),
        np.ones((edge, edge), dtype=np.uint8),
        iterations=1,
    ).astype(bool)
    if int(core.sum()) < 100:
        core = region
    mask = core.astype(np.uint8)

    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    lab = cv2.cvtColor(frame, cv2.COLOR_RGB2LAB)
    hue_saturation = cv2.calcHist(
        [hsv],
        [0, 1],
        mask,
        [24, 8],
        [0, 180, 0, 256],
    ).reshape(-1)
    perceptual_color = cv2.calcHist(
        [lab],
        [0, 1, 2],
        mask,
        [8, 8, 8],
        [0, 256, 0, 256, 0, 256],
    ).reshape(-1)
    hue_saturation /= max(1.0, float(hue_saturation.sum()))
    perceptual_color /= max(1.0, float(perceptual_color.sum()))
    descriptor = np.concatenate(
        [hue_saturation, perceptual_color],
    ).astype(np.float32, copy=False)
    norm = float(np.linalg.norm(descriptor))
    return descriptor / norm if norm > 1e-8 else None


def _build_recast_mapping_appearance_prototypes(
    source_frames, mapping_masks, shot_ranges, max_per_mapping=6,
):
    """Collect high-confidence per-shot source appearances for each card."""
    import numpy as np

    frames = np.asarray(source_frames, dtype=np.uint8)
    prototypes = []
    for raw_mask in mapping_masks or []:
        region = _recast_mask_region(raw_mask)
        candidates = []
        for raw_start, raw_end in shot_ranges or [(0, len(frames))]:
            start = max(0, min(len(frames), int(raw_start)))
            end = max(start, min(len(frames), int(raw_end)))
            if end <= start:
                continue
            areas = (
                region[start:end]
                .reshape(end - start, -1)
                .sum(axis=1)
            )
            if not int(areas.max(initial=0)):
                continue
            frame_index = start + int(np.argmax(areas))
            descriptor = _recast_appearance_descriptor(
                frames[frame_index],
                region[frame_index],
            )
            if descriptor is not None:
                candidates.append((
                    int(areas[frame_index - start]),
                    descriptor,
                ))
        candidates.sort(key=lambda item: item[0], reverse=True)
        prototypes.append([
            descriptor
            for _area, descriptor in candidates[:max_per_mapping]
        ])
    return prototypes


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


def _build_recast_character_mask(
    source_video, mappings, output_dir, progress_callback=None,
    abort_callback=None,
):
    """Track mapped characters across shots, then save one color mask."""
    import numpy as np
    from shared import magic_mask

    source_path, source_frames, fps = magic_mask.prepare_video_mask_input(
        source_video,
    )
    shot_ranges = _detect_recast_shot_ranges(source_frames)
    if len(shot_ranges) > 1:
        safe_fps = float(fps or 25.0)
        cut_times = ", ".join(
            f"{start / safe_fps:.2f}s"
            for start, _end in shot_ranges[1:]
        )
        print(
            f"[Recast] Detected {len(shot_ranges)} camera shots; "
            f"reacquiring mapped characters after cuts at {cut_times}."
        )
    else:
        print(
            "[Recast] Detected one continuous camera shot; "
            "tracking mapped characters across the full timeline."
        )
    mapping_masks = []
    mapping_summaries = []
    tracking_targets = []
    total_mappings = len(mappings)
    for index, mapping in enumerate(mappings):
        if abort_callback is not None:
            abort_callback()

        def _mapping_progress(done, total, mapping_index=index):
            if abort_callback is not None:
                abort_callback()
            if progress_callback is not None:
                progress_callback(
                    mapping_index,
                    total_mappings,
                    done,
                    total,
                )

        color = _RECAST_MASK_COLORS[index]
        tracking_target = _normalize_recast_tracking_target(
            mapping["target"],
        )
        tracking_targets.append(tracking_target)
        if tracking_target != mapping["target"]:
            print(
                "[Recast] SAM3 tracking wording normalized: "
                f"'{mapping['target']}' -> '{tracking_target}'."
            )
        tracked = magic_mask.generate_keyword_masks(
            source_frames,
            tracking_target,
            no_hole=True,
            colorize_objects=True,
            color_palette=[color],
            max_colored_objects=1,
            progress_callback=_mapping_progress,
            tracking_segments=shot_ranges,
        )
        summary = _summarize_recast_mapping_mask(tracked, fps)
        if summary is None:
            raise ValueError(
                f"Character mapping {index + 1} found no "
                f"'{mapping['target']}' anywhere in the selected video. "
                "Try a more specific description or adjust the trim range."
            )
        summary.update({
            "mapping_index": index,
            "target": mapping["target"],
            "tracking_target": tracking_target,
            "color": list(color),
        })
        mapping_masks.append(tracked)
        mapping_summaries.append(summary)

    unresolved_shots = _find_recast_unmapped_shots(
        mapping_masks,
        shot_ranges,
    )
    recovered_shots = []
    if unresolved_shots:
        compact_parts = []
        compact_ranges = []
        compact_offset = 0
        for shot in unresolved_shots:
            start = int(shot["start_frame"])
            end = int(shot["end_frame"])
            compact_parts.append(source_frames[start:end])
            length = end - start
            compact_ranges.append(
                (compact_offset, compact_offset + length),
            )
            compact_offset += length
        recovery_frames = (
            compact_parts[0]
            if len(compact_parts) == 1
            else np.concatenate(compact_parts, axis=0)
        )
        shot_numbers = ", ".join(
            str(int(shot["shot_index"]) + 1)
            for shot in unresolved_shots
        )
        print(
            "[Recast] No mapped target was grounded in camera shot"
            f"{'s' if len(unresolved_shots) != 1 else ''} "
            f"{shot_numbers}; running generic-person appearance recovery."
        )

        def _recovery_progress(_done, _total):
            if abort_callback is not None:
                abort_callback()

        compact_people_mask = magic_mask.generate_keyword_masks(
            recovery_frames,
            "person",
            no_hole=True,
            colorize_objects=True,
            color_palette=_RECAST_MASK_COLORS,
            max_colored_objects=len(_RECAST_MASK_COLORS),
            progress_callback=_recovery_progress,
            tracking_segments=compact_ranges,
        )
        mapping_masks, recovered_shots = (
            _recover_recast_unmapped_shots(
                source_frames,
                mapping_masks,
                shot_ranges,
                unresolved_shots,
                compact_people_mask,
                compact_ranges,
            )
        )
        del compact_people_mask
        del recovery_frames
        if recovered_shots:
            recovery_summary = ", ".join(
                "shot "
                f"{item['shot_index'] + 1} -> character "
                f"{chr(65 + item['mapping_index'])} "
                f"({item['similarity']:.2f})"
                for item in recovered_shots
            )
            print(
                "[Recast] Appearance recovery accepted "
                f"{recovery_summary}."
            )
            refreshed_summaries = []
            for index, mapping_mask in enumerate(mapping_masks):
                refreshed = _summarize_recast_mapping_mask(
                    mapping_mask,
                    fps,
                )
                if refreshed is None:
                    refreshed = mapping_summaries[index]
                refreshed.update({
                    "mapping_index": index,
                    "target": mappings[index]["target"],
                    "tracking_target": tracking_targets[index],
                    "color": list(_RECAST_MASK_COLORS[index]),
                    "recovered_shot_indices": [
                        item["shot_index"]
                        for item in recovered_shots
                        if item["mapping_index"] == index
                    ],
                })
                refreshed_summaries.append(refreshed)
            mapping_summaries = refreshed_summaries
        else:
            print(
                "[Recast] Generic-person recovery found no sufficiently "
                "distinct identity match; unresolved shots remain unchanged."
            )
    merged, overlaps = _compose_recast_character_masks(
        mapping_masks,
        _RECAST_MASK_COLORS[:total_mappings],
    )
    common_frame_index, scene_anchor_index = (
        _select_recast_timeline_anchor(mapping_masks)
    )
    for summary, overlap in zip(mapping_summaries, overlaps):
        summary["overlap_fraction"] = float(overlap)
    mask_path = magic_mask.save_mask_video(
        source_path,
        merged,
        fps,
        [mapping["target"] for mapping in mappings],
        output_dir=output_dir,
        abort_callback=abort_callback,
        background_color=(255, 255, 255),
    )
    return {
        "video_mask": mask_path,
        "mask_frames": merged,
        "source_frames": source_frames,
        "fps": fps,
        "overlaps": overlaps,
        "mapping_masks": mapping_masks,
        "mapping_summaries": mapping_summaries,
        "recovered_shots": recovered_shots,
        "shot_ranges": [list(bounds) for bounds in shot_ranges],
        "shot_count": len(shot_ranges),
        "common_frame_index": common_frame_index,
        "scene_anchor_index": scene_anchor_index,
        "timeline_aware": (
            len(shot_ranges) > 1
            or (
                total_mappings > 1
                and common_frame_index is None
            )
            or any(
                summary["first_frame_index"] > 0
                for summary in mapping_summaries
            )
        ),
    }


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


def _clean_recast_reference_region(region):
    """Keep the dominant connected subject and discard detached people."""
    import cv2
    import numpy as np

    binary = np.ascontiguousarray(
        np.asarray(region).astype(np.uint8, copy=False),
    )
    if binary.ndim != 2 or not bool(binary.any()):
        return binary.astype(bool), 0
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )
    foreground_count = max(0, int(component_count) - 1)
    if foreground_count <= 1:
        return binary.astype(bool), foreground_count
    areas = stats[1:, cv2.CC_STAT_AREA]
    selected_label = 1 + int(np.argmax(areas))
    return labels == selected_label, foreground_count


def _select_recast_reference_instance(colored_mask, palette):
    """Select one prominent central SAM3 instance from a reference image."""
    import numpy as np

    mask = np.asarray(colored_mask)
    if mask.ndim == 2:
        cleaned, component_count = _clean_recast_reference_region(mask)
        return cleaned, {
            "instance_count": component_count,
            "selected_index": 0,
        }
    if mask.ndim != 3 or mask.shape[-1] != 3:
        raise ValueError(
            "SAM3 returned an unsupported reference mask shape: "
            f"{mask.shape}."
        )

    height, width = mask.shape[:2]
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    max_distance = max(1.0, (center_x ** 2 + center_y ** 2) ** 0.5)
    candidates = []
    for palette_index, color in enumerate(palette):
        color_array = np.asarray(color, dtype=np.uint8)
        region = np.all(mask == color_array, axis=-1)
        if not bool(region.any()):
            continue
        cleaned, component_count = _clean_recast_reference_region(region)
        ys, xs = np.nonzero(cleaned)
        if len(xs) == 0:
            continue
        area = int(len(xs))
        distance = (
            (float(xs.mean()) - center_x) ** 2
            + (float(ys.mean()) - center_y) ** 2
        ) ** 0.5
        centrality = max(0.0, 1.0 - distance / max_distance)
        # Area remains the dominant signal. Centrality breaks close calls in
        # favor of the foreground subject users normally place near the middle.
        score = float(area) * (1.0 + 0.25 * centrality)
        candidates.append({
            "region": cleaned,
            "score": score,
            "area": area,
            "palette_index": palette_index,
            "component_count": component_count,
        })

    if not candidates:
        fallback, component_count = _clean_recast_reference_region(
            np.any(mask > 30, axis=-1),
        )
        return fallback, {
            "instance_count": component_count,
            "selected_index": 0,
        }
    selected = max(candidates, key=lambda item: item["score"])
    return selected["region"], {
        "instance_count": len(candidates),
        "selected_index": selected["palette_index"],
        "discarded_components": max(0, selected["component_count"] - 1),
    }


def _recast_reference_subject_mask(reference_frame, alpha_channel=None):
    """Find the single person represented by a standalone reference view."""
    import numpy as np
    from shared import magic_mask

    if alpha_channel is not None:
        alpha = np.asarray(alpha_channel, dtype=np.uint8)
        transparent_fraction = (
            float(np.count_nonzero(alpha < 250)) / float(alpha.size)
            if alpha.size else 0.0
        )
        if transparent_fraction >= 0.02 and int(alpha.max()) > 5:
            selected, component_count = _clean_recast_reference_region(
                alpha > 5,
            )
            opacity = alpha.astype(np.float32) / 255.0
            opacity[~selected] = 0.0
            return (
                selected,
                opacity,
                "png alpha"
                + (
                    f" (dominant of {component_count} regions)"
                    if component_count > 1 else ""
                ),
            )

    frame = np.asarray(reference_frame, dtype=np.uint8)
    instance_palette = [
        (0, 0, 255),
        (255, 0, 0),
        (0, 255, 0),
        (255, 0, 255),
        (0, 255, 255),
    ]
    for keyword in ("person", "human character", "woman", "man"):
        mask = magic_mask.generate_keyword_masks(
            frame[None],
            keyword,
            no_hole=True,
            colorize_objects=True,
            color_palette=instance_palette,
            max_colored_objects=len(instance_palette),
        )[0]
        region, selection = _select_recast_reference_instance(
            mask,
            instance_palette,
        )
        if bool(region.any()):
            instance_count = int(selection.get("instance_count") or 1)
            selected_number = int(selection.get("selected_index") or 0) + 1
            source = (
                f"{keyword} instance {selected_number}/{instance_count}"
                if instance_count > 1
                else f"{keyword} instance"
            )
            discarded = int(selection.get("discarded_components") or 0)
            if discarded:
                source += f" (removed {discarded} detached region(s))"
            return region, region.astype(np.float32), source
    raise ValueError(
        "SAM3 could not find one person in the replacement reference. "
        "Try a clearer full- or half-body image."
    )


def _decontaminate_recast_reference_edges(reference_frame, subject, width=3):
    """Replace bright boundary contamination with nearby foreground color."""
    import cv2
    import numpy as np

    frame = np.asarray(reference_frame, dtype=np.uint8)
    region = np.asarray(subject).astype(bool)
    if frame.ndim != 3 or frame.shape[-1] != 3:
        raise ValueError(
            "Recast edge cleanup needs an H/W/RGB reference image."
        )
    if region.shape != frame.shape[:2]:
        raise ValueError(
            "Recast edge cleanup mask does not match its reference image."
        )
    cleaned = frame.copy()
    current = region.copy()
    kernel = np.ones((3, 3), dtype=np.uint8)
    for _ in range(max(1, int(width))):
        inner = cv2.erode(
            current.astype(np.uint8),
            kernel,
            iterations=1,
        ).astype(bool)
        boundary = current & ~inner
        if not bool(boundary.any()) or not bool(inner.any()):
            break
        neighbor_count = cv2.filter2D(
            inner.astype(np.float32),
            cv2.CV_32F,
            kernel.astype(np.float32),
            borderType=cv2.BORDER_REPLICATE,
        )
        replace = boundary & (neighbor_count > 0.0)
        for channel in range(3):
            neighbor_sum = cv2.filter2D(
                cleaned[..., channel].astype(np.float32)
                * inner.astype(np.float32),
                cv2.CV_32F,
                kernel.astype(np.float32),
                borderType=cv2.BORDER_REPLICATE,
            )
            values = neighbor_sum / np.maximum(neighbor_count, 1.0)
            cleaned[..., channel][replace] = np.rint(
                values[replace],
            ).clip(0, 255).astype(np.uint8)
        current = inner
    return cleaned


def _constrain_recast_u2net_matte(subject, opacity, u2net_alpha):
    """Keep a soft U2Net edge inside the person instance selected by SAM3."""
    import cv2
    import numpy as np

    region = np.asarray(subject).astype(bool)
    original_opacity = np.clip(
        np.asarray(opacity, dtype=np.float32),
        0.0,
        1.0,
    )
    matte = np.asarray(u2net_alpha, dtype=np.float32)
    if matte.size and float(matte.max()) > 1.0:
        matte = matte / 255.0
    matte = np.clip(matte, 0.0, 1.0)
    if (
        region.shape != original_opacity.shape
        or region.shape != matte.shape
    ):
        raise ValueError(
            "U2Net matte dimensions do not match the selected SAM3 person."
        )
    if not bool(region.any()):
        raise ValueError("The selected SAM3 person mask is empty.")

    # SAM3 owns identity selection. U2Net is allowed only a small perimeter
    # around that instance so another person in the reference cannot leak
    # back into the conditioning image.
    edge_width = max(
        1,
        min(4, int(round(min(region.shape[:2]) * 0.004))),
    )
    kernel_size = edge_width * 2 + 1
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    guard = cv2.dilate(
        region.astype(np.uint8),
        kernel,
        iterations=1,
    ).astype(bool)
    guard_soft = cv2.GaussianBlur(
        guard.astype(np.float32),
        (0, 0),
        sigmaX=max(0.75, edge_width * 0.55),
        sigmaY=max(0.75, edge_width * 0.55),
    )
    guard_soft[~guard] = 0.0

    # Retain a feathered SAM3 silhouette even if U2Net misses a hand, hair
    # curl, or dark clothing. U2Net still supplies the cleaner outer alpha.
    inside_distance = cv2.distanceTransform(
        region.astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    sam_feather = np.clip(
        inside_distance / float(edge_width + 0.5),
        0.0,
        1.0,
    )
    sam_feather *= original_opacity
    refined = np.maximum(matte * guard_soft, sam_feather)
    refined[~guard] = 0.0
    return np.clip(refined, 0.0, 1.0).astype(np.float32)


def _get_recast_u2net_session():
    """Load the existing local background-removal model once on CPU."""
    global _recast_u2net_session

    if _recast_u2net_session is not None:
        return _recast_u2net_session
    with _recast_u2net_session_lock:
        if _recast_u2net_session is None:
            model_home = os.path.join(_app_dir, "ckpts", "rembg")
            os.makedirs(model_home, exist_ok=True)
            os.environ.setdefault("U2NET_HOME", model_home)
            from services.rembg_adapter import background_session

            print(
                "[Recast] Loading U2Net edge refinement on CPU "
                "(SAM3 remains the person selector; shared rembg adapter)"
            )
            _recast_u2net_session = background_session("u2net", force_cpu=True)
    return _recast_u2net_session


def _run_recast_u2net_matte(reference_frame, reference_path=None):
    """Return decontaminated foreground RGB and alpha, with a small cache."""
    import numpy as np
    from PIL import Image as _PILImage
    from services.rembg_adapter import remove_background_image

    frame = np.asarray(reference_frame, dtype=np.uint8)
    cache_key = None
    if reference_path:
        try:
            stat = os.stat(reference_path)
            cache_key = (
                os.path.normcase(os.path.realpath(reference_path)),
                int(stat.st_mtime_ns),
                int(stat.st_size),
            )
        except OSError:
            cache_key = None
    if cache_key is not None:
        with _recast_u2net_cache_lock:
            cached = _recast_u2net_cache.get(cache_key)
            if cached is not None:
                return cached[0].copy(), cached[1].copy()

    session = _get_recast_u2net_session()
    with _recast_u2net_run_lock:
        cutout = remove_background_image(
            _PILImage.fromarray(frame),
            model="u2net",
            session=session,
            alpha_matting=True,
            alpha_matting_erode_size=1,
            bgcolor=(0, 0, 0, 0),
        )
    if not isinstance(cutout, _PILImage.Image):
        raise ValueError("U2Net returned an unsupported Recast matte.")
    cutout_array = np.asarray(cutout.convert("RGBA"), dtype=np.uint8)
    foreground = cutout_array[..., :3].copy()
    alpha = cutout_array[..., 3].astype(np.float32) / 255.0
    if foreground.shape != frame.shape or alpha.shape != frame.shape[:2]:
        raise ValueError("U2Net returned a mismatched Recast matte size.")

    if cache_key is not None:
        with _recast_u2net_cache_lock:
            _recast_u2net_cache[cache_key] = (
                foreground.copy(),
                alpha.copy(),
            )
            while len(_recast_u2net_cache) > _RECAST_U2NET_CACHE_LIMIT:
                oldest_key = next(iter(_recast_u2net_cache))
                _recast_u2net_cache.pop(oldest_key, None)
    return foreground, alpha


def _refine_recast_reference_cutout(
    reference_frame,
    subject,
    opacity,
    mask_source,
    *,
    reference_path=None,
    matte_runner=None,
):
    """Clean one selected reference subject without changing its identity."""
    import cv2
    import numpy as np

    frame = np.asarray(reference_frame, dtype=np.uint8)
    selected = np.asarray(subject).astype(bool)
    selected_opacity = np.clip(
        np.asarray(opacity, dtype=np.float32),
        0.0,
        1.0,
    )
    # Respect a user's authored transparent cutout. It already has the most
    # precise alpha available and should not be reinterpreted by U2Net.
    if str(mask_source).lower().startswith("png alpha"):
        return selected, selected_opacity, mask_source, frame.copy()

    runner = matte_runner or _run_recast_u2net_matte
    edge_width = max(
        1,
        min(4, int(round(min(selected.shape[:2]) * 0.004))),
    )
    fallback_rgb = _decontaminate_recast_reference_edges(
        frame,
        selected,
        width=edge_width,
    )
    try:
        u2net_rgb, u2net_alpha = runner(
            frame,
            reference_path=reference_path,
        )
        u2net_rgb = np.asarray(u2net_rgb, dtype=np.uint8)
        u2net_alpha = np.asarray(u2net_alpha, dtype=np.float32)
        if u2net_rgb.shape != frame.shape:
            raise ValueError("U2Net foreground RGB size is invalid.")
        if u2net_alpha.shape != selected.shape:
            raise ValueError("U2Net alpha size is invalid.")
        normalized_alpha = (
            u2net_alpha / 255.0
            if u2net_alpha.size and float(u2net_alpha.max()) > 1.0
            else u2net_alpha
        )
        coverage = float(np.count_nonzero(
            (normalized_alpha > 0.05) & selected,
        )) / float(max(1, np.count_nonzero(selected)))
        if coverage < 0.45:
            raise ValueError(
                f"U2Net covered only {coverage:.0%} of the selected person."
            )
        refined_opacity = _constrain_recast_u2net_matte(
            selected,
            selected_opacity,
            normalized_alpha,
        )
        refined_subject = refined_opacity > 0.02
        cleaned_rgb = fallback_rgb
        valid_foreground = normalized_alpha > 0.01
        cleaned_rgb[valid_foreground] = u2net_rgb[valid_foreground]
        return (
            refined_subject,
            refined_opacity,
            f"{mask_source} + U2Net soft edge",
            cleaned_rgb,
        )
    except Exception as exc:
        # Recast must still work offline or when the optional matte runtime is
        # unavailable. The local fallback removes the most obvious fringe and
        # feathers only the boundary of the SAM-selected person.
        distance = cv2.distanceTransform(
            selected.astype(np.uint8),
            cv2.DIST_L2,
            3,
        )
        fallback_opacity = np.minimum(
            selected_opacity,
            np.clip(
                distance / float(edge_width + 0.5),
                0.0,
                1.0,
            ),
        ).astype(np.float32)
        print(
            "[Recast] U2Net edge refinement unavailable; using local "
            f"boundary cleanup ({exc})"
        )
        return (
            selected,
            fallback_opacity,
            f"{mask_source} + local edge cleanup",
            fallback_rgb,
        )


def _recast_subject_crop_box(subject, margin_fraction=0.08):
    """Return a padded subject box without discarding any identity pixels."""
    import numpy as np

    region = np.asarray(subject).astype(bool)
    ys, xs = np.nonzero(region)
    if len(xs) == 0:
        return 0, 0, region.shape[1], region.shape[0]
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    margin = max(4, int(round(max(x1 - x0, y1 - y0) * margin_fraction)))
    return (
        max(0, x0 - margin),
        max(0, y0 - margin),
        min(region.shape[1], x1 + margin),
        min(region.shape[0], y1 + margin),
    )


def _recast_face_detail_crop_box(subject):
    """Frame the upper identity region while retaining hair and shoulders.

    Recast references are expected to contain one clear replacement subject.
    A second, tighter view of that same subject gives SCAIL-2 substantially
    more facial detail without sacrificing the primary image's outfit/body
    information.  The semantic subject silhouette keeps this deterministic
    and avoids introducing a separate face-model download.
    """
    import numpy as np

    region = np.asarray(subject).astype(bool)
    height, width = region.shape[:2]
    ys, xs = np.nonzero(region)
    if len(xs) == 0 or width < 2 or height < 2:
        return 0, 0, width, height

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    subject_width = max(1, x1 - x0)
    subject_height = max(1, y1 - y0)

    # The upper 56% of an upright subject is a reliable head-and-shoulders
    # detail view.  A roughly 4:5 crop matches the successful manual Recast
    # close-up workflow while leaving room for hair, neck, and clothing cues.
    crop_height = max(2, int(round(subject_height * 0.56)))
    crop_width = max(
        2,
        int(round(crop_height * 0.80)),
        int(round(subject_width * 0.66)),
    )
    crop_height = max(crop_height, int(round(crop_width / 0.82)))
    crop_width = min(width, crop_width)
    crop_height = min(height, crop_height)

    upper_limit = y0 + max(1, int(round(subject_height * 0.40)))
    upper_xs = np.nonzero(region & (
        np.arange(height, dtype=np.int32)[:, None] < upper_limit
    ))[1]
    center_x = (
        float(np.median(upper_xs))
        if len(upper_xs)
        else (x0 + x1) / 2.0
    )

    left = int(round(center_x - crop_width / 2.0))
    top = int(round(y0 - subject_height * 0.02))
    left = max(0, min(left, width - crop_width))
    top = max(0, min(top, height - crop_height))
    return left, top, left + crop_width, top + crop_height


def _derive_recast_face_detail_reference(
    reference_path,
    output_path,
    *,
    refine_cutout=True,
):
    """Persist an automatic head-and-shoulders view of one reference."""
    import numpy as np
    from PIL import Image as _PILImage, ImageOps as _PILImageOps

    with _PILImage.open(reference_path) as source:
        rgba = _PILImageOps.exif_transpose(source).convert("RGBA")
        rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
        alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)

    subject, opacity, mask_source = _recast_reference_subject_mask(rgb, alpha)
    foreground_rgb = rgb
    if refine_cutout:
        subject, opacity, mask_source, foreground_rgb = (
            _refine_recast_reference_cutout(
                rgb,
                subject,
                opacity,
                mask_source,
                reference_path=reference_path,
            )
        )
    crop_box = _recast_face_detail_crop_box(subject)
    if crop_box == (0, 0, rgba.width, rgba.height):
        return None
    clean_rgba = np.concatenate(
        (
            np.asarray(foreground_rgb, dtype=np.uint8),
            np.rint(np.clip(opacity, 0.0, 1.0) * 255.0)
            .astype(np.uint8)[..., None],
        ),
        axis=-1,
    )
    detail = _PILImage.fromarray(clean_rgba).crop(crop_box)
    if detail.width < 2 or detail.height < 2:
        return None
    detail.save(output_path, format="PNG")
    left, top, right, bottom = crop_box
    metadata = {
        "path": output_path,
        "crop_box": list(crop_box),
        "source_size": [rgba.width, rgba.height],
        "detail_size": [detail.width, detail.height],
        "detail_source": f"upper-subject crop from {mask_source}",
    }
    return {
        "metadata": metadata,
        # Reuse this one segmentation pass for both generated SCAIL views.
        # Without these cached layers, the primary plus derived crop would
        # make SAM3 analyze the same identity three times.
        "source_conditioning": (
            subject,
            opacity,
            mask_source,
            foreground_rgb,
        ),
        "detail_conditioning": (
            subject[top:bottom, left:right],
            opacity[top:bottom, left:right],
            mask_source,
            foreground_rgb[top:bottom, left:right],
        ),
    }


def _recast_region_bbox_aspect(region):
    """Return width/height for the visible bounding box of a mask."""
    import numpy as np

    ys, xs = np.nonzero(np.asarray(region).astype(bool))
    if len(xs) == 0:
        return None
    width = max(1, int(xs.max()) - int(xs.min()) + 1)
    height = max(1, int(ys.max()) - int(ys.min()) + 1)
    return float(width) / float(height)


def _recast_face_detail_upscale_factor(detail_size, canvas_size):
    """Return the enlargement needed to contain a detail view on its canvas."""
    try:
        detail_width, detail_height = (
            float(detail_size[0]),
            float(detail_size[1]),
        )
        canvas_width, canvas_height = (
            float(canvas_size[0]),
            float(canvas_size[1]),
        )
    except (IndexError, TypeError, ValueError):
        return None
    if min(
        detail_width,
        detail_height,
        canvas_width,
        canvas_height,
    ) <= 0:
        return None
    return min(
        canvas_width / detail_width,
        canvas_height / detail_height,
    )


def _recast_should_add_auto_face_detail(
    mapping,
    enabled=True,
    *,
    source_probe_mask=None,
    semantic_color=None,
    reference_subject=None,
    detail_size=None,
    canvas_size=None,
    max_upscale=1.75,
):
    """Use auto detail only when it will not compete with an explicit view."""
    eligible = bool(
        enabled
        and not mapping.get("reference_aligned_to_source")
        and not mapping.get("additional_ref_image_paths")
    )
    if not eligible:
        return False

    upscale_factor = _recast_face_detail_upscale_factor(
        detail_size,
        canvas_size,
    )
    if (
        upscale_factor is not None
        and upscale_factor > float(max_upscale)
    ):
        return False

    if (
        source_probe_mask is None
        or semantic_color is None
        or reference_subject is None
    ):
        return eligible

    import numpy as np

    source_mask = np.asarray(source_probe_mask)
    if source_mask.ndim == 3 and source_mask.shape[-1] == 3:
        target_region = np.all(
            source_mask == np.asarray(semantic_color, dtype=np.uint8),
            axis=-1,
        )
    else:
        target_region = source_mask.astype(bool)
    target_aspect = _recast_region_bbox_aspect(target_region)
    reference_aspect = _recast_region_bbox_aspect(reference_subject)
    if target_aspect is None or reference_aspect is None:
        return eligible

    # A tall/narrow driving silhouette normally means a full-body shot. If
    # the supplied identity is a substantially wider upper-body portrait,
    # another enlarged face crop becomes a second competing spatial subject.
    # Keep the primary identity view but omit that redundant extra region.
    if (
        target_aspect < 0.65
        and reference_aspect > target_aspect * 1.45
    ):
        return False
    return eligible


def _fit_recast_reference_layers(
    rgb, semantic_rgb, width, height, *, aligned=False,
    crop_to_subject=True, canvas_color=(127, 127, 127),
):
    """Apply the exact shared image/mask transform used by Recast."""
    import numpy as np
    from PIL import Image as _PILImage

    rgb_image = _PILImage.fromarray(np.asarray(rgb, dtype=np.uint8))
    mask_image = _PILImage.fromarray(np.asarray(semantic_rgb, dtype=np.uint8))
    if aligned:
        scale = max(width / rgb_image.width, height / rgb_image.height)
        resized_size = (
            max(width, int(round(rgb_image.width * scale))),
            max(height, int(round(rgb_image.height * scale))),
        )
        rgb_image = rgb_image.resize(
            resized_size, resample=_PILImage.Resampling.LANCZOS,
        )
        mask_image = mask_image.resize(
            resized_size, resample=_PILImage.Resampling.NEAREST,
        )
        left = (resized_size[0] - width) // 2
        top = (resized_size[1] - height) // 2
        box = (left, top, left + width, top + height)
        return rgb_image.crop(box), mask_image.crop(box)

    subject = np.any(np.asarray(semantic_rgb, dtype=np.uint8) > 30, axis=-1)
    crop_box = (
        _recast_subject_crop_box(subject)
        if crop_to_subject
        else (0, 0, rgb_image.width, rgb_image.height)
    )
    rgb_image = rgb_image.crop(crop_box)
    mask_image = mask_image.crop(crop_box)
    scale = min(width / rgb_image.width, height / rgb_image.height)
    resized_size = (
        max(1, min(width, int(round(rgb_image.width * scale)))),
        max(1, min(height, int(round(rgb_image.height * scale)))),
    )
    rgb_image = rgb_image.resize(
        resized_size, resample=_PILImage.Resampling.LANCZOS,
    )
    mask_image = mask_image.resize(
        resized_size, resample=_PILImage.Resampling.NEAREST,
    )
    rgb_canvas = _PILImage.new(
        "RGB",
        (width, height),
        tuple(int(value) for value in canvas_color),
    )
    mask_canvas = _PILImage.new("RGB", (width, height), (0, 0, 0))
    offset = ((width - resized_size[0]) // 2, (height - resized_size[1]) // 2)
    rgb_canvas.paste(rgb_image, offset)
    mask_canvas.paste(mask_image, offset)
    return rgb_canvas, mask_canvas


def _prepare_recast_reference_frame(
    reference_path, color, *, isolate_reference=True,
    aligned_semantic_mask=None, subject_conditioning=None,
    spatial_background=None, width=832, height=480,
):
    """Build separate CLIP-identity and spatial RGB inputs for SCAIL-2."""
    import numpy as np
    from PIL import Image as _PILImage, ImageOps as _PILImageOps

    with _PILImage.open(reference_path) as source:
        rgba = _PILImageOps.exif_transpose(source).convert("RGBA")
        rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
        alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)

    aligned = aligned_semantic_mask is not None
    foreground_rgb = rgb
    if aligned:
        semantic_rgb = np.asarray(aligned_semantic_mask, dtype=np.uint8)
        if semantic_rgb.shape[:2] != rgb.shape[:2]:
            semantic_rgb = np.asarray(
                _PILImage.fromarray(semantic_rgb, mode="RGB").resize(
                    (rgb.shape[1], rgb.shape[0]),
                    resample=_PILImage.Resampling.NEAREST,
                ),
                dtype=np.uint8,
            )
        subject = np.any(semantic_rgb > 30, axis=-1)
        opacity = subject.astype(np.float32)
        mask_source = "aligned source overlap"
    else:
        if subject_conditioning is None:
            subject, opacity, mask_source = _recast_reference_subject_mask(
                rgb, alpha,
            )
            if isolate_reference:
                subject, opacity, mask_source, foreground_rgb = (
                    _refine_recast_reference_cutout(
                        rgb,
                        subject,
                        opacity,
                        mask_source,
                        reference_path=reference_path,
                    )
                )
        else:
            if len(subject_conditioning) == 4:
                (
                    subject,
                    opacity,
                    mask_source,
                    foreground_rgb,
                ) = subject_conditioning
            elif len(subject_conditioning) == 3:
                subject, opacity, mask_source = subject_conditioning
            else:
                raise ValueError(
                    "Cached Recast reference conditioning is invalid."
                )
            subject = np.asarray(subject).astype(bool)
            opacity = np.asarray(opacity, dtype=np.float32)
            foreground_rgb = np.asarray(foreground_rgb, dtype=np.uint8)
            if (
                subject.shape != rgb.shape[:2]
                or opacity.shape != rgb.shape[:2]
                or foreground_rgb.shape != rgb.shape
            ):
                raise ValueError(
                    "Cached Recast reference mask does not match its image."
                )
        semantic_rgb = np.zeros_like(rgb, dtype=np.uint8)
        semantic_rgb[subject] = np.asarray(color, dtype=np.uint8)

    if isolate_reference:
        foreground_image, prepared_mask = _fit_recast_reference_layers(
            foreground_rgb,
            semantic_rgb,
            int(width),
            int(height),
            aligned=aligned,
            crop_to_subject=True,
        )
        opacity_rgb = np.repeat(
            np.rint(np.clip(opacity, 0.0, 1.0) * 255.0)
            .astype(np.uint8)[..., None],
            3,
            axis=-1,
        )
        opacity_image, _ = _fit_recast_reference_layers(
            opacity_rgb,
            semantic_rgb,
            int(width),
            int(height),
            aligned=aligned,
            crop_to_subject=True,
            canvas_color=(0, 0, 0),
        )
        if spatial_background is None:
            background = np.full(
                (int(height), int(width), 3),
                127,
                dtype=np.uint8,
            )
        else:
            background = np.asarray(spatial_background, dtype=np.uint8)
            if background.ndim != 3 or background.shape[-1] != 3:
                raise ValueError(
                    "Recast spatial background must be an H/W/RGB image; "
                    f"got {background.shape}."
                )
            if background.shape[:2] != (int(height), int(width)):
                background = np.asarray(
                    _PILImage.fromarray(background).resize(
                        (int(width), int(height)),
                        resample=_PILImage.Resampling.LANCZOS,
                    ),
                    dtype=np.uint8,
                )
        foreground_array = np.asarray(
            foreground_image.convert("RGB"),
            dtype=np.uint8,
        )
        prepared_opacity = (
            np.asarray(
                opacity_image.convert("RGB"),
                dtype=np.float32,
            )[..., :1]
            / 255.0
        )
        semantic_region = np.any(
            np.asarray(
                prepared_mask.convert("RGB"),
                dtype=np.uint8,
            ) > 30,
            axis=-1,
        )
        prepared_opacity[~semantic_region] = 0.0
        prepared_array = np.rint(
            foreground_array.astype(np.float32) * prepared_opacity
            + background.astype(np.float32) * (1.0 - prepared_opacity)
        ).clip(0, 255).astype(np.uint8)
        prepared_image = _PILImage.fromarray(prepared_array)
    else:
        prepared_image, prepared_mask = _fit_recast_reference_layers(
            rgb,
            semantic_rgb,
            int(width),
            int(height),
            aligned=aligned,
            crop_to_subject=False,
        )
    if isolate_reference:
        # Keep the original, uncropped reference composition for CLIP identity.
        # Only the VAE/spatial reference gets the source-scene background and
        # tighter subject framing. This preserves the strong face signal
        # observed with isolation disabled without allowing the reference
        # room/background to leak through SCAIL-2's spatial latent.
        identity_image, _ = _fit_recast_reference_layers(
            rgb,
            semantic_rgb,
            int(width),
            int(height),
            aligned=aligned,
            crop_to_subject=False,
        )
    else:
        identity_image = prepared_image.copy()
    return {
        "image": prepared_image,
        "identity_image": identity_image,
        "mask": prepared_mask,
        "mask_source": mask_source,
        "source_size": (int(rgb.shape[1]), int(rgb.shape[0])),
        "prepared_size": (int(width), int(height)),
    }


def _recast_image_data_uri(image, image_format="PNG"):
    import base64
    import io

    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    mime = "image/png" if image_format.upper() == "PNG" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(buffer.getvalue()).decode()


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


def _recast_reference_preview_payload(
    prepared, mapping_index, view_index, kind, view_metadata=None,
):
    image = prepared["image"].convert("RGB")
    identity_image = prepared["identity_image"].convert("RGB")
    mask = prepared["mask"].convert("RGB")
    payload = {
        "mapping_index": mapping_index,
        "view_index": view_index,
        "kind": kind,
        "mask_source": prepared["mask_source"],
        "source_size": list(prepared["source_size"]),
        "prepared_size": list(prepared["prepared_size"]),
        "prepared_image": _recast_image_data_uri(image),
        "semantic_mask": _recast_image_data_uri(mask),
    }
    if view_metadata:
        payload.update({
            key: value
            for key, value in view_metadata.items()
            if key in {
                "crop_box", "detail_size", "detail_source",
                "detail_upscale_factor",
            }
        })
    if mapping_index == 0 and view_index == 0:
        payload["clip_identity_image"] = _recast_image_data_uri(identity_image)
    return payload


def _prepare_recast_reference_conditioning(
    mappings, source_probe_mask, output_dir, job_id, *,
    isolate_reference, selected_count, auto_face_detail=True,
    source_frame=None, reference_canvas=None, mapping_anchors=None,
):
    """Prepare reference pairs using each character's own timeline anchor."""
    import numpy as np
    from PIL import Image as _PILImage, ImageOps as _PILImageOps
    from shared import magic_mask

    os.makedirs(output_dir, exist_ok=True)
    image_paths = []
    mask_paths = []
    clip_identity_path = None
    expected_colors = []
    previews = []
    auto_face_detail_refs = []
    primary_target_refs = []
    canvas_width, canvas_height = 832, 480
    anchor_list = (
        mapping_anchors
        if isinstance(mapping_anchors, list)
        else []
    )
    first_anchor_frame = None
    if anchor_list and isinstance(anchor_list[0], dict):
        first_anchor_frame = anchor_list[0].get("source_frame")
    if reference_canvas is not None:
        try:
            canvas_width, canvas_height = (
                int(reference_canvas[0]),
                int(reference_canvas[1]),
            )
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                "Recast reference canvas must contain width and height."
            ) from exc
        if (
            min(canvas_width, canvas_height) <= 0
            or canvas_width % 32
            or canvas_height % 32
        ):
            raise ValueError(
                "Recast reference canvas dimensions must be positive and "
                "divisible by 32."
            )
    elif source_frame is not None:
        canvas_width, canvas_height = _recast_reference_canvas_size(
            source_frame,
        )
    elif first_anchor_frame is not None:
        canvas_width, canvas_height = _recast_reference_canvas_size(
            first_anchor_frame,
        )
    for mapping_index, mapping in enumerate(mappings):
        color = _RECAST_MASK_COLORS[mapping_index]
        mapping_source_frame = source_frame
        mapping_source_mask = source_probe_mask
        if (
            mapping_index < len(anchor_list)
            and isinstance(anchor_list[mapping_index], dict)
        ):
            mapping_source_frame = anchor_list[mapping_index].get(
                "source_frame",
                mapping_source_frame,
            )
            mapping_source_mask = anchor_list[mapping_index].get(
                "source_mask",
                mapping_source_mask,
            )
        spatial_background = None
        if mapping_source_frame is not None:
            scene_layers = _build_recast_source_scene_layers(
                mapping_source_frame,
                mapping_source_mask,
                selected_count,
                output_size=(canvas_width, canvas_height),
            )
            spatial_background = scene_layers["image"]
        views = [{
            "kind": "primary",
            "path": mapping["ref_image_path"],
        }]
        if _recast_should_add_auto_face_detail(mapping, auto_face_detail):
            detail_path = os.path.join(
                output_dir,
                f"recast_auto_face_detail_{job_id}_{mapping_index + 1}.png",
            )
            detail_result = _derive_recast_face_detail_reference(
                mapping["ref_image_path"],
                detail_path,
                refine_cutout=isolate_reference,
            )
            if detail_result:
                views[0]["subject_conditioning"] = detail_result[
                    "source_conditioning"
                ]
                detail_upscale_factor = _recast_face_detail_upscale_factor(
                    detail_result["metadata"]["detail_size"],
                    (canvas_width, canvas_height),
                )
                detail_result["metadata"]["detail_upscale_factor"] = (
                    round(detail_upscale_factor, 3)
                    if detail_upscale_factor is not None
                    else None
                )
                if _recast_should_add_auto_face_detail(
                    mapping,
                    auto_face_detail,
                    source_probe_mask=mapping_source_mask,
                    semantic_color=color,
                    reference_subject=detail_result[
                        "source_conditioning"
                    ][0],
                    detail_size=detail_result["metadata"]["detail_size"],
                    canvas_size=(canvas_width, canvas_height),
                ):
                    views.append({
                        "kind": "auto_face_detail",
                        "path": detail_path,
                        "metadata": detail_result["metadata"],
                        "subject_conditioning": detail_result[
                            "detail_conditioning"
                        ],
                    })
                    auto_face_detail_refs.append({
                        "mapping_index": mapping_index,
                        **detail_result["metadata"],
                    })
                else:
                    try:
                        os.remove(detail_path)
                    except OSError:
                        pass
                    if (
                        detail_upscale_factor is not None
                        and detail_upscale_factor > 1.75
                    ):
                        reason = (
                            "the crop would require "
                            f"{detail_upscale_factor:.2f}x enlargement"
                        )
                    else:
                        reason = (
                            "the source target is full-body while the identity "
                            "reference is already a tighter upper-body view"
                        )
                    print(
                        "[Recast] Skipped automatic face-detail spatial view "
                        f"for mapping {mapping_index + 1}: {reason}."
                    )
        views.extend({
            "kind": "additional",
            "path": path,
        } for path in mapping.get("additional_ref_image_paths", []))
        for view_index, view in enumerate(views):
            kind = view["kind"]
            reference_path = view["path"]
            aligned_mask = None
            if view_index == 0 and mapping.get("reference_aligned_to_source"):
                with _PILImage.open(reference_path) as reference_image:
                    reference_frame = np.asarray(
                        _PILImageOps.exif_transpose(reference_image).convert("RGB"),
                        dtype=np.uint8,
                    )
                reference_people = magic_mask.generate_keyword_masks(
                    reference_frame[None],
                    "person",
                    no_hole=True,
                    colorize_objects=True,
                    color_palette=_RECAST_MASK_COLORS,
                    max_colored_objects=len(_RECAST_MASK_COLORS),
                )[0]
                aligned_colors = (
                    _RECAST_MASK_COLORS[:selected_count]
                    if len(mappings) == 1 and selected_count > 1
                    else [color]
                )
                aligned_mask, matched = _align_recast_reference_mask(
                    mapping_source_mask,
                    reference_people,
                    aligned_colors,
                    _RECAST_MASK_COLORS,
                )
                if matched < len(aligned_colors):
                    raise ValueError(
                        "The edited first-frame reference could not be aligned "
                        f"to every selected source person ({matched}/"
                        f"{len(aligned_colors)})."
                    )
            prepared = _prepare_recast_reference_frame(
                reference_path,
                color,
                isolate_reference=isolate_reference,
                aligned_semantic_mask=aligned_mask,
                subject_conditioning=view.get("subject_conditioning"),
                spatial_background=spatial_background,
                width=canvas_width,
                height=canvas_height,
            )
            suffix = f"{mapping_index + 1}_{view_index + 1}"
            prepared_path = os.path.join(
                output_dir, f"recast_prepared_ref_{job_id}_{suffix}.png",
            )
            mask_path = os.path.join(
                output_dir, f"recast_prepared_mask_{job_id}_{suffix}.png",
            )
            prepared["image"].save(prepared_path)
            prepared["mask"].save(mask_path)
            if clip_identity_path is None:
                if isolate_reference:
                    clip_identity_path = os.path.join(
                        output_dir,
                        f"recast_clip_identity_ref_{job_id}_{suffix}.png",
                    )
                    prepared["identity_image"].save(clip_identity_path)
                else:
                    clip_identity_path = prepared_path
            image_paths.append(prepared_path)
            mask_paths.append(mask_path)
            expected_colors.append(list(color))
            if view_index == 0:
                primary_target_refs.append({
                    "mapping_index": mapping_index,
                    "image": prepared_path,
                    "mask": mask_path,
                    "color": list(color),
                })
            previews.append(
                _recast_reference_preview_payload(
                    prepared,
                    mapping_index,
                    view_index,
                    kind,
                    view.get("metadata"),
                )
            )
    if not image_paths:
        raise ValueError("Recast needs at least one prepared reference.")
    return {
        "image_refs": image_paths,
        "clip_identity_ref": clip_identity_path,
        "primary_mask": mask_paths[0],
        "additional_masks": mask_paths[1:],
        "expected_colors": expected_colors,
        "previews": previews,
        "auto_face_detail_refs": auto_face_detail_refs,
        "primary_target_refs": primary_target_refs,
        "reference_canvas": [canvas_width, canvas_height],
    }


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


def _recolor_recast_reference_mask(
    semantic_mask, global_mapping_index, local_mapping_index,
):
    """Recolor one prepared identity mask for a shot-local character slot."""
    import numpy as np

    mask = np.asarray(semantic_mask, dtype=np.uint8)
    global_color = np.asarray(
        _RECAST_MASK_COLORS[int(global_mapping_index)],
        dtype=np.uint8,
    )
    local_color = np.asarray(
        _RECAST_MASK_COLORS[int(local_mapping_index)],
        dtype=np.uint8,
    )
    region = np.all(mask == global_color, axis=-1)
    if not bool(region.any()):
        region = np.any(mask > 30, axis=-1)
    output = np.zeros_like(mask, dtype=np.uint8)
    output[region] = local_color
    return output


def _load_recast_reference_pair(
    image_path, mask_path, global_mapping_index, local_mapping_index,
):
    """Load a prepared image/mask pair and assign its shot-local color."""
    import numpy as np
    from PIL import Image as _PILImage

    with _PILImage.open(image_path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    with _PILImage.open(mask_path) as mask:
        semantic = np.asarray(mask.convert("RGB"), dtype=np.uint8)
    if semantic.shape != rgb.shape:
        raise ValueError(
            "Prepared Recast reference image and mask dimensions differ."
        )
    return (
        rgb,
        _recolor_recast_reference_mask(
            semantic,
            global_mapping_index,
            local_mapping_index,
        ),
    )


def _save_recast_reference_pair(
    output_dir, stem, image, semantic_mask,
):
    """Save an internal SCAIL reference pair and return both paths."""
    from PIL import Image as _PILImage

    os.makedirs(output_dir, exist_ok=True)
    image_path = os.path.join(output_dir, f"{stem}.png")
    mask_path = os.path.join(output_dir, f"{stem}_mask.png")
    _PILImage.fromarray(image).save(image_path)
    _PILImage.fromarray(semantic_mask).save(mask_path)
    return image_path, mask_path


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


def _normalize_repaint_region_mappings(raw_mappings):
    """Validate optional source-video → edited-frame semantic mappings."""
    if raw_mappings in (None, []):
        return []
    if not isinstance(raw_mappings, list):
        raise ValueError("Repaint region_mappings must be a list.")
    if len(raw_mappings) > len(_RECAST_MASK_COLORS):
        raise ValueError("SCAIL-2 supports at most five Repaint regions.")
    mappings = []
    for index, raw in enumerate(raw_mappings):
        if not isinstance(raw, dict):
            raise ValueError(f"Repaint region {index + 1} is invalid.")
        source = str(
            raw.get("source")
            or raw.get("source_target")
            or raw.get("source_description")
            or ""
        ).strip()
        target = str(
            raw.get("target")
            or raw.get("target_description")
            or raw.get("edited_target")
            or ""
        ).strip()
        if not source or not target:
            raise ValueError(
                f"Repaint region {index + 1} needs both a source-video "
                "description and an edited-frame description."
            )
        mappings.append({
            "id": str(raw.get("id") or f"repaint-{index + 1}"),
            "source": source,
            "target": target,
        })
    return mappings


def _repaint_resolution_for_aspect(
    width, height, pixel_budget=848 * 480, block_size=16,
):
    """Return a SCAIL-sized canvas while preserving the source aspect."""
    import math

    source_width = int(width)
    source_height = int(height)
    block = max(1, int(block_size))
    budget = max(block * block, int(pixel_budget))
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Repaint source dimensions must be positive.")
    ratio = float(source_width) / float(source_height)
    ideal_width = math.sqrt(float(budget) * ratio)
    ideal_height = math.sqrt(float(budget) / ratio)
    output_width = max(block, int(round(ideal_width / block)) * block)
    output_height = max(block, int(round(ideal_height / block)) * block)
    return output_width, output_height


def _validate_repaint_target_aspect(
    source_width, source_height, target_width, target_height,
    tolerance=0.025,
):
    """Reject edited frames that would require a destructive crop."""
    values = [
        int(source_width), int(source_height),
        int(target_width), int(target_height),
    ]
    if any(value <= 0 for value in values):
        raise ValueError("Repaint source and edited-frame dimensions must be positive.")
    source_ratio = float(values[0]) / float(values[1])
    target_ratio = float(values[2]) / float(values[3])
    difference = abs(target_ratio - source_ratio) / source_ratio
    if difference > float(tolerance):
        raise ValueError(
            "The edited first frame must keep the source video's aspect ratio "
            f"({values[0]}×{values[1]} source vs "
            f"{values[2]}×{values[3]} edited frame). "
            "Edit the extracted frame in Image Mode or resize without cropping."
        )
    return difference


def _prepare_repaint_target_frame(
    target_path, source_width, source_height, output_width, output_height,
    output_dir, job_id,
):
    """Orient, validate, and resize the edited frame without cropping."""
    from PIL import Image as _PILImage
    from PIL import ImageOps as _PILImageOps

    with _PILImage.open(target_path) as image:
        target = _PILImageOps.exif_transpose(image).convert("RGB")
        target_width, target_height = target.size
        _validate_repaint_target_aspect(
            source_width,
            source_height,
            target_width,
            target_height,
        )
        target = target.resize(
            (int(output_width), int(output_height)),
            resample=_PILImage.Resampling.LANCZOS,
        )
        os.makedirs(output_dir, exist_ok=True)
        prepared_path = os.path.join(
            output_dir,
            f"repaint_target_{job_id}.png",
        )
        target.save(prepared_path)
    return prepared_path, (target_width, target_height)


def _repaint_preview_data_uri(frame, semantic_mask, background="black"):
    """Blend a semantic mask over one RGB frame and return a JPEG data URI."""
    import base64
    import io as _io
    import numpy as np
    from PIL import Image as _PILImage

    rgb = np.asarray(frame, dtype=np.uint8)
    mask = np.asarray(semantic_mask, dtype=np.uint8)
    if rgb.shape != mask.shape:
        raise ValueError(
            f"Repaint preview frame/mask mismatch: {rgb.shape} vs {mask.shape}."
        )
    selected = (
        ~np.all(mask > 225, axis=-1)
        if background == "white"
        else np.any(mask > 30, axis=-1)
    )
    overlay = rgb.copy()
    if bool(selected.any()):
        overlay[selected] = (
            overlay[selected].astype(np.float32) * 0.45
            + mask[selected].astype(np.float32) * 0.55
        ).astype(np.uint8)
    buffer = _io.BytesIO()
    _PILImage.fromarray(overlay).save(buffer, format="JPEG", quality=85)
    return (
        "data:image/jpeg;base64,"
        + base64.b64encode(buffer.getvalue()).decode()
    )


def _build_repaint_semantic_conditioning(
    source_video, target_frame_path, mappings, output_dir,
    progress_callback=None, abort_callback=None,
):
    """Track mapped regions independently inside every detected camera shot."""
    import numpy as np
    from PIL import Image as _PILImage
    from shared import magic_mask

    source_path, source_frames, fps = magic_mask.prepare_video_mask_input(
        source_video,
    )
    shot_ranges = _detect_recast_shot_ranges(source_frames)
    if len(shot_ranges) > 1:
        print(
            "[Repaint] Detected "
            f"{len(shot_ranges)} camera shots; SAM3 will reacquire each "
            "mapped region after every cut."
        )
    with _PILImage.open(target_frame_path) as target_image:
        target_frame = np.asarray(target_image.convert("RGB"), dtype=np.uint8)

    source_masks = []
    target_masks = []
    mapping_summaries = []
    total = len(mappings)
    for index, mapping in enumerate(mappings):
        if abort_callback is not None:
            abort_callback()

        def _source_progress(done, frame_total, mapping_index=index):
            if abort_callback is not None:
                abort_callback()
            if progress_callback is not None:
                progress_callback(
                    mapping_index,
                    total,
                    done,
                    frame_total,
                )

        color = _RECAST_MASK_COLORS[index]
        source_mask = magic_mask.generate_keyword_masks(
            source_frames,
            mapping["source"],
            no_hole=True,
            colorize_objects=True,
            color_palette=[color],
            max_colored_objects=1,
            progress_callback=_source_progress,
            tracking_segments=shot_ranges,
        )
        summary = _summarize_recast_mapping_mask(source_mask, fps)
        if summary is None:
            raise ValueError(
                f"Repaint region {index + 1} found no "
                f"'{mapping['source']}' anywhere in the selected video."
            )
        target_mask = magic_mask.generate_keyword_masks(
            target_frame[None],
            mapping["target"],
            no_hole=True,
            colorize_objects=True,
            color_palette=[color],
            max_colored_objects=1,
        )[0]
        if not bool(target_mask.any()):
            raise ValueError(
                f"Repaint region {index + 1} found no "
                f"'{mapping['target']}' in the edited first frame."
            )
        source_masks.append(source_mask)
        target_masks.append(target_mask)
        mapping_summaries.append(summary)

    driving_mask, _ = _compose_recast_character_masks(
        source_masks,
        _RECAST_MASK_COLORS[:total],
        background_color=(0, 0, 0),
    )
    reference_mask, _ = _compose_recast_character_masks(
        target_masks,
        _RECAST_MASK_COLORS[:total],
        background_color=(255, 255, 255),
    )
    video_mask_path = magic_mask.save_mask_video(
        source_path,
        driving_mask,
        fps,
        [mapping["source"] for mapping in mappings],
        output_dir=output_dir,
        abort_callback=abort_callback,
        background_color=(0, 0, 0),
    )
    os.makedirs(output_dir, exist_ok=True)
    reference_mask_path = os.path.join(
        output_dir,
        "repaint_reference_mask_"
        + uuid.uuid4().hex[:8]
        + ".png",
    )
    _PILImage.fromarray(reference_mask).save(reference_mask_path)
    return {
        "source_video": source_path,
        "source_frames": source_frames,
        "fps": float(fps),
        "mapping_masks": source_masks,
        "mapping_summaries": mapping_summaries,
        "target_frame": target_frame,
        "target_masks": target_masks,
        "shot_ranges": [list(bounds) for bounds in shot_ranges],
        "shot_count": len(shot_ranges),
        "video_mask": video_mask_path,
        "reference_mask": reference_mask_path,
        "region_count": total,
    }


def _build_repaint_shot_prompt(
    active_count, *, finished_video_prompt=None, total_mapping_count=None,
):
    """Avoid mentioning mapped subjects that are absent from a camera shot."""
    count = max(1, min(5, int(active_count)))
    try:
        total_count = max(1, min(5, int(total_mapping_count)))
    except (TypeError, ValueError):
        total_count = None
    requested_prompt = str(finished_video_prompt or "").strip()
    if (
        total_count == count
        and any(character.isalnum() for character in requested_prompt)
    ):
        return requested_prompt
    noun = "region" if count == 1 else "regions"
    return (
        f"The {count} mapped edited {noun} move naturally with the exact "
        "source action and camera motion. Their edited appearance remains "
        "consistent, while the surrounding original scene, people, objects, "
        "lighting, and composition remain coherent and unchanged."
    )


def _build_repaint_shot_reference_conditioning(
    target_frame, target_masks, active_mapping_indices, source_frame,
    local_semantic_mask, output_dir, job_id, shot_index, *,
    cooccurring, reference_canvas, use_exact_target_frame=False,
):
    """Build one shot-local edited-region reference plus a clean scene anchor."""
    active = [int(index) for index in active_mapping_indices]
    if not active:
        raise ValueError("A generated Repaint shot needs an active region.")
    if any(
        index < 0 or index >= len(target_masks)
        for index in active
    ):
        raise ValueError("Repaint shot references contain an invalid mapping.")

    target_layers = []
    for local_index, mapping_index in enumerate(active):
        target_layers.append((
            target_frame,
            _recolor_recast_reference_mask(
                target_masks[mapping_index],
                mapping_index,
                local_index,
            ),
        ))

    if use_exact_target_frame:
        primary_image = target_frame
        primary_mask, _ = _compose_recast_character_masks(
            [layer[1] for layer in target_layers],
            _RECAST_MASK_COLORS[:len(active)],
            background_color=(255, 255, 255),
        )
        primary_mode = "edited_first_frame"
    else:
        primary_mode = "shot_layout"
        try:
            if len(active) > 1 and not cooccurring:
                raise ValueError(
                    "active edited regions never share one frame in this shot"
                )
            primary_image, primary_mask = (
                _compose_recast_group_reference_frame(
                    source_frame,
                    local_semantic_mask,
                    target_layers,
                    len(active),
                )
            )
        except ValueError as composition_error:
            print(
                f"[Repaint] Shot {shot_index + 1} has no usable shared "
                f"layout; using a balanced region sheet: "
                f"{composition_error}"
            )
            primary_image, primary_mask = (
                _compose_recast_cast_reference_frame(
                    target_layers,
                    len(active),
                    reference_canvas,
                )
            )
            primary_mode = "region_sheet"

    stem = f"repaint_shot_ref_{job_id}_{shot_index + 1}"
    primary_path, primary_mask_path = _save_recast_reference_pair(
        output_dir,
        stem,
        primary_image,
        primary_mask,
    )
    scene_reference = _build_recast_source_scene_reference(
        source_frame,
        local_semantic_mask,
        len(active),
        output_dir,
        f"repaint_{job_id}_shot_{shot_index + 1}",
        output_size=tuple(reference_canvas),
    )
    return {
        "image_start": primary_path,
        "primary_mask": primary_mask_path,
        "expected_colors": [
            list(_RECAST_MASK_COLORS[0])
            if len(active) == 1
            else None
        ],
        "source_scene_reference": scene_reference,
        "primary_mode": primary_mode,
    }


def _build_repaint_shot_manifest(
    base_params, conditioning, output_dir, job_id, *,
    reference_canvas, target_frame_count, generation_fps,
    minimum_frames, latent_size,
):
    """Create silent, exact-length mapped Repaint tasks per camera shot."""
    import copy
    import numpy as np

    source_frames, mapping_masks, shot_ranges = (
        _resample_recast_tracking_timeline(
            conditioning["source_frames"],
            conditioning["mapping_masks"],
            conditioning["shot_ranges"],
            target_frame_count,
        )
    )
    plans = _plan_recast_shot_segments(mapping_masks, shot_ranges)

    global_semantic = np.zeros(
        (*source_frames.shape[:-1], 3),
        dtype=np.uint8,
    )
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
        resized_source = _resize_recast_shot_frames(
            source_frames[start:end],
            reference_canvas,
        )
        published = dict(plan)
        published["active_mapping_indices"] = list(active)

        if not active:
            passthrough_path = os.path.join(
                output_dir,
                f"repaint_{job_id}_shot_{shot_index + 1}_source.mp4",
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
            background_color=(0, 0, 0),
        )
        resized_mask = _resize_recast_shot_frames(
            local_mask,
            reference_canvas,
            semantic=True,
        )
        use_exact_target_frame = (
            shot_index == 0
            and len(active) == len(mapping_masks)
            and all(
                bool(np.any(mapping_masks[index][start] > 30))
                for index in active
            )
        )
        # The user's edited image is the selected first source frame. Keep
        # its clean scene anchor on that same frame; pairing it with a later
        # camera position would create contradictory background references.
        anchor_index = (
            start
            if use_exact_target_frame
            else int(plan["anchor_frame_index"])
        )
        anchor_mask = _remap_recast_shot_mask(
            global_semantic[anchor_index],
            active,
            background_color=(0, 0, 0),
        )
        shot_refs = _build_repaint_shot_reference_conditioning(
            conditioning["target_frame"],
            conditioning["target_masks"],
            active,
            source_frames[anchor_index],
            anchor_mask,
            output_dir,
            job_id,
            shot_index,
            cooccurring=bool(plan["cooccurring"]),
            reference_canvas=reference_canvas,
            use_exact_target_frame=use_exact_target_frame,
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
            f"repaint_{job_id}_shot_{shot_index + 1}_guide.mp4",
        )
        mask_path = os.path.join(
            output_dir,
            f"repaint_{job_id}_shot_{shot_index + 1}_mask.mp4",
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
        custom_settings.update({
            "scail2_reference_mask_path": shot_refs["primary_mask"],
            "scail2_additional_reference_mask_paths": [],
            "scail2_reference_expected_colors": list(
                shot_refs["expected_colors"],
            ),
            "scail2_clip_reference_path": shot_refs["image_start"],
            "scail2_primary_reference_people": len(active),
            "scail2_dynamic_source_scene_reference": True,
            "scail2_timeline_source_scene_reference": False,
            "scail2_source_scene_reference_path": shot_refs[
                "source_scene_reference"
            ]["image"],
            "scail2_source_scene_mask_path": shot_refs[
                "source_scene_reference"
            ]["mask"],
        })
        shot_prompt = _build_repaint_shot_prompt(
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
                "image_start": shot_refs["image_start"],
                "image_refs": [],
                "video_length": generated_frames,
                "trim_tail_frames": trim_tail,
                "video_prompt_type": f"V{len(active)}A",
                "image_prompt_type": "S",
                # Internal shots remain silent. The finishing worker restores
                # one pristine source track after exact-frame assembly.
                "audio_prompt_type": "",
                "audio_guide": None,
                "audio_source": None,
                "force_fps": "control",
                "custom_settings": custom_settings,
                "output_filename": (
                    f"repaint_{job_id}_shot_{shot_index + 1}.mp4"
                ),
            },
        })
        plan["generated_task_index"] = len(tasks) - 1
        published.update({
            "generation_mode": "scail2",
            "generated_frame_count": generated_frames,
            "trim_tail_frames": trim_tail,
            "reference_mode": shot_refs["primary_mode"],
            "reference_anchor_frame_index": anchor_index,
            "native_scene_preservation": True,
        })
        published_plans.append(published)

    return {
        "tasks": tasks,
        "shots": plans,
        "published_shots": published_plans,
        "frame_count": int(target_frame_count),
        "fps": float(generation_fps),
    }


@api.post("/api/v1/repaint/preview")
async def repaint_preview_endpoint(request: Request):
    """Preview optional source/edited-frame semantic correspondences."""
    body = await request.json()
    workspace = body.get("workspace")
    video_path = _resolve_recast_media(body.get("video_path"), workspace)
    target_path = _resolve_recast_media(
        body.get("target_frame_path"),
        workspace,
    )
    if not video_path:
        raise HTTPException(
            status_code=400,
            detail=f"Video not found: {body.get('video_path')}",
        )
    if not target_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "Edited first frame not found: "
                f"{body.get('target_frame_path')}"
            ),
        )
    try:
        mappings = _normalize_repaint_region_mappings(
            body.get("region_mappings"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not mappings:
        raise HTTPException(
            status_code=400,
            detail="Add at least one region before previewing mappings.",
        )

    at_time = float(body.get("time", 0) or 0)
    try:
        import decord
        import numpy as np
        from PIL import Image as _PILImage
        from PIL import ImageOps as _PILImageOps
        from shared import magic_mask

        reader = decord.VideoReader(video_path)
        fps = reader.get_avg_fps() or 25
        frame_index = min(
            len(reader) - 1,
            max(0, int(at_time * fps)),
        )
        source_frame = reader[frame_index].asnumpy()
        del reader
        source_height, source_width = source_frame.shape[:2]
        with _PILImage.open(target_path) as image:
            target_image = _PILImageOps.exif_transpose(image).convert("RGB")
            _validate_repaint_target_aspect(
                source_width,
                source_height,
                *target_image.size,
            )
            target_frame = np.asarray(
                target_image.resize(
                    (source_width, source_height),
                    resample=_PILImage.Resampling.LANCZOS,
                ),
                dtype=np.uint8,
            )

        source_preview_mask = np.zeros_like(source_frame, dtype=np.uint8)
        target_preview_mask = np.full_like(
            target_frame,
            255,
            dtype=np.uint8,
        )
        source_occupied = np.zeros(
            source_frame.shape[:2],
            dtype=bool,
        )
        target_occupied = np.zeros(
            target_frame.shape[:2],
            dtype=bool,
        )
        results = []
        for index, mapping in enumerate(mappings):
            color = _RECAST_MASK_COLORS[index]
            source_mask = magic_mask.generate_keyword_masks(
                source_frame[None],
                mapping["source"],
                no_hole=True,
                colorize_objects=True,
                color_palette=[color],
                max_colored_objects=1,
            )[0]
            target_mask = magic_mask.generate_keyword_masks(
                target_frame[None],
                mapping["target"],
                no_hole=True,
                colorize_objects=True,
                color_palette=[color],
                max_colored_objects=1,
            )[0]
            source_region = np.any(source_mask > 30, axis=-1)
            target_region = np.any(target_mask > 30, axis=-1)
            source_preview_mask[source_region & ~source_occupied] = color
            target_preview_mask[target_region & ~target_occupied] = color
            source_occupied |= source_region
            target_occupied |= target_region
            results.append({
                "mapping_index": index,
                "source": mapping["source"],
                "target": mapping["target"],
                "source_found": bool(source_region.any()),
                "target_found": bool(target_region.any()),
                "color": list(color),
            })
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Repaint preview failed: {exc}",
        )

    found = all(
        result["source_found"] and result["target_found"]
        for result in results
    )
    return {
        "found": found,
        "frame_index": frame_index,
        "source_preview": _repaint_preview_data_uri(
            source_frame,
            source_preview_mask,
            background="black",
        ),
        "target_preview": _repaint_preview_data_uri(
            target_frame,
            target_preview_mask,
            background="white",
        ),
        "mapping_results": results,
    }


@api.post("/api/v1/repaint")
async def repaint_endpoint(request: Request):
    """Animate an edited first frame with SCAIL-2 and a source video.

    With no region mappings this deliberately mirrors the proven Studio
    Video/Frames SCAIL Animate path. Optional mappings add paired SAM3
    semantic masks for specific people or objects without changing that
    underlying motion-conditioning recipe.
    """
    body = await request.json()
    workspace = body.get("workspace")
    original_video_path = _resolve_recast_media(
        body.get("video_path"),
        workspace,
    )
    original_target_path = _resolve_recast_media(
        body.get("target_frame_path"),
        workspace,
    )
    if not original_video_path:
        raise HTTPException(
            status_code=400,
            detail=f"Video not found: {body.get('video_path')}",
        )
    if not original_target_path:
        raise HTTPException(
            status_code=400,
            detail=(
                "Edited first frame not found: "
                f"{body.get('target_frame_path')}"
            ),
        )
    try:
        mappings = _normalize_repaint_region_mappings(
            body.get("region_mappings"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    job_id = uuid.uuid4().hex[:8]
    video_path = original_video_path
    trim_start = body.get("start_time")
    trim_end = body.get("end_time")
    selected_start = 0.0
    selected_end = None
    if trim_start is not None and trim_end is not None:
        try:
            selected_start = float(trim_start)
            selected_end = float(trim_end)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="Repaint trim times must be numeric.",
            )
        if selected_start < 0 or selected_end <= selected_start + 0.05:
            raise HTTPException(
                status_code=400,
                detail="Repaint needs a valid source-video time range.",
            )
        try:
            import subprocess

            trim_dir = os.path.join(os.getcwd(), "uploads")
            os.makedirs(trim_dir, exist_ok=True)
            trimmed_path = os.path.join(
                trim_dir,
                f"repaint_trim_{job_id}.mp4",
            )
            command = [
                "ffmpeg", "-y", "-i", video_path,
                "-ss", f"{selected_start:.3f}",
                "-to", f"{selected_end:.3f}",
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k",
                trimmed_path,
            ]
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if process.returncode != 0 or not os.path.isfile(trimmed_path):
                raise RuntimeError(process.stderr[-500:])
            video_path = trimmed_path
            print(
                "[Repaint] Trimmed source to "
                f"[{selected_start:.2f}s, {selected_end:.2f}s] -> "
                f"{os.path.basename(trimmed_path)}"
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not prepare the selected Repaint range: {exc}",
            )

    try:
        import decord

        reader = decord.VideoReader(video_path)
        fps = float(reader.get_avg_fps() or 25)
        total_frames = len(reader)
        if total_frames <= 0:
            raise ValueError("the selected video range contains no frames")
        probe_frame = reader[0].asnumpy()
        del reader
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot read Repaint source video: {exc}",
        )

    source_height, source_width = probe_frame.shape[:2]
    resolution_profile = _normalize_recast_resolution_profile(
        body.get("resolution_profile"),
    )
    output_width, output_height = _recast_resolution_for_source(
        probe_frame,
        resolution_profile,
    )
    output_resolution = f"{output_width}x{output_height}"
    repaint_vram_gb = 0.0
    try:
        repaint_vram_gb = float(
            _get_cached_hardware().get("gpu_vram_gb", 0.0),
        )
    except (TypeError, ValueError, AttributeError):
        repaint_vram_gb = 0.0
    repaint_window_size = _recast_window_size_for_profile(
        resolution_profile,
        repaint_vram_gb,
    )
    if repaint_window_size <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "704p Repaint currently requires at least 16 GB of VRAM. "
                f"Detected {repaint_vram_gb:.1f} GB; select 512p or 480p."
            ),
        )
    print(
        f"[Repaint] Resolution profile {resolution_profile} -> "
        f"{output_resolution}."
    )
    if resolution_profile == "704p":
        hardware_label = (
            f"{repaint_vram_gb:.1f} GB VRAM"
            if repaint_vram_gb > 0
            else "unknown VRAM"
        )
        print(
            f"[Repaint] Adaptive 704p window: {hardware_label} -> "
            f"{repaint_window_size} frames with 5-frame overlap."
        )
    try:
        prepared_target_path, target_size = _prepare_repaint_target_frame(
            original_target_path,
            source_width,
            source_height,
            output_width,
            output_height,
            os.path.join(os.getcwd(), "uploads"),
            job_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not prepare the edited first frame: {exc}",
        )

    model_type = str(body.get("model_type") or "scail2_14B_fast")
    if model_type not in {"scail2_14B_fast", "scail2_14B"}:
        raise HTTPException(
            status_code=400,
            detail=(
                "Repaint requires SCAIL-2 Fast or SCAIL-2 HQ. "
                f"Received: {model_type}"
            ),
        )
    if wgp.get_model_def(model_type) is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model: {model_type}",
        )
    fast_profile = model_type == "scail2_14B_fast"
    duration_s = total_frames / fps if fps else 0.0
    force_fps = "control"
    generation_frames = total_frames
    if fps > 30.5:
        force_fps = "30"
        generation_frames = int(round(duration_s * 30.0))
        print(
            f"[Repaint] fps cap: {fps:.6g}fps source → "
            f"30fps ({generation_frames} frames)"
        )

    raw_prompt = str(body.get("prompt") or "").strip()
    prompt = raw_prompt or (
        "The edited first-frame scene moves naturally with the source "
        "video's exact action, interaction, and camera motion."
    )
    activated_loras = body.get("activated_loras")
    if not isinstance(activated_loras, list):
        activated_loras = []
    loras_multipliers = str(body.get("loras_multipliers") or "")
    region_count = len(mappings)
    process_type = f"V{region_count}A" if region_count else "V1"
    inference_steps = _normalize_scail2_inference_steps(
        body.get("num_inference_steps"),
        6 if fast_profile else 40,
    )
    # SCAIL-2 Fast uses a CFG-step-distilled LightX LoRA, so CFG remains at
    # one. The full model supports ordinary classifier-free guidance.
    guidance_scale = (
        1.0
        if fast_profile
        else _normalize_scail2_guidance_scale(
            body.get("guidance_scale"),
            5.0,
        )
    )
    print(
        f"[Repaint] Sampling: {inference_steps} steps, "
        f"guidance {guidance_scale:g} "
        f"({'Fast distilled' if fast_profile else 'HQ'})."
    )
    gen_params = {
        "prompt": prompt,
        "model_type": model_type,
        "negative_prompt": str(body.get("negative_prompt") or ""),
        "seed": body.get("seed", -1),
        "activated_loras": activated_loras,
        "loras_multipliers": loras_multipliers,
        "num_inference_steps": inference_steps,
        "flow_shift": 5 if fast_profile else 3,
        "guidance_scale": guidance_scale,
        "sample_solver": "euler" if fast_profile else "unipc",
        "generation_mode": "video",
        # Keep ``restyle`` as the internal saved-output id so existing gallery
        # filters and sidecars remain compatible; the UI calls this Repaint.
        "edit_sub_mode": "restyle",
        "video_prompt_type": process_type,
        "image_prompt_type": "S",
        "video_guide": video_path,
        "image_start": prepared_target_path,
        "video_length": generation_frames,
        "_duration_seconds": duration_s,
        "resolution": output_resolution,
        "force_fps": force_fps,
        "audio_prompt_type": "R",
        "input_video_strength": 1,
        "sliding_window_size": repaint_window_size,
        "sliding_window_overlap": 5,
        "settings_version": 2.57,
        "custom_settings": {
            "image_ref_keyword_content": (
                mappings[0]["target"] if mappings else "human character"
            ),
            "scail2_animate_preprocessing": "raw",
        },
        # Gallery Load Settings / API diagnostics.
        "edit_video_path": original_video_path,
        "edit_start_time": selected_start,
        "edit_end_time": selected_end if selected_end is not None else duration_s,
        "edit_repaint_target_frame": original_target_path,
        "edit_repaint_prepared_target_frame": prepared_target_path,
        "edit_repaint_target_size": list(target_size),
        "edit_repaint_region_mappings": mappings,
        "edit_repaint_region_count": region_count,
        "edit_repaint_resolution_profile": resolution_profile,
        "edit_repaint_output_resolution": [output_width, output_height],
        "edit_repaint_sliding_window_size": repaint_window_size,
        "edit_repaint_conditioning": (
            "semantic_regions" if mappings else "whole_frame_animate"
        ),
    }

    workspace_name = workspace or _get_active_workspace()
    job = {
        "id": job_id,
        "status": "queued",
        "progress": 0,
        "step": 0,
        "total_steps": 0,
        "phase": "",
        "message": "Queued (repaint)",
        "created_at": time.time(),
        "params": gen_params,
        "output_files": [],
        "error": None,
        "workspace": workspace_name,
        "out_dir": _workspace_dir(workspace_name),
    }
    _register_manual_generation_job(job)

    if not mappings:
        threading.Thread(
            target=_run_generation,
            args=(job_id,),
            daemon=False,
        ).start()
        return {
            "job_id": job_id,
            "status": "queued",
            "frames": generation_frames,
            "region_count": 0,
            "resolution_profile": resolution_profile,
            "resolution": output_resolution,
            "sliding_window_size": repaint_window_size,
            "num_inference_steps": inference_steps,
            "guidance_scale": guidance_scale,
            **_generation_job_acceptance(job),
        }

    def _run_repaint():
        abort_state = {"abort": False}
        shot_temp_dir = None
        shot_final_out_dir = None
        try:
            with _coordinated_generation_slot(
                job, description="HocusPocus Lab GPU preparation · repaint",
            ) as acquired:
                if not acquired:
                    return
                if not try_start(
                    job,
                    phase="Mapping repaint regions",
                    message=(
                        f"Mapping {region_count} Repaint "
                        f"region{'s' if region_count != 1 else ''}..."
                    ),
                ):
                    return
                if not register_abort_state(
                    job,
                    job_id,
                    _active_gen_states,
                    abort_state,
                ):
                    return

                progress_state = {"bucket": -1}

                def _abort_repaint_mapping():
                    if is_cancel_requested(job):
                        raise InterruptedError(
                            "Repaint region mapping was cancelled",
                        )

                def _mapping_progress(index, count, done, total):
                    percent = min(
                        100,
                        max(
                            0,
                            int(round(
                                100
                                * (
                                    index
                                    + float(done) / max(1, total)
                                )
                                / max(1, count)
                            )),
                        ),
                    )
                    bucket = percent // 5
                    if bucket == progress_state["bucket"]:
                        return
                    progress_state["bucket"] = bucket
                    if not update_job(
                        job,
                        phase="Mapping repaint regions",
                        message=f"Mapping Repaint regions... {percent}%",
                    ):
                        raise InterruptedError(
                            "Repaint region mapping was cancelled",
                        )

                conditioning = _build_repaint_semantic_conditioning(
                    video_path,
                    prepared_target_path,
                    mappings,
                    os.path.join(os.getcwd(), "uploads"),
                    progress_callback=_mapping_progress,
                    abort_callback=_abort_repaint_mapping,
                )
                if is_cancel_requested(job):
                    return
                job["params"]["video_mask"] = conditioning["video_mask"]
                job["params"]["custom_settings"][
                    "scail2_reference_mask_path"
                ] = conditioning["reference_mask"]
                job["params"]["custom_settings"][
                    "scail2_primary_reference_people"
                ] = region_count
                job["params"]["custom_settings"][
                    "scail2_reference_expected_colors"
                ] = [
                    list(color)
                    for color in _RECAST_MASK_COLORS[:region_count]
                ]
                job["params"]["edit_repaint_video_mask"] = conditioning[
                    "video_mask"
                ]
                job["params"]["edit_repaint_reference_mask"] = conditioning[
                    "reference_mask"
                ]
                job["params"]["edit_repaint_shot_ranges"] = conditioning[
                    "shot_ranges"
                ]
                job["params"]["edit_repaint_mapping_summaries"] = (
                    conditioning["mapping_summaries"]
                )
                print(
                    "[Repaint] Built native semantic correspondence for "
                    f"{region_count} region{'s' if region_count != 1 else ''}."
                )

                if not update_job(
                    job,
                    phase="Preparing camera shots",
                    message="Preparing shot-specific Repaint references...",
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
                    if force_fps == "30"
                    else float(conditioning.get("fps") or fps or 25.0)
                )
                try:
                    minimum_frames, _frame_step, latent_size = (
                        wgp.get_model_min_frames_and_step(model_type)
                    )
                except Exception:
                    minimum_frames, latent_size = 5, 4

                shot_temp_dir = tempfile.mkdtemp(
                    prefix="maestro-repaint-shots-",
                )
                try:
                    shot_manifest = _build_repaint_shot_manifest(
                        job["params"],
                        conditioning,
                        shot_temp_dir,
                        job_id,
                        reference_canvas=(output_width, output_height),
                        target_frame_count=generation_frames,
                        generation_fps=generation_fps,
                        minimum_frames=minimum_frames,
                        latent_size=latent_size,
                    )
                    if not shot_manifest["tasks"]:
                        raise ValueError(
                            "The mapped Repaint regions were too small to "
                            "schedule in any camera shot."
                        )
                except Exception:
                    shutil.rmtree(
                        shot_temp_dir,
                        ignore_errors=True,
                    )
                    shot_temp_dir = None
                    raise

                final_out_dir = job.get("out_dir") or _workspace_dir(
                    workspace_name,
                )
                shot_final_out_dir = final_out_dir
                job["params"].update({
                    "_defer_output_publication": True,
                    "_repaint_shot_manifest": shot_manifest["tasks"],
                    "_repaint_shot_temp_dir": shot_temp_dir,
                    "_repaint_final_out_dir": final_out_dir,
                    "_repaint_source_video": video_path,
                    "_repaint_shot_bundle": {
                        "shots": shot_manifest["shots"],
                        "published_shots": shot_manifest[
                            "published_shots"
                        ],
                        "frame_count": shot_manifest["frame_count"],
                        "fps": shot_manifest["fps"],
                        "resolved_seed": resolved_seed,
                    },
                    "edit_repaint_shot_aware": True,
                    "edit_repaint_shot_plan": shot_manifest[
                        "published_shots"
                    ],
                    "edit_repaint_native_scene_preservation": True,
                })
                # Generated shots and their references are disposable. The
                # finishing worker publishes only the exact joined timeline.
                job["out_dir"] = shot_temp_dir
                generated_count = len(shot_manifest["tasks"])
                passthrough_count = sum(
                    1
                    for shot in shot_manifest["shots"]
                    if shot["mode"] == "passthrough"
                )
                print(
                    "[Repaint] Shot-aware plan prepared "
                    f"{len(shot_manifest['shots'])} camera shots "
                    f"({generated_count} generated, "
                    f"{passthrough_count} source passthrough), "
                    f"{shot_manifest['frame_count']} exact output frames "
                    f"at {shot_manifest['fps']:.6g}fps."
                )
        except InterruptedError:
            return
        except Exception as exc:
            traceback.print_exc()
            if shot_temp_dir and os.path.isdir(shot_temp_dir):
                import shutil

                shutil.rmtree(shot_temp_dir, ignore_errors=True)
                if shot_final_out_dir:
                    job["out_dir"] = shot_final_out_dir
            finish_job(
                job,
                "failed",
                error=f"Repaint region mapping failed: {exc}",
                message="Region mapping failed",
            )
            return
        finally:
            unregister_abort_state(
                job_id,
                _active_gen_states,
                abort_state,
            )

        if not try_requeue(job, message="Queued (repaint)", phase=""):
            if shot_temp_dir and os.path.isdir(shot_temp_dir):
                import shutil

                shutil.rmtree(shot_temp_dir, ignore_errors=True)
                if shot_final_out_dir:
                    job["out_dir"] = shot_final_out_dir
            return
        _run_repaint_shot_generation(job_id)

    if execution_mode.policy().simulated:
        threading.Thread(target=_run_generation, args=(job_id,), daemon=False).start()
    else:
        threading.Thread(target=_run_repaint, daemon=False).start()
    return {
        "job_id": job_id,
        "status": "queued",
        "frames": generation_frames,
        "region_count": region_count,
        "resolution_profile": resolution_profile,
        "resolution": output_resolution,
        "sliding_window_size": repaint_window_size,
        "num_inference_steps": inference_steps,
        "guidance_scale": guidance_scale,
        **_generation_job_acceptance(job),
    }


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


def _resolve_outpaint_sampling(
    body, base_model_type, model_def, model_defaults,
):
    """Resolve model-aware Outpaint steps and guidance.

    Outpaint used to omit the Studio Advanced values and independently fall
    back to 8 steps. That is valid for distilled LTX-2, but LTXV 13B Dev
    rejects fewer than 20 steps. Use each model's own defaults, honor locked
    schedules, and reject invalid API input before it reaches the queue.
    """
    model_def = model_def if isinstance(model_def, dict) else {}
    model_defaults = (
        model_defaults if isinstance(model_defaults, dict) else {}
    )
    default_steps = (
        model_def.get("num_inference_steps")
        or model_defaults.get("num_inference_steps")
        or 8
    )
    default_guidance = (
        model_def.get("guidance_scale")
        or model_defaults.get("guidance_scale")
        or 1.0
    )

    try:
        default_steps = int(default_steps)
        default_guidance = float(default_guidance)
        if model_def.get("lock_inference_steps", False):
            inference_steps = default_steps
        else:
            inference_steps = int(
                body.get("num_inference_steps", default_steps)
            )
        if model_def.get("lock_guidance_scale", False):
            guidance_scale = default_guidance
        else:
            guidance_scale = float(
                body.get("guidance_scale", default_guidance)
            )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Inference Steps and Guidance Scale must be numeric."
        ) from error

    if inference_steps <= 0:
        raise ValueError("Inference Steps must be greater than zero.")
    if (
        base_model_type == "ltxv_13B"
        and not model_def.get("lock_inference_steps", False)
        and inference_steps < 20
    ):
        raise ValueError(
            "LTX Video 13B requires at least 20 inference steps."
        )
    return inference_steps, guidance_scale


def _resolve_outpaint_video_timing(
    source_frames,
    source_fps,
    model_def,
    reference_fps=None,
):
    """Resolve Outpaint duration, FPS, and the model's 8n+1 frame grid.

    The short-form Diffusers LTX-2.3 Outpaint demo resamples every source to
    24 fps.  ``reference_fps`` remains available for reproducing that narrow
    demo contract and rounds *up* to the next complete latent group so the
    source tail is not discarded. Maestro's production video path omits it:
    preserving source timing produced materially better long-form continuity
    and lets the normal sliding-window path carry clips beyond one window.
    """
    model_def = model_def if isinstance(model_def, dict) else {}
    try:
        fallback_fps = float(model_def.get("fps") or 25)
    except (TypeError, ValueError):
        fallback_fps = 25.0
    if not math.isfinite(fallback_fps) or fallback_fps <= 0:
        fallback_fps = 25.0

    try:
        source_frame_count = max(1, int(source_frames))
    except (TypeError, ValueError):
        source_frame_count = 1
    try:
        source_rate = float(source_fps)
    except (TypeError, ValueError):
        source_rate = fallback_fps
    if not math.isfinite(source_rate) or source_rate <= 0:
        source_rate = fallback_fps
    uses_reference_rate = reference_fps is not None
    if uses_reference_rate:
        try:
            target_fps = float(reference_fps)
        except (TypeError, ValueError):
            target_fps = 24.0
        if not math.isfinite(target_fps) or target_fps <= 0:
            target_fps = 24.0
    else:
        target_fps = source_rate

    duration = source_frame_count / source_rate
    try:
        minimum_frames = max(
            1,
            int(model_def.get("frames_minimum") or 1),
        )
    except (TypeError, ValueError):
        minimum_frames = 1
    try:
        frame_step = max(
            1,
            int(
                model_def.get("latent_size")
                or model_def.get("frames_steps")
                or 1
            ),
        )
    except (TypeError, ValueError):
        frame_step = 1

    nominal_frames = max(
        float(minimum_frames),
        (
            duration * target_fps
            if uses_reference_rate
            else float(source_frame_count)
        ),
    )
    if uses_reference_rate:
        # The reference loader clamps samples past EOF to the final source
        # frame.  Preserve that behavior instead of dropping up to seven
        # source frames when converting to LTX's causal temporal grid.
        latent_steps = max(
            0,
            int(math.ceil((nominal_frames - 1) / frame_step)),
        )
    else:
        latent_steps = max(
            0,
            int((nominal_frames - 1) // frame_step),
        )
    target_frames = max(
        minimum_frames,
        latent_steps * frame_step + 1,
    )
    return duration, target_fps, target_frames


def _resolve_ltx2_outpaint_reference_model(requested_model_type):
    """Select the best locally available model for official Outpaint.

    Lightricks' published two-stage graph uses the LTX-2.3 Dev transformer
    with the Distilled 1.1 LoRA at 0.5.  Keep an explicitly selected Dev
    model.  When the UI supplied a baked-Distilled model, prefer a compatible
    Dev checkpoint only when it is already installed; otherwise retain the
    requested model as a no-download compatibility fallback.
    """

    from urllib.parse import unquote, urlparse
    from shared.utils import files_locator as fl

    requested_def = wgp.get_model_def(requested_model_type) or {}
    requested_is_dev = bool(
        requested_def.get("architecture") == "ltx2_22B"
        and requested_def.get("ltx2_pipeline", "two_stage")
        != "distilled"
    )
    if requested_is_dev:
        return requested_model_type

    requested_lower = str(requested_model_type or "").lower()
    dev_candidates = (
        ("ltx2_22B_fp8", "ltx2_22B_1_1", "ltx2_22B")
        if "fp8" in requested_lower
        else ("ltx2_22B_1_1", "ltx2_22B_fp8", "ltx2_22B")
    )
    seen = set()
    for candidate in dev_candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        candidate_def = wgp.get_model_def(candidate) or {}
        if (
            candidate_def.get("architecture") != "ltx2_22B"
            or candidate_def.get("ltx2_pipeline", "two_stage")
            == "distilled"
        ):
            continue
        urls = wgp.get_model_recursive_prop(
            candidate,
            "URLs",
            return_list=True,
        )
        for url in urls or []:
            filename = os.path.basename(
                unquote(urlparse(str(url)).path)
            )
            if (
                filename
                and fl.locate_file(filename, error_if_none=False)
                is not None
            ):
                return candidate
    return requested_model_type


_OUTPAINT_PIXEL_BUDGETS = {
    "480p": 480 * 848,
    "540p": 540 * 960,
    "720p": 720 * 1280,
    "1080p": 1088 * 1920,
}

# A 257-frame 704x1280 two-stage Outpaint is the largest composition verified
# to fit a 24 GB card with Maestro's normal streaming profile.
# Keep larger canvases within the same approximate pixel-frame activation
# budget by shortening each diffusion window. This affects peak VRAM, not the
# total clip length; the existing sliding-window path covers the remainder.
_OUTPAINT_SINGLE_STAGE_REFERENCE_PIXELS = 704 * 1280
_OUTPAINT_SINGLE_STAGE_REFERENCE_FRAMES = 257


def _cap_outpaint_single_stage_window(
    requested_frames,
    target_width,
    target_height,
    window_min=17,
    window_max=501,
):
    requested_frames = max(1, int(requested_frames))
    target_pixels = max(1, int(target_width) * int(target_height))
    window_min = max(1, int(window_min))
    window_max = max(window_min, int(window_max))
    capped = max(window_min, min(window_max, requested_frames))
    if target_pixels <= _OUTPAINT_SINGLE_STAGE_REFERENCE_PIXELS:
        return capped

    pixel_frame_budget = (
        _OUTPAINT_SINGLE_STAGE_REFERENCE_PIXELS
        * _OUTPAINT_SINGLE_STAGE_REFERENCE_FRAMES
    )
    safe_frames = max(window_min, int(pixel_frame_budget / target_pixels))
    # LTX-2's causal temporal grid is 1 + 8k frames. Keeping the window on
    # that grid prevents downstream rounding from increasing it again.
    safe_frames = 1 + max(0, (safe_frames - 1) // 8) * 8
    safe_frames = max(window_min, min(window_max, safe_frames))
    return min(capped, safe_frames)


def _resolve_outpaint_canvas_geometry(
    src_w,
    src_h,
    pad_top,
    pad_bottom,
    pad_left,
    pad_right,
    resolution_preset="auto",
    alignment=64,
):
    """Resolve one grid-aligned Outpaint canvas and protected source rect.

    LTX-2's VAE works on a 64-pixel spatial grid. Previously the endpoint
    computed padding against an arbitrary target (for example 896x1593)
    and wgp silently floored that target later (to 896x1536). The model and
    source-overlay coordinates consequently described different canvases.

    Scale the complete composition uniformly, snap the final canvas once,
    then derive fractional padding percentages from that exact canvas.
    """
    src_w = max(1, int(src_w))
    src_h = max(1, int(src_h))
    pad_top = max(0, int(pad_top))
    pad_bottom = max(0, int(pad_bottom))
    pad_left = max(0, int(pad_left))
    pad_right = max(0, int(pad_right))
    alignment = max(1, int(alignment))

    composed_w = src_w + pad_left + pad_right
    composed_h = src_h + pad_top + pad_bottom
    target_w = float(composed_w)
    target_h = float(composed_h)
    preset = str(resolution_preset or "auto").lower()
    if preset in _OUTPAINT_PIXEL_BUDGETS:
        scale = (
            _OUTPAINT_PIXEL_BUDGETS[preset]
            / max(1.0, target_w * target_h)
        ) ** 0.5
        target_w *= scale
        target_h *= scale

    def _align(value):
        return max(
            alignment,
            int(math.floor((float(value) / alignment) + 0.5))
            * alignment,
        )

    final_w = _align(target_w)
    final_h = _align(target_h)

    # Uniformly fit the requested composition into the aligned canvas. Any
    # few grid-rounding pixels left over are centered around the composition,
    # preserving both the source aspect and the user's source placement.
    scale = min(
        final_w / max(1.0, float(composed_w)),
        final_h / max(1.0, float(composed_h)),
    )
    fitted_w = composed_w * scale
    fitted_h = composed_h * scale
    composition_x = (final_w - fitted_w) / 2.0
    composition_y = (final_h - fitted_h) / 2.0
    overlay_x = int(round(composition_x + pad_left * scale))
    overlay_y = int(round(composition_y + pad_top * scale))
    overlay_w = max(1, int(round(src_w * scale)))
    overlay_h = max(1, int(round(src_h * scale)))
    overlay_x = max(0, min(overlay_x, final_w - overlay_w))
    overlay_y = max(0, min(overlay_y, final_h - overlay_h))

    resolved_left = overlay_x
    resolved_top = overlay_y
    resolved_right = max(0, final_w - overlay_x - overlay_w)
    resolved_bottom = max(0, final_h - overlay_y - overlay_h)
    dims = (
        100.0 * resolved_top / overlay_h,
        100.0 * resolved_bottom / overlay_h,
        100.0 * resolved_left / overlay_w,
        100.0 * resolved_right / overlay_w,
    )

    # Re-resolve through the same helper inference uses. These coordinates
    # are retained for legacy overlay metadata and make any float rounding
    # difference observable instead of allowing two geometries to diverge.
    from shared.utils.utils import get_outpainting_frame_location

    (
        model_overlay_h,
        model_overlay_w,
        model_overlay_y,
        model_overlay_x,
    ) = get_outpainting_frame_location(
        final_h,
        final_w,
        list(dims),
        1,
    )
    return {
        "final_w": final_w,
        "final_h": final_h,
        "dims": dims,
        "overlay_w": int(model_overlay_w),
        "overlay_h": int(model_overlay_h),
        "overlay_x": int(model_overlay_x),
        "overlay_y": int(model_overlay_y),
        "requested_w": composed_w,
        "requested_h": composed_h,
    }


def _format_outpaint_percentage(value):
    text = f"{float(value):.8f}".rstrip("0").rstrip(".")
    return text or "0"


def _detect_outpaint_video_shot_ranges(
    source_video, target_frame_count, *, abort_callback=None,
    min_shot_frames=4, absolute_cut_threshold=0.12,
):
    """Stream a video into tiny thumbnails and return hard-cut ranges.

    Outpaint only needs camera-cut boundaries, not the full-resolution frame
    tensor that Recast keeps for SAM tracking. Retaining 64x36 RGB thumbnails
    bounds memory while deliberately reusing Recast's proven adaptive cut
    scoring. ``target_frame_count`` matches the exact timeline LTX will
    generate; any source tail outside its causal 8n+1 grid is ignored just as
    it is by the ordinary continuous Outpaint path.
    """
    import cv2
    import numpy as np

    frame_limit = max(1, int(target_frame_count))
    capture = cv2.VideoCapture(str(source_video))
    if not capture.isOpened():
        capture.release()
        raise ValueError(
            f"Outpaint could not open the source video: {source_video}"
        )

    thumbnails = []
    try:
        while len(thumbnails) < frame_limit:
            if abort_callback is not None:
                abort_callback()
            ok, frame = capture.read()
            if not ok or frame is None:
                break
            thumbnail = cv2.resize(
                frame,
                (64, 36),
                interpolation=cv2.INTER_AREA,
            )
            thumbnails.append(cv2.cvtColor(thumbnail, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()

    decoded_count = len(thumbnails)
    if decoded_count <= 0:
        raise ValueError("Outpaint source video contains no decodable frames.")
    if decoded_count < frame_limit:
        raise ValueError(
            "Outpaint source ended before its planned timeline "
            f"({decoded_count}/{frame_limit} frames)."
        )

    return _detect_recast_shot_ranges(
        np.stack(thumbnails),
        min_shot_frames=min_shot_frames,
        absolute_cut_threshold=absolute_cut_threshold,
    )


def _build_outpaint_shot_filter(
    start_frame, end_frame, pad_frames, fps,
):
    """Build an exact-frame, CFR filter for one lossless internal guide."""
    start = int(start_frame)
    end = int(end_frame)
    padding = max(0, int(pad_frames))
    rate = float(fps)
    if start < 0 or end <= start:
        raise ValueError("Outpaint shot frame bounds are invalid.")
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Outpaint shot FPS must be positive.")
    rate_text = f"{rate:.12g}"
    return (
        f"trim=start_frame={start}:end_frame={end},"
        f"setpts=N/({rate_text}*TB),"
        f"tpad=stop_mode=clone:stop={padding}"
    )


def _write_outpaint_shot_guide(
    source_video, output_path, *, start_frame, end_frame, pad_frames,
    fps, abort_callback=None,
):
    """Write one frame-exact, lossless H.264 guide without loading it whole."""
    import subprocess

    if abort_callback is not None:
        abort_callback()
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    filter_graph = _build_outpaint_shot_filter(
        start_frame,
        end_frame,
        pad_frames,
        fps,
    )
    ffmpeg_bin = os.environ.get("FFMPEG_BINARY", "ffmpeg")
    expected_frames = (
        int(end_frame) - int(start_frame) + max(0, int(pad_frames))
    )
    timeout = max(
        120,
        min(900, int(math.ceil(expected_frames / float(fps) * 10.0))),
    )
    command = [
        ffmpeg_bin,
        "-y",
        "-v",
        "error",
        "-i",
        str(source_video),
        "-map",
        "0:v:0",
        "-vf",
        filter_graph,
        "-an",
        "-map_metadata",
        "0",
        # The generated margins are color-sensitive. CRF 0 prevents an
        # intermediate guide encode from softening or shifting the protected
        # source before the IC-LoRA sees it.
        "-c:v",
        "libx264",
        "-crf",
        "0",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if abort_callback is not None:
        abort_callback()
    if completed.returncode != 0 or not os.path.isfile(output_path):
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        detail = (completed.stderr or "unknown ffmpeg error").strip()
        raise RuntimeError(
            "Could not prepare Outpaint camera shot: " + detail[:500]
        )

    actual_frames = _recast_video_frame_count(output_path)
    if actual_frames != expected_frames:
        try:
            os.remove(output_path)
        except OSError:
            pass
        raise RuntimeError(
            "Outpaint camera-shot guide changed timeline length "
            f"({actual_frames}/{expected_frames} frames)."
        )
    return output_path


def _build_outpaint_shot_manifest(
    base_params, source_video, shot_ranges, output_dir, job_id, *,
    target_frame_count, generation_fps, minimum_frames, latent_size,
    guide_writer=None, progress_callback=None, abort_callback=None,
):
    """Create exact-length official Outpaint tasks for every camera shot."""
    target_count = int(target_frame_count)
    if target_count <= 0:
        raise ValueError("Outpaint target timeline must contain frames.")
    ranges = [
        (int(bounds[0]), int(bounds[1]))
        for bounds in (shot_ranges or [])
    ]
    if not ranges:
        ranges = [(0, target_count)]
    cursor = 0
    for start, end in ranges:
        if start != cursor or end <= start or end > target_count:
            raise ValueError(
                "Outpaint camera shots must cover one contiguous timeline."
            )
        cursor = end
    if cursor != target_count:
        raise ValueError(
            "Outpaint camera shots do not cover the complete timeline."
        )

    writer = guide_writer or _write_outpaint_shot_guide
    os.makedirs(output_dir, exist_ok=True)
    tasks = []
    plans = []
    total_shots = len(ranges)
    for shot_index, (start, end) in enumerate(ranges):
        if abort_callback is not None:
            abort_callback()
        if progress_callback is not None:
            progress_callback(shot_index, total_shots)
        exact_frames = end - start
        generated_frames, trim_tail = _quantize_recast_shot_frame_count(
            exact_frames,
            minimum_frames,
            latent_size,
        )
        guide_path = os.path.join(
            output_dir,
            f"outpaint_{job_id}_shot_{shot_index + 1}_guide.mp4",
        )
        writer(
            source_video,
            guide_path,
            start_frame=start,
            end_frame=end,
            pad_frames=trim_tail,
            fps=generation_fps,
            abort_callback=abort_callback,
        )
        tasks.append({
            "shot_index": shot_index,
            "params": {
                "video_guide": guide_path,
                "video_length": generated_frames,
                "trim_tail_frames": trim_tail,
                "video_prompt_type": "VG",
                "image_prompt_type": "",
                "force_fps": "control",
                # Internal shots never replace their audio or perform the
                # continuous-path smear trim. One source track is attached
                # only after exact-frame assembly.
                "audio_prompt_type": "",
                "audio_guide": None,
                "audio_source": None,
                "_outpaint_preserve_audio": False,
                "_outpaint_source_video": None,
                "_outpaint_lock_source_pixels": False,
                "_outpaint_trim_smear": False,
                "output_filename": (
                    f"outpaint_{job_id}_shot_{shot_index + 1}.mp4"
                ),
            },
        })
        plans.append({
            "shot_index": shot_index,
            "start_frame": start,
            "end_frame": end,
            "frame_count": exact_frames,
            "generated_frame_count": generated_frames,
            "trim_tail_frames": trim_tail,
            "mode": "outpaint",
        })

    return {
        "tasks": tasks,
        "shots": plans,
        "published_shots": [dict(plan) for plan in plans],
        "frame_count": target_count,
        "fps": float(generation_fps),
    }


def _prepare_and_run_outpaint(job_id):
    """Detect camera cuts, prepare private shot tasks, then generate."""
    import secrets
    import shutil
    import tempfile

    job = _jobs[job_id]
    abort_state = {"abort": False}
    shot_temp_dir = None
    shot_final_out_dir = None
    has_shot_manifest = False

    try:
        # Match Recast/Repaint's two-phase lifecycle. Preparation is short and
        # CPU-bound, but taking the slot preserves submission order and avoids
        # stacking ffmpeg decoding on top of another active generation.
        with _coordinated_generation_slot(
            job, description="HocusPocus Lab GPU preparation · outpaint",
        ) as acquired:
            if not acquired:
                return
            if not try_start(
                job,
                phase="Detecting camera shots",
                message="Detecting camera cuts for Outpaint...",
            ):
                return
            if not register_abort_state(
                job,
                job_id,
                _active_gen_states,
                abort_state,
            ):
                return

            def _abort_preparation():
                if is_cancel_requested(job):
                    raise InterruptedError(
                        "Outpaint camera-shot preparation was cancelled",
                    )

            params = job.get("params") or {}
            source_video = params.get("video_guide")
            target_frame_count = int(params.get("video_length") or 0)
            generation_fps = float(
                params.get("_outpaint_generation_fps") or 0
            )
            if not source_video or not os.path.isfile(source_video):
                raise ValueError("Outpaint source video is unavailable.")
            if target_frame_count <= 0 or generation_fps <= 0:
                raise ValueError("Outpaint timeline metadata is invalid.")

            shot_ranges = _detect_outpaint_video_shot_ranges(
                source_video,
                target_frame_count,
                abort_callback=_abort_preparation,
            )
            params["edit_outpaint_detected_shot_ranges"] = [
                [int(start), int(end)]
                for start, end in shot_ranges
            ]
            if len(shot_ranges) <= 1:
                print(
                    "[Outpaint] Detected one continuous camera shot; "
                    "using the proven continuous pipeline."
                )
            else:
                cut_times = ", ".join(
                    f"{start / generation_fps:.2f}s"
                    for start, _end in shot_ranges[1:]
                )
                print(
                    f"[Outpaint] Detected {len(shot_ranges)} camera shots; "
                    f"generating each independently after cuts at "
                    f"{cut_times}."
                )
                if not update_job(
                    job,
                    phase="Preparing camera shots",
                    message=(
                        f"Preparing {len(shot_ranges)} Outpaint shots..."
                    ),
                ):
                    raise InterruptedError(
                        "Outpaint camera-shot preparation was cancelled",
                    )

                try:
                    resolved_seed = int(params.get("seed", -1))
                except (TypeError, ValueError):
                    resolved_seed = -1
                if resolved_seed < 0:
                    resolved_seed = secrets.randbelow(1_000_000_000)
                params["seed"] = resolved_seed

                model_type = params.get("model_type")
                try:
                    minimum_frames, _frame_step, latent_size = (
                        wgp.get_model_min_frames_and_step(model_type)
                    )
                except Exception:
                    minimum_frames, latent_size = 17, 8

                shot_temp_dir = tempfile.mkdtemp(
                    prefix="maestro-outpaint-shots-",
                )

                def _preparation_progress(index, total):
                    if not update_job(
                        job,
                        phase="Preparing camera shots",
                        message=(
                            f"Preparing Outpaint shot {index + 1}/{total}..."
                        ),
                    ):
                        raise InterruptedError(
                            "Outpaint camera-shot preparation was cancelled",
                        )

                try:
                    shot_manifest = _build_outpaint_shot_manifest(
                        params,
                        source_video,
                        shot_ranges,
                        shot_temp_dir,
                        job_id,
                        target_frame_count=target_frame_count,
                        generation_fps=generation_fps,
                        minimum_frames=minimum_frames,
                        latent_size=latent_size,
                        progress_callback=_preparation_progress,
                        abort_callback=_abort_preparation,
                    )
                except Exception:
                    shutil.rmtree(shot_temp_dir, ignore_errors=True)
                    shot_temp_dir = None
                    raise

                shot_final_out_dir = job.get("out_dir") or _workspace_dir(
                    job.get("workspace"),
                )
                params.update({
                    "_defer_output_publication": True,
                    "_outpaint_shot_manifest": shot_manifest["tasks"],
                    "_outpaint_shot_temp_dir": shot_temp_dir,
                    "_outpaint_final_out_dir": shot_final_out_dir,
                    "_outpaint_shot_source_video": source_video,
                    "_outpaint_shot_bundle": {
                        "shots": shot_manifest["shots"],
                        "published_shots": shot_manifest[
                            "published_shots"
                        ],
                        "frame_count": shot_manifest["frame_count"],
                        "fps": shot_manifest["fps"],
                        "resolved_seed": resolved_seed,
                        "preserve_source_audio": bool(
                            params.get("_outpaint_preserve_audio", True)
                        ),
                    },
                    "edit_outpaint_shot_aware": True,
                    "edit_outpaint_shot_plan": shot_manifest[
                        "published_shots"
                    ],
                })
                job["out_dir"] = shot_temp_dir
                has_shot_manifest = True
                print(
                    "[Outpaint] Shot-aware plan prepared "
                    f"{len(shot_manifest['shots'])} camera shots, "
                    f"{shot_manifest['frame_count']} exact output frames "
                    f"at {shot_manifest['fps']:.6g}fps."
                )
    except InterruptedError:
        return
    except Exception as error:
        traceback.print_exc()
        if shot_temp_dir and os.path.isdir(shot_temp_dir):
            shutil.rmtree(shot_temp_dir, ignore_errors=True)
        if shot_final_out_dir:
            job["out_dir"] = shot_final_out_dir
        finish_job(
            job,
            "failed",
            error=f"Outpaint shot preparation failed: {error}",
            message="Outpaint shot preparation failed",
        )
        return
    finally:
        unregister_abort_state(
            job_id,
            _active_gen_states,
            abort_state,
        )

    if not try_requeue(job, message="Queued (outpaint)", phase=""):
        if shot_temp_dir and os.path.isdir(shot_temp_dir):
            shutil.rmtree(shot_temp_dir, ignore_errors=True)
        if shot_final_out_dir:
            job["out_dir"] = shot_final_out_dir
        return
    if has_shot_manifest:
        _run_outpaint_shot_generation(job_id)
    else:
        _run_generation(job_id)


@api.post("/api/v1/outpaint")
async def outpaint_endpoint(request: Request):
    """Submit an outpaint job: extend video/image canvas using IC-LoRA.

    Body: {
        video_path: str, prompt: str, model_type: str,
        pad_top?: int, pad_bottom?: int, pad_left?: int, pad_right?: int,
        gamma_correct?: bool, seed?: int,
        num_inference_steps?: int, guidance_scale?: float,
        negative_prompt?: str,
        activated_loras?: list, loras_multipliers?: str, workspace?: str,
    }
    """
    body = await request.json()

    video_path = body.get("video_path")
    if not video_path:
        raise HTTPException(status_code=400, detail="video_path is required")
    if not os.path.isabs(video_path):
        workspace_dir = _workspace_dir(body.get("workspace"))
        candidate = os.path.join(workspace_dir, video_path)
        if os.path.isfile(candidate):
            video_path = candidate
    # Also check uploads folder
    if not os.path.isfile(video_path):
        uploads_candidate = os.path.join(os.getcwd(), "uploads", os.path.basename(video_path))
        if os.path.isfile(uploads_candidate):
            video_path = uploads_candidate
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Source file not found: {video_path}")

    model_type = body.get("model_type")
    if not model_type:
        raise HTTPException(status_code=400, detail="model_type is required")
    requested_model_type = model_type

    pad_top = int(body.get("pad_top", 0))
    pad_bottom = int(body.get("pad_bottom", 0))
    pad_left = int(body.get("pad_left", 0))
    pad_right = int(body.get("pad_right", 0))
    total_pad = pad_top + pad_bottom + pad_left + pad_right
    if total_pad <= 0:
        raise HTTPException(status_code=400, detail="At least one padding direction must be > 0")

    # Determine if source is video or image; get source dimensions
    ext = os.path.splitext(video_path)[1].lower()
    is_video = ext in (".mp4", ".mkv", ".avi", ".mov", ".webm")

    from PIL import Image as PILImage

    # Optional film-strip trim: if the UI sent start_time/end_time, ffmpeg-cut
    # the source to that range before reading frames. The trimmed clip becomes
    # the canonical video_path for the rest of the request. Falls back to
    # untrimmed source if ffmpeg fails or range is invalid.
    if is_video:
        trim_start = body.get("start_time")
        trim_end = body.get("end_time")
        if trim_start is not None and trim_end is not None:
            try:
                trim_start_f = float(trim_start)
                trim_end_f = float(trim_end)
                if trim_end_f - trim_start_f > 0.05 and trim_start_f >= 0:
                    import subprocess
                    import tempfile
                    trim_dir = os.path.join(os.getcwd(), "uploads")
                    os.makedirs(trim_dir, exist_ok=True)
                    trim_id = uuid.uuid4().hex[:8]
                    trimmed_path = os.path.join(trim_dir, f"outpaint_trim_{trim_id}.mp4")
                    # -ss + -to with re-encode for frame-accurate cut at the
                    # requested sub-second boundaries (stream-copy seeks to
                    # the nearest keyframe and would round our trim).
                    cmd = [
                        "ffmpeg", "-y", "-i", video_path,
                        "-ss", f"{trim_start_f:.3f}",
                        "-to", f"{trim_end_f:.3f}",
                        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                        "-c:a", "aac", "-b:a", "192k",
                        trimmed_path,
                    ]
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if proc.returncode == 0 and os.path.isfile(trimmed_path):
                        print(f"[Outpaint] Trimmed source to [{trim_start_f:.2f}s, {trim_end_f:.2f}s] -> {os.path.basename(trimmed_path)}")
                        video_path = trimmed_path
                    else:
                        print(f"[Outpaint] Trim failed (continuing with full clip): {proc.stderr[:200]}")
            except (TypeError, ValueError) as e:
                print(f"[Outpaint] Invalid trim params: {e}")

    if is_video:
        import decord
        vr = decord.VideoReader(video_path)
        source_total_frames = len(vr)
        source_fps = float(vr.get_avg_fps() or 0)
        src_h, src_w = vr[0].shape[:2]
        del vr
        total_frames = source_total_frames
    else:
        img = PILImage.open(video_path).convert("RGB")
        src_w, src_h = img.size
        source_total_frames = 1
        source_fps = 0.0
        total_frames = 1
        del img

    # Resolve the output grid and protected source rectangle together. The
    # fractional percentages survive through wgp so inference and later
    # metadata describe the same exact canvas.
    resolution_preset = str(body.get("resolution_preset") or "auto").lower()
    base_model_type = wgp.get_base_model_type(model_type)
    outpaint_alignment = 64 if base_model_type == "ltx2_22B" else 32
    geometry = _resolve_outpaint_canvas_geometry(
        src_w,
        src_h,
        pad_top,
        pad_bottom,
        pad_left,
        pad_right,
        resolution_preset,
        outpaint_alignment,
    )
    final_w = geometry["final_w"]
    final_h = geometry["final_h"]
    overlay_w = geometry["overlay_w"]
    overlay_h = geometry["overlay_h"]
    overlay_x = geometry["overlay_x"]
    overlay_y = geometry["overlay_y"]
    video_guide_outpainting = " ".join(
        _format_outpaint_percentage(value)
        for value in geometry["dims"]
    )

    # Auto stays near native dimensions; quality presets apply a pixel budget
    # before both axes are snapped to the model grid.
    if (
        final_w != geometry["requested_w"]
        or final_h != geometry["requested_h"]
    ):
        print(
            f"[Outpaint] Grid-aligned canvas: "
            f"{geometry['requested_w']}x{geometry['requested_h']} -> "
            f"{final_w}x{final_h}"
        )
    print(
        f"[Outpaint] Source: {src_w}x{src_h}, "
        f"Target: {final_w}x{final_h}, "
        f"Protected rect: {overlay_w}x{overlay_h}"
        f"+{overlay_x}+{overlay_y}, "
        f"Dims (%): {video_guide_outpainting}"
    )

    requested_mask_preservation = bool(
        body.get("mask_preserving_outpaint", True)
    )
    mask_preserving_outpaint = bool(
        requested_mask_preservation
        and is_video
        and base_model_type == "ltx2_22B"
    )
    if requested_mask_preservation and not mask_preserving_outpaint:
        print(
            "[Outpaint] Mask-preserving workflow is currently available "
            "for LTX-2.3 22B video outpainting; using the legacy path."
        )
    official_outpaint = bool(mask_preserving_outpaint)
    if official_outpaint:
        model_type = _resolve_ltx2_outpaint_reference_model(model_type)
        if model_type != requested_model_type:
            print(
                "[Outpaint] Official reference model stack: "
                f"{requested_model_type} -> {model_type} "
                "(installed Dev checkpoint + Distilled 1.1 LoRA at 0.5 "
                "+ In/Outpainting IC-LoRA)."
            )
        else:
            selected_def = wgp.get_model_def(model_type) or {}
            if selected_def.get("ltx2_pipeline", "two_stage") == "distilled":
                print(
                    "[Outpaint] No installed Dev checkpoint was found; "
                    "using the selected baked-Distilled model as a "
                    "compatibility fallback."
                )
        base_model_type = wgp.get_base_model_type(model_type)
        print(
            "[Outpaint] Using Lightricks' official two-stage workflow "
            "(#66FF00 mask guide, full reference attention, decoded-pixel "
            "handoff, and Laplacian source restoration)."
        )

    # The official mask-conditioned path requires full control strength. The
    # legacy rollback path keeps accepting the old conditioning control.
    if mask_preserving_outpaint:
        source_preservation = 1.0
    else:
        source_preservation = float(
            body.get("source_preservation", 1.0)
        )
        source_preservation = max(
            0.3,
            min(1.0, source_preservation),
        )

    # The official in/outpainting LoRA is fixed at its trained strength.
    # Legacy mode retains the old multiplier solely for rollback testing.
    if mask_preserving_outpaint:
        outpaint_lora_strength = 1.0
    else:
        outpaint_lora_strength = float(
            body.get("outpaint_lora_strength", 1.0)
        )
        outpaint_lora_strength = max(
            0.0,
            min(2.0, outpaint_lora_strength),
        )

    # Preserve source audio: outpainting only changes spatial canvas — the
    # temporal content (and therefore the audio) is identical to the source.
    # LTX-2 distilled, however, always synthesizes a fresh audio track via its
    # audio decoder, which replaces the source audio with unrelated synthetic
    # audio. We post-mux the original source audio back onto the output after
    # generation completes (see _outpaint_audio_postprocess in _run_generation).
    # Default True since the alternative (LTX-generated audio for an outpaint)
    # is essentially never what the user wants.
    preserve_source_audio = bool(body.get("preserve_source_audio", True)) and is_video

    # Lock source pixels: composite the original source clip back into the
    # source-area rectangle of the output. Default OFF — empirical testing
    # showed (a) the IC-LoRA's regenerated source area actually preserves
    # lip detail well, and (b) hard-overlaying source pixels creates a
    # visible rectangular seam because the model's outpainted region has
    # slightly different color/tone than raw source. Kept as opt-in for
    # power users who explicitly want pixel-perfect source area.
    lock_source_pixels = bool(
        body.get("lock_source_pixels", False)
    ) and is_video and not mask_preserving_outpaint

    # Trim sliding-window smear: at the boundary between window 1 and
    # window 2, the model's prefix-conditioning produces ~reuse_frames
    # frames of "stutter" content (showing the same source content as
    # window 1's last frame). Empirically this introduces a constant
    # ~9-frame lag for the rest of the output (windows 2+ all carry the
    # same offset; lag does NOT accumulate per boundary). Cutting 9
    # frames at the window 1→2 boundary realigns the output with audio
    # for the entire remaining duration. Default ON for multi-window
    # video outpaint since this is what the user actually needs to fix
    # lip sync. Single-window outpaint has no boundary so no-op.
    trim_window_smear = bool(body.get("trim_window_smear", True)) and is_video

    # Sliding window for long clips: outpaint VRAM scales with window frames ×
    # canvas pixels. Single-shot generation works for short clips at modest
    # resolutions but OOMs on longer clips (e.g. 57s @ 720p needs ~6 windows).
    # Use the model's recommended window default unless the caller overrides.
    # LTX-2 (per ltx2_handler.py): window_default=241 (~10s @ 24fps),
    # overlap_default=9, discard_last_frames=8 (LTX has 8 distorted tail
    # frames per window — discarding lets the next window's overlap region
    # replace them so seams stay clean).
    try:
        _model_def = wgp.get_model_def(model_type) or {}
    except Exception:
        _model_def = {}
    try:
        _model_defaults = wgp.get_default_settings(model_type) or {}
    except Exception:
        _model_defaults = {}
    if is_video:
        (
            source_duration,
            generation_fps,
            total_frames,
        ) = _resolve_outpaint_video_timing(
            source_total_frames,
            source_fps,
            _model_def,
        )
        print(
            "[Outpaint] Timing: "
            f"{source_total_frames} frames at {source_fps:.3f} fps "
            f"({source_duration:.3f}s) -> {total_frames} frames at "
            f"{generation_fps:g} fps"
        )
    if official_outpaint:
        # The official graph distills the Dev transformer to the published
        # eight-step schedule. Do not let stale saved settings alter it.
        inference_steps = 8
        guidance_scale = 1.0
        print(
            "[Outpaint] Reference sampling: 8-step masked first pass + "
            "2-step decoded-pixel refinement, CFG 1."
        )
    else:
        try:
            inference_steps, guidance_scale = _resolve_outpaint_sampling(
                body,
                wgp.get_base_model_type(model_type),
                _model_def,
                _model_defaults,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from error
    _sw_defaults = _model_def.get("sliding_window_defaults", {})
    sliding_window_size = int(body.get("sliding_window_size", _sw_defaults.get("window_default", 241)))
    sliding_window_overlap = int(body.get("sliding_window_overlap", _sw_defaults.get("overlap_default", 9)))
    sliding_window_discard_last_frames = int(body.get(
        "sliding_window_discard_last_frames",
        _sw_defaults.get("discard_last_frames", 8),
    ))
    # Clamp window to model's reported max (defaults to 501 for LTX-2).
    _window_max = int(_sw_defaults.get("window_max", 501))
    _window_min = int(_sw_defaults.get("window_min", 17))
    sliding_window_size = max(_window_min, min(_window_max, sliding_window_size))
    if official_outpaint and is_video:
        requested_window_size = sliding_window_size
        sliding_window_size = _cap_outpaint_single_stage_window(
            sliding_window_size,
            final_w,
            final_h,
            _window_min,
            _window_max,
        )
        if sliding_window_size < requested_window_size:
            print(
                "[Outpaint] Two-stage Outpaint VRAM window cap: "
                f"{requested_window_size} -> {sliding_window_size} frames "
                f"for {final_w}x{final_h}. The complete clip will use "
                "additional sliding windows."
            )
    # Outpaint system LoRAs are selected internally. Remove a persisted manual
    # selection of either system file so rerunning old settings cannot load
    # both the legacy and official variants at once.
    activated_loras = list(body.get("activated_loras") or [])
    multiplier_tokens = [
        token.split(";", 1)[0]
        for token in str(body.get("loras_multipliers") or "").split()
    ]
    system_outpaint_loras = {
        "ltx-2.3-22b-ic-lora-outpaint.safetensors",
        "ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors",
    }
    filtered_loras = []
    filtered_multipliers = []
    for index, lora in enumerate(activated_loras):
        if os.path.basename(str(lora)).lower() in system_outpaint_loras:
            print(
                "[Outpaint] Ignoring manually selected system LoRA "
                f"{os.path.basename(str(lora))}; the workflow manages it."
            )
            continue
        if official_outpaint:
            print(
                "[Outpaint] Ignoring user LoRA "
                f"{os.path.basename(str(lora))}; the reference workflow "
                "manages its Distilled and IC-LoRA adapters internally."
            )
            continue
        filtered_loras.append(lora)
        filtered_multipliers.append(
            multiplier_tokens[index]
            if index < len(multiplier_tokens)
            else "1"
        )

    submitted_outpaint_prompt = str(body.get("prompt") or "").strip()
    if official_outpaint:
        # Lightricks recommends an empty/minimal prompt, or a description of
        # only the missing region. Appending a whole-scene instruction makes
        # the model redraw or duplicate subjects at the source boundary.
        outpaint_prompt = (
            "."
            if not submitted_outpaint_prompt
            or submitted_outpaint_prompt.lower() == "extend the scene naturally"
            else submitted_outpaint_prompt
        )
    else:
        raw_outpaint_prompt = submitted_outpaint_prompt
        if not raw_outpaint_prompt or raw_outpaint_prompt.lower() == "extend the scene naturally":
            raw_outpaint_prompt = (
                "the scene continues naturally beyond the original frame, "
                "consistent style and lighting"
            )
        outpaint_prompt = (
            f"{raw_outpaint_prompt}; seamlessly extend the scene into the "
            "empty margins, matching the existing content."
        )

    gen_params = {
        "prompt": outpaint_prompt,
        "model_type": model_type,
        # The published Outpaint app deliberately leaves this empty. A broad
        # generic negative prompt can shift the generated margins away from
        # the appearance of the protected source.
        "negative_prompt": (
            ""
            if official_outpaint
            else str(body.get("negative_prompt") or "")
        ),
        "seed": body.get("seed", -1),
        "guidance_scale": guidance_scale,
        "num_inference_steps": inference_steps,
        "video_length": max(total_frames, 17) if is_video else 1,
        # Keep the generated timeline on the source video's native cadence.
        # Forcing the reference demo's 24 fps collapsed a known-good 305-frame
        # / two-window clip into one 249-frame window and caused the generated
        # margins to diverge visibly from the protected source rectangle.
        "force_fps": "control" if is_video else "auto",
        "resolution": f"{final_w}x{final_h}",
        "generation_mode": "video" if is_video else "image",
        # Tag for the gallery's Edits filter + Load Settings restore path.
        "edit_sub_mode": "outpaint",
        # V = source video guide (the ORIGINAL, unpadded source — the pipeline
        # places it into the padded canvas internally); G = masked inpaint mode
        # (required for outpaint IC-LoRA gamma-round-trip to trigger).
        "video_prompt_type": "VG" if is_video else "G",
        "video_guide": video_path if is_video else None,
        "image_start": video_path if not is_video else None,
        "video_guide_outpainting": video_guide_outpainting,
        "input_video_strength": body.get("input_video_strength", 1.0),
        "denoising_strength": source_preservation,
        # Read by ltx2.get_loras_transformer — NOT a standard wgp param, so it
        # must survive the signature filter. We pass it through raw_params and
        # ltx2.py picks it up via kwargs.get.
        "outpaint_lora_strength": outpaint_lora_strength,
        "outpaint_mask_preserve": mask_preserving_outpaint,
        "outpaint_official_stack": official_outpaint,
        # Match the current Lightricks graph as one coherent pipeline. The
        # implementation paints the exact marker immediately before VAE
        # encoding, keeps full reference attention, blends pass one back to
        # source pixels, resizes with Lanczos, and restores source again after
        # pass two. The marker-safe source pyramid prevents #66FF00 leakage.
        "single_stage_pipeline": False,
        "outpaint_full_resolution_refine": official_outpaint,
        "activated_loras": filtered_loras,
        "loras_multipliers": " ".join(filtered_multipliers),
        # Sliding window engages automatically when total_frames > sliding_window_size
        # (wgp.py:6739). For images / very short clips, force window > clip so the
        # pipeline runs single-shot (cheaper than multi-window for tiny inputs).
        "sliding_window_size": sliding_window_size if (is_video and total_frames > sliding_window_size) else (max(total_frames, 17) + 10 if is_video else 17),
        "sliding_window_overlap": sliding_window_overlap,
        "sliding_window_discard_last_frames": sliding_window_discard_last_frames,
        "settings_version": 2.53,
        # Underscore-prefixed flags survive job["params"] but get stripped by
        # the wgp.generate_video signature filter (line ~5119), so they don't
        # reach the inference pipeline. _run_generation reads them after the
        # job completes to drive post-processing (audio mux + source overlay).
        "_outpaint_preserve_audio": preserve_source_audio,
        "_outpaint_source_video": video_path if (preserve_source_audio or lock_source_pixels) else None,
        "_outpaint_lock_source_pixels": lock_source_pixels,
        "_outpaint_overlay_w": overlay_w,
        "_outpaint_overlay_h": overlay_h,
        "_outpaint_overlay_x": overlay_x,
        "_outpaint_overlay_y": overlay_y,
        "_outpaint_canvas_w": final_w,
        "_outpaint_canvas_h": final_h,
        # Private preparation metadata for automatic camera-shot dispatch.
        # It is stripped from the final sidecar after assembly.
        "_outpaint_generation_fps": generation_fps if is_video else None,
        "_outpaint_source_frame_count": (
            source_total_frames if is_video else None
        ),
        # Smear trim params: only meaningful when total_frames > sliding_window_size
        # (multi-window mode). Boundary 1 is at output position
        # sliding_window_size - sliding_window_discard_last_frames.
        # Smear count = sliding_window_overlap (reuse_frames) — the model
        # produces this many "duplicate" frames at the boundary that we trim.
        "_outpaint_trim_smear": trim_window_smear and is_video and total_frames > sliding_window_size,
        "_outpaint_smear_boundary_frame": sliding_window_size - sliding_window_discard_last_frames,
        "_outpaint_smear_count": sliding_window_overlap,
        # Restore-able state for the gallery's Load Settings flow. The
        # frontend recomputes canvas + video box from these on reload so
        # the user sees the same composition that produced the output.
        "edit_video_path": video_path,
        "outpaint_pad_top": pad_top,
        "outpaint_pad_bottom": pad_bottom,
        "outpaint_pad_left": pad_left,
        "outpaint_pad_right": pad_right,
        "outpaint_aspect": body.get("outpaint_aspect"),
        "outpaint_resolution_preset": resolution_preset,
        "outpaint_source_preservation": source_preservation,
        "outpaint_lora_strength_ui": outpaint_lora_strength,
        "outpaint_mask_preserving": mask_preserving_outpaint,
        "outpaint_requested_model_type": requested_model_type,
        "edit_outpaint_raw_prompt": submitted_outpaint_prompt,
        "outpaint_trim_start": body.get("start_time"),
        "outpaint_trim_end": body.get("end_time"),
    }
    # Strip None values so they don't override defaults downstream
    gen_params = {k: v for k, v in gen_params.items() if v is not None}

    workspace = body.get("workspace") or _get_active_workspace()
    job_out_dir = _workspace_dir(workspace)

    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
        "phase": "", "message": "Queued (outpaint)", "created_at": time.time(),
        "params": gen_params, "output_files": [], "error": None,
        "workspace": workspace, "out_dir": job_out_dir,
    }
    _register_manual_generation_job(job)

    worker = (
        _prepare_and_run_outpaint
        if official_outpaint and is_video and not execution_mode.policy().simulated
        else _run_generation
    )
    thread = threading.Thread(target=worker, args=(job_id,), daemon=False)
    thread.start()

    # Estimate window count for the response so the UI can surface it.
    # Mirrors wgp.compute_sliding_window_no for the multi-window case.
    if is_video and total_frames > sliding_window_size:
        _stride = max(1, sliding_window_size - sliding_window_discard_last_frames - sliding_window_overlap)
        _left = max(0, total_frames - sliding_window_size + sliding_window_discard_last_frames)
        _window_count = 1 + (_left + _stride - 1) // _stride
    else:
        _window_count = 1

    return {
        "job_id": job_id,
        "status": "queued",
        "source_size": f"{src_w}x{src_h}",
        "output_size": f"{final_w}x{final_h}",
        "outpainting_dims": video_guide_outpainting,
        "total_frames": total_frames,
        "sliding_window_size": sliding_window_size,
        "sliding_window_count": _window_count,
        **_generation_job_acceptance(job),
    }


@api.post("/api/v1/blend")
async def blend_endpoint(request: Request):
    """Blend two clips with an AI-generated transition (Sora-1 style overlap).

    For `overlap` mode: the last `overlap_sec` of Clip A blends with the
    first `overlap_sec` of Clip B during a shared window. Total output
    duration = len(A) + len(B) - overlap_sec.

    Pipeline: sparse keyframe injection — A's last N frames anchored at
    blend positions 1..N, B's first N frames anchored at blend positions
    (transition-N+1)..transition. Middle is free for the model to invent.
    Uses `video_prompt_type="FI"` (image_refs + frames_positions), the same
    mechanism Continue/Extend and the Director/music-video flows use for
    motion-preserving keyframe anchoring.

    Body: {
        clip_a_path: str, clip_b_path: str,
        prompt?: str — describe the *transition itself*, not just "smooth blend".
        model_type: str,
        blend_mode?: 'insert'|'overlap', overlap_sec?: float (default 3),
        motion_prefix_sec?: float (default 1.0) — seconds of A's overlap-zone
            start used as `video_source`, switching the pipeline from SE to
            VE mode. Gives the model real motion history to extrapolate so
            rotation/pan direction continues from A. Set to 0 for pure SE
            (single still-frame anchor). Capped at 80% of overlap_sec.
        motion_suffix_sec?: float (default 1.0) — symmetric counterpart to
            motion_prefix_sec. Feeds B's overlap-zone end as `video_end`
            via a keyframe-injection path in ltx2.py, giving the model B's
            actual motion trajectory leading into the landing frame. Without
            this, the joggers (for ex.) tend to "slow-mo" into the anchor
            then hard-cut to real-speed B_post. Capped at 80% of overlap_sec.
        anchor_frames?: int (default 0) — optional weak keyframes near the
            edges for extra motion-context. Usually leave 0 with VE mode.
        injection_strength?: float (default 0.4) — strength for those.
        num_inference_steps?: int, guidance_scale?: float, negative_prompt?: str,
        seed?: int, activated_loras?: list, loras_multipliers?: str,
        workspace?: str,
        base_params?: dict — UI passes state.params here so the blend
            inherits progressive_pipeline, stage2_steps, etc. Blend-specific
            fields (image_start/end, resolution, video_length, ...) override.
    }
    """
    body = await request.json()

    clip_a_path = body.get("clip_a_path")
    clip_b_path = body.get("clip_b_path")
    if not clip_a_path or not clip_b_path:
        raise HTTPException(status_code=400, detail="Both clip_a_path and clip_b_path are required")

    # Resolve paths (may be upload paths)
    for check_dir in [os.path.join(os.getcwd(), "uploads"), _workspace_dir(body.get("workspace"))]:
        if not os.path.isfile(clip_a_path):
            candidate = os.path.join(check_dir, os.path.basename(clip_a_path))
            if os.path.isfile(candidate):
                clip_a_path = candidate
        if not os.path.isfile(clip_b_path):
            candidate = os.path.join(check_dir, os.path.basename(clip_b_path))
            if os.path.isfile(candidate):
                clip_b_path = candidate

    if not os.path.isfile(clip_a_path):
        raise HTTPException(status_code=400, detail=f"Clip A not found: {clip_a_path}")
    if not os.path.isfile(clip_b_path):
        raise HTTPException(status_code=400, detail=f"Clip B not found: {clip_b_path}")

    model_type = body.get("model_type")
    if not model_type:
        raise HTTPException(status_code=400, detail="model_type is required")

    blend_mode = body.get("blend_mode", "overlap")
    overlap_sec = float(body.get("overlap_sec", 3))

    import tempfile
    import math
    import decord
    import numpy as np
    from PIL import Image as PILImage

    temp_dir = tempfile.mkdtemp(prefix="blend_")

    try:
        # ── Probe both clips ─────────────────────────────────────────────
        def _probe(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in (".mp4", ".mkv", ".avi", ".mov", ".webm"):
                vr = decord.VideoReader(path)
                fps = float(vr.get_avg_fps()) or 24.0
                h, w = vr[0].shape[:2]
                return {"is_video": True, "fps": fps, "frames": len(vr), "h": h, "w": w, "reader": vr}
            img = PILImage.open(path).convert("RGB")
            return {"is_video": False, "fps": 24.0, "frames": 1, "h": img.size[1], "w": img.size[0], "image": img}

        info_a = _probe(clip_a_path)
        info_b = _probe(clip_b_path)

        # ── Target geometry (A's native, aligned to 32 for LTX) ──────────
        fps = info_a["fps"]
        # LTX-2 frames schedule: must be >= 17 and (n - 17) % 8 == 0
        raw_frames = max(17, int(round(overlap_sec * fps)))
        transition_frames = 17 + 8 * math.ceil((raw_frames - 17) / 8) if raw_frames > 17 else 17
        # Effective overlap after rounding (for frame-accurate trim/concat)
        overlap_sec_eff = transition_frames / fps

        # Snap resolution to LTX's 32-px alignment
        src_w = (info_a["w"] // 32) * 32
        src_h = (info_a["h"] // 32) * 32
        if src_w <= 0 or src_h <= 0:
            raise HTTPException(status_code=400, detail=f"Clip A resolution too small: {info_a['w']}x{info_a['h']}")

        def _resample_frames(raw_list, target_len, target_w, target_h):
            """Resize + resample a list of RGB np arrays to exactly target_len frames."""
            if not raw_list:
                return [np.zeros((target_h, target_w, 3), dtype=np.uint8)] * target_len
            resized = []
            for f in raw_list:
                if f.shape[0] != target_h or f.shape[1] != target_w:
                    f = np.array(PILImage.fromarray(f).resize((target_w, target_h), PILImage.LANCZOS))
                resized.append(f)
            if len(resized) == target_len:
                return resized
            idx = np.linspace(0, len(resized) - 1, target_len).astype(int)
            return [resized[i] for i in idx]

        # ── Extract A's tail (last overlap_sec_eff seconds) ──────────────
        if info_a["is_video"]:
            src_frames_a = max(1, int(round(overlap_sec_eff * info_a["fps"])))
            start_idx_a = max(0, info_a["frames"] - src_frames_a)
            raw_a = [info_a["reader"][i].asnumpy() for i in range(start_idx_a, info_a["frames"])]
            del info_a["reader"]
        else:
            raw_a = [np.array(info_a["image"])]

        # ── Extract B's head (first overlap_sec_eff seconds) ─────────────
        if info_b["is_video"]:
            src_frames_b = max(1, int(round(overlap_sec_eff * info_b["fps"])))
            end_idx_b = min(src_frames_b, info_b["frames"])
            raw_b = [info_b["reader"][i].asnumpy() for i in range(end_idx_b)]
            del info_b["reader"]
        else:
            raw_b = [np.array(info_b["image"])]

        frames_a = _resample_frames(raw_a, transition_frames, src_w, src_h)
        frames_b = _resample_frames(raw_b, transition_frames, src_w, src_h)

        # ── Anchor frames for seamless concat at both seams ────────────────
        # Correct frame selection for overlap semantics (a):
        #   A_pre = A[0 : L_a - O]          → last frame = A[L_a-O-1]
        #   blend starts at A[L_a - O]       → first blend frame
        #   blend ends   at B[O - 1]         → last blend frame
        #   B_post = B[O : L_b]              → first frame = B[O]
        b_end_path = os.path.join(temp_dir, "b_overlap_end.png")
        PILImage.fromarray(frames_b[-1]).save(b_end_path)

        # ── Motion-prefix mode: video_source from A's overlap-zone start ───
        # Pure SE gives the model only a STILL frame at position 0, so it
        # has no motion context and tends to invent rotation/pan direction
        # arbitrarily (often opposite to A's). Passing K frames of A's
        # overlap tail as `video_source` flips the pipeline into VE mode
        # (Continue/Extend + End-frame), giving the model motion history
        # to extrapolate from — the same mechanism that makes Continue
        # preserve motion well.
        #
        # Those first K frames become the first K frames of the blend
        # output. They are EXACTLY the frames of A's overlap zone that
        # A_pre was going to cut off anyway, so the concat stays frame-
        # perfect (A_pre → blend seam = A[L_a-O-1] → A[L_a-O]).
        # Default 1s of A's overlap-zone start as video_source (VE mode).
        # The "still-frame joggers" regression was caused by image_mode
        # from base_params coercing the pipeline into image-only output,
        # not by VE mode itself.
        motion_prefix_sec = float(body.get("motion_prefix_sec", 1.0))
        motion_prefix_sec = max(0.0, min(motion_prefix_sec, overlap_sec_eff * 0.8))
        K_prefix = int(round(motion_prefix_sec * fps)) if motion_prefix_sec > 0 else 0
        K_prefix = max(0, min(K_prefix, len(frames_a) - 2))  # leave room for generation

        def _write_mp4(path: str, frames: list, fps_val: float):
            import imageio
            _writer = imageio.get_writer(path, fps=fps_val, codec="libx264", quality=9)
            try:
                for f in frames:
                    _writer.append_data(f)
            finally:
                _writer.close()

        video_source_path = None
        a_start_path = None
        if K_prefix > 0:
            video_source_path = os.path.join(temp_dir, "motion_prefix.mp4")
            _write_mp4(video_source_path, frames_a[:K_prefix], fps)
        else:
            # Pure SE fallback: single-frame anchor at blend start
            a_start_path = os.path.join(temp_dir, "a_overlap_start.png")
            PILImage.fromarray(frames_a[0]).save(a_start_path)

        # ── Motion-suffix mode: video_end from B's overlap-zone end ────────
        # Symmetric counterpart to motion_prefix. Placed at the END of the
        # output latent sequence via the new `_append_suffix_entries` path
        # in ltx2.py (VideoConditionByKeyframeIndex at end positions).
        # Gives the model B's actual motion trajectory leading into the
        # landing frame, so the joggers arrive at full speed instead of
        # easing-in to hit a static anchor.
        #
        # Those last K frames become the final K frames of the blend output.
        # They are EXACTLY the frames of B's overlap zone that B_post was
        # going to skip anyway, so the blend → B_post seam stays frame-
        # perfect (blend[N-1] = B[O-1] → B_post[0] = B[O]).
        motion_suffix_sec = float(body.get("motion_suffix_sec", 1.0))
        motion_suffix_sec = max(0.0, min(motion_suffix_sec, overlap_sec_eff * 0.8))
        K_suffix = int(round(motion_suffix_sec * fps)) if motion_suffix_sec > 0 else 0
        # Cap so suffix + prefix don't exceed transition length with no room
        # for AI-invented middle. Leave at least 9 frames (1 latent chunk + 1)
        # for the generator.
        K_suffix = max(0, min(K_suffix, len(frames_b) - 1, transition_frames - K_prefix - 9))

        video_end_path = None
        if K_suffix > 0:
            video_end_path = os.path.join(temp_dir, "motion_suffix.mp4")
            # Last K frames of B's overlap zone, in forward temporal order
            _write_mp4(video_end_path, frames_b[-K_suffix:], fps)

        # ── Optional weak keyframe hints for motion continuity ─────────────
        # Pure SE loses A's rotation and B's stride rhythm (model has no
        # motion context beyond the two endpoints). `anchor_frames > 0`
        # injects a few WEAK keyframes from A's overlap zone (forward in
        # time from image_start) and B's overlap zone (backward in time
        # from image_end), at low injection_strength so they act as hints
        # not hard locks.
        #
        # Default 0 = pure SE (proven to produce great creative bridges).
        # Try 2-3 with injection_strength=0.3 to carry some motion context.
        n_anchors = int(body.get("anchor_frames", 0))
        max_anchors = min(len(frames_a) - 1, len(frames_b) - 1, max(1, transition_frames // 4))
        n_anchors = max(0, min(n_anchors, max_anchors))

        extra_refs = []
        extra_positions = []
        if n_anchors > 0:
            # A-side hints: A frames [1..n_anchors] at blend positions [2..n_anchors+1]
            # (position 1 = image_start = frames_a[0]; these continue A's motion forward)
            for i in range(1, n_anchors + 1):
                p = os.path.join(temp_dir, f"a_hint_{i:02d}.png")
                PILImage.fromarray(frames_a[i]).save(p)
                extra_refs.append(p)
                extra_positions.append(i + 1)

            # B-side hints: B frames [len-2..len-1-n_anchors] at positions [N-1..N-n_anchors]
            # (position N = image_end = frames_b[-1]; these bring B's motion into the end)
            for i in range(1, n_anchors + 1):
                b_idx = len(frames_b) - 1 - i
                if b_idx < 0:
                    break
                p = os.path.join(temp_dir, f"b_hint_{i:02d}.png")
                PILImage.fromarray(frames_b[b_idx]).save(p)
                extra_refs.append(p)
                extra_positions.append(transition_frames - i)

        injection_strength = float(body.get("injection_strength", 0.4))
        injection_strength = max(0.0, min(1.0, injection_strength))

        # Diagnostic: show what the UI actually sent us.
        _raw_base_params = body.get("base_params")
        if _raw_base_params is None:
            print(f"[Blend] base_params: <NOT SENT by UI — hard-refresh the browser to pick up the store change>")
        else:
            _bp_keys = sorted(_raw_base_params.keys()) if isinstance(_raw_base_params, dict) else []
            print(f"[Blend] base_params received: {len(_bp_keys)} keys: {_bp_keys}")

        print(f"[Blend] A={os.path.basename(clip_a_path)} ({info_a['w']}x{info_a['h']}@{info_a['fps']:.1f}), "
              f"B={os.path.basename(clip_b_path)} ({info_b['w']}x{info_b['h']}@{info_b['fps']:.1f})")
        # Describe the blend mode selected by prefix/suffix config
        _end_desc = (
            f"video_end={K_suffix} frames ({motion_suffix_sec:.2f}s) of B's overlap end"
            if video_end_path is not None else "image_end=B[O-1]"
        )
        if video_source_path is not None:
            print(f"[Blend] VE mode: video_source={K_prefix} frames ({motion_prefix_sec:.2f}s) of A's overlap start, {_end_desc}")
        else:
            print(f"[Blend] SE mode (no motion prefix): image_start=A[L-O], {_end_desc}")
        if extra_refs:
            print(f"[Blend]   + {len(extra_refs)} weak anchors @ strength={injection_strength:.2f}, "
                  f"positions={' '.join(str(p) for p in extra_positions)}")

        # ── Build generation params ─────────────────────────────────────────
        # Inherit the user's Studio settings (progressive_pipeline,
        # num_inference_steps, guidance_scale, negative_prompt, CFG-related
        # flags, etc.) so the blend uses the same generation config that
        # their manual SE tests used. Then override with blend-specific
        # fields (image_start/end, resolution, video_length, ...).
        default_prompt = (
            "continuous coherent camera motion smoothly transitioning "
            "between the two scenes, cinematic, natural movement"
        )
        default_neg = (
            "crossfade, dissolve, fade, double exposure, ghosting, "
            "static, still, abrupt cut, jump cut"
        )

        # Start from Studio's full params (if the UI passed them). Drop
        # keys we always compute ourselves so they can't leak through stale.
        base_params = dict(body.get("base_params") or {})
        for _k in (
            # Blend computes these
            "video_length", "resolution", "generation_mode", "image_prompt_type",
            "image_start", "image_end", "video_guide", "video_mask",
            "video_prompt_type", "image_refs", "frames_positions", "video_source", "video_end",
            # image_mode: Studio's image-vs-video toggle. MUST drop or the blend
            # can be coerced into image-only mode (outputs a .png instead of
            # generating a video — happened when user had image_mode active in
            # the sidebar and triggered a blend).
            "image_mode",
            # Blend is always a single generation; don't inherit Studio's repeat
            "repeat_generation",
            # Reference pipeline is a per-model Advanced Settings toggle for
            # plain generations; a blend inheriting it would silently switch
            # the sampling pipeline (and its blend target model may not even
            # support it). Never inherit.
            "reference_pipeline",
            # These had their own top-level overrides below
            "prompt", "model_type", "seed", "activated_loras", "loras_multipliers",
        ):
            base_params.pop(_k, None)

        gen_params = dict(base_params)  # start with inherited Studio settings
        gen_params.update({
            "prompt": body.get("prompt", default_prompt),
            "model_type": model_type,
            # negative_prompt: explicit body wins > inherited studio value > default
            "negative_prompt": body.get("negative_prompt", base_params.get("negative_prompt", default_neg)),
            "seed": body.get("seed", -1),
            # guidance_scale / num_inference_steps: explicit body wins > studio value > safe default
            "guidance_scale": float(body.get("guidance_scale", base_params.get("guidance_scale", 1.0))),
            "num_inference_steps": int(body.get("num_inference_steps", base_params.get("num_inference_steps", 15))),
            "video_length": transition_frames,
            "resolution": f"{src_w}x{src_h}",
            "generation_mode": "video",
            "image_mode": 0,  # defensive: blend is always a video job
            "image_prompt_type": "SE",
            "image_start": a_start_path,
            "image_end": b_end_path,
            "activated_loras": body.get("activated_loras", []),
            # Distilled pipeline has a single phase; strip multi-phase lora multipliers.
            "loras_multipliers": " ".join(m.split(";")[0] for m in (body.get("loras_multipliers", "") or "").split()),
            "sliding_window_size": transition_frames + 10,
            "settings_version": 2.52,
            "_blend_clip_a": clip_a_path,
            "_blend_clip_b": clip_b_path,
            "_blend_temp_dir": temp_dir,
            "_blend_mode": blend_mode,
            "_blend_overlap_sec": overlap_sec_eff,
            "_blend_fps": fps,
            "_blend_out_w": src_w,
            "_blend_out_h": src_h,
            # Final concat target — A's native dimensions (rounded to even for
            # libx264). The blend was generated at (src_w, src_h) which has
            # been snapped to 32-multiples (e.g. 1280x720 → 1280x704). Scaling
            # the blend up to A's native dims at concat time matches A_pre and
            # B_post pixel-perfectly, so the seams don't letterbox.
            "_blend_concat_w": int(info_a["w"]) - (int(info_a["w"]) % 2),
            "_blend_concat_h": int(info_a["h"]) - (int(info_a["h"]) % 2),
        })

        # Motion-prefix mode switches from SE (single start frame) to VE
        # (video_source + end frame), giving the model real motion history
        # from A so it extrapolates the rotation direction correctly.
        if video_source_path is not None:
            gen_params["image_prompt_type"] = "VE"
            gen_params["video_source"] = video_source_path
            # Remove image_start entirely — setting it to None explicitly
            # can confuse validation code that checks `key in dict`.
            # "V" in image_prompt_type supersedes "S" (video_source replaces image_start).
            gen_params.pop("image_start", None)

        # Motion-suffix: pass B's overlap-end frames as video_end so the
        # model sees B's motion trajectory leading into the landing frame.
        # Handled in ltx2.py via _append_suffix_entries — supersedes image_end.
        #
        # NOTE: image_end stays in gen_params even when suffix is active.
        # wgp.py validates image_prompt_type="VE" requires an end image, so
        # stripping image_end here triggers "You must provide an End Image"
        # BEFORE our code runs. We keep image_end = B[O-1] for validation;
        # ltx2.py's `has_suffix_frames` branch skips the image_end append
        # when the suffix is present, so it's effectively unused downstream.
        if video_end_path is not None:
            gen_params["video_end"] = video_end_path

        # input_video_strength: how tightly the pipeline locks to video_source
        # AND image_end. Default 1.0 = full lock → model ends up averaging
        # between the two anchors, which decodes as a crossfade for disparate
        # scenes. Lowering to 0.5-0.8 frees the model to invent motion
        # between the anchors instead of interpolating pixels.
        # Handler description: "you may try values lower value than 1 to
        # get more motion" (ltx2_handler.py:181).
        input_video_strength = float(body.get("input_video_strength", base_params.get("input_video_strength", 1.0)))
        input_video_strength = max(0.1, min(1.0, input_video_strength))
        gen_params["input_video_strength"] = input_video_strength

        if extra_refs:
            gen_params["video_prompt_type"] = "KFI"
            gen_params["image_refs"] = extra_refs
            gen_params["frames_positions"] = " ".join(str(p) for p in extra_positions)
            gen_params["injection_strength"] = injection_strength

        # Log the EFFECTIVE gen_params values actually being used for the job
        # (after merging base_params + body overrides + blend-specific fields).
        _effective_log_keys = (
            "num_inference_steps", "guidance_scale", "guidance_phases",
            "stage2_steps", "progressive_pipeline", "input_video_strength",
            "progressive_stage2_steps", "progressive_stage3_steps",
            "cfg_star_switch", "apg_switch",
            "sliding_window_size", "sliding_window_overlap",
        )
        _eff_summary = [(k, gen_params[k]) for k in _effective_log_keys if k in gen_params]
        if _eff_summary:
            print(f"[Blend] Effective gen_params: "
                  f"{', '.join(f'{k}={v!r}' for k, v in _eff_summary)}")
        _neg = gen_params.get("negative_prompt", "")
        if _neg:
            _neg_short = _neg if len(_neg) < 100 else _neg[:97] + "..."
            print(f"[Blend] negative_prompt: {_neg_short!r}")

        workspace = body.get("workspace") or _get_active_workspace()
        job_out_dir = _workspace_dir(workspace)

        job_id = uuid.uuid4().hex[:8]
        job = {
            "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
            "phase": "", "message": "Queued (blend)", "created_at": time.time(),
            "params": gen_params, "output_files": [], "error": None,
            "workspace": workspace, "out_dir": job_out_dir,
        }
        _register_manual_generation_job(job)

        worker = (
            _run_generation
            if execution_mode.policy().simulated
            else _run_blend_generation
        )
        thread = threading.Thread(target=worker, args=(job_id,), daemon=False)
        thread.start()

        return {
            "job_id": job_id,
            "status": "queued",
            "overlap_sec": overlap_sec_eff,
            "frames": transition_frames,
            **_generation_job_acceptance(job),
        }

    except Exception:
        # Setup failed before the background thread took ownership of temp_dir.
        # _run_blend_generation is responsible for cleanup once it starts.
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _run_blend_generation(job_id: str):
    """Background thread: run VG blend generation, then concatenate
    A[:L_a - O] + generated_blend + B[O:] so the blend replaces the
    last O seconds of A and the first O seconds of B (overlap semantics).

    Uses filter_complex with explicit scale+fps normalization so the three
    segments (A at native res/fps, LTX output at snapped res/fps, B at
    native res/fps) always concatenate cleanly regardless of mismatches.
    """
    job = _jobs[job_id]
    temp_dir = job["params"].get("_blend_temp_dir")
    assembly_state = {"abort": False}

    try:
        if not _run_generation(job_id, finalize=False):
            return

        if not register_abort_state(
            job, job_id, _active_gen_states, assembly_state,
        ):
            return
        if not update_job(
            job, message="Assembling blend...", phase="Assembling blend",
        ):
            return

        if not job.get("output_files"):
            finish_job(
                job, "failed", error="Blend generation produced no output",
                message="Blend generation failed",
            )
            return

        blend_params = job["params"]
        clip_a = blend_params.get("_blend_clip_a")
        clip_b = blend_params.get("_blend_clip_b")
        overlap_sec = float(blend_params.get("_blend_overlap_sec", 3))
        # Generation dims (32-snapped, e.g. 1280x704 for a 1280x720 source)
        out_w = int(blend_params.get("_blend_out_w", 0))
        out_h = int(blend_params.get("_blend_out_h", 0))
        # Final concat dims (A's native, e.g. 1280x720) — used as the target
        # for the filter_complex so A_pre and B_post don't get letterboxed
        # down to the blend's 32-snapped aspect. The blend itself is force-
        # scaled to these dims (small vertical stretch if aspect differs).
        concat_w = int(blend_params.get("_blend_concat_w", out_w))
        concat_h = int(blend_params.get("_blend_concat_h", out_h))
        out_fps = float(blend_params.get("_blend_fps", 24.0))

        if not clip_a or not clip_b or not temp_dir:
            finish_job(
                job, "failed", error="Blend assembly inputs are incomplete",
                message="Blend assembly failed",
            )
            return

        import subprocess

        transition_file = job["output_files"][0]
        out_dir = job.get("out_dir", _workspace_dir())
        transition_path = os.path.join(out_dir, transition_file)

        if not os.path.isfile(transition_path):
            print(f"[Blend] Transition file not found: {transition_path}")
            finish_job(
                job, "failed", error="Generated transition file was not found",
                message="Blend assembly failed",
            )
            return

        # ── Durations ────────────────────────────────────────────────────
        def _duration(path):
            ext = os.path.splitext(path)[1].lower()
            if ext not in (".mp4", ".mkv", ".avi", ".mov", ".webm"):
                return 0.0
            try:
                import decord
                vr = decord.VideoReader(path)
                d = len(vr) / (float(vr.get_avg_fps()) or 24.0)
                del vr
                return d
            except Exception:
                return 0.0

        dur_a = _duration(clip_a)
        dur_b = _duration(clip_b)
        a_pre_dur = max(0.0, dur_a - overlap_sec)

        print(f"[Blend] Post: A={dur_a:.2f}s (pre={a_pre_dur:.2f}s), "
              f"B={dur_b:.2f}s (post={max(0.0, dur_b - overlap_sec):.2f}s), "
              f"blend gen={out_w}x{out_h} → concat={concat_w}x{concat_h}@{out_fps:.2f}fps")

        # ── Build ffmpeg filter_complex concat pipeline ──────────────────
        # We pass A, blend, B as three separate inputs, scale+fps-normalize
        # each inside the filter graph, then concat. This avoids the concat
        # demuxer's strict codec-param matching requirements and handles
        # arbitrary input resolutions/fps cleanly.
        import datetime
        ts = datetime.datetime.now().strftime("%Y-%m-%d-%Hh%Mm%Ss")
        blend_name = f"{ts}_blend.mp4"
        blend_path = os.path.join(out_dir, blend_name)

        have_pre = a_pre_dur > 0.05
        have_post = dur_b > overlap_sec + 0.05

        # Video normalization filters — all targeting concat_w × concat_h
        # (A's native dimensions, even). Using fully-named args for scale
        # because some ffmpeg builds reject mixing positional with named.
        #
        # _norm_v: aspect-preserve + pad. Used for A_pre and B_post which
        #          are already at concat dims so it's a no-op for matching
        #          inputs; falls back to pillarbox/letterbox if B's aspect
        #          differs from A's.
        # _norm_v_stretch: force-exact scale (no aspect preserve). Used
        #          for the generated blend, which was rendered at the
        #          32-snapped (out_w, out_h) and needs a tiny stretch to
        #          fill the native concat dims without black bars. The
        #          stretch is typically <3% (e.g. 704 → 720 is 2.3%) and
        #          visually imperceptible.
        def _norm_v(label_in, label_out):
            return (
                f"[{label_in}]scale=w={concat_w}:h={concat_h}:force_original_aspect_ratio=decrease,"
                f"pad=w={concat_w}:h={concat_h}:x=(ow-iw)/2:y=(oh-ih)/2,"
                f"setsar=1,fps={out_fps:.4f},format=yuv420p[{label_out}]"
            )

        def _norm_v_stretch(label_in, label_out):
            return (
                f"[{label_in}]scale=w={concat_w}:h={concat_h},"
                f"setsar=1,fps={out_fps:.4f},format=yuv420p[{label_out}]"
            )

        # Audio normalization: resample to 48k stereo. For inputs without
        # audio we synthesize silence via `anullsrc`.
        def _norm_a(label_in, label_out, dur):
            return f"[{label_in}]aresample=48000,aformat=channel_layouts=stereo[{label_out}]"

        def _silent_a(label_out, dur):
            return f"anullsrc=channel_layout=stereo:sample_rate=48000:d={dur:.3f}[{label_out}]"

        # Assemble inputs in playback order
        inputs = []
        filter_parts = []
        concat_v_labels = []
        concat_a_labels = []
        input_idx = 0

        def _has_audio(path):
            try:
                r = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "a:0",
                     "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                    capture_output=True, text=True, timeout=10,
                )
                return "audio" in (r.stdout or "").lower()
            except Exception:
                return False

        # A_pre (trimmed A)
        if have_pre:
            inputs += ["-t", f"{a_pre_dur:.4f}", "-i", clip_a]
            filter_parts.append(_norm_v(f"{input_idx}:v:0", f"v{input_idx}"))
            concat_v_labels.append(f"v{input_idx}")
            if _has_audio(clip_a):
                filter_parts.append(_norm_a(f"{input_idx}:a:0", f"a{input_idx}", a_pre_dur))
            else:
                filter_parts.append(_silent_a(f"a{input_idx}", a_pre_dur))
            concat_a_labels.append(f"a{input_idx}")
            input_idx += 1

        # Generated blend (the transition) — full duration.
        # Force-scale to concat dims so the 32-snapped render (e.g. 1280x704)
        # fills the native frame (e.g. 1280x720) without pillar/letterboxing.
        blend_dur = overlap_sec
        inputs += ["-i", transition_path]
        filter_parts.append(_norm_v_stretch(f"{input_idx}:v:0", f"v{input_idx}"))
        concat_v_labels.append(f"v{input_idx}")
        if _has_audio(transition_path):
            filter_parts.append(_norm_a(f"{input_idx}:a:0", f"a{input_idx}", blend_dur))
        else:
            filter_parts.append(_silent_a(f"a{input_idx}", blend_dur))
        concat_a_labels.append(f"a{input_idx}")
        input_idx += 1

        # B_post (B skipped by overlap_sec)
        if have_post:
            b_post_dur = dur_b - overlap_sec
            inputs += ["-ss", f"{overlap_sec:.4f}", "-i", clip_b]
            filter_parts.append(_norm_v(f"{input_idx}:v:0", f"v{input_idx}"))
            concat_v_labels.append(f"v{input_idx}")
            if _has_audio(clip_b):
                filter_parts.append(_norm_a(f"{input_idx}:a:0", f"a{input_idx}", b_post_dur))
            else:
                filter_parts.append(_silent_a(f"a{input_idx}", b_post_dur))
            concat_a_labels.append(f"a{input_idx}")
            input_idx += 1

        if input_idx <= 1:
            # Only the blend — nothing to concat. Leave job output as-is.
            print(f"[Blend] No flanking segments; output is the blend alone ({transition_file}).")
            finish_job(
                job,
                "completed",
                progress=100,
                step=0,
                total_steps=0,
                phase="",
                message="Done",
            )
            return

        # Concat filter. ffmpeg's concat demands inputs **interleaved** as
        # per-segment (v,a) pairs: [v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1
        # NOT grouped by stream type [v0][v1][v2][a0][a1][a2] — that causes
        # "Media type mismatch" because the concat filter reads positionally.
        n = input_idx
        pairs = "".join(
            f"[{concat_v_labels[i]}][{concat_a_labels[i]}]" for i in range(n)
        )
        filter_parts.append(f"{pairs}concat=n={n}:v=1:a=1[outv][outa]")

        filter_complex = ";".join(filter_parts)

        # Write the filter to a file and use `-/filter_complex <file>`. This
        # sidesteps any shell/argv escaping issues with long filter strings
        # containing `:` `[` `]` `(` `)` on Windows. The `-/option file`
        # syntax is ffmpeg 7+'s replacement for the deprecated
        # `-filter_complex_script`.
        filter_script_path = os.path.join(temp_dir, "concat_filter.txt")
        with open(filter_script_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(filter_complex)

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-/filter_complex", filter_script_path,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            blend_path,
        ]

        if is_cancel_requested(job):
            return
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        blend_ready = result.returncode == 0 and os.path.isfile(blend_path)
        if blend_ready:
            record_job_outputs(job, [blend_name])
        if is_cancel_requested(job):
            return
        if blend_ready:
            if not update_job(job, output_files=[blend_name]):
                return
            print(f"[Blend] Concatenated {n} segments "
                  f"({'A_pre+' if have_pre else ''}blend{'+B_post' if have_post else ''}) → {blend_name}")

            # Copy metadata sidecar from transition to blend
            meta_src = os.path.join(out_dir, os.path.splitext(transition_file)[0] + ".meta.json")
            meta_dst = os.path.join(out_dir, os.path.splitext(blend_name)[0] + ".meta.json")
            if os.path.isfile(meta_src):
                import shutil
                shutil.copy2(meta_src, meta_dst)
            finish_job(
                job,
                "completed",
                progress=100,
                step=0,
                total_steps=0,
                phase="",
                message="Done",
            )
        else:
            print(f"[Blend] ffmpeg concat failed (returncode={result.returncode})")
            print(f"[Blend] filter_complex was:\n  {filter_complex}")
            print(f"[Blend] cmd: {' '.join(repr(c) for c in cmd)}")
            print(f"[Blend] stderr tail:\n{result.stderr[-800:]}")
            finish_job(
                job,
                "failed",
                error=f"Blend assembly failed (ffmpeg exit {result.returncode})",
                message="Blend assembly failed",
            )

    except Exception as e:
        import traceback
        print(f"[Blend] Concatenation failed: {e}")
        traceback.print_exc()
        finish_job(job, "failed", error=str(e), message=f"Error: {e}")
    finally:
        unregister_abort_state(job_id, _active_gen_states, assembly_state)
        if temp_dir and os.path.isdir(temp_dir):
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


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


# The hardware probe lives in services/hardware_probe.py. This is the same
# function the coefficient pass and the director pipeline receive.
from services.hardware_probe import _get_cached_hardware


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


def _recast_video_frame_count(video_path):
    """Return the exact decoded video-frame count for final validation."""
    import decord

    reader = decord.VideoReader(video_path)
    try:
        return int(len(reader))
    finally:
        del reader


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


def _write_repaint_shot_aware_sidecar(
    job, output_path, shot_bundle, generation_time,
):
    """Persist mapped Repaint settings without disposable shot artifacts."""
    import copy
    from services.asset_manifest import publish_generation_sidecar

    output_name = os.path.basename(output_path)
    params = copy.deepcopy(job.get("params") or {})
    for key in (
        "_defer_output_publication",
        "_repaint_shot_manifest",
        "_repaint_shot_temp_dir",
        "_repaint_final_out_dir",
        "_repaint_source_video",
        "_repaint_shot_bundle",
    ):
        params.pop(key, None)
    params["video_length"] = int(shot_bundle["frame_count"])
    params["seed"] = int(shot_bundle["resolved_seed"])
    params["edit_repaint_shot_aware"] = True
    params["edit_repaint_native_scene_preservation"] = True
    params["edit_repaint_shot_plan"] = list(
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
        tool="repaint",
    )


def _run_repaint_shot_generation(job_id):
    """Generate mapped camera shots, then restore one exact source track."""
    import shutil

    job = _jobs[job_id]
    params = job.get("params") or {}
    shot_bundle = params.get("_repaint_shot_bundle") or {}
    temp_dir = params.get("_repaint_shot_temp_dir")
    final_out_dir = params.get("_repaint_final_out_dir") or _workspace_dir(
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
            phase="Joining camera shots",
            message="Joining Repaint shots and restoring source audio...",
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
                    "Repaint shot assembly is missing camera shot "
                    f"{int(shot.get('shot_index', 0)) + 1}."
                )
            ordered_paths.append(clip_path)

        if not ordered_paths:
            raise RuntimeError("Repaint shot assembly has no video segments.")

        os.makedirs(final_out_dir, exist_ok=True)
        seed = int(shot_bundle["resolved_seed"])
        timestamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
        extension = os.path.splitext(ordered_paths[0])[1] or ".mp4"
        final_path = wgp.get_available_filename(
            final_out_dir,
            f"{timestamp}_seed{seed}_repaint_shot_aware{extension}",
        )
        source_video = params.get("_repaint_source_video")
        source_audio = None
        if source_video and os.path.isfile(source_video):
            try:
                if _recast_video_has_audio(source_video):
                    source_audio = source_video
            except Exception as audio_probe_error:
                print(
                    "[Repaint] Could not probe source audio; assembling "
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
            raise RuntimeError("Repaint camera-shot assembly failed.")

        expected_frames = int(shot_bundle["frame_count"])
        actual_frames = _recast_video_frame_count(final_path)
        if actual_frames != expected_frames:
            try:
                os.remove(final_path)
            except OSError:
                pass
            raise RuntimeError(
                "Repaint camera-shot assembly changed the timeline length "
                f"({actual_frames}/{expected_frames} frames)."
            )

        _write_repaint_shot_aware_sidecar(
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
            "[Repaint] Shot-aware assembly completed: "
            f"{len(ordered_paths)} shots, {actual_frames} frames, "
            f"{'continuous source audio' if source_audio else 'video only'}."
        )
    except Exception as error:
        traceback.print_exc()
        if not is_cancel_requested(job):
            finish_job(
                job,
                "failed",
                error=str(error),
                message=f"Repaint assembly failed: {error}",
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
                job["params"]["edit_repaint_shot_aware"] = True
                job["params"]["edit_repaint_shot_plan"] = published_shots
                job["params"][
                    "edit_repaint_native_scene_preservation"
                ] = True
            job["params"].pop("_repaint_shot_manifest", None)
            job["params"].pop("_repaint_shot_temp_dir", None)
            job["params"].pop("_repaint_final_out_dir", None)
            job["params"].pop("_repaint_source_video", None)
            job["params"].pop("_repaint_shot_bundle", None)
            job["params"].pop("_defer_output_publication", None)
        if temp_dir and os.path.isdir(temp_dir):
            resolved_temp = os.path.realpath(temp_dir)
            expected_prefix = "maestro-repaint-shots-"
            if os.path.basename(resolved_temp).startswith(expected_prefix):
                shutil.rmtree(resolved_temp, ignore_errors=True)


def _write_outpaint_shot_aware_sidecar(
    job, output_path, shot_bundle, generation_time,
):
    """Persist restorable Outpaint settings without private shot paths."""
    import copy
    from services.asset_manifest import publish_generation_sidecar

    output_name = os.path.basename(output_path)
    params = copy.deepcopy(job.get("params") or {})
    params.pop("_defer_output_publication", None)
    for key in list(params):
        if str(key).startswith("_outpaint_"):
            params.pop(key, None)
    params["video_length"] = int(shot_bundle["frame_count"])
    params["seed"] = int(shot_bundle["resolved_seed"])
    params["edit_outpaint_shot_aware"] = True
    params["edit_outpaint_shot_plan"] = list(
        shot_bundle.get("published_shots") or [],
    )
    params["outpaint_preserve_source_audio"] = bool(
        shot_bundle.get("preserve_source_audio", True)
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
        tool="outpaint",
    )


def _run_outpaint_shot_generation(job_id):
    """Generate Outpaint shots independently, then join one exact timeline."""
    import shutil

    job = _jobs[job_id]
    params = job.get("params") or {}
    shot_bundle = params.get("_outpaint_shot_bundle") or {}
    temp_dir = params.get("_outpaint_shot_temp_dir")
    final_out_dir = params.get("_outpaint_final_out_dir") or _workspace_dir(
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
            phase="Joining camera shots",
            message="Joining Outpaint shots and restoring source audio...",
        ):
            return

        clip_outputs = job.get("_internal_clip_output_files") or {}
        ordered_paths = []
        for shot in shot_bundle.get("shots") or []:
            shot_index = int(shot.get("shot_index", len(ordered_paths)))
            raw_name = (
                clip_outputs.get(shot_index)
                or clip_outputs.get(str(shot_index))
            )
            clip_path = (
                raw_name
                if raw_name and os.path.isabs(raw_name)
                else os.path.join(temp_dir or "", raw_name or "")
            )
            if not clip_path or not os.path.isfile(clip_path):
                raise RuntimeError(
                    "Outpaint shot assembly is missing camera shot "
                    f"{shot_index + 1}."
                )
            expected_shot_frames = int(shot.get("frame_count") or 0)
            actual_shot_frames = _recast_video_frame_count(clip_path)
            if actual_shot_frames != expected_shot_frames:
                raise RuntimeError(
                    f"Outpaint camera shot {shot_index + 1} changed "
                    "timeline length "
                    f"({actual_shot_frames}/{expected_shot_frames} frames)."
                )
            ordered_paths.append(clip_path)

        if not ordered_paths:
            raise RuntimeError("Outpaint shot assembly has no video segments.")

        os.makedirs(final_out_dir, exist_ok=True)
        seed = int(shot_bundle["resolved_seed"])
        timestamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
        extension = os.path.splitext(ordered_paths[0])[1] or ".mp4"
        final_path = wgp.get_available_filename(
            final_out_dir,
            f"{timestamp}_seed{seed}_outpaint_shot_aware{extension}",
        )
        source_video = params.get("_outpaint_shot_source_video")
        source_audio = None
        if (
            shot_bundle.get("preserve_source_audio", True)
            and source_video
            and os.path.isfile(source_video)
        ):
            try:
                if _recast_video_has_audio(source_video):
                    source_audio = source_video
            except Exception as audio_probe_error:
                print(
                    "[Outpaint] Could not probe source audio; using "
                    f"generated shot audio: {audio_probe_error}"
                )

        expected_frames = int(shot_bundle["frame_count"])
        fps = float(shot_bundle["fps"])
        assembled = wgp.concatenate_multi_clip_videos(
            ordered_paths,
            final_path,
            source_audio,
            audio_start_sec=0.0,
            abort_callback=lambda: is_cancel_requested(job),
            pad_audio=bool(source_audio),
            audio_duration_sec=float(expected_frames) / fps,
        )
        if is_cancel_requested(job):
            if final_path and os.path.isfile(final_path):
                try:
                    os.remove(final_path)
                except OSError:
                    pass
            return
        if not assembled or not os.path.isfile(final_path):
            raise RuntimeError("Outpaint camera-shot assembly failed.")

        actual_frames = _recast_video_frame_count(final_path)
        if actual_frames != expected_frames:
            try:
                os.remove(final_path)
            except OSError:
                pass
            raise RuntimeError(
                "Outpaint camera-shot assembly changed the timeline length "
                f"({actual_frames}/{expected_frames} frames)."
            )

        _write_outpaint_shot_aware_sidecar(
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
            "[Outpaint] Shot-aware assembly completed: "
            f"{len(ordered_paths)} shots, {actual_frames} frames, "
            f"{'continuous source audio' if source_audio else 'generated audio'}."
        )
    except Exception as error:
        traceback.print_exc()
        if not is_cancel_requested(job):
            finish_job(
                job,
                "failed",
                error=str(error),
                message=f"Outpaint assembly failed: {error}",
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
                job["params"]["edit_outpaint_shot_aware"] = True
                job["params"]["edit_outpaint_shot_plan"] = published_shots
            for key in (
                "_outpaint_shot_manifest",
                "_outpaint_shot_temp_dir",
                "_outpaint_final_out_dir",
                "_outpaint_shot_source_video",
                "_outpaint_shot_bundle",
                "_outpaint_generation_fps",
                "_outpaint_source_frame_count",
                "_defer_output_publication",
            ):
                job["params"].pop(key, None)
        if temp_dir and os.path.isdir(temp_dir):
            resolved_temp = os.path.realpath(temp_dir)
            expected_prefix = "maestro-outpaint-shots-"
            if os.path.basename(resolved_temp).startswith(expected_prefix):
                shutil.rmtree(resolved_temp, ignore_errors=True)


from services.generation_jobs import bind as bind_generation_jobs
from services.generation_jobs import cancel_job, get_status, list_jobs
from routers.generation_jobs import create_generation_jobs_router

bind_generation_jobs(
    _active_gen_states=_active_gen_states,
    _gen_lock=_gen_lock,
    _jobs=_jobs,
    _public_generation_details=_public_generation_details,
    _remove_persisted_generation_job=_remove_persisted_generation_job,
    cancel_audio_analysis_job=cancel_audio_analysis_job,
)
api.include_router(create_generation_jobs_router())


from services.generation_recovery import (
    _discard_generation_leftover,
    _prepare_generation_leftovers,
    _queue_recovered_generation,
    _recovery_job_summary,
    _release_intermediates_at_startup,
    _start_recovered_generation,
    bind as bind_generation_recovery,
)
from routers.generation_jobs import create_generation_recovery_router

api.include_router(create_generation_recovery_router())


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
bind_generation_preparation(
    _PUBLIC_LLM_PROVIDERS=_PUBLIC_LLM_PROVIDERS,
    _effective_llm_routing=_effective_llm_routing,
    _ensure_llm_loaded=_ensure_llm_loaded,
    _image_generation_commands=_image_generation_commands,
    _jobs=_jobs,
    _persist_generation_job=_persist_generation_job,
    _publish_generation_sidecar_for_studio_job=_publish_generation_sidecar_for_studio_job,
    _remove_persisted_generation_job=_remove_persisted_generation_job,
    # Tests replace this name on the server module after import.
    _run_generation=lambda *args, **kwargs: _run_generation(*args, **kwargs),
    _workspace_dir=_workspace_dir,
    wgp=wgp,
)
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
# generate() and get_status() read _job_leftovers from their own module globals.
import services.studio_generate as _studio_generate
_studio_generate._job_leftovers = _job_leftovers
import services.generation_jobs as _generation_jobs
_generation_jobs._job_leftovers = _job_leftovers


bind_generation_recovery(
    _cancel_h3_idle_release=_cancel_h3_idle_release,
    _durable_generation_queue=_durable_generation_queue,
    _image_generation_commands=_image_generation_commands,
    _jobs=_jobs,
    _list_workspaces=_list_workspaces,
    _new_generation_job=_new_generation_job,
    _persist_generation_job=_persist_generation_job,
    _queue_recovery_lock=_queue_recovery_lock,
    # Tests replace this name on the server module after import.
    _reset_canonical_task_for_resume=lambda *args, **kwargs: _reset_canonical_task_for_resume(*args, **kwargs),
    _run_generation_with_preparation=_run_generation_with_preparation,
    _scene2d_export=_scene2d_export,
    _task_registry=_task_registry,
    _workspace_dir=_workspace_dir,
    _world3d_export=_world3d_export,
)

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
