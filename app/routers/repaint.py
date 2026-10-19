"""HTTP routes for Repaint.

POST /api/v1/repaint/preview and POST /api/v1/repaint. The handler bodies are
the ones that used to live in ``_launch_runtime``; they are the served
endpoints, so the route table names this file. Launch hands this module the
objects it owns once, as the arguments of :func:`create_repaint_router`. The
generation worker and the hardware probe are defined further down in launch
and the recast helpers are leaving it, so launch passes forwarders that call
its own names when a handler runs.
"""
import os
import threading
import time
import traceback
import uuid

from fastapi import APIRouter, HTTPException, Request

from services import execution_mode
from services.job_lifecycle import (
    finish_job,
    is_cancel_requested,
    register_abort_state,
    try_requeue,
    try_start,
    unregister_abort_state,
    update_job,
)
from services.repaint_planning import (
    _build_repaint_semantic_conditioning,
    _build_repaint_shot_manifest,
    _normalize_repaint_region_mappings,
    _prepare_repaint_target_frame,
    _repaint_preview_data_uri,
    _validate_repaint_target_aspect,
)
from services.repaint_run import _run_repaint_shot_generation

# Set by create_repaint_router(); None until the full server mounts the routes.
wgp = None
_RECAST_MASK_COLORS = None
_active_gen_states = None
_coordinated_generation_slot = None
_generation_job_acceptance = None
_get_active_workspace = None
_get_cached_hardware = None
_normalize_recast_resolution_profile = None
_normalize_scail2_guidance_scale = None
_normalize_scail2_inference_steps = None
_recast_resolution_for_source = None
_recast_window_size_for_profile = None
_register_manual_generation_job = None
_resolve_recast_media = None
_run_generation = None
_workspace_dir = None


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


def create_repaint_router(
    *, wgp, recast_mask_colors, active_gen_states, coordinated_generation_slot, generation_job_acceptance,
    get_active_workspace, get_cached_hardware, normalize_recast_resolution_profile, normalize_scail2_guidance_scale,
    normalize_scail2_inference_steps, recast_resolution_for_source, recast_window_size_for_profile,
    register_manual_generation_job, resolve_recast_media, run_generation, workspace_dir,
) -> APIRouter:
    """Mount the two Repaint routes, preview then repaint. Launch calls this once; it is the one place this module
    takes launch objects."""
    globals().update(
        wgp=wgp,
        _RECAST_MASK_COLORS=recast_mask_colors,
        _active_gen_states=active_gen_states,
        _coordinated_generation_slot=coordinated_generation_slot,
        _generation_job_acceptance=generation_job_acceptance,
        _get_active_workspace=get_active_workspace,
        _get_cached_hardware=get_cached_hardware,
        _normalize_recast_resolution_profile=normalize_recast_resolution_profile,
        _normalize_scail2_guidance_scale=normalize_scail2_guidance_scale,
        _normalize_scail2_inference_steps=normalize_scail2_inference_steps,
        _recast_resolution_for_source=recast_resolution_for_source,
        _recast_window_size_for_profile=recast_window_size_for_profile,
        _register_manual_generation_job=register_manual_generation_job,
        _resolve_recast_media=resolve_recast_media,
        _run_generation=run_generation,
        _workspace_dir=workspace_dir,
    )
    router = APIRouter()
    router.add_api_route(
        "/api/v1/repaint/preview",
        repaint_preview_endpoint,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/v1/repaint",
        repaint_endpoint,
        methods=["POST"],
    )
    return router
