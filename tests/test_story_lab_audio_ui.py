"""Source-level contracts for Story Lab music import and cancellation UI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORY = ROOT / "ui" / "src" / "features" / "stories" / "StoryLabPanel.tsx"
ACTIVITY = ROOT / "ui" / "src" / "components" / "ActivityFooter.tsx"
STORY_TYPES = ROOT / "ui" / "src" / "features" / "stories" / "types.ts"
STORY_MODEL = ROOT / "ui" / "src" / "features" / "stories" / "model.ts"
STORY_ADAPTATIONS = ROOT / "ui" / "src" / "features" / "stories" / "adaptations.ts"
STORY_ACTIVITY = ROOT / "ui" / "src" / "features" / "stories" / "activityLifecycle.ts"
IMAGE_GENERATION = ROOT / "ui" / "src" / "lib" / "imageGeneration.ts"
STORE = ROOT / "ui" / "src" / "stores" / "useStore.ts"
API_CLIENT = ROOT / "ui" / "src" / "api" / "client.ts"


def test_lyria_prompt_does_not_require_an_optional_reference_song():
    source = STORY.read_text(encoding="utf-8")
    function = source.split(
        "const adaptMusicCueWithLlm", 1,
    )[1].split("const uploadLyriaResult", 1)[0]
    button = source.split(
        "Generate / refresh Lyria prompt", 1,
    )[0].rsplit("<button", 1)[1]

    assert "referenceSong.trim()" not in function
    assert "referenceSong.trim()" not in button
    assert "include_lyria: includeLyria" in function


def test_custom_mp3_can_be_imported_and_selected_as_story_music():
    source = STORY.read_text(encoding="utf-8")

    assert "const uploadCustomMusic" in source
    assert "custom-audio-upload" in source
    assert "Import custom MP3" in source
    assert 'accept=".mp3,audio/mpeg,audio/*"' in source
    assert "setMusicProductionCandidateId(candidate.id)" in source


def test_chained_music_and_director_workflows_expose_cancel_controls():
    story = STORY.read_text(encoding="utf-8")
    activity = ACTIVITY.read_text(encoding="utf-8")

    assert "cancelMusicQueue" in story
    assert "Cancelling active request" in story
    assert "cancelStoryMusicCandidatesJob(jobId)" in story
    assert "api.cancelCanonicalTask(taskId, workspace)" in activity
    assert "active && task.cancelable" in activity
    assert "Cancelling…" in activity


def test_story_lab_frontend_wrappers_reach_terminal_state_before_dismissal():
    source = STORY_ACTIVITY.read_text(encoding="utf-8")

    assert "let terminal = false" in source
    assert "publishDismissibleTerminal('completed', phase, message)" in source
    assert "publishDismissibleTerminal('cancelled', 'cancelled', message)" in source
    assert "publishDismissibleTerminal('completed', 'handed_off', message)" in source
    assert "options.scheduleDismiss(options.id)" in source
    assert "if (terminal) return" in source


def test_story_lab_client_task_writes_are_serial_and_delete_only_terminal_roots():
    source = STORE.read_text(encoding="utf-8")

    assert "createKeyedWriteSequencer" in source
    assert "_canonicalClientTaskWrites.enqueue(activity.id" in source
    assert "_canonicalClientTaskWrites.enqueue(activityId" in source
    assert "!CLIENT_ACTIVITY_TERMINAL_STATUSES.has(activity.status)" in source
    assert "await api.dismissCanonicalTask" in source


def test_story_lab_hands_backend_jobs_to_the_durable_registry():
    source = STORY.read_text(encoding="utf-8")

    assert "activity.handoff(`Continuing as recoverable job ${progress.jobId}`)" in source
    assert "activity.handoff(\n            `Continuing as recoverable image job ${jobId}`" in source
    assert "activity.handoff(`Continuing as recoverable MiniMax Music job ${job.jobId}`)" in source
    assert "activity?.handoff(`Continuing as recoverable MiniMax Music job ${job.jobId}`)" in source
    assert "activity.handoff(`Continuing as recoverable job ${recoveryJobId.trim()}`)" in source
    assert "activity.handoff('Continuing in Director as a recoverable music-video workflow')" in source


def test_story_lab_refresh_recovers_the_backend_job_without_opening_a_client_root():
    source = STORY.read_text(encoding="utf-8")
    refresh = source.split("const savedJobId = window.localStorage.getItem", 1)[1].split(
        "useEffect(() => {\n    if (project.projectType === 'quick_video')", 1,
    )[0]

    assert "api.getStoryGenerationStatus(savedJobId)" in refresh
    assert "setPendingDraft" in refresh
    assert "beginStoryActivity" not in refresh


def test_story_lab_status_polling_survives_transient_mobile_disconnects():
    source = API_CLIENT.read_text(encoding="utf-8")

    assert "STORY_STATUS_RETRY_DELAYS_MS" in source
    assert "getStoryGenerationStatusResilient" in source
    assert "isStoryStatusNetworkError(error)" in source
    assert "Mobile connection interrupted; retrying" in source
    assert "The job remains saved. Resume job: ${jobId}" in source
    assert "getStoryGenerationStatus(jobId, signal)" in source


def test_music_video_confirmation_names_the_frozen_video_model():
    source = STORY.read_text(encoding="utf-8")

    assert "Video model: ${selectedFilmVideoModel?.name || filmVideoModel} (${filmVideoModel})" in source
    assert "Video model selection did not settle" in source
    assert "Director did not return a pipeline ID" in source


def test_story_lab_exposes_all_real_h3_legacy_resolution_tiers():
    source = STORY.read_text(encoding="utf-8")

    assert "preset !== '768p' || videoModel === 'minimax_h3_legacy'" in source
    assert "STORY_VIDEO_SAVED_RESOLUTIONS" in source
    assert "resolveResolution(options, resolution, aspectRatio)" in source


def test_story_assets_support_reviewed_non_destructive_style_variants():
    panel = STORY.read_text(encoding="utf-8")
    types = STORY_TYPES.read_text(encoding="utf-8")
    model = STORY_MODEL.read_text(encoding="utf-8")

    assert "approval: StoryApprovalState" in types
    assert "derivedFromAssetId?: string" in types
    assert "stylePrompt?: string" in types
    assert "Convert selected images to a style" in panel
    assert "QWEN_STYLE_EDIT_MODEL = 'qwen_image_edit_20B_gguf_q4_k_m'" in panel
    assert "FLUX_STYLE_EDIT_MODEL = 'flux2_klein_9b'" in panel
    assert "Style conversion model" in panel
    assert "MiniMax Image-01 · characters only" in panel
    assert "Install selected local editor" in panel
    assert "Review and approve only the images Director should use" in panel
    assert "approval: item.approval === 'draft' ? 'draft' : 'approved'" in model


def test_story_library_can_bulk_remove_only_selected_drafts():
    panel = STORY.read_text(encoding="utf-8")
    deletion = panel.split("const deleteSelectedDraftAssets", 1)[1].split(
        "const styleUsesMiniMax", 1,
    )[0]

    assert "snapshot.assets[id]?.approval === 'draft'" in deletion
    assert "current.assets[id]?.approval === 'draft'" in deletion
    assert "current.world.referenceAssetIds.filter" in deletion
    assert "location.referenceAssetIds.filter" in deletion
    assert "character.referenceAssetIds.filter" in deletion
    assert "delete current.assets[id]" in deletion
    assert "Generated files remain in Gallery" in deletion
    assert "Delete selected Draft" in panel
    assert "visualAssetsNewestFirst" in panel
    assert "Newest images appear first" in panel


def test_story_reference_images_confirm_removal_and_open_in_a_modal():
    panel = STORY.read_text(encoding="utf-8")
    gallery = panel.split("function ReferenceGallery", 1)[1].split(
        "function SectionHeader", 1,
    )[0]

    assert "window.confirm(" in gallery
    assert "createPortal(" in gallery
    assert "Maximize2" in gallery
    assert 'role="dialog"' in gallery
    assert 'aria-modal="true"' in gallery
    assert "event.key === 'Escape'" in gallery
    assert "onClick={() => setPreviewId(null)}" in gallery


def test_story_style_converter_warns_about_photo_to_photo_noops_and_honors_requested_text():
    panel = STORY.read_text(encoding="utf-8")
    prompt_builder = panel.split("function styleConversionPrompt", 1)[1].split(
        "function storySongBrief", 1,
    )[0]

    assert "requestsVisibleText" in prompt_builder
    assert "normalizedStyle" in prompt_builder
    assert ".replace(/\\s+/g, ' ')" in prompt_builder
    assert "Render only the visible wording explicitly requested" in prompt_builder
    assert "a photorealistic remake will look almost unchanged" in panel


def test_story_style_conversion_uses_true_qwen_edit_semantics_for_scenes():
    panel = STORY.read_text(encoding="utf-8")
    generation = IMAGE_GENERATION.read_text(encoding="utf-8")

    assert "referenceMode: 'edit'" in panel
    assert "resolution: STYLE_RESOLUTION_BY_ASPECT[aspectRatio]" in panel
    assert "MiniMax Image-01 references are documented for character identity only" in panel
    assert "options.referenceMode === 'edit'" in generation
    assert "? 'KI'" in generation
    assert "referenceParams.model_mode = 0" in generation
    assert "referenceParams.denoising_strength = 1" in generation


def test_story_style_conversion_uses_flux_klein_as_a_true_four_step_image_editor():
    panel = STORY.read_text(encoding="utf-8")
    generation = IMAGE_GENERATION.read_text(encoding="utf-8")

    assert "styleUsesFlux" in panel
    assert "styleUsesFlux ? 'flux' : 'qwen'" in panel
    assert "fast 4-step edit" in panel
    assert "selected === 'flux2_klein_9b'" in generation
    assert "referenceParams.num_inference_steps = 4" in generation
    assert "referenceParams.guidance_scale = 1" in generation
    assert "referenceParams.embedded_guidance_scale = 1" in generation
    assert "referenceParams.flow_shift = 5" in generation
    assert "referenceParams.masking_strength = 0.25" in generation


def test_story_direct_reference_mode_uses_only_approved_visual_assets():
    panel = STORY.read_text(encoding="utf-8")
    types = STORY_TYPES.read_text(encoding="utf-8")
    adaptations = STORY_ADAPTATIONS.read_text(encoding="utf-8")

    assert "'direct_references'" in types
    assert "H3 Ref2VA" in panel
    assert "setDirectorShotImageGuidance(directReferences ? 'prompt_only' : 'auto')" in panel
    assert "setDirectorH3ReferenceMode(directReferences ? 'references' : 'first_frame')" in panel
    assert "approvedReferenceIds" in adaptations
    assert "project.assets[id]?.approval === 'approved'" in adaptations
    assert "maximum = 3" in adaptations
