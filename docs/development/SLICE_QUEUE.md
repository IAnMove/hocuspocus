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

## Landed on main (as of #100)

Asset-manifest v1 writers: Studio generate (simulated, WGP, H3, SFX), Tools
upscale/revoice, Recast/Repaint/Outpaint, MiniMax image, Series assembly, 3D,
Rig, Director H3 join, Director timing attach, alternative songs, scene
recording, Video Editor screenshot/export, comic animatic.

Sidecar failure: Hunyuan3D and Rig keep the GLB when provenance write fails.

Domain provenance: `workspace_id` is the collection; `output_folder` is the
physical directory. `GenerationProvenance` / `CommandContext` distinguish
initiator (`origin.actor` / `tool` / `capability`) from provider/model.
Inspector timing reads `queue_ms` / `inference_ms` / `total_ms`.

Studio+Wizard provenance landed (#95): generation task IDs are assigned before
publish so Wizard→Studio→asset can share one durable identity.

`useStore` slices (facade kept): theme, settings (includes model-visibility
focus), developerMode, sidebar, retake dialog. Slices bind through
`bindSlice` without `as never`. `developerModeSlice` no longer writes
`mediaFilter`; the facade still leaves `auditdev` when developer mode turns
off. A parallel gallery/workspace slice PR may be in flight; it has not
landed on main.

Story Lab UI extracts:

- #88 shared `ReferenceGallery`, `LocationEditor`, `CharacterEditor`,
  `BeatEditor`, `storyLabVisuals` / `StoryLabVisualsProvider`; World,
  Characters, Relationships and Structure tabs.
- #91 Music, Trailer, Productions and Compact workspace, with `storyLab` EN+ES.
- #97 split those extracted tabs into smaller panels and added the code-health
  PR table (`scripts/code_health.py --check --markdown`).
- #98 Overview + generation-agent panel, EN+ES.
- #100 Assets tab extracted with EN/ES. Assets is no longer remaining in
  `StoryLabPanel`.

i18n: foundation + Extra info inspector + Extra info video dialog (`extraInfo`
namespace) + Assets catalog list chrome + Story Lab tabs listed above.

Recipe audio duration: generated audio is sized for its consumers (#93).
#21 was the earlier draft of that fix and is closed as superseded.

Character Kits / Face Rig / cutout dialogue HOWUSEIT: #94 on `main`. #26 was
the older Cursor docs pass and is closed as superseded.

`--markdown` without `--check` prints **Ratchet not evaluated.** (#99). CI
uses `--check --markdown`.

## Next medium PRs

1. **Domain provenance contract** — landed (#86).
2. **Typed Zustand composition** — landed (#87).
3. **Story Lab simple tabs** — landed (#88).
4. **Story Lab Music + Productions** — landed (#91, split further in #97).
5. **Story Lab Overview** — landed (#98).
6. **Story Lab Assets tab** — landed (#100).
7. **Story Lab assembly + library chrome** — remaining: extract Assembly tab
   and leftover library chrome (header, tab labels, project types, prepare
   buttons, nav notes) with EN/ES. No `useStore.ts` / `_launch_runtime.py`.
8. **`useStore` slice** — one moderate cohesive extract with the public facade
   kept and `architectureSlices.test.mjs` extended. Do not move all of
   `startGeneration` in one PR. At most one open PR may touch `useStore.ts`.
   A gallery/workspace slice may already be in flight; do not claim it landed.
9. **Backend by domain**: one complete router + services per PR (Assets, Music,
   Series, Comics, …). Preserve route-table ordinals. Do not split
   `_launch_runtime.py` by line count.
10. **Provenance applied by flow**: Studio+Wizard landed (#95). Remaining:
   Story Lab+videoclip, Series+Comics. 3D+Director already has folder vs
   Workspace provenance (#89). Do not start Director Paso 5 until a human
   decides release order; that work must begin with 5.0 PipelineRuntime.

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
