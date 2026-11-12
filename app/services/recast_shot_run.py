"""Recast shot generation: join the worker's clips and restore source audio.

The body is the launch module's, moved verbatim. Launch keeps the name the
worker calls. The standard library and the job-lifecycle helpers are imported
here. Launch passes the objects it owns through :func:`bind`, once.
``_run_generation`` is a forwarder, because the characterization rig replaces
launch's worker after this module has been imported.
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
from services.recast_reference_prepare import (
    _recast_video_frame_count,
    _recast_video_has_audio,
)
from services.recast_shot_manifest import _write_recast_shot_aware_sidecar

# Bound by bind(); None until launch calls it.
wgp = None
_jobs = None
_active_gen_states = None
_workspace_dir = None
_run_generation = None


def bind(*, wgp, _jobs, _active_gen_states, _workspace_dir, _run_generation):
    """Take the launch objects this module reads. Launch calls this once."""
    globals().update(
        wgp=wgp,
        _jobs=_jobs,
        _active_gen_states=_active_gen_states,
        _workspace_dir=_workspace_dir,
        _run_generation=_run_generation,
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
