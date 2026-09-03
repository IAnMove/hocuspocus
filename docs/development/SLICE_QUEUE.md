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

## Landed on main (as of #115)

`main` points at merge #115 (`69f57fe`, 2026-09-03). The queue below records
what is present in that tree; the numbered history is kept so earlier slice
decisions are not rewritten.

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
focus), developerMode, sidebar, retake dialog, Director, gallery/workspace
(#101), and LLM (#107). Slices bind through `bindSlice` without `as never`.
`developerModeSlice` no longer writes `mediaFilter`; the facade still leaves
`auditdev` when developer mode turns off. Gallery/workspace and LLM extraction
are landed; the remaining generation orchestration stays behind the public
facade and must be extracted in cohesive slices.

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
- #103 added `StoryAssemblyTab`, `StoryLabLibraryChrome` and the shared
  `storyLabTabs` registry. Assembly and the library header/tab/project-type/
  preparation chrome are no longer pending extractions.

Visible i18n is catalog-backed in the migrated chrome, with matching EN+ES
keys: foundation, Extra info inspector/dialog, Assets, Story Lab, Series Lab,
Director, Video Editor, workspaces, and the remaining Studio/creative UI
surfaces (#103, #105, #109). #108 also separates UI locale from conversation,
content, spoken and technical-prompt languages; UI locale must not select the
language of authored content or provider prompts. This remains incremental:
user-authored/generated text and untouched debt are not mass-translated.

Recipe audio duration: generated audio is sized for its consumers (#93).
#21 was the earlier draft of that fix and is closed as superseded.

Character Kits / Face Rig / cutout dialogue HOWUSEIT: #94 on `main`. #26 was
the older Cursor docs pass and is closed as superseded.

`--markdown` without `--check` prints **Ratchet not evaluated.** (#99). CI
uses `--check --markdown`.

### Cross-cutting work landed after #100

- **#104 — two-level UI architecture:** task navigation now exposes a
  primary category and inner destination, with an explicit **Output folder**
  control. The Wizard also has an embedded/sidebar presentation path.
- **#106 — LLM HTTP router:** LLM endpoints moved to `app/routers/llm.py`;
  `_launch_runtime.py` keeps the mount and wiring contract.
- **#107 — LLM store slice:** the LLM drawer state and actions live in
  `ui/src/stores/llmSlice.ts`; `useStore` remains the compatibility facade.
- **#110 — compositor boot intro:** the intro animation stays on the
  compositor, reducing per-frame browser work.
- **#111 — H3 owner handoff:** legacy H3 GPU ownership is stabilized with
  scheduler coverage.
- **#112 — Director temporary audio:** transient Director audio slices are
  hidden from the user-facing output flow while their jobs run.
- **#113 — Director server audio adoption:** Story audio that the server
  already owns is adopted by name with its Workspace/output-folder context;
  the browser does not round-trip the bytes before Director analyzes it.
- **#114 — new Story song before videoclip:** a request for a new song creates
  a fresh `music_video` Story, writes and generates its vocal cue, then carries
  that cue into Director. The reconciler no longer falls back to an unrelated
  selected project/song. The `music-video-new` acceptance scenario covers the
  identity chain.
- **#115 — media card viewport sizing:** rendered output cards and their
  virtualization share a viewport cap, including vertical-resize invalidation,
  so cards stay usable inside the feed.

## Queue history (original order, statuses updated)

1. **Domain provenance contract** — landed (#86).
2. **Typed Zustand composition** — landed (#87).
3. **Story Lab simple tabs** — landed (#88).
4. **Story Lab Music + Productions** — landed (#91, split further in #97).
5. **Story Lab Overview** — landed (#98).
6. **Story Lab Assets tab** — landed (#100).
7. **Story Lab assembly + library chrome** — landed (#103), including
   `StoryAssemblyTab` and `StoryLabLibraryChrome` with EN/ES.
8. **`useStore` slices** — gallery/workspace landed (#101), Director is
   extracted, and the LLM slice landed (#107). Keep the public facade and
   extend `architectureSlices.test.mjs`; do not move all of `startGeneration`
   in one PR. At most one open PR may touch `useStore.ts`.
9. **Backend by domain** — LLM router landed (#106). Continue with one
   complete router + services per PR (Assets, Music, Series, Comics, …),
   preserving route-table ordinals. Do not split `_launch_runtime.py` by line
   count.
10. **Provenance applied by flow** — Studio+Wizard landed (#95), and the
    Story song → Director handoff was hardened by #112–#114. Series+Comics
    and the final identity checks still remain. 3D+Director already has
    folder-vs-Workspace provenance (#89).

## Current next medium PRs (after #115)

1. **Close Story song → videoclip identity and provenance.** Keep the fixes
   from #112–#114 and add/verify one end-to-end contract that carries the
   exact `workspace_id`, `output_folder`, `project_id`, `cue_id`,
   `production_id`, `run_id`, `task_id` and `pipeline_id` through the new-song
   path. After an ID is returned, no step may resolve that object by title.
   Cover the Story → Director path and then the remaining Series → Comics
   handoffs separately.
2. **Wizard acceptance and real smoke.** Run the simulated
   `music-video-new` scenario first. Then run one uniquely named, explicitly
   opted-in real smoke, preserving the evidence and IDs; it must not enter
   nightly defaults or silently spend provider/GPU resources.
3. **`useStore` generation slice.** Extract one cohesive remaining generation
   or Director-orchestration slice behind the public facade, with architecture
   coverage. Keep `_launch_runtime.py` and `StoryLabPanel.tsx` out of this PR
   unless the contract requires a narrowly scoped adapter change.
4. **Story Lab coordination.** Reduce the remaining `StoryLabPanel` hotspot
   (~4,688 lines at #115) by moving coordination into hooks/controllers while
   preserving the extracted tabs, language catalogs and canonical IDs. Do not
   re-extract `StoryAssemblyTab`, `StoryLabLibraryChrome` or Assets.
5. **Backend domain router.** Choose the next complete domain boundary from
   the route inventory, extract its router and services in one cohesive PR,
   preserve route ordinals, and keep at most one pending PR on
   `_launch_runtime.py`.
6. **Director Paso 5.** Wait for a human release-order decision. Start with
   typed `5.0` `PipelineRuntime`, then one complete function/contract per PR;
   do not begin by splitting the file by line count.
7. **Visible Wizard magic expansion.** The Studio → Video prototype and
   semantic anchors already exist. Review its pace, focus, reduced-motion and
   interruption behavior before extending presentation effects to other Labs.

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
