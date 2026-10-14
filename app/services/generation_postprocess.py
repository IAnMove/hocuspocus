"""Film grain and spatial upsampling of an already-saved video.

Launch keeps the names the worker calls. ``wgp``, ``os``, ``time`` and
``is_cancel_requested`` are read from launch's globals at call time, and so
is ``_chunked_flashvsr_upscale``, which stays a launch name until that pass
moves. A test that patches any of those names on the launch module is seen.
"""
from __future__ import annotations

from services.generation_launch_binding import bindable

wgp = bindable("wgp")
os = bindable("os")
time = bindable("time")
is_cancel_requested = bindable("is_cancel_requested")
_chunked_flashvsr_upscale = bindable("_chunked_flashvsr_upscale")


def _apply_film_grain_to_file(video_path: str, intensity: float, saturation: float):
    """Apply film grain to an already-saved video file (post-generation).

    Reads frames with decord, applies grain on GPU if available, re-encodes
    in-place using the same codec settings.

    decord bridge state is restored to 'native' in a finally so subsequent
    code paths that index a VideoReader expecting decord.NDArray
    (`.asnumpy()`) — notably the retake pipeline at ltx2.py — don't break.
    Bug history: setting the bridge here without restoring caused every
    retake AFTER any film-grain-bearing generation to fail with
    `'Tensor' object has no attribute 'asnumpy'`. The retake side now
    has a defensive helper for the same case, but cleaning up here is
    the proper fix at the source.
    """
    import torch
    import decord
    from postprocessing.film_grain import add_film_grain
    from shared.utils.audio_video import save_video
    decord.bridge.set_bridge('torch')
    try:
        return _apply_film_grain_to_file_impl(video_path, intensity, saturation,
                                              torch=torch, decord=decord,
                                              add_film_grain=add_film_grain,
                                              save_video=save_video)
    finally:
        # Always restore decord's default bridge so downstream readers
        # (retake, director renderers, etc.) get decord.NDArray results.
        try:
            decord.bridge.set_bridge('native')
        except Exception:
            pass


def _apply_film_grain_to_file_impl(video_path: str, intensity: float, saturation: float,
                                   *, torch, decord, add_film_grain, save_video):
    """Body of _apply_film_grain_to_file. Extracted so the bridge-restore
    finally above can wrap the entire body cleanly without re-indenting
    the existing implementation."""

    reader = decord.VideoReader(video_path)
    fps = round(reader.get_avg_fps())
    # Read all frames as uint8 tensor [F, H, W, C]
    frames = reader.get_batch(range(len(reader)))
    # Rearrange to [C, F, H, W] as expected by add_film_grain
    frames = frames.permute(3, 0, 1, 2)
    # Free GPU memory from the generation model before using it for film grain
    if torch.cuda.is_available():
        import gc
        gc.collect()
        torch.cuda.empty_cache()
    # Try GPU first, fall back to CPU if OOM
    try:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        frames_dev = frames.to(device)
        frames = add_film_grain(frames_dev, intensity, saturation).cpu()
        del frames_dev
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except torch.cuda.OutOfMemoryError:
        print("  [Film Grain] GPU OOM, falling back to CPU")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        frames = add_film_grain(frames, intensity, saturation)
    # Check if source has audio track to preserve it
    has_audio = False
    audio_tmp = None
    try:
        import subprocess
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=10
        )
        has_audio = 'audio' in probe.stdout
        if has_audio:
            import tempfile
            audio_tmp = tempfile.mktemp(suffix='.aac')
            subprocess.run(
                ['ffmpeg', '-y', '-i', video_path, '-vn', '-acodec', 'copy', audio_tmp],
                capture_output=True, timeout=60
            )
    except Exception:
        has_audio = False
    # Save back — save_video expects [B, C, F, H, W] for the uint8 fast path
    codec_type = wgp.server_config.get("video_output_codec", "libx264_8")
    container = wgp.server_config.get("video_container", "mp4")
    tmp_path = video_path + ".grain_tmp." + container
    # frames is [C, F, H, W] uint8 — save_video has a uint8 fast path (no normalize needed)
    save_video(tensor=frames.unsqueeze(0), save_file=tmp_path, fps=fps, nrow=1,
               normalize=False, codec_type=codec_type, container=container)
    def _replace_with_retry(src, dst, max_retries=5):
        """Replace file with retry loop for Windows file locking."""
        import gc
        for attempt in range(max_retries):
            try:
                os.replace(src, dst)
                return
            except (PermissionError, OSError) as e:
                if attempt < max_retries - 1:
                    gc.collect()
                    time.sleep(1)
                else:
                    raise

    # Mux audio back if present
    if has_audio and audio_tmp and os.path.exists(audio_tmp):
        try:
            import subprocess
            muxed_path = video_path + ".muxed." + container
            subprocess.run(
                ['ffmpeg', '-y', '-i', tmp_path, '-i', audio_tmp, '-c:v', 'copy', '-c:a', 'aac', '-shortest', muxed_path],
                capture_output=True, timeout=120
            )
            _replace_with_retry(muxed_path, video_path)
            os.remove(tmp_path)
        except Exception:
            _replace_with_retry(tmp_path, video_path)
        finally:
            if os.path.exists(audio_tmp):
                os.remove(audio_tmp)
    else:
        _replace_with_retry(tmp_path, video_path)


def _apply_spatial_upsampling_to_file(video_path: str, method: str, job: dict = None):
    """Upscale an already-saved video file IN PLACE (post-generation pass).

    Used to defer FlashVSR from the per-sliding-window inline path to a
    whole-file pass after generation: FlashVSR is a temporal model, and
    per-window application resets its state at every window boundary
    (visible detail/texture "pop" at the seams). Running on the assembled
    video avoids that — and stops FlashVSR from competing with the
    diffusion model for VRAM between windows.

    Thin wrapper over _chunked_flashvsr_upscale: re-muxes the original
    audio (e.g. LTX-2's generated track) onto the upscaled video and
    replaces the file (same name) so gallery entries and sidecar metadata
    keep pointing at the right clip — mirroring
    _apply_film_grain_to_file's in-place contract. Raises on failure; the
    caller treats it as a non-fatal warning and keeps the original.
    """
    audio_tracks, audio_metadata = wgp.extract_audio_tracks(video_path)
    tmp_video = None
    tmp_muxed = None
    try:
        abort_check = (
            (lambda: is_cancel_requested(job)) if job is not None else None
        )
        tmp_video = _chunked_flashvsr_upscale(
            video_path, method, job=job, abort_check=abort_check,
        )
        if tmp_video is None:
            raise RuntimeError("FlashVSR upscale was aborted")
        if callable(abort_check) and abort_check():
            raise RuntimeError("FlashVSR upscale was aborted")
        if audio_tracks:
            container = wgp.server_config.get("video_container", "mp4")
            tmp_muxed = video_path + f".upscale_mux.{container}"
            wgp.combine_video_with_audio_tracks(tmp_video, audio_tracks, tmp_muxed, audio_metadata=audio_metadata)
            if callable(abort_check) and abort_check():
                raise RuntimeError("FlashVSR upscale was aborted")
            os.replace(tmp_muxed, video_path)
            tmp_muxed = None  # consumed by the replace
        else:
            if callable(abort_check) and abort_check():
                raise RuntimeError("FlashVSR upscale was aborted")
            os.replace(tmp_video, video_path)
            tmp_video = None  # consumed by the replace
    finally:
        for leftover in (tmp_video, tmp_muxed):
            if leftover and os.path.isfile(leftover):
                try:
                    os.remove(leftover)
                except OSError:
                    pass
        wgp.cleanup_temp_audio_files(audio_tracks)
