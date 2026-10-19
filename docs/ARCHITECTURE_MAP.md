# Architecture map

Agent map of this tree. Regenerate with `python scripts/dev/architecture_map.py`. Do not edit by hand. The Story Lab audio graph is a different file: `docs/development/ARCHITECTURE_MAP.md`.

## How the system is composed

From `docs/development/ARCHITECTURE_FOUNDATION.md`, `docs/development/CODE_HEALTH.md`, `scripts/size_ceilings.json` and `app/_launch_runtime.py`.

- `app/_launch_runtime.py` is the full server and `app/core_runtime.py` is the core server. They compose imports, `api.include_router(...)` and one keyword-only `bind(...)` per moved module. Ceilings in `scripts/size_ceilings.json` (3028 and 580) only go down.
- HTTP routes live in `app/routers/*`. Static order is `tests/fixtures/route_table.json`. Served order is `tests/fixtures/route_table_runtime.json`. Refresh with `scripts/architecture_contracts.py --write`.
- Logic lives in `app/services/*`. The shared kernel is `app/services/kernel/`. A service does not import a router. WanGP stays behind `app/services/generation/` (`bind_wgp`, `get_wgp()`).
- Names a module needs from launch arrive through that one `bind(**names)`, called once from launch and stored as plain module globals. No proxies and no `sys.modules` lookups.
- `ui/src/stores/useStore.ts` (ceiling 116) only composes slices in `ui/src/stores/` and `ui/src/features/*/store`. UI tests are node:test via tsx.
- `app/wgp.py` and `app/models/**` are upstream WanGP.

Mount is `launch`, `core`, `both`, or `ui` when `useStore.ts` imports the slice. Tests lists up to three files that mention the module path. Sections that do not fit stay indexed as `path (lines mount)`.

## Routers

| Module | Doc | Lines | Mount | Tests |
| --- | --- | ---: | --- | --- |
| `app/routers/__init__.py` | FastAPI routers kept separate from the legacy launch module. | 1 | both | — |
| `app/routers/about.py` | About page data: repository, author and the exact deployed commit. | 18 | launch | tests/test_about.py |
| `app/routers/alternative_songs.py` | Alternative-song routes, mounted where the full server registered them. | 59 | launch | — |
| `app/routers/asset_library.py` | Optional asset library: list, install on request, cancel, and serve installed files by ha… | 74 | both | tests/test_asset_library.py |
| `app/routers/assets.py` | Global asset catalog HTTP surface with injected workspace boundaries. | 113 | both | tests/test_assets_router.py, tests/test_core_mcp.py |
| `app/routers/audio.py` | Audio upload, adopt, trim, mix, analysis, clip suggestions and structure plans. | 771 | launch | tests/characterization/test_jobs_and_tasks.py, tests/test_audio_analysis_jobs.py, tests/test_custom_character_voice.py |
| `app/routers/audio_shorten.py` | CPU song shorten. It never enters the generation queue. | 123 | launch | tests/test_recoverability_followups.py |
| `app/routers/blend.py` | POST /api/v1/blend. | 569 | launch | tests/characterization/test_run_generation.py, tests/characterization/test_studio_generate.py, tests/test_job_lifecycle_wiring.py |
| `app/routers/canonical_tasks.py` | HTTP boundary for the canonical Activity task registry. | 269 | both | tests/test_canonical_tasks_router.py, tests/test_task_adapter_helpers.py |
| `app/routers/character_animation_jobs.py` | HTTP for making a character's animations on the server (services/character_animation_job.… | 80 | — | tests/test_character_animation_job.py, tests/test_output_delete_workspace.py |
| `app/routers/character_kit_face.py` | HTTP boundary for Character Kit Face Rig overlay cleanup. | 116 | both | tests/test_character_animations.py, tests/test_character_kit_face_cleanup.py, tests/test_scene3d_profiles.py |
| `app/routers/character_kit_library.py` | Character Kit library HTTP shared by full launch and core runtime. | 126 | launch | tests/test_character_kit_library_router.py, tests/test_flat_rig.py, tests/test_flat_rig_realistic.py |
| `app/routers/character_tools.py` | Browser routes for the one-click character tools; MCP keeps its own envelope. | 47 | launch | tests/test_character_tools.py |
| `app/routers/checkpoints.py` | Routes mounted where the launch module registered them. | 48 | launch | — |
| `app/routers/civitai.py` | Routes mounted where the launch module registered them. | 56 | launch | — |
| `app/routers/comics.py` | Comics HTTP surface: native projects, MiniMax images, and animatic queue. | 826 | both | tests/characterization/test_jobs_and_tasks.py, tests/test_code_health_moves.py, tests/test_comic_story_reference.py |
| `app/routers/core_gallery.py` | Gallery routes of the core server: the list, the thumbnail and the file of an output. | 37 | core | — |
| `app/routers/core_labs.py` | Story, Character Kit and Series filesystem persistence for core/remote. | 154 | core | — |
| `app/routers/core_mcp.py` | Core MCP handlers on the shared wangp transport. | 115 | core | tests/test_core_mcp.py, tests/test_mcp_access.py |
| `app/routers/core_remote.py` | Remote providers, production profile and Director planning for core/remote. | 189 | core | tests/test_no_paid_music_defaults.py |
| `app/routers/director.py` | Director planner and short-film pipeline routes for the full server. | 876 | launch | tests/characterization/test_generation_worker_bind.py, tests/test_job_lifecycle_wiring.py |
| `app/routers/director_comic.py` | Director comic HTTP routes for the full server. | 1063 | launch | tests/characterization/test_comics.py, tests/test_comic_plan_resume_contract.py |
| `app/routers/director_pipeline_reads.py` | Director routes that both servers serve the same way. | 155 | launch | tests/test_core_runtime.py |
| `app/routers/director_review.py` | — | 39 | launch | tests/test_director_review.py, tests/test_director_visible_reference.py |
| `app/routers/director_v2.py` | Director v2 plan routes for the full server. | 100 | launch | — |
| `app/routers/example_assets.py` | Preserve saved /examples/ URLs without shipping media in every installation. | 66 | both | tests/test_example_assets.py |
| `app/routers/game_library.py` | HTTP API for the game-asset library (''.game-library-v1.json''). | 213 | launch | tests/test_game_commands.py, tests/test_game_export.py, tests/test_game_library_router.py |
| `app/routers/game_produce.py` | HTTP for a game asset list and its batch production. | 172 | launch | tests/test_game_commands.py, tests/test_game_produce.py, tests/test_output_delete_workspace.py |
| `app/routers/generation_jobs.py` | HTTP routes for generation job status, cancel and list. | 66 | launch | — |
| `app/routers/huggingface.py` | Routes mounted where the launch module registered them. | 32 | launch | — |
| `app/routers/image_generation_commands.py` | HTTP and MCP projections of the executable image command contract. | 204 | both | tests/test_generation_contract.py, tests/test_image_generation_commands.py, tests/test_job_leftovers.py |
| `app/routers/image_remove_background.py` | REST projection of the idempotent image cutout command. | 10 | launch | — |
| `app/routers/lan_auth.py` | LAN authentication handshake routes. | 85 | both | tests/test_import_layers.py, tests/test_lan_auth.py |
| `app/routers/lips_creator.py` | Workspace-scoped mouth collections, independent of the character cast. | 69 | — | tests/test_lips_creator.py, tests/test_lips_creator_commands.py |
| `app/routers/llm.py` | LLM HTTP surface: load/generate, song-writer, H3 windows, enhance, describe. | 876 | both | tests/test_llm_router.py, tests/test_minimax_song_writer_prompt.py, tests/test_nsfw_guidance.py |
| `app/routers/llm_director.py` | Director music and character-reference description. | 411 | launch | — |
| `app/routers/lora_guides.py` | LoRA guide routes, mounted at the three places the launch module registered them. | 51 | launch | — |
| `app/routers/loras.py` | LoRA library routes, mounted where the launch module registered them. | 96 | launch | — |
| `app/routers/mcp_access.py` | MCP connection settings for the trusted application UI, not an MCP tool. | 46 | both | tests/test_mcp_access.py |
| `app/routers/mcp_oauth.py` | HTTP for MCP OAuth (services/mcp_oauth.py): discovery, client registration, the approval … | 125 | launch | tests/test_mcp_oauth.py |
| `app/routers/model3d.py` | Model3D routes shared by the full server and the core server. | 121 | launch | — |
| `app/routers/model3d_animate.py` | Add clips to a workspace GLB that already has the standard humanoid skeleton. | 495 | launch | tests/test_humanoid_action_clips.py, tests/test_humanoid_animate.py, tests/test_model3d_animate.py |
| `app/routers/model3d_compose.py` | CPU Model3D composition with workspace publication and retry identity. | 106 | launch | tests/test_model3d_compose.py |
| `app/routers/model_catalog.py` | Model list, files, reload, options and the active-download snapshot. | 114 | launch | — |
| `app/routers/model_preferences.py` | Visibility, selections and the production profile. | 46 | launch | — |
| `app/routers/montages.py` | HTTP projection of editable montages (''<name>.montage.json''). | 89 | launch | tests/test_montage_derive.py, tests/test_montage_documents.py |
| `app/routers/music_productions.py` | Read model for musical ''*.production.json'' files. | 263 | both | tests/test_music_productions_router.py, tests/test_recoverability_last.py |
| `app/routers/outpaint.py` | POST /api/v1/outpaint. | 591 | launch | tests/characterization/test_run_generation.py, tests/characterization/test_studio_generate.py, tests/test_job_lifecycle_wiring.py |
| `app/routers/output_facts.py` | Media facts for outputs the gallery already lists. | 50 | launch | tests/test_output_facts.py |
| `app/routers/outputs_ops.py` | Gallery routes that stay between the list, the file route and the editor. | 102 | launch | — |
| `app/routers/procedural_3d_assets.py` | Unmounted GLB inspection HTTP factory. | 62 | — | tests/test_procedural_3d_assets_router.py |
| `app/routers/production_media.py` | HTTP for the production media tools, so the Wizard and the UI call the same handlers as M… | 34 | both | tests/test_production_media_router.py |
| `app/routers/production_projects.py` | HTTP for the production-to-project link and the shared work catalog. | 153 | launch | tests/test_production_project_link.py, tests/test_production_shot_actions.py, tests/test_production_shot_view.py |
| `app/routers/productions.py` | Canonical Production and Run HTTP read models over Director pipelines. | 96 | both | tests/test_productions_router.py |
| `app/routers/projects.py` | Global project registry HTTP surface over explicit workspace roots. | 70 | both | tests/test_projects_router.py |
| `app/routers/props.py` | Prop-library commands shared with MCP. | 17 | launch | — |
| `app/routers/publish_presets.py` | Publish an exported video to a platform preset. CPU FFmpeg only. | 107 | launch | tests/test_publish_presets.py |
| `app/routers/quick_video_batches.py` | Durable, sequential Quick Video batch orchestration. | 795 | launch | tests/characterization/test_jobs_and_tasks.py, tests/test_output_delete_workspace.py, tests/test_quick_video_batches.py |
| `app/routers/recast.py` | HTTP route for POST /api/v1/recast. | 25 | launch | tests/characterization/test_studio_generate.py, tests/test_recast_helpers.py |
| `app/routers/recast_preview.py` | HTTP route for POST /api/v1/recast/preview. | 25 | launch | tests/characterization/test_studio_generate.py |
| `app/routers/recipes.py` | Studio recipe cards HTTP surface. | 147 | both | tests/test_recipes_router.py |
| `app/routers/repaint.py` | HTTP routes for Repaint. | 807 | launch | tests/characterization/test_repaint.py, tests/characterization/test_run_generation.py, tests/test_job_lifecycle_wiring.py |
| `app/routers/rig.py` | Rig routes shared by the full server and the core server. | 104 | both | — |
| `app/routers/scene2d_export.py` | HTTP projection for recoverable Video 2D export (''scenes.video2d.export''). | 54 | launch | tests/test_output_delete_workspace.py |
| `app/routers/scene3d_items.py` | REST projection of item editing. | 16 | launch | — |
| `app/routers/scene3d_profiles.py` | Workspace-scoped, content-addressed face calibration. No audio or model bytes. | 110 | — | — |
| `app/routers/scene3d_speech.py` | Small router mounted by the existing character-kit boundary, without loading AI runtimes. | 64 | — | tests/test_speech_alignment_parity.py |
| `app/routers/scene_commands.py` | — | 49 | both | tests/test_document_origin.py, tests/test_scene_effect_commands.py, tests/test_scene_library.py |
| `app/routers/scene_packages.py` | HTTP surface for portable Video3D scene packages. Independent of Gradio. | 217 | core | tests/test_scene_packages.py |
| `app/routers/scenes_favorites.py` | Favorites, scene projects and scene recordings. | 152 | both | tests/characterization/test_jobs_and_tasks.py, tests/test_core_runtime.py, tests/test_document_origin.py |
| `app/routers/series_assembly.py` | Ordered Series episode assembly API. | 796 | both | tests/characterization/test_jobs_and_tasks.py, tests/test_output_delete_workspace.py, tests/test_series_assembly_contract.py |
| `app/routers/series_guide.py` | HTTP for the agent guide and compact episodes (services/series_guide.py). | 45 | launch | tests/test_series_agent_fixes.py |
| `app/routers/series_language_versions.py` | HTTP for an episode's language versions: write lines by hand, translate with the LLM, rem… | 108 | launch | tests/test_document_origin.py, tests/test_recoverability_last.py, tests/test_series_language_versions.py |
| `app/routers/series_library.py` | Series Lab library and project HTTP surface shared by full launch and core runtime. | 771 | launch | tests/test_core_runtime.py, tests/test_document_origin.py, tests/test_import_layers.py |
| `app/routers/series_native_render.py` | HTTP for the server-side Series episode render (''services/series_native_render.py''). | 71 | launch | tests/test_output_delete_workspace.py, tests/test_series_native_render_router.py |
| `app/routers/series_plan.py` | Series plan HTTP routes shared by the full server and the core server. | 389 | launch | tests/test_core_runtime.py, tests/test_series_jobs.py |
| `app/routers/series_plates.py` | HTTP for 3D background plates of series locations (''services/series_plates.py''). | 45 | launch | tests/test_series_plates.py |
| `app/routers/series_produce.py` | HTTP for an episode from a script and its one-call production (services/series_script.py,… | 204 | launch | tests/test_output_delete_workspace.py, tests/test_recoverability_followups.py, tests/test_recoverability_last.py |
| `app/routers/series_render.py` | Series render HTTP routes for the full server. | 494 | launch | tests/characterization/test_series.py, tests/test_production_generation_link.py, tests/test_production_producer_link.py |
| `app/routers/series_review.py` | HTTP for an episode's staged review (''services/series_review.py''): its production mode,… | 74 | both | tests/test_series_review_router.py |
| `app/routers/series_sets.py` | REST projection of location room commands. | 17 | launch | tests/test_room_integration.py |
| `app/routers/series_shot_edit.py` | HTTP for reading and editing one Series shot by id or number (services/series_shot_edit.p… | 201 | launch | tests/test_series_look_room.py, tests/test_series_shot_edit.py |
| `app/routers/series_shot_inspector.py` | HTTP for Series Lab's shot inspector: one line's voice now, and a 3D shot's plan in the V… | 127 | launch | tests/test_output_delete_workspace.py, tests/test_series_line_voice.py, tests/test_series_shot3d_editor.py |
| `app/routers/set_catalog.py` | REST discovery of interior molds. | 11 | launch | tests/test_set_molds.py |
| `app/routers/settings.py` | Settings HTTP surface moved out of the full server. | 437 | launch | tests/test_system_memory_profiles.py |
| `app/routers/storage_tools.py` | HTTP routes for the storage duplicate finder. | 44 | launch | tests/test_router_wiring.py |
| `app/routers/story_lab.py` | Story Lab HTTP routes for the full server. | 385 | launch | tests/characterization/test_stories.py, tests/test_comic_plan_resume_contract.py, tests/test_story_lab_trailer_ui.py |
| `app/routers/story_library.py` | Story Lab library HTTP shared by full launch and core runtime. | 105 | launch | — |
| `app/routers/story_music.py` | Story MiniMax Music job HTTP surface extracted from the launch runtime. | 414 | launch | tests/test_minimax_music_jobs.py |
| `app/routers/studio_edit_requests.py` | HTTP routes for retake, frame extraction, edit-anything, and inpaint. | 161 | launch | — |
| `app/routers/studio_generate.py` | HTTP route for POST /api/v1/generate. | 63 | launch | — |
| `app/routers/studio_segmentation.py` | HTTP routes for SAM status and segment preview. | 38 | launch | — |
| `app/routers/style_library.py` | HTTP surface for the persistent style library. | 110 | both | tests/test_style_library.py |
| `app/routers/system.py` | System HTTP surface moved out of the full server. | 332 | launch | — |
| `app/routers/system_capabilities.py` | HTTP surface for the platform capability authority. | 28 | both | tests/test_import_layers.py, tests/test_platform_capabilities.py |
| `app/routers/templates.py` | HTTP projection of the template library (''/api/v1/templates''). | 112 | launch | tests/test_template_library.py |
| `app/routers/tools.py` | HTTP boundary for standalone image tools. | 859 | launch | tests/characterization/test_run_generation.py, tests/test_execution_mode.py, tests/test_job_lifecycle_wiring.py |
| `app/routers/uploads.py` | Uploads: POST /api/v1/upload and GET /api/v1/uploads/{filename}, one implementation for b… | 153 | both | tests/test_core_runtime.py, tests/test_import_layers.py, tests/test_uploads_router.py |
| `app/routers/user_diagnostics.py` | HTTP boundary for user-facing install and generation diagnostics. | 62 | core | tests/test_user_diagnostics.py |
| `app/routers/video2d_catalog.py` | HTTP read of the aggregated Video 2D catalog. No GPU, save or export. | 67 | launch | tests/test_video2d_catalog_query.py, tests/test_video2d_template_cards.py, tests/test_video2d_template_commands_router.py |
| `app/routers/video2d_edit.py` | HTTP projection for Video 2D scene edits (''scenes.video2d.edit''). | 36 | launch | tests/test_video2d_edit.py |
| `app/routers/video_editor.py` | Video Editor HTTP surface, mounted by the launch runtime. | 1078 | both | tests/characterization/test_jobs_and_tasks.py, tests/characterization/test_workspaces.py, tests/test_execution_mode.py |
| `app/routers/wangp_mcp.py` | Opt-in MCP access to the existing Hocuspocus generation endpoints. | 523 | launch | tests/test_agent_activity.py, tests/test_core_mcp.py, tests/test_generation_contract.py |
| `app/routers/wizard_activity.py` | Activity rows for what Ask to the Wizard changed without starting a job. | 43 | both | tests/test_recoverability_followups.py |
| `app/routers/wizard_persistence.py` | Wizard conversation and workflow files, shared by both servers. | 129 | both | — |
| `app/routers/wizard_workflow_executor.py` | HTTP and MCP projections for the server-owned image → upscale workflow. | 101 | both | tests/test_integration_audit_regressions.py, tests/test_wizard_workflow_executor.py |
| `app/routers/workspace_busy_probes.py` | Which running work each server lets stop a workspace delete. | 76 | — | tests/test_output_delete_workspace.py |
| `app/routers/workspace_collections.py` | HTTP API for explicit Workspace collections (not output directories). | 86 | both | tests/test_workspace_collections_router.py, tests/test_workspace_command_failures.py, tests/test_workspace_commands.py |
| `app/routers/workspace_outputs.py` | Workspaces, the gallery list, file serving and storage usage. | 217 | both | tests/test_output_delete_workspace.py, tests/test_router_wiring.py, tests/test_wangp_mcp.py |
| `app/routers/world3d_export.py` | HTTP and MCP projections for recoverable World3D export. | 80 | both | tests/test_output_delete_workspace.py, tests/test_world3d_export.py |
| `app/routers/world3d_templates.py` | HTTP projection of the shared Video 3D template commands. | 96 | launch | tests/test_recoverability_followups.py, tests/test_recoverable_artifacts.py, tests/test_world3d_template_suggest.py |
| `app/routers/writing_guide.py` | Shared full/core writing coach; proposals use the existing scoped LLM routing. | 79 | both | tests/test_writing_guide.py |

## services/kernel

| Module | Doc | Lines | Mount | Tests |
| --- | --- | ---: | --- | --- |
| `app/services/kernel/__init__.py` | The shared services of one server: config, workspaces, paths, jobs, tasks and the runtime… | 1 | launch | tests/test_architecture_contracts.py, tests/test_architecture_graph.py, tests/test_h3_preplan_job_contract.py |
| `app/services/kernel/config.py` | The live server configuration and its atomic save. | 63 | — | tests/test_h3_preplan_job_contract.py, tests/test_import_layers.py, tests/test_kernel_services.py |
| `app/services/kernel/context.py` | The runtime context: the kernel services of one server, built once. | 68 | launch | tests/test_kernel_services.py |
| `app/services/kernel/jobs.py` | The generation job registry, the single-GPU FIFO slot and the durable queue. | 443 | — | tests/test_activity_generation_details.py, tests/test_h3_preplan_job_contract.py, tests/test_import_layers.py |
| `app/services/kernel/paths.py` | Path containment and upload slots shared by both servers and by services. | 128 | — | tests/test_architecture_graph.py, tests/test_core_runtime.py, tests/test_custom_character_voice.py |
| `app/services/kernel/tasks.py` | Where a workspace's canonical task registry is found, and the adapter registry skeleton. | 57 | — | tests/test_kernel_services.py |
| `app/services/kernel/workspaces.py` | The active workspace and the output folder each workspace name stands for. | 94 | — | tests/test_kernel_services.py, tests/test_task_adapter_helpers.py, tests/test_wangp_frame_extraction.py |

## services/generation_worker

| Module | Doc | Lines | Mount | Tests |
| --- | --- | ---: | --- | --- |
| `app/services/generation_worker/__init__.py` | The generation worker: ''_run_generation'' split into a frame and the phases it chains th… | 14 | launch | tests/characterization/test_generation_worker_bind.py, tests/characterization/test_run_generation.py, tests/test_generation_worker_bind.py |
| `app/services/generation_worker/finalize.py` | The end of a generation run: post-processing passes and the hand-over. | 682 | — | tests/characterization/test_studio_generate.py, tests/test_frame_exact_outputs.py |
| `app/services/generation_worker/prepare.py` | The start of a generation run: the frame, the GPU slot, the preflight and the task manife… | 954 | — | tests/characterization/test_run_generation.py |
| `app/services/generation_worker/tasks.py` | The middle of a generation run: the task queue, the task loop and the collection of outpu… | 645 | — | — |

## services/generation

| Module | Doc | Lines | Mount | Tests |
| --- | --- | ---: | --- | --- |
| `app/services/generation/__init__.py` | HocusPocus generation wall around the live WanGP instance. | 17 | launch | tests/test_architecture_contracts.py, tests/test_generation_runtime.py, tests/test_import_layers.py |
| `app/services/generation/bootstrap.py` | Explicit bootstrap for the documented standalone WanGP Python API. | 76 | — | tests/test_architecture_contracts.py, tests/test_generation_runtime.py |
| `app/services/generation/runtime.py` | Bound WanGP runtime. Launch imports wgp once and calls bind_wgp(wgp). | 64 | — | — |

## services/engine

| Module | Doc | Lines | Mount | Tests |
| --- | --- | ---: | --- | --- |
| `app/services/engine/__init__.py` | Engine ports the full server and the core server share. | 5 | — | — |
| `app/services/engine/core_model3d.py` | Core server's Model3D engine. | 48 | — | — |
| `app/services/engine/model_files.py` | Which files a model pre-download fetches, without importing WanGP. | 151 | — | tests/test_voxcpm2_tts.py |

## services/director

`app/services/director/__init__.py` (6 —), `app/services/director/comic_identity.py` (104 —), `app/services/director/guide_loader.py` (29 —), `app/services/director/h3_dialogue.py` (2064 —)
`app/services/director/h3_story_contracts.py` (153 —), `app/services/director/image_prompt_rules.py` (210 —), `app/services/director/minimax_h3_prompting.py` (395 —), `app/services/director/music_video_coverage.py` (134 —)
`app/services/director/nsfw_guidance.py` (142 —), `app/services/director/orchestrator.py` (523 —), `app/services/director/pipeline_locks.py` (255 —), `app/services/director/pipeline_observer.py` (93 —)
`app/services/director/pipeline_reconcile.py` (118 —), `app/services/director/pipeline_repair_plan.py` (171 —), `app/services/director/planners/__init__.py` (6 —), `app/services/director/planners/base.py` (431 —)
`app/services/director/planners/comic_movie.py` (1607 —), `app/services/director/planners/music_video.py` (1636 —), `app/services/director/planners/podcast.py` (322 —), `app/services/director/planners/short_film.py` (6696 —)
`app/services/director/planners/viral_video.py` (221 —), `app/services/director/policies.py` (1078 —), `app/services/director/prompt_cleanup.py` (76 —), `app/services/director/prompt_polish.py` (2469 —)
`app/services/director/renderers/__init__.py` (7 —), `app/services/director/renderers/base.py` (144 —), `app/services/director/renderers/image_gen.py` (117 —), `app/services/director/renderers/ltx_a2v.py` (68 —)
`app/services/director/renderers/ltx_extend.py` (75 —), `app/services/director/renderers/ltx_i2v.py` (104 —), `app/services/director/renderers/ltx_retake.py` (78 —), `app/services/director/renderers/ltx_t2v.py` (73 —)
`app/services/director/schema.py` (493 —), `app/services/director/spoken_language.py` (119 —), `app/services/director/typed_prompts.py` (85 —), `app/services/director/validators/__init__.py` (3 —)
`app/services/director/validators/compressor.py` (163 —), `app/services/director/validators/prompt_validator.py` (230 —), `app/services/director/validators/shot_validator.py` (117 —), `app/services/director/visible_defaults.py` (98 —)

## services/game_generators

`app/services/game_generators/__init__.py` (26 —), `app/services/game_generators/animation.py` (760 —), `app/services/game_generators/audio.py` (563 —), `app/services/game_generators/background.py` (176 —)
`app/services/game_generators/base.py` (128 —), `app/services/game_generators/still.py` (185 —), `app/services/game_generators/three_d.py` (335 —), `app/services/game_generators/tiles.py` (253 —)
`app/services/game_generators/vfx.py` (154 —)

## services/humanoid_rig

`app/services/humanoid_rig/__init__.py` (9 —), `app/services/humanoid_rig/animate.py` (96 —), `app/services/humanoid_rig/body_parts.py` (394 —), `app/services/humanoid_rig/body_roles.py` (106 —), `app/services/humanoid_rig/bvh.py` (135 —)
`app/services/humanoid_rig/clip_inventory.py` (140 —), `app/services/humanoid_rig/clip_recipes.py` (600 —), `app/services/humanoid_rig/clips.py` (119 —), `app/services/humanoid_rig/comfort.py` (123 —)
`app/services/humanoid_rig/compatibility.py` (369 —), `app/services/humanoid_rig/contacts.py` (72 —), `app/services/humanoid_rig/covering.py` (164 —), `app/services/humanoid_rig/descriptor.py` (446 —)
`app/services/humanoid_rig/drape.py` (100 —), `app/services/humanoid_rig/errors.py` (24 —), `app/services/humanoid_rig/gltf_accessors.py` (342 —), `app/services/humanoid_rig/gltf_buffers.py` (89 —)
`app/services/humanoid_rig/gltf_export.py` (331 —), `app/services/humanoid_rig/gltf_world.py` (107 —), `app/services/humanoid_rig/interactions.py` (246 —), `app/services/humanoid_rig/landmark_depth.py` (117 —)
`app/services/humanoid_rig/landmarks.py` (386 —), `app/services/humanoid_rig/motion.py` (385 —), `app/services/humanoid_rig/names.py` (154 —), `app/services/humanoid_rig/path_walk.py` (261 —)
`app/services/humanoid_rig/pose_math.py` (311 —), `app/services/humanoid_rig/retarget.py` (369 —), `app/services/humanoid_rig/retarget_names.py` (164 —), `app/services/humanoid_rig/rig.py` (90 —)
`app/services/humanoid_rig/robe_legs.py` (95 —), `app/services/humanoid_rig/role_map.py` (354 —), `app/services/humanoid_rig/rotation.py` (113 —), `app/services/humanoid_rig/silhouette.py` (170 —)
`app/services/humanoid_rig/skeleton.py` (161 —), `app/services/humanoid_rig/weights.py` (269 —), `app/services/humanoid_rig/worker.py` (103 —)

## services/hunyuan3d

`app/services/hunyuan3d/__init__.py` (1 —), `app/services/hunyuan3d/build_mesh_painter.py` (55 —), `app/services/hunyuan3d/external_worker.py` (91 —), `app/services/hunyuan3d/humanoid_animation.py` (180 —)
`app/services/hunyuan3d/patch_windows_sources.py` (84 —), `app/services/hunyuan3d/procedural_rig.py` (899 —), `app/services/hunyuan3d/rig_worker.py` (57 —), `app/services/hunyuan3d/weight_integrity.py` (76 —)
`app/services/hunyuan3d/worker.py` (519 —)

## services/procedural_3d

`app/services/procedural_3d/__init__.py` (41 —), `app/services/procedural_3d/compose.py` (145 —), `app/services/procedural_3d/coplanar.py` (70 —), `app/services/procedural_3d/glb_container.py` (145 —)
`app/services/procedural_3d/glb_inspector.py` (1212 —)

## services/rigging

`app/services/rigging/rig_worker_unirig.py` (147 —)

## services/sam

`app/services/sam/sam_service.py` (632 —)

## UI slices

| Module | Doc | Lines | Mount | Tests |
| --- | --- | ---: | --- | --- |
| `ui/src/features/activity/store.ts` | — | 192 | ui | — |
| `ui/src/features/comics/store.ts` | — | 322 | — | — |
| `ui/src/features/director/store/directorDashboardSlice.ts` | — | 487 | ui | — |
| `ui/src/features/director/store/directorMusicSourceSlice.ts` | — | 558 | ui | — |
| `ui/src/features/director/store/directorMusicVideoSlice.ts` | — | 1199 | ui | — |
| `ui/src/features/director/store/directorPipelineSlice.ts` | — | 702 | ui | tests/test_code_health_moves.py, tests/test_director_model_compat.py, tests/test_story_lab_trailer_ui.py |
| `ui/src/features/director/store/shortFilmSlice.ts` | — | 487 | ui | — |
| `ui/src/features/game-assets/store.ts` | — | 561 | — | — |
| `ui/src/features/series/inspector/inspectorStore.ts` | — | 66 | — | — |
| `ui/src/features/series/store.ts` | — | 490 | — | — |
| `ui/src/features/stories/store.ts` | — | 779 | — | — |
| `ui/src/features/studio/store/outputRestoreSlice.ts` | — | 836 | ui | tests/test_minimax_h3.py, tests/test_phase1_issue_fixes.py, tests/test_scail2_workflows.py |
| `ui/src/features/studio/store/presetsSlice.ts` | — | 92 | ui | — |
| `ui/src/features/studio/store/studioEditSlice.ts` | — | 691 | ui | tests/test_phase1_issue_fixes.py, tests/test_scail2_workflows.py |
| `ui/src/features/studio/store/studioFormSlice.ts` | — | 539 | ui | tests/test_scail2_workflows.py |
| `ui/src/features/studio/store/toolsSlice.ts` | — | 242 | ui | tests/test_activity_generation_details.py |
| `ui/src/stores/civitaiSlice.ts` | — | 225 | ui | tests/test_download_state.py |
| `ui/src/stores/developerModeSlice.ts` | — | 16 | ui | — |
| `ui/src/stores/directorSlice.ts` | — | 292 | ui | — |
| `ui/src/stores/gallerySlice.ts` | — | 690 | ui | — |
| `ui/src/stores/generationSlice.ts` | — | 940 | ui | tests/test_minimax_h3.py |
| `ui/src/stores/jobsSlice.ts` | — | 170 | ui | tests/test_activity_generation_details.py, tests/test_cancellable_model_downloads.py |
| `ui/src/stores/llmSlice.ts` | — | 350 | ui | tests/test_h3_window_planner.py, tests/test_minimax_h3.py |
| `ui/src/stores/lorasSlice.ts` | — | 395 | ui | tests/test_scail2_workflows.py |
| `ui/src/stores/modelOptionsSlice.ts` | — | 469 | ui | tests/test_minimax_h3.py |
| `ui/src/stores/modelsSlice.ts` | — | 409 | ui | tests/test_director_model_compat.py, tests/test_model_selection_persistence.py, tests/test_phase1_issue_fixes.py |
| `ui/src/stores/recipesSlice.ts` | — | 164 | ui | — |
| `ui/src/stores/retakeDialogSlice.ts` | — | 15 | ui | — |
| `ui/src/stores/servicesSlice.ts` | — | 257 | ui | tests/test_model_selection_persistence.py |
| `ui/src/stores/settingsSlice.ts` | — | 54 | ui | — |
| `ui/src/stores/sidebarSlice.ts` | — | 13 | ui | — |
| `ui/src/stores/studioConfigurationSlice.ts` | — | 487 | ui | tests/test_minimax_h3.py |
| `ui/src/stores/studioMusicSlice.ts` | — | 52 | ui | — |
| `ui/src/stores/systemSlice.ts` | — | 80 | ui | — |
| `ui/src/stores/themeSlice.ts` | — | 27 | ui | — |

## services

`app/services/__init__.py` (1 both), `app/services/access_log_filter.py` (83 launch), `app/services/activity_media.py` (59 —), `app/services/agent_activity.py` (493 both), `app/services/alternative_songs.py` (942 launch)
`app/services/asset_catalog.py` (310 —), `app/services/asset_library.py` (194 —), `app/services/asset_manifest.py` (725 launch), `app/services/assets_upload.py` (490 launch), `app/services/audio_analysis.py` (1538 —)
`app/services/audio_jobs.py` (222 launch), `app/services/audio_levels.py` (52 —), `app/services/audio_mix.py` (109 —), `app/services/audio_trim.py` (156 —), `app/services/auk_speech_contract.py` (21 —)
`app/services/blend_run.py` (330 launch), `app/services/canonical_task_fields.py` (197 launch), `app/services/canonical_task_helpers.py` (74 —), `app/services/canonical_task_publishers.py` (376 launch)
`app/services/canonical_task_sync.py` (252 launch), `app/services/character_animation_commands.py` (115 —), `app/services/character_animation_job.py` (355 —), `app/services/character_animations.py` (344 —)
`app/services/character_face_patch.py` (147 —), `app/services/character_kit_face_cleanup.py` (197 —), `app/services/character_kit_library.py` (505 launch), `app/services/character_sheet.py` (177 —)
`app/services/character_speech_definition.py` (226 —), `app/services/character_styles.py` (57 —), `app/services/checkpoints.py` (632 launch), `app/services/civitai.py` (580 launch), `app/services/civitai_downloads.py` (900 launch)
`app/services/clip_align.py` (354 launch), `app/services/comic_animatic.py` (302 launch), `app/services/comic_director_json.py` (146 launch), `app/services/comic_helpers.py` (397 launch), `app/services/command_input_errors.py` (28 —)
`app/services/core_canonical_tasks.py` (277 core), `app/services/core_generation_commands.py` (305 core), `app/services/core_production.py` (105 core), `app/services/core_remote_3d.py` (290 —), `app/services/core_remote_image.py` (288 core)
`app/services/core_series_assembly.py` (171 both), `app/services/core_workspace.py` (250 core), `app/services/creation_model_catalog.py` (117 —), `app/services/creation_model_execution.py` (51 —)
`app/services/creation_model_graphs.py` (94 —), `app/services/creation_model_service.py` (222 —), `app/services/debug_trace.py` (196 launch), `app/services/diorama_set.py` (180 —), `app/services/director_comic_film.py` (101 —)
`app/services/director_comic_jobs.py` (220 launch), `app/services/director_model_compat.py` (328 —), `app/services/director_pipeline.py` (14536 launch), `app/services/director_pipeline_state.py` (174 —)
`app/services/director_plan_jobs.py` (297 —), `app/services/director_review.py` (154 —), `app/services/director_v2_plan.py` (461 launch), `app/services/director_video_strategy.py` (1070 —), `app/services/document_origin.py` (191 —)
`app/services/durable_generation_queue.py` (122 —), `app/services/enhance_guides.py` (161 —), `app/services/episode_av_sync.py` (161 —), `app/services/episode_finishing.py` (608 —), `app/services/example_assets.py` (95 —)
`app/services/example_collections.py` (140 —), `app/services/execution_mode.py` (253 launch), `app/services/export_output_name.py` (145 —), `app/services/export_qa.py` (547 launch), `app/services/export_receipts.py` (116 —)
`app/services/face_enlarge.py` (136 —), `app/services/face_landmarks.py` (195 —), `app/services/flat_rig.py` (1130 —), `app/services/flat_rig_base.py` (31 —), `app/services/flat_rig_eyes.py` (525 —), `app/services/flat_rig_hints.py` (57 —)
`app/services/flat_rig_ink.py` (90 —), `app/services/flat_rig_look.py` (66 —), `app/services/flat_rig_metrics.py` (206 —), `app/services/flat_rig_preview.py` (175 —), `app/services/flat_rig_warp.py` (518 —)
`app/services/game_audio.py` (495 —), `app/services/game_commands.py` (444 launch), `app/services/game_estimate.py` (201 —), `app/services/game_export.py` (852 —), `app/services/game_frames.py` (319 —), `app/services/game_guide.py` (77 —)
`app/services/game_image_ops.py` (209 —), `app/services/game_inputs.py` (90 —), `app/services/game_jobs.py` (88 —), `app/services/game_library.py` (1007 —), `app/services/game_list.py` (475 —), `app/services/game_pixel.py` (280 —)
`app/services/game_produce.py` (636 launch), `app/services/game_prompts.py` (195 —), `app/services/game_qa.py` (367 —), `app/services/game_sfxr.py` (275 —), `app/services/game_sheet.py` (225 —), `app/services/game_tiles.py` (172 —)
`app/services/game_tools.py` (538 —), `app/services/generation_coefficients.py` (403 launch), `app/services/generation_flashvsr.py` (211 launch), `app/services/generation_h3_release.py` (125 launch)
`app/services/generation_jobs.py` (166 launch), `app/services/generation_memory.py` (681 —), `app/services/generation_option_helpers.py` (216 launch), `app/services/generation_output_name.py` (268 core)
`app/services/generation_postprocess.py` (201 launch), `app/services/generation_preparation.py` (355 launch), `app/services/generation_provenance.py` (238 —), `app/services/generation_record.py` (1116 —)
`app/services/generation_record_io.py` (304 —), `app/services/generation_recovery.py` (167 launch), `app/services/generation_sfx.py` (231 launch), `app/services/generation_validation_notices.py` (66 —), `app/services/glb_cleanup.py` (334 —)
`app/services/gpu_engine_win.py` (154 —), `app/services/gpu_machine_lock.py` (521 —), `app/services/guide_loader.py` (57 —), `app/services/guide_resolution.py` (46 —), `app/services/h3_frame_lattice.py` (63 —)
`app/services/h3_prompt_finalization.py` (14 —), `app/services/h3_prompt_policy.py` (119 —), `app/services/h3_runtime_policy.py` (217 launch), `app/services/h3_story_contract.py` (279 —), `app/services/h3_window_planner.py` (766 —)
`app/services/hardware_detect.py` (220 launch), `app/services/hardware_probe.py` (28 launch), `app/services/hf_import.py` (473 launch), `app/services/hi3d_service.py` (199 —), `app/services/host_guard.py` (95 launch)
`app/services/image_edit_workflow.py` (75 —), `app/services/image_generation_commands.py` (371 —), `app/services/image_generation_runtime.py` (127 launch), `app/services/image_generation_spec.py` (280 —)
`app/services/image_remove_background.py` (141 launch), `app/services/inpaint_service.py` (441 —), `app/services/install_speech_tools.py` (67 —), `app/services/job_leftovers.py` (550 launch), `app/services/job_lifecycle.py` (1036 launch)
`app/services/jobs_cancel.py` (202 launch), `app/services/jobs_wait.py` (242 launch), `app/services/lan_auth.py` (291 launch), `app/services/language_intent.py` (100 —), `app/services/lips_creator_commands.py` (364 launch)
`app/services/lipsync_qa.py` (210 launch), `app/services/live_stats.py` (152 core), `app/services/llama_release_assets.py` (25 —), `app/services/llm_routing.py` (138 —), `app/services/llm_service.py` (6865 —)
`app/services/local_generation.py` (187 —), `app/services/local_mcp.py` (80 launch), `app/services/lora_compat.py` (113 —), `app/services/lora_guides.py` (554 launch), `app/services/lora_library.py` (1221 launch)
`app/services/lyric_timeline.py` (334 —), `app/services/lyrics_language.py` (364 —), `app/services/managed_loras.py` (209 launch), `app/services/managed_preprocessors.py` (385 —), `app/services/mcp_access.py` (63 both)
`app/services/mcp_compact.py` (154 —), `app/services/mcp_intent.py` (94 —), `app/services/mcp_oauth.py` (259 launch), `app/services/mcp_profiles.py` (86 launch), `app/services/media_compose.py` (210 —)
`app/services/media_dimensions.py` (375 launch), `app/services/media_frame.py` (168 —), `app/services/media_kinds.py` (48 —), `app/services/media_options.py` (116 launch), `app/services/media_paths.py` (206 —)
`app/services/media_publication.py` (53 —), `app/services/media_refs.py` (31 —), `app/services/media_thumbnails.py` (194 —), `app/services/memory_trim.py` (71 —), `app/services/meshy_3d_service.py` (160 —)
`app/services/minimax_h3_duration.py` (468 —), `app/services/minimax_h3_service.py` (1098 launch), `app/services/minimax_image_service.py` (194 core), `app/services/minimax_music_models.py` (10 —)
`app/services/minimax_music_service.py` (192 —), `app/services/minors_rule.py` (59 —), `app/services/mix_concat.py` (505 —), `app/services/mix_concat_blocks.py` (175 —), `app/services/model3d_commands.py` (150 launch)
`app/services/model3d_external.py` (111 —), `app/services/model3d_input_path.py` (44 both), `app/services/model3d_rig_commands.py` (30 launch), `app/services/model3d_service.py` (1415 launch), `app/services/model_downloads.py` (473 launch)
`app/services/model_file_groups.py` (107 launch), `app/services/model_options.py` (273 launch), `app/services/model_selectors.py` (374 —), `app/services/model_visibility.py` (337 launch), `app/services/montage_commands.py` (172 launch)
`app/services/montage_derive.py` (73 —), `app/services/montage_documents.py` (402 launch), `app/services/montage_preview.py` (410 launch), `app/services/montage_shots.py` (343 launch), `app/services/music_fake_worker.py` (71 —)
`app/services/music_finalization.py` (327 —), `app/services/music_model_contract.py` (495 —), `app/services/music_production.py` (771 launch), `app/services/music_submission.py` (383 —), `app/services/native_generation_operation.py` (17 —)
`app/services/oom_detect.py` (80 —), `app/services/operation_logging.py` (133 —), `app/services/outpaint_planning.py` (657 launch), `app/services/outpaint_run.py` (511 launch), `app/services/output_listing.py` (433 both)
`app/services/output_names.py` (162 —), `app/services/output_ops.py` (627 launch), `app/services/output_origin.py` (59 —), `app/services/output_result_kind.py` (152 —), `app/services/output_siblings.py` (16 —)
`app/services/perf_recommend.py` (745 launch), `app/services/phoneme_analysis.py` (49 —), `app/services/phoneme_commands.py` (60 —), `app/services/phoneme_ctc.py` (101 —), `app/services/phoneme_runtime.py` (56 —)
`app/services/phoneme_worker.py` (107 —), `app/services/platform_capabilities.py` (260 core), `app/services/pose_facing.py` (181 —), `app/services/production_backplates.py` (64 —), `app/services/production_camera.py` (163 —)
`app/services/production_cast_portrait.py` (86 —), `app/services/production_clip_qa.py` (213 —), `app/services/production_close.py` (33 —), `app/services/production_commands.py` (224 —), `app/services/production_control.py` (73 —)
`app/services/production_diorama.py` (115 —), `app/services/production_disk.py` (112 —), `app/services/production_dry_run.py` (376 —), `app/services/production_enhance.py` (49 —), `app/services/production_estimate.py` (140 —)
`app/services/production_frame_clock.py` (18 —), `app/services/production_generation_link.py` (69 —), `app/services/production_image_defaults.py` (74 —), `app/services/production_lyric_looks.py` (106 —)
`app/services/production_media_commands.py` (36 both), `app/services/production_media_common.py` (299 —), `app/services/production_models.py` (537 —), `app/services/production_package.py` (157 —)
`app/services/production_parallax.py` (126 —), `app/services/production_perf.py` (31 —), `app/services/production_plan.py` (230 —), `app/services/production_preview.py` (566 —), `app/services/production_producer_link.py` (66 —)
`app/services/production_profile.py` (247 —), `app/services/production_profile_defaults.py` (39 —), `app/services/production_progress.py` (63 —), `app/services/production_project_link.py` (845 —)
`app/services/production_publication.py` (240 —), `app/services/production_quality.py` (43 —), `app/services/production_quality_gate.py` (518 —), `app/services/production_resolution.py` (79 —)
`app/services/production_resource_gate.py` (115 —), `app/services/production_resume.py` (185 launch), `app/services/production_review.py` (418 launch), `app/services/production_review_checks.py` (599 —)
`app/services/production_review_layers.py` (173 —), `app/services/production_rooms.py` (127 —), `app/services/production_run.py` (186 —), `app/services/production_scene2d.py` (471 —), `app/services/production_scene3d.py` (449 —)
`app/services/production_scene_ops.py` (87 —), `app/services/production_scene_retry.py` (143 —), `app/services/production_seeds.py` (36 —), `app/services/production_sheets.py` (70 —), `app/services/production_shot_actions.py` (619 —)
`app/services/production_shot_commands.py` (185 —), `app/services/production_shot_edit.py` (312 —), `app/services/production_shot_plan.py` (421 —), `app/services/production_shot_redo.py` (104 —)
`app/services/production_shot_regeneration.py` (153 —), `app/services/production_shot_request.py` (129 —), `app/services/production_shot_review.py` (266 —), `app/services/production_shot_sources.py` (99 —)
`app/services/production_shot_view.py` (562 —), `app/services/production_smoothness.py` (302 —), `app/services/production_song.py` (97 —), `app/services/production_song_switch.py` (124 —), `app/services/production_stage_clips.py` (146 —)
`app/services/production_stage_frames.py` (239 —), `app/services/production_stage_run.py` (117 —), `app/services/production_stage_scenes.py` (294 —), `app/services/production_state.py` (37 —), `app/services/production_structure.py` (156 —)
`app/services/production_style_presets.py` (49 —), `app/services/production_subject_count.py` (185 —), `app/services/production_takes.py` (92 —), `app/services/production_timing.py` (101 —)
`app/services/production_trailer_audio.py` (151 —), `app/services/production_treatment.py` (264 —), `app/services/production_turn.py` (48 —), `app/services/production_usage.py` (104 —), `app/services/production_video_model.py` (104 —)
`app/services/production_wait.py` (121 —), `app/services/production_windows.py` (103 —), `app/services/production_work_catalog.py` (277 —), `app/services/production_work_commands.py` (180 —), `app/services/project_catalog.py` (391 —)
`app/services/prop_commands.py` (200 —), `app/services/prop_library.py` (80 —), `app/services/provider_profile.py` (283 —), `app/services/publication_server.py` (41 —), `app/services/publish_presets.py` (231 —)
`app/services/qa_accent.py` (250 launch), `app/services/qa_people.py` (355 launch), `app/services/readable_names.py` (49 —), `app/services/recast_endpoint.py` (1175 launch), `app/services/recast_masks.py` (770 launch)
`app/services/recast_matte.py` (505 launch), `app/services/recast_preview.py` (355 —), `app/services/recast_reference_compose.py` (1088 launch), `app/services/recast_reference_prepare.py` (1033 launch)
`app/services/recast_shot_manifest.py` (789 launch), `app/services/recast_shot_planning.py` (665 launch), `app/services/recast_shot_run.py` (233 launch), `app/services/recipes.py` (269 —), `app/services/rembg_adapter.py` (99 —)
`app/services/repaint_planning.py` (642 launch), `app/services/repaint_run.py` (297 launch), `app/services/request_guards.py` (123 both), `app/services/request_numbers.py` (49 —), `app/services/resource_scheduler.py` (461 launch)
`app/services/rig_service.py` (1097 —), `app/services/runtime_environment.py` (86 —), `app/services/runtime_profiles.py` (409 —), `app/services/runtime_sources.py` (55 —), `app/services/safe_download.py` (426 launch)
`app/services/scail2_lora.py` (176 —), `app/services/scene2d_blank_frames.py` (38 —), `app/services/scene2d_export.py` (365 launch), `app/services/scene2d_schema.py` (416 —), `app/services/scene2d_text_boxes.py` (462 —)
`app/services/scene2d_validate.py` (686 launch), `app/services/scene3d_items.py` (218 —), `app/services/scene3d_speech.py` (129 —), `app/services/scene_asset_facts.py` (506 launch), `app/services/scene_commands.py` (314 both)
`app/services/scene_documents.py` (210 launch), `app/services/scene_export_lane.py` (43 —), `app/services/scene_export_leftovers.py` (64 launch), `app/services/scene_favorites.py` (71 launch), `app/services/scene_library.py` (64 —)
`app/services/scene_links.py` (136 —), `app/services/scene_packages.py` (1031 launch), `app/services/scene_packages_import.py` (313 —), `app/services/scene_recording.py` (335 —), `app/services/scene_save.py` (467 core)
`app/services/scene_speech_command.py` (66 —), `app/services/search_index.py` (188 —), `app/services/secure_download.py` (136 —), `app/services/series_ambience.py` (244 —), `app/services/series_assembly.py` (76 —)
`app/services/series_asset_path.py` (37 —), `app/services/series_canon_snapshot.py` (136 —), `app/services/series_commands.py` (1096 launch), `app/services/series_continuity.py` (185 —), `app/services/series_cutouts.py` (104 —)
`app/services/series_document_card.py` (322 —), `app/services/series_duration_estimate.py` (108 —), `app/services/series_entrances.py` (95 —), `app/services/series_episode.py` (69 —), `app/services/series_episode_numbers.py` (65 —)
`app/services/series_finish.py` (132 —), `app/services/series_guide.py` (163 —), `app/services/series_hearing.py` (226 —), `app/services/series_jobs.py` (113 —), `app/services/series_kit_pins.py` (248 —)
`app/services/series_language_versions.py` (334 launch), `app/services/series_layers.py` (153 —), `app/services/series_library.py` (1785 launch), `app/services/series_lifecycle.py` (100 —), `app/services/series_line_voice.py` (228 launch)
`app/services/series_look_room.py` (143 —), `app/services/series_native_render.py` (1017 launch), `app/services/series_plan_jobs.py` (623 launch), `app/services/series_planning.py` (1353 —), `app/services/series_plate_checks.py` (266 —)
`app/services/series_plates.py` (169 launch), `app/services/series_produce.py` (366 launch), `app/services/series_production.py` (159 —), `app/services/series_reference_router.py` (470 —), `app/services/series_render.py` (699 —)
`app/services/series_render_jobs.py` (592 launch), `app/services/series_review.py` (464 —), `app/services/series_review_gate.py` (169 —), `app/services/series_scene_inputs.py` (52 —), `app/services/series_score.py` (254 —)
`app/services/series_script.py` (540 —), `app/services/series_script_history.py` (145 —), `app/services/series_script_problems.py` (94 —), `app/services/series_script_warnings.py` (232 —), `app/services/series_set_items.py` (26 —)
`app/services/series_sets.py` (223 —), `app/services/series_shot3d.py` (529 —), `app/services/series_shot3d_editor.py` (166 —), `app/services/series_shot_bridge.py` (90 —), `app/services/series_shot_dialogue.py` (155 —)
`app/services/series_shot_edit.py` (370 —), `app/services/series_shot_extras.py` (231 —), `app/services/series_shot_foley.py` (132 —), `app/services/series_shot_instruction.py` (90 —), `app/services/series_shot_plan.py` (622 —)
`app/services/series_sound_cuts.py` (118 —), `app/services/series_stop_motion.py` (81 —), `app/services/series_take_inputs.py` (286 —), `app/services/series_take_sound.py` (286 —), `app/services/series_templates.py` (84 —)
`app/services/series_transitions.py` (307 —), `app/services/series_video_foley.py` (93 —), `app/services/series_video_inputs.py` (131 —), `app/services/series_video_shots.py` (974 —), `app/services/series_voice_rooms.py` (347 —)
`app/services/server_endpoint.py` (50 —), `app/services/server_entry.py` (110 both), `app/services/server_lifecycle.py` (178 —), `app/services/set_commands.py` (20 launch), `app/services/set_generation.py` (79 —)
`app/services/set_glb_size.py` (55 —), `app/services/set_molds.py` (186 —), `app/services/set_skins.py` (189 —), `app/services/settings_store.py` (118 launch), `app/services/song_analysis.py` (229 launch)
`app/services/song_shorten.py` (306 —), `app/services/speech_alignment.py` (54 —), `app/services/speech_analysis_cache.py` (241 —), `app/services/speech_analysis_request.py` (27 —), `app/services/speech_file_commands.py` (116 —)
`app/services/speech_language.py` (40 —), `app/services/speech_qa.py` (226 launch), `app/services/speech_reference_pauses.py` (276 —), `app/services/speech_text_es.py` (322 —), `app/services/storage_tools.py` (276 launch)
`app/services/storage_usage.py` (177 launch), `app/services/story_asset_import.py` (83 —), `app/services/story_lab_jobs.py` (531 launch), `app/services/story_lab_schema.py` (912 —), `app/services/story_library.py` (353 —)
`app/services/story_music_generation_record.py` (175 —), `app/services/story_music_jobs.py` (483 launch), `app/services/studio_edit_requests.py` (653 launch), `app/services/studio_generate.py` (589 launch)
`app/services/studio_image_alpha.py` (60 —), `app/services/studio_image_alpha_restore.py` (143 —), `app/services/studio_image_conditioning.py` (35 —), `app/services/studio_image_preparation.py` (77 —)
`app/services/studio_image_resources.py` (300 —), `app/services/studio_image_spec.py` (833 —), `app/services/studio_key.py` (628 both), `app/services/studio_key_clean.py` (194 —), `app/services/studio_music_commands.py` (42 —)
`app/services/studio_music_preparation.py` (400 —), `app/services/studio_music_spec.py` (512 —), `app/services/studio_segmentation.py` (138 launch), `app/services/studio_sfx_commands.py` (64 —), `app/services/studio_sfx_execution.py` (59 —)
`app/services/studio_sfx_preparation.py` (172 —), `app/services/studio_sfx_resources.py` (161 —), `app/services/studio_sfx_spec.py` (458 —), `app/services/studio_speech_commands.py` (20 —)
`app/services/studio_speech_preparation.py` (519 —), `app/services/studio_speech_resources.py` (35 —), `app/services/studio_speech_spec.py` (646 —), `app/services/studio_video_commands.py` (64 —)
`app/services/studio_video_preparation.py` (195 —), `app/services/studio_video_resources.py` (101 —), `app/services/studio_video_spec.py` (61 —), `app/services/style_library.py` (955 both), `app/services/task_command_admission.py` (171 —)
`app/services/task_controls.py` (70 —), `app/services/task_identity.py` (29 —), `app/services/task_maintenance.py` (366 —), `app/services/task_manager.py` (1100 —), `app/services/template_commands.py` (149 launch)
`app/services/template_community.py` (147 launch), `app/services/template_format.py` (463 —), `app/services/template_library.py` (480 launch), `app/services/template_search.py` (110 —), `app/services/tool_sidecars.py` (89 —)
`app/services/tools_upscale.py` (371 —), `app/services/tools_upscale_commands.py` (261 —), `app/services/tools_upscale_preparation.py` (412 —), `app/services/tools_upscale_spec.py` (357 —), `app/services/ui_distribution.py` (149 both)
`app/services/upload_stream.py` (254 core), `app/services/upload_video_metadata.py` (52 both), `app/services/user_diagnostics.py` (559 —), `app/services/video2d_catalogs.py` (648 launch), `app/services/video2d_character_ops.py` (125 launch)
`app/services/video2d_compile.py` (658 launch), `app/services/video2d_edit.py` (1215 launch), `app/services/video2d_edit_titles.py` (278 —), `app/services/video2d_preset_catalog.py` (38 —), `app/services/video2d_preview.py` (486 launch)
`app/services/video2d_template_cards.py` (375 —), `app/services/video_editor.py` (685 —), `app/services/video_editor_frames.py` (687 —), `app/services/video_editor_layers.py` (334 —), `app/services/video_editor_time_cards.py` (412 —)
`app/services/video_extra_info.py` (521 —), `app/services/video_generation_commands.py` (46 —), `app/services/video_generation_spec.py` (416 —), `app/services/video_generation_v3.py` (662 —), `app/services/video_layout.py` (119 —)
`app/services/vocal_isolation.py` (103 —), `app/services/vocal_isolation_worker.py` (79 —), `app/services/voice_pitch.py` (92 —), `app/services/voxcpm2_speech_contract.py` (22 —), `app/services/wangp_agent_adapters.py` (108 launch)
`app/services/wangp_analysis.py` (106 —), `app/services/wangp_submission.py` (258 launch), `app/services/win_safe_files.py` (653 launch), `app/services/wizard_conversations.py` (236 —), `app/services/wizard_workflow_executor.py` (787 both)
`app/services/wizard_workflow_supervisor.py` (36 —), `app/services/wizard_workflows.py` (283 —), `app/services/workspace_asset_import.py` (222 —), `app/services/workspace_busy.py` (185 —), `app/services/workspace_cleanup.py` (184 —)
`app/services/workspace_commands.py` (144 launch), `app/services/workspace_folder_commands.py` (66 —), `app/services/workspace_registry.py` (285 both), `app/services/workspace_store_lock.py` (41 —)
`app/services/world3d_export.py` (1100 both), `app/services/world3d_frame_encoder.py` (90 —), `app/services/world3d_grades.py` (42 —), `app/services/world3d_look.py` (44 —), `app/services/world3d_media_cache.py` (137 —)
`app/services/world3d_modifiers.py` (142 —), `app/services/world3d_renderer_support.py` (34 —), `app/services/world3d_scenes.py` (871 launch), `app/services/world3d_slot_fields.py` (103 —), `app/services/world3d_stage_cards.py` (149 —)
`app/services/world3d_stage_documents.py` (102 —), `app/services/world3d_talk.py` (183 —), `app/services/world3d_template_catalog.py` (624 —), `app/services/world3d_template_commands.py` (275 launch)
`app/services/world3d_template_vocabulary.py` (235 —), `app/services/world3d_thumbnails.py` (309 —), `app/services/writing_guide.py` (180 —)
