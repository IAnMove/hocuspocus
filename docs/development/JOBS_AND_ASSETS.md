# Jobs, leftovers, uploads and named outputs

Public MCP / HTTP surface for the **existing** generation queue and workspace
files. This is not a second scheduler. Nothing here starts a model except
`jobs.resume`, which calls the same recovery hook the UI uses.

Related: [video commands](VIDEO_COMMANDS.md), [image commands](IMAGE_COMMANDS.md),
[Wizard / MCP usage](WIZARD_MCP_USAGE.md), [Video 2D MCP guide](../agents/VIDEO2D_MCP_GUIDE.md).

Landed in **development** via #552 (`assets.upload`) and #561 (leftovers, wait,
`output_name`, queue priority, compact catalogs, `invalid_selector`).

---

## 1. Leftovers — `jobs.leftovers` / `jobs.resume` / `jobs.discard`

After a restart, durable queue records that are not live workers are leftovers.
A record that was `running` or `cancelling` is reported as `interrupted`;
anything else waiting is `leftover`.

| Tool | Mutation | Input | Result |
|---|---|---|---|
| `jobs.leftovers` | no | `{version: 1}` only | `{jobs: [{job_id, intent_id, status, previous_status, workspace, model_type, prompt_preview, fingerprint, created_at}]}` |
| `jobs.resume` | yes | `{version: 1, intent_id}` | `{job_id, intent_id, status, started}` |
| `jobs.discard` | yes | `{version: 1, intent_id}` | `{job_id, intent_id, discarded, status}` |

`intent_id` is the original command id, or the job id. Extra fields → `422`.

**Do not submit a second copy.** A generate with the same content fingerprint
as a leftover returns `duplicate_leftover` with that `job_id`. Resume it.

`jobs.resume` rehydrates the stored params onto the existing queue. If that
job is already `queued` / `waiting_resource` / `running` / `cancelling`,
`started` is `false` and no second worker starts.

`jobs.discard` removes a leftover. It does **not** cancel a live job
(`discarded: false`). Missing id → `404 leftover_not_found`.

Code: `app/services/job_leftovers.py`. The fingerprint ignores identity,
provenance and H3 runtime keys (`h3_window_*`).

---

## 2. Wait — `jobs.wait`

Blocks until a generation job is `completed`, `failed`, `cancelled` or
`discarded`, or until `timeout_s`. Returns the **same payload as `status`**.
It does not poll the GPU or start a model. `interrupted` stays open because
it can be resumed.

```json
{
  "version": 1,
  "input": {
    "job_id": "a1b2c3d4",
    "timeout_s": 30
  }
}
```

Default timeout is 30 s. Values above 120 are capped at 120. Timeout → HTTP
`408` with `code: "timeout"` and `retryable: true`, plus the last status
payload. Missing `job_id` → `422`.

Code: `app/services/jobs_wait.py`.

---

## 3. Upload — `assets.upload`

Stores one image, audio or video **inside the selected workspace** and
returns `{asset_id, url}`. The URL is accepted by `image_refs`,
`image_start`, `image_end` and `audio_guide`. It does not call
`POST /api/v1/upload` and does not use the GPU.

Two input shapes (exactly one):

```json
{
  "version": 1,
  "intent_id": "upload-start-1",
  "input": {
    "workspace": "my-outputs",
    "filename": "start.png",
    "data_base64": "<standard base64>"
  }
}
```

or `{workspace, source}` where `source` is already inside that workspace or
the uploads root.

| Limit | Value |
|---|---|
| Decoded payload | 8 MiB |
| `intent_id` | 1–160 characters; reuse only for the **same** payload |
| Filename | Basename only; image / audio / video extension |

Reuse of `intent_id` with the same digest returns the stored result.
A different payload under the same id → `409 intent_conflict`.

Codes: `invalid_command`, `invalid_intent`, `invalid_filename`,
`invalid_payload`, `payload_too_large` (413), `unsupported_media`,
`path_not_allowed`, `media_not_found` (404), `invalid_workspace`,
`storage_unavailable` (503).

Code: `app/services/assets_upload.py`. Journal: `.assets-upload-intents.json`
in the workspace.

---

## 4. Named outputs — `output_name`

Optional on any `generation.*` command except `generation.receipt`.
A caller-supplied basename replaces the truncated-prompt stem. It is stripped
before the closed schema sees it, then attached to native params and the
content fingerprint.

| Rule | Value |
|---|---|
| Length | 1–180 |
| Shape | Single file name. No `/`, `\`, `:`, `{}`, controls, `..`, or absolute path |
| Error | `invalid_output_name` before any model runs |
| Omitted / `null` | Historical prompt stem |

`status` and `generation.receipt` project produced files as:

```json
{
  "outputs": [
    {
      "asset_id": "…",
      "canonical_url": "/api/v1/file/hero.mp4?workspace=my-outputs",
      "path": "hero.mp4"
    }
  ],
  "asset_id": "…",
  "canonical_url": "…",
  "path": "hero.mp4"
}
```

The stored admission is unchanged. Code: `app/services/generation_output_name.py`.

---

## 5. Queue priority

Optional integer on generate / submit (`priority` on the command, `input`, or
`input.params`). Higher integers run first among **pending** jobs. The running
job is never preempted.

Tie-break after priority: shorter **known** duration, then FIFO. Images
count as 1 s. Unknown length does not jump ahead of another job that also
omitted a length. A long high-priority video still runs before a short
low-priority image.

Omitted priority is `0` and keeps registration order. Non-integers are
rejected before queueing. The field is lifted off closed schemas the same
way as `output_name`.

Code: `app/services/job_lifecycle.py`
(`ensure_generation_priority`, `take_submission_priority`,
`generation_queue_seconds`).

---

## 6. Compact catalogs and `invalid_selector`

`models` / `models.list` and `scenes.catalog` default to
`{id, name, one-line description, counts}`. Pass `detail: true` for the full
JSON, or `id` / `model_type` for one full entry. Images are not inlined in
the summary. Code: `app/services/mcp_compact.py`.

A rejected selector returns `invalid_selector` with a short `allowed` list.
When that list is truncated, `truncated: true` and `model_detail: "models"`
point at the full catalog. Code: `app/services/model_selectors.py`.
