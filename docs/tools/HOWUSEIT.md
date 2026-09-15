# HOWUSEIT — Studio Tools (upscale, revoice, remove background)

Operator guide for **post-processing existing media**. Tools do not invent a
new shot: they take one exact image or clip, write a **new** file, and leave
the source untouched.

UI: Studio sidebar → **Tools** (`generationMode: tools`,
`ui/src/components/Sidebar/ToolsPanel.tsx`). Upscale uses the version 2
`tools.upscale` operation at `POST /api/v1/generation/commands` from Studio,
Wizard and MCP. Revoice and remove-background still use
`POST /api/v1/tools/revoice` and `POST /api/v1/tools/remove-background`.
The native `/api/v1/tools/upscale` route remains for legacy clients. Workers:
`app/services/tools_upscale.py`, `app/shared/tools/`,
`app/_launch_runtime.py`. Poll and cancel with the shared job endpoints.

Related: [Video Editor](../video-editor/HOWUSEIT.md) (cut, do not regenerate),
[Character Kits Face Rig cleanup](../character-kits/HOWUSEIT.md)
(`POST /api/v1/character-kits/face-rig/cleanup` is a different rembg path),
[HTTP API](../../app/docs/API.md).

---

## 1. What this system is

| Tool | Accepts | Backend | Output |
|---|---|---|---|
| **Upscale / processors** | Image or video, depending on processor | FlashVSR, Lanczos and available native processors | New `_upscaled` PNG or video |
| **Revoice** | Video + 1–2 voice refs | SeedVC | New `_revoiced` clip (same container) |
| **Remove background** | Image | rembg U2Net | New `{stem}.no-background-{id}.png` |

Use Tools when the pixels (or voices) are already good and you need a
derivative. Use Studio generate when you need a new image/clip. Use Video
Editor when you only need trim, order, and export.

The three actions share the generation GPU slot, Activity footer, and
`GET /api/v1/status/{job_id}` / `POST /api/v1/cancel/{job_id}`. They are not
a second scheduler.

### Output folder versus Workspace collection

`workspace` on these routes is the **physical output folder**
(`default` or `[A-Za-z0-9][A-Za-z0-9_-]*`). It is not a logical Workspace
collection ID. Uploads use the virtual scope `__uploads__`. See
[domain model](../development/DOMAIN_MODEL_AND_ASSET_PROVENANCE.md).

---

## 2. Hard limits

1. **Never overwrite.** Every tool writes a new filename. A cancelled job
   deletes its partial output when the worker can settle the cancel.
2. **Exact source.** For version 2 upscale, put an exact asset ID or canonical
   local API media URL in `input.params.source`. Host paths, remote URLs and
   bare filenames are rejected. Native Tools routes also accept confined
   filenames/paths and a separate `asset_id`; do not mix those schemas.
3. **Source folder.** Keep the source folder distinct from the destination
   `workspace`. A file URL carries it in `?workspace=`; an explicit
   `source_workspace` must agree. Select a scope when an asset has multiple
   locations. Upload URLs use `__uploads__`. Preserve the full canonical URL.
4. **Conflicting aliases.** The native upscale/revoice endpoints accept
   `source`, `source_path`, and legacy `video_path`. Different values return
   `409`. The version 2 upscale contract accepts only `params.source`.
5. **Kind gates.** Revoice is video-only. Remove-background is image-only
   (`.png`, `.jpg`, `.jpeg`, `.webp`). Upscale images also allow
   `.bmp`, `.gif`, `.tif`, `.tiff`. Videos:
   `.avi`, `.m4v`, `.mkv`, `.mov`, `.mp4`, `.mpeg`, `.mpg`, `.webm`, `.wmv`.
6. **Instruction is metadata.** Remove-background accepts `instruction`
   (max 2 000 chars) and stores it on the job/sidecar. U2Net does **not**
   read it; the matte is the same with or without the note.

---

## 3. Operator workflow

1. Open Studio and choose **Tools** (Direct generation → Tools).
2. Pick **Upscale**, **Revoice**, or **Remove background**.
3. Set the source:
   - gallery card → **Use selected gallery image/clip**
   - resource selector: browse the library and confirm with **Choose**;
     **Cancel** keeps the current selection
   - upload through the same source field (image/video as allowed by the tool)
   - from a selected video: **Send to Tools** / quick upscale in the info bar
4. Set tool-specific parameters. Run. Upscale presents the prepared request
   before admission and returns a shared receipt. Watch the footer; the gallery
   refreshes on `completed`. Failed/cancelled tiles remain available to inspect.

Wizard has adapters for upscale and remove-background. It does not currently
expose a dedicated Revoice action; use the Tools panel for Revoice. MCP has the
shared `tools.upscale` operation; that entry does not imply shared operations
for all three tools. See [shared commands](../development/SHARED_NATIVE_COMMANDS.md).

---

## 4. Upscale

Built-in spatial choices include:

```
flashvsr2, flashvsr3, flashvsr4, flashvsr2pass2, flashvsr2pass4,
lanczos1.5, lanczos2
```

Additional processor choices are discovered from the server and filtered by
source kind and availability. Consult `GET /api/v1/generation/commands` for
the `tools.upscale` schema and the panel's processor options; the list above
is not the whole catalog. The shared command requires an explicit `method`.
Only the native legacy route defaults an omitted method to `flashvsr2`.

FlashVSR is model-based super-resolution (weights download on first use).
Lanczos is a fast classic resize. If Settings → Services has FlashVSR mode
`0`, the panel warns but still lets you pick a FlashVSR method.

- Images go through the spatial upsampler in still mode and always become a
  new PNG (`_upscaled`). Optional `seed` is an integer (`-1` default).
- Videos keep the existing audio-preserving pipeline and write a new clip
  (`_upscaled` + configured container).

```bash
curl -X POST "$HOCUSPOCUS_URL/api/v1/generation/commands" \
  -H "Content-Type: application/json" \
  -d '{
    "version": 2,
    "operation": "tools.upscale",
    "intent_id": "upscale-still-001",
    "input": {
      "workspace": "default",
      "params": {
        "source": "/api/v1/file/still.png?workspace=default",
        "source_kind": "image",
        "method": "lanczos2"
      }
    }
  }'
```

Replace the example source with an existing resource. Keep the same
`intent_id` when retrying an uncertain response to this request; choose a new
one for another intentional operation. Admission returns `receipt.result.job_id`
and `receipt.result.task_id`; it does not mean the file is complete. Follow the
job status or recover through `generation.receipt` as described in
[shared commands](../development/SHARED_NATIVE_COMMANDS.md).

Native legacy clients may keep using `/api/v1/tools/upscale` with the flat
body and `video_path` alias. That endpoint does not provide the shared
command receipt/replay contract; see [Tools command contract](../development/TOOLS_COMMANDS.md).

---

## 5. Revoice (SeedVC)

Body: `{ video_path, voice_ref_paths: [1–2 paths], mode?: "single"|"two",
diffusion_steps?: 25, cfg_rate?: 0.5, workspace? }`.

| Mode | Effect |
|---|---|
| `single` (default) | Replace every voice with the first reference |
| `two` | Detect two speakers; first → Voice A, second → Voice B; keep music and silence |

Supply two references for `two`; with only one, the worker falls back to
single-voice conversion. Any other `mode` string is coerced to `single`.
Voice refs may be audio or
video files resolved inside the destination folder or uploads. The worker
copies the source first, then converts the copy.

Failure cases you will actually see: clip has no audio, SeedVC is
unavailable, or no reference file could be resolved.

```bash
curl -X POST "$HOCUSPOCUS_URL/api/v1/tools/revoice" \
  -H "Content-Type: application/json" \
  -d '{
    "video_path": "take.mp4",
    "voice_ref_paths": ["ref-a.wav"],
    "mode": "single",
    "workspace": "default"
  }'
```

---

## 6. Remove background

Prefer `asset_id`. `source` alone is accepted. Destination `workspace`
defaults to the server active output folder.

```bash
curl -X POST "$HOCUSPOCUS_URL/api/v1/tools/remove-background" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "asset_image_123",
    "workspace": "default",
    "provenance": {"actor": "user"}
  }'
```

Accepted immediately with `job_id`, `task_id`, `root_task_id`, and frozen
`generation_details.model_type: rembg-u2net`. The sidecar records source
lineage, timings, and transparent-PNG metrics (`width`, `height`, `alpha`).

Face Rig overlay cleanup is a **different** endpoint
(`POST /api/v1/character-kits/face-rig/cleanup`) that also uses rembg U2Net
plus crop-to-alpha. Do not substitute one for the other.

---

## 7. Pitfalls

- Sending a `.bmp` / `.tif` to remove-background fails; those formats are
  upscale-only.
- Revoice on an image is rejected by both the panel and the HTTP
  `expected_kinds=("video",)` gate.
- `instruction` will not “preserve hair.” It is stored, not consumed.
- Two different `source` / `video_path` values fail with `409`, not a silent
  pick-one.
- Gallery URLs look like `/api/v1/file/clip.mp4?workspace=default`. Keep the
  query: it identifies the source folder. It is not part of the disk filename.
- Tools share the GPU lock with Studio generate. A long FlashVSR job blocks
  the next generation until it finishes or is cancelled.
