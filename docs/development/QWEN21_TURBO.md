# Official Qwen Image 2.1 Turbo

Added on October 10, 2026 as `qwen_image_21_turbo`. This is the official eight-step checkpoint, separate from the existing Viggle six-step LoRA. The 40-step base remains the default: the local comparison shows a substantial speed improvement, but does not establish identical quality or instruction following.

## Model recipe

- Official [model card](https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo) and [Qwen release](https://github.com/QwenLM/Qwen-Image-2.1).
- INT8 ConvRot transformer from Comfy-Org/Qwen-Image-2.1, pinned to `df94239739eef7205973a145ffa6f441f7b64e84`. The Qwen3-VL encoder and Qwen 2.1 VAE are shared with the base model.
- Eight sampling sigmas from the official `model_index.json` at `d65dbc9a7e8f6b5479e33dee6030eaab2a906509`: `1, .978453, .95418, .926626, .89508, .845148, .704534, .414568`. Terminal zero is appended by the scheduler.
- CFG 1; dynamic resolution shifting and terminal stretching are disabled, matching the official scheduler. Prefix KV caching stays enabled in the native pipeline.
- Fixed steps and guidance are enforced before generation. Base and Viggle schedules remain unchanged. Native 2K, RGBA, editing and ten references remain available through the unified 2.1 runtime.

## Local comparison

RTX 4090 24 GB, INT8 ConvRot transformer and encoder, SDPA, memory profile 3, CFG 1, one image per request, seed `20261010`. Identical prompts and inputs for each scored pair. A warmup precedes each model; the first download and queue wait are excluded. Times below are backend processing times, including prompt encoding, sampling, decoding and saving.

| Case | Base, 40 steps | Official Turbo, 8 steps | Speedup |
| --- | ---: | ---: | ---: |
| Portrait, 1024² | 22.92 s | 7.54 s | 3.04× |
| Typography, 1024² | 22.99 s | 7.60 s | 3.03× |
| Objects, 1024² | 23.03 s | 7.54 s | 3.05× |

The portrait retains convincing skin, hair, hands and knitted fabric; the composition changes. Both posters render the three requested headings legibly. In the objects case the Turbo output holds the flowerpot above the watering can instead of holding the can with both hands to water the plant. This is a concrete instruction-following difference, so Turbo remains an optional fast alternative.

The original saved `vae_config=1` disables tiling. The base's initial 2048² attempt completed sampling but ran out of VRAM during VAE decoding; that failed attempt is excluded. A temporary `--vae-config 0` replay then encountered another running HocusPocus instance using about 19 GB of VRAM. The scored comparison therefore covers the three 1K pairs above; native 2K transparency and the same-source edit pair remain unvalidated on this workstation. The saved configuration was not changed.

An exploratory base reference edit also hit a pre-existing Triton shared-memory limit and disabled injected INT8 kernels for the session. That exploratory request used subject-reference conditioning and is excluded from scored results. The reproducible full-scene edit recipe uses `KI` and disables background removal. Run editing after the text-to-image cases and retain any kernel fallback warning when interpreting edit timings.

## Reproduce and inspect

Use a freshly started backend with the GPU available, then run from the activated `app` environment:

```bash
python scripts/benchmark_qwen21_turbo.py \
  --base-url http://127.0.0.1:PORT \
  --output-dir ../logs/qwen21-turbo-benchmark
```

Results are saved into a separate `qwen21_turbo_benchmark` workspace. The output directory contains the exact requests, job receipts, status histories, phase timings, unmodified PNGs and `comparison.html`. Both edit cases use the base objects PNG as the same full-scene reference, with background removal disabled. Re-running reconnects to recorded jobs instead of submitting duplicates; interrupted/failed jobs stop the client for inspection.

The October 10 workstation artifacts are in `logs/qwen21-turbo-images/` and the gallery workspace `qwen21_turbo_images`. Logs, generated media and checkpoints are ignored by Git. The runtime checks cover scheduler fidelity at multiple resolutions, base/Viggle compatibility, fixed parameters, reference limits and production step defaults.
