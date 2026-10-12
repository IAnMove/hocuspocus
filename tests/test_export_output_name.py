"""Named scene exports: ``output_name`` publishes a stable file that a later export replaces, keeping the previous."""
from __future__ import annotations

import json
import hashlib
import shutil
import time
from pathlib import Path

import pytest

from services.export_output_name import export_file_name, publish_export_file
from services.export_receipts import project_export_receipt
from services.generation_output_name import OutputNameError
from services.scene2d_export import (
    OPERATION as VIDEO2D,
    Scene2DExportService,
    command_catalog as video2d_catalog,
    freeze_export_command as freeze_video2d,
)
from services.task_manager import TaskRegistry, forget_task_registry
from services.world3d_export import (
    OPERATION as WORLD3D,
    World3DExportService,
    command_catalog as world3d_catalog,
    freeze_export_command as freeze_world3d,
    write_png,
)
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
WORKSPACE = "workspace-a"


def world3d_command(intent_id: str, **extra) -> dict:
    document = {
        "version": 1, "units": "meters", "up": "y", "width": 64, "height": 64, "fps": 30, "duration": 2 / 30,
        "templateId": "two-shot", "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
        "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
        "slots": [{"id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0, "scale": 1,
                   "sourceUrl": "", "media": "model3d", "clip": None}],
    }
    return {"version": 1, "operation": WORLD3D, "intent_id": intent_id,
            "input": {"workspace": WORKSPACE, "document": document, "refs": [], **extra}}


def _wait(registry, task_id, wanted, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = registry.get(task_id)
        if task and task["status"] in wanted:
            return task
        time.sleep(0.02)
    raise AssertionError(registry.get(task_id))


def _paint(snapshot, staging, progress, cancelled):
    plan, frames = snapshot["plan"], []
    for index in range(plan["count"]):
        path = Path(staging) / "frames" / f"frame_{index + 1:06d}.png"
        write_png(path, plan["width"], plan["height"], (40 * index % 255, 90, 160))
        frames.append(path)
        progress(index + 1, plan["count"])
    return frames


def _service(tmp_path: Path, kind=World3DExportService):
    def workspace_dir(name: str) -> str:
        path = Path(tmp_path) / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    return kind(workspace_dir=workspace_dir, registry_for=lambda name: TaskRegistry(workspace_dir(name), interrupt_stale=False),
                renderer=_paint, uploads_dir=lambda: str(uploads))


def _video2d_command(intent: str, **extra) -> dict:
    document = {"version": 1, "name": "Fog", "width": 64, "height": 36, "fps": 24, "duration": 2 / 24, "layers": [{
        "id": "fx", "name": "fx", "type": "effect", "source": "", "visible": True, "z": 0,
        "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1},
        "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1}, "duration": 1, "curve": "linear"},
        "atmosphere": {"kind": "rain", "density": 20, "speed": 1, "size": 1, "wind": 0, "color": "#ffffff"}}]}
    return {"version": 1, "operation": VIDEO2D, "intent_id": intent, "input": {"workspace": WORKSPACE, "document": document, **extra}}


def _export(service, command) -> dict:
    receipt = service.submit(command)["receipt"]
    registry = service._registry(WORKSPACE)
    task = _wait(registry, receipt["taskIds"][0], {"completed", "failed"})
    assert task["status"] == "completed", task.get("error")
    return service.receipt(WORKSPACE, command["intent_id"])


@pytest.mark.parametrize("value, expected", [("set-crane-loop", "set-crane-loop.mp4"), ("set-crane-loop.mp4", "set-crane-loop.mp4"),
                                             ("Plano 5.MOV", "Plano 5.mp4"), ("v1.2", "v1.2.mp4")])
def test_names_get_one_mp4_extension(value, expected):
    assert export_file_name(value) == expected


@pytest.mark.parametrize("value", ["", " x", "../x", "a/b", "a\\b", ".hidden", "loop.previous", "loop.previous.mp4", "c:x",
                                   "x" * 181, 7, None])
def test_bad_names_are_refused(value):
    with pytest.raises(OutputNameError):
        export_file_name(value)


@pytest.mark.parametrize("freeze, command", [(freeze_world3d, lambda **extra: world3d_command("n1", **extra)),
                                             (freeze_video2d, lambda **extra: _video2d_command("n1", **extra))])
def test_freeze_puts_the_name_in_the_snapshot_and_the_digest(freeze, command):
    plain, named = freeze(command()), freeze(command(output_name="loop"))
    assert "outputName" not in plain["effective"]["input"]["snapshot"]  # earlier intents keep their digest
    assert named["effective"]["input"]["snapshot"]["outputName"] == "loop.mp4"
    assert named["fingerprint"] != plain["fingerprint"]
    with pytest.raises(Exception) as error:
        freeze(command(output_name="../loop"))
    assert error.value.status_code == 422 and error.value.detail["code"] == "invalid_output_name"


def test_both_catalogs_offer_output_name():
    for catalog in (world3d_catalog(), video2d_catalog()):
        export_input = catalog[0]["inputSchema"]["properties"]["input"]["properties"]
        assert "previous" in export_input["output_name"]["description"]
        assert "output_name" in catalog[0]["description"]


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")
def test_world3d_named_export_replaces_and_keeps_the_previous(tmp_path):
    service = _service(tmp_path)
    workspace = tmp_path / WORKSPACE
    first = _export(service, world3d_command("crane-1", output_name="set-crane-loop"))
    original = (workspace / "set-crane-loop.mp4").read_bytes()
    sha256 = hashlib.sha256(original).hexdigest()
    assert first["receipt"]["artifacts"] == [{"name": "set-crane-loop.mp4",
                                              "url": f"/api/v1/file/set-crane-loop.mp4?workspace={WORKSPACE}&sha256={sha256}",
                                              "workspace": WORKSPACE, "sha256": sha256}]
    first_id = json.loads((workspace / "set-crane-loop.meta.json").read_text())["asset"]["id"]

    second = _export(service, world3d_command("crane-2", output_name="set-crane-loop.mp4", quality="final"))
    artifact = second["receipt"]["artifacts"][0]
    assert artifact["name"] == "set-crane-loop.mp4"
    assert artifact["replaced"] is True and artifact["previous"] == "set-crane-loop.previous.mp4"
    assert (workspace / "set-crane-loop.previous.mp4").read_bytes() == original
    previous = json.loads((workspace / "set-crane-loop.previous.meta.json").read_text())
    assert previous["asset"]["filename"] == "set-crane-loop.previous.mp4" and previous["asset"]["id"] == first_id
    current = json.loads((workspace / "set-crane-loop.meta.json").read_text())
    assert current["asset"]["filename"] == "set-crane-loop.mp4" and current["asset"]["id"] != first_id
    old_artifact = service.receipt(WORKSPACE, "crane-1")["receipt"]["artifacts"][0]
    assert (workspace / old_artifact["name"]).read_bytes() == original
    assert sorted(path.name for path in workspace.glob("set-crane-loop*")) == [
        "set-crane-loop.meta.json", "set-crane-loop.mp4", "set-crane-loop.previous.meta.json", "set-crane-loop.previous.mp4"]

    # Replaying an intent returns its receipt without exporting again; the same intent with another name conflicts.
    replay = service.submit(world3d_command("crane-2", output_name="set-crane-loop.mp4", quality="final"))
    assert replay["replayed"] is True
    with pytest.raises(Exception) as error:
        service.submit(world3d_command("crane-2", output_name="other", quality="final"))
    assert error.value.detail["code"] == "intent_conflict"
    forget_task_registry(str(workspace))


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")
def test_video2d_named_export_publishes_under_the_name(tmp_path):
    service = _service(tmp_path, Scene2DExportService)
    viewed = _export(service, _video2d_command("fog-1", output_name="fg-fog"))
    assert viewed["receipt"]["artifacts"][0]["name"] == "fg-fog.mp4"
    assert viewed["task"]["result_refs"] == ["fg-fog.mp4"]
    sidecar = json.loads((tmp_path / WORKSPACE / "fg-fog.meta.json").read_text())
    assert sidecar["output_filename"] == "fg-fog.mp4"
    again = _export(service, _video2d_command("fog-2", output_name="fg-fog"))
    assert again["receipt"]["artifacts"][0]["previous"] == "fg-fog.previous.mp4"
    unnamed = _export(service, _video2d_command("fog-3"))
    assert "_video2d-Fog_" in unnamed["receipt"]["artifacts"][0]["name"]
    assert "replaced" not in unnamed["receipt"]["artifacts"][0]
    forget_task_registry(str(tmp_path / WORKSPACE))


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")
def test_failed_named_export_restores_current_previous_and_sidecars(tmp_path, monkeypatch):
    from services import world3d_export
    service = _service(tmp_path)
    _export(service, world3d_command("kept-1", output_name="loop"))
    _export(service, world3d_command("kept-2", output_name="loop", quality="final"))
    folder = tmp_path / WORKSPACE
    before = {path.name: path.read_bytes() for path in folder.glob("loop*")}
    publish = world3d_export.publish_generation_sidecar

    def fail_after_sidecar(*args, **kwargs):
        publish(*args, **kwargs)
        raise OSError("sidecar storage failed")

    monkeypatch.setattr(world3d_export, "publish_generation_sidecar", fail_after_sidecar)
    admitted = service.submit(world3d_command("failed-3", output_name="loop"))['receipt']
    task = _wait(service._registry(WORKSPACE), admitted['taskIds'][0], {'failed', 'completed'})
    assert task['status'] == 'failed'
    assert {path.name: path.read_bytes() for path in folder.glob("loop*")} == before
    assert not list(folder.glob('.publication-*'))
    forget_task_registry(str(folder))


def test_publish_keeps_one_previous_level_and_the_prores_sibling(tmp_path):
    output = tmp_path / "loop.mp4"
    for round_number in range(3):
        encoded, master = tmp_path / f"enc{round_number}.mp4", tmp_path / f"m{round_number}.mov"
        encoded.write_bytes(f"mp4-{round_number}".encode())
        master.write_bytes(f"mov-{round_number}".encode())
        (tmp_path / "loop.meta.json").write_text(json.dumps({"asset": {"filename": "loop.mp4", "uri": "loop.mp4", "id": f"a{round_number - 1}"},
                                                             "output_filename": "loop.mp4"}))
        kept = publish_export_file(encoded, output, master if round_number < 2 else None)
    assert kept == {"replaced": True, "previous": "loop.previous.mp4"}
    assert output.read_bytes() == b"mp4-2" and (tmp_path / "loop.previous.mp4").read_bytes() == b"mp4-1"
    assert (tmp_path / "loop.previous.mov").read_bytes() == b"mov-1"
    assert not (tmp_path / "loop.mov").exists()  # the new render has no master: the old one is only the previous
    assert not (tmp_path / "loop.meta.json").exists()  # the publisher writes the new file's own sidecar
    previous = json.loads((tmp_path / "loop.previous.meta.json").read_text())
    assert previous["asset"] == {"filename": "loop.previous.mp4", "uri": "loop.previous.mp4", "id": "a1"}
    assert previous["output_filename"] == "loop.previous.mp4"
    assert not list(tmp_path.glob(".*.keep"))


def test_receipt_projects_the_replacement():
    task = {"status": "completed", "workspace": "w", "metadata": {"output": {
        "name": "loop.mp4", "url": "/api/v1/file/loop.mp4", "workspace": "w", "replaced": True, "previous": "loop.previous.mp4"}}}
    projected = project_export_receipt({"status": "queued", "artifacts": []}, task)
    assert projected["artifacts"] == [{"name": "loop.mp4", "url": "/api/v1/file/loop.mp4", "workspace": "w",
                                       "replaced": True, "previous": "loop.previous.mp4"}]
