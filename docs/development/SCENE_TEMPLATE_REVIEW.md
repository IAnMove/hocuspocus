# Scene Template Review sandbox

This tool reviews the candidate SceneTemplate catalog through the real
`SceneTemplateReviewPage` and `SceneAnimatorPanel`. It does not call a video
provider, an LLM, a model download service or another HocusPocus application.
Images and GLBs come from the catalog's procedural data URIs, or from local files
given with `--assets` (below). MP4 export is the existing browser
compositor/exporter running under Playwright Chromium.

## Run

From the repository root:

```bash
npm --prefix ui run scene:review
```

The equivalent command from `ui/` is:

```bash
npm run scene:review
```

The default binds only `127.0.0.1` on an ephemeral port, creates a fresh
directory under the OS temporary directory, and prints:

```text
REVIEW_OUTPUT_DIR=/tmp/hocus-scene-template-review-…
REVIEW_URL_LOCAL=http://127.0.0.1:…/scene-template-review
```

The process remains open so the user can inspect the gallery and editor. Stop
it with Ctrl-C. The in-memory output index is intentionally not recovered after
a restart; the fresh directory remains available for inspection.

To render every card the catalog lists (`ALL_SCENE_TEMPLATES`, read at run time)
with the real browser exporter and leave the server open afterwards:

```bash
npm --prefix ui run scene:review -- --render
```

Specific IDs may be appended after `--render` for a short review, for example
`--render cinema-establishing space-cruise`. Any ID the catalog resolves is
accepted, so an alias renders as its surviving card with the alias's preset. A
render failure sets exit code 1 and writes a `status: "render-failed"` JSON
record. It never creates a fake MP4, PNG or success record in place of the
failure.

### Real assets (`--assets`)

Approval needs renders with real pictures, not the demo art:

```bash
npm --prefix ui run scene:review -- --render --assets review-assets.json [card-id ...]
```

The path resolves from the folder the command was typed in; the files in the plan
resolve from the plan's folder. A plan maps slot names to local files:
`subject_1`, `subject_2`, `background`, `prop_1`, `prop_2`, `foreground`. The old
names are read too (`hero` is `subject_1`, `plate` is `background`, `prop` is
`subject_2` on `cinema-two-shot` and `music-duet` and `prop_1` elsewhere); one
layer naming a slot twice (`hero` and `subject_1`) fails with
`slot_alias_conflict`. A plain `{slot: file}` object applies to every card. The
sectioned form layers a default, a family and a card, later layers winning, and a
layer may carry the card's controls (choice values, `duration`, `bpm`...), which go
to the compiler as they are:

```json
{
  "default": {"subject_1": "singer.png", "subject_2": "dancer.png", "background": "stage.png", "prop_1": "mic.png"},
  "families": {"space": {"subject_1": "ship.glb", "prop_1": "ship-two.glb", "background": "nebula.png"}},
  "cards": {"music-pulse": {"controls": {"camera": "sweep"}}, "music-duet": {"background": "loop.mp4"}}
}
```

A `.png`, `.jpg` or `.webp` is a picture, a `.glb` a model and an `.mp4` or
`.webm` a video; the slot must accept that kind. A card with a required slot the
plan leaves empty fails with a message naming the slot, and the other cards still
render; a `cards.<id>` entry that names a slot the card does not have fails too.
Cutouts should carry transparency. The files are copied once into the run's
`inputs/` directory (named by content, `asset-<sha256>.<ext>`) and served from there
like any indexed input: pictures up to 4 MiB, GLBs and videos up to 32 MiB, 64
inputs and 128 MiB in all. Without `--assets` the cards use the inline demo art as
before. `ui/tests/fixtures/sceneTemplateReview/assets.json` is a small working plan.

The provider-free HTTP contract can be checked without a browser or render:

```bash
cd ui
npm exec --offline -- tsx --tsconfig tsconfig.app.json --test tests/sceneTemplateReviewServer.test.mjs
```

The asset plan, the staging, the contact sheet and the index are checked the same
way, with the real catalog and compiler and no browser (the sheet test needs ffmpeg
and is skipped without it):

```bash
cd ui
npm exec --offline -- tsx --tsconfig tsconfig.app.json --test tests/sceneTemplateReviewAssets.test.mjs
```

LAN review is opt-in and accepts only an RFC1918 IPv4 address that is present
on a local network interface:

```bash
npm --prefix ui run scene:review -- --host YOUR_LOCAL_PRIVATE_IPV4
```

Replace `YOUR_LOCAL_PRIVATE_IPV4` with an address on your own local interface;
omit `--port` to avoid collisions. This is a local development tool, not a public
server: do not expose it through port forwarding or an internet tunnel.
LAN access is **read-only and unauthenticated**, for a trusted network only.
Use the loopback editor to save scenes or recordings. It is not a secure
multi-user service or the application's Library backend.
Dependencies must already be installed with the repository's UI setup. Rendering
requires the Playwright Chromium browser, plus `ffmpeg` and `ffprobe` on PATH.
The tool does not install them or download anything automatically.

Wildcard binds (`0.0.0.0`), public addresses and non-local hostnames are
rejected. The tool still prints the loopback URL; when LAN mode is enabled it
also prints `REVIEW_URL_LAN`.

## Sandbox contract

- The actual UI is built by Vite into the run's temporary `ui/` directory and
  served as indexed static files, not through a development server. There is no
  HMR/websocket or source-file endpoint. `/api` and `/classic` never proxy to the
  live backend. Known review routes are handled locally; unknown
  application APIs return HTTP 403 and are recorded by the status endpoint
  with a bounded diagnostic list.
- Every request must carry a `Host` header for the served loopback address
  (`127.0.0.1`, `localhost`, or the explicitly selected local RFC1918 address)
  and port. This keeps a loopback socket from accepting a DNS-rebinding host.
- POST requests with an `Origin` other than the served host or loopback on the
  same port return HTTP 403 before reading or writing a body.
- Request bodies are capped at 40 MB. Saved scene and recording names are
  generated UUIDs; file reads resolve through the server's in-memory index, not
  arbitrary paths supplied by a URL.
- Writes are serialized and restricted to the loopback listening socket. The
  conservative HTTP write budget is 128 outputs / 256 MiB (including the exact
  recording-sidecar bytes);
  partial I/O failures do not refund reservations. A request times out after
  30 seconds; incomplete headers after 10 seconds. Start a fresh sandbox when
  its budget is exhausted. Generated files remain for inspection, not auto-deleted.
  This is not a quota for the entire temporary directory: the trusted local CLI's
  build, preview copies and failure records are outside this HTTP write budget.
- Snapshots require `provided_only`, valid Scene v1 layer types, a safe template
  ID, at most 24 layers, 1920×1080, 30 seconds, and no audio tracks. Asset sources
  must be inline or relative references to this sandbox's indexed files. Absolute URLs
  (including another loopback hostname),
  unregistered local references, blob URLs and disk paths are refused on save.
- CSP restricts interactive browser media/network requests to this origin,
  data and blob sources; additional no-referrer/nosniff/frame-denial headers
  are sent. The production application's API remains outside this tool.
- Scene saves and MP4 recordings are written only below the run's `exports/`
  directory. Render previews and metadata are written only below `previews/`.
- The editable scene is saved and read back before each MP4 export. Each
  successful template has `<template-id>.mp4`, `<template-id>.png` (a poster at
  1.5 s), `<template-id>.sheet.png` (a 3x2 contact sheet of frames from the middle
  of six equal slices, painted by ffmpeg from the MP4) and `<template-id>.json`.
  Metadata includes catalog/template versions, the compiled card id, variant
  (`coral` or `assets`), the controls and assets used (with the files' SHA-256),
  render status, source HEAD SHA, dirty state, MP4 SHA-256, dimensions,
  duration, measured FPS, editable-scene filename/hash, and the exact scene
  snapshot sent to the recording endpoint. A preview is published only after
  page-error, `ffprobe` dimensions/FPS/duration, and metadata checks pass.
- Metadata also records Node/Playwright/Chromium/ffmpeg/ffprobe versions, poster
  hash and input-reference hashes. Git HEAD and tracked-diff digest are checked
  before/after render. Dirty/untracked content is explicitly not fully reproducible;
  a URL hash is not a hash of remote media bytes. Merge/release state is not inferred.
- Failed renders receive a uniquely named `*.failure-<uuid>.json` record. The
  failure path never overwrites a success record or masks the original error
  when a same-name write is not available.
- The run ends with one `review.json` in `previews/` (printed as `REVIEW_INDEX`):
  per card its id, compiled card id, files (MP4, sheet, poster, metadata),
  duration, controls and assets, plus the failures, the plan path and the source
  snapshot.
- The status is `rendered-not-approved`: a correct local render is evidence for
  review only, never an automatic catalog approval. The integrator sets
  `reviewStatus: approved` on the cards that pass; the owner can override in the
  app's review page.

The HTTP status endpoint is available at
`/api/v1/scene-template-review/status` while the process is running. It reports
the blocked API paths and the current in-memory output count without claiming
durable persistence.

The HTTP recording test uses a synthetic `ftyp` header and checks **transport and
metadata only**, not a decodable MP4. Actual local render verification separately
uses ffprobe and the browser exporter. CI must not call models or require weights.
