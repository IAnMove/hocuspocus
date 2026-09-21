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


def test_activity_reference_images_preserve_roots_order_and_bound_metadata(tmp_path):
    from services.activity_media import activity_reference_images
    from services.task_manager import _bounded

    uploads = tmp_path / 'uploads'
    workspace = tmp_path / 'outputs' / 'art'
    uploads.mkdir()
    workspace.mkdir(parents=True)
    source = uploads / 'source image.png'
    source.touch()
    refs = [workspace / f'ref-{i}.png' for i in range(12)]
    for ref in refs:
        ref.touch()
    items = activity_reference_images({
        'image_guide': str(source), 'image_start': str(source),
        'image_refs': [str(ref) for ref in refs],
        'image_mask': str(uploads / 'mask.png'),
    }, 'art', uploads_dir=uploads, workspace_dir=workspace)
    assert len(items) == 10
    assert items[0]['url'] == '/api/v1/uploads/source%20image.png'
    assert items[0]['thumbnail_url'].endswith('source%20image.png?workspace=__uploads__')
    assert items[1]['url'] == '/api/v1/file/ref-0.png?workspace=art'
    assert items[1]['thumbnail_url'].endswith('ref-0.png?workspace=art')
    assert _bounded({'reference_images': items}) == {'reference_images': items}
    assert str(tmp_path) not in str(items)


def test_activity_reference_images_reject_foreign_urls_paths_and_traversal(tmp_path):
    from services.activity_media import activity_reference_images

    uploads = tmp_path / 'uploads'
    workspace = tmp_path / 'art'
    uploads.mkdir()
    workspace.mkdir()
    (workspace / 'known.png').touch()
    values = [
        'https://example.com/image.png', 'blob:abc', '/private/image.png',
        '/api/v1/file/known.png?workspace=other',
        '/api/v1/uploads/../art/known.png',
        '/api/v1/uploads/%2E%2E/art/known.png',
        str(workspace / 'video.mp4'), None, {'path': 'image.png'},
    ]
    assert activity_reference_images({'image_refs': values}, 'art', uploads_dir=uploads, workspace_dir=workspace) == []
