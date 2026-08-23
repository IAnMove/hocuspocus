"""Source-level UI contract checks for Series Lab's lazy, recoverable workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERIES = ROOT / "ui" / "src" / "features" / "series"


def source(name: str) -> str:
    return (SERIES / name).read_text(encoding="utf-8")


def test_series_lab_is_top_level_immediately_after_story_lab():
    tabs = (ROOT / "ui" / "src" / "components" / "MainContent" / "TabFilter.tsx").read_text(encoding="utf-8")
    assert tabs.index("Story Lab") < tabs.index("Series Lab") < tabs.index("Video Editor")


def test_client_created_series_entities_use_browser_uuid():
    model = source("model.ts")
    assert "crypto.randomUUID()" in model
    assert "Math.random()" not in model


def test_setup_has_required_aura_explicit_models_and_canvas_choices():
    setup = source("SeriesSetupPanel.tsx")
    fields = source("components.tsx")
    assert "shadow-[0_0_18px" in fields
    assert "Prepare canon text" in setup
    assert "Prepare canon + up to 4 images" in setup
    assert "will not silently select or download a recommended model" in setup
    assert "minimax_h3" in setup and "minimax_h3_full" in setup
    assert "480p" in setup and "720p" in setup
    assert "Landscape" in setup and "Portrait" in setup
    assert "Fill from a known series · one click" in setup
    assert "bootstrapKnownSeries: true" in setup and "autoApply: true" in setup
    assert "not live web research" in setup
    assert "Nothing has been approved automatically" in setup


def test_shot_ui_exposes_exact_manifest_and_persistent_manual_policy():
    shots = source("SeriesShotsPanel.tsx")
    assert "Exact routed manifest" in shots
    assert "manualIncludeAssetIds" in shots
    assert "manualExcludeAssetIds" in shots
    assert "composed_start_frame" in shots and "composed_end_frame" in shots
    assert "Render selected" in shots and "Render missing" in shots and "Retry failed" in shots
    assert "Select all" in shots and "Clear selection" in shots
    assert "I understand · enable dialogue rendering" in shots
    assert "onAcknowledgeLipSync" in shots


def test_canon_facts_can_be_removed_individually():
    canon = source("SeriesCanonPanel.tsx")
    assert 'title="Current facts"' in canon
    assert "currentFacts: series.canon.currentFacts.filter(item => item.id !== fact.id)" in canon
    assert "aria-label={`Delete fact: ${fact.description}`}" in canon


def test_review_is_thumbnail_first_and_exposes_ordered_editable_attempt_history():
    review = source("SeriesReviewPanel.tsx")
    assert "getOutputThumbnailUrl" in review
    assert "open ? <video" in review
    assert 'preload="metadata"' in review
    assert "Saved generation request and result metadata" in review
    assert "Approve this attempt" in review and "Reject</button>" in review
    assert "Approve all" in review and "approveSeriesAttemptsBulk" in review
    assert "Play all" in review and "if (playingAll) advancePlayAll()" in review
    assert "orderedTimelineShots" in review and "safeTimelineAttempt" in review
    assert "Edit & regenerate" in review and "Save and regenerate in this slot" in review
    assert "Join clips" in review and "startSeriesEpisodeAssembly" in review
    assert "Montaje ordenado" in review and "Historial e intentos" in review
    assert "will replace this slot" in review and "progressAdvanced" in review
    assert "Open complete approved sequence in Video Editor" in review


def test_story_productions_have_an_in_place_ordered_clip_timeline():
    story = (ROOT / "ui" / "src" / "features" / "stories" / "StoryLabPanel.tsx").read_text(encoding="utf-8")
    timeline = (ROOT / "ui" / "src" / "features" / "stories" / "StoryProductionTimeline.tsx").read_text(encoding="utf-8")
    assert "StoryProductionTimeline" in story
    assert "{ id: 'assembly', label: 'Montaje', icon: Play }" in story
    assert "initiallyOpen={index === 0}" in story
    assert "View ordered clips" in timeline and "Play all" in timeline
    assert "Edit/regenerate clips" in timeline and "Join clips" in timeline
    assert "fetchSavedPipeline" in timeline


def test_backend_authority_selection_restore_and_recovery_cards_are_wired():
    store = source("store.ts")
    panel = source("SeriesLabPanel.tsx")
    assert "fetchSeriesLibrary" in store
    assert "maestro-series-lab-active" in store
    assert "seriesId, episodeId" in store
    assert "fetchSeriesPlanRecovery" in store and "fetchSeriesRenderRecovery" in store
    assert "Recoverable Series Lab work" in panel
    assert ">Resume<" in panel and ">Discard state<" in panel


def test_episode_proposal_uses_readable_cards_and_manual_editing():
    panel = source("SeriesEpisodePanel.tsx")
    review = source("SeriesEpisodeProposalReview.tsx")
    client = (ROOT / "ui" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
    assert "SeriesEpisodeProposalReview" in panel
    assert "Generated proposal — review and edit" in review
    assert "Internal IDs remain protected" in review
    assert 'title="Outline"' in review and 'title="Script"' in review and 'title="Timed shots"' in review
    assert "Reset edits" in review and "Apply reviewed" in review
    assert "Generation prompt" in review and "Visible characters" in review
    assert "Technical JSON (optional, read-only)" in review
    assert "JSON.stringify(episodeResult ? { episodeResult } : {})" in client
