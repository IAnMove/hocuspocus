"""Repaint shot assembly.

The shot sidecar and the shot-generation worker. The function bodies are the
ones that used to live in ``_launch_runtime``. Launch hands this module the
objects it owns once, through :func:`bind`. The generation worker is defined
further down in launch and the recast video helpers are leaving it, so launch
passes forwarders that call its own names when a function runs.
"""
import os
import time
import traceback

from services.job_lifecycle import (
    finish_job,
    is_cancel_requested,
    register_abort_state,
    unregister_abort_state,
    update_job,
)

# Bound by bind(); None until the full server binds them.
wgp = None
_jobs = None
_active_gen_states = None
_workspace_dir = None
_recast_video_has_audio = None
_recast_video_frame_count = None
_run_generation = None


def bind(
    *, wgp, jobs, active_gen_states, workspace_dir, recast_video_has_audio, recast_video_frame_count,
    run_generation,
):
    """Take the launch objects this module reads. Launch calls this once, after it defines them."""
    globals().update(
        wgp=wgp,
        _jobs=jobs,
        _active_gen_states=active_gen_states,
        _workspace_dir=workspace_dir,
        _recast_video_has_audio=recast_video_has_audio,
        _recast_video_frame_count=recast_video_frame_count,
        _run_generation=run_generation,
    )


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
