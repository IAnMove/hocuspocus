"""Source contracts for Story Lab's cinematic trailer creator."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "ui" / "src" / "features" / "stories" / "StoryLabPanel.tsx"
ADAPTATIONS = ROOT / "ui" / "src" / "features" / "stories" / "adaptations.ts"
MODEL = ROOT / "ui" / "src" / "features" / "stories" / "model.ts"
TYPES = ROOT / "ui" / "src" / "features" / "stories" / "types.ts"


def test_trailer_is_a_persisted_story_production_kind():
    types = TYPES.read_text(encoding="utf-8")
    model = MODEL.read_text(encoding="utf-8")

    assert "'comic' | 'film' | 'music_video' | 'trailer'" in types
    assert "item.kind === 'trailer' ? 'trailer'" in model


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
    panel = PANEL.read_text(encoding="utf-8")

    assert "{ id: 'trailer', label: 'Tráiler'" in panel
    assert "Creador de tráileres cinematográficos" in panel
    assert "TRAILER_ARC.map" in panel
    assert "setTrailerDuration" in panel
    assert "setTrailerFormat" in panel
    assert "setTrailerNarration" in panel
    assert "setTrailerSpoiler" in panel
    assert "setTrailerIntensity" in panel
    assert "setTrailerTagline" in panel
    assert "setTrailerTitleCards" in panel


def test_trailer_can_review_generate_reopen_and_reuse_ordered_assembly():
    panel = PANEL.read_text(encoding="utf-8")
    stage = panel.split("const stageTrailer", 1)[1].split("const writeStorySong", 1)[0]
    reopen = panel.split("const reopenProduction", 1)[1].split(
        "const restoreProductionSource", 1,
    )[0]

    assert "buildTrailerAdaptation" in panel
    assert "kind: 'trailer'" in stage
    assert "pipelineId: useStore.getState().pipelineId" in stage
    assert "stageTrailer(true)" in panel
    assert "stageTrailer(false)" in panel
    assert "production.kind === 'trailer'" in reopen
    assert "trailerOptions" in reopen
