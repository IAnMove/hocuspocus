# HOWUSEIT — Workspaces tab (Director threads)

The **Workspaces** gallery tab is a **Director generation-thread dashboard**. It is **not** the sidebar selector for physical output folders, and it is not the explicit Workspace collection registry.

UI tab: **Workspaces** (`mediaFilter: workspaces`). Code: `ui/src/features/workspaces/`. Persistence: `app/services/director_pipeline.py`. HTTP: `app/_launch_runtime.py`. Domain terminology: [Domain model and asset provenance](../development/DOMAIN_MODEL_AND_ASSET_PROVENANCE.md).

Related: [Video Editor / mixes](../video-editor/HOWUSEIT.md), [H3 prompt revisions](../h3-prompt-revisions.md).

---

## 1. What this system is

| Name | What it is |
|---|---|
| Output folder | Isolated physical save directory (`services.active_workspace`, default `default`). Favorites and outputs are per directory. The older API often calls this value `workspace`. |
| Workspace collection | Explicit logical collection of project, asset and Production IDs. It is not a directory and does not move files. Its API is `/api/v1/workspace-collections`. |
| Workspaces tab | List of saved Director / music-video **pipelines** in the **active** output folder. Inspect the shot queue, edit prompts, toggle vocal drive, batch-rewrite, resume, rejoin. |

Director pipeline routes **do not** take `?workspace=`. They always read/write the server’s active **output folder**. A logical Workspace collection is metadata only and does not change this routing rule.

Typical flow: generate a song or Director video elsewhere → the thread appears in the left list (newest first) → select it → edit shots → **Start / resume videos** or **Regenerar vídeo completo** (rejoin). The run may optionally be linked to a Workspace collection, but the files remain in the selected output folder.

---

## 2. Queue inspection

`GET /api/v1/director/pipelines` — saved threads (newest first).
`GET /api/v1/director/pipelines/active` — in-memory runs (recovery).
`GET /api/v1/director/pipelines/{pid}` — full state, **hydrated**.

List query: `?limit=&offset=`. **`limit=0` (default) returns every saved pipeline** and parses each JSON. The Workspaces UI pages **8** (`DASHBOARD_PIPELINE_PAGE_SIZE`) and uses `total` plus `loadMorePipelineList` so opening the tab does not hydrate the whole archive. `GET …/{pid}` is still required for the selected thread. Status polls are serialised in the UI; do not fire a full unpaged list on an interval.

Hydration (`hydrate_queue_clips`):

| Condition | `queue_source` |
|---|---|
| `clips` is non-empty | `clips` |
| else `clip_plans` present | `clip_plans` |
| else `planned_clips` | `planned` |
| nothing to show | `clips` (empty array) |

Prompt fallback on hydrated rows: `video_prompt` → `_director_h3_source_prompt` → (UI also uses `suggested_prompt_hint`).

`404` body: `{ "error": "Pipeline not found" }`.

Live busy threads are polled every **3000 ms** from the UI.

---

## 3. Edit one shot

`PUT /api/v1/director/pipelines/{pid}/clips/{clip_index}/prompt`

```json
{
  "video_prompt": "...",
  "image_prompt": "...",
  "soundtrack_drive": true
}
```

All three fields are optional. Writes propagate to `clips`, `clip_plans`, and `planned_clips`. A video-prompt edit also sets `_director_h3_source_prompt`.

**`soundtrack_drive: true`** sets `_director_audio_plan` to:

```json
{
  "mode": "audio_driven",
  "timing_anchor": "audio",
  "lip_sync_critical": true,
  "vocal_style": "lips and body synchronized to the mapped driving audio; do not invent or transcribe lyrics"
}
```

**`soundtrack_drive: false`** sets `mode: "music_driven"`, `lip_sync_critical: false`, and **clears `_director_dialogue_beats`**.

Errors:

- `409` `{ "error": "Pipeline is still active; try again shortly." }`
- `400` `{ "error": "Clip not found" }` (or pipeline missing)

Clip tags: `PUT .../clips/{clip_index}/tag` with `{ "tag": "good" | "needs_work" | null }`.

---

## 4. Vocal drive vs mute (music video)

Planner (`music_video.py`) turns drive **on** only when a performer is present **and** treatment `lip_sync` is not `none` / `never` / `off`. Music videos do **not** author H3 `<d>` dialogue; lyrics are timing-only. Performance shots receive a sliced soundtrack; B-roll stays mute.

Legacy clips with an empty/missing `_director_audio_plan` still **drive** (backward compatible). The UI label is `canto · drive` vs `mute`.

Silent / mute H3 shots must compile with **no affirmative vocal cues** in the visual field (words such as `habla` fail even inside “Gandalf nunca habla.”). The compiler rewrites those negatives (e.g. `nunca habla` → `nunca abre la boca`). Preflight error pattern:

```
silent visual field still contains affirmative vocal cues: <token>
```

Silent shots require `lip_sync_critical=false` and a permitted mode (`""`, `ambient_only`, `music_driven`, `audio_driven`, `generated_audio`). See `app/services/director/h3_dialogue.py`.

---

## 5. Batch rewrite (UI-only)

There is **no** dedicated rewrite endpoint. The panel loops:

1. `POST /api/v1/llm/generate` with `{ prompt, system_prompt, max_new_tokens?: 1536, temperature?: 0.2 }` — **local LLM must be loaded**.
2. Review proposals.
3. `PUT .../clips/{i}/prompt` to persist selected rows.

Requires an instruction **or** the “Acortar” checkbox. UI error if neither: `Escribe una consigna o marca acortar para MiniMax.`

The system prompt (`ui/src/features/workspaces/rewrite.ts`) keeps official H3 fields (`subject_definitions`, `summary`, `retention_analysis`, `detailed_description`, `integrated_multimodal_description`, `overall_soundscape`, `non_diegetic_music`) and existing tags (`<Picture N>`, `<d>`, `[Shot 1]`, …). It forbids inventing a modern rapper / concert crowd unless the instruction asks for one.

---

## 6. Resume, takes, rejoin

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/director/pipeline/{pid}/resume` | In-memory resume |
| `POST` | `/api/v1/director/pipeline/{pid}/continue` | Continue paused |
| `POST` | `/api/v1/director/pipelines/{pid}/rejoin` | Join all clips → `{ filename, assembly_time_sec, total_time_sec }` |
| `PUT` | `/api/v1/director/pipelines/{pid}/clips/{clip_index}/video-selection` | `{ "filename": "<basename>" }` |
| `POST` | `/api/v1/director/pipelines/{pid}/clips/{clip_index}/rerun-video` | `{ "prompt"?: "..." }` |

The UI enables **Start / resume** only when status ∈ `{failed, crashed, cancelled, paused, interrupted}` **and** `clips.length > 0`. Mutations while the pipeline is active return `409`.

Rejoin uses the mix path in [Video Editor / mixes](../video-editor/HOWUSEIT.md) §6 (soft freeze + crossfade unless driving audio is attached).

---

## 7. Pitfalls

- Calling `GET /api/v1/director/pipelines` with the default `limit=0` from a poller. That re-parses every pipeline JSON. Use `limit`/`offset` (the tab uses 8).
- Confusing this tab with the **output-folder** selector or with a logical Workspace collection. Threads are scoped to whichever output folder is active.
- Editing prompts while Director is sampling → `409`.
- Batch rewrite without a loaded local LLM → `POST /api/v1/llm/generate` fails.
- Toggling a shot to mute without cleaning vocal verbs in the visual prose → H3 preflight rejects the shot.
- Empty `_director_audio_plan` looks like “drive” in the UI even on older B-roll.

---

## 8. Files to read next

| Path | Why |
|---|---|
| `ui/src/features/workspaces/WorkspacesPanel.tsx` | Thread list, consigna, drive toggle |
| `ui/src/features/workspaces/queue.ts` | Client hydration |
| `ui/src/features/workspaces/rewrite.ts` | LLM rewrite contract |
| `app/services/director_pipeline.py` | `hydrate_queue_clips`, `update_clip_prompts` |
| `app/services/director/planners/music_video.py` | When a shot wants drive |
| `app/services/director/h3_dialogue.py` | Mute / vocal-cue validation |
