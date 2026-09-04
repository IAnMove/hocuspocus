# Generation record v1

Status: accepted contract (2026-09-04)

A **Generation** is one attempt to produce an asset. This document is the
portable read/write contract for that attempt. It projects existing sources; it
does not invent a second media store.

Authoritative bytes and published provenance remain the adjacent
`<stem>.meta.json` asset-manifest v1 sidecar. The generation record adds a
typed attempt identity, lifecycle, cancellation and resume vocabulary on top of:

- `app/services/asset_manifest.py` / `asset-manifest-v1.schema.json`
- `app/services/generation_provenance.py`
- `app/services/job_lifecycle.py`
- crash-safe JSON replacement as in `app/services/durable_generation_queue.py`

Python helpers live in `app/services/generation_record.py`. UI types and pure
mappers live in `ui/src/lib/generationRecord.ts`. The JSON schema is
`generation-record-v1.schema.json`.

This module does not import FastAPI, WanGP or launch. Wiring into
`_launch_runtime.py`, Activity and the Library catalog is a later sequential PR.

## Identity

| Field | Rule |
|---|---|
| `generation_id` | Stable attempt ID. Never recycled. |
| `asset_id` | Stable artifact ID. Never recycled. Matches `asset.id` when published. |

Titles, prompts, filenames and display labels are never identity. Two attempts
with the same prompt are still two generations.

**Attempt policy (b):** a retry mints a **new** `generation_id`, increments
`retry_count` on the new attempt, and links the parent `generation_id` in
`lineage.parents` (`kind: "attempt"`). The parent may list the child in
`lineage.derivatives`. `asset_id` is copied only when the bytes are the same
artifact (`same_artifact=True`). Distinct output files get a new `asset_id`.

Resume after a process restart reloads the JSON and continues from the last
durable status. It does not mint IDs and does not invent `completed`.

Policy (a) — mutate one `generation_id` and only bump `retry_count` — is
rejected because a retry is a new run in the domain model.

## Product / origin

`product` is the originating UI surface, projected from `origin.tool` (and, when
needed, a trusted capability) onto:

`studio | story_lab | series_lab | director | comic | tools | wizard |
video_editor | video_3d | character_kit | system | unknown`

Who started the work (`provenance.actor`) stays separate from what computed the
bytes (`model.provider` / `model.id` / `model.version`).

## Location

`workspace_id` is a Workspace **collection** ID. `output_folder` is the physical
folder **name**. `location.filename`, `location.uri` and `location.sidecar` are
relative filenames (`clip.mp4`, `clip.meta.json`). Host absolute paths are
rejected.

A record persisted under workspace A cannot be loaded, listed or adopted as
workspace B. `load` / `list` always take `workspace_id` and compare it to the
document.

## Status

Public enum (six values):

`planned | queued | running | completed | failed | cancelled`

| Asset-manifest `execution.status` | Generation record |
|---|---|
| `prepared` | `planned` |
| `queued` | `queued` |
| `running` | `running` |
| `completed` | `completed` |
| `failed` | `failed` |
| `cancelled` | `cancelled` |
| `partial` | `completed` + `result.kind = "partial"` when a filename exists; otherwise `failed` with `error.code = "partial"` |

`partial` is **not** a seventh public status. Legal transitions match the
in-process job lifecycle, including `running -> queued` for multi-phase work.
Terminal states do not transition. A requested cancellation beats a late
`completed` / `failed` write, as in `job_lifecycle.finish_job`.

Cancellation:

- **before running** (`planned` / `queued`): `request_cancel` settles immediately
  to `cancelled`;
- **while running**: `request_cancel` sets `cancellation.requested` and keeps
  `status=running` (the public form of job `cancelling`); `apply_cancel` is the
  worker acknowledgement that moves the record to `cancelled`.

## Persistence and resume

`persist_generation_record` / `GenerationRecordStore` write one JSON document
per attempt with atomic temp-file replace and `fsync`, the same durability
pattern as `DurableGenerationQueue`. Identity fields on an existing file cannot
be replaced.

After a simulated process restart, construct a new store, `load` / `resume` the
id, and continue from `queued` or `running`. Do not mark the attempt completed
just because the process came back.

## Projection

- `project_from_asset_manifest(manifest)` — read model over a canonical sidecar.
  `generation_id` comes from `technical.generation_id`, else `execution.job_id`,
  else `gen_{asset_id}`.
- `to_asset_manifest_patch(record)` — the asset-manifest fields implied by the
  record (`planned` writes back as `prepared`). Patching does not rewrite media
  bytes and does not create a parallel catalog.

## Secrets and prompts

`model.configuration` (and any nested parameters) recursively redact credentials,
tokens and API keys using the asset-manifest policy. `prompt_display` is at most
180 characters and is derived from `prompt_full` after that redaction.

## Follow-up

Launch, Activity and Library wiring is deferred: `_launch_runtime.py` is owned
by another in-flight PR. This contract is the portable layer those writers
should adopt next.
