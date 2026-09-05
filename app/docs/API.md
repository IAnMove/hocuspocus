# WanGP Python API

`shared/api.py` provides a lightweight in-process wrapper over WanGP's existing generation path.

The main goal is to let third-party code call WanGP directly, keep the last loaded model alive across requests, receive structured progress updates, and still capture the same stdout/stderr output that would normally go to the console.

**Please note that use of the WanGP API is subject to the WanGP Terms and Conditions. Any product that integrates WanGP should clearly disclose that it uses WanGP in both its user interface and its documentation.**

## Quick Start

```python
from pathlib import Path

from shared.api import init

session = init(
    root=Path(r"C:\WanGP"),
    cli_args=["--attention", "sdpa", "--profile", "4"],
)

settings = {
    "model_type": "ltx2_22B_distilled",
    "prompt": "Cinematic shot of a neon train entering a rainy station",
    "resolution": "1280x704",
    "num_inference_steps": 8,
    "video_length": 97,
    "duration_seconds": 4,
    "force_fps": 24,
}

job = session.submit_task(settings)

for event in job.events.iter(timeout=0.2):
    if event.kind == "progress":
        progress = event.data
        print(progress.phase, progress.progress, progress.current_step, progress.total_steps)
    elif event.kind == "preview":
        preview = event.data
        if preview.image is not None:
            preview.image.save("preview.png")
    elif event.kind == "stream":
        line = event.data
        print(f"[{line.stream}] {line.text}")

result = job.result()
if result.success:
    print(result.generated_files)
else:
    for error in result.errors:
        print(error.message)
```

## Main Entry Points

- `init(...) -> WanGPSession`
  - Creates a reusable session and eagerly loads the runtime. If HocusPocus
    already bound WanGP, it reuses that exact instance; in a standalone Python
    process it performs the one authorized import and binds it for all later
    calls.
- `WanGPSession.submit(source) -> SessionJob`
  - Starts a job from a settings dict, a manifest list, or a saved `.json` / `.zip` file.
- `WanGPSession.submit_task(settings) -> SessionJob`
  - Preferred single-task entrypoint.
- `WanGPSession.submit_manifest(settings_list) -> SessionJob`
  - Batch entrypoint for multiple tasks.
- `SessionJob.result() -> GenerationResult`
  - Waits for completion and returns a structured result object.
- `SessionJob.cancel()`
  - Requests cancellation of the active generation.

## `init(...)` Parameters

```python
session = init(
    root=Path(r"C:\WanGP"),
    config_path=Path(r"C:\WanGP\wgp_config.json"),  # optional
    output_dir=Path(r"C:\WanGP\outputs_override"),  # optional
    callbacks=MyCallbacks(),                        # optional
    cli_args=["--attention", "sdpa"],              # optional
    console_output=True,                           # optional, default=True
    console_isatty=True,                           # optional, default=True
)
```

- `root`
  - Path to the WanGP installation folder.
  - Example: `C:\WanGP`

- `config_path`
  - Optional path to `wgp_config.json`.
  - If omitted, WanGP uses `C:\WanGP\wgp_config.json`.
  - This must point to a file named `wgp_config.json`.

- `output_dir`
  - Optional override for generated outputs.
  - If omitted, WanGP uses the output paths defined in the config file.

- `callbacks`
  - Optional callback object. See the callback section below.

- `cli_args`
  - Optional WanGP startup flags.
  - Example: `["--attention", "sdpa", "--profile", "4"]`

- `console_output`
  - Enables or disables writing WanGP stdout/stderr to the real console.
  - Default: `True`
  - The stream object always receives a copy of stdout/stderr, regardless of this setting.

- `console_isatty`
  - Controls the TTY capability reported by the API's console capture wrapper.
  - Default: `True`
  - Keep this enabled if you want tqdm or other terminal-style progress output to behave like a live console stream even when WanGP is called from another Python process.

## Accepted Input Shapes

Relative attachment paths are normalized to absolute paths when the job is submitted.

- For direct settings dictionaries and `.json` settings files, the base is the API caller's current working directory at submit time.
- For `.zip` queue files, WanGP keeps the queue bundle behavior and resolves bundled media from the extracted queue contents.
- A few WanGP string-like fields are normalized for convenience. For example, `force_fps` may be passed as `24` or `"24"`.

### Single Task

For single-task use, the intended input is the task settings dictionary itself:

```python
settings = {
    "model_type": "qwen_image_20B",
    "prompt": "A red bicycle parked in front of a bakery",
    "resolution": "1024x1024",
    "num_inference_steps": 4,
    "image_mode": 1,
}

job = session.submit_task(settings)
```

### Manifest

`submit_manifest(...)` accepts a list of settings dictionaries:

```python
settings_list = [
    {
        "model_type": "qwen_image_20B",
        "prompt": "A quiet library at sunrise",
        "resolution": "1024x1024",
        "num_inference_steps": 4,
        "image_mode": 1,
    },
    {
        "model_type": "qwen_image_20B",
        "prompt": "A rainy alley with neon signs",
        "resolution": "1024x1024",
        "num_inference_steps": 4,
        "image_mode": 1,
    },
]

job = session.submit_manifest(settings_list)
```

### Saved Queue / Settings File

`submit(...)` also accepts:

- a `.json` settings file path
- a `.zip` saved queue path

Example:

```python
job = session.submit(Path(r"C:\WanGP\my_queue.zip"))
```

## Streaming Events

Each job exposes `job.events`, a `SessionStream`.

The stream yields `SessionEvent` objects:

```python
SessionEvent(
    kind="progress",
    data=ProgressUpdate(...),
    timestamp=1710000000.0,
)
```

Known `kind` values:

- `started`
  - Job accepted and session processing started.
- `progress`
  - Structured progress update.
- `preview`
  - RGB preview update.
- `stream`
  - One stdout/stderr line.
- `status`
  - WanGP status message.
- `info`
  - WanGP informational message.
- `output`
  - Raw output refresh event from WanGP.
- `refresh_models`
  - Raw model-refresh event from WanGP.
- `completed`
  - Final `GenerationResult`.
- `error`
  - One `GenerationError` record.

## Returned Objects

### `GenerationResult`

Returned by `job.result()`:

```python
GenerationResult(
    success=False,
    generated_files=[
        r"C:\WanGP\outputs\clip_001.mp4",
    ],
    errors=[
        GenerationError(
            message="Task 2 failed validation",
            task_index=2,
            task_id=2,
            stage="validation",
        ),
    ],
    total_tasks=3,
    successful_tasks=2,
    failed_tasks=1,
)
```

Fields:

- `success: bool`
  - `True` only when every submitted task completed without error.
- `generated_files: list[str]`
  - Absolute paths to every file generated by the job, including partial-success runs.
- `errors: list[GenerationError]`
  - Structured error records collected during the run.
- `total_tasks: int`
  - Number of tasks submitted in the job.
- `successful_tasks: int`
  - Number of tasks that completed successfully.
- `failed_tasks: int`
  - Number of tasks that failed or were cancelled.

`job.result()` does not raise generation-task failures. Instead, inspect `result.success` and `result.errors`.

### `GenerationError`

Delivered through `error` events, `on_error(...)`, and `GenerationResult.errors`:

```python
GenerationError(
    message="Task 2 did not complete successfully",
    task_index=2,
    task_id=2,
    stage="generation",
)
```

Fields:

- `message: str`
  - Human-readable error message.
- `task_index: int | None`
  - One-based task index when the error is associated with a specific task.
- `task_id: Any`
  - Task identifier from the manifest when available.
- `stage: str | None`
  - Error stage such as `validation`, `generation`, `cancelled`, or `runtime`.

### `ProgressUpdate`

Delivered through `progress` events and `on_progress(...)`:

```python
ProgressUpdate(
    phase="inference",
    status="Prompt 1/1 | Denoising | 7.2s",
    progress=54,
    current_step=4,
    total_steps=8,
    raw_phase="Denoising",
    unit=None,
)
```

Fields:

- `phase: str`
  - Normalized phase. Typical values:
  - `loading_model`
  - `encoding_text`
  - `inference`
  - `decoding`
  - `downloading_output`
  - `cancelled`
- `status: str`
  - Human-readable status string produced by WanGP.
- `progress: int`
  - Estimated percentage from `0` to `100`.
- `current_step: int | None`
  - Current inference step when available.
- `total_steps: int | None`
  - Total inference steps when available.
- `raw_phase: str | None`
  - Original WanGP phase label before normalization.
- `unit: str | None`
  - Optional progress unit if WanGP provides one.

### `PreviewUpdate`

Delivered through `preview` events and `on_preview(...)`:

```python
PreviewUpdate(
    image=<PIL.Image.Image image mode=RGB size=800x200>,
    phase="inference",
    status="Prompt 1/1 | Denoising",
    progress=54,
    current_step=4,
    total_steps=8,
)
```

Fields:

- `image: PIL.Image.Image | None`
  - RGB preview image generated from WanGP's latent preview payload.
- `phase`, `status`, `progress`, `current_step`, `total_steps`
  - Same interpretation as `ProgressUpdate`.

### `StreamMessage`

Delivered through `stream` events and `on_stream(...)`:

```python
StreamMessage(
    stream="stdout",
    text="New video saved to Path: C:\\WanGP\\outputs\\clip_001.mp4",
)
```

Fields:

- `stream: str`
  - Usually `stdout` or `stderr`.
- `text: str`
  - One redirected line of console output.

### `SessionEvent`

Generic event wrapper:

```python
SessionEvent(
    kind="stream",
    data=StreamMessage(stream="stdout", text="Model loaded"),
    timestamp=1710000000.0,
)
```

Fields:

- `kind: str`
  - Event type.
- `data: Any`
  - Payload object for that event.
- `timestamp: float`
  - Event creation time.

## Callback Object

You can pass a callback object to `init(...)` or `WanGPSession(...)`.

Supported callback methods:

- `on_progress(progress_update)`
  - Called when WanGP emits a structured progress update.
  - Use this for progress bars, step counters, and status text.

- `on_preview(preview_update)`
  - Called when a preview image is available.
  - Use this when you want live RGB preview frames during inference.

- `on_stream(stream_message)`
  - Called for every redirected stdout/stderr line.
  - This is the programmatic equivalent of watching the terminal output.

- `on_status(text)`
  - Called for WanGP status messages.
  - Use this if you want coarse status without parsing full progress objects.

- `on_info(text)`
  - Called for informational messages.

- `on_output(data)`
  - Called for raw WanGP output refresh events.
  - This is a low-level hook and is usually not needed by third-party integrations.

- `on_complete(result)`
  - Called when the job finishes.
  - Receives a `GenerationResult`.

- `on_error(error)`
  - Called each time WanGP reports a task or runtime error.
  - Receives a `GenerationError`.

- `on_event(session_event)`
  - Generic catch-all event hook.
  - Called alongside the specific callback above, not instead of it.

Example:

```python
class Callbacks:
    def on_progress(self, progress):
        print("progress:", progress.progress, progress.phase)

    def on_preview(self, preview):
        if preview.image is not None:
            preview.image.save("latest_preview.png")

    def on_stream(self, line):
        print(f"[{line.stream}] {line.text}")

    def on_complete(self, result):
        print("success:", result.success)
        print("generated:", result.generated_files)

    def on_error(self, error):
        print("error:", error.message)
```

Full signature example:

```python
from shared.api import GenerationError, GenerationResult, PreviewUpdate, ProgressUpdate, SessionEvent, StreamMessage


class VerboseCallbacks:
    def on_progress(self, progress: ProgressUpdate) -> None:
        print("progress", progress.progress, progress.current_step, progress.total_steps)

    def on_preview(self, preview: PreviewUpdate) -> None:
        print("preview", preview.phase, preview.image.size if preview.image is not None else None)

    def on_stream(self, line: StreamMessage) -> None:
        print(line.stream, line.text)

    def on_status(self, text: str) -> None:
        print("status", text)

    def on_info(self, text: str) -> None:
        print("info", text)

    def on_output(self, data: object) -> None:
        print("output", data)

    def on_complete(self, result: GenerationResult) -> None:
        print("success", result.success)
        print("files", result.generated_files)

    def on_error(self, error: GenerationError) -> None:
        print("error", error.stage, error.task_index, error.message)

    def on_event(self, event: SessionEvent) -> None:
        print("event", event.kind)
```

## Cancellation

```python
job = session.submit_task(settings)
job.cancel()
```

Cancellation is cooperative and forwards WanGP's normal abort signal to the active model. A cancelled run completes with `result.success == False` and a cancellation entry in `result.errors`.

## Story Lab

Story generation is checkpointed and asynchronous. Start with
`POST /api/v1/stories/generate/start`, poll
`GET /api/v1/stories/generate/status/{job_id}`, resume with
`POST /api/v1/stories/generate/resume/{job_id}`, or cancel between stages with
`POST /api/v1/stories/generate/cancel/{job_id}`. Supported scopes are `all`,
`overview`, `world`, `characters`, `relationships`, and `structure`. Full
generation runs overview, cast, world, relationships, and dramatic structure as
separately validated stages; completed stages survive a later failure.

```bash
curl -X POST "$MAESTRO_URL/api/v1/stories/generate/start" \
  -H "Content-Type: application/json" \
  -d '{
    "scope": "all",
    "premise": "A cartographer discovers that her hand-drawn islands are becoming real.",
    "language": "Español",
    "genre": "Adventure",
    "tone": "Mysterious",
    "audience": "General",
    "writingProvider": "maestro",
    "project": {}
  }'
```

External per-story overrides use the same isolated provider fields as Comic
Director: `writingProvider`, `writingModel`, and `writingBaseUrl`. Credentials
are read from Settings → Services and are never accepted in the request or
embedded in the returned story.

```javascript
const job = await fetch(`${base}/api/v1/stories/generate/start`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    scope: 'characters',
    premise: story.premise,
    language: story.language,
    genre: story.genre,
    tone: story.tone,
    audience: story.audience,
    instruction: 'Make the rival sympathetic and give both leads distinct voices',
    writingProvider: 'minimax',
    writingModel: 'MiniMax-M3',
    project: story,
  }),
}).then(r => r.json())

let status
do {
  await new Promise(resolve => setTimeout(resolve, 1000))
  status = await fetch(`${base}/api/v1/stories/generate/status/${job.jobId}`).then(r => r.json())
} while (!['completed', 'failed', 'cancelled'].includes(status.status))
if (status.status !== 'completed') throw new Error(status.error || status.message)
const response = status.result
```

```python
import time
import requests

job = requests.post(f"{base}/api/v1/stories/generate/start", json={
    "scope": "world",
    "premise": story["premise"],
    "language": "English",
    "genre": "Fantasy",
    "tone": "Melancholic",
    "audience": "General",
    "writingProvider": "deepseek",
    "writingModel": "deepseek-v4-pro",
    "project": story,
}).json()
while True:
    status = requests.get(
        f"{base}/api/v1/stories/generate/status/{job['jobId']}"
    ).json()
    if status["status"] in {"completed", "failed", "cancelled"}:
        break
    time.sleep(1)
result = status["result"]["result"]
```

For backward compatibility, `POST /api/v1/stories/generate` remains available
for a single section only. Full `scope: "all"` requests must use the durable
start/status workflow.

## Comic preproduction and animatics

Comic Director planning is asynchronous: start with `POST /api/v1/director/comic/plan/start`, then poll `GET /api/v1/director/comic/plan/status/{job_id}`. Existing plans can be story-edited without regenerating artwork through `POST /api/v1/director/comic/story/revise`, or lettered/translated one page at a time through `POST /api/v1/director/comic/text/page`.

Story Lab adaptations may also supply `storyContext`, an editable plain-text
bible containing the canonical plot, beats, relationships, character arcs and
locations, plus `sourceStory: {id, revision, title}` for provenance. Comic
Director treats this material as canon while still allowing the user to edit it
before starting the plan. Character records and their reference asset IDs remain
the source of truth when the writing LLM returns the plan.

`POST /api/v1/comics/generate/minimax` follows MiniMax's official `image-01`
image-to-image request shape. Send one optional `subject_reference` source; the
backend resolves a Maestro output/upload to a base64 `image_file` and sends
`subject_reference: [{"type": "character", "image_file": "..."}]`. MiniMax
supports one identity reference per image request, so group panels use the first
visually prioritised character with an available reference and describe the
remaining cast from the locked character bible. `aspect_ratio` accepts `1:1`,
`16:9`, `4:3`, `3:2`, `2:3`, `3:4`, `9:16`, or `21:9`.

Director and Story Lab film adaptations can select the virtual image model ID
`minimax:image-01` in their normal `image_model` field. This routes shot-frame
generation through the same external Image-01 client while the independently
selected video model (for example local `minimax_h3`) remains unchanged.
Director maps its requested frame resolution to the nearest supported MiniMax
aspect ratio, sends at most one prioritised character identity reference, and
does not apply local image LoRAs. The credential is read only from
Settings → Services; it is not accepted in pipeline payloads or persisted in
output metadata.

Comic recovery checkpoints are output-folder-scoped and durable. Create one with
`POST /api/v1/comics/history`, list versions with
`GET /api/v1/comics/history` (optionally `?comic_id=...`), and load a version
with `GET /api/v1/comics/history/{snapshot_id}`. Identical consecutive
snapshots are de-duplicated and the newest 40 versions per comic are retained.
The editor creates these checkpoints automatically after editing pauses and
before replacing the open comic.

```bash
curl -X POST "$MAESTRO_URL/api/v1/comics/history" \
  -H "Content-Type: application/json" \
  -d '{"project": {"version": 2, "id": "comic-123", "pages": [{}], "assets": {}}, "reason": "Manual checkpoint"}'
curl "$MAESTRO_URL/api/v1/comics/history?comic_id=comic-123"
```

All three narrative endpoints accept the optional fields `writingProvider`, `writingModel`, and `writingBaseUrl`. `writingProvider` may be `maestro`, `deepseek`, `minimax`, `openai`, or `openai-compatible`. Named DeepSeek, MiniMax, and OpenAI profiles always use their fixed official API hosts; the compatible profile uses the URL and optional key explicitly saved under Settings → Services. Credentials are never accepted from, or embedded in, comic JSON. DeepSeek supports `deepseek-v4-pro` and `deepseek-v4-flash`; translation requests are always resolved to Flash in the backend even when Pro is selected for writing. MiniMax supports `MiniMax-M3`, `MiniMax-M2.7`, and `MiniMax-M2.7-highspeed` for writing and reuses the same MiniMax credential as image generation, while keeping `writingModel` independent from the comic's `imageModel`. Older comics that stored an official DeepSeek or OpenAI host as `openai-compatible` are migrated to the matching named profile.

`POST /api/v1/comics/animatic` accepts ordered, uploaded lettered-panel images and queues a 1080p MP4 render. Poll the returned job with the Video Editor status endpoint.

```bash
curl -X POST "$MAESTRO_URL/api/v1/comics/animatic" \
  -H "Content-Type: application/json" \
  -d '{
    "comic_id": "comic-123",
    "comic_title": "My comic",
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "transition": "crossfade",
    "transition_duration": 0.35,
    "panels": [
      {"source": "/api/v1/uploads/panel.png", "page_number": 1, "panel_number": 1, "duration": 3, "motion": "push-in", "script": "[Caption] Opening"}
    ]
  }'
```

```python
import requests

base = "http://127.0.0.1:7860"
job = requests.post(f"{base}/api/v1/comics/animatic", json={
    "comic_title": "My comic", "width": 1080, "height": 1920, "fps": 30,
    "transition": "dissolve", "transition_duration": 0.35,
    "panels": [{"source": "/api/v1/uploads/panel.png", "duration": 3, "motion": "pan-right"}],
}).json()
status = requests.get(f"{base}/api/v1/video-editor/export/{job['job_id']}").json()
```

```javascript
const job = await fetch('/api/v1/comics/animatic', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ comic_title: 'My comic', width: 1920, height: 1080, fps: 30,
    transition: 'crossfade', transition_duration: 0.35,
    panels: [{ source: '/api/v1/uploads/panel.png', duration: 3, motion: 'pull-out' }] }),
}).then(response => response.json());
```

## Video Editor HTTP API

The React Video Editor (`ui/src/features/video-editor/`) keeps the timeline in the browser. The server only probes media, extracts frames, and queues FFmpeg exports. Strip `?workspace=` from gallery URLs before sending a `source` — `services.media_refs.parse_media_ref` does this on the server, but a filename-with-query will not resolve.

Supported extensions: `.mp4`, `.webm`, `.mov`, `.mkv`, `.avi`, `.m4v`.

```bash
curl -X POST "$MAESTRO_URL/api/v1/video-editor/probe" \
  -H "Content-Type: application/json" \
  -d '{"source": "shot_a.mp4", "workspace": "default"}'
```

`POST /api/v1/video-editor/export` returns **202** and accepts 1–100 clips. Width/height must be even and in 240–3840. `fps` must be `24`, `25`, `30`, `50`, or `60`. Transition names: `none`, `crossfade`, `fade-black`, `wipe-left`, `slide-left`, `slide-right`, `circle-open`, `dissolve`, `pixelize`, `blur`, `zoom-in`, `later-clock`, `later-tropical`, `later-cinematic`. `transition_duration` is 0.05–5 seconds; `later-*` inserts a time card (duration also clamped to ≥0.5 s at render). Poll `GET /api/v1/video-editor/export/{job_id}`; cancel with `POST /api/v1/video-editor/export/{job_id}/cancel` (deferred to the next FFmpeg boundary). The completed MP4 sidecar uses Video Editor metadata contract v2: `params.video_editor.source_manifest` embeds each available source sidecar (including scene recipe, prompts, audio references and model metadata) without absolute paths. Missing or malformed legacy sidecars are recorded per clip and do not fail the export; nested editor manifests are omitted to prevent recursive growth.

```python
import requests

base = "http://127.0.0.1:7860"
job = requests.post(f"{base}/api/v1/video-editor/export", json={
    "name": "final_cut",
    "width": 1280,
    "height": 720,
    "fps": 30,
    "clips": [{
        "source": "shot_a.mp4",
        "trim_start": 0,
        "trim_end": 4.2,
        "fit": "fit",
        "transition": "crossfade",
        "transition_duration": 0.4,
    }],
}).json()
status = requests.get(f"{base}/api/v1/video-editor/export/{job['job_id']}").json()
```

`POST /api/v1/video-editor/screenshot` writes a PNG (`generation_mode: "image"`) at `{source, time, name?, workspace?}`. Character Creator uses it for Hunyuan views.

## Image background removal

`POST /api/v1/tools/remove-background` queues a standalone image tool job. It
uses the shared rembg U2Net adapter, never overwrites the source, and publishes
the transparent PNG plus a canonical `.meta.json` asset manifest in the
destination workspace. Use an exact `asset_id` from `GET /api/v1/assets?kind=image`
whenever possible; `source` may be the exact filename, an `/api/v1/file/...`
URL, or an absolute path already inside the selected uploads/workspace root.
`source_workspace` is required when the source belongs to another output
folder. Poll `GET /api/v1/status/{job_id}` and cancel with
`POST /api/v1/cancel/{job_id}`.

```bash
curl -X POST "$HOCUSPOCUS_URL/api/v1/tools/remove-background" \
  -H "Content-Type: application/json" \
  -d '{
    "asset_id": "asset_image_123",
    "workspace": "default",
    "instruction": "preserve the hair edges",
    "provenance": {"actor": "user"}
  }'
```

The response is accepted immediately with `job_id`, canonical task IDs and
frozen model details (`rembg-u2net`). The Activity/task record reports queued,
running, completed, failed or cancelled state; the derived asset exposes the
source asset ID, tool/capability, instruction, model/backend, timings and
transparent-PNG technical metadata.

## Tools upscale

`POST /api/v1/tools/upscale` is one shared post-processing action for either a
still image or a video. Send `{ "source": "image.png", "source_kind":
"image", "asset_id": "...", "source_workspace": "...", "method":
"flashvsr2", "workspace": "default" }` for an image, or keep the legacy
`video_path` field with `source_kind: "video"` for a clip. Supported image
formats are `.bmp`, `.gif`, `.jpeg`, `.jpg`, `.png`, `.tif`, `.tiff`, and
`.webp`; supported video formats are `.avi`, `.m4v`, `.mkv`, `.mov`, `.mp4`,
`.mpeg`, `.mpg`, `.webm`, and `.wmv`. The source must be an exact asset, upload, or
file inside the selected workspace roots; path traversal and mismatched asset
IDs/kinds are rejected. Images use the existing spatial upsampler in still
mode and produce a new PNG beside the source. Videos retain the existing
audio-preserving pipeline and produce a new video. Neither path overwrites its
source. Poll the returned job with `GET /api/v1/status/{job_id}` and cancel it
with `POST /api/v1/cancel/{job_id}`. Activity and the canonical asset manifest
retain the source lineage, method, workspace, provenance, and execution mode.

## Gallery mix kinds

`GET /api/v1/outputs` accepts `result_kind=music_video|trailer|series_episode` (plus the existing `media_type`, `multiclip_only`, `favorites_only`, `search`, `workspace`, `limit`, `offset`). Classification lives in `services.output_result_kind` and applies only to **assembled** filenames (`multiclip`, `_mv.mp4`, `_movie.mp4`, `_rejoin_multiclip.mp4`, `_series_assembly`). Requesting `series_episode` also matches `chapter`. When `result_kind` is set, pagination is bypassed and every match is returned.

`POST /api/v1/outputs/rejoin` (`{ "group_id", "audio_file"? }`) and `POST /api/v1/director/pipelines/{pid}/rejoin` concatenate generated shots. With two or more clips and no external driving audio, `services.mix_concat` holds the last frame 0.5 s and crossfades ~0.4 s; FFmpeg failure falls back to a hard concat.

## Character sheet describe-refs

`POST /api/v1/characters/describe-refs` uses hosted MiniMax-M3 vision (not the local LLM) and requires the MiniMax key in Settings → Services.

```bash
curl -X POST "$MAESTRO_URL/api/v1/characters/describe-refs" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "character",
    "image_paths": ["subject.png"],
    "roles": ["subject"],
    "workspace": "default"
  }'
```

`kind` is `character` or `object` (default `character`). `roles` are `subject`, `face`, `outfit`, `extra`, or `accessory`; missing/invalid roles become `subject` for index 0 and `extra` otherwise. Response: `{ "a_prompt", "kind" }`. `400` if `image_paths` is empty, a file is missing, or the API key is unset.

## Character Kits

Character Kits are reusable 2D cutout puppets. Their current HTTP routes are
scoped to a physical output folder. The query/body field is named `workspace`
for compatibility; it is **not** the ID of a logical Workspace collection.
Logical collections use `/api/v1/workspace-collections` and only group project,
asset, and Production IDs. See [`docs/character-kits/HOWUSEIT.md`](../../docs/character-kits/HOWUSEIT.md)
for the operator workflow and [the domain contract](../../docs/development/DOMAIN_MODEL_AND_ASSET_PROVENANCE.md).

Set the base URL in the examples to your running HocusPocus instance:

```bash
export HOCUSPOCUS_URL=http://127.0.0.1:7860
```

- `GET /api/v1/character-kits/library?workspace=default` — reads the normalized
  `{output-folder}/.character-kit-library-v1.json`, or returns an empty
  `{ "version": 1, "revision": 0, "activeId": "", "kits": {} }` when it is
  missing.
- `PATCH /api/v1/character-kits/library/kits/{kit_id}` — creates or replaces one
  kit with `{ workspace, baseRevision, kit, makeActive? }`; neighbours are not
  replaced. `makeActive` defaults to true. A stale revision returns `409` with
  `code: character_kit_revision_conflict`, `expectedRevision`, and
  `currentRevision`.
- `DELETE /api/v1/character-kits/library/kits/{kit_id}` — body
  `{ workspace, baseRevision }`; `404` if the kit is absent. Source files are
  intentionally retained.
- `POST /api/v1/character-kits/face-rig/cleanup` — body
  `{ workspace, source, padding? }`, where `padding` is 0–64 (default 8). The
  endpoint runs rembg U2Net + crop-to-alpha, writes a new PNG, and never
  overwrites `source`. Sources must be inside uploads or the selected output
  folder; disallowed/missing images return `400`/`404`.

The output-folder token is `default` or `[A-Za-z0-9][A-Za-z0-9_-]*`. Kit mouth
keys are `closed`, `small`, `wide`, and `round`; eye keys are `open` and
`blink`. `blob:` sources are rejected, and the UI-only `lookNotes` field is
stripped when the kit is normalized for persistence.

```bash
curl "$HOCUSPOCUS_URL/api/v1/character-kits/library?workspace=default"

curl -X PATCH "$HOCUSPOCUS_URL/api/v1/character-kits/library/kits/luma" \
  -H "Content-Type: application/json" \
  -d '{
    "workspace": "default",
    "baseRevision": 0,
    "kit": {
      "version": 1, "id": "luma", "name": "Luma", "style": "cutout",
      "base": {
        "id": "luma-base", "name": "Luma base", "source": "luma-base.png",
        "kind": "image", "alphaStatus": "transparent", "reviewState": "approved"
      },
      "poses": {}, "mouth": {}, "eyes": {},
      "anchors": { "base": { "mouth": { "offsetX": 0, "offsetY": -18, "scale": 0.05, "rotation": 0 } } },
      "provenance": []
    }
  }'
```

## Director pipeline threads

These routes always use the server active output folder. They do not accept `?workspace=`.

- `GET /api/v1/director/pipelines` / `GET /api/v1/director/pipelines/active` / `GET /api/v1/director/pipelines/{pid}` — list or load. `{pid}` hydrates an empty `clips` array from `clip_plans` or `planned_clips` and sets `queue_source` to `clips`, `clip_plans`, or `planned`. List accepts `limit` and `offset` (newest first); `limit=0` (the default) returns the full list, while the Workspaces tab pages 8 at a time and uses `total` for “load more”.
- `PUT /api/v1/director/pipelines/{pid}/clips/{clip_index}/prompt` — optional `video_prompt`, `image_prompt`, `soundtrack_drive`. `true` writes an `audio_driven` / `lip_sync_critical` plan; `false` writes `music_driven` and clears `_director_dialogue_beats`. `409` while the pipeline is active.
- `POST /api/v1/director/pipeline/{pid}/resume` and `POST /api/v1/director/pipeline/{pid}/continue` use the singular `pipeline` path.
- Batch prompt rewrite is UI-only: loop `POST /api/v1/llm/generate` (local LLM) then PUT the chosen prompts.

Operator notes: `docs/video-editor/HOWUSEIT.md`, `docs/workspaces/HOWUSEIT.md`, and `docs/character-kits/HOWUSEIT.md`.
