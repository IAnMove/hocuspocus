"""POST /api/v1/blend.

The handler body is the one that used to live in ``_launch_runtime``; it is
the served endpoint, so the route table names this file. Launch hands this
module the objects it owns once, as the arguments of
:func:`create_blend_router`. The generation worker is defined further down
in launch, so launch passes a forwarder that calls launch's
``_run_generation``.
"""
import os
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request

from services import execution_mode
from services.blend_run import _run_blend_generation

# Set by create_blend_router(); None until the full server mounts the route.
_get_active_workspace = None
_workspace_dir = None
_register_manual_generation_job = None
_generation_job_acceptance = None
_run_generation = None


async def blend_endpoint(request: Request):
    """Blend two clips with an AI-generated transition (Sora-1 style overlap).

    For `overlap` mode: the last `overlap_sec` of Clip A blends with the
    first `overlap_sec` of Clip B during a shared window. Total output
    duration = len(A) + len(B) - overlap_sec.

    Pipeline: sparse keyframe injection — A's last N frames anchored at
    blend positions 1..N, B's first N frames anchored at blend positions
    (transition-N+1)..transition. Middle is free for the model to invent.
    Uses `video_prompt_type="FI"` (image_refs + frames_positions), the same
    mechanism Continue/Extend and the Director/music-video flows use for
    motion-preserving keyframe anchoring.

    Body: {
        clip_a_path: str, clip_b_path: str,
        prompt?: str — describe the *transition itself*, not just "smooth blend".
        model_type: str,
        blend_mode?: 'insert'|'overlap', overlap_sec?: float (default 3),
        motion_prefix_sec?: float (default 1.0) — seconds of A's overlap-zone
            start used as `video_source`, switching the pipeline from SE to
            VE mode. Gives the model real motion history to extrapolate so
            rotation/pan direction continues from A. Set to 0 for pure SE
            (single still-frame anchor). Capped at 80% of overlap_sec.
        motion_suffix_sec?: float (default 1.0) — symmetric counterpart to
            motion_prefix_sec. Feeds B's overlap-zone end as `video_end`
            via a keyframe-injection path in ltx2.py, giving the model B's
            actual motion trajectory leading into the landing frame. Without
            this, the joggers (for ex.) tend to "slow-mo" into the anchor
            then hard-cut to real-speed B_post. Capped at 80% of overlap_sec.
        anchor_frames?: int (default 0) — optional weak keyframes near the
            edges for extra motion-context. Usually leave 0 with VE mode.
        injection_strength?: float (default 0.4) — strength for those.
        num_inference_steps?: int, guidance_scale?: float, negative_prompt?: str,
        seed?: int, activated_loras?: list, loras_multipliers?: str,
        workspace?: str,
        base_params?: dict — UI passes state.params here so the blend
            inherits progressive_pipeline, stage2_steps, etc. Blend-specific
            fields (image_start/end, resolution, video_length, ...) override.
    }
    """
    body = await request.json()

    clip_a_path = body.get("clip_a_path")
    clip_b_path = body.get("clip_b_path")
    if not clip_a_path or not clip_b_path:
        raise HTTPException(status_code=400, detail="Both clip_a_path and clip_b_path are required")

    # Resolve paths (may be upload paths)
    for check_dir in [os.path.join(os.getcwd(), "uploads"), _workspace_dir(body.get("workspace"))]:
        if not os.path.isfile(clip_a_path):
            candidate = os.path.join(check_dir, os.path.basename(clip_a_path))
            if os.path.isfile(candidate):
                clip_a_path = candidate
        if not os.path.isfile(clip_b_path):
            candidate = os.path.join(check_dir, os.path.basename(clip_b_path))
            if os.path.isfile(candidate):
                clip_b_path = candidate

    if not os.path.isfile(clip_a_path):
        raise HTTPException(status_code=400, detail=f"Clip A not found: {clip_a_path}")
    if not os.path.isfile(clip_b_path):
        raise HTTPException(status_code=400, detail=f"Clip B not found: {clip_b_path}")

    model_type = body.get("model_type")
    if not model_type:
        raise HTTPException(status_code=400, detail="model_type is required")

    blend_mode = body.get("blend_mode", "overlap")
    overlap_sec = float(body.get("overlap_sec", 3))

    import tempfile
    import math
    import decord
    import numpy as np
    from PIL import Image as PILImage

    temp_dir = tempfile.mkdtemp(prefix="blend_")

    try:
        # ── Probe both clips ─────────────────────────────────────────────
        def _probe(path):
            ext = os.path.splitext(path)[1].lower()
            if ext in (".mp4", ".mkv", ".avi", ".mov", ".webm"):
                vr = decord.VideoReader(path)
                fps = float(vr.get_avg_fps()) or 24.0
                h, w = vr[0].shape[:2]
                return {"is_video": True, "fps": fps, "frames": len(vr), "h": h, "w": w, "reader": vr}
            img = PILImage.open(path).convert("RGB")
            return {"is_video": False, "fps": 24.0, "frames": 1, "h": img.size[1], "w": img.size[0], "image": img}

        info_a = _probe(clip_a_path)
        info_b = _probe(clip_b_path)

        # ── Target geometry (A's native, aligned to 32 for LTX) ──────────
        fps = info_a["fps"]
        # LTX-2 frames schedule: must be >= 17 and (n - 17) % 8 == 0
        raw_frames = max(17, int(round(overlap_sec * fps)))
        transition_frames = 17 + 8 * math.ceil((raw_frames - 17) / 8) if raw_frames > 17 else 17
        # Effective overlap after rounding (for frame-accurate trim/concat)
        overlap_sec_eff = transition_frames / fps

        # Snap resolution to LTX's 32-px alignment
        src_w = (info_a["w"] // 32) * 32
        src_h = (info_a["h"] // 32) * 32
        if src_w <= 0 or src_h <= 0:
            raise HTTPException(status_code=400, detail=f"Clip A resolution too small: {info_a['w']}x{info_a['h']}")

        def _resample_frames(raw_list, target_len, target_w, target_h):
            """Resize + resample a list of RGB np arrays to exactly target_len frames."""
            if not raw_list:
                return [np.zeros((target_h, target_w, 3), dtype=np.uint8)] * target_len
            resized = []
            for f in raw_list:
                if f.shape[0] != target_h or f.shape[1] != target_w:
                    f = np.array(PILImage.fromarray(f).resize((target_w, target_h), PILImage.LANCZOS))
                resized.append(f)
            if len(resized) == target_len:
                return resized
            idx = np.linspace(0, len(resized) - 1, target_len).astype(int)
            return [resized[i] for i in idx]

        # ── Extract A's tail (last overlap_sec_eff seconds) ──────────────
        if info_a["is_video"]:
            src_frames_a = max(1, int(round(overlap_sec_eff * info_a["fps"])))
            start_idx_a = max(0, info_a["frames"] - src_frames_a)
            raw_a = [info_a["reader"][i].asnumpy() for i in range(start_idx_a, info_a["frames"])]
            del info_a["reader"]
        else:
            raw_a = [np.array(info_a["image"])]

        # ── Extract B's head (first overlap_sec_eff seconds) ─────────────
        if info_b["is_video"]:
            src_frames_b = max(1, int(round(overlap_sec_eff * info_b["fps"])))
            end_idx_b = min(src_frames_b, info_b["frames"])
            raw_b = [info_b["reader"][i].asnumpy() for i in range(end_idx_b)]
            del info_b["reader"]
        else:
            raw_b = [np.array(info_b["image"])]

        frames_a = _resample_frames(raw_a, transition_frames, src_w, src_h)
        frames_b = _resample_frames(raw_b, transition_frames, src_w, src_h)

        # ── Anchor frames for seamless concat at both seams ────────────────
        # Correct frame selection for overlap semantics (a):
        #   A_pre = A[0 : L_a - O]          → last frame = A[L_a-O-1]
        #   blend starts at A[L_a - O]       → first blend frame
        #   blend ends   at B[O - 1]         → last blend frame
        #   B_post = B[O : L_b]              → first frame = B[O]
        b_end_path = os.path.join(temp_dir, "b_overlap_end.png")
        PILImage.fromarray(frames_b[-1]).save(b_end_path)

        # ── Motion-prefix mode: video_source from A's overlap-zone start ───
        # Pure SE gives the model only a STILL frame at position 0, so it
        # has no motion context and tends to invent rotation/pan direction
        # arbitrarily (often opposite to A's). Passing K frames of A's
        # overlap tail as `video_source` flips the pipeline into VE mode
        # (Continue/Extend + End-frame), giving the model motion history
        # to extrapolate from — the same mechanism that makes Continue
        # preserve motion well.
        #
        # Those first K frames become the first K frames of the blend
        # output. They are EXACTLY the frames of A's overlap zone that
        # A_pre was going to cut off anyway, so the concat stays frame-
        # perfect (A_pre → blend seam = A[L_a-O-1] → A[L_a-O]).
        # Default 1s of A's overlap-zone start as video_source (VE mode).
        # The "still-frame joggers" regression was caused by image_mode
        # from base_params coercing the pipeline into image-only output,
        # not by VE mode itself.
        motion_prefix_sec = float(body.get("motion_prefix_sec", 1.0))
        motion_prefix_sec = max(0.0, min(motion_prefix_sec, overlap_sec_eff * 0.8))
        K_prefix = int(round(motion_prefix_sec * fps)) if motion_prefix_sec > 0 else 0
        K_prefix = max(0, min(K_prefix, len(frames_a) - 2))  # leave room for generation

        def _write_mp4(path: str, frames: list, fps_val: float):
            import imageio
            _writer = imageio.get_writer(path, fps=fps_val, codec="libx264", quality=9)
            try:
                for f in frames:
                    _writer.append_data(f)
            finally:
                _writer.close()

        video_source_path = None
        a_start_path = None
        if K_prefix > 0:
            video_source_path = os.path.join(temp_dir, "motion_prefix.mp4")
            _write_mp4(video_source_path, frames_a[:K_prefix], fps)
        else:
            # Pure SE fallback: single-frame anchor at blend start
            a_start_path = os.path.join(temp_dir, "a_overlap_start.png")
            PILImage.fromarray(frames_a[0]).save(a_start_path)

        # ── Motion-suffix mode: video_end from B's overlap-zone end ────────
        # Symmetric counterpart to motion_prefix. Placed at the END of the
        # output latent sequence via the new `_append_suffix_entries` path
        # in ltx2.py (VideoConditionByKeyframeIndex at end positions).
        # Gives the model B's actual motion trajectory leading into the
        # landing frame, so the joggers arrive at full speed instead of
        # easing-in to hit a static anchor.
        #
        # Those last K frames become the final K frames of the blend output.
        # They are EXACTLY the frames of B's overlap zone that B_post was
        # going to skip anyway, so the blend → B_post seam stays frame-
        # perfect (blend[N-1] = B[O-1] → B_post[0] = B[O]).
        motion_suffix_sec = float(body.get("motion_suffix_sec", 1.0))
        motion_suffix_sec = max(0.0, min(motion_suffix_sec, overlap_sec_eff * 0.8))
        K_suffix = int(round(motion_suffix_sec * fps)) if motion_suffix_sec > 0 else 0
        # Cap so suffix + prefix don't exceed transition length with no room
        # for AI-invented middle. Leave at least 9 frames (1 latent chunk + 1)
        # for the generator.
        K_suffix = max(0, min(K_suffix, len(frames_b) - 1, transition_frames - K_prefix - 9))

        video_end_path = None
        if K_suffix > 0:
            video_end_path = os.path.join(temp_dir, "motion_suffix.mp4")
            # Last K frames of B's overlap zone, in forward temporal order
            _write_mp4(video_end_path, frames_b[-K_suffix:], fps)

        # ── Optional weak keyframe hints for motion continuity ─────────────
        # Pure SE loses A's rotation and B's stride rhythm (model has no
        # motion context beyond the two endpoints). `anchor_frames > 0`
        # injects a few WEAK keyframes from A's overlap zone (forward in
        # time from image_start) and B's overlap zone (backward in time
        # from image_end), at low injection_strength so they act as hints
        # not hard locks.
        #
        # Default 0 = pure SE (proven to produce great creative bridges).
        # Try 2-3 with injection_strength=0.3 to carry some motion context.
        n_anchors = int(body.get("anchor_frames", 0))
        max_anchors = min(len(frames_a) - 1, len(frames_b) - 1, max(1, transition_frames // 4))
        n_anchors = max(0, min(n_anchors, max_anchors))

        extra_refs = []
        extra_positions = []
        if n_anchors > 0:
            # A-side hints: A frames [1..n_anchors] at blend positions [2..n_anchors+1]
            # (position 1 = image_start = frames_a[0]; these continue A's motion forward)
            for i in range(1, n_anchors + 1):
                p = os.path.join(temp_dir, f"a_hint_{i:02d}.png")
                PILImage.fromarray(frames_a[i]).save(p)
                extra_refs.append(p)
                extra_positions.append(i + 1)

            # B-side hints: B frames [len-2..len-1-n_anchors] at positions [N-1..N-n_anchors]
            # (position N = image_end = frames_b[-1]; these bring B's motion into the end)
            for i in range(1, n_anchors + 1):
                b_idx = len(frames_b) - 1 - i
                if b_idx < 0:
                    break
                p = os.path.join(temp_dir, f"b_hint_{i:02d}.png")
                PILImage.fromarray(frames_b[b_idx]).save(p)
                extra_refs.append(p)
                extra_positions.append(transition_frames - i)

        injection_strength = float(body.get("injection_strength", 0.4))
        injection_strength = max(0.0, min(1.0, injection_strength))

        # Diagnostic: show what the UI actually sent us.
        _raw_base_params = body.get("base_params")
        if _raw_base_params is None:
            print(f"[Blend] base_params: <NOT SENT by UI — hard-refresh the browser to pick up the store change>")
        else:
            _bp_keys = sorted(_raw_base_params.keys()) if isinstance(_raw_base_params, dict) else []
            print(f"[Blend] base_params received: {len(_bp_keys)} keys: {_bp_keys}")

        print(f"[Blend] A={os.path.basename(clip_a_path)} ({info_a['w']}x{info_a['h']}@{info_a['fps']:.1f}), "
              f"B={os.path.basename(clip_b_path)} ({info_b['w']}x{info_b['h']}@{info_b['fps']:.1f})")
        # Describe the blend mode selected by prefix/suffix config
        _end_desc = (
            f"video_end={K_suffix} frames ({motion_suffix_sec:.2f}s) of B's overlap end"
            if video_end_path is not None else "image_end=B[O-1]"
        )
        if video_source_path is not None:
            print(f"[Blend] VE mode: video_source={K_prefix} frames ({motion_prefix_sec:.2f}s) of A's overlap start, {_end_desc}")
        else:
            print(f"[Blend] SE mode (no motion prefix): image_start=A[L-O], {_end_desc}")
        if extra_refs:
            print(f"[Blend]   + {len(extra_refs)} weak anchors @ strength={injection_strength:.2f}, "
                  f"positions={' '.join(str(p) for p in extra_positions)}")

        # ── Build generation params ─────────────────────────────────────────
        # Inherit the user's Studio settings (progressive_pipeline,
        # num_inference_steps, guidance_scale, negative_prompt, CFG-related
        # flags, etc.) so the blend uses the same generation config that
        # their manual SE tests used. Then override with blend-specific
        # fields (image_start/end, resolution, video_length, ...).
        default_prompt = (
            "continuous coherent camera motion smoothly transitioning "
            "between the two scenes, cinematic, natural movement"
        )
        default_neg = (
            "crossfade, dissolve, fade, double exposure, ghosting, "
            "static, still, abrupt cut, jump cut"
        )

        # Start from Studio's full params (if the UI passed them). Drop
        # keys we always compute ourselves so they can't leak through stale.
        base_params = dict(body.get("base_params") or {})
        for _k in (
            # Blend computes these
            "video_length", "resolution", "generation_mode", "image_prompt_type",
            "image_start", "image_end", "video_guide", "video_mask",
            "video_prompt_type", "image_refs", "frames_positions", "video_source", "video_end",
            # image_mode: Studio's image-vs-video toggle. MUST drop or the blend
            # can be coerced into image-only mode (outputs a .png instead of
            # generating a video — happened when user had image_mode active in
            # the sidebar and triggered a blend).
            "image_mode",
            # Blend is always a single generation; don't inherit Studio's repeat
            "repeat_generation",
            # Reference pipeline is a per-model Advanced Settings toggle for
            # plain generations; a blend inheriting it would silently switch
            # the sampling pipeline (and its blend target model may not even
            # support it). Never inherit.
            "reference_pipeline",
            # These had their own top-level overrides below
            "prompt", "model_type", "seed", "activated_loras", "loras_multipliers",
        ):
            base_params.pop(_k, None)

        gen_params = dict(base_params)  # start with inherited Studio settings
        gen_params.update({
            "prompt": body.get("prompt", default_prompt),
            "model_type": model_type,
            # negative_prompt: explicit body wins > inherited studio value > default
            "negative_prompt": body.get("negative_prompt", base_params.get("negative_prompt", default_neg)),
            "seed": body.get("seed", -1),
            # guidance_scale / num_inference_steps: explicit body wins > studio value > safe default
            "guidance_scale": float(body.get("guidance_scale", base_params.get("guidance_scale", 1.0))),
            "num_inference_steps": int(body.get("num_inference_steps", base_params.get("num_inference_steps", 15))),
            "video_length": transition_frames,
            "resolution": f"{src_w}x{src_h}",
            "generation_mode": "video",
            "image_mode": 0,  # defensive: blend is always a video job
            "image_prompt_type": "SE",
            "image_start": a_start_path,
            "image_end": b_end_path,
            "activated_loras": body.get("activated_loras", []),
            # Distilled pipeline has a single phase; strip multi-phase lora multipliers.
            "loras_multipliers": " ".join(m.split(";")[0] for m in (body.get("loras_multipliers", "") or "").split()),
            "sliding_window_size": transition_frames + 10,
            "settings_version": 2.52,
            "_blend_clip_a": clip_a_path,
            "_blend_clip_b": clip_b_path,
            "_blend_temp_dir": temp_dir,
            "_blend_mode": blend_mode,
            "_blend_overlap_sec": overlap_sec_eff,
            "_blend_fps": fps,
            "_blend_out_w": src_w,
            "_blend_out_h": src_h,
            # Final concat target — A's native dimensions (rounded to even for
            # libx264). The blend was generated at (src_w, src_h) which has
            # been snapped to 32-multiples (e.g. 1280x720 → 1280x704). Scaling
            # the blend up to A's native dims at concat time matches A_pre and
            # B_post pixel-perfectly, so the seams don't letterbox.
            "_blend_concat_w": int(info_a["w"]) - (int(info_a["w"]) % 2),
            "_blend_concat_h": int(info_a["h"]) - (int(info_a["h"]) % 2),
        })

        # Motion-prefix mode switches from SE (single start frame) to VE
        # (video_source + end frame), giving the model real motion history
        # from A so it extrapolates the rotation direction correctly.
        if video_source_path is not None:
            gen_params["image_prompt_type"] = "VE"
            gen_params["video_source"] = video_source_path
            # Remove image_start entirely — setting it to None explicitly
            # can confuse validation code that checks `key in dict`.
            # "V" in image_prompt_type supersedes "S" (video_source replaces image_start).
            gen_params.pop("image_start", None)

        # Motion-suffix: pass B's overlap-end frames as video_end so the
        # model sees B's motion trajectory leading into the landing frame.
        # Handled in ltx2.py via _append_suffix_entries — supersedes image_end.
        #
        # NOTE: image_end stays in gen_params even when suffix is active.
        # wgp.py validates image_prompt_type="VE" requires an end image, so
        # stripping image_end here triggers "You must provide an End Image"
        # BEFORE our code runs. We keep image_end = B[O-1] for validation;
        # ltx2.py's `has_suffix_frames` branch skips the image_end append
        # when the suffix is present, so it's effectively unused downstream.
        if video_end_path is not None:
            gen_params["video_end"] = video_end_path

        # input_video_strength: how tightly the pipeline locks to video_source
        # AND image_end. Default 1.0 = full lock → model ends up averaging
        # between the two anchors, which decodes as a crossfade for disparate
        # scenes. Lowering to 0.5-0.8 frees the model to invent motion
        # between the anchors instead of interpolating pixels.
        # Handler description: "you may try values lower value than 1 to
        # get more motion" (ltx2_handler.py:181).
        input_video_strength = float(body.get("input_video_strength", base_params.get("input_video_strength", 1.0)))
        input_video_strength = max(0.1, min(1.0, input_video_strength))
        gen_params["input_video_strength"] = input_video_strength

        if extra_refs:
            gen_params["video_prompt_type"] = "KFI"
            gen_params["image_refs"] = extra_refs
            gen_params["frames_positions"] = " ".join(str(p) for p in extra_positions)
            gen_params["injection_strength"] = injection_strength

        # Log the EFFECTIVE gen_params values actually being used for the job
        # (after merging base_params + body overrides + blend-specific fields).
        _effective_log_keys = (
            "num_inference_steps", "guidance_scale", "guidance_phases",
            "stage2_steps", "progressive_pipeline", "input_video_strength",
            "progressive_stage2_steps", "progressive_stage3_steps",
            "cfg_star_switch", "apg_switch",
            "sliding_window_size", "sliding_window_overlap",
        )
        _eff_summary = [(k, gen_params[k]) for k in _effective_log_keys if k in gen_params]
        if _eff_summary:
            print(f"[Blend] Effective gen_params: "
                  f"{', '.join(f'{k}={v!r}' for k, v in _eff_summary)}")
        _neg = gen_params.get("negative_prompt", "")
        if _neg:
            _neg_short = _neg if len(_neg) < 100 else _neg[:97] + "..."
            print(f"[Blend] negative_prompt: {_neg_short!r}")

        workspace = body.get("workspace") or _get_active_workspace()
        job_out_dir = _workspace_dir(workspace)

        job_id = uuid.uuid4().hex[:8]
        job = {
            "id": job_id, "status": "queued", "progress": 0, "step": 0, "total_steps": 0,
            "phase": "", "message": "Queued (blend)", "created_at": time.time(),
            "params": gen_params, "output_files": [], "error": None,
            "workspace": workspace, "out_dir": job_out_dir,
        }
        _register_manual_generation_job(job)

        worker = (
            _run_generation
            if execution_mode.policy().simulated
            else _run_blend_generation
        )
        thread = threading.Thread(target=worker, args=(job_id,), daemon=False)
        thread.start()

        return {
            "job_id": job_id,
            "status": "queued",
            "overlap_sec": overlap_sec_eff,
            "frames": transition_frames,
            **_generation_job_acceptance(job),
        }

    except Exception:
        # Setup failed before the background thread took ownership of temp_dir.
        # _run_blend_generation is responsible for cleanup once it starts.
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def create_blend_router(
    *, get_active_workspace, workspace_dir, register_manual_generation_job, generation_job_acceptance, run_generation,
) -> APIRouter:
    """Mount POST /api/v1/blend. Launch calls this once; it is the one place this module takes launch objects."""
    globals().update(
        _get_active_workspace=get_active_workspace,
        _workspace_dir=workspace_dir,
        _register_manual_generation_job=register_manual_generation_job,
        _generation_job_acceptance=generation_job_acceptance,
        _run_generation=run_generation,
    )
    router = APIRouter()
    router.add_api_route(
        "/api/v1/blend",
        blend_endpoint,
        methods=["POST"],
    )
    return router
