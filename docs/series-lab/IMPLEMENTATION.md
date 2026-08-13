# Series Lab implementation

Series Lab is a top-level Maestro workspace for persistent episodic production. Its hierarchy is:

`Series → Season → Episode → Scene → Shot → append-only Attempts`

## Persistence and recovery

- Authoritative library: `<workspace>/.series-library-v1.json`.
- Durable planning checkpoints: `<workspace>/.series-jobs-v1/planning/`.
- Durable render checkpoints: `<workspace>/.series-jobs-v1/render/`.
- Imported references are copied below `<workspace>/assets/<series-id>/`; library JSON stores paths and metadata, never base64 media.
- Writes are atomic and workspace scoped. Project and canon commits use optimistic revisions.
- A restart exposes unfinished checkpoints as Resume/Discard cards. Discarding state never deletes approved media.

Every new episode freezes its approved canon, entity definitions, provider/capability profile and reference asset records. Later bible edits therefore do not silently change the old episode. Shot/attempt outputs created after the snapshot remain available to that episode.

## User flow

1. Create an original series or import a Story Lab bible as a new draft.
2. Complete Setup and choose explicit writing, image and MiniMax H3 defaults. Local concept-image generation never silently chooses a recommended model.
3. Prepare a durable canon proposal as text, optionally followed by missing identity/location images. Inspect the proposal before applying it.
4. Review World, Characters, Relationships, Locations, Props, Long arcs, Timeline and Voice bible. Approving the reviewed canon creates a new canon revision.
5. Create an episode, then generate an outline or a complete editable script and a duration-aware shot proposal. Planning uses the frozen canon and compact prior-episode summaries. Each generated video is 5, 10, or 15 seconds; longer episodes add shots instead of extending a clip.
6. Inspect or manually override each deterministic reference manifest. Loose portraits are never labelled as exact start frames; composed start/end frames are explicit shot assets.
7. Render selected, missing, failed or all unapproved shots. Cancellation records interrupted attempts and recovery appends a new retry instead of overwriting history.
8. Preview thumbnail-first attempts, approve/reject them, regenerate individual rejected shots, and open the approved sequence in Video Editor.
9. Accept/reject individual proposed continuity facts. Only accepted facts update canon for later episodes.

## HTTP surface

The `/api/v1/series` resource includes:

- series list/create/get/update/delete/duplicate and Story import;
- episode list/create/get/update/delete;
- canon preparation start/status/cancel/resume/apply and reviewed-canon approval;
- one-click known-series bootstrap into an editable, unapproved bible;
- episode planning start/status/cancel/resume/apply;
- deterministic episode/shot reference routing;
- render start/status/cancel/resume/discard;
- attempt approve/reject;
- selected CanonDelta commit.

All mutating requests carry a workspace in their JSON body, or a workspace query parameter for DELETE. Generated video metadata records the exact effective prompt, negative prompt, H3 model, seed, settings/frame count, reference manifest, request hash, job ID, creation/submission/completion timestamps and elapsed milliseconds.

## MVP boundaries

The optimized production path remains a manually reviewed short pilot, but episode planning scales to the saved target runtime with duration-aware shot counts. Every shot has a nominal duration of 5, 10, or 15 seconds, the generated H3 request stays below the hard 15-second ceiling, and dialogue is limited to one speaker per shot so speaker changes become separate clips. Native dialogue includes exact text/emotion but lip sync is explicitly best-effort. A one-click known-series bootstrap may seed a broader reusable draft bible (up to 12 recurring characters/locations, 24 relationships and 12 props) from the selected writing model's general knowledge. It performs no live web research, copies no scripts or dialogue, preserves uploaded assets, and never approves the generated canon; users must verify facts and rights before production or publication. Controlled TTS, training/fine-tuning, crowds with individually stable identities and automatic publication remain non-goals.

## Verification

From the existing environments:

```bash
cd app
env/bin/python -m pytest -q ../tests/test_series_library.py ../tests/test_series_reference_router.py ../tests/test_series_planning.py ../tests/test_series_jobs.py ../tests/test_series_render.py ../tests/test_series_lab_ui.py ../tests/test_video_editor_preview_canvas.py

cd ../ui
npm run lint
npm run build

cd ..
app/env/bin/python -m pytest -q tests
```

Broader Story Lab, Director, job lifecycle and Video Editor regression suites are required before release.
