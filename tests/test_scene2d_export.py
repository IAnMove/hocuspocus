"""Server-side Video 2D export and editable scene documents.

The owned browser is replaced by an injected renderer so admission, publication
and audio-track mixing are verified without Chromium.
"""
from __future__ import annotations

import asyncio
import json
import math
import shutil
import struct
import subprocess
import time
from pathlib import Path

import pytest

from services import resource_scheduler
from services.scene2d_export import (
    OPERATION,
    Scene2DExportService,
    command_catalog,
    command_handlers,
    freeze_export_command,
    project_export_receipt,
)
from services.scene_documents import SceneDocumentError, command_catalog as document_catalog, get_document, save_document
from services.task_manager import TaskRegistry
from services.world3d_export import write_png

WORKSPACE = "x-song"
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def _layer(layer_id="bg", **overrides):
    layer = {"id": layer_id, "name": layer_id, "type": "image", "source": f"/api/v1/file/{layer_id}.png?workspace={WORKSPACE}",
             "visible": True, "z": 0, "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1},
             "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1.2}, "duration": 1, "curve": "ease"}}
    layer.update(overrides)
    return layer


def _document(**overrides):
    document = {"version": 1, "name": "Intro", "width": 64, "height": 36, "fps": 24, "duration": 0.25,
                "layers": [_layer(), {"id": "rain", "name": "rain", "type": "effect", "source": "", "visible": True, "z": 1,
                                      "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1},
                                      "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1},
                                                    "duration": 1, "curve": "linear"},
                                      "atmosphere": {"kind": "rain", "density": 20, "speed": 1, "size": 1, "wind": 0, "color": "#ffffff"}}]}
    document.update(overrides)
    return document


def _command(intent="scene2d-1", document=None, **extra):
    return {"version": 1, "operation": OPERATION, "intent_id": intent,
            "input": {"workspace": WORKSPACE, "document": document or _document(), **extra}}


def _workspace_dir(tmp_path):
    def resolve(name: str) -> str:
        path = Path(tmp_path) / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return resolve


def _paint(snapshot, staging, progress, cancelled):
    plan = snapshot["plan"]
    frames = []
    for index in range(plan["count"]):
        path = Path(staging) / "frames" / f"frame_{index + 1:06d}.png"
        write_png(path, plan["width"], plan["height"], (20 * index % 255, 80, 140))
        frames.append(path)
        progress(index + 1, plan["count"])
    return frames


def _service(tmp_path, renderer=_paint):
    workspace_dir = _workspace_dir(tmp_path)
    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    return Scene2DExportService(workspace_dir=workspace_dir, registry_for=lambda name: TaskRegistry(workspace_dir(name), interrupt_stale=False),
                                renderer=renderer, uploads_dir=lambda: str(uploads))


def _tone(path, frequency, duration=0.25):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={duration}",
                    str(path)], check=True)


def _tone_energy(media, frequency, sample_rate=48000):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(media), "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    samples = struct.unpack(f"<{len(raw) // 4}f", raw)
    real = imag = 0.0
    for index, sample in enumerate(samples):
        angle = 2 * math.pi * frequency * index / sample_rate
        real += sample * math.cos(angle)
        imag += sample * math.sin(angle)
    return (real * real + imag * imag) / max(1, len(samples))


def test_freeze_keeps_draft_and_accepts_a_final_shutter():
    draft = freeze_export_command(_command())["effective"]["input"]["snapshot"]["plan"]
    assert "quality" not in draft and "shutter" not in draft
    final = freeze_export_command(_command(quality="final", shutter=90))["effective"]["input"]["snapshot"]["plan"]
    assert final["quality"] == "final" and final["shutter"] == 90 and final["subframes"] == 4 and final["supersample"] == 1.5
    with pytest.raises(Exception) as caught:
        freeze_export_command(_command(quality="draft", shutter=180))
    assert caught.value.status_code == 422


def test_freeze_validates_2d_documents_and_collects_refs():
    frozen = freeze_export_command(_command())
    snapshot = frozen["effective"]["input"]["snapshot"]
    assert snapshot["plan"] == {"width": 64, "height": 36, "fps": 24, "duration": 0.25, "count": 6}
    assert snapshot["refs"] == [{"layerId": "bg", "url": f"/api/v1/file/bg.png?workspace={WORKSPACE}", "kind": "image",
                                 "filename": "bg.png", "workspace": WORKSPACE}]


def test_freeze_accepts_sequence_only_layers_and_collects_frame_refs():
    document = _document(layers=[_layer(
        id="walk", source="",
        sequence={"kind": "frames", "sources": [
            f"/api/v1/file/walk-1.png?workspace={WORKSPACE}",
            f"/api/v1/file/walk-2.png?workspace={WORKSPACE}",
        ], "fps": 12, "loop": "loop"},
    )])
    snapshot = freeze_export_command(_command(document=document))["effective"]["input"]["snapshot"]
    assert [ref["filename"] for ref in snapshot["refs"]] == ["walk-1.png", "walk-2.png"]


def test_freeze_collects_sheet_sequence_ref_when_source_is_empty():
    document = _document(layers=[_layer(
        id="sheet", source="",
        sequence={"kind": "sheet", "source": f"/api/v1/file/atlas.png?workspace={WORKSPACE}",
                  "columns": 4, "rows": 2, "count": 8, "fps": 12, "loop": "loop"},
    )])
    snapshot = freeze_export_command(_command(document=document))["effective"]["input"]["snapshot"]
    assert snapshot["refs"] == [{"layerId": "sheet", "url": f"/api/v1/file/atlas.png?workspace={WORKSPACE}",
                                 "kind": "image", "sequence": True, "filename": "atlas.png", "workspace": WORKSPACE}]


def test_freeze_rejects_sequence_only_layer_without_durable_frames():
    document = _document(layers=[_layer(id="walk", source="", sequence={"kind": "frames", "sources": ["blob:http://x/1"], "fps": 12, "loop": "loop"})])
    with pytest.raises(Exception) as error:
        freeze_export_command(_command(document=document))
    assert error.value.detail["code"] == "missing_ref"


def test_freeze_keeps_still_and_collects_sequence_frames():
    document = _document(layers=[_layer(sequence={"kind": "frames", "sources": [
        f"/api/v1/file/walk-1.png?workspace={WORKSPACE}",
    ], "fps": 12, "loop": "loop"})])
    snapshot = freeze_export_command(_command(document=document))["effective"]["input"]["snapshot"]
    assert [ref["filename"] for ref in snapshot["refs"]] == ["bg.png", "walk-1.png"]


@pytest.mark.parametrize("document,code", [
    (_document(layers=[_layer(type="model3d")]), "unsupported_capability"),
    (_document(layers=[_layer(source="blob:http://x/1")]), "missing_ref"),
    (_document(layers=[_layer(source="https://example.com/a.png")]), "missing_ref"),
    (_document(fps=25), "unsupported_capability"),
])
def test_freeze_rejects_unsupported_scenes(document, code):
    with pytest.raises(Exception) as error:
        freeze_export_command(_command(document=document))
    assert error.value.detail["code"] == code


def test_freeze_accepts_screen_fx_sound_and_sequence_refs():
    frozen = freeze_export_command(_command(document=_document(sfx=[{"id": "boom", "kind": "explosion", "start": 0, "end": 0.2, "sound": True, "volume": 0.4}])))
    assert frozen["effective"]["input"]["snapshot"]["document"]["sfx"][0]["sound"] is True
    sequenced = _layer(sequence={"kind": "frames", "sources": [f"/api/v1/file/wing.png?workspace={WORKSPACE}"], "fps": 8, "loop": "loop"})
    refs = freeze_export_command(_command(document=_document(layers=[sequenced])))["effective"]["input"]["snapshot"]["refs"]
    assert any(ref.get("sequence") and ref["filename"] == "wing.png" for ref in refs)
    with pytest.raises(Exception) as error:
        freeze_export_command(_command(document=_document(layers=[_layer(sequence={"kind": "frames", "sources": ["https://example.com/a.png"], "fps": 8, "loop": "loop"})])))
    assert error.value.detail["code"] == "missing_ref"


def test_freeze_gives_colourless_screen_effects_their_catalog_colour():
    # The effect painters call addColorStop(cue.color); a missing colour failed the whole render.
    from services.scene2d_schema import EFFECT_COLORS
    frozen = freeze_export_command(_command(document=_document(sfx=[
        {"id": "smoke", "kind": "smoke", "start": 0, "end": 1},
        {"id": "dust", "kind": "dust", "start": 0, "end": 1, "color": "#123456"},
    ])))
    cues = frozen["effective"]["input"]["snapshot"]["document"]["sfx"]
    assert [cue["color"] for cue in cues] == [EFFECT_COLORS["smoke"], "#123456"]


def _queued_receipt():
    return {
        "version": 1, "commandId": "scene2d-1", "operation": OPERATION, "status": "queued",
        "entities": [], "artifacts": [], "taskIds": ["task-1"], "pipelineIds": [],
        "result": {"job_id": "job-1", "task_id": "task-1", "workspace": WORKSPACE, "status": "queued"},
    }


def test_receipt_follows_the_completed_task_and_lists_the_mp4(tmp_path, monkeypatch):
    stored = _queued_receipt()
    published = {"name": "clip.mp4", "url": "/api/v1/file/clip.mp4", "workspace": WORKSPACE}
    task = {"id": "task-1", "status": "completed", "workspace": WORKSPACE, "metadata": {"output": published}, "result_refs": ["clip.mp4"]}

    class Registry:
        def command_admission(self, intent_id):
            assert intent_id == "scene2d-1"
            return {"receipt": stored, "task_id": "task-1"}

        def get(self, task_id):
            assert task_id == "task-1"
            return task

    service = _service(tmp_path)
    monkeypatch.setattr(service, "_registry", lambda _workspace: Registry())
    viewed = service.receipt(WORKSPACE, "scene2d-1")
    assert viewed["receipt"]["status"] == "completed"
    assert viewed["receipt"]["result"]["status"] == "completed"
    assert viewed["receipt"]["artifacts"] == [published]
    assert stored["status"] == "queued"
    assert stored["artifacts"] == []
    refs_only = {**task, "metadata": {}, "result_refs": ["only.mp4"]}
    fallback = project_export_receipt(stored, refs_only)
    assert fallback["artifacts"] == [{"name": "only.mp4", "url": "/api/v1/file/only.mp4", "workspace": WORKSPACE}]
    running = project_export_receipt(stored, {"status": "running", "workspace": WORKSPACE, "metadata": {}, "result_refs": []})
    assert running["status"] == "running"
    assert running["artifacts"] == []


def test_catalog_and_lane_do_not_use_the_gpu(monkeypatch):
    monkeypatch.delenv("HOCUS_SCENE_EXPORT_CONCURRENCY", raising=False)
    monkeypatch.setattr("services.scene_export_lane.os.cpu_count", lambda: 8)
    assert [item["name"] for item in command_catalog()] == [OPERATION, OPERATION + ".receipt", OPERATION + ".cancel"]
    assert Scene2DExportService.resource_lane(None) == resource_scheduler.cpu_lane("scene2d-render", capacity=2)


def test_missing_workspace_media_is_refused_before_admission(tmp_path):
    with pytest.raises(Exception) as error:
        _service(tmp_path).submit(_command())
    assert error.value.status_code == 409 and error.value.detail["code"] == "missing_ref"


def test_freeze_marks_upload_urls_as_uploads_root():
    document = _document(layers=[_layer(source="/api/v1/uploads/local-hero.png")])
    snapshot = freeze_export_command(_command(document=document))["effective"]["input"]["snapshot"]
    assert snapshot["refs"] == [{"layerId": "bg", "url": "/api/v1/uploads/local-hero.png", "kind": "image",
                                 "filename": "local-hero.png", "root": "uploads"}]


def test_upload_media_is_admitted_from_uploads_dir(tmp_path):
    service = _service(tmp_path)
    write_png(Path(service.uploads_dir()) / "local-hero.png", 8, 8, (10, 20, 30))
    document = _document(layers=[_layer(source="/api/v1/uploads/local-hero.png")])
    receipt = service.submit(_command(intent="scene2d-upload", document=document))
    assert receipt["receipt"]["taskIds"]


def test_missing_upload_media_is_refused_before_admission(tmp_path):
    service = _service(tmp_path)
    write_png(Path(service.workspace_dir(WORKSPACE)) / "local-hero.png", 8, 8, (10, 20, 30))
    document = _document(layers=[_layer(source="/api/v1/uploads/local-hero.png")])
    with pytest.raises(Exception) as error:
        service.submit(_command(intent="scene2d-upload-missing", document=document))
    assert error.value.status_code == 409 and error.value.detail["code"] == "missing_ref"


def test_freeze_marks_uploads_gallery_file_urls():
    document = _document(layers=[_layer(source="/api/v1/file/gallery-hero.png?workspace=__uploads__")])
    snapshot = freeze_export_command(_command(document=document))["effective"]["input"]["snapshot"]
    assert snapshot["refs"] == [{"layerId": "bg", "url": "/api/v1/file/gallery-hero.png?workspace=__uploads__",
                                 "kind": "image", "filename": "gallery-hero.png", "root": "uploads"}]


def test_uploads_gallery_file_url_is_admitted(tmp_path):
    service = _service(tmp_path)
    write_png(Path(service.uploads_dir()) / "gallery-hero.png", 8, 8, (10, 20, 30))
    document = _document(layers=[_layer(source="/api/v1/file/gallery-hero.png?workspace=__uploads__")])
    receipt = service.submit(_command(intent="scene2d-uploads-gallery", document=document))
    assert receipt["receipt"]["taskIds"]


def test_scoped_workspace_file_url_is_admitted(tmp_path):
    service = _service(tmp_path)
    write_png(Path(service.workspace_dir("assets")) / "shared.png", 8, 8, (40, 50, 60))
    document = _document(layers=[_layer(source="/api/v1/file/shared.png?workspace=assets")])
    receipt = service.submit(_command(intent="scene2d-scoped", document=document))
    assert receipt["receipt"]["taskIds"]


def test_missing_scoped_workspace_file_is_refused(tmp_path):
    service = _service(tmp_path)
    write_png(Path(service.workspace_dir(WORKSPACE)) / "shared.png", 8, 8, (10, 20, 30))
    document = _document(layers=[_layer(source="/api/v1/file/shared.png?workspace=assets")])
    with pytest.raises(Exception) as error:
        service.submit(_command(intent="scene2d-scoped-missing", document=document))
    assert error.value.status_code == 409 and error.value.detail["code"] == "missing_ref"


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")
def test_export_publishes_mp4_with_audio_tracks(tmp_path):
    service = _service(tmp_path)
    root = Path(service.workspace_dir(WORKSPACE))
    write_png(root / "bg.png", 8, 8, (10, 20, 30))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=0.2", str(root / "vo.wav")], check=True)
    document = _document(audioTracks=[{"id": "vo", "filename": "vo.wav", "name": "vo", "kind": "speech", "startTime": 0.05, "volume": 1}])
    receipt = asyncio.run(asyncio.to_thread(command_handlers(service)[OPERATION],
                                            {"version": 1, "intent_id": "scene2d-audio", "input": {"workspace": WORKSPACE, "document": document}}))
    task_id = receipt["receipt"]["taskIds"][0]
    registry = service._registry(WORKSPACE)
    deadline = time.time() + 20
    while time.time() < deadline and (registry.get(task_id) or {}).get("status") not in {"completed", "failed"}:
        time.sleep(0.05)
    task = registry.get(task_id)
    assert task["status"] == "completed", task
    output = root / task["metadata"]["output"]["name"]
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)],
                                      capture_output=True, text=True, check=True).stdout)
    assert {stream["codec_type"] for stream in probe["streams"]} == {"video", "audio"}
    sidecar = json.loads(output.with_suffix(".meta.json").read_text()) if output.with_suffix(".meta.json").exists() else None
    assert output.name.startswith(time.strftime("%Y")) and "_video2d-Intro_" in output.name
    assert sidecar is None or sidecar.get("tool") == "scene2d-export" or "scene2d-export" in json.dumps(sidecar)


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")
def test_export_mixes_synthesized_screen_fx_wav(tmp_path):
    def paint_with_fx(snapshot, staging, progress, cancelled):
        frames = _paint(snapshot, staging, progress, cancelled)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.25", str(Path(staging) / "fx.wav")], check=True)
        return frames

    service = _service(tmp_path, renderer=paint_with_fx)
    root = Path(service.workspace_dir(WORKSPACE))
    write_png(root / "bg.png", 8, 8, (10, 20, 30))
    document = _document(sfx=[{"id": "boom", "kind": "explosion", "start": 0, "end": 0.2, "sound": True, "volume": 0.4}])
    receipt = asyncio.run(asyncio.to_thread(command_handlers(service)[OPERATION],
                                            {"version": 1, "intent_id": "scene2d-fx", "input": {"workspace": WORKSPACE, "document": document}}))
    task_id = receipt["receipt"]["taskIds"][0]
    registry = service._registry(WORKSPACE)
    deadline = time.time() + 20
    while time.time() < deadline and (registry.get(task_id) or {}).get("status") not in {"completed", "failed"}:
        time.sleep(0.05)
    task = registry.get(task_id)
    assert task["status"] == "completed", task
    output = root / task["metadata"]["output"]["name"]
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)],
                                      capture_output=True, text=True, check=True).stdout)
    assert {stream["codec_type"] for stream in probe["streams"]} == {"video", "audio"}


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")
def test_finish_media_keeps_screen_fx_when_mixing_audio_tracks(tmp_path):
    service = _service(tmp_path)
    root = Path(service.workspace_dir(WORKSPACE))
    staging = tmp_path / "staging"
    staging.mkdir()
    encoded = staging / "silent.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x36:d=0.25:r=24",
                    "-pix_fmt", "yuv420p", str(encoded)], check=True)
    _tone(staging / "fx.wav", 440)
    _tone(root / "vo.wav", 330)
    snapshot = {"workspace": WORKSPACE, "document": _document(
        sfx=[{"id": "boom", "kind": "explosion", "start": 0, "end": 0.2, "sound": True, "volume": 0.4}],
        audioTracks=[{"id": "vo", "filename": "vo.wav", "name": "vo", "kind": "speech", "startTime": 0, "volume": 1}]),
                "plan": {"width": 64, "height": 36, "fps": 24, "duration": 0.25, "count": 6}, "refs": []}
    mixed = service.finish_media(snapshot, staging, encoded)
    noise = _tone_energy(mixed, 800)
    assert _tone_energy(mixed, 440) > 10 * noise
    assert _tone_energy(mixed, 330) > 10 * noise


def test_scene_documents_save_2d_and_3d_revisions(tmp_path):
    workspace_dir = _workspace_dir(tmp_path)
    saved = save_document(WORKSPACE, _document(), name="Intro shot", preview=None, workspace_dir=workspace_dir)
    assert saved["editor"] == "video2d" and saved["name"].startswith("Intro-shot-") and saved["name"].endswith(".scene.json")
    again = save_document(WORKSPACE, _document(), name="Intro shot", preview=None, workspace_dir=workspace_dir)
    assert again["name"] != saved["name"]
    assert get_document(WORKSPACE, saved["name"], workspace_dir=workspace_dir)["document"]["layers"][0]["id"] == "bg"
    world = {"version": 1, "units": "meters", "up": "y", "width": 64, "height": 64, "fps": 24, "duration": 1,
             "camera": {"family": "fixed", "eye": [0, 1, 4], "look": [0, 1, 0], "fov": 40},
             "light": {"kind": "directional", "direction": [0, -1, 0], "intensity": 1, "color": "#ffffff"}, "slots": []}
    stored = save_document(WORKSPACE, world, name="Launch", preview=None, workspace_dir=workspace_dir)
    assert stored["editor"] == "video3d" and stored["name"].endswith(".world3d.scene.json")
    with pytest.raises(SceneDocumentError):
        save_document(WORKSPACE, _document(layers=[_layer(source="blob:x")]), name=None, preview=None, workspace_dir=workspace_dir)
    with pytest.raises(SceneDocumentError):
        save_document(WORKSPACE, _document(layers=[_layer(sequence={"kind": "frames", "sources": ["https://example.com/a.png"], "fps": 8, "loop": "loop"})]), name=None, preview=None, workspace_dir=workspace_dir)
    assert [item["name"] for item in document_catalog()] == ["scenes.document.save", "scenes.document.get"]


def test_series_lab_media_in_a_workspace_subfolder_can_be_exported(tmp_path):
    # Series Lab keeps location images in assets/<series>/; the export used to look only at the file name.
    service = _service(tmp_path)
    folder = Path(_workspace_dir(tmp_path)(WORKSPACE)) / "assets" / "uv"
    folder.mkdir(parents=True)
    write_png(folder / "garage.png", 8, 8, (10, 20, 30))
    document = _document(layers=[_layer(source=f"/api/v1/file/assets/uv/garage.png?workspace={WORKSPACE}")])
    admitted = service.submit(_command("scene2d-subfolder", document))
    assert admitted["receipt"]["taskIds"]
    escaping = _document(layers=[_layer(source=f"/api/v1/file/assets/../../secret.png?workspace={WORKSPACE}")])
    with pytest.raises(Exception) as error:
        service.submit(_command("scene2d-escape", escaping))
    assert error.value.status_code == 422
