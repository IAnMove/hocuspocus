# Music submission contract

Status: accepted (phase 4). Authority is the Story library + TaskRegistry +
this reservation JSON. Inference is not part of acceptance.

## Paths (kept)

| Path | Endpoint | Models |
|---|---|---|
| Local ACE-Step / MiniMax-Music3 | existing `generateMusic` / start_generation | `ace_step_*`, `minimax_music3` |
| Remote MiniMax (durable) | `POST /api/v1/stories/music-candidates/jobs` → **202** | `music-3.0`, `music-2.6`, covers |
| Legacy sync | `POST /api/v1/stories/music-candidates` | same remote models; waits for bytes |

Clients of the durable job route keep working. Extra fields on the 202 body
(`generationId`, `commandId`, `candidateId`, `idempotencyKey`, `replay`) are
additive.

## Request

`command_id` / `idempotency_key`, project/cue/candidate IDs (never titles),
physical `output_folder` (or `workspace` as the folder name), optional
Workspace `workspace_id`, optional Story `library_revision`, and an immutable
spec snapshot (`model`, prompt, lyrics, instrumental, count, reference).

`intent`: `retransmit` (default) | `retry` | `new_version`. Retry and new
version mint a new attempt with lineage and a distinct key.

## Dedup

Same idempotency key + same spec hash → same `job_id` / `task_id` /
`generation_id` / `candidate_id` (HTTP replay). Same key + different spec →
**409**. IDs are reserved **before** `after_persist` (worker start). A worker
start failure does not delete the reservation.

Story rows are looked up by ID in `.story-library-v1.json`. A title is never
a key.

## Query

`GET /api/v1/stories/music-candidates/jobs/{job_id}` remains the poll URL.
TaskRegistry owns the task row. This module does not download models or talk
to a GPU.
