"""Per-job VRAM safety coefficient.

The number lives on ``wgp.args``, the one WanGP args object. Tightening it
for one job and restoring the base afterwards both write that same object.
The hardware probe and its cache stay in the launch module. Launch hands
this module its ``wgp`` and its ``_get_cached_hardware`` once, through
:func:`bind`; that function reads launch's cache when it is called, so a
test that replaces the cache is seen.
"""
import os

# Bound by bind(); None until the full server binds them.
wgp = None
_get_cached_hardware = None


def bind(*, wgp, get_cached_hardware):
    """Take the launch objects this module reads. Launch calls this once, after it defines them."""
    globals().update(wgp=wgp, _get_cached_hardware=get_cached_hardware)


# ── Per-job VRAM coefficient adjustment ────────────────────────────
# Auto-tune sets a single base coefficient (e.g. 0.80 for a 24 GB
# card) but real jobs vary in memory pressure based on:
#   - LoRA stack size (each LoRA adds ~its file size in VRAM)
#   - Pipeline stage count (each extra stage holds latents resident)
#
# This helper lowers wgp.args.vram_safety_coefficient temporarily for
# the duration of a single job so heavier jobs get a tighter cap and
# more aggressive offloading. The base is restored after the job so
# subsequent lighter jobs aren't penalized.
#
# IMPORTANT — model-caching caveat:
#   wgp.py's offload.profile() is called inside load_models(), which
#   only runs when a model gets (re)loaded. If the user runs two jobs
#   back-to-back with the same model, the second job picks up the
#   coefficient set on `args` at that moment, BUT the cached offload
#   profile from the first load is still active. So the per-job
#   adjustment is most effective:
#     - on the first job after switching models
#     - on the first job after app startup
#     - when the model gets unloaded between jobs (mmgp's choice)
#   For back-to-back same-model jobs the helper still records the
#   intended adjustment in job["vram_adjustment"] (so the UI can show
#   the user what the budget *would* be), but enforcement depends on
#   when wgp next reloads. Forcing an unload on large coef changes is
#   a possible follow-up if the limitation bites in practice.

def _stage_count_from_params(params: dict) -> int:
    """Translate the user's pipeline-mode flags to a stage count.

    UI exposes three options:
      Single (1 stage)     → single_stage_pipeline=True
      Standard (2 stages)  → both flags False (the default)
      Progressive (3)      → progressive_pipeline=True

    Image-mode jobs (HiDream, Flux 2 Klein, Qwen Image) don't run through
    a multi-stage pipeline — they're single-pass. The "standard 2 stages"
    default only applies to video models (LTX-2 distilled, etc.). Returning
    2 for image jobs was triggering a phantom -0.083 coefficient penalty
    (and ~1.3 GB cap shrink) that did nothing useful and possibly caused
    HiDream's int8 quanto load path to mis-handle layer offload.
    """
    if params.get("image_mode", 0) and int(params.get("image_mode", 0)) > 0:
        return 1
    if params.get("progressive_pipeline"):
        return 3
    if params.get("outpaint_full_resolution_refine"):
        return 2
    if params.get("single_stage_pipeline"):
        return 1
    return 2


def _apply_per_job_coefficient(job: dict) -> None:
    """Compute and apply a per-job VRAM safety coefficient.

    Mutates `wgp.args.vram_safety_coefficient` for the duration of the
    job so wgp's offload profile uses the tighter cap. Restored by
    `_restore_base_coefficient()` in the job's finally block.

    Records the result on `job` so the API/UI can surface it:
      job["vram_adjustment"] = {
          base_coef, effective_coef, lora_total_gb,
          lora_penalty, pass_penalty, stage_count, reasons
      }
    """
    try:
        from services.perf_recommend import (
            compute_h3_weight_budget,
            compute_per_job_coefficient,
        )

        params = job.get("params") or {}

        # SFX (mmaudio) jobs don't go through the LoRA / stage pipeline —
        # nothing to adjust.
        if params.get("sfx_mode"):
            return

        base_coef = float(
            wgp.server_config.get("vram_safety_coefficient", 0.80)
        )
        hw = _get_cached_hardware()
        total_vram_gb = float(hw.get("gpu_vram_gb", 0.0))
        if total_vram_gb <= 0:
            return  # no VRAM info → can't adjust safely

        active_loras = list(params.get("activated_loras") or [])
        model_type = params.get("model_type")
        lora_dir = None
        if model_type:
            try:
                lora_dir = wgp.get_lora_dir(model_type)
            except Exception:
                lora_dir = None

        stage_count = _stage_count_from_params(params)
        resolution = params.get("resolution")
        # video_length is in frames (Maestro convention). For images
        # video_length is typically 1 — the helper handles both.
        video_length = params.get("video_length")
        try:
            video_length = int(video_length) if video_length is not None else None
        except (TypeError, ValueError):
            video_length = None

        # Director long-form jobs pass video_length = TOTAL movie frames
        # (e.g. 5400 for a 3-minute film), but the per-denoising-step
        # VRAM peak is bounded by sliding_window_size — wgp only holds
        # one window's worth of latents and activations on the GPU at
        # a time. Without this clamp, compute_per_job_coefficient sees
        # 5400 frames worth of "compute size" and applies an aggressive
        # (and wrong) penalty that pushes the safety coefficient too low,
        # shrinking the cap and forcing unnecessary offload during
        # Director video gen. Clamping here makes the calc correctly
        # size against the actual per-step working set.
        #
        # Studio single-shot jobs typically have video_length ≤
        # sliding_window_size, so the clamp is a no-op there.
        # Image jobs have video_length = 1 and no sliding window —
        # also a no-op.
        sliding_window_size = params.get("sliding_window_size")
        try:
            sliding_window_size = (
                int(sliding_window_size) if sliding_window_size is not None else None
            )
        except (TypeError, ValueError):
            sliding_window_size = None
        effective_frames = video_length
        if (
            sliding_window_size
            and sliding_window_size > 0
            and effective_frames
            and effective_frames > sliding_window_size
        ):
            effective_frames = sliding_window_size

        # SCAIL-2 activation surcharge. The model appends the driving
        # video as in-context tokens (~25% extra sequence) and prepends
        # reference latents, so its attention working set is far larger
        # than resolution × frames predicts — the generic compute curve
        # rates a 480p SCAIL-2 window "lighter than baseline" and
        # LOOSENS the cap. Measured on a 24GB RTX 4090: a 49-frame
        # 848x480 window peaked at 23.1GB under a 17.8GB weight cap
        # (~5.3GB activations); an 81-frame window extrapolates to
        # ~8.5GB activations and overflowed 24GB in the field
        # (user-reported OOM, 2026-07-17). Surcharge = 6GB at the
        # 848x480 x 81-frame reference, scaled linearly by window
        # pixels x frames, so the freed VRAM tracks the actual
        # activation need.
        model_activation_gb = 0.0
        try:
            _base_mt = wgp.get_base_model_type(model_type) if model_type else None
        except Exception:
            _base_mt = None
        try:
            _job_model_def = wgp.get_model_def(model_type) if model_type else {}
        except Exception:
            _job_model_def = {}
        _h3_references = list(params.get("minimax_h3_references") or [])
        _h3_video_reference_count = sum(
            1
            for reference in _h3_references
            if isinstance(reference, dict)
            and str(reference.get("type") or reference.get("kind") or "").lower() == "video"
        )
        _is_h3 = str(_job_model_def.get("architecture") or "").startswith(
            "minimax_h3"
        )
        _h3_omni_video = bool(
            _job_model_def.get("omni_reference")
            and _h3_video_reference_count
        )
        # H3 itself is a single denoising pipeline. Treating the ordinary
        # two-stage UI default as a second H3 stage double-counts model memory.
        if _is_h3:
            stage_count = 1

        if _base_mt in ("scail2_14B", "scail2_1.3B"):
            _ref_pixels, _ref_frames = 848 * 480, 81
            _pixels = _ref_pixels
            if isinstance(resolution, str) and "x" in resolution:
                try:
                    _w, _h = resolution.lower().split("x")
                    _pixels = int(_w) * int(_h)
                except (ValueError, TypeError):
                    pass
            _frames = effective_frames or _ref_frames
            model_activation_gb = 6.0 * (_pixels / _ref_pixels) * (_frames / _ref_frames)

        h3_reference_activation_gb = 0.0
        if _h3_omni_video:
            # Every Ref2VA video is appended as full spatiotemporal attention
            # context. With Match Output detail, one 15-second 960x544 video
            # contributes roughly another complete target-video token set.
            # Reserve 8 GB per baseline-sized video for packed hidden states,
            # Q/K/V, attention output, and allocator slack. The transformer is
            # streamed more aggressively below, matching WanGP's low-VRAM H3
            # strategy instead of letting weights occupy activation space.
            _ref_pixels = 960 * 544
            _ref_frames = 345
            _pixels = _ref_pixels
            if isinstance(resolution, str) and "x" in resolution:
                try:
                    _w, _h = resolution.lower().split("x")
                    _pixels = int(_w) * int(_h)
                except (ValueError, TypeError):
                    pass
            _frames = min(effective_frames or _ref_frames, _ref_frames)
            h3_reference_activation_gb = (
                8.0
                * _h3_video_reference_count
                * (_pixels / _ref_pixels)
                * (_frames / _ref_frames)
            )
            # Diagnostic estimate only. The dedicated H3 budget below uses
            # its own 10 GB/reference reserve; feeding this estimate into the
            # generic coefficient too would charge every video reference
            # twice and make low-VRAM Omni jobs needlessly slow.

        adjustment = compute_per_job_coefficient(
            base_coef=base_coef,
            total_vram_gb=total_vram_gb,
            active_loras=active_loras,
            lora_dir=lora_dir,
            stage_count=stage_count,
            resolution=resolution,
            video_length_frames=effective_frames,
            model_activation_gb=model_activation_gb,
        )
        if h3_reference_activation_gb:
            adjustment["h3_reference_activation_estimate_gb"] = (
                h3_reference_activation_gb
            )
        # The dedicated upstream SCAIL-2 transformer uses the official
        # attention/token layout instead of WanGP's generalized fused path.
        # Its measured peak is healthy when transformer residency is held to
        # roughly 7 GB on a 24 GB card; allowing the ordinary coefficient
        # floor to keep 10-12 GB resident leaves too little attention
        # workspace and makes WDDM spill into shared memory (minutes per
        # denoise step). MMGP streams the remaining weights efficiently.
        dedicated_scail2 = (
            _base_mt in ("scail2_14B", "scail2_1.3B")
            and os.environ.get(
                "MAESTRO_SCAIL2_DEDICATED_MODEL", "1",
            ).strip().lower() not in {"0", "false", "no", "off"}
        )
        if dedicated_scail2:
            dedicated_weight_budget_gb = min(
                16.0,
                max(3.5, total_vram_gb - 17.0),
            )
            dedicated_coefficient_cap = (
                dedicated_weight_budget_gb / total_vram_gb
            )
            if adjustment["effective_coef"] > dedicated_coefficient_cap:
                adjustment["effective_coef"] = dedicated_coefficient_cap
                adjustment["floored"] = False
                adjustment["reasons"].append(
                    f"- dedicated SCAIL-2 transformer residency capped at "
                    f"{dedicated_weight_budget_gb:.1f} GB to preserve "
                    "attention workspace"
                )
            adjustment["dedicated_scail2_budget_gb"] = (
                dedicated_weight_budget_gb
            )
        if _is_h3:
            # H3 is one pipeline stage, but its packed text + stereo audio +
            # video attention needs explicit workspace.  Without this cap,
            # the generic light-job bonus raised a 960x544 x 336-frame job
            # to 19.3 GB of resident weights on a 24 GB 4090 and the process
            # exited on denoising step zero.  The budget also scales down for
            # lower-VRAM cards and adds reference-video attention headroom.
            h3_runtime_workspace_gb = float(
                _job_model_def.get(
                    "minimax_h3_transformer_working_vram_gb",
                    0.0,
                )
                or 0.0
            )
            h3_budget = compute_h3_weight_budget(
                total_vram_gb,
                resolution,
                effective_frames,
                _h3_video_reference_count if _h3_omni_video else 0,
                runtime_workspace_gb=h3_runtime_workspace_gb,
                # A LoRA's resident adapter tensors are outside the base
                # transformer's measured working set. The generic LoRA
                # coefficient can be superseded by H3's stricter absolute
                # cap, so carry the bytes into this budget explicitly.
                additional_reserve_gb=adjustment.get("lora_total_gb", 0.0),
            )
            h3_weight_budget_gb = h3_budget["weight_budget_gb"]
            h3_coefficient_cap = h3_weight_budget_gb / total_vram_gb
            if adjustment["effective_coef"] > h3_coefficient_cap:
                adjustment["effective_coef"] = h3_coefficient_cap
                adjustment["floored"] = False
                adjustment["reasons"].append(
                    f"- MiniMax H3 transformer residency "
                    f"capped at {h3_weight_budget_gb:.1f} GB to preserve "
                    f"{h3_budget['activation_reserve_gb']:.1f} GB of packed-sequence workspace"
                )
            adjustment["h3_weight_budget_gb"] = h3_weight_budget_gb
            adjustment["h3_activation_reserve_gb"] = h3_budget[
                "activation_reserve_gb"
            ]
            adjustment["h3_runtime_workspace_gb"] = h3_runtime_workspace_gb
            adjustment["h3_scaled_runtime_workspace_gb"] = h3_budget[
                "scaled_runtime_workspace_gb"
            ]
            if h3_budget["runtime_scaling_active"]:
                adjustment["reasons"].append(
                    f"- H3's {h3_runtime_workspace_gb:.1f} GB runtime "
                    "workspace baseline scales to "
                    f"{h3_budget['scaled_runtime_workspace_gb']:.1f} GB for "
                    "this high-token window; MMGP streams "
                    "model weights around that reserve"
                )
            if h3_budget["runtime_safety_margin_gb"]:
                adjustment["reasons"].append(
                    f"- {h3_budget['runtime_safety_margin_gb']:.1f} GB "
                    "high-load allocator/display safety margin"
                )
            if h3_budget["additional_reserve_gb"]:
                adjustment["reasons"].append(
                    f"- {h3_budget['additional_reserve_gb']:.2f} GB reserved "
                    "inside the H3 cap for active LoRA tensors"
                )
        job["vram_adjustment"] = adjustment

        effective = adjustment["effective_coef"]
        if abs(effective - base_coef) > 1e-6 or _is_h3:
            wgp.args.vram_safety_coefficient = effective
            if _is_h3 and getattr(wgp, "wan_model", None) is not None:
                loaded_coefficient = getattr(
                    wgp.wan_model,
                    "_maestro_profile_vram_coefficient",
                    None,
                )
                if loaded_coefficient is None or float(loaded_coefficient) > effective + 1e-6:
                    wgp.reload_needed = True
                    adjustment["reasons"].append(
                        "- resident H3 profile will reload with packed-sequence headroom"
                    )
            cap_gb = effective * total_vram_gb
            base_cap_gb = base_coef * total_vram_gb
            # Log the frame-clamp explicitly when it fired so a future
            # "why is the coefficient X" question has data right next
            # to the answer.
            clamp_note = ""
            if (
                video_length and effective_frames
                and effective_frames < video_length
            ):
                clamp_note = (
                    f" [frames clamped {video_length}→{effective_frames} "
                    f"via sliding_window_size]"
                )
            print(
                f"[VRAM] Job {job.get('id', '?')}: coefficient "
                f"{base_coef:.2f} → {effective:.3f} "
                f"(cap {base_cap_gb:.1f}GB → {cap_gb:.1f}GB){clamp_note}"
            )
            for reason in adjustment["reasons"]:
                print(f"[VRAM]   {reason}")
    except Exception as e:
        # Never let a coefficient-adjustment bug fail the job.
        print(f"[VRAM] per-job adjustment failed: {e}")


def _restore_base_coefficient() -> None:
    """Restore wgp.args.vram_safety_coefficient to the persisted base.

    Called from the finally block in `_run_generation` and
    `_run_sfx_generation` so subsequent jobs start from the user's
    auto-tuned base, not a previous job's adjusted value.
    """
    try:
        base = float(wgp.server_config.get("vram_safety_coefficient", 0.80))
        wgp.args.vram_safety_coefficient = base
    except Exception:
        pass  # Never fail teardown
