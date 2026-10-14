"""Outpaint preparation, the shot sidecar and per-shot generation.

The function bodies are the ones that used to live in ``_launch_runtime``.
Launch hands this module the objects it owns once, through :func:`bind`.
The generation worker and ``_recast_video_frame_count`` are defined further
down in launch, so launch passes forwarders that call launch's functions.
"""
import os
import time
import traceback

from services.job_lifecycle import (
    finish_job,
    is_cancel_requested,
    register_abort_state,
    try_requeue,
    try_start,
    unregister_abort_state,
    update_job,
)
from services.outpaint_planning import (
    _build_outpaint_shot_manifest,
    _detect_outpaint_video_shot_ranges,
)

# Bound by bind(); None until the full server binds them.
wgp = None
_jobs = None
_active_gen_states = None
_coordinated_generation_slot = None
_workspace_dir = None
_recast_video_has_audio = None
_recast_video_frame_count = None
_run_generation = None


def bind(
    *, wgp, jobs, active_gen_states, coordinated_generation_slot, workspace_dir,
    recast_video_has_audio, recast_video_frame_count, run_generation,
):
    """Take the launch objects this module reads. Launch calls this once, after it defines them."""
    globals().update(
        wgp=wgp,
        _jobs=jobs,
        _active_gen_states=active_gen_states,
        _coordinated_generation_slot=coordinated_generation_slot,
        _workspace_dir=workspace_dir,
        _recast_video_has_audio=recast_video_has_audio,
        _recast_video_frame_count=recast_video_frame_count,
        _run_generation=run_generation,
    )


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
