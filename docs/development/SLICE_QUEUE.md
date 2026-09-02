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

## Landed on main (as of #85)

Asset-manifest v1 writers: Studio generate (simulated, WGP, H3, SFX), Tools
upscale/revoice, Recast/Repaint/Outpaint, MiniMax image, Series assembly, 3D,
Rig, Director H3 join, Director timing attach, alternative songs, scene
recording, Video Editor screenshot/export, comic animatic.

Sidecar failure: Hunyuan3D and Rig keep the GLB when provenance write fails.

`useStore` slices (facade kept): theme, settings (includes model-visibility
focus), developerMode, sidebar, retake dialog. Slices bind through
`bindSlice` without `as never`. `developerModeSlice` no longer writes
`mediaFilter`; the facade still leaves `auditdev` when developer mode turns
off.

Story Lab: `relationships` and `world` tabs extracted. `StoryWorldTab` is an
intermediate cut (too many props; `LocationEditor` / `ReferenceGallery` still
owned by the panel). Visible copy on extracted tabs is still hardcoded English.

i18n: foundation + Extra info inspector + Extra info video dialog (`extraInfo`
namespace) + Assets catalog list chrome.

## Next medium PRs

1. **Domain provenance contract** — landed (#86).
2. **Typed Zustand composition** (this track): `bindSlice`, no `as never` at
   compose time, settings owns model-visibility focus, developerMode does not
   write `mediaFilter`.
3. **Story Lab simple tabs**: extract shared `ReferenceGallery` /
   `LocationEditor` / controllers first, then Characters + Structure (and other
   purely visual tabs) in one PR, with i18n and tests. Do not pass 16 props.
   Music and Productions stay a later PR with Wizard E2E.
4. **Backend by domain**: one complete router + services per PR (Assets, Music,
   Series, Comics, …). Preserve route-table ordinals. Do not split
   `_launch_runtime.py` by line count.
5. **Provenance applied by flow** (after 1): Studio+Wizard, Story Lab+videoclip,
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
