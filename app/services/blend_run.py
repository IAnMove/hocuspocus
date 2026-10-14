"""The blend worker.

The function body is the one that used to live in ``_launch_runtime``.
Launch hands this module the objects it owns once, through :func:`bind`.
The generation worker is defined further down in launch, so launch passes
a forwarder that calls launch's ``_run_generation``.
"""
import os

from services.job_lifecycle import (
    finish_job,
    is_cancel_requested,
    record_job_outputs,
    register_abort_state,
    unregister_abort_state,
    update_job,
)

# Bound by bind(); None until the full server binds them.
_jobs = None
_active_gen_states = None
_workspace_dir = None
_run_generation = None


def bind(*, jobs, active_gen_states, workspace_dir, run_generation):
    """Take the launch objects this module reads. Launch calls this once, after it defines them."""
    globals().update(
        _jobs=jobs,
        _active_gen_states=active_gen_states,
        _workspace_dir=workspace_dir,
        _run_generation=run_generation,
    )


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
