# HocusPocus Wizard Automation Roadmap

## Objective

Turn **Ask to the Wizard** into a reliable application operator. The Wizard
must be able to understand a request, show the user where it is working,
configure the real application, start and follow long-running work, recover
after reloads, and report only outcomes verified by HocusPocus.

The implementation must keep two concerns separate:

1. **Reliable execution:** typed actions call stores, backend endpoints and the
   canonical queue directly. Correctness must never depend on DOM clicks.
2. **Visible magic:** navigation, focus, progressive field filling, highlights
   and particles make those actions understandable to the user. These effects
   observe execution; they do not become the source of truth.

## Invariants

- The LLM plans; HocusPocus resolves, validates and executes.
- Visible names are resolved to exact internal IDs before mutation.
- Ambiguous or stale targets fail safely.
- Destructive or compute-consuming work follows one confirmation policy.
- Every expensive operation has a deterministic `executionKey`.
- Retries must not duplicate successful or active jobs.
- Long workflows survive closing the Wizard, changing tabs and reloading.
- Chat claims come from execution reports, never from the LLM's prediction.
- UI animation may be skipped or shortened without changing the result.
- `prefers-reduced-motion` and an explicit “reduced magic” setting are honored.

## Target architecture

```text
User request
    |
    v
LLM turn: reply + structured intents
    |
    v
Capability registry / JSON schemas
    |
    v
resolve -> validate -> authorize -> execute -> correlate -> track -> report
    |                                      |
    |                                      +--> canonical queue / workflows
    v
Application adapters
    |
    +--> Studio / Story / Series / Comics / Video3D / Editor / CharacterKit
    |
    +--> presentation events (navigate, focus, reveal, sparkle, announce)
```

## Delivery strategy

Do not rewrite all existing Wizard actions at once. Stabilize the current
implementation, introduce the new infrastructure beside it, and prove the
design with one complete vertical workflow: `create_rhythmic_3d_video`.

Each phase ends with a separate commit and a testable acceptance gate.

---

## Phase 1 — Stabilize the current Wizard

### 1A. Build and conversation persistence

- Make TypeScript and ESLint pass after backend conversation persistence.
- Give the API payload concrete message/card types instead of unsafe records.
- Hydrate once per workspace without allowing a stale GET to erase a new turn.
- Reset or resolve the CAS revision when the workspace changes.
- Handle `409 revision conflict` by fetching, merging safely and retrying once.
- Ensure clearing the conversation is persisted.
- Ensure execution cards survive reloads.

Acceptance:

- TypeScript, ESLint and Wizard contract tests pass.
- Switching A -> empty B -> A never mixes conversations.
- A delayed GET cannot erase a message written after it began.
- Two tabs cannot silently overwrite each other.

### 1B. Correct misleading existing actions

- Video Editor external audio must become a real project soundtrack and reach
  the exporter as a separately validated audio source.
- CharacterKit must either persist all named references or expose a singular
  action and report exactly one.
- `open_video_editor_project` must not pretend multiple projects exist if it
  only renames the current draft.
- Add behavior tests that inspect persisted/exported payloads rather than only
  action parser output.

Acceptance:

- Action reports describe exactly what the stores and backend contain.
- Repeating each action is idempotent or explicitly additive as documented.

Status: **implemented**. Video Editor now persists one soundtrack per
workspace draft, displays it in the timeline, validates audio-only outputs and
mixes the track during export. Repeating `add_video_editor_audio` replaces that
single soundtrack. CharacterKit now accepts and reports exactly one identity
reference. `open_video_editor_project` opens only the current workspace draft
and refuses to disguise a rename as opening another project.

### 1C. Nightly runner correctness

- Do not classify known baseline failures as passes.
- Make the default no-GPU/no-provider run reproducible on this environment.
- Preserve per-job logs, JUnit and the summary on failure.
- Document implemented and intentionally missing levels.

Acceptance:

- Default nightly exits zero only when there are no new regressions.
- It never starts GPU generation or an external provider unless opted in.

Status: **implemented**. The runner preserves raw non-zero exits as
`expected_failure`, matches baselines by exact test title and file, emits
truthful JUnit skips, reports requested/executed/missing levels, and treats an
explicitly requested but unavailable level as `INCOMPLETE`. Its safe default
remains levels 1, 2, 4 and 6 with GPU and providers disabled. See
[`docs/development/WIZARD_NIGHTLY.md`](docs/development/WIZARD_NIGHTLY.md).

---

## Phase 2 — Capability registry foundation

Create a central definition for every newly migrated action:

```ts
defineCapability({
  name: 'apply_3d_rhythm',
  description: 'Bake detected rhythm into editable scene keyframes',
  inputSchema,
  risk: 'compute',
  confirmation: 'required',
  resolve,
  validate,
  execute,
  track,
  summarize,
  presentation,
})
```

The registry must generate or supply:

- LLM capability descriptions.
- JSON Schema action definitions.
- Runtime parsing and validation.
- Confirmation/risk metadata.
- Execution report metadata.
- Documentation rows.
- A minimum parser/contract test for every registered action.

Keep legacy actions behind an adapter until migrated; do not block current
features on a full conversion.

### Decision gate A — presentation contract

Before freezing this interface, review it with the user. Decide:

- Default magic speed and whether the user can choose instant/normal/theatrical.
- Whether the Wizard panel remains open while it operates elsewhere.
- How much auto-scrolling is acceptable.
- Whether field animation shows the committed value progressively or delays
  the actual commit. Recommended: commit atomically, animate a visual replay.
- Accessibility defaults and sound-effect policy.

This gate happens early enough to reserve `presentation` metadata without
building the visual effects yet.

Acceptance:

- One existing read action and one mutation run entirely through the registry.
- Existing non-migrated actions still work unchanged.

Status: **implemented**. `open_tab` and `apply_3d_rhythm` now obtain their LLM
description, input schema, runtime resolver/validator, risk and confirmation,
execution dispatch, tracking metadata, summary and presentation hints from one
typed registry. The previous action chain remains as the explicit compatibility
adapter for every action not migrated yet. Decision gate A remains open before
the presentation hints become a UI animation contract.

---

## Phase 3 — Common action runner and adapters

Every capability follows:

```text
resolve -> validate -> prepare -> confirm -> execute -> correlate -> track -> report
```

Introduce application adapters instead of DOM automation:

- `StudioAdapter`
- `StoryLabAdapter`
- `SeriesLabAdapter`
- `ComicAdapter`
- `Video3DAdapter`
- `VideoEditorAdapter`
- `CharacterKitAdapter`
- `QueueAdapter`

Adapters expose business operations and optional presentation anchors. React
components may change without invalidating the business contract.

Acceptance:

- Tests can run adapters without rendering the whole UI.
- Action outcomes contain real task/pipeline/output IDs.
- Navigation is emitted as a verified result target, not guessed separately.

Status: **implemented** for the registered-capability path. The common runner
executes all eight lifecycle stages and preserves real IDs supplied by an
operation. Eight application adapter ports isolate navigation and business
requests from React; navigation is verified against canonical store state and
returned as the report target. `open_tab` and `apply_3d_rhythm` are the first
end-to-end users. The legacy action dispatcher remains the compatibility
adapter while actions migrate domain by domain. See
[`docs/development/WIZARD_ACTION_RUNNER.md`](docs/development/WIZARD_ACTION_RUNNER.md).

---

## Phase 4 — Durable workflow runtime

Actions are immediate operations. Workflows coordinate actions and waits.

Persist per workflow:

- `workflowId`, type, workspace and user request.
- Current step and completed step outputs.
- Resolved entity IDs and immutable input snapshots.
- Task/pipeline IDs and output references.
- Confirmation scope.
- Attempts, timestamps and recoverable error.
- Cancellation and resumption state.

Required states:

```text
prepared -> queued -> waiting -> running -> completed
                                  |-> partial
                                  |-> failed -> retrying
                                  |-> cancelled
```

The canonical task event stream should wake workflows. Mechanical transitions
must not call the LLM again. The LLM is consulted only for a new creative
decision, ambiguity or replanning after a meaningful failure.

Acceptance:

- A mock workflow waits for a task, resumes on its completion event and
  produces one updated chat card.
- Reloading between steps resumes exactly once.
- Duplicate completion events do not duplicate the next action.

Status: **implemented**. Workflow checkpoints are stored atomically per
workspace behind CAS revisions. The UI runtime serializes transitions, wakes
exact waits from the canonical task event stream, remembers processed event
IDs, resumes explicitly and updates one stable chat card. Mock coverage proves
reload and duplicate completion events execute the next step once. See
[`docs/development/WIZARD_WORKFLOW_RUNTIME.md`](docs/development/WIZARD_WORKFLOW_RUNTIME.md).

---

## Phase 5 — Complete rhythmic Video3D workflow

Implement `create_rhythmic_3d_video` as the reference vertical slice:

```text
prepare/generate song
    -> wait for canonical task completion
    -> resolve exact audio output
    -> create or open Video3D scene
    -> set duration from audio/request
    -> add/resolve visual layers and camera
    -> analyze audio once
    -> create choreography plan
    -> bake editable keyframes
    -> save editable scene
    -> export and publish MP4
```

New Video3D capabilities required:

- `create_3d_scene`
- `set_3d_scene_properties`
- `add_3d_scene_layer`
- `update_3d_scene_layer`
- `remove_3d_scene_layer`
- `attach_3d_scene_audio`
- `analyze_3d_scene_audio`
- `apply_3d_choreography`
- Existing open/save/export actions migrated to the common contract.

Rhythm mapping should progress in layers:

1. Beats: pulse, bounce and small movement.
2. Downbeats: camera accents and important entrances.
3. Onset strength: scale reaction intensity.
4. Sections: shot/layout changes.
5. Drops/transitions: reveals, cuts and effects.
6. Optional lyric timing: text, mouth or narrative cues.

Acceptance:

- One Wizard request can generate the song and finish the MP4 without another
  user message.
- The same workflow resumes after reload.
- The saved scene retains editable audio, analysis choices and keyframes.
- A deterministic 120 BPM click track stays within the agreed timing tolerance.

---

## Phase 6 — Migrate high-value workflows

Migrate incrementally using the proven contract:

1. Multi-page comic creation and rendering.
2. Story film/trailer/music-video production.
3. Series episode planning, rendering, review and assembly.
4. CharacterKit creation and Face Rig preparation.
5. Video Editor assembly and export.
6. Remaining Studio and workspace actions.

Do not migrate an action without behavior tests for its real adapter and report.

---

## Phase 7 — Visible Wizard magic

Add a presentation orchestrator driven by events such as:

```ts
type WizardPresentationEvent =
  | { type: 'navigate'; area: string; section?: string; targetId?: string }
  | { type: 'reveal'; anchor: string }
  | { type: 'focus'; anchor: string }
  | { type: 'fill'; anchor: string; displayValue: string; durationMs: number }
  | { type: 'select'; anchor: string; label: string }
  | { type: 'sparkle'; anchor: string; intensity: number }
  | { type: 'announce'; message: string }
```

### Desired experience

- The requested tab and inner section visibly open.
- The viewport gently reveals and focuses the affected control.
- Inputs show a short progressive fill animation.
- Selects and toggles receive a glow/sparkle accent.
- The Wizard avatar changes state while casting.
- A short trail can visually connect the Wizard to the target control.
- The execution card remains the factual progress source.

### Robustness rules

- Controls expose stable semantic anchors such as
  `data-wizard-anchor="studio.video.prompt"`; never depend on CSS positions.
- The adapter commits through stores/backend. DOM typing is presentation only.
- Missing/unmounted anchors do not fail an otherwise successful action.
- Lazy panels acknowledge readiness before presentation begins.
- Multiple effects are queued and can be skipped by the user.
- Focus is not stolen while the user is actively typing elsewhere.
- Reduced-motion mode replaces particles/movement with a brief outline.

### Decision gate B — visual prototype

Before rolling this across the app, build one prototype covering:

1. Open Studio -> Video.
2. Reveal and focus the prompt.
3. Visually fill prompt, duration and aspect ratio.
4. Sparkle once when configuration is committed.

Review the pace, particles, focus behavior and interruption rules with the user.
Only then generalize anchors across every lab, avoiding large-scale markup work
that might need to be discarded.

Acceptance:

- The prototype remains fully correct with animations disabled.
- Keyboard focus and screen readers remain usable.
- User interaction cancels or yields the presentation cleanly.

---

## Phase 8 — Nightly and real smoke coverage

Default nightly, with no GPU or external APIs:

- Static checks and build.
- Registry/schema completeness.
- Resolver ambiguity and authorization tests.
- Workflow event, reload, retry and idempotency tests.
- Synthetic click-track rhythm tests.
- Presentation-anchor and reduced-motion tests.

Explicit opt-in smoke:

- Generate a short song.
- Continue automatically into a small Video3D scene.
- Export MP4.
- Record task IDs, audio output, BPM, beat timing error, scene name and MP4.
- Never run automatically without `RUN_GPU_TESTS=1` and/or the appropriate
  external-provider flag.

---

## Planned commit sequence

1. `fix: stabilize Wizard persistence and build`
2. `fix: align editor audio and CharacterKit references`
3. `test: make Wizard nightly reporting trustworthy`
4. `feat: add Wizard capability registry foundation`
5. `feat: add common Wizard action runner and adapters`
6. `feat: persist and resume Wizard workflows`
7. `feat: automate rhythmic Video3D productions`
8. `test: cover rhythmic workflow recovery and timing`
9. `feat: add visible Wizard presentation events`
10. `feat: animate Wizard focus, field filling and sparkles`

## Current status

Update this section after each accepted block rather than marking the entire
Agent Mode complete prematurely.

- Existing action catalog: implemented, partially on the common report contract.
- Typed capability registry: implemented for `open_tab` and
  `apply_3d_rhythm`; legacy actions remain operational through the adapter.
- Common capability runner and application adapters: implemented for the
  registered path; navigation targets are verified and report correlation is
  centralized.
- Chat execution cards: implemented.
- Backend chat persistence: stabilized (typed payloads, guarded hydration,
  workspace revision reset and CAS merge/retry); final UI smoke pending.
- Video Editor named audio: corrected and behavior-tested through the export payload.
- Basic Video3D beat keyframes: implemented and unit-tested.
- Durable multi-step workflow runtime: implemented with backend checkpoints,
  canonical-event wakeup, retry/cancel state and stable chat cards.
- Autonomous song -> Video3D -> MP4: implemented as the first durable vertical
  slice. It resolves/generates exact audio, waits on the canonical task,
  builds an editable scene, analyzes once, bakes keyframes, saves and exports;
  real GPU smoke remains opt-in.
- Rhythmic recovery and timing coverage: implemented in nightly level 5,
  including a deterministic 120 BPM click-track tolerance check.
- Comic Director creation and artwork rendering: migrated to the common Wizard
  adapter/registry contract with the real comic project ID preserved.
- Director production start: migrated to the common contract; it preserves the
  verified production target and real running pipeline ID.
- Story-to-Director staging: film/trailer and music-video preparation now
  verify and return the exact production target before launch.
- Story Lab creation and updates: migrated to the common adapter/registry
  contract, preserving the canonical story project ID after each mutation.
- Story Lab proposals and section approval: migrated to the common contract;
  generation remains reviewable until an explicit apply and approval returns the
  canonical story ID.
- Story Lab visual references: generation and approval now use the common
  contract; generated assets are correlated by their new canonical asset IDs.
- Story-to-Comic staging: migrated to the common contract and verifies that the
  Story production links to the newly created editable Comic Director project.
- Series Lab episode creation and updates: migrated to the common contract and
  return the persisted canonical episode ID.
- Series Lab planning: generation now returns the verified recoverable plan job
  ID for its canonical episode; applying a plan remains separate and explicit.
- Series Lab rendering: rendering eligible shots now returns the verified
  recoverable render-job ID tied to the canonical episode.
- Series Lab review and canon decisions: migrated to the common contract and
  keep approvals, rejections and canon mutations bound to the canonical episode.
- Series Lab assembly: migrated to the common contract and returns the verified
  recoverable assembly-job ID for the canonical episode.
- Visible focus/fill/sparkle presentation: designed here, implementation pending.

## Continuity note

Finished migration subblock **Series Lab assembly**. Continue the migration
audit with the remaining legacy domains, preserving real IDs and behavior tests
before implementing visible magic effects. Keep Decision gate A open; the
workflow remains correct without visual magic effects.
