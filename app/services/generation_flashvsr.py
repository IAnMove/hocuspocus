"""Chunked FlashVSR upscale of an already-saved video.

Launch keeps the name the worker and the tools router call. ``wgp``, ``os``
and ``update_job`` are read from launch's globals at call time, so a test
that patches them on the launch module is seen. The tools router receives
this function object.
"""
from __future__ import annotations

from services.generation_launch_binding import bindable

wgp = bindable("wgp")
os = bindable("os")
update_job = bindable("update_job")


def _chunked_flashvsr_upscale(video_path: str, method: str, *, job: dict = None, abort_check=None, progress_callback=None):
    """Chunked FlashVSR upscale of a saved video -> tmp VIDEO-ONLY file.

    Shared engine for the post-generation in-place pass
    (_apply_spatial_upsampling_to_file) and Tools -> Upscale
    (_run_tool_upscale).

    LONG videos are processed in bounded-RAM chunks: FlashVSR's output
    accumulates as float32 at full output resolution, so an unchunked
    4-minute 2x upscale tries to allocate 280+ GB of RAM. Each chunk is
    read with an 11-frame overlap and chained through FlashVSR's
    continue_cache (its native tail-handoff for seamless segment
    continuation), encoded to a segment file immediately to free the
    buffer, and the segments are stream-copy concatenated (same encoder
    settings -> frame-accurate). The FlashVSR models are kept resident
    across chunks regardless of the persistence setting, then released
    per the user's setting.

    Returns the tmp file path (NO audio track) — the caller owns audio
    muxing, final placement, and deleting the tmp. Returns None when
    aborted via abort_check. Raises on failure.
    """
    import gc
    import math
    import subprocess
    import torch

    from shared.utils.utils import get_video_info
    from postprocessing.flashvsr.runtime import FLASHVSR_CONTINUE_CACHE_FRAMES

    fps, width, height, total_frames = get_video_info(video_path)
    scale = wgp.flashvsr.scale_for_upsampling(method) or 2.0
    out_h, out_w = max(1, int(height * scale)), max(1, int(width * scale))

    # Direct bridge calls bypass perform_spatial_upsampling, so replicate
    # its live sync of the React Settings panel values (services.*) onto
    # the top-level keys the bridge reads — BEFORE the variant-dependent
    # chunk sizing below.
    _svc = wgp.server_config.get("services", {})
    for _k in ("flashvsr_mode", "flashvsr_topk_ratio", "flashvsr_backend"):
        if _k in _svc:
            wgp.server_config[_k] = _svc[_k]

    # Chunk length bounds the per-chunk output accumulation buffer (~8 GB).
    # tiny-long and full accumulate uint8 (3 B/px) — 4x longer chunks, which
    # also means 4x fewer per-chunk warmups/encodes; plain tiny still
    # accumulates float32 (12 B/px).
    _, _variant, _ = wgp.flashvsr.settings()
    bytes_per_out_frame = 3 * out_h * out_w * (1 if _variant in ("tiny-long", "full") else 4)
    chunk_frames = int(8e9 // max(1, bytes_per_out_frame))
    chunk_frames = max(49, min(chunk_frames, 1200))
    overlap = FLASHVSR_CONTINUE_CACHE_FRAMES
    n_chunks = max(1, math.ceil(max(1, int(total_frames)) / chunk_frames))

    # Free generation-model cache before loading FlashVSR.
    if torch.cuda.is_available():
        gc.collect()
        torch.cuda.empty_cache()

    def _progress(phase, current_step=None, total_steps=None):
        if callable(progress_callback):
            progress_callback(phase, current_step, total_steps)
            return
        if job is None:
            return
        changes = {}
        if phase:
            changes.update(message=str(phase), phase=str(phase))
        try:
            if total_steps:
                changes.update(
                    step=int(current_step or 0),
                    total_steps=int(total_steps),
                )
        except (TypeError, ValueError):
            pass
        if changes:
            update_job(job, **changes)

    output_fps = round(fps)
    container = wgp.server_config.get("video_container", "mp4")
    codec = wgp.server_config.get("video_output_codec", None)

    def _save_segment(frames, path):
        # tiny/tiny-long yield float32 in [-1,1]; the full variant yields
        # uint8 (decode_to_cpu_uint8) which save_video takes un-normalized.
        if frames.dtype == torch.uint8:
            wgp.save_video(tensor=frames[None], save_file=path, fps=output_fps, nrow=1, normalize=False, codec_type=codec, container=container)
        else:
            wgp.save_video(tensor=frames[None], save_file=path, fps=output_fps, nrow=1, normalize=True, value_range=(-1, 1), codec_type=codec, container=container)

    profile = wgp.loaded_profile if wgp.loaded_profile >= 0 else wgp.get_default_profile("video")

    # Keep the FlashVSR models resident across chunks; restore the user's
    # persistence choice (and release if they chose unload) afterwards.
    persistence_orig = wgp.server_config.get("flashvsr_persistence")
    wgp.server_config["flashvsr_persistence"] = wgp.flashvsr.PERSIST_RAM

    segment_paths = []
    concat_list = None
    tmp_video = None
    try:
        written = 0
        seg_idx = 0
        cache = None
        while True:
            if callable(abort_check) and abort_check():
                return None
            ov = overlap if written > 0 else 0
            seg = wgp.get_resampled_video(video_path, written - ov, ov + chunk_frames, fps)
            if seg is None or seg.shape[0] <= ov:
                break
            take_new = int(seg.shape[0]) - ov
            last = take_new < chunk_frames
            if n_chunks > 1:
                if job is not None:
                    if not update_job(
                        job,
                        message=f"Upscaling chunk {seg_idx + 1}/{n_chunks} (FlashVSR)...",
                    ):
                        return None
                print(f"  [Upscale] Chunk {seg_idx + 1}/{n_chunks}: frames {written}-{written + take_new - 1} (+{ov} overlap)")
            seg = seg.permute(-1, 0, 1, 2)  # [F,H,W,C] -> [C,F,H,W]
            out, cache = wgp.flashvsr.upscale(
                seg, method, seed=-1,
                continue_cache=cache, return_continue_cache=not last,
                vae_tile_size=None, process_files=wgp.process_files_def,
                vae_config=wgp.vae_config, init_pipe=wgp.init_pipe,
                profile=profile, still_image=False,
                abort_callback=abort_check, progress_callback=_progress,
            )
            seg = None
            if out is None:
                if callable(abort_check) and abort_check():
                    return None
                raise RuntimeError("FlashVSR returned no frames")
            if ov:
                # First `ov` output frames replicate the previous segment's
                # tail (continue_cache contract) — already encoded there.
                out = out[:, ov:]
            seg_path = video_path + f".upseg{seg_idx:03d}.{container}"
            _save_segment(out, seg_path)
            segment_paths.append(seg_path)
            out = None
            written += take_new
            seg_idx += 1
            if last:
                break
        if callable(abort_check) and abort_check():
            return None
        if not segment_paths:
            raise RuntimeError("No frames read from source video")

        if len(segment_paths) == 1:
            tmp_video = segment_paths[0]
            segment_paths = []
        else:
            if job is not None:
                if not update_job(job, message="Joining upscaled segments..."):
                    return None
            if callable(abort_check) and abort_check():
                return None
            concat_list = video_path + ".upconcat.txt"
            with open(concat_list, "w", encoding="utf-8") as f:
                for p in segment_paths:
                    f.write("file '" + os.path.abspath(p).replace("\\", "/").replace("'", "'\\''") + "'\n")
            tmp_video = video_path + f".upscale_tmp.{container}"
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", tmp_video],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode != 0 or not os.path.isfile(tmp_video):
                raise RuntimeError(f"ffmpeg concat failed: {result.stderr[-400:]}")

        if callable(abort_check) and abort_check():
            return None
        result_path = tmp_video
        tmp_video = None  # ownership transfers to the caller
        return result_path
    finally:
        wgp.server_config["flashvsr_persistence"] = persistence_orig if persistence_orig is not None else wgp.flashvsr.PERSIST_UNLOAD
        if persistence_orig != wgp.flashvsr.PERSIST_RAM:
            try:
                wgp.release_flashvsr_vram()
            except Exception:
                pass
        for leftover in segment_paths + [concat_list, tmp_video]:
            if leftover and os.path.isfile(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
