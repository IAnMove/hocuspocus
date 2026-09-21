"""Contracts for exact model/settings visibility beside global cancellation."""

from pathlib import Path

from tests.api_client_source import api_client_source


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"
STORE = ROOT / "ui" / "src" / "stores" / "useStore.ts"
ACTIVITY = ROOT / "ui" / "src" / "components" / "ActivityFooter.tsx"
ACTIVITY_FEATURE = ROOT / "ui" / "src" / "features" / "activity"
ACTIVITY_EN = ROOT / "ui" / "src" / "i18n" / "locales" / "en" / "activity.json"


def activity_ui() -> str:
    parts = [ACTIVITY.read_text(encoding="utf-8"), ACTIVITY_EN.read_text(encoding="utf-8")]
    for path in sorted(ACTIVITY_FEATURE.glob("*")):
        if path.suffix in {".ts", ".tsx"}:
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_backend_status_and_reconnect_publish_frozen_generation_details():
    launch = LAUNCH.read_text(encoding="utf-8")
    client = api_client_source()
    store = STORE.read_text(encoding="utf-8")

    assert "def _public_generation_details" in launch
    assert launch.count('"generation_details": _public_generation_details') >= 2
    assert "generation_details?: GenerationDetails" in client
    assert "generationDetails: j.generation_details" in store
    assert "patch.generationDetails = status.generation_details" in store
    assert 'details["prompt"]' in launch
    assert 'details["initiator"]' in launch
    assert 'gen_params["_initiator"]' in launch


def test_activity_footer_places_exact_model_and_recipe_next_to_cancel():
    source = activity_ui()

    assert "export function generationRecipe" in source
    assert "const parts = [task.provider, task.model]" in source
    assert "details.video_model_name" in source
    assert "details.video_model_type" in source
    assert "details.image_model_name" in source
    assert "details.image_model_type" in source
    assert "flow shift" in source
    assert "audio shift" in source
    assert "profile ${details.profile}" in source
    assert "Turbo ${details.turbo ? 'on' : 'off'}" in source
    assert "Cache off" in source
    assert "LoRAs off" in source
    assert "primary.model" in source
    assert "title={generationRecipe(primary)}" in source
    assert "api.cancelCanonicalTask(taskId, workspace)" in source
    assert "primary.cancelable" in source
    assert "export function generationPrompt" in source
    assert "export function generationInitiator" in source
    assert "Click to copy the complete prompt" in source
    assert "Started by {{name}}" in source


def test_activity_footer_treats_cancellation_as_terminal_history():
    source = activity_ui()

    assert '"planning": "Planning"' in source
    assert '"cancelling": "Cancelling at a safe boundary"' in source
    assert '"cancelled": "Cancelled"' in source
    assert "LIVE_TASK_STATUSES = new Set(['created', 'queued', 'waiting_resource', 'running'])" in source
    assert "visual === 'cancelled'" in source


def test_activity_footer_recovers_and_cancels_series_lab_jobs():
    source = activity_ui()

    assert "api.fetchCanonicalTasks(activeWorkspace, 'all')" in source
    assert "api.subscribeCanonicalTaskEvents" in source
    assert "api.cancelCanonicalTask(taskId, workspace)" in source
    assert "api.dismissCanonicalTask(taskId, workspace)" in source
    assert "Building series bible" in source
