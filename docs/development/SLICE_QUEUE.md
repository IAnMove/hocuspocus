# Slice queue

Humans own merges. Agents do not merge until checks are green, and never
open a second PR on the same hotspot.

PRs should be **medium and cohesive** (about 300–1,000 net lines) with one
verifiable contract. Do not open a PR per property, action or tiny component.

Canonical sources in git:

- Domain identities: `docs/development/DOMAIN_MODEL_AND_ASSET_PROVENANCE.md`
- i18n boy scout: `docs/development/INTERNATIONALIZATION.md`
- Architecture contracts: `docs/development/ARCHITECTURE_FOUNDATION.md`

Working notes under `comunicaciones/` are session handoff only. They are
gitignored and are not canonical.

## Landed on main (as of #87)

Asset-manifest v1 writers: Studio generate (simulated, WGP, H3, SFX), Tools
upscale/revoice, Recast/Repaint/Outpaint, MiniMax image, Series assembly, 3D,
Rig, Director H3 join, Director timing attach, alternative songs, scene
recording, Video Editor screenshot/export, comic animatic.

Sidecar failure: Hunyuan3D and Rig keep the GLB when provenance write fails.

Domain provenance: `workspace_id` is the collection; `output_folder` is the
physical directory. `GenerationProvenance` / `CommandContext` distinguish
initiator (`origin.actor` / `tool` / `capability`) from provider/model.
Inspector timing reads `queue_ms` / `inference_ms` / `total_ms`.

`useStore` slices (facade kept): theme, settings (includes model-visibility
focus), developerMode, sidebar, retake dialog. Slices bind through
`bindSlice` without `as never`. `developerModeSlice` no longer writes
`mediaFilter`; the facade still leaves `auditdev` when developer mode turns
off.

Story Lab: shared `ReferenceGallery`, `LocationEditor`, `CharacterEditor`,
`BeatEditor`, `storyLabVisuals` and `StoryLabVisualsProvider`. World, characters,
relationships and structure tabs import those modules instead of receiving
16 props. Visible copy on those tabs lives in the `storyLab` namespace
(EN+ES). Compact music/trailer/quick-video prep still sits in the panel.

i18n: foundation + Extra info inspector + Extra info video dialog (`extraInfo`
namespace) + Assets catalog list chrome + Story Lab simple tabs (`storyLab`).

## Next medium PRs

1. **Domain provenance contract** — landed (#86).
2. **Typed Zustand composition** — landed (#87).
3. **Story Lab simple tabs** — this PR: shared gallery/editors/controller,
   then Characters + Structure (and world/relationships i18n) without 16-prop
   drilling.
4. **Story Lab Music + Productions**: keep Wizard E2E with that PR. Do not
   fold compact prep into another tiny extract.
5. **Backend by domain**: one complete router + services per PR (Assets, Music,
   Series, Comics, …). Preserve route-table ordinals. Do not split
   `_launch_runtime.py` by line count.
6. **Provenance applied by flow** (after 1): Studio+Wizard, Story Lab+videoclip,
   Series+Comics, 3D+Director.

## Standing rules

- Boy scout: migrate visible copy of the touched UI zone, EN+ES in the same
  commit, glossary first. Do not mass-translate the app.
- Workspace stays the product name; physical directories stay **Output folder**.
- No WanGP / models / launchers. No `agentActions.ts` unless the assigned
  slice already owns it.
- `#48` stays draft unless a human asks to revive it.
- Video Editor drafts stay out of the global project registry until they have
  durable server storage.
- Only one pending PR may touch `_launch_runtime.py`. Only one pending PR may
  touch `useStore.ts`. Independent PRs may proceed in parallel when files do
  not overlap.
