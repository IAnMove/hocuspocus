"""Source-level contracts for Story Lab music import and cancellation UI."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORY = ROOT / "ui" / "src" / "features" / "stories" / "StoryLabPanel.tsx"
ACTIVITY = ROOT / "ui" / "src" / "components" / "ActivityFooter.tsx"
STORY_TYPES = ROOT / "ui" / "src" / "features" / "stories" / "types.ts"
STORY_MODEL = ROOT / "ui" / "src" / "features" / "stories" / "model.ts"
STORY_ADAPTATIONS = ROOT / "ui" / "src" / "features" / "stories" / "adaptations.ts"
IMAGE_GENERATION = ROOT / "ui" / "src" / "lib" / "imageGeneration.ts"


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
    assert "Cancelling after current track" in story
    assert "row.id.startsWith('pipeline:')" in activity
    assert "stopPipeline(row.id.slice('pipeline:'.length))" in activity
    assert "Cancel this complete generation workflow" in activity


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
