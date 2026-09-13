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

## Reference images and mixed production

In **Canon → Characters / Locations**, **Generate reference image** uses the subject description and the series visual style. The prompt can be edited before submission. Generation uses the configured image provider and the existing image job queue. A pending job can reconnect from the same browser without submitting another generation. Images are copied into the series asset library with their prompt, provider and job provenance. Choose the primary character image or remove a reference from its card; removing a reference preserves its file and earlier episode evidence.

Location references use a dedicated empty-environment prompt. Before a new location image job, the series writing model extracts the physical setting and environment rendering style, removing character-design instructions and occupants even when mentioned in the location description. **Prepare environment prompt** previews that editable result without generating an image. The same preparation is used by the Setup and Shots reference batches. Failed preparation does not submit an image; reconnecting an existing image job preserves its original prompt. Locations use 16:9 framing, an explicit zero-occupant instruction and clean local model defaults so an old character reference cannot leak in from Studio. The scoped writer uses `/api/v1/llm/generate` with optional `writingProvider`, `writingModel` and `writingBaseUrl`, preserving the configured global model.

Review the result and approve the canon. New episodes capture those references automatically. For an existing pilot, click **Use approved references in this episode** directly in Shots (the Episode room also retains its refresh action). This updates the matching characters' and locations' reference images, preserving the episode's frozen story, dialogue and existing takes. Active rendering and stale revisions block this update.

**Setup → Allowed production methods** stores a nonempty `allowedProductionMethods` list:

| Value | Shot workflow |
| --- | --- |
| `generated_video` | Automatic video-model rendering with the configured H3 variant. |
| `animation_2d` | Open the episode references as editable character/background layers in Video 2D. |
| `animation_3d` | Open an editable spatial composition using reference image planes; models can be assigned in Video 3D. |
| `imported_video` | Import a completed clip from another workflow or generator. |

Select several methods to permit a mixed episode. The planner chooses `productionMethod` per shot from that list; each shot can be reassigned manually. Existing legacy shots retain `generated_video`. H3 batch rendering processes only permitted model-video shots, and checks the permission again before running queued shots. Native/imported shot durations are editable independently of H3 duration quantization.

The same production-method checkboxes are available at the top of **Shots**, including in existing series. Enabling a method adds it to every shot's selector. To reassign an existing episode, choose the enabled method in **Method for shots without a take**, then click **Apply to shots without a take**. This updates eligible shots in the current episode, preserving completed/approved takes and queued/running/cancelling attempts. Each shot's **Configure series methods** link returns to the checkboxes. Changing the allowed list alone preserves existing shot assignments.

The 2D/3D buttons prepare scenes; animation, model assignment, audio and export are completed in those editors. Import the exported video back into its shot using **Import video as a take**. The server verifies the video stream and duration, appends a completed take, and preserves earlier takes and approval. Approve the imported take in Review to include it in the normal episode assembly.

Both animation methods require an approved environment image and approved images for every visible character in the episode snapshot. Setup shows environment/cast preparation counts and links to their Bible cards. Each animation shot displays the assigned environment, its optional variant and the exact reference previews; preparation stays disabled until all required images are available. Video assets, derived thumbnails and unapproved references do not satisfy this requirement. Establishing shots can have an empty cast, but still need an environment. When a planning response omits an animation shot's location, it inherits its script scene's canonical location; a plan without either is rejected. Shots also shows **Generate all missing references**, which generates only the characters and locations used by this episode that lack an image. It deduplicates subjects across shots and skips completed imports on retry. Generation does not approve canon or replace the episode snapshot. **Review and approve canon**, then **Use approved references in this episode**, complete the workflow. References that already exist in the series are labelled as available for incorporation rather than missing images.

The normal project PUT API persists `allowedProductionMethods`; episode/shot updates persist `productionMethod`. To refresh approved references in an existing episode, POST `/api/v1/series/{seriesId}/episodes/{episodeId}/references/refresh` with `workspace` and the current series `baseRevision`:

```javascript
const result = await fetch(`${base}/api/v1/series/${seriesId}/episodes/${episodeId}/references/refresh`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ workspace: 'default', baseRevision: series.revision }),
});
if (!result.ok) throw new Error(await result.text());
const updated = await result.json();
```

```python
response = requests.post(f'{base}/api/v1/series/{series_id}/episodes/{episode_id}/references/refresh',
    json={'workspace': 'default', 'baseRevision': series['revision']})
response.raise_for_status()
updated = response.json()
```

```bash
curl -X POST "$BASE/api/v1/series/$SERIES_ID/episodes/$EPISODE_ID/references/refresh" \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"default","baseRevision":12}'
```

Import a completed take using the existing `/api/v1/series/{seriesId}/assets/import` endpoint with `ownerType: "shot"`, `ownerId: shotId`, `kind: "video"`, `asTake: true`, and an `uploadPath` returned by `/api/v1/upload`. Both imports and reference refresh are supported by the full and core runtimes. The automatic H3 renderer remains part of the full runtime.

## Reusable character voice and lip-sync configuration

**Canon → Characters** owns the setup entry for each series character. It reports voice, 2D mouth-pack and 3D face-calibration readiness separately. An empty library no longer leaves the user with only an unlinked selector: **Configure in Character Creator** navigates to a dedicated, spacious editor in the Character Creator tab with the exact character name and reference image as a draft. Identity selection is locked to that subject. Voice and model drafts survive studio-tab navigation; the 2D workshop retains its existing scoped recovery. The return button waits for unsaved configuration to be saved and goes back to the source character and episode. Saving persists a Character Kit and its exact workspace/id link in the series. Editing that link opens the same identity; it never matches or merges characters by name. The compact Series card keeps a visible selector for linking an existing library character and separate readiness indicators for voice and lip sync. Saving links only the original series/workspace/character; changed selections are never silently overwritten.

Voice-only characters do not need a GLB. The 3D model is optional; configuring the 3D face still requires a verified GLB. The 2D workshop opens the saved character's exact ID and keeps its recovery draft separate from other characters and the general workshop. A missing image or unprepared mouth remains visibly pending. Opening or saving settings does not generate audio, images or video.

Dialogue-shot speech controls open the same Character Creator destination directly. The advanced voice table links to the corresponding character card. The 3D speech workflow consumes the linked kit's model, face settings and local TTS preset. 2D mouth preparation continues through the existing workshop and compositor. Native-audio AI video does not consume the local TTS voice ID; its provider generates the voice. Scene audio and existing takes remain independent of character settings.
