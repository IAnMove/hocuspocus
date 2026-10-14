# Shared Workspace collection commands

Workspace collections are logical groups of canonical project, asset and
Production IDs. They do not select an output folder or move source files.

The collection command circuit uses the existing `WorkspaceRegistry` as its
only data authority. The web editor, Wizard and MCP call the same versioned
operations. No worker, generation queue or second collection registry is added.
This is the first data-domain slice of the Wizard/MCP plan, not coverage of all
editorial, generation, Scene3D or workflow operations.

## Catalog and invocation

`GET /api/v1/commands` returns version 1 of the executable operation catalog.
`POST /api/v1/commands` accepts:

```json
{
  "version": 1,
  "operation": "collections.create",
  "intent_id": "example-create-001",
  "input": {
    "name": "Nightwatch launch",
    "description": "Screens and product assets",
    "project_ids": [],
    "asset_ids": [],
    "production_ids": []
  }
}
```

| Operation | Required input | Effect |
| --- | --- | --- |
| `collections.create` | `name` | Creates one collection and a durable receipt. Empty membership is valid. |
| `collections.update` | `workspace_id`, `expected_revision` | Updates that exact revision; omitted editable fields are preserved. |
| `collections.get` | `workspace_id` | Reads the current canonical record. |
| `collections.list` | Empty object | Lists logical collections. |
| `commands.receipt` | `intent_id` | Reads the historical committed result of an intention. |

Only create/update accept an execution `intent_id` on the envelope. Read
operations put their arguments in `input` and omit the envelope intention.
All operations require the explicit integer version. Unknown fields, null
collection fields, invalid revisions, duplicate reference IDs and unknown
references are rejected before a domain write. References resolve through the
application's existing exact-ID catalog handlers, including across output
folders when the caller explicitly selected those IDs.

`app/services/workspace_commands.py` defines the schemas and executable names.
`scripts/export_workspace_command_catalog.py` projects that catalog into
`ui/src/api/workspaceCommandCatalog.json`; `--check` and the Python contract test
detect drift. New names must have an executable handler before discovery exposes
them. The catalog's `inputSchema` describes the full HTTP command, including
its constant `operation`; MCP derives its argument schema by removing that
field because the tool name supplies it. Reference arrays advertise unique
items and names require a non-whitespace character. This catalog currently
contains only the five operations above.

## Intention, effect and recovery

An intention is scoped to the installation/registry, independent of browser,
transport and physical output folder. Reuse the same opaque ID after a lost
response. A deliberate second creation gets another ID, even when its content
is identical. Changing content or a revision precondition under a committed ID
returns `intent_conflict`.

Fingerprint version 1 covers contract version, operation and validated effective
input, including `expected_revision`. Creation defaults are resolved before
hashing. Original submitted input and effective input are stored separately.
The domain's existing text normalization still defines the canonical record.

The registry stores the mutation and its receipt in the same JSON document and
commits them with one atomic replacement. Every registry reader/writer takes the
same cross-process lock. The temporary file is flushed before replacement; the
parent directory is also flushed on POSIX. A crash before replacement leaves no
effect; a lost response after replacement can replay the persisted receipt.
There is no reservation expiry that retries an unproven effect.
An existing malformed receipt is a storage error, never an unused intention.
Its mutation cannot be repeated while the registry needs repair.

Successful mutation receipts carry `version`, `commandId`, `operation`,
`status: completed`, `entities` with ID/revision, `result` with the canonical
collection, empty artifact/task/pipeline arrays, and a `replayed` flag. A receipt
is historical: if the collection was later edited or deleted, replay returns
that original result and does not recreate it. Use `collections.get` to inspect
its current revision.

Command HTTP errors contain `detail.code`, `detail.message` and
`detail.retryable`. Codes include `invalid_command`, `not_found`,
`reference_error`, `revision_conflict`, `intent_conflict` and
`uncertain_response`. Storage uncertainty retains the intention for recovery;
it does not imply that the effect failed to commit.

## Wizard and manual editing

The capability runner's command ID reaches the backend before mutation. The
Wizard navigates to the collection editor, waits for its mounted/loaded state,
and requests presentation of the exact draft. A correlated acknowledgement is
sent after React commits those fields. Unrelated unsaved edits, a busy editor,
an unmounted view or an obsolete revision stop preparation before admission.
Manual controls in that editor are disabled only while the synchronous mutation
is being submitted.
Malformed or duplicate Wizard reference IDs reject the whole action; they are
not silently dropped or truncated into a different collection membership.

The shared command is the sole writer. Presentation never clicks a second
mutation button. On success, the editor applies the returned ID and revision.
If presentation fails after commit, the adapter keeps the receipt and explains
that the collection was saved but its view could not be confirmed. Cards open
Workspace collections through their proper destination.

The manual create/save controls use the same command API. A per-intention local
recovery hint is written before submission. It contains the original request,
not a claim of success. Uncertain requests remain visible under **Requests
awaiting a confirmed result**, including after reload. The explicit recovery
button retries that same intention; the backend decides whether to replay or
commit it. Storage hints from different tabs use different keys, so one pending
request cannot overwrite another client's hint. Server receipts remain the
authority even if browser storage cannot be updated after a successful commit.

## MCP and compatibility

The existing opt-in MCP endpoint and its token/origin checks are retained.
The five catalog operations appear as tools when their handlers are mounted.
The MCP factory also accepts a trusted application-supplied `command_operations`
catalog so later domains can reuse the same discovery, argument forwarding and
structured results. The default remains these five collection operations;
entries without a mounted handler are never published.
An omitted command cannot be invoked through the legacy fallback. Supplied
command names must be unique and cannot collide with the ten legacy names.
For `tools/call`, use the operation name as the tool name and put `version`,
`input` and (for mutations) `intent_id` in `arguments`; omit `operation` there.
Responses expose structured content and readable JSON. Command errors set
`isError` and include the same structured error fields. The HTTP command routes
inherit the application's existing LAN authentication (full server only; the
core server has no LAN gate, see [LAN_AUTH](LAN_AUTH.md)) and cross-origin
mutation guards; adding the routes does not disable or bypass those guards.

The ten legacy tools keep their names. Legacy `organize` continues to require
nonempty exact asset membership and returns its original record shape. New
`organize` effects use the shared domain command internally. A legacy journal
reservation without a result is recoverable only when the domain can prove a
matching committed intention; otherwise it remains uncertain. Existing completed
legacy receipts/digests are returned unchanged. Generation/recast/upscale
reservations are not made retryable by this collection-specific proof. Storage
5xx responses leave reservations uncertain, including a failure after the
collection and receipt were replaced. A temporary read failure also remains
recoverable instead of being treated as an invalid client request.

Legacy HTTP CRUD routes remain compatible, including optional revision on old
PUT and unguarded DELETE. New commands always require an edit revision. Delete
migration, complete generation/editor schemas, server workflow execution and
headless rendering are separate slices. Do not run old and new server binaries
as simultaneous writers: old binaries do not participate in the new lock.
Host-crash behavior on Windows/network filesystems needs platform validation;
Linux process/restart tests alone do not certify those platforms.
