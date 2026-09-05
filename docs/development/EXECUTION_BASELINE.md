# Architecture execution baseline

Status: living register for the 12-phase wave (`fase1.md`–`fase12.md`).
Verified against `origin/main` **`9ac4cacb`** (2026-09-05).

This document is the single queue for that wave. Working notes under
`comunicaciones/` are historical evidence only.

## Authority by datum

| Datum | Authority | Not authority |
|---|---|---|
| Canonical tasks, job events, wait/cancel | `TaskRegistry` / `app/services/task_manager.py` and the durable generation queue | Generation-record JSON, Activity cards, chat prose |
| Story project, cue, song candidate, production | Story library (`.story-library-v1.json`) and Story domain IDs | Titles, `v1` labels, filenames, Wizard in-memory reports |
| Published bytes and provenance | Adjacent `<stem>.meta.json` asset-manifest v1 | Generation-record projection, gallery order |
| Generation attempt lifecycle | **Projection** over asset-manifest + provenance + job lifecycle (`generation-record v1`, #138) | A second scheduler, a second media store |

`GenerationRecord` does not own GPU workers, file bytes or Story candidates.
Writers stay in the existing stores. Wiring into `_launch_runtime.py` is a
later sequential PR (phases 4–5).

Workspace **collection** (`workspace_id`) is optional. `output_folder` is the
physical directory name. Do not invent a collection to satisfy a schema.

## Phase graph

Each arrow requires the **merge** of the source phase into `origin/main`, not
merely an open PR.

```text
1 → {2, 3}
3 → 4 → 5
{2, 4} → 6
{5, 6} → 7
4 → 8
5 → 9
7 → 10
{6, 7} → 11
{3, 7} → 12
```

Hotspot rule: at most one open PR may edit `_launch_runtime.py`, `useStore.ts`,
`agentActions.ts`, `StoryLabPanel.tsx`, or Director/Wizard runtime. Branches
start from current `main`; they are not stacked.

## Delivery matrix

Columns are independent. Do not infer merge from CI, or CI from a previous
commit's Cursor review.

| Entrega | Diseñado | Implementado | Commit | PR | CI del head | Cursor del head | Merge | Validación real | SHA |
|---|---|---|---|---|---|---|---|---|---|
| #135 MiniMax-Music3 | sí | sí | sí | #135 | verde al merge | 5 bugs corregidos en el head mezclado | **sí** `a899a8cc` | no (smoke local aparte) | head `93287183` |
| #138 generation-record v1 | sí | sí (proyección) | sí | #138 | verde al merge | 5 bugs corregidos (`b66ea0a9`) | **sí** `3f14b0e0` | no | head `b66ea0a9` |
| #137 lyrics guard | sí | sí (librería) | sí | #137 | verde al merge | alias `startswith` defectuoso quedó en main | **sí** `9ac4cacb` | no | head `8c696b26` |
| #136 docs cola | sí | sí | `b2bdad47` + este commit | #136 | verificar head nuevo | verificar head nuevo | no | N/A | ver PR |
| #139 lyrics alias tokens | sí (F2.3 parcial) | sí (prefijos) | `a6b7b0ff` | #139 | verde | Bugbot SUCCESS | no | no | `a6b7b0ff` |
| #140 Story song pending | sí (cliente) | sí (pending antes de generate) | `dc63eb5b` | #140 | verde en `dc63eb5b` | hallazgos de `5d513534` corregidos en `dc63eb5b`; Bugbot del head nuevo pendiente | no | no | `dc63eb5b` |

Stashes (do not apply or delete): `stash@{0}` CI e2e on `test/create_e2e_test`;
`stash@{1}` Hunyuan3D/model3d on `feat/3d-compositor-recipe`.

Cursor opened `origin/cursor/music-recovery-persistence-6c38` (`ae76c653`)
without a PR. #140 already contains the equivalent persist/reattach fix.
Do not land that branch unless a human compares it with `dc63eb5b`.

## What #135/#137/#138/#139 still leave open

Verified on `9ac4cacb` plus the open PR heads. Do not copy old Cursor
findings onto a SHA that already fixed them.

| Source | Already in tree | Still missing |
|---|---|---|
| #135 | Local ACE-Step + MiniMax-Music3, download, 300s clamp, captions, generate without API key | Server-side song attach; lyrics guard not wired; generation-record not wired |
| #137 | Spanish contamination + bounded CJK/Arabic strip; `[Verse]` allowed | Prefix aliases on main (`English`→es, `en español`→en); empty vocal / unevaluable language / Estonian-as-Spanish; destructive repair-by-default; wiring to generate |
| #138 | Portable generation-record projection; cancel/retry/timing mapping | Empty-list patch semantics; write-point CAS; optional workspace collection; no producer wiring |
| #139 | Token aliases longer than 2 letters | Remaining F2 corpus (empty vocal, unsupported language ≠ ok, protected multiline exact, no destructive default) |
| #140 | Pending `song-…` before generate; sidecar recovery; refuse pending staging | Server finalization without browser (phase 5); launch still blocking POST |

## Next slices (this wave)

Mapped onto `fase1.md`–`fase12.md`. Do not open a slice whose arrow is not
merged.

1. **Phase 1 (this PR)** — this baseline.
2. **Phase 2** — continue #139 after phase 1 merges: unevaluable languages,
   exact protected spans, no destructive default.
3. **Phase 3** — generation-record authority after phase 1 merges.
4. **Phase 4** — idempotent music submit (minimal `_launch_runtime.py`).
5. **Phase 5** — server-side music finalization (launch sequential after 4).
6. **Phase 6** — music spec/catalog after 2 and 4 merge.
7. **Phase 7** — async client rehydration after 5 and 6.
8. **Phase 8** — Wizard workflow concurrency after 4.
9. **Phase 9** — Story Music router extract after 5.
10. **Phase 10** — Story session controller after 7.
11. **Phase 11** — Studio music `useStore` slice after 6 and 7.
12. **Phase 12** — visible traceability after 3 and 7.

Real media smoke remains `bash scripts/run_real_media_smoke.sh` with explicit
confirmation. It is never GitHub Actions.
