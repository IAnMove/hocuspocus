"""The end of a generation run: post-processing passes and the hand-over.

Part of the generation worker (``services.generation_worker``). The functions are the bodies that
``_run_generation`` and its phases had in ``app/_launch_runtime.py``, moved without edits. The objects
they use from the full server are injected by ``bind`` (called by ``bind_generation_worker``) and are
the same objects the rest of the server uses; this module does not import WanGP, a router or
``_launch_runtime``.
"""

import gc
import os
import time
import traceback
from services.job_lifecycle import finish_job, record_job_outputs, update_job

# Injected by bind(); None until the full server binds them.
_apply_film_grain_to_file = None
_apply_spatial_upsampling_to_file = None
_build_recast_adaptive_mask = None
_render_recast_mask_locked_video = None
wgp = None


def bind(**names):
    """Take the full server's objects this module uses (see bind_generation_worker)."""
    global _apply_film_grain_to_file, _apply_spatial_upsampling_to_file, _build_recast_adaptive_mask
    global _render_recast_mask_locked_video, wgp
    _apply_film_grain_to_file = names["_apply_film_grain_to_file"]
    _apply_spatial_upsampling_to_file = names["_apply_spatial_upsampling_to_file"]
    _build_recast_adaptive_mask = names["_build_recast_adaptive_mask"]
    _render_recast_mask_locked_video, wgp = names["_render_recast_mask_locked_video"], names["wgp"]


def _run_generation_finalize(st):
    """Post-process the produced files (outpaint, recast, upscale, grain, voice)."""
    out_dir = st.out_dir
    if os.path.isdir(out_dir):
        return _run_generation_outpaint(st)
    return _run_generation_finish(st)


def _run_generation_outpaint(st):
    """Outpaint pass: restore the source audio and pixels with ffmpeg."""
    _write_output_sidecars, clip_output_files = st._write_output_sidecars, st.clip_output_files
    job, new_files, out_dir, raw_params = st.job, st.new_files, st.out_dir, st.raw_params
    success = st.success
    # Post-generation outpaint cleanup: combines two operations
    # in a single ffmpeg invocation so we touch the output mp4
    # only once.
    #
    # 1. SOURCE-AREA OVERLAY (lip-sync drift fix). The IC-LoRA
    #    outpaint preserves the source rectangle only
    #    approximately — each window the model regenerates
    #    source pixels with strong conditioning toward the
    #    input, but adds tiny motion variation. Across multiple
    #    sliding windows that drift compounds (each window's
    #    prefix conditioning is the previous window's already
    #    slightly-drifted output), causing visible lip offset
    #    on long talking clips. Hard-overlaying source pixels
    #    on the source rectangle fixes this — the model still
    #    owns the outpainted padding regions.
    #
    # 2. SOURCE-AUDIO MUX. LTX-2 distilled always synthesizes
    #    a fresh audio track via its audio decoder, which
    #    replaces the source audio with unrelated synthetic
    #    audio. We replace it with the source clip's audio.
    #
    # Both ops run BEFORE film grain so film grain operates on
    # the audio-correct, source-locked file (film grain re-
    # encodes video so muxed audio is preserved).
    #
    # Windows file-lock note: the UI has often already opened
    # the freshly-saved mp4 over HTTP for streaming preview by
    # the time we get here. FastAPI's FileResponse does NOT
    # pass FILE_SHARE_DELETE, so os.replace into the live file
    # fails with PermissionError until the stream finishes.
    # We track replace success explicitly and on hard failure
    # promote the post-processed copy to a sibling filename
    # (`_with_source_audio.mp4`), updating job["output_files"]
    # so the UI shows the corrected version.
    _do_audio = bool(raw_params.get("_outpaint_preserve_audio"))
    _do_overlay = bool(raw_params.get("_outpaint_lock_source_pixels"))
    _do_trim = bool(raw_params.get("_outpaint_trim_smear"))
    _trim_boundary = int(raw_params.get("_outpaint_smear_boundary_frame", 0))
    _trim_count = int(raw_params.get("_outpaint_smear_count", 0))
    if success and (_do_audio or _do_overlay or _do_trim) and raw_params.get("_outpaint_source_video"):
        src_video = raw_params.get("_outpaint_source_video")
        if src_video and os.path.isfile(src_video):
            _candidates = _run_generation_outpaint_candidates(new_files)
                # Allow the surrounding 'if' chain to fall through
            # Process only the final (latest-timestamp) canonical save.
            # Iterate the single-element list so the existing per-fname logic
            # (ffmpeg, os.replace, fallback) below still runs as written.
            for fname in _candidates[-1:]:
                out_video = os.path.join(out_dir, fname)
                try:
                    import subprocess
                    # Probe source audio availability
                    src_has_audio = False
                    if _do_audio:
                        probe = subprocess.run(
                            ["ffprobe", "-v", "quiet", "-select_streams", "a",
                             "-show_entries", "stream=codec_type", "-of", "csv=p=0", src_video],
                            capture_output=True, text=True, timeout=10,
                        )
                        src_has_audio = bool(probe.stdout.strip())
                        if not src_has_audio:
                            print(f"  [Outpaint] Source has no audio — keeping generated track on {fname}")

                    muxed_path = out_video.rsplit(".", 1)[0] + "_post." + out_video.rsplit(".", 1)[1]

                    _do_overlay, cmd = _run_generation_outpaint_command(
                            _do_audio, _do_overlay, _do_trim, _trim_boundary, _trim_count,
                            muxed_path, out_video, raw_params, src_has_audio, src_video, subprocess)

                    # Skip if there's truly nothing to do
                    if not _do_trim and not _do_overlay and not (_do_audio and src_has_audio):
                        continue

                    op_label = []
                    if _do_trim: op_label.append("smear-trim")
                    if _do_overlay: op_label.append("source-overlay")
                    if _do_audio and src_has_audio: op_label.append("source-audio")
                    op_str = "+".join(op_label) or "noop"

                    # Re-encode for sliding-window 1425-frame outputs
                    # can take 30-60s at 720p — give plenty of timeout.
                    mux_result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                    if not (mux_result.returncode == 0 and os.path.isfile(muxed_path)):
                        print(f"  [Outpaint {op_str}] ffmpeg failed: {mux_result.stderr[:300]}")
                        if os.path.isfile(muxed_path):
                            try: os.remove(muxed_path)
                            except OSError: pass
                        continue

                    # Try os.replace into the canonical filename.
                    replaced = False
                    last_err = None
                    for _retry in range(15):  # up to ~15s
                        try:
                            os.replace(muxed_path, out_video)
                            replaced = True
                            break
                        except PermissionError as pe:
                            last_err = pe
                            gc.collect()
                            time.sleep(1)

                    if replaced:
                        print(f"  [Outpaint {op_str}] Applied to {fname}")
                        continue

                    # Hard fallback: promote post-processed copy
                    # to sibling final filename, swap in
                    # new_files. UI ends up pointing at the
                    # corrected version.
                    final_name = out_video.rsplit(".", 1)[0] + "_with_source_audio." + out_video.rsplit(".", 1)[1]
                    try:
                        os.replace(muxed_path, final_name)
                    except OSError as e:
                        print(f"  [Outpaint {op_str}] WARN: could not finalize: {e}")
                        if os.path.isfile(muxed_path):
                            try: os.remove(muxed_path)
                            except OSError: pass
                        continue
                    try:
                        os.remove(out_video)
                    except OSError:
                        pass
                    final_basename = os.path.basename(final_name)
                    new_files = [f if f != fname else final_basename for f in new_files]
                    for clip_index, clip_filename in list(
                        clip_output_files.items()
                    ):
                        if clip_filename == fname:
                            clip_output_files[clip_index] = final_basename
                    record_job_outputs(
                        job,
                        [final_basename],
                        clip_output_files=clip_output_files,
                    )
                    _write_output_sidecars([final_basename])
                    if not update_job(job, output_files=new_files):
                        return False
                    print(f"  [Outpaint {op_str}] Original mp4 locked ({last_err}); promoted post copy → {final_basename}")
                except Exception as outpaint_post_err:
                    print(f"  [Outpaint] Post-process error (non-fatal): {outpaint_post_err}")
    st.new_files = new_files
    return _run_generation_recast(st)


def _run_generation_outpaint_candidates(new_files):
    """Pick the canonical video to post-process."""
    video_exts = {".mp4", ".webm", ".mkv", ".mov"}
    # Sliding-window outpaint produces ONE complete cumulative mp4
    # per window (e.g. 4 windows → 4 timestamped saves: 473→937→1401→1424
    # frames). The post-process should only run on the FINAL save,
    # not every per-window intermediate. Pick the last canonical mp4
    # by sorted order — wgp prefixes filenames with timestamps so
    # alphabetic sort = chronological. Skip _tmp.mp4 (intermediate
    # save_path_tmp leftover) and our own _with_source_audio.mp4
    # (in case of re-runs).
    _candidates = []
    for fname in sorted(new_files):
        ext = os.path.splitext(fname)[1].lower()
        if ext not in video_exts:
            continue
        if fname.endswith("_tmp" + ext):
            continue
        if "_with_source_audio" in fname or fname.endswith("_post" + ext):
            continue
        _candidates.append(fname)
    if not _candidates:
        print(f"  [Outpaint] No canonical video output to post-process")
    return _candidates


def _run_generation_outpaint_command(
        _do_audio, _do_overlay, _do_trim, _trim_boundary, _trim_count, muxed_path, out_video,
        raw_params, src_has_audio, src_video, subprocess):
    """Build the ffmpeg command for the outpaint cleanup."""
    # Build ffmpeg command. Three modes:
    #   - overlay+audio: scale source, overlay on output, mux source audio
    #   - overlay only: scale source, overlay on output, keep generated audio
    #   - audio only: copy video, mux source audio
    cmd = ["ffmpeg", "-y", "-i", out_video, "-i", src_video]
    if _do_overlay:
        ow = int(raw_params.get("_outpaint_overlay_w", 0))
        oh = int(raw_params.get("_outpaint_overlay_h", 0))
        ox = int(raw_params.get("_outpaint_overlay_x", 0))
        oy = int(raw_params.get("_outpaint_overlay_y", 0))
        if ow <= 0 or oh <= 0:
            # Bad coords — fall through to audio-only path
            _do_overlay = False

    # Decide what filter graph we need. Modes:
    #
    #   smear-trim only: cut N frames at boundary 1 of
    #     output video, mux source audio (no cuts —
    #     source audio aligns with the trimmed video
    #     because the smear lag was constant from that
    #     point onward).
    #
    #   audio mux only: copy video, replace audio with
    #     source audio.
    #
    #   overlay (legacy/opt-in): scale source video,
    #     feathered alpha-overlay onto output, mux
    #     source audio.
    #
    # Trim takes priority over overlay if both are on,
    # since trim is what fixes the actual lip-sync bug.
    if _do_trim and _trim_boundary > 0 and _trim_count > 0:
        # Read fps from output to compute timestamps.
        fps_probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", out_video],
            capture_output=True, text=True, timeout=10,
        )
        _fps = 25.0
        _fps_str = fps_probe.stdout.strip()
        if "/" in _fps_str:
            _num, _den = _fps_str.split("/")
            if _den and float(_den) != 0:
                _fps = float(_num) / float(_den)
        cut_start = _trim_boundary / _fps
        cut_end = (_trim_boundary + _trim_count) / _fps
        # ffmpeg trim+concat: keep [0, cut_start) and [cut_end, end).
        # asetpts on source audio resets PTS so it starts at 0
        # in the output timeline; -shortest will clamp the audio
        # to the (now shorter by N frames) trimmed video duration.
        filter_str = (
            f"[0:v]trim=0:{cut_start:.6f},setpts=PTS-STARTPTS[v0];"
            f"[0:v]trim={cut_end:.6f},setpts=PTS-STARTPTS[v1];"
            f"[v0][v1]concat=n=2:v=1[outv]"
        )
        cmd += ["-filter_complex", filter_str, "-map", "[outv]"]
        cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"]
        if _do_audio and src_has_audio:
            cmd += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-an"]  # drop audio if we can't replace it
    elif _do_overlay:
        cw = int(raw_params.get("_outpaint_canvas_w", 0)) or (ox + ow)
        ch = int(raw_params.get("_outpaint_canvas_h", 0)) or (oy + oh)
        fade_top = oy > 0
        fade_bottom = (oy + oh) < ch
        fade_left = ox > 0
        fade_right = (ox + ow) < cw
        feather = 24
        distances = []
        if fade_top: distances.append("Y")
        if fade_bottom: distances.append("(H-Y)")
        if fade_left: distances.append("X")
        if fade_right: distances.append("(W-X)")
        if distances:
            d_min = distances[0]
            for d in distances[1:]:
                d_min = f"min({d_min},{d})"
            alpha_expr = (
                f"if(gt({d_min},{feather}),255,"
                f"255*{d_min}/{feather})"
            )
            filter_str = (
                f"[1:v]scale={ow}:{oh}:flags=lanczos,setsar=1,format=yuva420p,"
                f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':"
                f"a='{alpha_expr}'[s];"
                f"[0:v][s]overlay={ox}:{oy}:shortest=1:format=auto[outv]"
            )
        else:
            filter_str = (
                f"[1:v]scale={ow}:{oh}:flags=lanczos,setsar=1[s];"
                f"[0:v][s]overlay={ox}:{oy}:shortest=1[outv]"
            )
        cmd += ["-filter_complex", filter_str, "-map", "[outv]"]
        cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"]
        if _do_audio and src_has_audio:
            cmd += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-map", "0:a?", "-c:a", "copy"]
    else:
        # Audio mux only — no video filter
        cmd += ["-map", "0:v:0", "-c:v", "copy"]
        if _do_audio and src_has_audio:
            cmd += ["-map", "1:a:0", "-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-map", "0:a?", "-c:a", "copy"]

    cmd += ["-shortest", muxed_path]
    return _do_overlay, cmd


def _run_generation_recast(st):
    """Recast pass: protect the people around the replaced target."""
    job, new_files, out_dir, raw_params = st.job, st.new_files, st.out_dir, st.raw_params
    success = st.success
    # Recast target lock: SCAIL-2 regenerates the full frame even
    # in Replace mode, so a strong identity can leak into a nearby
    # person. Trace the actual generated replacement, match it to
    # the approved source target by overlap, and restore the source
    # everywhere outside the union of the old and new silhouettes.
    if success and raw_params.get("_recast_protect_bystanders"):
        source_video = raw_params.get("_recast_source_video")
        mask_video = raw_params.get("video_mask")
        video_exts = {".mp4", ".webm", ".mkv", ".mov"}
        candidates = [
            name for name in new_files
            if os.path.splitext(name)[1].lower() in video_exts
        ]
        if source_video and mask_video and candidates:
            fname = candidates[-1]
            generated_video = os.path.join(out_dir, fname)
            protected_path = None
            adaptive_mask_dir = None
            try:
                if not update_job(
                    job,
                    message="Preparing adaptive Recast protection...",
                    phase="Tracing generated replacement",
                ):
                    return False

                # SAM3 needs its own CUDA headroom. Recast is
                # already rendered, so release the generation model
                # before tracing the finished replacement. The next
                # generation reloads it normally.
                if (
                    getattr(wgp, "wan_model", None) is not None
                    or getattr(wgp, "offloadobj", None) is not None
                ):
                    print("  [Recast] Releasing generation model for adaptive protection")
                    wgp.release_model()

                import tempfile
                adaptive_mask_dir = tempfile.mkdtemp(
                    prefix="maestro-recast-protect-",
                )
                protection_progress = {"bucket": -1}

                def _adaptive_protection_progress(done, total):
                    percent = min(
                        100,
                        max(0, int(round(100 * float(done) / max(1, total)))),
                    )
                    bucket = percent // 5
                    if bucket == protection_progress["bucket"]:
                        return
                    protection_progress["bucket"] = bucket
                    if not update_job(
                        job,
                        message=f"Tracing generated replacement... {percent}%",
                        phase="Tracing generated replacement",
                    ):
                        raise InterruptedError("Recast protection was cancelled")

                adaptive_mask = _build_recast_adaptive_mask(
                    generated_video,
                    mask_video,
                    raw_params.get("edit_recast_person_count", 1),
                    adaptive_mask_dir,
                    progress_callback=_adaptive_protection_progress,
                )
                if not update_job(
                    job,
                    message="Protecting people outside the generated replacement...",
                    phase="Protecting surrounding people",
                ):
                    return False
                protected_path = _render_recast_mask_locked_video(
                    source_video, adaptive_mask, generated_video,
                )
                replaced = False
                last_error = None
                for _retry in range(15):
                    try:
                        os.replace(protected_path, generated_video)
                        replaced = True
                        break
                    except PermissionError as exc:
                        last_error = exc
                        gc.collect()
                        time.sleep(1)
                if replaced:
                    print(f"  [Recast] Protected non-target pixels in {fname}")
                else:
                    stem, extension = os.path.splitext(generated_video)
                    final_path = f"{stem}_target_locked{extension}"
                    os.replace(protected_path, final_path)
                    protected_path = None
                    final_name = os.path.basename(final_path)
                    new_files = [
                        final_name if name == fname else name
                        for name in new_files
                    ]
                    record_job_outputs(job, new_files)
                    if not update_job(job, output_files=new_files):
                        return False
                    print(
                        "  [Recast] Original output was locked "
                        f"({last_error}); published {final_name}"
                    )
            except InterruptedError as recast_protect_cancelled:
                print(f"  [Recast] {recast_protect_cancelled}")
                return False
            except Exception as recast_protect_error:
                print(
                    "  [Recast] Warning: target-mask protection "
                    f"failed; keeping generated frame: {recast_protect_error}"
                )
                traceback.print_exc()
            finally:
                if protected_path and os.path.isfile(protected_path):
                    try:
                        os.remove(protected_path)
                    except OSError:
                        pass
                if adaptive_mask_dir:
                    import shutil
                    shutil.rmtree(adaptive_mask_dir, ignore_errors=True)
    st.new_files = new_files
    return _run_generation_video_passes(st)


def _run_generation_video_passes(st):
    """FlashVSR, film grain and voice clone passes."""
    job, new_files, out_dir = st.job, st.new_files, st.out_dir
    pp_film_grain_intensity = st.pp_film_grain_intensity
    pp_film_grain_saturation = st.pp_film_grain_saturation
    pp_spatial_upsampling = st.pp_spatial_upsampling
    pp_voice_clone_enabled, pp_voice_clone_mode = st.pp_voice_clone_enabled, st.pp_voice_clone_mode
    pp_voice_clone_refs, success = st.pp_voice_clone_refs, st.success
    # Post-generation FlashVSR pass — whole-file upscale on the
    # assembled video (see the pop near the top of this function
    # for why this isn't done inline per sliding window). Ordered
    # BEFORE film grain so grain lands on the upscaled pixels (the
    # inline path had the same order), and before voice clone so
    # the audio swap happens on the final video.
    if success and pp_spatial_upsampling:
        video_exts = {".mp4", ".webm", ".mkv"}
        for fname in new_files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in video_exts:
                continue
            video_path = os.path.join(out_dir, fname)
            try:
                if not update_job(
                    job,
                    message=f"Upscaling {fname} (FlashVSR)...",
                    phase="Upscaling",
                ):
                    return False
                print(f"  [Upscale] Applying {pp_spatial_upsampling} to {fname}")
                _apply_spatial_upsampling_to_file(video_path, pp_spatial_upsampling, job=job)
                print(f"  [Upscale] Done: {fname}")
            except Exception as up_err:
                print(f"  [Upscale] Warning: failed on {fname} (keeping original): {up_err}")
                traceback.print_exc()

    # Post-generation film grain pass (applied to output files, not during inference)
    if success and pp_film_grain_intensity > 0:
        video_exts = {".mp4", ".webm", ".mkv"}
        for fname in new_files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in video_exts:
                continue
            video_path = os.path.join(out_dir, fname)
            try:
                if not update_job(
                    job, message=f"Applying film grain to {fname}...",
                ):
                    return False
                print(f"  [Film Grain] Applying to {fname} (intensity={pp_film_grain_intensity}, saturation={pp_film_grain_saturation})")
                _apply_film_grain_to_file(video_path, pp_film_grain_intensity, pp_film_grain_saturation)
                print(f"  [Film Grain] Done: {fname}")
            except Exception as fg_err:
                print(f"  [Film Grain] Warning: failed on {fname}: {fg_err}")
                traceback.print_exc()

    # Post-generation voice clone pass (SeedVC). Replaces 1 or 2
    # voices in the generated video's audio track with user-
    # supplied reference voice(s). Order matters: runs AFTER
    # film grain so the audio replacement happens on the final
    # color-graded video. Video stream is copied through (no
    # re-encode), so film grain is preserved.
    #
    # The voice-clone function leaves the video unchanged on any
    # failure (no audio track, missing refs, SeedVC failure,
    # remux failure) — it's safe to enable speculatively.
    if success and pp_voice_clone_enabled and pp_voice_clone_refs:
        video_exts = {".mp4", ".webm", ".mkv"}
        for fname in new_files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in video_exts:
                continue
            video_path = os.path.join(out_dir, fname)
            try:
                if not update_job(
                    job,
                    message=f"Voice cloning ({pp_voice_clone_mode}) on {fname}...",
                ):
                    return False
                print(f"  [Voice Clone] mode={pp_voice_clone_mode} refs={len(pp_voice_clone_refs)} on {fname}")
                from postprocessing.voice_clone import apply_voice_clone_to_file
                apply_voice_clone_to_file(
                    video_path=video_path,
                    voice_ref_paths=pp_voice_clone_refs,
                    mode=pp_voice_clone_mode,
                )
                print(f"  [Voice Clone] Done: {fname}")
            except Exception as vc_err:
                print(f"  [Voice Clone] Warning: failed on {fname}: {vc_err}")
                traceback.print_exc()
    return _run_generation_audio_and_sidecars(st)


def _run_generation_audio_and_sidecars(st):
    """Dynamic audio normalisation, then refresh the sidecars."""
    _write_output_sidecars = st._write_output_sidecars
    defer_output_publication, job, new_files = st.defer_output_publication, st.job, st.new_files
    out_dir, raw_params, success = st.out_dir, st.raw_params, st.success
    # Post-generation dynamic audio normalization (smooths speaker volume transitions)
    if success and raw_params.get("tts_dynaudnorm"):
        audio_exts = {".wav", ".mp3", ".flac", ".ogg"}
        for fname in new_files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in audio_exts:
                continue
            audio_path = os.path.join(out_dir, fname)
            try:
                if not update_job(
                    job, message="Smoothing speaker volumes...",
                ):
                    return False
                print(f"  [DynAudNorm] Applying to {fname}")
                tmp_path = audio_path + ".dynaudnorm.wav"
                import subprocess
                comp_threshold = raw_params.get("tts_comp_threshold", -25)
                comp_attack = raw_params.get("tts_comp_attack", 5)
                comp_release = raw_params.get("tts_comp_release", 100)
                comp_makeup = raw_params.get("tts_comp_makeup", 4)
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", audio_path,
                     "-af", f"acompressor=threshold={comp_threshold}dB:ratio=3:attack={comp_attack}:release={comp_release}:makeup={comp_makeup},alimiter=limit=0.95",
                     tmp_path],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0 and os.path.isfile(tmp_path):
                    os.replace(tmp_path, audio_path)
                    print(f"  [DynAudNorm] Done: {fname}")
                else:
                    print(f"  [DynAudNorm] ffmpeg failed: {result.stderr[:200]}")
                    if os.path.isfile(tmp_path):
                        os.remove(tmp_path)
            except Exception as dan_err:
                print(f"  [DynAudNorm] Warning: failed on {fname}: {dan_err}")

    # Refresh sidecars after post-processing/renames. Internal
    # shot clips are deleted after shot-aware edit assembly and
    # therefore must never be published as gallery artifacts.
    if not defer_output_publication:
        _write_output_sidecars(new_files)
    return _run_generation_finish(st)


def _run_generation_finish(st):
    """Hand the job over: Finalizing for a deferred caller, else completed or failed."""
    clip_output_files, defer_output_publication = st.clip_output_files, st.defer_output_publication
    finalize, job, join_output_file = st.finalize, st.job, st.join_output_file
    new_files, success = st.new_files, st.success
    if success and not finalize:
        deferred_updates = {}
        if defer_output_publication:
            deferred_updates.update({
                "_internal_output_files": list(new_files),
                "_internal_clip_output_files": dict(
                    clip_output_files,
                ),
                "_internal_join_output_file": join_output_file,
            })
        return update_job(
            job,
            progress=99,
            step=0,
            total_steps=0,
            phase="Finalizing",
            message="Finalizing...",
            **deferred_updates,
        )

    finish_job(
        job,
        "completed" if success else "failed",
        progress=100 if success else 0,
        step=0,
        total_steps=0,
        phase="",
        message="Done" if success else (job.get("error") or "Generation failed"),
    )
    return success and job.get("status") == "completed"
