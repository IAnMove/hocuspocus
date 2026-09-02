# Slice queue after #62 / #63

Status: 2026-09-02. Humans own merges. Agents do not merge and do not open a second PR on the same hotspot.

Canonical sources:

- Architecture move: `comunicaciones/plan_arquitectura_hocuspocus.md` (gitignored working copy)
- Domain identities: `docs/development/DOMAIN_MODEL_AND_ASSET_PROVENANCE.md`
- i18n boy scout: `docs/development/INTERNATIONALIZATION.md`

## Ready to merge

1. **#62** i18n foundation (`feat/i18n-foundation`). Pilot only: navigation, canonical entity names, Settings language selector, Wizard/Activity chrome.
2. **#63** Studio generate writes asset-manifest v1 (`refactor/generate-asset-manifest`). Independent of #62; either order is fine.

## After those two land

Do **one** of these next. Do not mix them.

### A. ADR §6 — one mutating surface

Replace implicit `active_workspace` fallbacks on **one** family of mutating APIs (for example Studio generate, or workspace-collection writes, not both). Callers must send the output-folder / workspace id. Keep JSON contracts; do not rename routes.

Boy scout: only if that PR also touches UI copy.

### B. Next asset-manifest writer

Same helper as #63 (`publish_generation_sidecar`) on **one** remaining writer:

1. Tools (`_write_tool_sidecar`)
2. Recast / Repaint / Outpaint shot sidecars
3. Director pipeline outputs
4. Series assembly / render
5. 3D / rig / scene recordings

Do not convert every `.meta.json` writer in one PR.

### C. Architecture Paso 4 — one UI store/panel split

After #62 is merged, any UI PR in this lane applies boy scout to the touched zone only.

Preferred first split: a bounded slice of `useStore` **or** a first extraction from `StoryLabPanel`. Not both. Not `director_pipeline.py`.

### D. Architecture Paso 5 — `director_pipeline.py`

Only after an explicit assignment. Abandon by whole function, not mid-function. Do not fuse with `app/services/director/`.

## Standing rules

- Boy scout (post-#62): migrate visible copy of the touched UI zone, EN+ES in the same commit, glossary first. Do not mass-translate the app.
- Workspace stays the product name; physical directories stay **Output folder**.
- No WanGP / models / launchers. No `agentActions.ts` unless the assigned slice already owns it.
- `#48` stays draft unless a human asks to revive it.
- Video Editor drafts stay out of the global project registry until they have durable server storage.

## Not this queue

Wizard product roadmap, 3D compositor notes, and live GPU batteries are other programmes. They do not reorder this list.
