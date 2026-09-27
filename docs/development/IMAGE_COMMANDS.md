# Shared image command admission

Studio's image Generate button, Wizard `start_generation` in image mode, and
MCP `generation.image` share native preparation and durable command admission.
The browser builds version 2 from its complete assembled image parameters,
including references, LoRAs and advanced options. Version 1 remains available
for small text-to-image clients. Video, audio, Tools, editorial domains and
workflow execution are not covered by this slice.

## Contract and discovery

`GET /api/v1/generation/commands` describes the two executable operations.
The same entries generate MCP `generation.image` and `generation.receipt`.
The original ten MCP tools retain their existing names and behavior.
The Python schemas also generate `ui/src/api/imageCommandCatalog.json` through
`python scripts/export_image_command_catalog.py`; `--check` rejects stale
projections. Discovery preserves the correlation between each envelope version
and its input schema. It does not expose an arbitrary runtime parameter map.

Submit to `POST /api/v1/generation/commands`:

```json
{
  "version": 1,
  "operation": "generation.image",
  "intent_id": "an-intention-chosen-by-the-client",
  "input": {
    "workspace": "default",
    "model_type": "an-exact-installed-image-model-id",
    "prompt": "A literal prompt\nwith a second line",
    "resolution": "512x512",
    "num_inference_steps": 1,
    "seed": 42,
    "guidance_scale": 1.0
  }
}
```

MCP carries the operation in the tool name and omits `operation` from its
arguments. `negative_prompt` is optional. Unknown fields and authority claims
are rejected. The native image selectors, single-output counts and complete
multiline prompt policy are fixed by the contract; prompt enhancement is off.
Models must be installed and support image output without mandatory references.
Resolution uses explicit dimensions, each 64..4096 and divisible by eight.
No discovery call downloads a model. Native generation preparation remains the
authority for its model-specific rules and execution policy.

Studio and advanced MCP clients use this version 2 envelope:

```json
{
  "version": 2,
  "operation": "generation.image",
  "intent_id": "another-explicit-intention",
  "input": {
    "workspace": "default",
    "params": {
      "model_type": "an-exact-installed-image-model-id",
      "prompt": "A literal prompt\nwith a second line",
      "resolution": "512x512",
      "num_inference_steps": 4,
      "seed": 42,
      "guidance_scale": 1.0,
      "image_refs": ["/api/v1/file/reference.png?workspace=source"],
      "video_prompt_type": "I",
      "activated_loras": [],
      "loras_multipliers": "",
      "spatial_upsampling": ""
    }
  }
}
```

Qwen Image 2.1 (`qwen_image_21` and its BF16/GGUF variants) is a unified
generator and editor. There is no separate Edit-2.1 checkpoint. Version 2
local edits use `image_guide` as the source canvas, `image_mask` as the
white=change mask, `video_prompt_type` containing `VAG` (and `I`/`KI` when
identity refs are also attached), and optional `video_guide_outpainting`
as `"top bottom left right"` percents. Native 2K is `2048x2048`.

The selected model must support the supplied conditioning. Version 2 accepts
only the typed image fields declared in `studio_image_spec.py`. Optional native
sentinels and explicit null values remain in the snapshot. Active video/audio
inputs and unknown fields are rejected before admission. Repeat/batch and
multiline policies are explicit native parameters; they can produce several
images in one native job. Nested processor settings use a closed schema and
must match the installed image processor's capabilities.
Selected inputs must also match their native conditioning selectors (`I` for
references, `V` for a guide, `VA` for its mask, `S`/`E` for frames). Inconsistent
selectors and active frame lists with empty slots are rejected before admission.

References use exact asset IDs or local API URLs. Workspace file URLs must
name their source workspace, which may differ from the output workspace.
An asset with multiple locations requires an exact URL. The read-only
`POST /api/v1/generation/commands/references` converts existing absolute paths
from older UI state to canonical URLs; it never searches by basename. Selected
images have their file structure verified and are hashed. LoRAs must exist unambiguously in the selected
model's search directories and pass its existing compatibility rule. This does
not add universal tensor compatibility validation for every model family.

`input.workspace_collection_id` optionally names the target Workspace collection
and contributes to the fingerprint. The native preparation layer validates the
collection. It is separate from the physical output folder. UI surface and
workflow/run attribution travel in typed `X-Hocus-UI-Surface` and
`X-Hocus-UI-Context` headers; they grant no permissions. MCP supplies its own
external tool context. A retry returns the first admission's attribution.

## Visible browser execution

The complete native form is assembled once and detached before submission.
The shared client persists that exact command, then awaits the Studio panel's
correlated React acknowledgement before POST. The panel shows the literal
prompt, model, dimensions, workspace and reference/LoRA counts. It expands the
sidebar when needed; mobile Generate waits for admission before closing it.
The existing form remains available for manual editing. Changes to the form or
workspace during preparation cancel the pending submission before its effect.

The Wizard uses the admission's exact task/job IDs for execution cards. A later
navigation failure retains the real receipt with a presentation warning. A
pending command appears in its original output workspace after reload; its
recovery button retries the stored intention and parameters, rather than the
currently edited form. Native task/gallery projections remain authoritative
for progress and finished assets.

## Admission and progress

The response is `{receipt, replayed}`. An immutable receipt with status `queued`
proves admission and contains exact native job/task IDs. It does not prove that
a worker is currently running, that inference completed, or that media passed
quality review. Read the current task through the canonical task API or through
`GET /api/v1/generation/commands/receipt?workspace=...&intent_id=...`, which
returns `{receipt, task}`. A retained receipt may outlive task retention.

The intention namespace is the physical output workspace's TaskRegistry
database. It is independent of the installation-wide collection intentions.
Every request freezes its explicit output workspace; neither transport reads
the last browser's current selection. The field `workspace` here is an output
folder name, not a Workspace collection ID. A retry preserves that field and
the intention ID; another deliberate generation uses another intention.

The content fingerprint excludes transport identity and includes all validated
effective inputs. TaskRegistry stores the original envelope, effective input
and the prepared native runtime snapshot separately from its bounded public
task metadata. The native snapshot also freezes the engine's base settings at
admission, including omitted settings outside the typed image input. These
defaults come from the engine's settings file, not a browser's current form.
Changing those defaults while a job waits cannot alter that admitted snapshot.
They are recorded in the runtime snapshot, outside the input fingerprint.
Version 2 receipts expose `commandVersion`, `fingerprintVersion`
and `contentFingerprint` together. The fingerprint versions cannot adopt each
other's intentions. A snapshot checksum detects corrupt admission storage and fails
closed. This is integrity checking, not protection against a malicious database
administrator. Server configuration and installed model bytes are external
dependencies; storing a request does not freeze a model installation. Resource
hashes record the files inspected before admission; this slice does not make
immutable copies of references or LoRAs during a queued job's lifetime.

## Atomicity and recovery

TaskRegistry schema version 3 adds command admissions to its existing SQLite
database. One transaction commits the canonical task, creation event and
receipt. This is not another task registry or scheduler. Older binaries reject
this schema rather than modifying tasks while ignoring their receipts.

A separate atomic claim permits initial dispatch once. The existing native
FIFO and worker perform inference. The existing durable generation queue is a
recoverable projection of the stored runtime request; persistence must succeed
before dispatch. Transport retries cannot steal a claimed command after a
timeout. A failed response after admission must be recovered with the same ID.

On restart, TaskRegistry marks interrupted work and the existing queue recovery
UI can restore its native request without automatically starting inference.
Explicit resume restarts the original inference from the beginning, according
to that existing policy; it is not a mid-diffusion checkpoint. Discard records
the terminal cancellation so a later recovery scan cannot resurrect it.
The deployment remains one native generation runtime; independent API worker
processes sharing a GPU still need the broader server fencing/lease work.

The browser client persists a detached command before POST. A lost response,
invalid receipt or temporary outage preserves it across reload. A rejection
on an already uncertain retry does not delete the hint. A storage-cleanup
failure after receiving a valid receipt does not turn admission into failure.
JavaScript clients reject unsafe integer seeds instead of rounding a literal.

## Validation boundary

Provider-free service, HTTP/MCP, SQLite concurrency/failure and browser client
tests cover the command boundary. Runtime wiring tests preserve the existing
task projection and H3 preparation behavior. Real-media evidence is recorded
separately in the execution outputs and PR; unit tests do not certify GPU
generation, quality, Windows durability or every Studio parameter.
