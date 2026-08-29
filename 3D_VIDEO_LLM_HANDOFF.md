# 3D Video + LLM: test and fix handoff

Date: 2026-08-23  
Branch: `feat/3d-compositor-recipe`  
Runtime: Loreframe is online through Pinokio at `http://127.0.0.1:42003`.

## Product objective

An LLM must be able to turn a natural-language request into a precise, executable 3D-video plan using all Loreframe 3D-video tools:

1. Understand the requested subjects, persistent identities, ordered actions, camera, timing, setting, and effects.
2. Reuse images, videos, and GLBs selected from Loreframe or uploaded from disk.
3. In automatic mode, generate only genuinely missing assets; never regenerate a supplied image or GLB.
4. Produce a closed, validated recipe JSON and a deterministic compiled scene for every shot.
5. Preview the same result that will be recorded.
6. Render every requested shot in order, create a playable H.264 MP4, publish it in Videos, and retain the exact user prompt, full recipe, compiled scene, and source assets.

The target is not merely “LLM returns JSON”. Success means the natural-language intent survives the whole chain:

`prompt -> recipe -> asset resolution -> compiled shots -> rendered frames -> MP4 -> gallery metadata`

## Current implementation

- `ui/src/lib/sceneRecipe.ts`
  - Closed JSON schema, parser/repair helpers, semantic validation, manual-inventory constraints, motion/camera/effect presets, shot compiler.
- `ui/src/components/Sidebar/SceneRecipePanel.tsx`
  - Manual assets from Loreframe or disk, automatic missing-asset resolution, LLM recipe generation/repair, shot mounting.
- `ui/src/components/Sidebar/SceneAnimatorPanel.tsx`
  - DOM/WebGL preview, scene animation, browser `MediaRecorder`, recipe application, MP4 publication.
- `ui/src/api/client.ts`
  - Uploads, saved scenes, and the new scene-recording publication call.
- `app/_launch_runtime.py`
  - `POST /api/v1/scenes/recordings`: accepts the browser capture and metadata, calls FFmpeg, writes an MP4 plus `.meta.json`, and exposes it as a Videos output.
- `app/services/scene_recording.py`
  - Atomic WebM-to-H.264/yuv420p MP4 conversion.

Current changes are uncommitted. Preserve unrelated dirty files, especially Hunyuan/model3d work and the many untracked `scripts/` files. Do not stage everything with `git add -A`.

## Reproduced failures and evidence

### Failure A: model appears only near the end

Source browser capture:

`app/uploads/ebe752758d8b4d46885bcef354d44c67.webm`

Converted, playable MP4:

`app/outputs/2026-08-23-17h39m29s_Saucer-cruise_3d_e4ef64.mp4`

Properties: H.264, yuv420p, 1280x720, 30 fps, 5.13 s. It appears in Videos and its sidecar contains the exact prompt, recipe, scene, and both source assets. Its content is wrong: the starfield is visible throughout, while the GLB appears only near second 4.

Likely cause: `waitForModelViewers()` previously treated the existence and dimensions of model-viewer's canvas as “ready”. The canvas exists before the GLB has loaded. The current working tree now also requires `viewer.loaded === true`, waits for every visible model layer, and warms up for two animation frames. This change compiled, but has not yet passed a valid recording test.

### Failure B: empty MP4 is accepted as success

After the readiness change, a headless Chromium test produced:

`app/outputs/2026-08-23-17h47m56s_saucer-cruise-cruise-fixed_3d_fe4d8c.mp4`

This file is only 262 bytes. It has an MP4 container but no video stream. The API nevertheless returned HTTP 200, wrote metadata, listed it in Videos, and its thumbnail endpoint returns 500.

This proves two independent defects:

1. Browser capture can finish without encoded frames (headless/background throttling or an unreliable `captureStream(fps)` contract).
2. The backend validates only FFmpeg exit code and nonzero file size, not the presence of a decodable video stream.

The invalid 262-byte output should be deleted after it is no longer needed as evidence.

### Multi-shot functional gap

The recipe supports ordered `shots`, but `runRecipe()` mounts one shot for preview. It does not yet render every shot and concatenate them into one final video. A request such as “first it rises, then it flies left to right” cannot be considered complete until the final MP4 contains both actions in order.

## Fix order

### P0. Reject empty or corrupt recordings before publication

- Add a post-transcode FFprobe validation in `app/services/scene_recording.py`.
- Require exactly one readable video stream, width/height > 0, duration > 0, and decoded frame count > 0.
- For a declared five-second 30 fps scene, require a sensible lower bound (for example at least 135 decoded frames after CFR normalization).
- If validation fails, remove MP4 and sidecar/temp files and return a clear 400 error. Never add the file to the output scan cache/gallery.
- Add tests for a 262-byte empty MP4, no-stream MP4, truncated file, and a valid short WebM fixture.

Acceptance: the known 262-byte file is rejected; `/outputs/thumbnail/...` is never called for a failed publication.

### P0. Make browser recording deterministic

- Replace timing that depends only on `requestAnimationFrame` plus `canvas.captureStream(fps)`.
- Prefer `canvas.captureStream(0)` and call `CanvasCaptureMediaStreamTrack.requestFrame()` explicitly after each completed scene frame.
- Drive a fixed frame index from `0..round(duration*fps)-1`; derive scene time from `frameIndex / fps`, not wall-clock drift.
- For each frame:
  1. Set video/rig time and model orientation.
  2. Wait for media seek/render completion where required.
  3. Paint the composited 2D canvas.
  4. Call `requestFrame()` exactly once.
- Keep a real pacing clock only so `MediaRecorder` assigns usable timestamps; do not use wall time as the authoritative animation state.
- Fail in the browser when total chunks are implausibly small, and display a useful error instead of publishing.
- Test both visible Chromium and headless Chromium with background throttling disabled. If headless remains unsupported, document that and make the automated E2E use a headed virtual display.

Acceptance: a five-second 30 fps recording produces about 150 frames and never produces a header-only WebM/MP4.

### P0. Prove the GLB is actually drawable before recording

- Keep the current `loaded === true` check and two-frame warm-up.
- Strengthen it with a drawability probe: copy each model-viewer canvas to a small transparent probe canvas and verify nontransparent/nonuniform pixels.
- Do not return early when expected model layers exist but the DOM has no model-viewer yet.
- Distinguish “GLB loaded”, “WebGL canvas exists”, and “model pixels rendered” in error/status messages.
- Re-check after source changes and before every manual Export MP4, not only after applying a recipe.

Acceptance: recording cannot start while a model layer is blank; timeout names the offending layer/source.

### P0. Render the complete ordered recipe

Choose and implement one explicit contract:

- Recommended: render every recipe shot independently with stable assets, then concatenate the validated MP4 clips in shot order and publish one final recipe output.
- Alternative: compile all shots into one scene timeline with deterministic cut boundaries and keyframes.

Required behavior:

- One persistent recipe asset ID maps to one resolved GLB across every shot.
- The final duration equals the sum of shot durations (within mux tolerance).
- Final metadata stores the original recipe, per-shot compiled scenes, per-shot output/timing data, and final assembly details.
- Intermediate clips are hidden/grouped using the existing multiclip conventions.
- A failure in shot N is recoverable without regenerating completed assets or earlier valid shots.

Acceptance: “first lands, then cruises left to right” visibly contains both actions and one final gallery video.

### P1. Tighten the LLM execution contract

- Keep structured JSON/schema mode and the current repair pass.
- Add semantic validation before any asset generation:
  - every requested chronological beat maps to a shot or keyframe segment;
  - every visual layer resolves to a declared asset;
  - manual mode sources are exact inventory values;
  - no invented rig clips for unrigged GLBs;
  - one persistent subject identity reuses one asset ID;
  - no duplicate hero embedded in both plate prompt and GLB layer;
  - camera/effect layers use only supported presets;
  - coordinates and timing keep the subject visible for the intended interval.
- Return validation errors to the LLM as machine-readable paths, while preserving the original user intent verbatim.
- Show the final execution plan to the user before generation/recording: assets reused, assets to generate, shots, duration, camera, motion, and effects.

Acceptance: invalid recipes never start image/3D/video generation; repaired recipes retain every requested action.

## Test matrix

### Unit and contract tests

1. JSON extraction: plain JSON, fenced JSON, quoted JSON, brace noise, no object.
2. Schema: unknown keys, wrong version, missing assets/layers, invalid preset, out-of-range timing/coordinates.
3. Semantic inventory:
   - manual image + GLB uses exact filenames;
   - no generation calls occur when all assets are supplied;
   - automatic mode generates only missing assets;
   - one GLB identity is reused across shots.
4. Prompt coverage: Spanish and English prompts with two or more ordered actions; assert every action is represented.
5. Compiler: motion start/end, duration, opacity, camera, effect, rig clip, parallax, z-order, portrait/landscape.
6. MP4 finalizer: valid WebM, empty WebM, no video stream, corrupt stream, odd dimensions, 30/60 fps, atomic cleanup.

### Browser integration tests

Use one small checked-in or stable local fixture image and one small GLB. Do not invoke image/model generation in these tests.

1. Static GLB hold: model visible at 10%, 50%, and 90% of the clip.
2. `space-cruise`: model centroid moves monotonically left-to-right and is present through the intended interval.
3. `landing`: centroid moves top-to-bottom.
4. Spin: orientation changes while screen position remains correct.
5. Image/video plate + GLB + procedural effect: all layers visible with correct z-order.
6. Manual Export MP4 and recipe-driven Export MP4 use the same frame path.
7. Slow GLB load: recording waits; it does not capture background-only frames.
8. WebGL/context failure: recording fails cleanly and publishes nothing.

For visual assertions, sample frames at 10/30/50/70/90 percent and use a known-color/alpha fixture or segmentation-friendly model to measure presence and centroid. Do not rely only on file existence.

### End-to-end LLM scenarios

1. Manual: “Usa este fondo y este alien. Entra desde la izquierda, cruza girando y se detiene en el centro.”
2. Multi-shot identity: “El mismo alien aterriza, mira alrededor y después despega.”
3. Camera/effect: “La cámara se acerca lentamente mientras el robot flota; añade niebla, no generes otro robot.”
4. Auto missing-only: supplied GLB, missing plate; assert only the plate is generated.
5. Fully supplied: supplied plate + GLB; assert zero generation jobs.
6. Unrigged GLB request: asks to walk; LLM must choose compositor motion or explain the limitation, never invent a skeletal clip.
7. Portrait request and explicit duration.

## Final acceptance gate

All must pass before calling the feature complete:

- Valid H.264/yuv420p MP4 with a readable video stream.
- Resolution and fps match the scene.
- Duration is within 0.25 s of requested duration.
- Decoded frame count is at least 90% of `duration * fps` after CFR normalization.
- Required model is visible in the expected sampled frames.
- Motion direction/trajectory matches the selected preset and prompt.
- Every ordered shot/action appears in the final video.
- Manual supplied assets trigger zero generation jobs.
- Final output appears in Videos and thumbnail returns HTTP 200.
- Metadata contains the exact prompt, full recipe, compiled scene(s), asset IDs/sources/prompts, fps, resolution, duration, and assembly provenance.
- Failed/empty captures publish no file, no sidecar, and no gallery entry.

## Existing test status

- Python targeted tests: `4 passed` (`test_scene_recording.py`, `test_video_decode_metadata.py`). These do not yet catch the empty-stream MP4 defect and must be expanded.
- UI build: passes.
- ESLint on changed UI files: passes.
- Full UI suite: 146/147 pass. The single failure is the pre-existing/unrelated `directorPipelineLoadError.test.tsx` alert timing/behavior test.
- Recipe tests: pass, including closed schema, inventory constraints, identity reuse, and rig validation.

## Commands for the next agent

Start by following `AGENTS.md`: inspect `logs/api/start.js/latest` before debugging and preserve unrelated worktree changes.

```bash
git status --short --branch
tail -160 logs/api/start.js/latest
/home/ina/pinokio/bin/npm/bin/pterm status pinokio://127.0.0.1:42000/api/Maestro-next.git
app/env/bin/python -m pytest -q tests/test_scene_recording.py tests/test_video_decode_metadata.py
npm --prefix ui run build
```

Inspect the two evidence files:

```bash
ffprobe -v error -show_streams -show_format app/outputs/2026-08-23-17h39m29s_Saucer-cruise_3d_e4ef64.mp4
ffprobe -v error -show_streams -show_format app/outputs/2026-08-23-17h47m56s_saucer-cruise-cruise-fixed_3d_fe4d8c.mp4
```

Use `pinokio_agent/skills/api/Maestro-next.git/clients/browser_cdp.mjs` for browser recording checks. The temporary Chromium debug port used in this session was `9223`; do not assume it is still alive.

## Worktree safety

The intended 3D-video changes include:

- `app/_launch_runtime.py`
- `app/services/scene_recording.py`
- `app/shared/utils/video_decode.py`
- `tests/test_scene_recording.py`
- `tests/test_video_decode_metadata.py`
- `ui/src/api/client.ts`
- `ui/src/components/Sidebar/SceneAnimatorPanel.tsx`
- `ui/src/components/Sidebar/SceneRecipePanel.tsx`
- `ui/src/lib/sceneRecipe.ts`
- `ui/tests/sceneRecipe.test.mjs`
- `pinokio_agent/skills/api/Maestro-next.git/SKILL.md`
- `pinokio_agent/skills/api/Maestro-next.git/clients/browser_cdp.mjs`

Do not accidentally stage unrelated modifications in:

- `app/services/hunyuan3d/worker.py`
- `app/services/model3d_service.py`
- `app/services/hunyuan3d/__init__.py`
- `app/services/hunyuan3d/weight_integrity.py`
- unrelated root notes, scripts, logs, pipeline JSON files, and Hunyuan tests.
