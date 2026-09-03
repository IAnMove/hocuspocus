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

## Open integration queue (#116–#119)

These PRs are open against the #115 `main` baseline; the following status is
the state at the time of writing, not a claim that any of them has landed.

- **#116 — this documentation update:** the queue and Wizard roadmap record
  the state after #115 and the recommended merge order.
- **#117 — Studio configuration slice:** open and green. The typed
  `studioConfigurationSlice` owns Studio form/configuration state while
  `startGeneration` and Tools execution stay in `useStore`; the public facade
  and architecture coverage remain intact. The PR reduces `useStore.ts` from
  10,239 to 9,741 lines.
- **#118 — Story Lab production controller:** open and green. The
  `storyProductionController.ts` owns Story Lab → Director production handoff
  for film/trailer and music-video flows, including model/reference/audio
  preparation. The PR reduces `StoryLabPanel.tsx` from 4,688 to 4,395 lines
  without touching `useStore.ts` or `_launch_runtime.py`.
- **#119 — exact Story song → music-video identity/provenance:** open and
  still under review. The critical simulated E2E passed. An opt-in real smoke
  generated the requested song and an H264/AAC video of 19.75 seconds, but the
  harness initially reported a false negative after selecting a lateral
  `Untitled story` project; selection by exact requested title has now been
  corrected. #119's CI and Cursor checks are still in progress and it must not
  be described as finished yet.

Recommended integration order: **#116 → #117 → #118 → #119**. Keep #119's
remaining checks and the corrected exact-title smoke evidence attached to the
final review.

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

## Next medium PRs after integrating #116–#119

1. **Series → Comics provenance.** Apply the same exact-ID contract used by
   #119 to the remaining cross-domain handoff, with persisted project,
   production, run, task and output references and no title lookup after an ID
   has been returned.
2. **Remaining `useStore` generation slice.** #117 moves Studio
   configuration only. Extract one cohesive remaining generation or
   Director-orchestration slice behind the public facade, with architecture
   coverage; do not move all of `startGeneration` in one PR.
3. **Remaining Story Lab coordination.** #118 moves production handoff into
   a controller. Continue reducing the residual `StoryLabPanel` hotspot
   (~4,395 lines on the #118 branch) through hooks/controllers while
   preserving extracted tabs, language catalogs and canonical IDs. Do not
   re-extract `StoryAssemblyTab`, `StoryLabLibraryChrome` or Assets.
4. **Backend domain router.** Choose the next complete domain boundary from
   the route inventory, extract its router and services in one cohesive PR,
   preserve route ordinals, and keep at most one pending PR on
   `_launch_runtime.py`.
5. **Director Paso 5.** Wait for a human release-order decision. Start with
   typed `5.0` `PipelineRuntime`, then one complete function/contract per PR;
   do not begin by splitting the file by line count.
6. **Visible Wizard magic expansion.** The Studio → Video prototype and
   semantic anchors already exist. Review its pace, focus, reduced-motion and
   interruption behavior before extending presentation effects to other Labs.

## Residual risks to track separately

- The real smoke produced valid H264/AAC media, but its lyrical content was
  semantically generic. Treat that as a content-quality follow-up, not as
  evidence that the identity/provenance chain failed.
- Conversation `409` revision conflicts under concurrent writes remain a
  separate concurrency investigation; do not fold them into the #119 media
  identity acceptance claim.

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
