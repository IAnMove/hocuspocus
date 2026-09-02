"""Source-level UI contract checks for Series Lab's lazy, recoverable workflow."""

import json

from pathlib import Path

from tests.api_client_source import api_client_source


ROOT = Path(__file__).resolve().parents[1]
SERIES = ROOT / "ui" / "src" / "features" / "series"
CATALOG_EN = ROOT / "ui" / "src" / "i18n" / "locales" / "en" / "seriesLab.json"


def source(name: str) -> str:
    return (SERIES / name).read_text(encoding="utf-8")


def test_series_lab_is_top_level_immediately_after_story_lab():
    tabs = (ROOT / "ui" / "src" / "components" / "MainContent" / "TabFilter.tsx").read_text(encoding="utf-8")
    assert tabs.index("value: 'stories'") < tabs.index("value: 'series'") < tabs.index("value: 'videoeditor'")


def test_client_created_series_entities_use_browser_uuid():
    model = source("model.ts")
    assert "crypto.randomUUID()" in model
    assert "Math.random()" not in model


def test_setup_has_required_aura_explicit_models_and_canvas_choices():
    setup = source("SeriesSetupPanel.tsx")
    fields = source("components.tsx")
    catalog = json.loads(CATALOG_EN.read_text(encoding="utf-8"))
    assert "shadow-[0_0_18px" in fields
    assert "t('setup.prepareText')" in setup
    assert catalog["setup"]["prepareText"] == "Prepare canon text"
    assert "t('setup.prepareImages')" in setup
    assert catalog["setup"]["prepareImages"] == "Prepare canon + up to 4 images"
    assert "t('setup.needImageModel')" in setup
    assert "will not silently select or download a recommended model" in catalog["setup"]["needImageModel"]
    assert "minimax_h3" in setup and "minimax_h3_full" in setup
    assert "480p" in setup and "720p" in setup
    assert "t('providers.landscape')" in setup and "t('providers.portrait')" in setup
    assert catalog["providers"]["landscape"].startswith("Landscape")
    assert catalog["providers"]["portrait"].startswith("Portrait")
    assert "t('setup.knownTitle')" in setup
    assert catalog["setup"]["knownTitle"] == "Fill from a known series · one click"
    assert "bootstrapKnownSeries: true" in setup and "autoApply: true" in setup
    assert "t('setup.knownDisclaimer')" in setup
    assert "not live web research" in catalog["setup"]["knownDisclaimer"]
    assert "t('setup.draftReview')" in setup
    assert "Nothing has been approved automatically" in catalog["setup"]["draftReview"]


def test_shot_ui_exposes_exact_manifest_and_persistent_manual_policy():
    shots = source("SeriesShotsPanel.tsx")
    catalog = json.loads(CATALOG_EN.read_text(encoding="utf-8"))
    assert "t('shots.manifestTitle')" in shots
    assert catalog["shots"]["manifestTitle"] == "Exact routed manifest"
    assert "manualIncludeAssetIds" in shots
    assert "manualExcludeAssetIds" in shots
    assert "composed_start_frame" in shots and "composed_end_frame" in shots
    assert "t('shots.renderSelected'" in shots and "t('shots.renderMissing')" in shots and "t('shots.retryFailed')" in shots
    assert catalog["shots"]["renderSelected"].startswith("Render selected")
    assert catalog["shots"]["renderMissing"] == "Render missing"
    assert catalog["shots"]["retryFailed"] == "Retry failed"
    assert "t('shots.selectAll'" in shots and "t('shots.clearSelection')" in shots
    assert "t('shots.lipSyncEnable')" in shots
    assert catalog["shots"]["lipSyncEnable"] == "I understand · enable dialogue rendering"
    assert "onAcknowledgeLipSync" in shots


def test_canon_facts_can_be_removed_individually():
    canon = source("SeriesCanonPanel.tsx")
    catalog = json.loads(CATALOG_EN.read_text(encoding="utf-8"))
    assert "title={t('canon.currentFacts')}" in canon
    assert catalog["canon"]["currentFacts"] == "Current facts"
    assert "currentFacts: series.canon.currentFacts.filter(item => item.id !== fact.id)" in canon
    assert "aria-label={t('canon.deleteFact', { description: fact.description })}" in canon


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
    assert "t('review.orderedAssembly')" in review and "t('review.historyAttempts')" in review
    assert "Attempts in this slot" in review
    assert "Open complete approved sequence in Video Editor" in review


def test_story_productions_have_an_in_place_ordered_clip_timeline():
    tabs = (ROOT / "ui" / "src" / "features" / "stories" / "storyLabTabs.ts").read_text(encoding="utf-8")
    assembly = (ROOT / "ui" / "src" / "features" / "stories" / "StoryAssemblyTab.tsx").read_text(encoding="utf-8")
    timeline = (ROOT / "ui" / "src" / "features" / "stories" / "StoryProductionTimeline.tsx").read_text(encoding="utf-8")
    catalog_es = (ROOT / "ui" / "src" / "i18n" / "locales" / "es" / "storyLab.json").read_text(encoding="utf-8")
    assert "id: 'assembly'" in tabs
    assert "icon: Play" in tabs
    assert "StoryProductionTimeline" in assembly
    assert "initiallyOpen={index === 0}" in assembly
    assert '"assembly": "Montaje"' in catalog_es
    assert "t('timeline.viewOrdered')" in timeline and "t('timeline.playAll')" in timeline
    assert "t('timeline.editRegenerate')" in timeline and "t('timeline.joinClips')" in timeline
    assert "fetchSavedPipeline" in timeline


def test_backend_authority_selection_restore_and_recovery_cards_are_wired():
    store = source("store.ts")
    panel = source("SeriesLabPanel.tsx")
    catalog = json.loads(CATALOG_EN.read_text(encoding="utf-8"))
    assert "fetchSeriesLibrary" in store
    assert "maestro-series-lab-active" in store
    assert "seriesId, episodeId" in store
    assert "fetchSeriesPlanRecovery" in store and "fetchSeriesRenderRecovery" in store
    assert "t('recovery.title')" in panel
    assert catalog["recovery"]["title"] == "Recoverable Series Lab work"
    assert "t('chrome.resume')" in panel and "t('chrome.discardState')" in panel


def test_episode_proposal_uses_readable_cards_and_manual_editing():
    panel = source("SeriesEpisodePanel.tsx")
    review = source("SeriesEpisodeProposalReview.tsx")
    client = api_client_source()
    catalog = json.loads(CATALOG_EN.read_text(encoding="utf-8"))
    assert "SeriesEpisodeProposalReview" in panel
    assert "t('proposal.title')" in review
    assert catalog["proposal"]["title"] == "Generated proposal — review and edit"
    assert "t('proposal.description')" in review
    assert "Internal IDs remain protected" in catalog["proposal"]["description"]
    assert "title={t('proposal.outline')}" in review
    assert "title={t('proposal.script')}" in review
    assert "title={t('proposal.timedTitle')}" in review
    assert "t('proposal.reset')" in review and "t('proposal.apply')" in review
    assert "t('proposal.prompt')" in review and "t('proposal.visibleCharacters')" in review
    assert "t('proposal.technicalJson')" in review
    assert catalog["proposal"]["technicalJson"] == "Technical JSON (optional, read-only)"
    assert "JSON.stringify(episodeResult ? { episodeResult } : {})" in client
