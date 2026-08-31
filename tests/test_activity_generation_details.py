"""Contracts for exact model/settings visibility beside global cancellation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"
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
    assert 'details["prompt"]' in launch
    assert 'details["initiator"]' in launch
    assert 'gen_params["_initiator"]' in launch


def test_activity_footer_places_exact_model_and_recipe_next_to_cancel():
    source = ACTIVITY.read_text(encoding="utf-8")

    assert "function generationRecipe" in source
    assert "const parts = [task.provider, task.model]" in source
    assert "details.video_model_name || details.video_model_type" in source
    assert "details.image_model_name || details.image_model_type" in source
    assert "flow shift ${details.flow_shift ?? details.flowShift}" in source
    assert "audio shift ${details.audio_shift ?? details.audioShift}" in source
    assert "profile ${details.profile}" in source
    assert "Turbo ${details.turbo ? 'on' : 'off'}" in source
    assert "Cache off" in source
    assert "LoRAs off" in source
    assert "primary?.model" in source
    assert "title={generationRecipe(primary)}" in source
    assert "api.cancelCanonicalTask(taskId, workspace)" in source
    assert "primary.cancelable" in source
    assert "function generationPrompt" in source
    assert "function generationInitiator" in source
    assert "Click to copy the complete prompt" in source
    assert "Started by {initiator}" in source


def test_activity_footer_treats_cancellation_as_terminal_history():
    source = ACTIVITY.read_text(encoding="utf-8")

    assert "planning: 'Planning'" in source
    assert "cancelling: 'Cancelling at a safe boundary'" in source
    assert "cancelled: 'Cancelled'" in source
    assert "const ACTIVE = new Set(['created', 'queued', 'waiting_resource', 'running'])" in source
    assert "primaryVisualState === 'cancelled'" in source


def test_activity_footer_recovers_and_cancels_series_lab_jobs():
    source = ACTIVITY.read_text(encoding="utf-8")

    assert "api.fetchCanonicalTasks(activeWorkspace, 'all')" in source
    assert "api.subscribeCanonicalTaskEvents" in source
    assert "api.cancelCanonicalTask(taskId, workspace)" in source
    assert "api.dismissCanonicalTask(taskId, workspace)" in source
    assert "known_series_research: 'Building series bible'" in source
