# Slice queue

Humans own merges. Agents do not merge and do not open a second PR on the same hotspot.

Canonical sources in git:

- Domain identities: `docs/development/DOMAIN_MODEL_AND_ASSET_PROVENANCE.md`
- i18n boy scout: `docs/development/INTERNATIONALIZATION.md`
- Architecture contracts: `docs/development/ARCHITECTURE_FOUNDATION.md`

Working notes under `comunicaciones/` are session handoff only. They are gitignored and are not canonical for the repository.

## Landed on main

- i18n foundation: navigation, canonical entity names, Settings language, Wizard/Activity chrome
- Studio generate writes asset-manifest v1 (simulated worker, native WGP outputs, H3 Legacy, MMAudio SFX)

## Next slices (one PR each)

### A. Next asset-manifest writer: Tools

`publish_generation_sidecar` on `_write_tool_sidecar` only. Not Director, Series, Recast, 3D, or other writers.

### B. First bounded `useStore` slice

Extract `create<Slice>Slice(set, get)` for a cohesive non-Story/Series/Comics slice. Keep `useStore.ts` as the public facade.

### C. ADR §6 — one mutating surface

Replace implicit `active_workspace` fallbacks on one family of mutating APIs. Keep JSON contracts.

### D. Later

- Other `.meta.json` writers (Recast/Repaint/Outpaint, Director, Series, 3D, scene recordings)
- Further `useStore` slices after A/B-style cuts stay green
- `StoryLabPanel` tab split (design first)
- `director_pipeline.py` only with an explicit assignment

## Standing rules

- Boy scout: migrate visible copy of the touched UI zone, EN+ES in the same commit, glossary first. Do not mass-translate the app.
- Workspace stays the product name; physical directories stay **Output folder**.
- No WanGP / models / launchers. No `agentActions.ts` unless the assigned slice already owns it.
- `#48` stays draft unless a human asks to revive it.
- Video Editor drafts stay out of the global project registry until they have durable server storage.
- Only one pending PR may touch `_launch_runtime.py`. Only one pending PR may touch `useStore.ts`.
