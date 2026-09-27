# The Oath of Cinders — layered heroes revision

Two vertical HocusPocus music films: English (3,926 frames / 30 fps) and Spanish (2,976 frames / 30 fps). This collection reuses the songs in `../ashes-oath/` and rebuilds the visual story with human protagonists, static architectural plates and independently moving scenery.

Open `index.html` from the running app to watch and download the films. Download `scenes.zip` and import any `.world3d.json` file in **Studios → Video 3D → Load scene**. Each scene is also published to the app's default workspace during native export. The source documents retain separate slots for scenery, architectural openings, characters, near objects, fog and dust. Use the editor's layer list to select a partly obscured object.

## Production choices

- The tower and arch have actual geometric openings (`imageLook.windows`); they remain static while a video plays behind them.
- The bridge uses the original painted stone texture with geometric cutouts. Automatic matting damaged its light stone edges, so that result was rejected.
- Character poses share a human face reference and a complete repeated costume description. Reference conditioning alone did not reliably preserve clothing.
- Character video is forward-only, normal speed, non-looping. Every accepted action is used once in each language. Other shots deliberately use still illustration layers, camera parallax and ambient motion.
- A small warm mote pulses gently on measured musical downbeats. Camera movement has no roll, spin or oscillating orbit.
- Each outgoing shot requests a 15-frame crossfade. The adjacent scene includes overlap handles, and its musical time starts at its actual assembled timeline position. Overlap is subtracted when validating total duration.
- Songs, subtitles and lyric timing are inherited from the previous native YuE2 generation and HocusPocus audio analysis. No new music generation is claimed for this revision.

## Native reproduction

The clients under `pinokio_agent/skills/api/Maestro-next.git/clients/` only submit or inspect native app operations. They do not replace HocusPocus with a separate compositor.

1. Generate reference images with `image_job_batch.py` (Story Lab MiniMax Image-01 jobs).
2. Submit H3 video generation and image/video background removal with `production_jobs.py` and explicit workspace/source workspace.
3. Open HocusPocus in a Chromium session with CDP enabled. Use `world3d_native_previews.mjs` to import each scene into the actual Video 3D editor and capture its native stage preview.
4. Use `world3d_export_batch.py` with `--base-url`, `--plan`, `--previews`, `--output-dir`, and a fresh `--intent-prefix`. It saves scenes, submits recoverable exports, polls the original tasks and downloads their canonical publications.
5. Use `world3d_assemble.py` with the same plan and render directory. It submits the clip sequence and original soundtrack to the native Video Editor, preserving each shot's outgoing transition.

Plans and assets use app-relative paths and contain no machine-specific host or model-cache paths. Export receipts and measured production times are in `production-report.json`. The saved scene documents contain the complete editable composition. Read-only FFmpeg checks validate final frames, duration, alpha and decoding.

## Findings for later improvement

- Image subject references preserve faces more reliably than costumes; costume and pose validation should precede animation admission.
- H3 sometimes reframes a full-body subject into a closer view. Review the whole source clip and compose an appropriate medium/close shot rather than displaying a clipped body.
- A default automatic background mask can remove pale stone detail. Architecture benefits from editable geometric openings.
- The editor currently times out a video load/seek after 15 seconds. During disk stalls this can reject a valid clip; the preview client now checkpoints completed documents and retries loading through the editor. A general app-level recovery flow would improve this.
- Native GPU work shares one queue. Intermittent disk stalls on the production machine increased wall time; per-job processing times and total elapsed time are reported separately.
- The current ambience clips are short source takes reused across different compositions. Within each shot they play once, forward, without stretching or reverse playback.
