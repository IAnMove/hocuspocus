"""Comic-page chapter transition: two saved scenes, a fake export, and the failures that must not write."""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from PIL import Image

from services.montage_documents import MontageStore
from services.scene3d_comic import bind_comic_exporter
from services.scene3d_comic_cutout import bind_comic_cutout
from services.world3d_template_commands import command_catalog, execute_command

def _paint_cutout(source, dest):
    image = Image.open(source).convert("RGBA")
    pixels = image.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            if min(x, y, width - 1 - x, height - 1 - y) < 8:
                red, green, blue, _alpha = pixels[x, y]
                pixels[x, y] = (red, green, blue, 0)
    image.save(dest)
    return dest


@pytest.fixture(autouse=True)
def _clear_exporter():
    bind_comic_exporter(None)
    bind_comic_cutout(_paint_cutout)
    yield
    bind_comic_exporter(None)
    bind_comic_cutout(None)


class _FakeExport:
    def export_clip(self, workspace, document, output_name):
        assert document["templateId"].startswith("comic-panel-")
        assert document["look"]["toneMapping"] == "none"
        return {"name": f"{output_name}.mp4", "url": f"/api/v1/file/{output_name}.mp4?workspace={workspace}"}


def _panels(tmp_path, count=4, cutout=False):
    folder = tmp_path / "sources"
    folder.mkdir(exist_ok=True)
    panels = []
    for index in range(count):
        path = folder / f"frame-{index}.png"
        Image.new("RGB", (64, 36), (40 + index * 30, 80, 120)).save(path)
        if cutout and index == 1:
            mask = folder / "hero-cutout.png"
            image = Image.new("RGBA", (64, 36), (0, 0, 0, 0))
            for y in range(8, 28):
                for x in range(12, 52):
                    image.putpixel((x, y), (196, 90, 74, 255))
            image.save(mask)
            panels.append({"image": str(path), "cutout": str(mask)})
        else:
            panels.append(str(path))
    return panels


def _call(tmp_path, panels, *, export=False, fmt="landscape", intent="comic-1", **extra):
    root = lambda workspace: str(tmp_path / workspace)
    (tmp_path / "studio").mkdir(exist_ok=True)
    return execute_command("scene3d.comic.transition", {
        "version": 1, "intent_id": intent,
        "input": {"workspace": "studio", "format": fmt, "panels": panels, "from_panel": 0, "to_panel": 3, "export": export, **extra},
    }, root)


def _documents(tmp_path, scenes):
    studio = tmp_path / "studio" / "world3d-edits"
    return [json.loads((studio / f"{scene['sceneId']}.json").read_text())["document"] for scene in scenes]


def _endpoint(document, end: bool):
    framing = document["camera"]["framing"]
    slot = next(item for item in document["slots"] if item["id"] == framing["targetSlot"])
    center = [slot["position"][0], slot["position"][1] + slot["scale"], slot["position"][2]]
    eye_key, look_key = ("to", "lookTo") if end else ("from", "lookFrom")
    scale = slot["scale"]
    eye = [center[i] + framing[eye_key][i] * scale for i in range(3)]
    look = [center[i] + framing[look_key][i] * scale for i in range(3)]
    return eye, look


def _written(tmp_path):
    studio = tmp_path / "studio"
    return [path.relative_to(studio).as_posix() for path in studio.rglob("*") if path.is_file()]


def test_the_scene2d_exporter_does_not_replace_the_video3d_one():
    import services.scene3d_comic as comic

    class _World:
        operation = "scenes.world3d.export"

    class _Flat:
        operation = "scenes.video2d.export"

    comic.bind_live_exporter(_World())
    bound = comic._EXPORTER
    assert bound is not None
    comic.bind_live_exporter(_Flat())
    assert comic._EXPORTER is bound
    comic.bind_live_exporter(object())
    assert comic._EXPORTER is bound


def test_the_operation_is_in_the_shared_catalog():
    named = {item["name"]: item for item in command_catalog()}
    assert named["scene3d.comic.transition"]["mutation"] is True
    assert "panels" in named["scene3d.comic.transition"]["inputSchema"]["properties"]["input"]["properties"]


def test_a_transition_saves_two_editable_scenes_and_exports_through_the_bound_exporter(tmp_path):
    bind_comic_exporter(_FakeExport())
    reply = _call(tmp_path, _panels(tmp_path, cutout=True), export=True)
    assert reply["status"] == "completed"
    scenes = reply["result"]["scenes"]
    assert [scene["role"] for scene in scenes] == ["exit", "enter"]
    assert {scene["templateId"] for scene in scenes} == {"comic-panel-exit", "comic-panel-enter"}
    for scene in scenes:
        assert scene["sceneId"].startswith("w3d-") and len(scene["sceneId"]) == 16
        assert (tmp_path / "studio" / "world3d-edits" / f"{scene['sceneId']}.json").is_file()
        assert (tmp_path / "studio" / scene["file"]).is_file()
    assert [clip["name"] for clip in reply["result"]["clips"]] == ["comic-panel-exit.mp4", "comic-panel-enter.mp4"]
    stored = json.loads((tmp_path / "studio" / "world3d-edits" / f"{scenes[0]['sceneId']}.json").read_text())
    slots = stored["document"]["slots"]
    ids = [slot["id"] for slot in slots]
    assert ids == ["page", "panel-0", "panel-1", "panel-2", "panel-3", "cutout-0", "cutout-1", "cutout-2", "cutout-3"]
    assert slots[0]["sourceUrl"].startswith("/api/v1/file/comic-page-landscape.png")
    panel = next(slot for slot in slots if slot["id"] == "panel-0")
    cutout = next(slot for slot in slots if slot["id"] == "cutout-0")
    distance = panel["scale"] / math.tan(math.radians(36) / 2)
    factor = (distance - 0.04) / distance
    assert cutout["scale"] == pytest.approx(panel["scale"] * factor)
    assert cutout["position"][2] == pytest.approx(panel["position"][2] + 0.04)
    assert cutout["position"][1] + cutout["scale"] == pytest.approx(panel["position"][1] + panel["scale"])
    assert stored["document"]["duration"] == pytest.approx(1.8)
    assert stored["document"]["camera"]["framing"]["yawArc"] == 8
    assert reply["result"]["warnings"] == []


def test_the_wide_pose_is_shared_and_the_durations_are_parameters(tmp_path):
    reply = _call(tmp_path, _panels(tmp_path), intent="comic-arc", exit_duration=2.2, enter_duration=2.0, hold=0.5)
    exit_doc, enter_doc = _documents(tmp_path, reply["result"]["scenes"])
    assert exit_doc["duration"] == pytest.approx(2.2)
    assert enter_doc["duration"] == pytest.approx(2.0)
    assert exit_doc["camera"]["framing"]["yawArc"] == enter_doc["camera"]["framing"]["yawArc"] == 8
    assert exit_doc["camera"]["framing"]["moveStart"] == 0
    assert 0.5 < exit_doc["camera"]["framing"]["moveEnd"] < 1
    assert 0 < enter_doc["camera"]["framing"]["moveStart"] < 0.5
    exit_eye, exit_look = _endpoint(exit_doc, True)
    enter_eye, enter_look = _endpoint(enter_doc, False)
    assert exit_eye == pytest.approx(enter_eye)
    assert exit_look == pytest.approx(enter_look)
    assert abs(exit_eye[0]) > 0.05


def test_a_hold_that_eats_the_move_is_rejected(tmp_path):
    with pytest.raises(HTTPException) as eaten:
        _call(tmp_path, _panels(tmp_path), intent="comic-hold", hold=1.8)
    assert eaten.value.status_code == 422 and eaten.value.detail["code"] == "invalid_duration"
    assert _written(tmp_path) == []


def test_a_missing_source_and_a_missing_exporter_write_nothing(tmp_path):
    broken = _panels(tmp_path)
    broken[0] = {"video": str(tmp_path / "missing.mp4"), "at": 60}
    with pytest.raises(HTTPException) as missing:
        _call(tmp_path, broken, export=False, intent="comic-missing")
    assert missing.value.status_code == 422 and missing.value.detail["code"] == "missing_source"
    assert _written(tmp_path) == []
    with pytest.raises(HTTPException) as offline:
        _call(tmp_path, _panels(tmp_path), export=True, intent="comic-offline")
    assert offline.value.status_code == 503 and offline.value.detail["code"] == "export_unavailable"
    assert _written(tmp_path) == []


def test_an_empty_cutout_leaves_the_panel_flat_and_warns(tmp_path):
    bind_comic_cutout(lambda _source, _dest: None)
    reply = _call(tmp_path, _panels(tmp_path), export=False, intent="comic-empty")
    assert reply["result"]["warnings"]
    assert all("cutout unavailable" in warning for warning in reply["result"]["warnings"])
    stored = json.loads(next((tmp_path / "studio" / "world3d-edits").glob("*.json")).read_text())
    assert [slot["id"] for slot in stored["document"]["slots"] if slot["id"].startswith("cutout")] == []


def test_two_or_seven_panels_are_rejected(tmp_path):
    with pytest.raises(HTTPException) as few:
        _call(tmp_path, _panels(tmp_path, 3)[:2], intent="comic-two")
    assert few.value.status_code == 422 and few.value.detail["code"] == "panel_count"
    with pytest.raises(HTTPException) as many:
        _call(tmp_path, _panels(tmp_path, 6) + _panels(tmp_path, 1), intent="comic-seven")
    assert many.value.status_code == 422 and many.value.detail["code"] == "panel_count"
    assert _written(tmp_path) == []


def test_five_panels_keep_the_cut_aspect_and_crop_the_rest(tmp_path):
    reply = _call(tmp_path, _panels(tmp_path, 5), intent="comic-five", seed=1, to_panel=4)
    cells = reply["result"]["layout"]["cells"]
    assert [index for index, cell in enumerate(cells) if cell["hero"]] == [0, 4]
    for index, cell in enumerate(cells):
        image = Image.open(tmp_path / "studio" / f"comic-panel-{index}.png")
        assert image.size == ((64, 36) if cell["hero"] else (cell["w"], cell["h"]))
        assert (image.size[0] * 9 == image.size[1] * 16) is bool(cell["hero"])
    stored = json.loads(next((tmp_path / "studio" / "world3d-edits").glob("*.json")).read_text())
    panel = next(slot for slot in stored["document"]["slots"] if slot["id"] == "panel-0")
    assert panel["scale"] == pytest.approx(cells[0]["h"] * 0.00125 / 2)


def test_a_recolored_cutout_keeps_the_picture_on_a_full_size_cut_panel(tmp_path):
    def recolor(source, dest):
        image = Image.open(source).convert("RGBA")
        Image.new("RGBA", image.size, (255, 0, 0, 180)).save(dest)
        return dest

    bind_comic_cutout(recolor)
    reply = _call(tmp_path, _panels(tmp_path, 5), intent="comic-color", seed=1, to_panel=4)
    cells = reply["result"]["layout"]["cells"]
    panel = Image.open(tmp_path / "studio" / "comic-panel-0.png").convert("RGBA")
    cutout = Image.open(tmp_path / "studio" / "comic-cutout-0.png").convert("RGBA")
    filler = Image.open(tmp_path / "studio" / "comic-panel-1.png")
    assert panel.size == (64, 36) and cutout.size == panel.size
    assert cutout.getpixel((4, 4))[:3] == panel.getpixel((4, 4))[:3]
    assert cutout.getpixel((4, 4))[3] == 180
    assert filler.size == (cells[1]["w"], cells[1]["h"]) and filler.size != panel.size


def _movie(tmp_path, name="clip.mp4", seconds=4):
    folder = tmp_path / "studio"
    folder.mkdir(exist_ok=True)
    path = folder / name
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x2244aa:s=64x36:r=30:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={seconds}",
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return name


def _save_montage(tmp_path, file, clips):
    store = MontageStore(lambda workspace: str(tmp_path / workspace))
    return store.save("studio", {
        "version": 1, "name": "Song", "width": 640, "height": 360, "fps": 30,
        "clips": clips, "soundtrack": None,
    }, file=file)


def _montage_call(tmp_path, file, between, **extra):
    return execute_command("scene3d.comic.transition", {
        "version": 1, "intent_id": extra.pop("intent", "comic-montage"),
        "input": {"workspace": "studio", "montage": file, "between": between, **extra},
    }, lambda workspace: str(tmp_path / workspace))


def _span(clips):
    return sum(clip["trimEnd"] - clip["trimStart"] for clip in clips)


def test_insert_at_a_clip_index_keeps_the_first_clip_and_grows(tmp_path):
    """Integer 0 is the boundary after clip 0, not a split at t=0."""
    bind_comic_exporter(_FakeExport())
    _movie(tmp_path)
    _save_montage(tmp_path, "cuts.montage.json", [
        {"id": "a", "name": "A", "source": "clip.mp4", "trimStart": 0, "trimEnd": 2, "transition": "none"},
        {"id": "b", "name": "B", "source": "clip.mp4", "trimStart": 2, "trimEnd": 4, "transition": "none"},
    ])
    reply = _montage_call(tmp_path, "cuts.montage.json", 0, mode="insert", intent="comic-insert")
    saved = json.loads((tmp_path / "studio" / "cuts.montage.json").read_text())
    clips = saved["clips"]
    assert [clip["id"] for clip in clips] == ["a", "comic-exit", "comic-enter", "b"]
    assert clips[0]["trimStart"] == pytest.approx(0)
    assert clips[0]["trimEnd"] == pytest.approx(2)
    assert clips[0]["source"] == "clip.mp4"
    assert clips[3]["trimStart"] == pytest.approx(2)
    assert _span(clips) == pytest.approx(7.6)
    assert saved["revision"] == 2
    assert saved["soundtrack"]["source"] == "clip.mp4"
    assert all(clip["muted"] for clip in clips)
    backup = json.loads((tmp_path / "studio" / "cuts.r1.montage.json").read_text())
    assert backup["revision"] == 1 and len(backup["clips"]) == 2
    assert reply["result"]["montage"] == {"file": "cuts.montage.json", "revision": 2, "backup": "cuts.r1.montage.json"}
    assert [index for index, cell in enumerate(reply["result"]["layout"]["cells"]) if cell["hero"]] == [1, 2]


def test_replace_at_a_time_keeps_the_duration_and_the_previous_revision(tmp_path):
    """Integer 2 is seconds: one clip has no boundary index 2."""
    bind_comic_exporter(_FakeExport())
    _movie(tmp_path)
    _save_montage(tmp_path, "song.montage.json", [
        {"id": "a", "name": "A", "source": "clip.mp4", "trimStart": 0, "trimEnd": 4, "transition": "none"},
    ])
    reply = _montage_call(
        tmp_path, "song.montage.json", 2, mode="replace",
        exit_duration=0.8, enter_duration=0.8, hold=0.2, intent="comic-replace",
    )
    saved = json.loads((tmp_path / "studio" / "song.montage.json").read_text())
    clips = saved["clips"]
    assert [clip["id"] for clip in clips] == ["a", "comic-exit", "comic-enter", "a-next"]
    assert clips[0]["trimEnd"] == pytest.approx(1.2)
    assert clips[3]["trimStart"] == pytest.approx(2.8)
    assert clips[3]["trimEnd"] == pytest.approx(4)
    assert clips[1]["trimEnd"] == pytest.approx(0.8)
    assert clips[2]["trimEnd"] == pytest.approx(0.8)
    assert _span(clips) == pytest.approx(4)
    assert all(clip["muted"] for clip in clips)
    assert saved["soundtrack"]["source"] == "clip.mp4"
    assert saved["soundtrack"]["trimStart"] == pytest.approx(0)
    assert saved["soundtrack"]["trimEnd"] == pytest.approx(4)
    assert saved["revision"] == 2
    backup = json.loads((tmp_path / "studio" / "song.r1.montage.json").read_text())
    assert backup["revision"] == 1 and len(backup["clips"]) == 1
    assert reply["result"]["montage"]["backup"] == "song.r1.montage.json"
    props = next(item for item in command_catalog() if item["name"] == "scene3d.comic.transition")
    fields = props["inputSchema"]["properties"]["input"]
    assert fields["required"] == ["workspace"]
    assert "montage" in fields["properties"] and "between" in fields["properties"]


def test_replace_too_close_to_the_start_writes_no_revision(tmp_path):
    _save_montage(tmp_path, "song.montage.json", [
        {"id": "a", "name": "A", "source": "clip.mp4", "trimStart": 0, "trimEnd": 4, "transition": "none"},
    ])
    with pytest.raises(HTTPException) as tight:
        _montage_call(
            tmp_path, "song.montage.json", 0.1, mode="replace",
            exit_duration=0.8, enter_duration=0.8, hold=0.2, intent="comic-tight",
        )
    assert tight.value.status_code == 422 and tight.value.detail["code"] == "clip_too_short"
    live = json.loads((tmp_path / "studio" / "song.montage.json").read_text())
    assert live["revision"] == 1 and len(live["clips"]) == 1
    assert not (tmp_path / "studio" / "song.r1.montage.json").exists()


def test_a_montage_document_is_saved_only_after_the_clips_exist(tmp_path):
    bind_comic_exporter(_FakeExport())
    _movie(tmp_path)
    document = {
        "version": 1, "name": "Song", "width": 640, "height": 360, "fps": 30, "soundtrack": None,
        "clips": [{"id": "a", "name": "A", "source": "clip.mp4", "trimStart": 0, "trimEnd": 4, "transition": "none"}],
    }
    reply = _montage_call(tmp_path, document, 2, mode="replace", exit_duration=0.8, enter_duration=0.8, hold=0.2, intent="comic-inline")
    saved = json.loads((tmp_path / "studio" / "Song.montage.json").read_text())
    assert saved["revision"] == 2
    assert reply["result"]["montage"]["backup"] == "Song.r1.montage.json"
    assert json.loads((tmp_path / "studio" / "Song.r1.montage.json").read_text())["revision"] == 1
