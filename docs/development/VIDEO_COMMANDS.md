# Studio video commands

The shared command boundary for video is `operation=generation.video`.
Two envelope versions are published on `GET /api/v1/generation/commands` and
as the MCP tool `generation.video` of the **full server** (full catalog and the
`game` profile; the `series` profile does not list it). The core server
publishes only `generation.image` and `generation.receipt` in that catalog.

Related: [IMAGE_COMMANDS](IMAGE_COMMANDS.md) (same admission path),
[H3_EXTENDED_DURATION](H3_EXTENDED_DURATION.md),
[SHARED_NATIVE_COMMANDS](SHARED_NATIVE_COMMANDS.md).

This is admission, not a finished MP4. A queued receipt is not GPU success.

## Who calls it

- MCP clients (full catalog and `game` profile).
- Server-side producers: Series shots (`series_video_shots.py`, version 3) and
  the game tools (`game_tools.py`).
- The generation inspector's clone and retry in the UI
  (`ui/src/features/generation-inspector/submit.ts`).

Studio → Video **Generate** and the Wizard's `prepare_video` +
`start_generation` do not use this command: they still post the Studio form to
`POST /api/v1/generate`. A typed Wizard capability for `generation.video`
exists in `ui/src/features/agent/videoGenerationCapability.ts`, but it is not
wired into the application store, so a Wizard action `generation_video` is not
executable.

## Version 2 — Wan 2.1 Text2Video

Closed family `t2v` / `t2v_1.3B` (`VIDEO_MODEL_TYPES` in
`app/services/video_generation_spec.py`). `freeze_video_generation_spec`
validates and deep-copies the native parameter map. `original` keeps the
submitted envelope; `effective` adds the adapter-owned Studio video defaults
(`STUDIO_VIDEO_DEFAULTS`: `generation_mode=video`, `image_mode=0`,
`batch_size=1`, `repeat_generation=1`, empty LoRA, negative-prompt and
prompt-type fields, `seed=-1`, and `multi_prompts_gen_type=2` so a multiline
prompt stays one clip) for every field the caller left out. The fingerprint is
SHA-256 over the version, operation, workspace and effective parameters;
`intent_id` is excluded.

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
installed. Version 2 has no `validate` flag: sending one is rejected as an
unexpected field.

## Version 3 — MiniMax H3 and LTX-2.3

Typed frames and driving audio. Families (`app/services/video_generation_v3.py`):

| Family | Model ids |
|---|---|
| FL2VA | `minimax_h3`, `minimax_h3_full`, `minimax_h3_legacy`, `minimax_h3_fused_turbo` |
| Ref2VA | `minimax_h3_ref2va`, `minimax_h3_ref2va_full`, `minimax_h3_ref2va_fused_turbo` |
| LTX-2.3 | `ltx2_22B` and the shipped 2.3 variants (`_1_1`, `_distilled`, GGUF, fp8, nvfp4, …) |

H3 Advanced is a separate family and is **not** accepted here. LTX-2
(`ltx2_19B`) is not this family.

`validate: true` builds the internal generate payload and returns
`{validated: true, enqueued: false, payload}` **before** admission. Nothing in
this path loads a checkpoint or enters the GPU queue. It checks the envelope
(shape, families, lattices, presets, audio mode) only: whether the model is
installed and whether a referenced asset exists are checked at admission, so a
validated command can still be refused there. Only version 3 accepts
`validate`.

```json
{
  "version": 3,
  "operation": "generation.video",
  "intent_id": "stable-client-intention",
  "validate": true,
  "input": {
    "workspace": "output-workspace",
    "params": {
      "prompt": "A courier steps off a night bus and looks back",
      "model_type": "minimax_h3",
      "resolution": "864x480",
      "video_length": 124,
      "image_start": "asset_start01",
      "seed": -1
    }
  }
}
```

Per family:

- **FL2VA** requires `image_start` and rejects `references`
  (`invalid_selector`).
- **Ref2VA** takes `references[]` (`type` image/video/audio, `source` an asset
  id or canonical local URL, optional role and intent flags) and needs at least
  one image or video reference (`invalid_reference`). It rejects `image_start`,
  `image_end` and audio mode `A`: its audio is a reference.
- **LTX-2.3** requires `image_start`, may take `image_end`, and rejects
  references and `minimax_h3_extended_duration`.

`audio_prompt_type: "A"` (FL2VA and LTX-2.3) requires `audio_guide`, and an
`audio_guide` requires mode `A`. Host paths and remote URLs fail before
admission.

Lattices and resolutions:

- H3 `video_length` (and `sliding_window_size` when set) must be on the
  124 + 17k lattice through 345 frames. `minimax_h3_extended_duration: true`
  extends that lattice through 719 frames (experimental 30 s; see
  [H3_EXTENDED_DURATION](H3_EXTENDED_DURATION.md)). A value off the lattice
  fails with `invalid_selector` and the allowed list.
- H3 `resolution` must be one of the published H3 presets (for example
  `864x480`, `1280x704`, `1920x1088`), not an arbitrary size.
- LTX-2.3 `video_length` is 17 + 8k, `sliding_window_size` 5 + 4k through 501,
  and `resolution` one of the typed list taken from WanGP with 4K off.

## Jobs after admission

`jobs.wait` `{version: 1, input: {job_id, timeout_s?}}` blocks until
`completed` / `failed` / `cancelled` / `discarded`, or until `timeout_s`
(default 30, cap 120). A timeout returns the **live** status with
`timed_out: true`, not an error. `interrupted` stays open so resume works.
The call does not poll the GPU or start a model.

After a restart, `jobs.leftovers` lists interrupted generation jobs and
Video 2D/3D exports. `jobs.resume` retries the stored command;
`jobs.discard` drops it from the queue (status `discarded`) so a later scan
cannot resurrect it, and does nothing to a job that is already running (use
`jobs.cancel`). Both take `input.intent_id`. These three
tools are in the `game` MCP profile and the full catalog; the `series` profile
has `jobs.wait` and `jobs.cancel` only.

## Limits

- A queued receipt is not a finished file and not a quality claim.
- An `intent_id` already admitted with other content, including the other
  envelope version (their fingerprint versions differ), is a conflict.
- `validate: true` on version 3 must not create a task.
- This slice does not publish H3 Advanced, remote providers or an arbitrary
  runtime parameter map.
