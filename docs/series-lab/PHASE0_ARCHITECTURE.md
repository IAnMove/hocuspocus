# Series Lab — Phase 0 architecture

Status: approved architecture, implemented through the reviewed MVP described
in `IMPLEMENTATION.md`. This file remains the original phase/contract record;
where a historical phase boundary below says "do not add generation", it
describes that phase's former delivery gate rather than the current product.

## Product boundary

Series Lab is a separate top-level feature/tab immediately after Story Lab.
It reuses Story, Director, output, queue and editor primitives through adapters;
it is not conditional UI inside `StoryLabPanel`. The backend is the source of
truth. Each workspace has one durable library at `.series-library-v1.json`.
No binary data is embedded: assets contain Maestro paths/URLs and metadata.

Workspace routing is authoritative: the workspace selected by the API route
and resolved to the server workspace directory owns the file. `workspaceId`
is a consistency field only; a request whose payload `workspaceId` differs
from the route workspace is rejected (normalization must never silently move
or re-home data).

The hierarchy is `Series -> Season -> Episode -> Scene -> Shot -> Attempts`.
Seasons keep ordering in `episodeOrder`; episodes are normalized in
`episodesById`. All persisted entities have stable IDs.

## Contract rules

- Root `schema: "series-library"`, `version: 1`; normalizers must preserve
  unknown fields and tolerate missing optional fields.
- An episode stores `canonSnapshot` and `canonRevisionAtCreation`; reopening it
  never reads later canon implicitly.
- `proposedCanonDelta` is review data only. Applying selected changes requires
  an explicit optimistic-revision commit.
- Shots route references by IDs (`visibleCharacterIds`,
  `speakingCharacterIds`, location/prop IDs), not prompt names. The persisted
  `referenceManifest` records selected and omitted references and strategy.
- Render attempts are append-only. Rewrites create a new attempt and never
  delete accepted media or prompt/settings history.
- Expensive planning/render work is a server-side Director job, persisted with
  request hash, provider task ID, state, outputs, errors and timestamps. Browser
  state is not authoritative and restart must offer resume/discard.
- Jobs are a separate Phase 2/4 wire contract, not embedded in
  `.series-library-v1.json` v1. Their durable checkpoints must include at
  least `jobId`, `workspaceId`, `seriesId`, `episodeId`, optional `shotId` and
  `attemptId`, request payload hash, model/settings, reference manifest,
  queued/running/completed/failed/cancelled state, provider task ID, output
  asset/path IDs, retry count, error, and created/submitted/completed/elapsed
  timestamps. Recovery polls an existing provider task before resubmitting;
  discard removes pending work but never approved media.
- IDs are authoritative. Normalization rejects duplicate IDs, validates
  cross-entity references, removes or marks orphaned non-authoritative
  references with a warning, and repairs `episodeOrder` deterministically by
  retaining valid unique IDs then appending unlisted episodes by number and
  ID. It never matches entities by display name except an explicit import
  migration fallback.
- Asset URIs are owned by the workspace asset service: only contained Maestro
  asset/output paths or explicitly permitted HTTPS URLs are accepted; unsafe
  paths, traversal and opaque local paths are rejected. Binary/base64 content
  is never stored in Series JSON. Derived thumbnails/previews are separate
  asset records or service URLs with metadata linking them to the source.
- A canon delta carries `baseRevision`. Each add/change/retire item is shown
  and reviewed independently (`accepted`/`rejected`), and commit succeeds only
  when the server canon revision still equals `baseRevision`; conflicts return
  the current revision without applying any item.
- `canonSnapshot` also freezes the episode's creative/provider context:
  visual and character style, camera language, source mode and user-authored
  `masterUniversePrompt` (when applicable), `allowClipText`, provider/model
  settings, approved reference asset IDs, and the capability snapshot used by
  planning/rendering. Reopening never reads later values implicitly.
- Story import records provenance (`sourceStoryId`, source workspace and
  imported-at metadata) plus `historicalProductionIds`. It creates a new
  Series draft and never silently turns a Story production into an Episode.

## Existing-type alignment

Story fields map from `StoryProject` (brief, world, characters, locations,
relationships, assets, provider and `allowClipText`). Director adaptation maps
each shot to `ShotPlan`: ID subjects, `DialogueBeat`s, camera/audio plans,
continuity/source mode, prompts and selected references. Existing Story
productions and Director pipelines remain reopenable.

## Phase 0 decision table

| Decision | Phase 0 resolution | User approval still required? |
| --- | --- | --- |
| Product name | `Series Lab` | Yes, Phase 0 exit gate |
| Product hierarchy | `Series -> Season -> Episode -> Scene -> Shot -> Attempts` | Yes, Phase 0 exit gate |
| Storage shape and filename | `episodesById` plus `seasons[].episodeOrder`; one `.series-library-v1.json` per route workspace | No |
| Workspace authority | API route/path is authoritative; mismatched payload `workspaceId` rejects | No |
| Top-level placement | Separate Series Lab tab immediately after Story Lab | Yes, product/navigation sign-off |
| API resource names | Resource-oriented `/api/v1/series` family; exact endpoint naming remains implementation detail | No |
| Story import | New Series draft with provenance/history; no automatic Episode creation | No |
| Canon review | `baseRevision` optimistic commit with per-item accept/reject | No |
| Assets | Workspace-owned contained paths/URLs, no base64; derived thumbnails are separate records | No |
| Director mapping | Adapter maps `auto/direct/first_frame/references/first_last`; live capability metadata controls limits | No |
| Future jobs | Separate Phase 2/4 checkpoint contract, not library v1 | No |
| MVP limits | 60–90 seconds, 8–12 shots, two principals, at most two speakers per shot, two locations, MiniMax H3 first, manual review | Yes, Phase 0 exit gate |

Phase 0 exits only after the user explicitly approves the product name,
hierarchy, top-level placement and MVP limits above.

## Phase 1 boundary

Implement types, constructors, normalization/migration, workspace-scoped
list/create/get/update/delete/duplicate/import, autosave/recovery, Series setup,
canon sections and the explicit **Import Story as Series** flow. Do not add
generation, reference routing, render jobs, queue execution, voice synthesis,
or automatic canon mutation in Phase 1.

## Import Story as Series

Import is explicit and produces a new Series draft: Story overview/style/provider
fields map to Series; world/rules/locations to canon and locations; characters,
relationships and visual assets retain their IDs where safe; existing
productions remain in `historicalProductionIds`, with `sourceStoryId` and
import provenance retained. Show a review diff and never silently reclassify an
imported original project. A separate explicit one-click known-series action may
seed an editable `masterUniversePrompt`, setup and broad canon bible from the
selected writing model's general knowledge. It is labelled experimental, does
not perform live research or copy scripts/dialogue, preserves user assets, and
applies only as an unapproved draft for human fact and rights review.

## MVP limits

One series/season, one 60–90 second episode, 8–12 shots, two principal
characters, at most two speakers per shot, two canonical locations, MiniMax H3,
manual review before rendering and canon commit. No crowds with stable faces,
ten-minute automatic episodes, guaranteed lip sync, fine-tuning, publication or
fully automatic visual QA. These are domain/UI/normalizer validation limits,
not JSON-Schema cardinality constraints; the schema remains migration-tolerant.
Voice and native-audio dialogue are best effort: preserve voice/pronunciation
metadata and label lip sync as unguaranteed until measured; never claim exact
synchronization.
