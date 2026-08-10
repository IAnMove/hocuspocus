"""Source-level UI contract checks for Series Lab's lazy, recoverable workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERIES = ROOT / "ui" / "src" / "features" / "series"


def source(name: str) -> str:
    return (SERIES / name).read_text(encoding="utf-8")


def test_series_lab_is_top_level_immediately_after_story_lab():
    tabs = (ROOT / "ui" / "src" / "components" / "MainContent" / "TabFilter.tsx").read_text(encoding="utf-8")
    assert tabs.index("Story Lab") < tabs.index("Series Lab") < tabs.index("Video Editor")


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


def test_review_is_thumbnail_first_and_exposes_exact_attempt_metadata():
    review = source("SeriesReviewPanel.tsx")
    assert "getOutputThumbnailUrl" in review
    assert "open ? <video" in review
    assert 'preload="metadata"' in review
    assert "Exact generation metadata" in review
    assert "Approve this attempt" in review and "Reject</button>" in review
    assert "Open approved sequence in Video Editor" in review


def test_backend_authority_selection_restore_and_recovery_cards_are_wired():
    store = source("store.ts")
    panel = source("SeriesLabPanel.tsx")
    assert "fetchSeriesLibrary" in store
    assert "maestro-series-lab-active" in store
    assert "seriesId, episodeId" in store
    assert "fetchSeriesPlanRecovery" in store and "fetchSeriesRenderRecovery" in store
    assert "Recoverable Series Lab work" in panel
    assert ">Resume<" in panel and ">Discard state<" in panel
