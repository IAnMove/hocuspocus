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

## Landed on main (as of #137)

`main` points at merge #137 (`9ac4cacb`, 2026-09-05). That commit sits on
#138 (`3f14b0e0`) and #135 (`a899a8cc`). The queue below records what is
present in that tree; the numbered history is kept so earlier slice
decisions are not rewritten. MiniMax-Music3, generation-record v1 and the
lyrics-language library are landed. `_launch_runtime.py`, `useStore.ts` and
`agentActions.ts` are free for **one** sequential PR: durable Story song
identity.

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

## Integrated slices (#116–#120)

All five PRs are merged into `main` and their required CI checks were green at
merge. The merge commits are recorded here so a handoff never confuses a
prepared branch or an in-progress check with an accepted change.

- **#116 — documentation after #115:** merged as `215ad2a`; refreshed the
  queue and Wizard roadmap for the post-#115 state.
- **#117 — Studio configuration slice:** merged as `bfd4e9d`. The typed
  `studioConfigurationSlice` owns Studio form/configuration state while
  `startGeneration` and Tools execution stay in `useStore`; the public facade
  and architecture coverage remain intact. The extraction reduces
  `useStore.ts` from 10,239 to 9,741 lines.
- **#118 — Story Lab production controller:** merged as `e545836`. The
  `storyProductionController.ts` owns Story Lab → Director production handoff
  for film/trailer and music-video flows, including model/reference/audio
  preparation. The extraction reduces `StoryLabPanel.tsx` from 4,688 to 4,395
  lines without touching `useStore.ts` or `_launch_runtime.py`.
- **#119 — exact Story song → music-video identity/provenance:** merged as
  `4bc7376`, with simulated E2E and Cursor checks green. The opt-in real smoke
  generated the requested song and an H264/AAC video of 19.75 seconds. The
  harness's initial false negative came from selecting a lateral `Untitled
  story` project; exact-title selection is now covered by the accepted flow.
- **#120 — code-quality trend score:** merged as `658a1c3`. The current
  aggregate is **48.7/100**: complexity **52.1**, concentration **53.3**,
  oversized-file health **28.5**, and modularity **62.2**; this is **+2.2**
  against the historical committed baseline. It is a diagnostic trend signal,
  not a CI blocker or quality certificate; the existing ratchet remains the
  guardrail. CI publishes the score and comparison in PRs.

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
10. **Provenance applied by flow** — Studio+Wizard landed (#95), Story song →
    Director was hardened by #112–#114/#119, Series → Comics exact
    provenance landed (#124), and generation-record v1 landed as a
    portable projection (#138). Remaining identity work is Story music
    versions and cue-by-id recovery after the client closes. 3D+Director
    already has folder-vs-Workspace provenance (#89).

## Integrated slices (#121–#134)

These PRs are merged into `main`. Do not re-plan them.

- **#121 — documentation after #120:** `0d5b077`.
- **#122 — Wizard conversation `409` recovery:** `98b824a`. Concurrent
  conversation writes merge/retry instead of silently overwriting.
- **#123 — semantic song/lyrics language:** `c4e45d2`. Requested lyric
  language and quoted spans are preserved; UI locale does not choose content.
- **#124 — Series → Comics exact provenance:** `ecad72d`. Cross-domain
  handoff keeps project/production/run/task/output IDs.
- **#125 — remove background Tool:** `020f37e`.
- **#126 — task cost reports:** `08e1adc`.
- **#127 — rich PR template:** `78ed61e`.
- **#129 — Tools image/video upscale:** `df146f2`.
- **#130 — nightly ACE-Step smoke recipe:** `227d0e8`. Uses the local
  ACE-Step route, not a MiniMax Music model ID.
- **#131/#132 — local validation vs real smoke:** `94921fb` / `31c0a42`.
  `scripts/validate_local.sh` is provider-free; real media is
  `scripts/run_real_media_smoke.sh` with explicit confirmation.
- **#133 — Tools upscale worker extract:** `08993d5`.
- **#134 — Wizard workflow persist pinned to source workspace:** `247554a2`.

## Integrated slices (#135–#137)

These PRs are merged into `main`. Do not re-plan them.

- **#135 — local MiniMax-Music3:** `a899a8cc`. ACE-Step and MiniMax-Music3
  are selectable local backends. Wizard download, duration clamp (300s),
  caption preservation and local generate-without-API-key landed with the
  feature. This was the hotspot PR on `_launch_runtime.py` / `useStore.ts` /
  `agentActions.ts`.
- **#138 — generation-record v1:** `3f14b0e0`. Portable projection over
  asset-manifest, provenance and job lifecycle. New modules only; wiring
  into launch/Activity/Library is still sequential.
- **#137 — lyrics language guard:** `9ac4cacb`. Provider-free Spanish
  contamination checks and bounded foreign-script repair. Not yet wired
  into write-song/generate. A follow-up must replace prefix aliases
  (`English` starts with `es`; `en español` starts with `en`) with exact
  aliases plus tokens longer than two letters.

Open, not landed:

- **Docs sync (this PR).** Refresh the queue after #135/#138/#137. Does not
  touch launch, store or agent actions.

## Next medium PRs after #137

Keep these as separate, reviewable slices. Do not open a second PR on a
hotspot already owned by an open PR.

1. **Lyrics alias tokens.** `canonical_lyrics_language` must score
   `Español de España` and `en español` as Spanish and `English` as
   English. Library-only; no launch.
2. **Durable Story song identity.** Cue-by-id, distinct version IDs,
   server-side candidate finalization after the browser closes, no preview
   fragments as final songs. **The next sequential PR on
   `_launch_runtime.py` / Story music.** Wizard must read the open project
   before acting.
3. **Wire lyrics guard + generation-record** into write-song, generate and
   Activity after identity owns the launch hotspot, or in a follow-up if
   identity leaves those call sites untouched.
4. **Story Music router extract.** One complete domain from
   `_launch_runtime.py` (the four `stories/music-candidates` routes),
   preserving ordinals. Only after identity.
5. **Second `useStore` audio/generation slice.** Cohesive selection/family
   boundary; do not move all of `startGeneration`.
6. **Story Lab session controller.** Selection, load, autosave/CAS and
   rehydration; do not re-extract tabs or production handoff.
7. **Decompose `agentActions`.** Parser, request/context reconciliation,
   capability execution and confirmation as separate modules.
8. **Typed Director `PipelineRuntime`.** One complete function or lifecycle
   at a time.
9. **Activity/Library observability.** Latest real event, truncated prompt
   with copy, model/duration/status, formatted extra info, audio covers.
10. **Decision gate, then visible Wizard magic.**
11. **Release validation.** Simulated CI vs explicit local media smoke.

## Residual risks to track separately

- The real smoke produced valid H264/AAC media, but lyrical content can still
  mix languages or stay generic. Treat that as a content-quality follow-up,
  not as evidence that the identity/provenance chain failed.
- Closing the client during local music generation can leave a WAV without a
  linked cue/candidate. Server-side finalization is still required.
- #137's prefix alias treats `English` as Spanish and `en español` as
  English until the token follow-up lands.
- Generation-record v1 is a projection, not a second store, and is not
  yet wired into launch writers.
- Two local stashes remain unaudited as product work: `stash@{0}` is a CI
  workflow addition on `test/create_e2e_test`; `stash@{1}` is Hunyuan3D/
  model3d worker work. Do not apply or delete them without a human.

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

## Low-cost delegation protocol

When work is orchestrated from Codex/ChatGPT, the lead agent delegates each
bounded implementation packet to `luna_worker` (configured by
`luna-worker.toml`). This is an engineering workflow convention, not a
product dependency. A packet must name the branch base, owned and forbidden
files, contracts/invariants, tests/commands, expected PR and stop conditions.
Luna makes one bounded PR and never merges it; the lead reviews the diff,
quality score and CI before asking a human to merge. Keep at most one open PR
per hot file (`_launch_runtime.py`, `useStore`, `agentActions`). If Luna is
unavailable, the lead executes the packet or asks for direction; it must not
silently substitute a broad uncontrolled agent.

Reusable packet header:

> **Execution context: Codex/ChatGPT — delegate the bounded implementation to
> `luna_worker`; lead coordinates and reviews.**
