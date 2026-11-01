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


def _panels(tmp_path, count=4, cutout=False, tint=0):
    folder = tmp_path / "sources"
    folder.mkdir(exist_ok=True)
    panels = []
    for index in range(count):
        path = folder / f"frame-{index}.png"
        Image.new("RGB", (64, 36), (40 + index * 30, 80, min(255, 120 + tint))).save(path)
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


def _panel_url(tmp_path, scene_id: str, slot_id: str) -> str:
    stored = json.loads((tmp_path / "studio" / "world3d-edits" / f"{scene_id}.json").read_text())
    slot = next(item for item in stored["document"]["slots"] if item["id"] == slot_id)
    return slot["sourceUrl"]


def _file_of(url: str) -> str:
    return url.split("/api/v1/file/", 1)[1].split("?", 1)[0]


def _comic_token(url: str) -> str:
    body = _file_of(url).removeprefix("comic-")
    for marker in ("-page-", "-desk-", "-panel-", "-print-", "-cutout-", "-live-", "-shadow-"):
        if marker in body:
            return body.split(marker, 1)[0]
    raise AssertionError(url)


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
    reply = _call(tmp_path, _panels(tmp_path, cutout=True), export=True, paper=False)
    assert reply["status"] == "completed"
    scenes = reply["result"]["scenes"]
    assert [scene["role"] for scene in scenes] == ["exit", "enter"]
    assert {scene["templateId"] for scene in scenes} == {"comic-panel-exit", "comic-panel-enter"}
    for scene in scenes:
        assert scene["sceneId"].startswith("w3d-") and len(scene["sceneId"]) == 16
        assert (tmp_path / "studio" / "world3d-edits" / f"{scene['sceneId']}.json").is_file()
        assert (tmp_path / "studio" / scene["file"]).is_file()
    stored = json.loads((tmp_path / "studio" / "world3d-edits" / f"{scenes[0]['sceneId']}.json").read_text())
    slots = stored["document"]["slots"]
    ids = [slot["id"] for slot in slots]
    assert ids == ["page", "panel-0", "panel-1", "panel-2", "panel-3", "cutout-0", "cutout-1", "cutout-2", "cutout-3"]
    page_url = slots[0]["sourceUrl"]
    token = _comic_token(page_url)
    assert page_url.startswith(f"/api/v1/file/comic-{token}-page-landscape.png")
    assert [clip["name"] for clip in reply["result"]["clips"]] == [f"comic-{token}-exit.mp4", f"comic-{token}-enter.mp4"]
    assert (tmp_path / "studio" / f"comic-{token}-panel-0.png").is_file()
    assert (tmp_path / "studio" / f"comic-{token}-cutout-1.png").is_file()
    panel = next(slot for slot in slots if slot["id"] == "panel-0")
    cutout = next(slot for slot in slots if slot["id"] == "cutout-0")
    distance = panel["scale"] / math.tan(math.radians(36) / 2)
    factor = (distance - 0.108) / distance
    assert cutout["scale"] == pytest.approx(panel["scale"] * factor)
    assert cutout["position"][2] == pytest.approx(panel["position"][2] + 0.108)
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


def test_a_second_transition_keeps_the_first_scene_pictures(tmp_path):
    first = _call(tmp_path, _panels(tmp_path, tint=0), intent="comic-first", paper=False)
    first_id = first["result"]["scenes"][0]["sceneId"]
    first_panel = _file_of(_panel_url(tmp_path, first_id, "panel-0"))
    first_bytes = (tmp_path / "studio" / first_panel).read_bytes()
    second = _call(tmp_path, _panels(tmp_path, tint=40), intent="comic-second", paper=False)
    second_id = second["result"]["scenes"][0]["sceneId"]
    second_panel = _file_of(_panel_url(tmp_path, second_id, "panel-0"))
    assert first_panel != second_panel
    assert (tmp_path / "studio" / first_panel).read_bytes() == first_bytes
    assert (tmp_path / "studio" / first_panel).read_bytes() != (tmp_path / "studio" / second_panel).read_bytes()
    assert _panel_url(tmp_path, first_id, "panel-0") == f"/api/v1/file/{first_panel}?workspace=studio"


def test_five_panels_keep_the_cut_aspect_and_crop_the_rest(tmp_path):
    reply = _call(tmp_path, _panels(tmp_path, 5), intent="comic-five", seed=1, to_panel=4)
    cells = reply["result"]["layout"]["cells"]
    token = _comic_token(_panel_url(tmp_path, reply["result"]["scenes"][0]["sceneId"], "panel-0"))
    assert [index for index, cell in enumerate(cells) if cell["hero"]] == [0, 4]
    for index, cell in enumerate(cells):
        image = Image.open(tmp_path / "studio" / f"comic-{token}-panel-{index}.png")
        assert image.size == ((64, 36) if cell["hero"] else (cell["w"], cell["h"]))
        assert (image.size[0] * 9 == image.size[1] * 16) is bool(cell["hero"])
    stored = json.loads(next((tmp_path / "studio" / "world3d-edits").glob("*.json")).read_text())
    panel = next(slot for slot in stored["document"]["slots"] if slot["id"] == "panel-0")
    assert panel["scale"] == pytest.approx(cells[0]["h"] * 0.00125 / 2)


def test_a_recolored_cutout_keeps_the_picture_on_a_full_size_cut_panel(tmp_path):
    def recolor(source, dest):
        image = Image.open(source).convert("RGBA")
        Image.new("RGBA", image.size, (255, 0, 0, 255)).save(dest)
        return dest

    bind_comic_cutout(recolor)
    reply = _call(tmp_path, _panels(tmp_path, 5), intent="comic-color", seed=1, to_panel=4)
    cells = reply["result"]["layout"]["cells"]
    token = _comic_token(_panel_url(tmp_path, reply["result"]["scenes"][0]["sceneId"], "panel-0"))
    panel = Image.open(tmp_path / "studio" / f"comic-{token}-panel-0.png").convert("RGBA")
    cutout = Image.open(tmp_path / "studio" / f"comic-{token}-cutout-0.png").convert("RGBA")
    filler = Image.open(tmp_path / "studio" / f"comic-{token}-panel-1.png")
    assert panel.size == (64, 36) and cutout.size == panel.size
    assert cutout.getpixel((4, 4))[:3] == (40, 80, 120)
    assert cutout.getpixel((4, 4))[3] == 255
    assert cutout.getpixel((0, 0))[3] == 0
    assert filler.size == (cells[1]["w"], cells[1]["h"]) and filler.size != panel.size


def test_a_sticker_leaves_no_subject_in_the_base_outside_the_ring(tmp_path):
    """Soft U2Net values, a hole and a second figure are one sticker. A speck stays put."""
    import numpy as np

    from services.scene3d_comic_cutout import finish_cutout

    height, width = 120, 160
    rgb = np.zeros((height, width, 3), np.uint8)
    rgb[..., 0] = np.arange(width, dtype=np.uint8)[None, :]
    rgb[..., 1] = np.arange(height, dtype=np.uint8)[:, None]
    rgb[..., 2] = 40
    subject = (255, 0, 128)
    alpha = np.zeros((height, width), np.uint8)
    alpha[40:80, 50:110] = 255
    rgb[40:80, 50:110] = subject
    alpha[55:65, 70:90] = 0
    alpha[40:80, 48:50] = 100
    rgb[40:80, 48:50] = subject
    alpha[40:80, 110:112] = 90
    rgb[40:80, 110:112] = subject
    alpha[90:110, 120:140] = 200
    rgb[90:110, 120:140] = subject
    alpha[2:6, 2:6] = 255
    rgb[2:6, 2:6] = (0, 0, 255)
    original = np.dstack([rgb, np.full((height, width), 255, np.uint8)])
    picture = tmp_path / "panel.png"
    cutout = tmp_path / "cut.png"
    Image.fromarray(original).save(picture)
    Image.fromarray(np.dstack([rgb, alpha])).save(cutout)
    finish_cutout(picture, cutout)
    base = np.asarray(Image.open(picture).convert("RGBA"))
    matte = np.asarray(Image.open(cutout).convert("RGBA"))
    assert np.array_equal(matte[..., :3], original[..., :3])
    assert matte[60, 80, 3] == 255 and matte[60, 75, 3] == 255
    assert matte[100, 130, 3] == 255
    assert matte[4, 4, 3] == 0 and tuple(base[4, 4, :3]) == (0, 0, 255)
    assert tuple(base[0, 0]) == tuple(original[0, 0])
    painted = (base[..., 0] == 255) & (base[..., 1] == 0) & (base[..., 2] == 128)
    assert not painted.any()
    solid = (matte[..., 3] == 0) | (matte[..., 3] == 255)
    weight = matte[..., 3:4].astype(np.float64) / 255.0
    composite = weight * original[..., :3] + (1.0 - weight) * base[..., :3]
    assert np.array_equal(np.rint(composite[solid]), original[..., :3][solid])
    partial = np.argwhere((matte[..., 3] > 0) & (matte[..., 3] < 255))
    assert len(partial) > 0
    opaque = matte[..., 3] == 255
    clear = matte[..., 3] == 0
    for y, x in partial:
        y0, y1 = max(0, y - 2), min(height, y + 3)
        x0, x1 = max(0, x - 2), min(width, x + 3)
        assert opaque[y0:y1, x0:x1].any() and clear[y0:y1, x0:x1].any()


def test_a_small_head_next_to_its_body_travels_with_the_sticker(tmp_path):
    """A small figure splits at the neck when the matte is binarized. The head must not stay in the base."""
    import numpy as np

    from services.scene3d_comic_cutout import finish_cutout

    height, width = 200, 320
    rgb = np.full((height, width, 3), 60, np.uint8)
    alpha = np.zeros((height, width), np.uint8)
    head = (200, 150, 100)
    alpha[100:160, 130:190] = 255
    rgb[100:160, 130:190] = (180, 120, 40)
    alpha[90:98, 154:162] = 255
    rgb[90:98, 154:162] = head
    original = np.dstack([rgb, np.full((height, width), 255, np.uint8)])
    picture = tmp_path / "panel.png"
    cutout = tmp_path / "cut.png"
    Image.fromarray(original).save(picture)
    Image.fromarray(np.dstack([rgb, alpha])).save(cutout)
    finish_cutout(picture, cutout)
    base = np.asarray(Image.open(picture).convert("RGBA"))
    matte = np.asarray(Image.open(cutout).convert("RGBA"))
    assert matte[94, 158, 3] == 255
    assert not ((base[..., 0] == 200) & (base[..., 1] == 150) & (base[..., 2] == 100)).any()


def test_an_uncertain_matte_raises_and_leaves_both_files_alone(tmp_path):
    """A busy scene where U2Net mostly guesses must stay flat, not smear the base."""
    import numpy as np
    import pytest

    from services.scene3d_comic_cutout import finish_cutout

    height, width = 60, 80
    rgb = np.full((height, width, 3), 90, np.uint8)
    alpha = np.zeros((height, width), np.uint8)
    alpha[10:50, 10:70] = 120
    alpha[25:35, 35:45] = 255
    picture = tmp_path / "panel.png"
    cutout = tmp_path / "cut.png"
    Image.fromarray(np.dstack([rgb, np.full((height, width), 255, np.uint8)])).save(picture)
    Image.fromarray(np.dstack([rgb, alpha])).save(cutout)
    before = (picture.read_bytes(), cutout.read_bytes())
    with pytest.raises(ValueError, match="uncertain matte"):
        finish_cutout(picture, cutout)
    assert (picture.read_bytes(), cutout.read_bytes()) == before


def test_a_tiny_subject_stays_flat(tmp_path):
    import numpy as np
    import pytest

    from services.scene3d_comic_cutout import finish_cutout

    height, width = 100, 200
    rgb = np.full((height, width, 3), 70, np.uint8)
    alpha = np.zeros((height, width), np.uint8)
    alpha[40:60, 90:110] = 255
    picture = tmp_path / "panel.png"
    cutout = tmp_path / "cut.png"
    Image.fromarray(np.dstack([rgb, np.full((height, width), 255, np.uint8)])).save(picture)
    Image.fromarray(np.dstack([rgb, alpha])).save(cutout)
    with pytest.raises(ValueError, match="subject too small"):
        finish_cutout(picture, cutout)


def test_a_full_matte_fades_over_the_outer_three_percent(tmp_path):
    import numpy as np

    from services.scene3d_comic_cutout import finish_cutout

    height, width = 60, 80
    rgb = np.zeros((height, width, 3), np.uint8)
    rgb[..., 0] = 20
    rgb[..., 1] = np.arange(width, dtype=np.uint8)[None, :]
    original = np.dstack([rgb, np.full((height, width), 255, np.uint8)])
    picture = tmp_path / "panel.png"
    cutout = tmp_path / "cut.png"
    Image.fromarray(original).save(picture)
    Image.fromarray(original).save(cutout)
    finish_cutout(picture, cutout)
    base = np.asarray(Image.open(picture).convert("RGBA"))
    matte = np.asarray(Image.open(cutout).convert("RGBA"))
    assert matte[0, 0, 3] == 0
    assert matte[height // 2, width // 2, 3] == 255
    assert 0 < int(matte[height // 2, 1, 3]) < 255
    assert np.array_equal(base[0, 0], original[0, 0])
    assert np.array_equal(base[height // 2, 1], original[height // 2, 1])


def test_a_failed_inpaint_leaves_the_panel_flat_and_warns(tmp_path, monkeypatch):
    import cv2

    def _boom(*_args, **_kwargs):
        raise RuntimeError("inpaint broke")

    monkeypatch.setattr(cv2, "inpaint", _boom)
    reply = _call(tmp_path, _panels(tmp_path), export=False, intent="comic-inpaint")
    assert reply["result"]["warnings"]
    assert all("inpaint broke" in warning for warning in reply["result"]["warnings"])
    stored = json.loads(next((tmp_path / "studio" / "world3d-edits").glob("*.json")).read_text())
    assert [slot["id"] for slot in stored["document"]["slots"] if slot["id"].startswith("cutout")] == []


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
    assert saved.get("soundtrack") is None
    assert not clips[0].get("muted") and not clips[3].get("muted")
    assert clips[1]["muted"] and clips[2]["muted"]
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


def test_a_printed_twin_keeps_the_size_and_alpha_and_looks_printed(tmp_path):
    import numpy as np

    from services.scene3d_comic_paper import print_picture

    source = tmp_path / "panel.png"
    picture = np.zeros((90, 160, 4), np.uint8)
    picture[..., 0] = np.linspace(0, 255, 160, dtype=np.uint8)[None, :]
    picture[..., 1] = 90
    picture[..., 3] = 255
    Image.fromarray(picture).save(source)
    print_picture(source, tmp_path / "print.png", 3, (0, 0, 160, 90, 320, 180))
    printed = np.asarray(Image.open(tmp_path / "print.png").convert("RGBA"))
    assert printed.shape == picture.shape
    assert (printed[..., 3] == 255).all()
    assert tuple(printed[0, 80, :3]) == (20, 17, 16), "an ink line runs inside the edge"
    assert np.abs(printed[..., :3].astype(int) - picture[..., :3]).mean() > 4


def test_a_printed_sticker_gets_a_white_die_cut_edge(tmp_path):
    import numpy as np

    from services.scene3d_comic_paper import print_sticker, sticker_shadow

    sticker = np.zeros((80, 120, 4), np.uint8)
    sticker[20:60, 40:80] = (30, 60, 200, 255)
    Image.fromarray(sticker).save(tmp_path / "sticker.png")
    print_sticker(tmp_path / "sticker.png", tmp_path / "printed.png", 5)
    sticker_shadow(tmp_path / "sticker.png", tmp_path / "shadow.png")
    printed = np.asarray(Image.open(tmp_path / "printed.png").convert("RGBA"))
    shadow = np.asarray(Image.open(tmp_path / "shadow.png").convert("RGBA"))
    assert printed[40, 38, 3] > 200 and printed[40, 38, :3].mean() > 180, "white paper just outside the figure"
    assert printed[5, 5, 3] == 0
    assert shadow[..., 3].max() > 0 and shadow[62, 82, 3] > shadow[18, 38, 3], "the lamp throws it down and right"


def _dressed_documents(tmp_path, panels, **extra):
    bind_comic_exporter(_FakeExport())
    reply = _call(tmp_path, panels, export=False, from_panel=1, to_panel=3, **extra)
    assert reply["status"] == "completed", reply
    return reply["result"], _documents(tmp_path, reply["result"]["scenes"])


def test_paper_prints_the_fillers_and_fades_the_cut_panels(tmp_path):
    result, (exit_doc, enter_doc) = _dressed_documents(tmp_path, _panels(tmp_path, cutout=True))
    exit_slots = {slot["id"]: slot for slot in exit_doc["slots"]}
    enter_slots = {slot["id"]: slot for slot in enter_doc["slots"]}
    assert exit_doc["slots"][0]["id"] == "desk" and exit_doc["environment"]["floorStyle"] == "none"
    assert "-print-0.png" in exit_slots["panel-0"]["sourceUrl"]
    assert "-panel-1.png" in exit_slots["panel-1"]["sourceUrl"]
    assert _comic_token(exit_slots["panel-0"]["sourceUrl"]) == _comic_token(exit_slots["panel-1"]["sourceUrl"])
    leaving = exit_slots["print-1"]["imageLook"]["fade"]
    assert leaving["from"] == 0 and leaving["to"] == 1 and leaving["end"] < exit_doc["duration"]
    assert exit_slots["print-cutout-1"]["imageLook"]["fade"] == leaving and exit_slots["shadow-1"]["imageLook"]["fade"] == leaving
    assert "fade" not in exit_slots["print-3"]["imageLook"] and "fade" not in enter_slots["print-1"]["imageLook"]
    arriving = enter_slots["print-3"]["imageLook"]["fade"]
    assert arriving["from"] == 1 and arriving["to"] == 0 and arriving["start"] > 0
    assert "screen" not in enter_slots["panel-3"], "a still picture does not play"
    assert result["warnings"] == []


def test_a_video_panel_plays_its_own_frames_up_to_the_cut(tmp_path):
    clip = _movie(tmp_path, seconds=4)
    panels = [{"video": clip, "at": at} for at in (0.5, 1.0, 1.5, 3.5)]
    _result, (exit_doc, enter_doc) = _dressed_documents(tmp_path, panels)
    screen = next(slot for slot in enter_doc["slots"] if slot["id"] == "panel-3")["screen"]
    assert screen["media"] == "video" and screen["loop"] is False and screen["lines"] == 120  # 36 rows, raised to the parser floor
    assert "-live-3.mp4" in screen["sourceUrl"]
    assert "screen" not in next(slot for slot in exit_doc["slots"] if slot["id"] == "panel-3")
    live = tmp_path / "studio" / _file_of(screen["sourceUrl"])
    frames = int(subprocess.check_output(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(live)],
    ).strip())
    assert frames >= round(enter_doc["duration"] * 30)
    assert not any(slot["id"] in {"cutout-3", "print-cutout-3", "shadow-3"} for slot in enter_doc["slots"])
    _flat, (_plain_exit, plain_enter) = _dressed_documents(tmp_path, panels, intent="comic-still", live_enter=False)
    assert "screen" not in next(slot for slot in plain_enter["slots"] if slot["id"] == "panel-3")
