# Labs ↔ Wizard action matrix (L0)

Status: detailed L0 fixture/reference with L5–L12 updates; not the startup checklist.
For current delivery state and remaining QA, read [CURRENT_WORK](CURRENT_WORK.md).
The machine fixture preserves historical classifications: a frozen defect ID is
not proof that its defect is still present after the linked fixes.

## Base

- Integration SHA: `e465a56ebbdcc979c73578655b6965b69db9976e` (`origin/development`).
- Date: 2026-09-06.
- PR #179: **merged**. PR #180: **merged**.
- Visual audit SHA (unchanged Labs files vs this freeze for Story/Series/Agent): `5a0040c55219b04082d9e962f8e021baa6d3266d`.
- Audit: 42 browser states; 94 selected UI tests; 191 selected backend tests; 0 real generations.
- Canonical machine-readable copy: `tests/fixtures/labs_wizard_action_matrix.json`.
- Effective H3 prompt freeze (before UI and before queue): `tests/fixtures/h3_prompt_fase1_expected.json` reused by `tests/test_h3_prompt_finalization.py`. Do not refresh that fixture to hide a prompt change.

## Methodology

- One row is one **user operation**, not one tab and not one i18n string.
- Inventory components from `INVENTARIO_CONTROLES.md` are classified as **control groups** pointing at operations. Hidden help text is not counted as a simultaneous visible control.
- `wizard_available` is true only when the capability is registered, the domain function is identified, the action is in the live Wizard context (or is a non-Labs capability), and there is no documented blocking defect. Appearing in `AGENT_ACTION_TYPES` is not enough.
- `actor=user` stays on UI handlers; `actor=wizard` stays on the runner. Both must share the domain operation listed here.
- Classifications: `operativa`, `condicional`, `solo_navegacion`, `solo_informacion`, `no_expuesta`, `sin_implementar`.

## Historical gap IDs and implementation follow-up

| Id | Phase | Summary |
|---|---|---|
| `fused_dropped_by_model_for_manifest` | L1 | Addressed in #183/#197: fused IDs stay fused; references use minimax_h3_ref2va_fused_turbo; frames use minimax_h3_fused_turbo. Real GPU verification was not repeated by L12. |
| `partial_global_profile_guard` | L2 | Addressed in #183/#197: seriesProviderMatchesGlobal includes writingBaseUrl, flowShift, audioShift and modelProfile. Frozen episode snapshots stay. |
| `approve_all_replaces_chosen_takes` | L3 | Addressed in #183/#197: pending takes / all_latest keep valid finals; replace_latest and explicit selected_latest remain replace paths. |
| `shot_number_is_not_attempt_id` | QA | Addressed in #201: `attempt_id` on `selected_latest` with exactly one shot selects that historical take; `shot_numbers: [2]` without `attempt_id` remains latest of shot 2. |
| `script_shots_dialogue_desync` | L4 | Addressed in #183/#197: script edits annotate stale shots; render refuses them; sync is explicit. Full UI-to-real-render validation is separate. |
| `blocked_always_empty` | L5 | Addressed: availability is derived as executable / needs_data / blocked / requires_navigation. |
| `stage_series_comic_unregistered` | L6 | Addressed: stageSeriesComic is exposed as `stage_series_comic` on the existing Series comic handoff. |
| `wizard_auto_approves_canon` | L7 | Addressed: episode creation may approve only a brand-new canon base from the same request, never pending canon on an existing series. |
| `false_success_invisible_tab` | L8 | Addressed: open_story_section resolves a visible tab or explains incompatibility; it never claims an invisible tab opened. |
| `t2v_double_mode_and_image_requirements` | L9 | Addressed: exclusive visual modes; T2V does not require identity images. |
| `voice_bible_not_h3` | L10 | Series voice bible fields persist but do not change the inspected H3 shot prompt. |
| `ace_labelled_as_minimax` | L11 | Addressed: StoryMusicSettingsBar names ACE, MiniMax Music 3 local and MiniMax API from the effective model. |
| `runtime_calls_omit_explicit_policy` | H-A | Addressed: runtime adapt_clip_plans_for_h3 now passes effective policy; ref2va quote path uses models-safe language tags. Default remains native when omitted. |
| `audio_policy_contradictions` | H-B | Addressed: plan vs send recorded on existing Director provenance fields; quoted 'Qué silencio' is dialogue, not a mute order. |
| `creative_does_not_add_dialogue_in_cited_tests` | H-C | Addressed: Creative extra lines come from the LLM transport, not a canned post-LLM sentence. Faithful and 'only these lines' keep extras out. |

## Story, Series, Wizard, and H3 operations

| Id | Lab | Classification | Phase | Wizard | Status | Domain function | Test |
|---|---|---|---|---|---|---|---|
| `story.nav.open_section` | story | solo_navegacion | L8 | `open_story_section` | disponible | `open_story_section` | `ui/tests/labsWizardL8.test.mjs` |
| `story.library.create` | story | operativa | L6 | `create_story` | disponible | `createFilledStory` | `ui/tests/storyLibraryMerge.test.mjs` |
| `story.library.update` | story | operativa | L6 | `update_story` | disponible | `updateFilledStory` | `ui/tests/storyWritingProvider.test.mjs` |
| `story.library.duplicate_delete` | story | operativa | L9 | `—` | dominio_sin_capacidad | `saveStoryLibrary` | `ui/tests/storyLibraryMerge.test.mjs` |
| `story.workflow.mode` | story | condicional | L7 | `—` | dominio_sin_capacidad | `updateFilledStory` | `ui/tests/storyProductionController.test.ts` |
| `story.prepare.section_text` | story | operativa | L6 | `generate_story_section` | disponible | `generateStorySectionDraft` | `ui/tests/storyActivityLifecycle.test.mjs` |
| `story.prepare.apply_proposal` | story | operativa | L7 | `apply_story_proposal` | disponible | `applyStoredStoryProposal` | `ui/tests/commandContract.test.mjs` |
| `story.section.approve` | story | operativa | L7 | `approve_story_section` | disponible | `approveStorySection` | `ui/tests/storyProvenance.test.ts` |
| `story.assets.import_analyze` | story | operativa | L6 | `—` | dominio_sin_capacidad | `analyzeStoryAssets` | `tests/test_story_asset_import.py` |
| `story.visuals.generate` | story | operativa | L6 | `generate_story_visuals` | disponible | `generateStoryVisuals` | `ui/tests/storyVisualRequest.test.mjs` |
| `story.visuals.approve` | story | operativa | L7 | `approve_story_visuals` | disponible | `approveStoryVisuals` | `ui/tests/storyVisualRequest.test.mjs` |
| `story.world.edit` | story | operativa | L9 | `update_story` | disponible | `updateFilledStory` | `ui/tests/storyLabResponsive.test.tsx` |
| `story.characters.edit` | story | operativa | L9 | `update_story` | disponible | `updateFilledStory` | `ui/tests/storyLabResponsive.test.tsx` |
| `story.relationships.edit` | story | operativa | L9 | `update_story` | disponible | `updateFilledStory` | `ui/tests/storyLabResponsive.test.tsx` |
| `story.structure.edit` | story | operativa | L9 | `update_story` | disponible | `updateFilledStory` | `ui/tests/storyLabResponsive.test.tsx` |
| `story.music.configure` | story | operativa | L11 | `configure_story_song` | disponible | `configureStorySong` | `ui/tests/storyMusicModel.test.ts` |
| `story.music.generate` | story | condicional | L11 | `generate_story_song` | disponible | `generateStorySong` | `ui/tests/storySongRecovery.test.mjs` |
| `story.music.import` | story | operativa | L11 | `attach_videoclip_alternative_song` | registrada_fuera_de_contexto | `attachAlternativeSong` | `ui/tests/alternativeSongs.test.tsx` |
| `story.trailer.recipe` | story | condicional | L9 | `update_story` | disponible | `updateFilledStory` | `ui/tests/trailerDefaults.test.mjs` |
| `story.productions.comic` | story | condicional | L5 | `stage_story_comic` | registrada_fuera_de_contexto | `stageStoryComic` | `ui/tests/storyComicProgress.test.mjs` |
| `story.productions.video` | story | condicional | L9 | `stage_story_video` | registrada_defectuosa | `stageStoryVideo` | `ui/tests/storyProductionController.test.ts` |
| `story.productions.music_video` | story | operativa | L11 | `stage_story_music_video` | disponible | `stageStoryMusicVideo` | `ui/tests/musicVideoSelection.test.mjs` |
| `story.productions.director` | story | operativa | L7 | `start_director_production` | disponible | `startDirectorProduction` | `ui/tests/storyProductionController.test.ts` |
| `story.productions.quick_batch` | story | operativa | L9 | `—` | dominio_sin_capacidad | `startQuickVideoBatch` | `ui/tests/quickVideoBatchMode.test.tsx` |
| `story.assembly.history` | story | operativa | L9 | `—` | dominio_sin_capacidad | `startDirectorProduction` | `tests/test_story_montage_clip_history_ui.py` |
| `story.music.legacy_drawer` | story | no_expuesta | L11 | `—` | dominio_sin_capacidad | `—` | `ui/tests/storySongRecovery.test.mjs` |
| `story.prepare.cancel_recover` | story | operativa | L6 | `resume_task` | registrada_fuera_de_contexto | `resumeStoryGeneration` | `ui/tests/storySongRecovery.test.mjs` |
| `series.nav.open_section` | series | solo_navegacion | L8 | `open_series_section` | disponible | `open_series_section` | `ui/tests/seriesResponsive.test.tsx` |
| `series.library.create` | series | condicional | L6 | `create_series_episode` | disponible | `create_series_project` | `tests/test_series_library.py` |
| `series.library.import_story` | series | operativa | L6 | `—` | dominio_sin_capacidad | `importStoryAsSeries` | `tests/test_series_library.py` |
| `series.library.duplicate_delete` | series | operativa | L10 | `—` | dominio_sin_capacidad | `duplicateSeriesProject` | `tests/test_series_library.py` |
| `series.episode.create` | series | condicional | L7 | `create_series_episode` | disponible | `createFilledSeriesEpisode` | `ui/tests/labsWizardL7.test.mjs` |
| `series.episode.delete` | series | operativa | L10 | `—` | dominio_sin_capacidad | `deleteSeriesEpisode` | `tests/test_series_lifecycle.py` |
| `series.setup.edit` | series | operativa | L2 | `update_series_episode` | disponible | `saveSeriesProject` | `tests/test_series_lab_ui.py` |
| `series.setup.bootstrap_known` | series | operativa | L6 | `—` | dominio_sin_capacidad | `startSeriesCanonPreparation` | `tests/test_series_planning.py` |
| `series.setup.model_options` | series | condicional | L2 | `render_series_shots` | registrada_defectuosa | `model_for_manifest` | `tests/test_series_render.py` |
| `series.setup.global_profile` | series | condicional | L2 | `—` | dominio_sin_capacidad | `updateSeries` | `ui/tests/productionProfile.test.mjs` |
| `series.canon.edit` | series | operativa | L10 | `—` | dominio_sin_capacidad | `saveSeriesProject` | `tests/test_series_library.py` |
| `series.canon.voices` | series | solo_informacion | L10 | `—` | dominio_sin_capacidad | `shot_generation_prompt` | `tests/test_series_render.py` |
| `series.canon.approve` | series | condicional | L7 | `commit_series_canon` | disponible | `approveSeriesCanon` | `tests/test_series_library.py` |
| `series.episode.edit` | series | condicional | L4 | `update_series_episode` | registrada_defectuosa | `updateSeriesEpisode` | `tests/test_series_episode_update_router.py` |
| `series.plan.generate` | series | operativa | L6 | `generate_series_plan` | disponible | `generateSeriesPlan` | `tests/test_series_planning.py` |
| `series.plan.apply` | series | operativa | L6 | `apply_series_plan` | disponible | `applySeriesPlan` | `tests/test_series_planning.py` |
| `series.comic.stage` | series | operativa | L6 | `stage_series_comic` | disponible | `stageSeriesComic` | `ui/tests/seriesComicProvenance.test.ts` |
| `series.shots.render` | series | condicional | L1 | `render_series_shots` | registrada_defectuosa | `renderSeriesShots` | `tests/test_series_render.py` |
| `series.shots.edit_prompt_cast` | series | operativa | L10 | `update_series_episode` | disponible | `update_series_episode` | `ui/tests/seriesShotsAccessibility.test.tsx` |
| `series.shots.duration` | series | operativa | L4 | `—` | dominio_sin_capacidad | `plan_series_shot_duration` | `ui/tests/seriesShotDurationControl.test.tsx` |
| `series.review.approve_one` | series | operativa | L3 | `review_series_attempts` | disponible | `approve_episode_render_attempts` | `ui/tests/seriesShotSelection.test.tsx` |
| `series.review.approve_all` | series | condicional | L3 | `review_series_attempts` | registrada_defectuosa | `reviewSeriesAttempts` | `ui/tests/seriesShotSelection.test.tsx` |
| `series.review.reject` | series | operativa | L3 | `review_series_attempts` | disponible | `rejectSeriesAttempt` | `ui/tests/seriesShotSelection.test.tsx` |
| `series.review.assemble` | series | operativa | L6 | `assemble_series_episode` | disponible | `assembleSeriesEpisode` | `tests/test_series_assembly.py` |
| `series.review.open_editor` | series | operativa | L10 | `create_video_editor_project` | registrada_fuera_de_contexto | `openEditor` | `ui/tests/seriesReviewEpisodeReset.test.tsx` |
| `series.canon.commit_delta` | series | operativa | L6 | `commit_series_canon` | disponible | `commitSeriesCanonDelta` | `tests/test_series_library.py` |
| `series.recovery.plan_render` | series | operativa | L6 | `resume_task` | registrada_fuera_de_contexto | `resumeSeriesRenderJob` | `tests/test_series_jobs.py` |
| `series.review.i18n` | series | solo_informacion | L11 | `—` | ninguna | `—` | `ui/tests/i18nFoundation.test.tsx` |
| `h3.prompt.finalization_fixture` | shared | operativa | L0 | `—` | dominio_sin_capacidad | `finalize_h3_prompt` | `tests/test_h3_prompt_finalization.py` |
| `h3.policy.e2e` | shared | condicional | H-A | `—` | dominio_sin_capacidad | `adapt_clip_plans_for_h3` | `tests/test_h3_policy_language_audio_creative.py` |
| `h3.audio.contradictions` | shared | condicional | H-B | `—` | dominio_sin_capacidad | `apply_h3_audio_policy` | `tests/test_h3_policy_language_audio_creative.py` |
| `h3.creative.extra_line` | shared | condicional | H-C | `—` | dominio_sin_capacidad | `writing_contract` | `tests/test_h3_policy_language_audio_creative.py` |
| `wizard.context.blocked` | wizard | operativa | L5 | `—` | disponible | `projectWizardContextCapabilities` | `ui/tests/wizardLabsL5L6.test.mjs` |
| `wizard.schema.sent` | wizard | operativa | L5 | `—` | disponible | `wizardLlmRequestSchema` | `ui/tests/wizardLabsL5L6.test.mjs` |

### Operation details

#### `story.nav.open_section` — Open a Story Lab section

- Control: StoryLabNavigation / storyLabTabs
- UI handler: `StoryLabNavigation.setTab`
- Domain: `open_story_section` in `ui/src/features/agent/navigationQueueCapabilities.ts`
- Adapter: `storyLab.open`
- API: `—`
- Wizard capability / schema: `open_story_section` / `capabilityRegistry.open_story_section.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Active Story project; tab must be visible for the project type or have a compact equivalent
- Persistence: none (canonical tab state)
- Presentation: story_lab + section alias
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Compact Story types map world/characters/structure onto overview. Full stories group world/characters/relationships/assets onto Universe and trailer onto Generate. Series keeps setup/canon/episode/shots/review IDs labeled Preparation · Bible · Episode · Shots · Results. Invisible sections fail instead of reporting a false open.

#### `story.library.create` — Create a Story Lab project

- Control: StoryLabLibraryChrome new project
- UI handler: `StoryLabLibraryChrome`
- Domain: `createFilledStory` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.create`
- API: `POST /api/v1/stories (saveStoryLibrary)`
- Wizard capability / schema: `create_story` / `capabilityRegistry.create_story.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Workspace selected
- Persistence: story library document
- Presentation: story_lab overview
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.library.update` — Edit Story fields (title, languages, premise, style, providers)

- Control: StoryOverviewTab fields
- UI handler: `StoryOverviewTab / saveStoryProjectMutation`
- Domain: `updateFilledStory` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.update`
- API: `PUT story library`
- Wizard capability / schema: `update_story` / `capabilityRegistry.update_story.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Existing story id or unique title
- Persistence: story project document
- Presentation: story_lab overview
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.library.duplicate_delete` — Duplicate or delete a Story project

- Control: StoryLabLibraryChrome duplicate/delete
- UI handler: `StoryLabLibraryChrome`
- Domain: `saveStoryLibrary` in `ui/src/api/stories.ts`
- Adapter: `—`
- API: `PUT story library`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Existing project
- Persistence: story library document
- Presentation: library chrome
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: UI-only maintenance; no Wizard capability. Keep, do not remove for seeming unused.

#### `story.workflow.mode` — Choose whether to review proposals before applying them

- Control: StoryLabLibraryChrome workflow mode
- UI handler: `StoryLabPanel workflowMode`
- Domain: `updateFilledStory` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.update`
- API: `story library`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Persisted on existing projects
- Persistence: project.workflowMode
- Presentation: chrome
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Guided is “Review proposals before applying them”, not a universal authorization and not Director Auto. New stories default to direct flow; existing documents keep workflowMode.

#### `story.prepare.section_text` — Generate a reviewable Story section proposal

- Control: Prepare text / generate section buttons
- UI handler: `generateStorySection / Compact* prepare text`
- Domain: `generateStorySectionDraft` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.generateProposal`
- API: `generateStorySection`
- Wizard capability / schema: `generate_story_section` / `capabilityRegistry.generate_story_section.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Story exists; LLM writing provider configured
- Persistence: proposal draft, not applied until apply_story_proposal
- Presentation: story_lab section
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.prepare.apply_proposal` — Apply a reviewed Story proposal

- Control: Apply proposal
- UI handler: `applyStoredStoryProposal`
- Domain: `applyStoredStoryProposal` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.applyProposal`
- API: `saveStoryLibrary`
- Wizard capability / schema: `apply_story_proposal` / `capabilityRegistry.apply_story_proposal.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Existing proposal for the exact story
- Persistence: story sections; does not generate media
- Presentation: story_lab section
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.section.approve` — Mark a Story section reviewed

- Control: Approve section
- UI handler: `approveStorySection`
- Domain: `approveStorySection` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.approveSection`
- API: `saveStoryLibrary`
- Wizard capability / schema: `approve_story_section` / `capabilityRegistry.approve_story_section.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Section content present
- Persistence: section approval timestamp/version
- Presentation: story_lab section
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Editorial checkpoint, not generation authorization.

#### `story.assets.import_analyze` — Import and analyze reference images

- Control: StoryAssetsImporter / Compact import images
- UI handler: `analyzeStoryAssets`
- Domain: `analyzeStoryAssets` in `ui/src/api/stories.ts`
- Adapter: `—`
- API: `analyzeStoryAssets`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Image files; image provider
- Persistence: asset drafts until applied
- Presentation: assets tab
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: No dedicated Wizard capability; generate_story_visuals covers generated refs, not this importer.

#### `story.visuals.generate` — Generate Story visual references

- Control: Generate identity / variation / location image
- UI handler: `generateStoryVisuals / CharacterEditor`
- Domain: `generateStoryVisuals` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.generateVisuals`
- API: `story visual generation jobs`
- Wizard capability / schema: `generate_story_visuals` / `capabilityRegistry.generate_story_visuals.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Named subject; image provider
- Persistence: visual jobs + assets
- Presentation: assets / characters
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.visuals.approve` — Approve a visual as production reference

- Control: Approve identity / primary image
- UI handler: `approveStoryVisuals`
- Domain: `approveStoryVisuals` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.approveVisuals`
- API: `saveStoryLibrary`
- Wizard capability / schema: `approve_story_visuals` / `capabilityRegistry.approve_story_visuals.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Existing visual asset
- Persistence: approved reference flags
- Presentation: assets / characters
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.world.edit` — Edit world / locations / visual language

- Control: StoryWorldTab / LocationEditor / CompactWorldArticle
- UI handler: `StoryWorldTab`
- Domain: `updateFilledStory` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.update`
- API: `saveStoryLibrary`
- Wizard capability / schema: `update_story` / `capabilityRegistry.update_story.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Story exists
- Persistence: world + locations
- Presentation: world / compact mesa
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.characters.edit` — Edit characters / compact subjects

- Control: StoryCharactersTab / CharacterEditor / CompactSubjectEditor
- UI handler: `StoryCharactersTab`
- Domain: `updateFilledStory` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.update`
- API: `saveStoryLibrary`
- Wizard capability / schema: `update_story` / `capabilityRegistry.update_story.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Story exists
- Persistence: characters[]
- Presentation: characters / compact mesa
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.relationships.edit` — Edit character relationships

- Control: StoryRelationshipsTab
- UI handler: `StoryRelationshipsTab`
- Domain: `updateFilledStory` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.update`
- API: `saveStoryLibrary`
- Wizard capability / schema: `update_story` / `capabilityRegistry.update_story.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: At least two characters for usefulness
- Persistence: relationships[]
- Presentation: relationships tab
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.structure.edit` — Edit beats / compact sequence

- Control: BeatEditor / CompactBeatEditor / StoryStructureTab
- UI handler: `StoryStructureTab`
- Domain: `updateFilledStory` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.update`
- API: `saveStoryLibrary`
- Wizard capability / schema: `update_story` / `capabilityRegistry.update_story.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Story exists
- Persistence: structure beats
- Presentation: structure / compact sequence
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.music.configure` — Configure a Story song draft

- Control: StoryMusicTab / ManualSongPanel / MusicCueCard
- UI handler: `configureStorySong`
- Domain: `configureStorySong` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.configureSong`
- API: `story music form persistence`
- Wizard capability / schema: `configure_story_song` / `capabilityRegistry.configure_story_song.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Story of a type that has music
- Persistence: music cue draft
- Presentation: music tab
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.music.generate` — Generate a Story song

- Control: Generate song / generate all cues
- UI handler: `generateStorySong`
- Domain: `generateStorySong` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.generateSong`
- API: `generateStoryMusicCandidates / startStoryMusicCandidatesJob`
- Wizard capability / schema: `generate_story_song` / `capabilityRegistry.generate_story_song.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Configured cue; music model
- Persistence: music job + candidates
- Presentation: music tab / activity
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: ACE, MiniMax local and MiniMax API use distinct ready copy. Prompt limits come from musicGenerationSpec.

#### `story.music.import` — Import MP3 / attach alternative song

- Control: Import audio / alternative song
- UI handler: `ManualSongPanel / attach_videoclip_alternative_song`
- Domain: `attachAlternativeSong` in `ui/src/features/agent/applicationAdapters.ts`
- Adapter: `videoclips.attachAlternativeSong`
- API: `audio output attach`
- Wizard capability / schema: `attach_videoclip_alternative_song` / `capabilityRegistry.attach_videoclip_alternative_song.inputSchema`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Existing audio output
- Persistence: cue selected song id
- Presentation: music / videoclip
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.trailer.recipe` — Edit trailer recipe and illustrative six-phase guide

- Control: StoryTrailerTab / StoryTrailerTimeline / StoryTrailerNarrativeForm
- UI handler: `StoryTrailerTab`
- Domain: `updateFilledStory` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.update`
- API: `saveStoryLibrary`
- Wizard capability / schema: `update_story` / `capabilityRegistry.update_story.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Story exists
- Persistence: project.productionRecipe / creativeBrief.durationSeconds
- Presentation: Generate (full story) or trailer tab (trailer projects)
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Six-phase guide is calculated orientation, not planned shots.

#### `story.productions.comic` — Stage a Story comic in Comic Director

- Control: StoryComicProductionCard
- UI handler: `stageStoryComic`
- Domain: `stageStoryComic` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.stageComic`
- API: `comic handoff`
- Wizard capability / schema: `stage_story_comic` / `capabilityRegistry.stage_story_comic.inputSchema`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Story with enough text; confirm=true for Wizard
- Persistence: comic project + provenance
- Presentation: comics
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Registered and implemented, but omitted from wizardContext story_lab available list.

#### `story.productions.video` — Stage a Story film or trailer production

- Control: StoryFilmProductionCard / StoryTrailerClipProduction
- UI handler: `stageStoryVideo`
- Domain: `stageStoryVideo` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.stageVideo`
- API: `Director production staging`
- Wizard capability / schema: `stage_story_video` / `capabilityRegistry.stage_story_video.inputSchema`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Recipe valid for T2V vs references vs start frames
- Persistence: Director production (prepared, not generated)
- Presentation: director
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: `t2v_double_mode_and_image_requirements`
- Notes: T2V highlights two visual modes; collectProductionIssues(true) can demand images for film even in T2V. Not listed in wizardContext story_lab.

#### `story.productions.music_video` — Stage a Story music video

- Control: StoryMusicProductionLaunch / StoryProductionsMusicPanel
- UI handler: `stageStoryMusicVideo`
- Domain: `stageStoryMusicVideo` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.stageMusicVideo`
- API: `Director / music video staging`
- Wizard capability / schema: `stage_story_music_video` / `capabilityRegistry.stage_story_music_video.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Selected song; visual mode
- Persistence: music-video production
- Presentation: director / productions
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: `none`
- Notes: —

#### `story.productions.director` — Start Director production

- Control: Open Director / start production
- UI handler: `startDirectorProduction`
- Domain: `startDirectorProduction` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.startDirectorProduction`
- API: `Director pipeline start`
- Wizard capability / schema: `start_director_production` / `capabilityRegistry.start_director_production.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Staged production; technical requirements met
- Persistence: pipeline + tasks
- Presentation: director
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: `none`
- Notes: Director Auto is a distinct variable from Story workflowMode.

#### `story.productions.quick_batch` — Start a quick-video night batch

- Control: QuickVideoBatchPanel
- UI handler: `startQuickVideoBatch`
- Domain: `startQuickVideoBatch` in `ui/src/api/stories.ts`
- Adapter: `—`
- API: `startQuickVideoBatch`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: quick_video project
- Persistence: batch job
- Presentation: productions
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: UI-only; no Wizard capability yet.

#### `story.assembly.history` — Inspect productions, restore origin as copy, open destination timeline

- Control: StoryAssemblyTab / StoryProductionTimeline
- UI handler: `StoryAssemblyTab`
- Domain: `startDirectorProduction` in `ui/src/features/stories/actions.ts`
- Adapter: `storyLab.startDirectorProduction`
- API: `production history`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Existing productions
- Persistence: production records; restore creates a copy
- Presentation: assembly tab
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `story.music.legacy_drawer` — Legacy music production drawer

- Control: removed; ManualSongPanel remains the visible editor
- UI handler: `ManualSongPanel`
- Domain: `` in ``
- Adapter: `storyLab.stageMusicVideo`
- API: `—`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: none
- Persistence: cue candidates recover via storySongRecovery without the drawer
- Presentation: hidden markup removed
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Hidden drawer markup removed in L11. Create/import/cover/versions stay in ManualSongPanel; candidates are not deleted.

#### `story.prepare.cancel_recover` — Cancel or recover Story generation

- Control: Cancel / recover in chrome
- UI handler: `cancelStoryGeneration / resumeStoryGeneration`
- Domain: `resumeStoryGeneration` in `ui/src/api/stories.ts`
- Adapter: `queue.resume`
- API: `cancelStoryGeneration / resumeStoryGeneration`
- Wizard capability / schema: `resume_task` / `capabilityRegistry.resume_task.inputSchema`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Existing job id
- Persistence: server-authoritative job
- Presentation: activity / chrome
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.nav.open_section` — Open a Series Lab section

- Control: SeriesLabPanel tabs setup/canon/episode/shots/review
- UI handler: `SeriesLabPanel.setTab`
- Domain: `open_series_section` in `ui/src/features/agent/navigationQueueCapabilities.ts`
- Adapter: `seriesLab.open`
- API: `—`
- Wizard capability / schema: `open_series_section` / `capabilityRegistry.open_series_section.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Active series
- Persistence: tab state
- Presentation: series_lab + alias
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.library.create` — Create a Series project

- Control: SeriesLabPanel new series
- UI handler: `createSeriesProject`
- Domain: `create_series_project` in `app/services/series_library.py`
- Adapter: `—`
- API: `POST /api/v1/series`
- Wizard capability / schema: `create_series_episode` / `capabilityRegistry.create_series_episode.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Workspace
- Persistence: series library
- Presentation: setup
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Wizard create_series_episode with createIfMissing can create a series; UI also has a dedicated create. Do not announce series creation as impossible.

#### `series.library.import_story` — Import a Story as a Series base

- Control: Import Story
- UI handler: `importStoryAsSeries`
- Domain: `importStoryAsSeries` in `ui/src/api/series.ts`
- Adapter: `—`
- API: `POST /api/v1/series/import-story`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Existing story id
- Persistence: new series, not a live-linked edit
- Presentation: setup
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.library.duplicate_delete` — Duplicate or delete a Series

- Control: SeriesLabPanel duplicate/delete
- UI handler: `duplicateSeriesProject / deleteSeriesProject`
- Domain: `duplicateSeriesProject` in `ui/src/api/series.ts`
- Adapter: `—`
- API: `POST /api/v1/series/{id}/duplicate ; DELETE /api/v1/series/{id}`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Existing series
- Persistence: series library
- Presentation: library chrome
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.episode.create` — Create a filled Series episode

- Control: Create episode
- UI handler: `createFilledSeriesEpisode`
- Domain: `createFilledSeriesEpisode` in `ui/src/features/series/actions.ts`
- Adapter: `seriesLab.createEpisode`
- API: `POST /api/v1/series/{id}/episodes`
- Wizard capability / schema: `create_series_episode` / `capabilityRegistry.create_series_episode.inputSchema`
- In Wizard context snapshot: True
- Available (strict): False
- Preconditions: Series exists or createIfMissing
- Persistence: episode + optional approval of a brand-new canon base created in the same request
- Presentation: episode
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Shared policy: a new series or empty canon base may be approved to satisfy episode creation. Pending canon on an existing series is not auto-approved.

#### `series.episode.delete` — Delete an episode

- Control: Delete episode
- UI handler: `deleteSeriesEpisode`
- Domain: `deleteSeriesEpisode` in `ui/src/api/series.ts`
- Adapter: `—`
- API: `DELETE /api/v1/series/{id}/episodes/{episodeId}`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Existing episode
- Persistence: series document
- Presentation: library
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.setup.edit` — Edit series title, format, premise, languages, styles

- Control: SeriesSetupPanel identity fields
- UI handler: `SeriesSetupPanel / saveSeriesProject`
- Domain: `saveSeriesProject` in `ui/src/api/series.ts`
- Adapter: `seriesLab.updateEpisode`
- API: `PUT /api/v1/series/{id}`
- Wizard capability / schema: `update_series_episode` / `capabilityRegistry.update_series_episode.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Series exists
- Persistence: series.provider and bible fields
- Presentation: setup
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: update_series_episode patches an episode; series-level setup is primarily UI/saveSeriesProject. L6 may add a dedicated capability if needed.

#### `series.setup.bootstrap_known` — Bootstrap a known-universe series via LLM

- Control: Prepare known series / canon with text or images
- UI handler: `startSeriesCanonPreparation`
- Domain: `startSeriesCanonPreparation` in `ui/src/api/series.ts`
- Adapter: `—`
- API: `POST /api/v1/series/{id}/canon/prepare/start`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Series id; writing provider
- Persistence: canon plan job
- Presentation: setup / canon
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: LLM knowledge bootstrap, not web research. Distinct from create_series_episode createIfMissing.

#### `series.setup.model_options` — Choose Series video model, resolution, steps

- Control: SeriesSetupPanel model/resolution/steps
- UI handler: `SeriesSetupPanel provider fields`
- Domain: `model_for_manifest` in `app/services/series_render.py`
- Adapter: `seriesLab.renderShots`
- API: `series.provider persistence then render/start`
- Wizard capability / schema: `render_series_shots` / `capabilityRegistry.render_series_shots.inputSchema`
- In Wizard context snapshot: True
- Available (strict): False
- Preconditions: Do not expose Fused in Setup until L1 lands
- Persistence: series.provider.videoModel / videoSettings
- Presentation: setup
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: `fused_dropped_by_model_for_manifest`
- Notes: Setup offers only Legacy/Pruned/Full. Fused IDs exist in the catalog but are dropped by model_for_manifest.

#### `series.setup.global_profile` — Follow or copy the global production profile

- Control: useGlobalProfile / SeriesLabPanel sync
- UI handler: `SeriesLabPanel useEffect profile copy`
- Domain: `updateSeries` in `ui/src/features/series/SeriesLabPanel.tsx`
- Adapter: `—`
- API: `PUT /api/v1/series/{id}`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: useGlobalProfile true
- Persistence: series.provider copy of global fields
- Presentation: setup
- Prompt fixture: `n/a`
- Blocking defect: `partial_global_profile_guard`
- Notes: Equality guard omits writingBaseUrl, flowShift, audioShift, modelProfile so an isolated shift change does not sync.

#### `series.canon.edit` — Edit bible entities (world, characters, relationships, locations, props, arcs, timeline)

- Control: SeriesCanonPanel sections
- UI handler: `SeriesCanonPanel / saveSeriesProject`
- Domain: `saveSeriesProject` in `ui/src/api/series.ts`
- Adapter: `—`
- API: `PUT /api/v1/series/{id}`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Series exists; edits return canon to draft
- Persistence: canon entities + draft status
- Presentation: canon
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.canon.voices` — Edit voice bible (provider, voiceId, pitch, rhythm, emotion, dictionary)

- Control: SeriesCanonPanel Voces
- UI handler: `SeriesCanonPanel voiceProfile fields`
- Domain: `shot_generation_prompt` in `app/services/series_render.py`
- Adapter: `seriesLab.renderShots`
- API: `PUT series (metadata only for H3)`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: None for render; fields persist as metadata
- Persistence: character.voiceProfile
- Presentation: canon voces
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: `none`
- Notes: Changing these fields does not change the H3 shot prompt. Keep data; do not sell as deterministic TTS. Out of scope to add TTS.

#### `series.canon.approve` — Approve the current canon version

- Control: Approve canon
- UI handler: `approveSeriesCanon`
- Domain: `approveSeriesCanon` in `ui/src/api/series.ts`
- Adapter: `—`
- API: `approveSeriesCanon`
- Wizard capability / schema: `commit_series_canon` / `capabilityRegistry.commit_series_canon.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Canon entities present
- Persistence: approved canon version captured by new episodes
- Presentation: canon
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Approving the bible is distinct from commit_series_canon (episode delta). Wizard create episode may auto-approve.

#### `series.episode.edit` — Edit episode title, premise, outline, script dialogue

- Control: SeriesEpisodePanel
- UI handler: `updateSeriesEpisode`
- Domain: `updateSeriesEpisode` in `ui/src/features/series/actions.ts`
- Adapter: `seriesLab.updateEpisode`
- API: `PUT /api/v1/series/{id}/episodes/{episodeId}`
- Wizard capability / schema: `update_series_episode` / `capabilityRegistry.update_series_episode.inputSchema`
- In Wizard context snapshot: True
- Available (strict): False
- Preconditions: Existing episode; revision headers
- Persistence: episode.script and episode.shots independently
- Presentation: episode
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: `script_shots_dialogue_desync`
- Notes: Updating script[].dialogue[] keeps shots[].dialogueBeats; shot_generation_prompt still uses the old line.

#### `series.plan.generate` — Generate a recoverable Series plan (outline/script/shots/complete)

- Control: Generate outline / complete / redo shots
- UI handler: `generateSeriesPlan`
- Domain: `generateSeriesPlan` in `ui/src/features/series/actions.ts`
- Adapter: `seriesLab.generatePlan`
- API: `POST .../plan/start`
- Wizard capability / schema: `generate_series_plan` / `capabilityRegistry.generate_series_plan.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Episode exists; confirm=true for Wizard; complete here means planning, not render
- Persistence: plan job (recoverable)
- Presentation: episode / plan
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.plan.apply` — Apply a completed Series plan

- Control: SeriesEpisodeProposalReview apply
- UI handler: `applySeriesPlan`
- Domain: `applySeriesPlan` in `ui/src/features/series/actions.ts`
- Adapter: `seriesLab.applyPlan`
- API: `applySeriesPlanJob`
- Wizard capability / schema: `apply_series_plan` / `capabilityRegistry.apply_series_plan.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Completed plan job for the exact episode
- Persistence: episode outline/script/shots; historical takes kept
- Presentation: episode
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.comic.stage` — Adapt episode to a comic

- Control: Adapt to comic
- UI handler: `stageSeriesComic`
- Domain: `stageSeriesComic` in `ui/src/features/series/actions.ts`
- Adapter: `seriesLab.stageComic`
- API: `comic handoff`
- Wizard capability / schema: `stage_series_comic` / `capabilityRegistry.stage_series_comic.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Episode with plan
- Persistence: comic project + provenance
- Presentation: comics
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Wizard reuses `stageSeriesComic`. `actor=wizard` from the adapter; UI keeps `actor=user`. No second comic pipeline.

#### `series.shots.render` — Render selected / missing / failed / unapproved shots

- Control: SeriesShotsPanel generate buttons
- UI handler: `renderSeriesShots`
- Domain: `renderSeriesShots` in `ui/src/features/series/actions.ts`
- Adapter: `seriesLab.renderShots`
- API: `POST .../render/start`
- Wizard capability / schema: `render_series_shots` / `capabilityRegistry.render_series_shots.inputSchema`
- In Wizard context snapshot: True
- Available (strict): False
- Preconditions: Eligible shots; confirm=true for Wizard
- Persistence: render job + attempts
- Presentation: review / render
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: `fused_dropped_by_model_for_manifest`
- Notes: Queued payload uses model_for_manifest, which maps fused IDs to minimax_h3 / minimax_h3_ref2va.

#### `series.shots.edit_prompt_cast` — Edit shot prompt, cast, wardrobe, strategy, include/exclude assets

- Control: SeriesShotsPanel shot details
- UI handler: `SeriesShotsPanel / saveSeriesEpisode`
- Domain: `update_series_episode` in `app/services/series_library.py`
- Adapter: `seriesLab.updateEpisode`
- API: `PUT episode`
- Wizard capability / schema: `update_series_episode` / `capabilityRegistry.update_series_episode.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Shot exists
- Persistence: shot.prompt / manifest / cast
- Presentation: shots
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: `none`
- Notes: —

#### `series.shots.duration` — Adjust shot duration

- Control: SeriesShotDurationControl
- UI handler: `previewSeriesShotDuration / save`
- Domain: `plan_series_shot_duration` in `app/services/series_render.py`
- Adapter: `—`
- API: `previewSeriesShotDuration`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Shot exists
- Persistence: shot.durationSeconds
- Presentation: shots
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Duration sync does not repair stale dialogueBeats.

#### `series.review.approve_one` — Choose one attempt as the take for a shot

- Control: Approve / Use this take
- UI handler: `approveSeriesAttempt`
- Domain: `approve_episode_render_attempts` in `app/services/series_library.py`
- Adapter: `seriesLab.reviewAttempts`
- API: `approveSeriesAttempt`
- Wizard capability / schema: `review_series_attempts` / `capabilityRegistry.review_series_attempts.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Completed attempt with valid asset
- Persistence: shot.approvedAttemptId
- Presentation: review
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Explicit single-shot selection must keep replacing the previous take.

#### `series.review.approve_all` — Approve all latest eligible attempts

- Control: Approve all (N)
- UI handler: `approveAll / approveSeriesAttemptsBulk`
- Domain: `reviewSeriesAttempts` in `ui/src/features/series/actions.ts`
- Adapter: `seriesLab.reviewAttempts`
- API: `approveSeriesAttemptsBulk`
- Wizard capability / schema: `review_series_attempts` / `capabilityRegistry.review_series_attempts.inputSchema`
- In Wizard context snapshot: True
- Available (strict): False
- Preconditions: Completed non-rejected attempts
- Persistence: approvedAttemptId per shot
- Presentation: review
- Prompt fixture: `n/a`
- Blocking defect: `approve_all_replaces_chosen_takes`
- Notes: UI copy says existing approvals are kept, but approvable includes shots whose latest completed attempt differs from approvedAttemptId, so a chosen take is replaced. Wizard all_latest has the same policy.

#### `series.review.reject` — Reject an attempt

- Control: Reject
- UI handler: `rejectSeriesAttempt`
- Domain: `rejectSeriesAttempt` in `ui/src/api/series.ts`
- Adapter: `seriesLab.reviewAttempts`
- API: `rejectSeriesAttempt`
- Wizard capability / schema: `review_series_attempts` / `capabilityRegistry.review_series_attempts.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Existing attempt
- Persistence: attempt.reviewDecision=rejected
- Presentation: review
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.review.assemble` — Join approved clips into an episode assembly

- Control: Join clips
- UI handler: `assembleSeriesEpisode`
- Domain: `assembleSeriesEpisode` in `ui/src/features/series/actions.ts`
- Adapter: `seriesLab.assembleEpisode`
- API: `startSeriesEpisodeAssembly`
- Wizard capability / schema: `assemble_series_episode` / `capabilityRegistry.assemble_series_episode.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Every canonical shot has an approved reproducible asset
- Persistence: assembly job
- Presentation: review / assembly
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.review.open_editor` — Open approved clips in Video Editor

- Control: Open editor
- UI handler: `SeriesReviewPanel.openEditor`
- Domain: `openEditor` in `ui/src/features/series/SeriesReviewPanel.tsx`
- Adapter: `videoEditor.create`
- API: `localStorage maestro-video-editor-pending-sequence`
- Wizard capability / schema: `create_video_editor_project` / `capabilityRegistry.create_video_editor_project.inputSchema`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: All shots approved
- Persistence: editor draft via pending sequence
- Presentation: video_editor
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.canon.commit_delta` — Accept or reject episode canon delta items

- Control: Finalize / Canon view
- UI handler: `commitSeriesCanonDelta`
- Domain: `commitSeriesCanonDelta` in `ui/src/features/series/actions.ts`
- Adapter: `seriesLab.commitCanon`
- API: `commitSeriesCanon`
- Wizard capability / schema: `commit_series_canon` / `capabilityRegistry.commit_series_canon.inputSchema`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Explicit item decisions; confirm=true for Wizard
- Persistence: canon delta committed
- Presentation: review / canon
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Narrative continuity, not take selection.

#### `series.recovery.plan_render` — Recover, resume, cancel or discard plan/render/assembly jobs

- Control: Recovery banners
- UI handler: `resumeSeriesPlanJob / resumeSeriesRenderJob / fetchSeries*Recovery`
- Domain: `resumeSeriesRenderJob` in `ui/src/api/series.ts`
- Adapter: `queue.resume`
- API: `.../plan|render/jobs/{id}/resume and recovery listings`
- Wizard capability / schema: `resume_task` / `capabilityRegistry.resume_task.inputSchema`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Server-side recoverable job
- Persistence: job documents
- Presentation: review / activity
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: —

#### `series.review.i18n` — Read Series Review action labels

- Control: Generate missing / Play all / Join clips / Edit & regenerate (seriesLab.review.*)
- UI handler: `SeriesReviewPanel copy`
- Domain: `` in `ui/src/features/series/SeriesReviewPanel.tsx`
- Adapter: `—`
- API: `—`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: none
- Persistence: none
- Presentation: review labels
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Visible labels come from catalogs. Internal option ids, user dialogue and prompts stay untranslated.

#### `h3.prompt.finalization_fixture` — Freeze effective H3 prompts before UI and before queue

- Control: n/a (compiler contract)
- UI handler: `finalize_h3_prompt / format_minimax_h3_prompt`
- Domain: `finalize_h3_prompt` in `app/services/h3_prompt_finalization.py`
- Adapter: `—`
- API: `queued generation payload`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Literal dialogue already tagged
- Persistence: none (fixture only)
- Presentation: n/a
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: `none`
- Notes: Reuse #179 fixtures. Do not refresh to hide a prompt change. L4/L12 must compare against this file.

#### `h3.policy.e2e` — Propagate H3 audio policy and spoken language end to end

- Control: runtime adapt_clip_plans_for_h3 + ref2va quote path
- UI handler: `adapt_clip_plans_for_h3`
- Domain: `adapt_clip_plans_for_h3` in `app/services/director/minimax_h3_prompting.py`
- Adapter: `—`
- API: `queued H3 payload`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Bounded generation-runtime wiring only after hotspot is free
- Persistence: plan vs send must not silently mix native/legacy
- Presentation: generation details
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: none
- Notes: Bounded runtime wiring. Omitted policy stays native. Quote language lives in models/minimax_h3/spoken_language.py.

#### `h3.audio.contradictions` — Resolve generated audio-policy contradictions; keep user text

- Control: n/a
- UI handler: `apply_h3_audio_policy`
- Domain: `apply_h3_audio_policy` in `app/services/h3_prompt_policy.py`
- Adapter: `—`
- API: `queued H3 payload`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Capture concrete before/after examples first
- Persistence: details/provenance fields already available
- Presentation: generation details
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: none
- Notes: 'Qué silencio' inside a line is literal dialogue, not a mute order. Plan vs send uses existing _director_h3_* fields.

#### `h3.creative.extra_line` — Creative writing actually adds supporting dialogue

- Control: H3 writing mode Creative
- UI handler: `writing_contract / LLM proposal application`
- Domain: `writing_contract` in `app/services/h3_prompt_policy.py`
- Adapter: `—`
- API: `queued H3 payload`
- Wizard capability / schema: `—` / `—`
- In Wizard context snapshot: False
- Available (strict): False
- Preconditions: Explicit request to add a line; duration budget; Faithful negative control
- Persistence: compiled prompt, not prefabricated post-LLM lines
- Presentation: effective prompt
- Prompt fixture: `tests/fixtures/h3_prompt_fase1_expected.json`
- Blocking defect: none
- Notes: Simulated LLM transport keeps the extra line; Faithful and only-these-lines do not. Do not hand-write the evaluated sentence.

#### `wizard.context.blocked` — Advertise blocked vs available Wizard capabilities

- Control: wizardContext.capabilities
- UI handler: `contextCapabilities`
- Domain: `projectWizardContextCapabilities` in `ui/src/features/agent/wizardCapabilityAvailability.ts`
- Adapter: `—`
- API: `—`
- Wizard capability / schema: `—` / `HOCUSPOCUS_AGENT_RESPONSE_SCHEMA`
- In Wizard context snapshot: True
- Available (strict): True
- Preconditions: Active tab
- Persistence: none (snapshot)
- Presentation: Wizard system prompt context
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Availability is derived: executable, needs_data, blocked, requires_navigation. Off-tab Labs stay visible as requires_navigation.

#### `wizard.schema.sent` — Send structured action schema to the LLM

- Control: AgentAssistantPanel json_schema
- UI handler: `wizardLlmRequestSchema`
- Domain: `wizardLlmRequestSchema` in `ui/src/features/agent/agentActions.ts`
- Adapter: `capabilityRunner`
- API: `generateLlmText`
- Wizard capability / schema: `—` / `HOCUSPOCUS_AGENT_RESPONSE_SCHEMA`
- In Wizard context snapshot: False
- Available (strict): True
- Preconditions: Wizard panel mounted
- Persistence: conversation
- Presentation: assistant
- Prompt fixture: `n/a`
- Blocking defect: `none`
- Notes: Prove which schema is actually sent, not only registeredCapabilitySchemas().

## Wizard capabilities outside Story/Series Labs

These IDs are in `AGENT_ACTION_TYPES`. They are listed so L0 can prove every Wizard-promised action has an identified function. They are not Labs simplification work.

| Id | Capability | Function | Module | Adapter |
|---|---|---|---|---|
| `other.open_tab` | `open_tab` | `openTab` | `ui/src/features/agent/applicationAdapters.ts` | `openTab` |
| `other.inspect_queue` | `inspect_queue` | `inspect` | `ui/src/features/agent/navigationQueueCapabilities.ts` | `queue.inspect` |
| `other.cancel_task` | `cancel_task` | `cancel` | `ui/src/features/agent/navigationQueueCapabilities.ts` | `queue.cancel` |
| `other.resume_task` | `resume_task` | `resume` | `ui/src/features/agent/navigationQueueCapabilities.ts` | `queue.resume` |
| `other.retry_task` | `retry_task` | `retry` | `ui/src/features/agent/navigationQueueCapabilities.ts` | `queue.retry` |
| `other.select_workspace` | `select_workspace` | `select` | `ui/src/features/agent/navigationQueueCapabilities.ts` | `workspace.select` |
| `other.create_workspace` | `create_workspace` | `create` | `ui/src/features/agent/navigationQueueCapabilities.ts` | `workspace.create` |
| `other.create_workspace_collection` | `create_workspace_collection` | `createCollection` | `ui/src/features/agent/navigationQueueCapabilities.ts` | `workspace.createCollection` |
| `other.update_workspace_collection` | `update_workspace_collection` | `updateCollection` | `ui/src/features/agent/navigationQueueCapabilities.ts` | `workspace.updateCollection` |
| `other.prepare_video` | `prepare_video` | `prepareVideo` | `ui/src/features/agent/studioCapabilities.ts` | `studio.prepareVideo` |
| `other.prepare_programmatic_video` | `prepare_programmatic_video` | `prepareProgrammaticVideo` | `ui/src/features/agent/programmaticVideo.ts` | `video3d.prepareProgrammaticVideo` |
| `other.speech_analysis_engine` | other | condicional | out_of_scope | `speech_analysis_engine` | disponible | `setupSpeechAnalysis` | `ui/tests/speechAnalysisParity.test.tsx` |
| `other.prepare_image` | `prepare_image` | `prepareImage` | `ui/src/features/agent/studioCapabilities.ts` | `studio.prepareImage` |
| `other.prepare_audio` | `prepare_audio` | `prepareAudio` | `ui/src/features/agent/studioCapabilities.ts` | `studio.prepareAudio` |
| `other.download_model` | `download_model` | `downloadModel` | `ui/src/features/agent/studioCapabilities.ts` | `studio.downloadModel` |
| `other.queue_sfx_pack` | `queue_sfx_pack` | `queueSfxPack` | `ui/src/features/agent/studioCapabilities.ts` | `studio.queueSfxPack` |
| `other.prepare_3d` | `prepare_3d` | `prepare3d` | `ui/src/features/agent/studioCapabilities.ts` | `studio.prepare3d` |
| `other.start_generation` | `start_generation` | `startGeneration` | `ui/src/features/agent/studioCapabilities.ts` | `studio.startGeneration` |
| `other.attach_studio_references` | `attach_studio_references` | `attachReferences` | `ui/src/features/agent/studioCapabilities.ts` | `studio.attachReferences` |
| `other.configure_studio_loras` | `configure_studio_loras` | `configureLoras` | `ui/src/features/agent/studioCapabilities.ts` | `studio.configureLoras` |
| `other.remove_background` | `remove_background` | `removeBackground` | `ui/src/features/agent/toolCapabilities.ts` | `tools.removeBackground` |
| `other.upscale` | `upscale` | `upscale` | `ui/src/features/agent/toolCapabilities.ts` | `tools.upscale` |
| `other.open_3d_scene` | `open_3d_scene` | `open` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.open` |
| `other.save_3d_scene` | `save_3d_scene` | `run` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.run` |
| `other.export_3d_scene` | `export_3d_scene` | `run` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.run` |
| `other.apply_3d_rhythm` | `apply_3d_rhythm` | `applyRhythm` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.applyRhythm` |
| `other.create_rhythmic_3d_video` | `create_rhythmic_3d_video` | `run` | `ui/src/features/agent/rhythmic3dWorkflow.ts` | `video3d.run` |
| `other.create_3d_scene` | `create_3d_scene` | `run` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.run` |
| `other.set_3d_scene_properties` | `set_3d_scene_properties` | `control` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.control` |
| `other.add_3d_scene_layer` | `add_3d_scene_layer` | `control` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.control` |
| `other.update_3d_scene_layer` | `update_3d_scene_layer` | `control` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.control` |
| `other.remove_3d_scene_layer` | `remove_3d_scene_layer` | `control` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.control` |
| `other.attach_3d_scene_audio` | `attach_3d_scene_audio` | `control` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.control` |
| `other.analyze_3d_scene_audio` | `analyze_3d_scene_audio` | `control` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.control` |
| `other.apply_3d_choreography` | `apply_3d_choreography` | `control` | `ui/src/features/agent/applicationAdapters.ts` | `video3d.control` |
| `other.create_comic` | `create_comic` | `create` | `ui/src/features/agent/applicationAdapters.ts` | `comic.create` |
| `other.generate_comic` | `generate_comic` | `generate` | `ui/src/features/agent/applicationAdapters.ts` | `comic.generate` |
| `other.generate_comic_panel` | `generate_comic_panel` | `generatePanel` | `ui/src/features/agent/applicationAdapters.ts` | `comic.generatePanel` |
| `other.create_character_kit` | `create_character_kit` | `create` | `ui/src/features/agent/applicationAdapters.ts` | `characterKit.create` |
| `other.open_character_kit` | `open_character_kit` | `openKit` | `ui/src/features/agent/applicationAdapters.ts` | `characterKit.openKit` |
| `other.update_character_kit` | `update_character_kit` | `update` | `ui/src/features/agent/applicationAdapters.ts` | `characterKit.update` |
| `other.attach_character_kit_references` | `attach_character_kit_references` | `attachReference` | `ui/src/features/agent/applicationAdapters.ts` | `characterKit.attachReference` |
| `other.build_character_kit` | `build_character_kit` | `build` | `ui/src/features/agent/applicationAdapters.ts` | `characterKit.build` |
| `other.open_character_kit_rig` | `open_character_kit_rig` | `openRig` | `ui/src/features/agent/applicationAdapters.ts` | `characterKit.openRig` |
| `other.apply_character_kit_preset` | `apply_character_kit_preset` | `applyPreset` | `ui/src/features/agent/applicationAdapters.ts` | `characterKit.applyPreset` |
| `other.track_character_kit_job` | `track_character_kit_job` | `trackJob` | `ui/src/features/agent/applicationAdapters.ts` | `characterKit.trackJob` |
| `other.create_video_editor_project` | `create_video_editor_project` | `create` | `ui/src/features/agent/applicationAdapters.ts` | `videoEditor.create` |
| `other.open_video_editor_project` | `open_video_editor_project` | `openProject` | `ui/src/features/agent/applicationAdapters.ts` | `videoEditor.openProject` |
| `other.add_video_editor_clips` | `add_video_editor_clips` | `addClips` | `ui/src/features/agent/applicationAdapters.ts` | `videoEditor.addClips` |
| `other.order_video_editor_clips` | `order_video_editor_clips` | `orderClips` | `ui/src/features/agent/applicationAdapters.ts` | `videoEditor.orderClips` |
| `other.trim_video_editor_clip` | `trim_video_editor_clip` | `trimClip` | `ui/src/features/agent/applicationAdapters.ts` | `videoEditor.trimClip` |
| `other.add_video_editor_audio` | `add_video_editor_audio` | `addAudio` | `ui/src/features/agent/applicationAdapters.ts` | `videoEditor.addAudio` |
| `other.validate_video_editor_timeline` | `validate_video_editor_timeline` | `validateTimeline` | `ui/src/features/agent/applicationAdapters.ts` | `videoEditor.validateTimeline` |
| `other.export_video_editor` | `export_video_editor` | `exportProject` | `ui/src/features/agent/applicationAdapters.ts` | `videoEditor.exportProject` |
| `other.track_video_editor_export` | `track_video_editor_export` | `trackExport` | `ui/src/features/agent/applicationAdapters.ts` | `videoEditor.trackExport` |
| `other.attach_videoclip_alternative_song` | `attach_videoclip_alternative_song` | `attachAlternativeSong` | `ui/src/features/agent/applicationAdapters.ts` | `videoclips.attachAlternativeSong` |
| `other.mount_videoclip_alternative_song` | `mount_videoclip_alternative_song` | `mountAlternativeSong` | `ui/src/features/agent/applicationAdapters.ts` | `videoclips.mountAlternativeSong` |

## Audited control groups

Each inventory component has a classification and a phase destination. Labels inside a component inherit that group unless a specific operation overrides it.

| Component | Classification | Phase | Operations |
|---|---|---|---|
| `AudioRangeSelector.tsx` | operativa | L11 | `story.music.configure`, `story.trailer.recipe` |
| `BeatEditor.tsx` | operativa | L9 | `story.structure.edit` |
| `CharacterEditor.tsx` | operativa | L9 | `story.characters.edit`, `story.visuals.generate` |
| `CompactBeatEditor.tsx` | operativa | L9 | `story.structure.edit` |
| `CompactCastArticle.tsx` | operativa | L9 | `story.characters.edit`, `story.prepare.section_text` |
| `CompactPrepStatus.tsx` | solo_informacion | L7 | `story.section.approve` |
| `CompactSequenceArticle.tsx` | operativa | L9 | `story.structure.edit`, `story.prepare.section_text` |
| `CompactSubjectEditor.tsx` | operativa | L9 | `story.characters.edit`, `story.visuals.approve` |
| `CompactVideoWorkspace.tsx` | operativa | L9 | `story.nav.open_section` |
| `CompactWorldArticle.tsx` | operativa | L9 | `story.world.edit` |
| `LocationEditor.tsx` | operativa | L9 | `story.world.edit` |
| `ManualSongPanel.tsx` | operativa | L11 | `story.music.configure`, `story.music.import` |
| `MusicCueCard.tsx` | condicional | L11 | `story.music.configure`, `story.music.generate` |
| `QuickVideoBatchPanel.tsx` | operativa | L9 | `story.productions.quick_batch` |
| `ReferenceGallery.tsx` | operativa | L6 | `story.assets.import_analyze`, `story.visuals.approve` |
| `StoryAssemblyTab.tsx` | operativa | L9 | `story.assembly.history` |
| `StoryAssetsImporter.tsx` | operativa | L6 | `story.assets.import_analyze` |
| `StoryAssetsLibrary.tsx` | operativa | L6 | `story.visuals.approve` |
| `StoryAssetsProposalCard.tsx` | operativa | L7 | `story.prepare.apply_proposal` |
| `StoryAssetsStyleConverter.tsx` | operativa | L6 | `story.visuals.generate` |
| `StoryCharactersTab.tsx` | operativa | L9 | `story.characters.edit` |
| `StoryComicProductionCard.tsx` | condicional | L5 | `story.productions.comic` |
| `StoryFilmProductionCard.tsx` | condicional | L9 | `story.productions.video` |
| `StoryLabLibraryChrome.tsx` | operativa | L9 | `story.library.create`, `story.workflow.mode`, `story.prepare.cancel_recover` |
| `StoryLabNavigation.tsx` | solo_navegacion | L8 | `story.nav.open_section` |
| `StoryLibraryConflictNotice.tsx` | solo_informacion | L6 | `story.library.update` |
| `StoryMusicHeader.tsx` | operativa | L11 | `story.music.configure` |
| `StoryMusicProductionGuide.tsx` | solo_informacion | L11 | `story.productions.music_video` |
| `StoryMusicProductionLaunch.tsx` | operativa | L11 | `story.productions.music_video` |
| `StoryMusicProductionLegacyDrawer.tsx` | no_expuesta | L11 | `story.music.legacy_drawer` |
| `StoryMusicProductionModels.tsx` | operativa | L11 | `story.productions.music_video` |
| `StoryMusicProductionSong.tsx` | operativa | L11 | `story.productions.music_video` |
| `StoryMusicSettingsBar.tsx` | condicional | L11 | `story.music.generate` |
| `StoryMusicTab.tsx` | operativa | L11 | `story.music.configure`, `story.music.generate` |
| `StoryOverviewTab.tsx` | operativa | L9 | `story.library.update`, `story.prepare.section_text` |
| `StoryProductionIssuesBanner.tsx` | condicional | L9 | `story.productions.video` |
| `StoryProductionTimeline.tsx` | operativa | L9 | `story.assembly.history` |
| `StoryProductionsMusicPanel.tsx` | operativa | L11 | `story.productions.music_video` |
| `StoryProductionsTab.tsx` | operativa | L9 | `story.productions.video`, `story.productions.comic`, `story.productions.music_video` |
| `StoryProviderImageFields.tsx` | operativa | L9 | `story.library.update` |
| `StoryProviderPanel.tsx` | operativa | L9 | `story.library.update` |
| `StoryProviderWritingFields.tsx` | operativa | L9 | `story.library.update` |
| `StoryRelationshipsTab.tsx` | operativa | L9 | `story.relationships.edit` |
| `StoryStructureTab.tsx` | operativa | L9 | `story.structure.edit` |
| `StoryTrailerClipProduction.tsx` | condicional | L9 | `story.productions.video`, `story.trailer.recipe` |
| `StoryTrailerNarrativeForm.tsx` | operativa | L9 | `story.trailer.recipe` |
| `StoryTrailerTab.tsx` | operativa | L9 | `story.trailer.recipe` |
| `StoryTrailerTimeline.tsx` | solo_informacion | L9 | `story.trailer.recipe` |
| `StoryVideoFormatControls.tsx` | operativa | L9 | `story.productions.video` |
| `StoryWorldTab.tsx` | operativa | L9 | `story.world.edit` |
| `storyLabChrome.tsx` | solo_navegacion | L8 | `story.nav.open_section` |
| `SeriesCanonPanel.tsx` | condicional | L10 | `series.canon.edit`, `series.canon.voices`, `series.canon.approve` |
| `SeriesEpisodePanel.tsx` | condicional | L4 | `series.episode.edit`, `series.plan.generate`, `series.comic.stage` |
| `SeriesEpisodeProposalReview.tsx` | operativa | L6 | `series.plan.apply` |
| `SeriesLabPanel.tsx` | condicional | L2 | `series.setup.global_profile`, `series.library.create`, `series.nav.open_section` |
| `SeriesReviewPanel.tsx` | condicional | L3 | `series.review.approve_all`, `series.review.approve_one`, `series.review.assemble`, `series.review.i18n` |
| `SeriesSetupPanel.tsx` | condicional | L2 | `series.setup.edit`, `series.setup.model_options`, `series.setup.bootstrap_known` |
| `SeriesShotDurationControl.tsx` | operativa | L4 | `series.shots.duration` |
| `SeriesShotsPanel.tsx` | condicional | L1 | `series.shots.render`, `series.shots.edit_prompt_cast` |
| `components.tsx` | solo_informacion | L10 | `series.canon.edit` |

## Acceptance (L0)

- Every audited control group has a classification and a phase destination.
- Every Wizard-promised action (`AGENT_ACTION_TYPES`) has an identified function in this matrix.
- `stageSeriesComic` is exposed as Wizard capability `stage_series_comic` (L6).
- Effective prompts reuse `tests/fixtures/h3_prompt_fase1_expected.json`; later L4/L12/H-* PRs must not silently regenerate it.

This freeze does not execute models and does not change runtime behaviour.

## L12 verification (2026-09-06)

Executable coverage lives in `ui/tests/labsWizardL12.test.mjs`, plus the L7–L11 suites it reuses. Desktop Story Lab shells are in `ui/e2e/specs/labs-wizard-l12-shells.spec.ts` against the simulated API. Mobile layout remains in RTL (`seriesResponsive`, `storyLabResponsive`); the boot e2e helper needs the desktop Studios control.

| Mandatory case | Result in this PR |
|---|---|
| «¿Qué puedes hacer en Series Lab?» | `isLabsInventoryQuestion` strips every action. Availability lists capabilities with reasons. No mutation. |
| «¿Cómo genero un capítulo?» | How-to filter keeps only navigation. Does not enqueue render/create. |
| «Abre los personajes de este clip rápido» | `open_story_section` / `resolveStoryLabNavigation` opens overview (equivalent), never claims a hidden characters tab. |
| Create episode with pending canon | L7 policy: `shouldApproveCanonForExplicitEpisodeCreate` is false. |
| «He descubierto ChatGPT» | `syncShotsFromScript` keeps the literal and marks the speaking shot stale. |
| Generate pending shots in quick mode | Wizard parses `render_series_shots` `missing`. Fused 4-step payload is covered by `tests/test_series_render.py`. This PR did **not** run a GPU generation. |
| Choose latest pending takes | `bulkApproveSelections({ replaceFinals: false })` keeps existing finals. |
| Use take 2 for this shot | `shot_numbers: [2]` + `selected_latest` is latest of shot 2. A concrete take uses `attempt_id` on exactly one shot (`ui/tests/labsWizardQaAttemptId.test.mjs`). |
| Make a comic of this episode | `stage_series_comic` remains the existing operation. |
| Assemble without enough takes | `missingAssemblyShotOrders` lists missing shot numbers; assemble throws `Faltan`. |
| Workspace change in flight | Covered by `ui/tests/storyAsyncOwnership.test.mjs`. |
| Reload with pending question | `pending_question.id` is `question:workflow:step` and stays stable. |
| Reload with live generation | `reusableInFlightSongCandidate` reuses the pending job candidate. |
| Invalid provider action/fields | Unknown types and invalid `render_mode` parse to no actions. |

Historical gap IDs above have fixes in #183/#197/#201; they are not all open defects. Remaining validation: real mobile browser navigation and bounded audiovisual/UI-to-Wizard checks. No real audiovisual generation was repeated here.

## Lips Creator

`characters.lips_creator` exposes the workspace mouth collection commands through
`lipsCreator.command`, backed by `manageLipsCollection` in
`ui/src/features/characters/lipsActions.ts`. It lists, creates, updates, captures,
reviews and applies collections using the same HTTP/MCP command service. Edits
need exact collection IDs and revisions; applying mouths uses the character
library revision and preserves identity, voice and existing placement.

`characters.generate_lips` uses `lipsCreator.generate` and
`generateLipsCollection`. An explicit generation request creates missing mouths
sequentially; `states` addresses individual replacements. Each output is saved
as a pending candidate before the next native image job. Confirmed failed jobs
allow the sequence to continue; uncertain job status or save failure stops it.
Approval remains explicit. Coverage is in `ui/tests/lipsCreatorWizard.test.ts`
and `tests/test_lips_creator_commands.py`; the browser character-linking path is
covered by `ui/e2e/specs/lips-creator.spec.ts`.

## Video 3D shots

`video3d.templates.apply` searches the editor's shot library and applies an exact
id through `world3dTemplates.command`, registered by
`registerWorld3DTemplateCapabilities` in
`ui/src/features/agent/world3dTemplateCapabilities.ts`. The same cards serve MCP
and the production planner. A tied or unknown query does not create a scene.
Coverage is in `ui/tests/world3dTemplatesWizard.test.ts`.

## Productions

`production.works.review` lists works in one workspace, opens one production, or
links a light Story through `productionWorks.command`, registered by
`registerProductionWorkCapabilities` in
`ui/src/features/agent/productionWorkCapabilities.ts`. List and open do not
start a generator. The same intent reuses the production. `production.works.link`
attaches one existing production id to an existing project and does not match
titles. `production.review` stays the vision QA tool. Coverage is in
`ui/tests/productionWorksWizard.test.ts` and `tests/test_production_journey.py`.
