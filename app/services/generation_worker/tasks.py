"""The middle of a generation run: the task queue, the task loop and the collection of outputs.

Part of the generation worker (``services.generation_worker``). The functions are the bodies that
``_run_generation`` and its phases had in ``app/_launch_runtime.py``, moved without edits. The objects
they use from the full server are injected by ``bind`` (called by ``bind_generation_worker``) and are
the same objects the rest of the server uses; this module does not import WanGP, a router or
``_launch_runtime``.
"""

import gc
import os
import time
import torch
import traceback
from services import media_dimensions, safe_download
from services.job_lifecycle import (
    GENERATED_MEDIA_EXTENSIONS,
    collect_job_outputs,
    finish_job,
    is_cancel_requested,
    record_job_outputs,
    update_job,
)
from shared.utils.generation_timing import GenerationTaskTimer
from shared.utils.ltx_prompt_queue import schedule_ltx_prompt_windows
from services.generation_worker.finalize import _run_generation_finalize

# Injected by bind(); None until the full server binds them.
_extract_output_seed = None
_publish_generation_sidecar_for_studio_job = None
wgp = None


def bind(**names):
    """Take the full server's objects this module uses (see bind_generation_worker)."""
    global _extract_output_seed, _publish_generation_sidecar_for_studio_job, wgp
    _extract_output_seed = names["_extract_output_seed"]
    _publish_generation_sidecar_for_studio_job = names["_publish_generation_sidecar_for_studio_job"]
    wgp = names["wgp"]


def _run_generation_queue(st):
    """Parse the manifest into the task queue and prepare the output folder."""
    job, job_id, manifest = st.job, st.job_id, st.manifest
    pp_film_grain_intensity = st.pp_film_grain_intensity
    pp_film_grain_saturation = st.pp_film_grain_saturation
    pp_spatial_upsampling, start_time, state = st.pp_spatial_upsampling, st.start_time, st.state
    queue, error = wgp._parse_task_manifest(manifest, state, os.getcwd())

    if error:
        finish_job(
            job, "failed", error=error,
            message=f"Validation error: {error}",
        )
        return False

    if not queue:
        finish_job(
            job, "failed", error="Task validation failed",
            message="Task validation failed",
        )
        return False

    state["gen"]["queue"] = queue

    prompt_windows = schedule_ltx_prompt_windows(queue)
    if prompt_windows:
        print(
            f"[LTX2][queue-prefetch] scheduled {len(prompt_windows)} "
            f"prompt windows: {prompt_windows}"
        )

    # Track existing outputs to detect new files
    # Use workspace captured at submission time, not current global save_path
    out_dir = job.get("out_dir") or wgp.save_path
    # Point wgp.save_path to this job's target directory.
    # No save/restore — the workspace switch endpoint is the sole
    # controller of wgp.save_path outside of generation.
    wgp.save_path = out_dir
    wgp.image_save_path = out_dir
    wgp.audio_save_path = out_dir
    print(f"[Gen {job_id}] save_path locked to: {out_dir}")
    before = set()
    if os.path.isdir(out_dir):
        before = set(os.listdir(out_dir))

    # Process tasks with live progress (inline from process_tasks_cli)
    gen = wgp.get_gen_info(state)
    total_tasks = len(queue)
    completed = 0
    skipped = 0
    job["task_timings"] = []
    job["clip_output_files"] = [None] * total_tasks
    job["last_progress_at"] = time.time()
    cancelled = False
    clip_output_files: dict[int, str] = {}
    join_output_file = None

    def _write_output_sidecars(file_names):
        """Stamp every produced media file, including abort leftovers.

        Director only exposes the final sliding-window file for each
        clip, but pipeline deletion also needs ownership metadata on
        superseded window saves.  Write these sidecars as soon as the
        files are discovered so a later cancellation cannot strand
        unowned intermediates.
        """
        if not file_names:
            return
        upload_filenames = {}
        for key in [
            "image_start", "image_end", "video_guide", "audio_guide",
            "audio_guide2", "audio_guide3", "audio_guide4",
            "audio_guide5", "audio_guide6",
        ]:
            val = job["params"].get(key)
            if val and isinstance(val, str):
                upload_filenames[key] = os.path.basename(val)
            elif val and isinstance(val, list):
                upload_filenames[key] = [
                    os.path.basename(v)
                    if isinstance(v, str) and v else ""
                    for v in val
                ]
        sidecar_params = job["params"].copy()
        # These settings are stripped before generation and applied
        # afterward, so retain them for pencil-restore metadata.
        if pp_film_grain_intensity > 0:
            sidecar_params["film_grain_intensity"] = (
                pp_film_grain_intensity
            )
            sidecar_params["film_grain_saturation"] = (
                pp_film_grain_saturation
            )
        if pp_spatial_upsampling:
            sidecar_params["spatial_upsampling"] = (
                pp_spatial_upsampling
            )
        sidecar = {
            "params": sidecar_params,
            "upload_filenames": upload_filenames,
            "generation_mode": job["params"].get("generation_mode"),
            "job_id": job_id,
            "task_id": job.get("task_id"),
            "root_task_id": job.get("root_task_id") or job.get("task_id"),
            "generation_time": round(time.time() - start_time),
            "created_at": time.time(),
        }
        dpid = job["params"].get("_director_pipeline_id")
        if dpid:
            sidecar["director_pipeline_id"] = dpid
        if isinstance(gen.get("model_prompts"), dict):
            # The prompt a model handler rewrote (an H3 window's
            # timing contract): what the model really received.
            sidecar["model_prompts"] = dict(gen["model_prompts"])
        clip_index_by_filename = {
            filename: index
            for index, filename in clip_output_files.items()
        }
        for fname in file_names:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in GENERATED_MEDIA_EXTENSIONS:
                continue
            file_sidecar = dict(sidecar)
            file_sidecar["params"] = sidecar_params.copy()
            resolved_seed = _extract_output_seed(fname)
            if resolved_seed is not None:
                # A request seed of -1 means "choose randomly".  The
                # filename carries the seed that was actually used;
                # store it so Load Settings reproduces a good result,
                # including after ffmpeg post-processing.
                file_sidecar["params"]["seed"] = resolved_seed
            if fname in clip_index_by_filename:
                file_sidecar["director_clip_index"] = (
                    clip_index_by_filename[fname]
                )
            else:
                file_sidecar.pop("director_clip_index", None)
            file_sidecar["output_filename"] = fname
            produced = media_dimensions.produced_resolution(
                os.path.join(out_dir, fname), sidecar_params.get("resolution"),
            )
            if produced:
                file_sidecar["output_resolution"] = produced
            _publish_generation_sidecar_for_studio_job(
                job, os.path.join(out_dir, fname), file_sidecar,
            )

    is_multiclip = total_tasks > 1 and any(t.get('params', {}).get('multi_clip_info') for t in queue)
    st._write_output_sidecars, st.before, st.cancelled = _write_output_sidecars, before, cancelled
    st.clip_output_files, st.completed, st.gen = clip_output_files, completed, gen
    st.is_multiclip, st.join_output_file, st.out_dir = is_multiclip, join_output_file, out_dir
    st.queue, st.skipped, st.total_tasks = queue, skipped, total_tasks
    return _run_generation_tasks(st)


def _run_generation_tasks(st):
    """Run the queued tasks one by one, with live progress, then summarise."""
    AsyncStream, active_task_timer, async_run = st.AsyncStream, st.active_task_timer, st.async_run
    cancelled, clip_output_files, completed = st.cancelled, st.clip_output_files, st.completed
    gen, inspect, is_multiclip, job, job_id = st.gen, st.inspect, st.is_multiclip, st.job, st.job_id
    join_output_file, out_dir, queue = st.join_output_file, st.out_dir, st.queue
    skipped, start_time, state, total_tasks = st.skipped, st.start_time, st.state, st.total_tasks
    try:
        for task_idx, task in enumerate(queue):
            if is_cancel_requested(job):
                cancelled = True
                break
            task_before = set(os.listdir(out_dir)) if os.path.isdir(out_dir) else set()
            task_no = task_idx + 1
            task_file_start = len(gen.get("file_list") or [])
            task_artifact_start = len(gen.get("artifact_list") or [])
            prompt_preview = (task.get('prompt', '') or '')[:60]
            print(f"\n[Task {task_no}/{total_tasks}] {prompt_preview}...")
            active_task_timer = GenerationTaskTimer(
                panel_no=task_no,
                panel_total=total_tasks,
                prompt_preview=prompt_preview,
            )
            job["task_timings"].append(active_task_timer.data)
            if is_multiclip:
                progress_info = (
                    (task.get("params") or {}).get("multi_clip_info")
                    or {}
                )
                progress_label = str(
                    progress_info.get("progress_label") or "Clip"
                )
                if not update_job(
                    job,
                    message=f"{progress_label} {task_no}/{total_tasks}",
                    phase=f"{progress_label} {task_no}/{total_tasks}",
                ):
                    cancelled = True
                    break

            validated_params = wgp.validate_task(task, state)
            if validated_params is None:
                print(f"  [SKIP] Task {task_no} failed validation")
                active_task_timer.finish("skipped")
                active_task_timer = None
                skipped += 1
                continue

            task_error = _run_generation_task_stream(
                    AsyncStream, active_task_timer, async_run, gen, inspect, is_multiclip, job,
                    job_id, state, task, task_idx, task_no, total_tasks, validated_params)

            join_output_file, task_files = _run_generation_task_files(
                    clip_output_files, gen, join_output_file, task, task_artifact_start,
                    task_file_start)

            if is_cancel_requested(job) or gen.get("abort"):
                cancelled = True
                break

            completed = _run_generation_task_done(
                    active_task_timer, completed, is_multiclip, job, out_dir, queue, task_before,
                    task_error, task_files, task_idx, task_no, total_tasks)
            active_task_timer = None

        elapsed = time.time() - start_time
        print(f"\n{'='*50}")
        summary = f"Generation completed: {completed}/{total_tasks} tasks in {wgp.format_time(elapsed)}"
        if skipped > 0:
            summary += f" ({skipped} skipped)"
        print(summary)
        success = not cancelled and completed == (total_tasks - skipped)
    finally:
        st.active_task_timer = active_task_timer
    st.cancelled, st.join_output_file, st.success = cancelled, join_output_file, success
    return _run_generation_collect(st)


def _run_generation_task_stream(
        AsyncStream, active_task_timer, async_run, gen, inspect, is_multiclip, job, job_id, state,
        task, task_idx, task_no, total_tasks, validated_params):
    """Start the engine for one task and relay its progress until it exits."""
    gen["prompt_no"] = task_no
    gen["prompts_max"] = total_tasks

    params = validated_params.copy()
    params['state'] = state

    com_stream = AsyncStream()
    send_cmd = com_stream.output_queue.push

    def make_error_handler(task, params, send_cmd):
        def error_handler():
            try:
                expected_args = set(inspect.signature(wgp.generate_video).parameters.keys())
                filtered_params = {k: v for k, v in params.items() if k in expected_args}
                # A cloned voice hears its reference with long pauses shortened
                # (a cached copy; the job and the user's file keep the original).
                from services.speech_reference_pauses import tighten_clone_references
                tighten_clone_references(filtered_params, base_model_type=wgp.get_base_model_type)
                plugin_data = task.get('plugin_data', {})
                # Model downloads are blocking inside hf-hub. Bind
                # their byte-progress loop to this exact job's
                # durable abort state so Cancel works before the
                # model has finished downloading or loading.
                from services.generation_memory import prepare_queued_params
                prepare_queued_params(params)
                with safe_download.cancellable_downloads(
                    lambda: is_cancel_requested(job)
                    or bool(gen.get("abort")),
                ):
                    wgp.generate_video(task, send_cmd, plugin_data=plugin_data, **filtered_params)
            except Exception as e:
                if is_cancel_requested(job) or gen.get("abort"):
                    print(f"\n  [Cancel] Generation worker acknowledged job {job_id}")
                else:
                    print(f"\n  [ERROR] {e}")
                    traceback.print_exc()
                    send_cmd("error", str(e))
            finally:
                send_cmd("exit", None)
        return error_handler

    async_run(make_error_handler(task, params, send_cmd))

    # Process stream — update job dict with live progress
    task_error = False
    last_msg_len = 0
    in_status_line = False
    while True:
        cmd, data = com_stream.output_queue.next()
        if is_cancel_requested(job) and cmd != "exit":
            continue
        if cmd == "exit":
            if in_status_line:
                print()
            break
        elif cmd == "error":
            print(f"\n  [ERROR] {data}")
            in_status_line = False
            task_error = True
            update_job(job, error=str(data), message=f"Error: {data}")
        elif cmd == "progress":
            job["last_progress_at"] = time.time()
            if isinstance(data, list) and len(data) >= 2:
                (msg, progress_updates, step, total) = _run_generation_task_progress(
                        data, is_multiclip, job, task, task_idx, task_no, total_tasks)
                if not update_job(job, **progress_updates):
                    continue
                active_task_timer.phase(msg)
                status_line = f"\r  [{step}/{total}] {msg}" if total > 0 else f"\r  {msg}"
                print(status_line.ljust(max(last_msg_len, len(status_line))), end="", flush=True)
                last_msg_len = len(status_line)
                in_status_line = True
        elif cmd == "status":
            active_task_timer.phase(data)
            if not update_job(
                job,
                message=str(data),
                phase=str(data),
                step=0,
                total_steps=0,
                progress=0,
                last_progress_at=time.time(),
            ):
                continue
            if "Loading" in str(data):
                print(data)
                in_status_line = False
                last_msg_len = 0
            else:
                status_line = f"\r  {data}"
                print(status_line.ljust(max(last_msg_len, len(status_line))), end="", flush=True)
                last_msg_len = len(status_line)
                in_status_line = True
        elif cmd == "info":
            job["last_progress_at"] = time.time()
            print(f"\n  [INFO] {data}")
            in_status_line = False
    return task_error


def _run_generation_task_progress(data, is_multiclip, job, task, task_idx, task_no, total_tasks):
    """Turn one engine progress report into a job update."""
    progress_updates = {}
    if isinstance(data[0], tuple):
        step, total = data[0]
        msg = data[1] if len(data) > 1 else ""
        # For TTS: extract progress from message
        # Multi-speaker: "Segment 26/51" — use segment count
        # Single-speaker: "45/600 s" — show seconds, use indeterminate progress
        import re as _re
        seg_match = _re.search(r'Segment\s+(\d+)/(\d+)', msg)
        sec_match = _re.search(r'(\d+)/(\d+)\s*s\b', msg) if not seg_match else None
        if sec_match:
            # Single/text mode: show seconds generated as a pulsing progress
            sec_current = int(sec_match.group(1))
            progress_updates.update(
                progress=min(95, sec_current * 3),
                step=sec_current,
                total_steps=0,
                message=f"Generating audio... {sec_current}s",
            )
        if seg_match:
            seg_current = int(seg_match.group(1))
            seg_total = int(seg_match.group(2))
            progress_updates.update(
                progress=int((seg_current / seg_total) * 100) if seg_total > 0 else 0,
                step=seg_current,
                total_steps=seg_total,
            )
        elif is_multiclip and total > 0:
            # Aggregate: each clip contributes 1/total_tasks of overall progress
            clip_progress = step / total
            progress_updates["progress"] = int(((task_idx + clip_progress) / total_tasks) * 100)
            progress_info = (
                (task.get("params") or {}).get(
                    "multi_clip_info",
                )
                or {}
            )
            progress_label = str(
                progress_info.get(
                    "progress_label",
                )
                or "Clip"
            )
            msg = (
                f"{progress_label} "
                f"{task_no}/{total_tasks}: {msg}"
            )
            progress_updates.update(step=step, total_steps=total)
        else:
            progress_updates.update(
                progress=int((step / total) * 100) if total > 0 else 0,
                step=step,
                total_steps=total,
            )
    else:
        step = 0
        msg = data[1] if len(data) > 1 else str(data[0])
        total = 0
        progress_updates.update(step=0, total_steps=0)
    from shared.utils.generation_timing import inference_progress_clock
    from services.generation_memory import note_inference_step
    progress_updates.update(inference_progress_clock(job, msg, step, time.time()))
    progress_updates.update(note_inference_step(
        job, step=step, now=time.time(), message=msg,
    ))
    progress_updates.update(message=msg, phase=msg, last_progress_at=time.time())
    return msg, progress_updates, step, total


def _run_generation_task_files(
        clip_output_files, gen, join_output_file, task, task_artifact_start, task_file_start):
    """Collect the files one task registered and bind its clip file."""
    # WGP may emit several cumulative sliding-window files for a
    # single clip. Bind only the latest file from this task to its
    # explicit multi-clip index; filename ordering is ambiguous.
    task_files = []
    for output_path in (
        (gen.get("artifact_list") or [])[task_artifact_start:]
        + (gen.get("file_list") or [])[task_file_start:]
    ):
        if output_path not in task_files:
            task_files.append(output_path)
    clip_info = (task.get("params") or {}).get("multi_clip_info")
    if isinstance(clip_info, dict) and "index" in clip_info:
        latest_clip_file = None
        for output_path in reversed(task_files):
            filename = os.path.basename(output_path)
            stem, extension = os.path.splitext(filename)
            if extension.lower() not in {
                ".mp4", ".webm", ".mkv", ".mov",
            }:
                continue
            if "_multiclip" in stem.lower():
                if join_output_file is None:
                    join_output_file = filename
            elif latest_clip_file is None:
                latest_clip_file = filename
        if latest_clip_file:
            try:
                clip_output_files[
                    int(clip_info["index"])
                ] = latest_clip_file
            except (TypeError, ValueError):
                pass
    return join_output_file, task_files


def _run_generation_task_done(
        active_task_timer, completed, is_multiclip, job, out_dir, queue, task_before, task_error,
        task_files, task_idx, task_no, total_tasks):
    """Close a finished task: timer, outputs, memory and continuation frame."""
    if not task_error:
        completed += 1
        active_task_timer.finish("completed")
        job["last_progress_at"] = time.time()
        current_after = set(os.listdir(out_dir)) if os.path.isdir(out_dir) else set()
        task_outputs = sorted(
            filename
            for filename in current_after - task_before
            if os.path.splitext(filename)[1].lower() in {".mp4", ".webm", ".mkv", ".mov"}
            and "_tmp." not in filename
            and "_multiclip." not in filename
        )
        if task_outputs:
            job["clip_output_files"][task_idx] = task_outputs[-1]
        print(f"\n  Task {task_no} completed")

        # Free VRAM between clips to prevent OOM on long pipelines
        if is_multiclip and task_idx + 1 < total_tasks:
            gc.collect()
            torch.cuda.empty_cache()

        # Multi-clip continuation: if next clip has no start image,
        # extract last frame from this clip's output as its start image
        if is_multiclip and task_idx + 1 < total_tasks:
            next_task = queue[task_idx + 1]
            next_params = next_task.get('params', {})
            if next_params.pop("_continuation", False):
                try:
                    continuation_tail_skip = max(
                        0,
                        int(next_params.pop(
                            "_continuation_tail_skip", 8,
                        )),
                    )
                except (TypeError, ValueError):
                    continuation_tail_skip = 8
                # Find the latest video explicitly registered by
                # this task; a shared-folder diff can pick up a
                # concurrent dashboard operation's media.
                video_exts = {".mp4", ".webm", ".mkv", ".mov"}
                latest_video = None
                for output_path in reversed(task_files):
                    if os.path.splitext(output_path)[1].lower() in video_exts:
                        latest_video = output_path
                        if not os.path.isabs(latest_video):
                            latest_video = os.path.join(
                                out_dir, latest_video,
                            )
                        latest_video = os.path.realpath(latest_video)
                        if (
                            os.path.normcase(os.path.dirname(latest_video))
                            != os.path.normcase(os.path.realpath(out_dir))
                            or not os.path.isfile(latest_video)
                        ):
                            latest_video = None
                            continue
                        break
                if latest_video:
                    try:
                        from PIL import Image as PILImage
                        import decord
                        vr = decord.VideoReader(latest_video)
                        # LTX-2 skips its distortion-prone tail;
                        # bounded H3 continuations use the true
                        # final frame (the model does not trim one).
                        safe_idx = max(
                            0,
                            len(vr) - continuation_tail_skip - 1,
                        )
                        last_frame = vr[safe_idx].asnumpy()
                        del vr
                        frame_img = PILImage.fromarray(last_frame)
                        # Save as temp file for the next task
                        cont_path = os.path.join(out_dir, f"_continuation_{task_no}.png")
                        frame_img.save(cont_path)
                        next_params["image_start"] = cont_path
                        next_params["image_prompt_type"] = "S" + (next_params.get("image_prompt_type", "") or "")
                        next_task["start_image_data"] = frame_img
                        print(f"  [Continuation] Extracted last frame for clip {task_no + 1}")
                    except Exception as e:
                        print(f"  [Continuation] Failed to extract frame: {e}")
    else:
        active_task_timer.finish("failed")
    return completed


def _run_generation_collect(st):
    """Clean up, publish the files the run produced and honour a cancel."""
    _write_output_sidecars, before, cancelled = st._write_output_sidecars, st.before, st.cancelled
    clip_output_files, defer_output_publication = st.clip_output_files, st.defer_output_publication
    gen, job, join_output_file, out_dir = st.gen, st.job, st.join_output_file, st.out_dir
    # Clean up continuation temp files
    if os.path.isdir(out_dir):
        for f in os.listdir(out_dir):
            if f.startswith("_continuation_") and f.endswith(".png"):
                try:
                    os.remove(os.path.join(out_dir, f))
                except Exception:
                    pass

    # Publish any files that finished before an abort. Director waits
    # for this worker to settle and persists these partial outputs.
    new_files = []
    if os.path.isdir(out_dir):
        new_files = collect_job_outputs(
            gen,
            out_dir,
            before,
            allow_legacy_fallback=not bool(
                job["params"].get("_director_pipeline_id")
            ),
        )
        record_job_outputs(
            job,
            [] if defer_output_publication else new_files,
            clip_output_files=(
                None
                if defer_output_publication
                else clip_output_files
            ),
            join_output_file=(
                None
                if defer_output_publication
                else join_output_file
            ),
        )
        if not defer_output_publication:
            _write_output_sidecars(new_files)

    if cancelled or is_cancel_requested(job):
        return False
    st.new_files = new_files
    return _run_generation_finalize(st)
