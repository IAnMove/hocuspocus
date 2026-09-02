# Domain model and asset provenance

Status: accepted foundation (2026-09-02)

This decision separates durable creative work from execution and from files.
It extends the existing command plane; it does not create a second Wizard API.

## Canonical nouns

- **Project** is a durable creative document: Story, Series, episode, comic,
  Video3D scene, character kit or editor project. A title is presentation; its
  immutable ID is identity.
- **Asset** is an imported or generated file plus a versioned provenance
  manifest. Assets are globally discoverable and may be related to zero or
  more projects and workspaces.
- **Workspace** is an optional, explicit collection of references used to
  group a collaboration or goal. It is not the identity of a project and must
  not be inferred merely because a directory exists.
- **Production** is a prepared output plan, such as a film, trailer, episode
  assembly or music video.
- **Run** is one execution attempt of a production or command. Retrying creates
  a new run while retaining lineage to the prior attempt.
- **Task** is a technical queued step belonging to a run.

The identity chain is therefore:

```text
project ─┐
workspace├──> production -> run -> task -> asset
inputs ──┘                              -> asset
```

Every command and relationship propagates opaque IDs. Names, selected labels
and `v1`-style display versions are never used to recover an identity that was
already returned by the previous step.

## Storage transition

Existing workspace folders and `.meta.json` files remain readable. New APIs
will expose registries/read models before any physical file move:

1. add the asset manifest contract and legacy adapter;
2. build a global asset catalog over canonical and legacy sidecars;
3. expose project adapters over the existing Story/Series/Comic/etc. stores;
4. expose Productions and Runs independently;
5. add an explicit workspace registry containing references;
6. replace implicit `active_workspace` fallbacks at mutating boundaries;
7. place unclaimed legacy records in the virtual `Inbox / Legacy` collection.

The migration must be additive and reversible. No old output is deleted or
moved merely because its metadata cannot be upgraded. Remaining work is listed
in `SLICE_QUEUE.md`.

## Workspace vs output folder

`origin.workspace_id` is an optional **Workspace collection** ID from
`/api/v1/workspace-collections`. It must not be inferred merely because a
directory exists.

`origin.output_folder` is the **physical output-folder name** (never an
absolute host path). Catalog scans still walk those folders; `locations[]`
expose both fields. A folder name is not a Workspace.

Python helpers live in `app/services/generation_provenance.py`:

- `CommandContext` — command, workflow, run, task, job, pipeline IDs
- `GenerationProvenance` — initiator (`actor` / `tool` / `capability`) vs
  provider/model (`generation.model.provider` / `generation.model.id`) vs
  location (`workspace_id` / `output_folder`)
- `resolve_generation_location` — splits the two location fields
- `provenance_from_manifest` — read model over a canonical sidecar

Legacy writers that only pass `workspace_id=` still store that string on both
fields so existing readers keep working. New writers should pass
`output_folder=` for the directory and `workspace_id=` only when a collection
ID is known.

## Initiator vs provider

Who started the work is `origin.actor` (`user` | `wizard` | `system` |
`unknown`) plus `origin.tool` and optional `origin.capability`. What computed
the bytes is `generation.model` (`provider`, `id`, `revision`). Do not store
the model provider in `origin.actor` or the initiator in `generation.model`.

## Sidecar failure policy

The media file is the generation commit. After the file exists on disk,
`publish_generation_sidecar_best_effort` writes provenance and **never
raises**. A metadata failure must not delete the artifact or mark a successful
generation as failed. Hunyuan3D and Rig already follow this rule; other
writers should switch to the helper instead of wrapping `json.dump` in the
same `try` as inference.

## Project record v1

The project registry is a portable read model over existing authoritative
stores, not a replacement store. A record preserves the immutable project ID,
kind and optional subtype, title, real revision when one exists, timestamps,
parent relationship, workspace references and logical source locators. It
never exposes an absolute host path.

Initial adapters cover Story Lab, Series Lab, embedded series episodes,
Comics, Video3D scenes and Character Kits. Legacy scene files without an ID
receive a deterministic read-time identity derived from their workspace and
filename; the source file is not rewritten. Video Editor drafts remain
excluded until they have durable server-side storage: browser `localStorage`
is not sufficient evidence for a global project registry.

## Production and Run records v1

The global read API separates an intended Production from each Run that tries
to execute it. `GET /api/v1/productions` groups retry attempts by immutable
`production_id`; `GET /api/v1/runs` exposes their status, timing and legacy
pipeline/task/job correlations. Director snapshots without canonical IDs are
adapted to deterministic IDs without rewriting their files. The schemas are
`production-record-v1.schema.json` and `run-record-v1.schema.json`.

## Workspace record v1

A Workspace is now an explicitly created collection stored in the global
registry, with optimistic revisions and lists of project, asset and Production
IDs. Its API lives at `/api/v1/workspace-collections`; it never creates, moves
or deletes generated files. The older physical directory selector remains
available during migration but is labelled **Output folder** in the UI. The
portable contract is `workspace-record-v1.schema.json`.

The Wizard uses the same collection API as the visible editor. It can create
a collection with exact project, asset and Production IDs, or update one only
by its immutable `workspace_id` (optionally guarded by `expected_revision`).
After persistence it opens Workspaces and selects the returned record. The
legacy `select_workspace` and `create_workspace` capabilities remain scoped to
physical **Output folders** and are deliberately not aliases for collections.

## Asset manifest v1

Every newly generated or imported item eventually receives one adjacent
`<stem>.meta.json` document conforming to
`asset-manifest-v1.schema.json`. The canonical data records:

- immutable asset ID, type, filename and media properties;
- origin tool/capability/actor, optional Workspace collection ID, output-folder
  name, and optional project/production refs;
- command, workflow, run, task, job and pipeline correlation IDs;
- original/effective/negative/audio prompts and their language;
- provider, model, revision, seed and effective parameters;
- created, queued, started and completed times plus queue/inference/total time;
- exact input assets and parent/transformation lineage;
- execution mode, status, errors and application/contract versions.

Secrets, credentials, authorization headers and tokens are recursively
redacted. Absolute local paths are not part of the portable contract.
Legacy top-level keys such as `params` may coexist during migration.

## UI requirement: Extra info

The existing **Extra info** action becomes the human-readable inspector for
this manifest for every asset type. It must show well-formatted sections,
relationships and timing, provide copy buttons for complete prompts and IDs,
and offer the raw JSON as an advanced copy/download view. Missing legacy data
is labelled as unavailable, never invented. This presentation is intentionally
scheduled after the canonical manifest and catalog are stable.

The global Assets tab now provides that inspector for every catalogued media
kind. **Inbox / Legacy** is a virtual filter over missing, legacy, unreadable
or invalid sidecars; reading it never moves or rewrites the underlying files.

## Compatibility and acceptance

- Existing sidecars are adapted in memory and are not rewritten on read.
- Writing is atomic and preserves explicitly supplied legacy fields.
- A retry never changes the ID of an existing asset; a distinct output gets a
  distinct asset ID.
- The contract stays independent of FastAPI, WanGP and model imports.
- Tests cover redaction, timing, identity, legacy adaptation and atomic
  round-trip. Studio generate (including the simulated worker, native WGP
  outputs, H3 Legacy and MMAudio SFX) is the first writer of the v1 sidecar.
  `command_id`, `workflow_id`, `capability` and `actor` are stored only when
  known. Missing actor is `unknown`. A `_director_pipeline_id` attributes
  origin to `director` without inventing Story or Series identities.
