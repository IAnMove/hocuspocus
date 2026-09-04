"""Standalone Tools upscale worker.

The launch runtime owns process state and WanGP's singleton.  This module owns
the post-processing algorithm and receives those runtime hooks explicitly so
it can be tested without importing the heavyweight server bootstrap.
"""

from __future__ import annotations

import os
import time
import traceback
import uuid
from typing import Any, Mapping


TOOL_UPSCALE_METHODS = frozenset(
    {
        "flashvsr2",
        "flashvsr3",
        "flashvsr4",
        "flashvsr2pass2",
        "flashvsr2pass4",
        "lanczos1.5",
        "lanczos2",
    }
)
TOOL_SOURCE_EXTENSIONS = {
    "image": frozenset(
        {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
    ),
    "video": frozenset(
        {
            ".avi",
            ".m4v",
            ".mkv",
            ".mov",
            ".mp4",
            ".mpeg",
            ".mpg",
            ".webm",
            ".wmv",
        }
    ),
}


def upscale_image(
    source_path: str,
    output_path: str,
    method: str,
    *,
    wgp: Any,
    seed: int = -1,
    abort_callback=None,
    progress_callback=None,
) -> tuple[int, int]:
    """Upscale one still image through the existing spatial adapter."""
    from PIL import Image
    from shared.utils.utils import convert_image_to_tensor, convert_tensor_to_image

    if callable(abort_callback) and abort_callback():
        raise InterruptedError("Image upscale was cancelled")
    temporary_path = f"{output_path}.tmp-{uuid.uuid4().hex}"
    try:
        with Image.open(source_path) as opened:
            image = wgp.convert_image(opened).copy()
            sample = convert_image_to_tensor(image).unsqueeze(1)
        if callable(progress_callback):
            progress_callback("Upscaling image", 5, 0, 1)
        sample = wgp.perform_spatial_upsampling(
            sample,
            method,
            seed=seed,
            abort_callback=abort_callback,
            progress_callback=progress_callback,
            still_image=True,
        )
        if callable(abort_callback) and abort_callback():
            raise InterruptedError("Image upscale was cancelled")
        if sample is None:
            if callable(abort_callback) and abort_callback():
                raise InterruptedError("Image upscale was cancelled")
            raise RuntimeError("Image upsampler returned no result")
        result = convert_tensor_to_image(sample, 0).convert("RGB")
        result.save(temporary_path, format="PNG")
        os.replace(temporary_path, output_path)
        return result.size
    except Exception:
        try:
            if os.path.isfile(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass
        raise


def run_tool_upscale(job_id: str, *, runtime: Mapping[str, Any]) -> bool:
    """Run one image/video upscale using explicit launch-runtime hooks.

    ``runtime`` is intentionally a narrow dependency map.  It keeps this
    service independent from FastAPI and from the module-level launch state,
    while preserving the existing job, cancellation, GPU-slot and sidecar
    semantics.
    """
    jobs = runtime["jobs"]
    active_gen_states = runtime["active_gen_states"]
    wgp = runtime["wgp"]
    job = jobs[job_id]
    start_time = None
    abort_state = {"abort": False}
    audio_tracks = []
    final_path = None
    with runtime["coordinated_generation_slot"](
        job, description="HocusPocus Lab GPU tool · upscale"
    ) as acquired:
        if not acquired:
            return False
        try:
            if not runtime["try_start"](
                job, message="Preparing upscale...", phase="Preparing"
            ):
                return False
            start_time = float(job.get("started_at") or time.time())
            if not runtime["register_abort_state"](
                job, job_id, active_gen_states, abort_state
            ):
                return False

            params = job["params"]
            workspace = job.get("workspace")
            out_dir = job.get("out_dir") or wgp.save_path
            os.makedirs(out_dir, exist_ok=True)
            wgp.save_path = out_dir

            method = params.get("method") or "flashvsr2"
            if method not in TOOL_UPSCALE_METHODS:
                raise ValueError("Unsupported upscale method")
            source_kind = str(params.get("source_kind") or "video").casefold()
            source_value = (
                params.get("source_path")
                if source_kind == "image"
                else params.get("video_path")
            ) or params.get("_source_path") or params.get("source")
            source_path = runtime["resolve_tool_clip_path"](source_value, workspace)
            if not source_path:
                runtime["finish_job"](
                    job,
                    "failed",
                    error="Input source not found",
                    message="Error: input source not found",
                )
                return False
            if source_kind not in TOOL_SOURCE_EXTENSIONS:
                raise ValueError("Unsupported source kind")
            source_extension = os.path.splitext(source_path)[1].casefold()
            if source_extension not in TOOL_SOURCE_EXTENSIONS[source_kind]:
                raise ValueError("Source kind does not match file format")

            before = set(os.listdir(out_dir)) if os.path.isdir(out_dir) else set()

            def _abort():
                return bool(abort_state.get("abort")) or runtime[
                    "is_cancel_requested"
                ](job)

            def _progress(phase, current_step=None, total_steps=None):
                changes = {}
                if phase:
                    changes.update(message=str(phase), phase=str(phase))
                try:
                    if total_steps:
                        step = int(current_step or 0)
                        total = int(total_steps)
                        changes.update(
                            step=step,
                            total_steps=total,
                            progress=max(5, min(95, int(step / total * 100))),
                        )
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
                if changes:
                    runtime["update_job"](job, **changes)

            source_filename = str(
                params.get("source_filename") or os.path.basename(source_path)
            )
            final_path = None
            image_size = None
            if source_kind == "image":
                if not runtime["update_job"](
                    job, message="Upscaling image...", phase="Upscaling", progress=5
                ):
                    return False
                final_path = wgp.get_available_filename(
                    out_dir,
                    source_filename,
                    "_upscaled",
                    force_extension=".png",
                )
                image_size = upscale_image(
                    source_path,
                    final_path,
                    method,
                    wgp=wgp,
                    seed=int(params.get("seed", -1)),
                    abort_callback=_abort,
                    progress_callback=_progress,
                )
            else:
                from shared.utils.utils import get_video_info

                fps, _width, _height, _frames = get_video_info(source_path)
                audio_tracks, audio_metadata = wgp.extract_audio_tracks(source_path)
                has_audio = len(audio_tracks) > 0
                if not runtime["update_job"](
                    job, message="Upscaling...", phase="Upscaling", progress=5
                ):
                    wgp.cleanup_temp_audio_files(audio_tracks)
                    return False

                container = wgp.server_config.get("video_container", "mp4")
                codec = wgp.server_config.get("video_output_codec", None)
                final_path = wgp.get_available_filename(
                    out_dir,
                    source_filename,
                    "_upscaled",
                    force_extension=f".{container}",
                )
                if wgp.flashvsr.is_upsampling(method):
                    tmp_path = runtime["chunked_flashvsr_upscale"](
                        source_path,
                        method,
                        job=job,
                        abort_check=_abort,
                        progress_callback=_progress,
                    )
                    if tmp_path is None or _abort():
                        if tmp_path and os.path.isfile(tmp_path):
                            try:
                                os.remove(tmp_path)
                            except OSError:
                                pass
                        wgp.cleanup_temp_audio_files(audio_tracks)
                        return False
                    if has_audio:
                        wgp.combine_video_with_audio_tracks(
                            tmp_path,
                            audio_tracks,
                            final_path,
                            audio_metadata=audio_metadata,
                        )
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                        wgp.cleanup_temp_audio_files(audio_tracks)
                    else:
                        os.replace(tmp_path, final_path)
                else:
                    sample = wgp.get_resampled_video(
                        source_path, 0, wgp.max_source_video_frames, fps
                    )
                    sample = sample.permute(-1, 0, 1, 2)
                    sample = wgp.perform_spatial_upsampling(
                        sample,
                        method,
                        seed=int(params.get("seed", -1)),
                        abort_callback=_abort,
                        progress_callback=_progress,
                    )
                    if _abort():
                        return False
                    output_fps = round(fps)
                    if has_audio:
                        tmp_path = wgp.get_available_filename(
                            out_dir,
                            source_filename,
                            "_uptmp",
                            force_extension=f".{container}",
                        )
                        wgp.save_video(
                            tensor=sample[None],
                            save_file=tmp_path,
                            fps=output_fps,
                            nrow=1,
                            normalize=True,
                            value_range=(-1, 1),
                            codec_type=codec,
                            container=container,
                        )
                        wgp.combine_video_with_audio_tracks(
                            tmp_path,
                            audio_tracks,
                            final_path,
                            audio_metadata=audio_metadata,
                        )
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                        wgp.cleanup_temp_audio_files(audio_tracks)
                    else:
                        wgp.save_video(
                            tensor=sample[None],
                            save_file=final_path,
                            fps=output_fps,
                            nrow=1,
                            normalize=True,
                            value_range=(-1, 1),
                            codec_type=codec,
                            container=container,
                        )
                    sample = None

            after = set(os.listdir(out_dir)) if os.path.isdir(out_dir) else set()
            new_files = sorted(
                f
                for f in (after - before)
                if not f.endswith(".meta.json") and "_uptmp" not in f
            )
            if runtime["is_cancel_requested"](job):
                for fname in new_files:
                    try:
                        os.remove(os.path.join(out_dir, fname))
                    except OSError:
                        pass
                return False
            runtime["record_job_outputs"](job, new_files)
            source_asset_id = params.get("source_asset_id")
            source_ref = {
                "id": source_asset_id,
                "kind": source_kind,
                "uri": source_filename,
                "role": "source",
            }
            for fname in new_files:
                runtime["write_tool_sidecar"](
                    out_dir,
                    fname,
                    source_name=source_filename,
                    tool="upscale",
                    params={
                        "method": method,
                        "model_type": "post_processing",
                        "source_asset_id": source_asset_id,
                        "source_kind": source_kind,
                        "source_filename": source_filename,
                    },
                    elapsed=time.time() - start_time,
                    job_id=job_id,
                    task_id=job.get("task_id"),
                    root_task_id=job.get("root_task_id"),
                    workspace=job.get("workspace"),
                    generation_mode=source_kind,
                    source_asset_id=source_asset_id,
                    source_kind=source_kind,
                    provenance=job.get("provenance"),
                    inputs=[source_ref] if source_asset_id else [],
                    parents=[source_ref] if source_asset_id else [],
                    transformations=[
                        {
                            "type": "upscale",
                            "backend": (
                                "flashvsr" if method.startswith("flashvsr") else "lanczos"
                            ),
                            "method": method,
                        }
                    ],
                    technical=(
                        {
                            "width": image_size[0],
                            "height": image_size[1],
                            "output": "png",
                        }
                        if image_size
                        else {"output": "video"}
                    ),
                )
            completed = runtime["finish_job"](
                job,
                "completed",
                progress=100,
                phase="",
                message="Done",
            )
            print(
                f"[Tools/upscale] {source_filename} -> {new_files} "
                f"({wgp.format_time(time.time() - start_time)})"
            )
            return completed
        except InterruptedError:
            if final_path and os.path.isfile(final_path):
                try:
                    os.remove(final_path)
                except OSError:
                    pass
            runtime["acknowledge_cancel"](job)
            return False
        except Exception as error:
            traceback.print_exc()
            runtime["finish_job"](
                job, "failed", error=str(error), message=f"Error: {error}"
            )
            return False
        finally:
            runtime["unregister_abort_state"](job_id, active_gen_states, abort_state)
            try:
                wgp.cleanup_temp_audio_files(audio_tracks)
            except Exception:
                pass
            try:
                wgp.release_flashvsr_vram()
            except Exception:
                pass
