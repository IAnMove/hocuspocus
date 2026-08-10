"""Contracts for exact model/settings visibility beside global cancellation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "app" / "launch.py"
CLIENT = ROOT / "ui" / "src" / "api" / "client.ts"
STORE = ROOT / "ui" / "src" / "stores" / "useStore.ts"
ACTIVITY = ROOT / "ui" / "src" / "components" / "ActivityFooter.tsx"


def test_backend_status_and_reconnect_publish_frozen_generation_details():
    launch = LAUNCH.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")

    assert "def _public_generation_details" in launch
    assert launch.count('"generation_details": _public_generation_details') >= 2
    assert "generation_details?: GenerationDetails" in client
    assert "generationDetails: j.generation_details" in store
    assert "patch.generationDetails = status.generation_details" in store


def test_activity_footer_places_exact_model_and_recipe_next_to_cancel():
    source = ACTIVITY.read_text(encoding="utf-8")

    assert "function currentModelLabel" in source
    assert "function generationRecipe" in source
    assert "function generationTitle" in source
    assert "Using: ${currentModel}" in source
    assert "flow shift ${details.flow_shift}" in source
    assert "Turbo ${details.turbo ? 'on' : 'off'}" in source
    assert "primaryModel" in source
    assert "activeRows.find" in source
    assert "Cancel this complete generation workflow" in source


def test_activity_footer_hides_cancelled_ltx_jobs_and_explains_planning():
    source = ACTIVITY.read_text(encoding="utf-8")

    assert "function humanReadableActivityMessage" in source
    assert "image and video generation have not started" in source
    assert "job.status === 'completed' || job.status === 'failed'" in source
    assert "job.status === 'completed' || job.status === 'cancelled'" in source


def test_activity_footer_recovers_and_cancels_series_lab_jobs():
    source = ACTIVITY.read_text(encoding="utf-8")

    assert "fetchSeriesPlanRecovery(activeWorkspace)" in source
    assert "fetchSeriesRenderRecovery(activeWorkspace)" in source
    assert "Series Lab · Known-series bible" in source
    assert "'series-plan' : 'series-render'" in source and "${job.jobId}" in source
    assert "api.cancelSeriesPlanJob" in source
    assert "api.cancelSeriesRenderJob" in source
    assert "api.discardSeriesPlanJob" in source
    assert "known_series_research: 'Building series bible'" in source
