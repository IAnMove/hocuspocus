# Studio video commands

The shared command boundary for Studio video is `operation=generation.video`.
Two envelope versions are published on `GET /api/v1/generation/commands` and
as the MCP tool `generation.video` (full catalog and the `game` profile;
the `series` profile does not list it).

Related: [IMAGE_COMMANDS](IMAGE_COMMANDS.md) (same admission path),
[H3_EXTENDED_DURATION](H3_EXTENDED_DURATION.md),
[SHARED_NATIVE_COMMANDS](SHARED_NATIVE_COMMANDS.md).

This is admission, not a finished MP4. A queued receipt is not GPU success.

## Version 2 — Wan 2.1 Text2Video

Closed family `t2v` / `t2v_1.3B` (`VIDEO_MODEL_TYPES` in
`app/services/video_generation_spec.py`). `freeze_video_generation_spec`
validates and deep-copies the native parameter map. `original` keeps the
submitted envelope; `effective` adds only adapter-owned video sentinels
(`generation_mode=video`, `image_mode=0`, `multi_prompts_gen_type=2` so a
multiline prompt stays one clip). The fingerprint is SHA-256 over version,
operation, workspace and effective parameters; `intent_id` is excluded.

```json
{
  "version": 2,
  "operation": "generation.video",
  "intent_id": "stable-client-intention",
  "input": {
    "workspace": "output-workspace",
    "params": {
      "prompt": "A red boat crossing calm water",
      "model_type": "t2v",
      "resolution": "832x480",
      "video_length": 81,
      "num_inference_steps": 20,
      "guidance_scale": 5,
      "seed": -1
    }
  }
}
```

MCP omits `operation` (the tool name carries it). Unknown fields, host paths,
remote URLs and speech/music/SFX controls are rejected. Models must be
installed. Version 2 has no `validate` flag.

## Version 3 — MiniMax H3 and LTX-2.3

Typed frames and driving audio. Families (`app/services/video_generation_v3.py`):

| Family | Model ids |
|---|---|
| FL2VA | `minimax_h3`, `minimax_h3_full`, `minimax_h3_legacy`, `minimax_h3_fused_turbo` |
| Ref2VA | `minimax_h3_ref2va`, `minimax_h3_ref2va_full`, `minimax_h3_ref2va_fused_turbo` |
| LTX-2.3 | `ltx2_22B` and the shipped 2.3 variants (`_1_1`, `_distilled`, GGUF, fp8, nvfp4, …) |

H3 Advanced is a separate family and is **not** accepted here. LTX-2
(`ltx2_19B`) is not this family.

`validate: true` builds the internal generate payload and returns **before**
admission. Nothing in this path loads a checkpoint or enters the GPU queue.

```json
{
  "version": 3,
  "operation": "generation.video",
  "intent_id": "stable-client-intention",
  "validate": false,
  "input": {
    "workspace": "output-workspace",
    "params": {
      "prompt": "A courier steps off a night bus and looks back",
      "model_type": "minimax_h3",
      "resolution": "1280x720",
      "video_length": 124,
      "seed": -1
    }
  }
}
```

H3 `video_length` (and `sliding_window_size` when set) must be on the
124 + 17k lattice through 345 frames. `minimax_h3_extended_duration: true`
extends that lattice through 719 frames (experimental 30 s; see
[H3_EXTENDED_DURATION](H3_EXTENDED_DURATION.md)). A value off the lattice
fails with `invalid_selector` and the allowed list. Resolutions must be a
published H3 preset or, for LTX-2.3, one of the typed WanGP list (no
4K unless the handler publishes it).

Ref2VA takes `references[]` (`type` image/video/audio, `source` an asset id
or canonical local URL, optional role/intent flags). FL2VA rejects a
reference list (`invalid_selector`). `audio_prompt_type: "A"` requires
`audio_guide`. Host paths and remote URLs fail before admission.

## Jobs after admission

`jobs.wait` `{version: 1, input: {job_id, timeout_s?}}` blocks until
`completed` / `failed` / `cancelled` / `discarded`, or until `timeout_s`
(default 30, cap 120). A timeout returns the **live** status with
`timed_out: true`, not an error. `interrupted` stays open so resume works.
The call does not poll the GPU or start a model.

After a restart, `jobs.leftovers` lists interrupted generation jobs and
Video 2D/3D exports. `jobs.resume` retries the stored command;
`jobs.discard` cancels it so a later scan cannot resurrect it.

## Limits

- A queued receipt is not a finished file and not a quality claim.
- Version 2 and version 3 cannot adopt each other's `intent_id`.
- `validate: true` on version 3 must not create a task.
- This slice does not publish H3 Advanced, remote providers or an arbitrary
  runtime parameter map.
