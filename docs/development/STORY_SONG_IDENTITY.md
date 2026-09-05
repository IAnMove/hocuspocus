# Story song identity

Status: accepted for Block 3 (client persist-before-generate). Server-side
`generate-music` attach is a follow-up and is **not** in this slice.

A song version **is** `StoryMusicCandidate.id` (`song-…`). Display `v1` / `v2`
is denormalized and must never be used to recover identity.

## Persist before compute

1. Resolve the **open Story** first (`targetStoryId` / current Story Lab
   project), then a unique title. Do not invent another project.
2. Resolve the cue by **cueId**. Use title only when no ID is supplied. A stale
   title fails. Never pick an unrelated sole cue because a title was given.
3. Mint `candidateId = storyId('song')` and `version = nextMusicCandidateVersion(...)`
   **before** calling generate.
4. Save a **pending** row on that cue (`status: 'pending'`, empty source,
   provenance with `projectId` / `cueId` / `candidateId` / `songVersion`) with
   Story library CAS **before** compute starts.
5. Call generate with provenance
   `{ actor, capability, project_id, cue_id, candidate_id, song_version }`.
6. On success, patch **the same id**: source, filename, task/job ids,
   `status: 'ready'`. Do not mint a second id.
7. On failure, mark `status: 'failed'` and keep the id for retry lineage.

Client close during generate is recoverable because the pending row is already
on disk. `loadWorkspace` reattaches a WAV whose sidecar/output carries the
matching `candidate_id`, including rows marked `failed` after a client timeout
once the sidecar exists. Recovery writes the `ready` patch to the Story
library immediately; it must not only update the in-memory snapshot.

## Staging

Staging a videoclip requires a **ready** candidate by id. Pending and failed
rows are refused. The synthetic cue id `story-song` is refused unless the
caller passed that exact id.

## Normalize

`normalizeMusicCandidate` keeps pending/failed rows that already have a stable
id, even with an empty `source`. It never remints an existing id on load.
Incomplete preview rows with no id and no source stay dropped.

## Out of scope

This slice does not edit `_launch_runtime.py`, `useStore.ts` or
`agentActions.ts`. Server-side attach during `generate-music` is the next PR.
