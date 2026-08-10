# Maestro Task Scheduler

## Purpose

Maestro currently has several independent execution and activity systems. The
goal of this project is to introduce one canonical task manager for every
meaningful user-triggered operation, while preserving the specialized engines
that already perform the work.

The scheduler must answer, at all times:

- What is Maestro doing?
- Which concrete call or process is running?
- How long has the task and its current operation been running?
- Which provider, model, server, and local resource are being used?
- What is queued, what can run in parallel, and what is blocking what?
- How many items, attempts, and tokens have been consumed?
- Can the operation be cancelled, retried, resumed, or recovered after refresh?
- Which user action, request, worker, and output belong to the same workflow?

This is both a scheduler and an observability layer. The footer is a client of
the task manager, not the owner of task state.

## Implemented architecture note (2026-08-10)

The canonical registry is stored per output workspace in
`.maestro-tasks-v1.sqlite3`. Domain checkpoints remain authoritative for
editing/resume semantics; compatibility adapters publish their observable
state into the registry and task controls dispatch back to the owning engine.
The React footer reads only canonical tasks through SSE with polling fallback.
Frontend-only foreground operations are mirrored to the backend registry so
synchronous uploads and remote calls cannot disappear from activity history.

Series Lab planning and rendering are first-class adapters. Series planning
also propagates task context into provider threads, allowing each compatible
LLM request to appear as a child operation with provider, model, server,
attempt, elapsed time, and aggregated token usage. The same context boundary
is the required integration pattern for the remaining specialized workflows;
adapters must never recreate task ownership in the footer.

## Current problems

### Fragmented task ownership

The application currently has multiple independent registries and execution
mechanisms:

- Main image/video generation uses `launch._jobs` and a global GPU lock.
- Director owns a separate persisted pipeline registry.
- Story planning, comic planning, and video editor jobs have separate maps.
- Audio analysis shares part of the main job map but has its own execution lock.
- Hunyuan3D and Rig each own a queue and an independent semaphore.
- MiniMax image and music operations may be synchronous remote HTTP requests.
- Frontend-only activities are manually created by individual feature panels.
- Some LLM and Director operations use resource lanes, while other operations
  bypass the resource coordinator.

The footer currently merges some of these sources after the fact. This causes
missing tasks, duplicated tasks, inconsistent cancellation, and incomplete
recovery after a browser refresh.

### Concrete missing-activity example

Story Lab's `Generate identity variation` calls the shared image helper and
only sets component-local busy state.

- A local image job is submitted and polled directly without immediately being
  registered in the global frontend job store.
- A MiniMax image request has no durable task at all.
- The button can therefore spin while the footer says there are no active jobs.

The first migration of the scheduler must cover the shared image helper so the
fix automatically applies to character identities, worlds, locations, and
comic image generation.

### Concrete opaque-LLM example

Director pipeline `7784cbdd` displayed only `Planning with LLM... 0/1` while a
single MiniMax-compatible request was running.

Observed data from the debug trace:

- Operation: `generate_openai_compatible`
- Call ID: `4be65c42560e4c838d9f4ab7a2c1ae87`
- Duration: 381.03 seconds (6:21)
- Prompt tokens: 15,638
- Completion tokens: 18,856
- Total tokens: 34,494
- Requested shots: 40
- Valid shots returned: 46

The UI did not expose the concrete call, its elapsed time, attempt, token use,
or response state. After the response arrived, strict cardinality validation
failed and no images were queued.

This scenario is a required scheduler acceptance test.

## Design principles

1. **One canonical task identity.** Every operation receives a `task_id` before
   work begins. Child operations receive their own IDs and retain `parent_id`
   and `root_id`.
2. **Backend is the source of truth.** React state mirrors backend tasks; it
   must not be the only record that a task exists.
3. **Execution and presentation remain separate.** Existing engines may keep
   their internal job representation during migration, but must publish task
   events through adapters.
4. **Every wait is observable.** A task distinguishes queued, acquiring a
   resource, uploading, requesting, streaming, parsing, validating, retrying,
   generating, post-processing, and saving.
5. **Parallelism is resource-based.** Work overlaps only when its declared
   resources are independent.
6. **Retries belong to the original task.** Retrying increments an attempt and
   creates child-operation history; it does not create an unrelated footer row.
7. **Safe recovery.** Active tasks survive browser refresh. After a backend
   restart, persisted tasks become recoverable, resumable, or explicitly
   interrupted rather than silently disappearing.
8. **Logs are correlated, not merely verbose.** User action, HTTP request, task,
   provider call, worker, token usage, and output share correlation IDs.
9. **No sensitive input in UI-action logs.** Existing protection against
   recording typed values remains. Provider payload logging follows debug-mode
   redaction and size limits.
10. **Incremental migration.** Each phase is independently deployable and has
    its own commit and tests.

## Canonical task model

The initial task record should contain:

```text
id, root_id, parent_id
kind, title, workflow
status, phase, message, detail
current, total, progress
detail_current, detail_total
created_at, queued_at, started_at, updated_at, completed_at
provider, model, server_origin
resource_requirements[], acquired_resources[]
attempt, max_attempts
token_usage { prompt, completion, total, calls }
workspace, project_id, entity_type, entity_id
backend_job_id, pipeline_id, external_request_id
cancelable, resumable, recoverable
error { code, message, retryable, details }
result_refs[]
metadata
```

Statuses:

```text
created -> queued -> waiting_resource -> running
running -> completed | failed | cancelled | interrupted
failed/interrupted -> queued (retry or resume)
```

An operation is a child task when it is independently useful for diagnosis or
progress. Examples include an LLM call, generation of one image, generation of
one clip, an upload, or an FFmpeg join.

## Task events and persistence

Use an append-only event stream plus a current-state snapshot. SQLite is the
preferred durable store because it supports atomic updates, querying active
tasks, and bounded retention without loading a large JSON file. JSONL debug
traces remain a diagnostic export, not the source of task state.

Minimum event shape:

```json
{
  "event_id": "...",
  "task_id": "...",
  "root_id": "...",
  "sequence": 12,
  "timestamp": "...",
  "type": "operation.started",
  "changes": {},
  "context": {}
}
```

Backend endpoints:

```text
GET  /api/v1/tasks?status=active
GET  /api/v1/tasks/{task_id}
GET  /api/v1/tasks/{task_id}/events
GET  /api/v1/tasks/events              # SSE stream
POST /api/v1/tasks/{task_id}/cancel
POST /api/v1/tasks/{task_id}/retry
POST /api/v1/tasks/{task_id}/resume
```

SSE is sufficient for the first version. Polling the active-task endpoint is
the fallback for reconnection and environments where the event stream closes.

## Concrete operation visibility

Every provider or subprocess invocation must be represented as a child
operation. For an LLM request the footer/detail view should show:

```text
Planning music-video shots
Call 1/1 · MiniMax-M2.7 · api.minimax.io
Waiting for response · 6:21
40 shots requested · response not received yet
Tokens: pending
```

After a response:

```text
Parsing response · 46 candidate shots received
Validating 46/40 · repairing cardinality
34,494 tokens · 15,638 input · 18,856 output
```

Long details are truncated in the footer and exposed through a title/tooltip
and expanded activity panel. Prompts and responses are never dumped into the
compact footer.

Both the task and current operation have independent elapsed timers. Failed
tasks retain their final duration rather than resetting or continuing to count.

## LLM output repair policy

Strict validation should prevent malformed plans from reaching image
generation, but a harmless cardinality mismatch should not discard an
otherwise valid six-minute response.

The expected count is initially the number of time slots produced by audio
analysis. It is not a creative upper bound: it means the current edit has `N`
places that each require one primary shot. Additional good ideas may be kept as
alternatives, but they cannot silently become extra clips without re-segmenting
the song and changing the edit structure.

For an expected count of `N`:

1. Parse and validate every candidate independently.
2. Require every planned shot to return `clip_index`, `start_sec`, and
   `end_sec`. Reconcile candidates to the requested slots rather than relying
   only on array position.
3. If more than `N` valid candidates are returned, exact valid indexes win.
   Useful overflow candidates are retained as named alternatives for the
   nearest compatible slot. Repetitions and unassignable overflow are rejected
   with a logged reason; they are never silently lost.
4. If fewer than `N` are valid, issue one compact repair call containing only:
   the expected schema, missing indexes, validation errors, and the relevant
   previous output fragments. Do not resend the complete story bible unless
   required.
5. If indexes are duplicated or ambiguous, make one repair attempt rather than
   silently assigning shots to the wrong audio segments.
6. Preserve the original response and repair result in debug storage with the
   same root task and separate call IDs.
7. Expose `received`, `valid`, `expected`, `repair attempt`, elapsed time, and
   incremental token usage in the task.
8. Never queue images until every required time slot has one valid primary
   plan. Alternatives do not block image generation.

For the observed 46-for-40 response, the six trailing entries are highly
repetitive variations of the final fade. With explicit indexes they could be
retained as alternatives to the ending slots. Because the current response is
positional and does not carry reliable indexes, the safe recovery is to keep
the original response, map the first structurally valid plans to the requested
slots, and run at most one compact reconciliation call if ambiguity remains.

## Adaptive LLM planning batches

Planning an entire long production in one request makes progress opaque,
creates very large prompts, increases the cost of retries, and makes one schema
mistake invalidate all otherwise useful work. One request per clip has the
opposite problem: it repeats global instructions many times, loses continuity,
and can produce dozens of paid calls.

Use adaptive contiguous batches instead:

1. Build a compact production brief once from the story bible: visual style,
   character identities, locations, narrative arc, forbidden content, and
   model-specific rules. Do not resend the full story bible and every unrelated
   asset description to every batch.
2. Divide the timeline first on narrative and musical boundaries: introduction,
   development, climax/resolution, verse/chorus/bridge transitions, and major
   location changes.
3. Subdivide large acts to a configurable target of 6-10 clips per batch and a
   maximum estimated prompt/output token budget. Small productions can remain
   a single call.
4. Each batch receives the compact production brief, only its clip timing and
   lyrics, relevant characters/locations, and a short continuity handoff from
   the previous batch.
5. Each result must include explicit original clip indexes and time ranges.
6. Persist and expose every batch immediately. A 40-clip plan should show, for
   example, `Planning batch 2/5 · clips 9-16 · 3/8 parsed`, including call
   elapsed time and tokens.
7. On failure, retry only that batch. If some indexes remain missing after
   validation, perform one repair call for only those indexes.
8. Preserve overflow candidates as per-slot alternatives; do not change audio
   segmentation without an explicit re-edit operation.

Batches for the same remote server run sequentially by default. Configurable
remote capacity may allow parallel batch calls, but only when the user has
enabled it and the provider/resource policy permits the extra cost and rate
limit risk. Results are assembled deterministically by clip index, not response
completion order.

## Resource model

All engines must acquire resources through one coordinator. Initial lanes:

```text
local_gpu:{index}          capacity 1 by default
local_cpu:llm              configurable
local_cpu:audio            configurable
local_cpu:ffmpeg           configurable
remote:{server_origin}     capacity 1 by default
disk:outputs               bounded writer capacity
```

Examples of allowed overlap:

- Remote image generation plus local video generation.
- Remote LLM planning plus local GPU generation.
- Local CPU work plus local GPU generation.
- Requests to different remote server origins.
- Work assigned to two distinct physical GPUs.

Examples disallowed by default:

- Two generators on the same local GPU, even if one is 3D and one is video.
- Two requests to the same remote subscription endpoint unless configured.
- Multiple local LLM calls when that LLM uses the same GPU as generation.

Hunyuan3D, Rig, Director, and the main generation engine must not retain
independent notions of exclusive ownership of GPU 0 after migration.

Configuration should expose conservative per-resource capacities. Increasing
remote concurrency must be explicit because it can multiply token consumption,
rate-limit failures, and paid retries.

## Debug correlation

The UI creates or obtains a task ID before every mutating generation request
and sends it as a request header and/or payload field. Backend middleware
places these fields in trace context:

```text
task_id, root_id, parent_id, request_id
backend_job_id, pipeline_id, provider_call_id
provider, model, server_origin, attempt
```

Worker threads must explicitly receive and restore this context; Python
`contextvars` do not automatically propagate into newly created threads.

Debug events should cover:

- User control activation.
- Request accepted/rejected.
- Task created and queued.
- Resource wait/acquisition/release.
- Provider/subprocess request and response.
- Parsing and validation counts.
- Retry/repair decisions.
- Token usage and timing.
- Output attachment and final task state.

## Footer and activity UI

The footer subscribes to canonical tasks and no longer merges unrelated stores.

Compact row:

- Phase and concrete current operation.
- Task elapsed time.
- Current-operation elapsed time when useful.
- Primary and nested progress (`1/3`, `12/40`).
- Queue/resource state.
- Token total when available.

Expanded row:

- Provider, model, server, and resource lane.
- Parent/child operation history.
- Attempt and validation details.
- Input/output token split.
- Cancel, retry, resume, dismiss, and copy task ID actions where valid.
- Tooltip containing the full non-sensitive detail when compact text is
  truncated.

Task IDs must also be visible on generated songs, images, clips, and final
outputs so a user can report a specific failure later.

## Compatibility adapters

During migration, adapters publish legacy state into the task manager:

1. Main `_jobs` adapter.
2. Director pipeline adapter.
3. Story and comic planning adapters.
4. Audio-analysis adapter.
5. Video-editor/animatic adapter.
6. MiniMax image/music request wrapper.
7. Hunyuan3D and Rig adapters.

An adapter links its legacy identifier to `task_id`. The UI deduplicates by
that explicit relationship, never by comparing titles or timestamps.

## Delivery phases and commits

### Phase 1 — Task core and diagnostics

- Add task schema, durable registry, event stream, and REST endpoints.
- Add correlation context and thread propagation.
- Add unit tests for transitions, persistence, and event ordering.
- Do not migrate execution behavior yet.

Commit: `feat(scheduler): add durable task registry`

### Phase 2 — Shared image generation

- Register every `generateImageAsset` operation.
- Attach local backend job IDs immediately.
- Wrap synchronous MiniMax image calls as observable child operations.
- Cover Story Lab identity/world/location and comic image entry points.
- Verify refresh, cancellation, retry, and deduplication.

Commit: `feat(scheduler): track shared image generation`

### Phase 3 — Director and detailed LLM calls

- Adapt Director pipelines to canonical parent tasks.
- Publish each planning, polish, and repair LLM call as a child operation.
- Show model, server, request state, elapsed time, counts, and tokens.
- Split long productions into adaptive narrative/music batches with explicit
  clip indexes and bounded prompt/output budgets.
- Implement bounded cardinality repair for music-video shot planning.
- Keep all existing pipeline checkpoints and resume behavior.

Commit: `feat(scheduler): expose director operations`

### Phase 4 — Story, comics, music, and audio

- Migrate story/comic planning and regeneration.
- Track individual songs and sequential `generate all` queues.
- Track uploads, translation, analysis phases, and model loading.
- Preserve language/version metadata and output task IDs.

Commit: `feat(scheduler): track creative workflows`

### Phase 5 — Video editor, 3D, Rig, and unified resources

- Migrate FFmpeg, animatic, 3D, and rig jobs.
- Replace independent GPU semaphores with shared resource acquisition.
- Add conservative configurable capacities.
- Test the supported parallelism matrix.

Commit: `feat(scheduler): unify execution resources`

### Phase 6 — Remove compatibility paths

- Make the footer consume only canonical tasks.
- Remove frontend-only generation activity helpers and redundant polling.
- Add retention/cleanup policy and task-history UI.
- Document task APIs and operational debugging.

Commit: `refactor(scheduler): remove legacy activity paths`

## Acceptance criteria

- Every generation-related user action creates a visible task within 250 ms.
- Browser refresh reconstructs every active task without duplicate rows.
- Backend restart marks unfinished durable tasks as interrupted/recoverable.
- The footer always shows total elapsed time for running and terminal tasks.
- A provider call shows provider, model, server, call attempt, and call elapsed
  time while it is in flight.
- Counts display at the finest available level, such as phase `1/3` and shot
  planning `12/40`.
- Token usage updates per call and aggregates into parent and root tasks.
- Retries and repairs retain one root task and an auditable attempt history.
- Cancelling a queued task removes it without acquiring its resource.
- Cancelling a running task reports whether cancellation is immediate or
  deferred to a safe boundary.
- Tasks using the same physical GPU never execute concurrently by default.
- Tasks on independent resources overlap when workflow parallelism is enabled.
- Every generated output stores its task ID and root workflow ID.
- Debug logs can reconstruct click -> request -> resource -> provider -> result.
- The 46-valid-for-40 music-video response is reconciled or repaired without
  queuing images prematurely and without discarding the entire valid response.

## Non-goals for the first phase

- Rewriting each generation engine.
- Increasing concurrency by default.
- Persisting full sensitive prompts outside explicitly enabled debug mode.
- Automatically retrying paid provider calls without a bounded policy.
- Replacing Director's production/checkpoint model with a generic task record.

The task manager coordinates and observes those systems; it does not erase the
domain-specific state required to edit and resume a production.
