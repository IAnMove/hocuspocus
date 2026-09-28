# Shared video command admission

Studio Video, Wizard `prepare_video` + `start_generation`, and MCP
`generation.video` share a closed, versioned envelope. Closing the browser
does not cancel an already admitted job. This page is the contract; it is not
a GPU quality report.

Related: [image commands](IMAGE_COMMANDS.md), [H3 30 s](H3_EXTENDED_DURATION.md),
[jobs and assets](JOBS_AND_ASSETS.md), [Wizard / MCP usage](WIZARD_MCP_USAGE.md).

Code: `app/services/video_generation_spec.py` (version 2),
`app/services/video_generation_v3.py` (version 3),
`app/routers/studio_video_commands.py`.

---

## Discovery

`GET /api/v1/generation/commands` lists `generation.video` with
`supportedVersions: [2, 3]`. MCP `tools/list` publishes the same name.
The tool name carries the operation; HTTP also sends `"operation": "generation.video"`.

| Version | Family | What it types |
|---|---|---|
| 2 | Wan 2.1 Text2Video | `t2v`, `t2v_1.3B` only |
| 3 | MiniMax H3 FL2VA / Ref2VA, LTX-2.3 | Frames, optional driving audio, Ref2VA references |

H3 Advanced and other video families stay on their existing Studio paths.
They are not accepted here.

---

## Version 2 — Wan 2.1 Text2Video

Closed envelope. Extra fields are rejected. `original` keeps the submitted
bytes; `effective` adds only adapter-owned video sentinels. The fingerprint
covers operation, workspace and native parameters and excludes `intent_id`.

```json
{
  "version": 2,
  "operation": "generation.video",
  "intent_id": "one-client-intention",
  "input": {
    "workspace": "my-outputs",
    "params": {
      "model_type": "t2v_1.3B",
      "prompt": "A red boat on calm water",
      "resolution": "832x480",
      "video_length": 17,
      "num_inference_steps": 4,
      "guidance_scale": 1.0,
      "seed": 42
    }
  }
}
```

`model_type` must be `t2v` or `t2v_1.3B`. Prompt enhancement stays off.
A multiline prompt is one clip (`multi_prompts_gen_type: 2`).

---

## Version 3 — H3 and LTX-2.3

Version 3 types one shot with first/last frames or Ref2VA references.
`validate: true` builds the internal generate payload and returns **before**
admission. Nothing in this path loads a checkpoint or enters the GPU queue.

```json
{
  "version": 3,
  "operation": "generation.video",
  "intent_id": "h3-fl2va-1",
  "validate": false,
  "input": {
    "workspace": "my-outputs",
    "params": {
      "model_type": "minimax_h3",
      "prompt": "A courier steps into rain. Audio: rain, distant traffic.",
      "resolution": "864x480",
      "video_length": 124,
      "seed": 42,
      "image_start": "/api/v1/file/start.png?workspace=my-outputs",
      "audio_prompt_type": "A",
      "audio_guide": "/api/v1/file/drive.wav?workspace=my-outputs"
    }
  }
}
```

### Families

| Family | `model_type` examples | Required media | Forbidden |
|---|---|---|---|
| FL2VA | `minimax_h3`, `minimax_h3_full`, `minimax_h3_legacy`, `minimax_h3_fused_turbo` | `image_start` (asset id or canonical URL) | Ref2VA `references` |
| Ref2VA | `minimax_h3_ref2va`, `minimax_h3_ref2va_full`, `minimax_h3_ref2va_fused_turbo` | ≥1 image or video `references[]` | `image_start` / `image_end`; audio mode `A` |
| LTX-2.3 | `ltx2_22B` and the wired `ltx2_22B_*` catalog ids | `image_start` | Ref2VA `references`; `minimax_h3_extended_duration` |

Discovery publishes the exact id lists under `families` on the version-3 schema.

### Lengths and resolutions

Lengths are the lattices the model handlers already publish. They are **not**
snapped into compliance: a value off the lattice is `invalid_selector`.

| Family | Frames | Window | Resolution |
|---|---|---|---|
| H3 | `124 + 17k` through **345**. With `minimax_h3_extended_duration: true`, through **719**. | Same lattice as `video_length` when omitted | H3 presets only (`864x480`, `480x864`, `auto_480p`, …). See `limits.h3_resolutions`. |
| LTX-2.3 | `17 + 8k` through the 501-frame window cap | `5 + 4k` through 501 | The LTX list in `limits.ltx2_3_resolutions` (for example `1280x720`, `720x1280`) |

Omitted `sliding_window_size` copies `video_length`.

### Driving audio

- FL2VA and LTX: `audio_prompt_type: "A"` requires `audio_guide` (asset id or
  canonical URL). `audio_guide` without mode `A` is rejected.
- Ref2VA: soundtrack is a reference with `type: "audio"` and
  `audio_intent: "voice" | "drive" | "style"`. Mode `A` is rejected.

Upload a file first with [`assets.upload`](JOBS_AND_ASSETS.md); pass the
returned URL as `image_start`, `image_end`, `audio_guide`, or `references[].source`.

### Ref2VA references

```json
{
  "type": "image",
  "source": "/api/v1/file/hero.png?workspace=my-outputs",
  "role": "courier",
  "image_intent": "identity"
}
```

Caps (from `reference_manifest.py`): 9 images, 3 videos, 3 audios, 12 total.
Over those limits, or a missing visual when required, is `invalid_reference`.

---

## Errors

| Code | When |
|---|---|
| `invalid_command` | Envelope / types / extra fields |
| `invalid_selector` | Value off the published lattice. The message lists **allowed** values. |
| `invalid_reference` | Ref2VA manifest / count / missing visual |

`invalid_selector` does not enqueue. Call `models` with `detail: true` or
`model_type` for the full allowed set when the short list is truncated.

---

## Optional fields shared with other generation commands

- `output_name` — basename inside the workspace. See [jobs and assets](JOBS_AND_ASSETS.md).
- `priority` — integer; higher runs first among pending jobs. Same page.

`generation.receipt` projects produced files as `asset_id`, `canonical_url`
and workspace-relative `path`. The stored admission is unchanged.
