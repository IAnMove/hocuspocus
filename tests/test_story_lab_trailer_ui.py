"""Source contracts for Story Lab's cinematic trailer creator."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STORIES = ROOT / "ui" / "src" / "features" / "stories"
PANEL = STORIES / "StoryLabPanel.tsx"
TABS = STORIES / "storyLabTabs.ts"
TRAILER = STORIES / "StoryTrailerTab.tsx"
COMPACT = STORIES / "CompactVideoWorkspace.tsx"
VIDEO_FORMAT = STORIES / "storyLabVideoFormat.ts"
VIDEO_CONTROLS = STORIES / "StoryVideoFormatControls.tsx"
ADAPTATIONS = STORIES / "adaptations.ts"
MODEL = STORIES / "model.ts"
TYPES = STORIES / "types.ts"
STORE = ROOT / "ui" / "src" / "stores" / "useStore.ts"
DIRECTOR_CHAT = ROOT / "ui" / "src" / "components" / "Sidebar" / "DirectorChat.tsx"
CATALOG_EN = ROOT / "ui" / "src" / "i18n" / "locales" / "en" / "storyLab.json"
CATALOG_ES = ROOT / "ui" / "src" / "i18n" / "locales" / "es" / "storyLab.json"


def story_lab_trailer_ui() -> str:
    extracted = sorted(STORIES.glob("StoryTrailer*.tsx")) + sorted(STORIES.glob("Compact*.tsx"))
    return "\n".join(path.read_text(encoding="utf-8") for path in (
        PANEL, TABS, TRAILER, COMPACT, VIDEO_FORMAT, VIDEO_CONTROLS, CATALOG_EN, CATALOG_ES, *extracted,
    ))


def test_trailer_is_a_persisted_story_production_kind():
    types = TYPES.read_text(encoding="utf-8")
    model = MODEL.read_text(encoding="utf-8")

    assert "'comic' | 'film' | 'music_video' | 'trailer'" in types
    assert "item.kind === 'trailer' ? 'trailer'" in model


def test_trailer_is_a_standalone_story_project_type_without_music():
    types = TYPES.read_text(encoding="utf-8")
    model = MODEL.read_text(encoding="utf-8")
    panel = PANEL.read_text(encoding="utf-8")
    tabs = TABS.read_text(encoding="utf-8")
    catalog_en = CATALOG_EN.read_text(encoding="utf-8")
    catalog_es = CATALOG_ES.read_text(encoding="utf-8")
    backend = ROOT.joinpath("app", "_launch_runtime.py").read_text(encoding="utf-8")

    assert "'full_story' | 'music_video' | 'trailer' | 'quick_video'" in types
    assert "projectType === 'trailer' ? 60" in model
    assert "id: 'trailer'" in tabs
    assert '"label": "Cinematic trailer"' in catalog_en
    assert '"label": "Tráiler cinematográfico"' in catalog_es
    assert '"createTrailer": "Create trailer"' in catalog_en
    assert '"createTrailer": "Crear tráiler"' in catalog_es
    assert "No escribirá ni exigirá una canción" in catalog_es
    assert "musicVideoGenerationMode: 'image_guided' as const" in panel
    assert "project.projectType === 'trailer' ? 'trailer' : 'productions'" in panel
    assert 'if project_type in {"trailer", "quick_video"}' in backend
    assert '4 if project_type in {"trailer", "quick_video"}' in backend
    assert "Never require a song" in backend


def test_trailer_adapter_enforces_a_story_arc_without_revealing_the_ending():
    source = ADAPTATIONS.read_text(encoding="utf-8")
    adapter = source.split("export function buildTrailerAdaptation", 1)[1]

    assert "CREATE AN EPIC CINEMATIC STORY TRAILER" in adapter
    assert "MANDATORY TRAILER ARC" in adapter
    assert "Cold open (0–10%)" in adapter
    assert "Final hook (90–100%)" in adapter
    assert "Never show the source story ending" in adapter
    assert "return buildShortFilmAdaptation" in adapter


def test_story_lab_exposes_editable_trailer_controls_and_timed_preview():
    source = story_lab_trailer_ui()
    tabs = TABS.read_text(encoding="utf-8")
    trailer = source

    assert "id: 'trailer'" in tabs
    assert '"trailer": "Trailer"' in CATALOG_EN.read_text(encoding="utf-8")
    assert '"trailer": "Tráiler"' in CATALOG_ES.read_text(encoding="utf-8")
    assert "Creador de tráileres cinematográficos" in source
    assert "TRAILER_ARC.map" in trailer
    assert "setTrailerDuration" in trailer
    assert "setTrailerFormat" in trailer
    assert "setTrailerNarration" in trailer
    assert "setTrailerSpoiler" in trailer
    assert "setTrailerIntensity" in trailer
    assert "setTrailerTagline" in trailer
    assert "setTrailerTitleCards" in trailer


def test_compact_trailer_review_uses_full_width_rows():
    workspace = story_lab_trailer_ui()
    catalog = CATALOG_ES.read_text(encoding="utf-8")

    assert "export function CompactVideoWorkspace" in workspace
    assert '<div className="space-y-4">' in workspace
    assert '<div className="grid gap-4 2xl:grid-cols-3">' not in workspace
    assert "1 · Entorno y dirección visual" in catalog
    assert "Protagonistas y antagonistas" in catalog
    assert "Arco y momentos de tráiler" in catalog
    assert "t('compact.worldStep')" in workspace
    assert "t('compact.subjectsTrailer')" in workspace
    assert "t('compact.sequenceTrailer')" in workspace


def test_trailer_orientation_can_override_the_global_landscape_default_inline():
    source = story_lab_trailer_ui()
    panel = PANEL.read_text(encoding="utf-8")
    trailer = source
    handler = panel.split("const setStoryVideoFormat", 1)[1].split("useEffect", 1)[0]

    assert "Portrait / Shorts" in source
    assert "disabled={!storyVideoOptionsReady}" in trailer
    assert "provider: { ...project.provider, useGlobalProfile: false }" in handler
    assert "if (project.provider.useGlobalProfile) return" not in handler
    assert "Formato seleccionado" in source
    assert "aria-pressed={aspectRatio === option.value}" in source
    assert "Formato de vídeo actualizado:" in handler


def test_trailer_supports_text_only_direct_video_without_visual_inputs():
    source = story_lab_trailer_ui()
    trailer = source
    store = STORE.read_text(encoding="utf-8")
    director_chat = DIRECTOR_CHAT.read_text(encoding="utf-8")
    pipeline = ROOT.joinpath("app", "services", "director_pipeline.py").read_text(encoding="utf-8")

    assert "Vídeo directo" in source
    assert "T2V · sin imágenes" in source
    assert "musicVideoGenerationMode: 'direct_video', protagonistConsistency: false" in trailer
    assert "directVideoMasterReady" in trailer
    assert "disabled={directVideo || directReferenceVideo}" in trailer
    assert "const directVideo = state.directorMusicVideoTreatment.generation_mode === 'direct_video'" in store
    assert "pipelineType === 'music_video' || directVideo" in store
    assert "const isDirectVideo = musicVideoTreatment.generation_mode === 'direct_video'" in director_chat
    assert '"music_video", "short_film_story"' in pipeline


def test_direct_trailer_cast_approval_does_not_require_identity_images():
    panel = PANEL.read_text(encoding="utf-8")
    approval = panel.split("const approve =", 1)[1].split("const isApproved", 1)[0]

    assert "const requiresVisualIdentities = !directVideo" in approval
    assert "Character descriptions approved. Direct-video mode does not require identity images." in approval
    assert "project.projectType === 'trailer'" in panel
    assert "? trailerProductionIssues" in panel
    assert "requiresVisualIdentities={!directVideo}" in panel


def test_trailer_can_review_generate_reopen_and_reuse_ordered_assembly():
    panel = PANEL.read_text(encoding="utf-8")
    trailer = story_lab_trailer_ui()
    stage = panel.split("const stageTrailer", 1)[1].split("const writeStorySong", 1)[0]
    reopen = panel.split("const reopenProduction", 1)[1].split(
        "const restoreProductionSource", 1,
    )[0]

    assert "buildTrailerAdaptation" in panel
    assert "kind: 'trailer'" in stage
    assert "pipelineId: useStore.getState().pipelineId" in stage
    assert "stageTrailer(true)" in trailer
    assert "stageTrailer(false)" in trailer
    assert "production.kind === 'trailer'" in reopen
    assert "trailerOptions" in reopen
