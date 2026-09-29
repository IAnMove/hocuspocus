"""Code review for production.status: bars, freeze, titles, duplicate people.

The Omarchy sheets are optional. CI skips them when the output tree is absent.
Protagonist identity is unknown unless a test injects an embedding callable.
These tests do not download weights.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from services.music_production import status_summary
from services.production_review import review_production
from services.production_review_checks import has_bar


OMARCHY = Path("/mnt/extras/hocuspocus-worktrees/claude-pop/app/outputs/omarchy-anthem-20260928")
WEIGHTS = Path("/mnt/extras/pinokio/api/hocuspocus-development/app/ckpts/pose/yolox_l.onnx")


def _state(key: str = "hero", *, kind: str = "h3", cast: list | None = None, held: bool = False, final: str | None = None) -> dict:
    shot: dict = {"key": key, "kind": kind}
    if cast is not None:
        shot["cast"] = cast
    scene: dict = {"file": f"{key}.mp4"}
    if held:
        scene["held"] = True
    state: dict = {
        "spec": {"shots": [shot]},
        "scenes": {key: scene},
        "segments": [[key, 0.0, 2.0]],
    }
    if final:
        state["final"] = final
    return state


def _touch(root: Path, name: str, scene: dict | None = None) -> None:
    (root / name).write_bytes(b"not-a-decoded-video")
    if scene is None:
        return
    meta = {"generation": {"parameters": {"scene": scene}}}
    (root / f"{Path(name).stem}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _color(full: np.ndarray) -> np.ndarray:
    return np.dstack([full, full, full])


def _clip(grays: list[np.ndarray], full: np.ndarray) -> dict:
    return {
        "gray": grays,
        "full_gray": full,
        "color": _color(full),
        "width": int(full.shape[1]),
        "height": int(full.shape[0]),
    }


def _moving(full: np.ndarray | None = None) -> dict:
    if full is None:
        full = np.full((180, 320), 128, np.uint8)
    dark = np.full((90, 160), 20, np.uint8)
    bright = np.full((90, 160), 200, np.uint8)
    return _clip([dark, bright, dark, bright], full)


def _still_frames() -> dict:
    gray = np.full((90, 160), 40, np.uint8)
    full = np.full((180, 320), 90, np.uint8)
    return _clip([gray, gray.copy(), gray.copy()], full)


def _letterbox() -> np.ndarray:
    full = np.full((180, 320), 180, np.uint8)
    full[:30, :] = 0
    full[-30:, :] = 0
    return full


def _sample(clips: dict[str, dict]):
    def read(path: str) -> dict:
        return clips[Path(path).name]

    return read


def _video_scene(layers: list[dict] | None = None, texts: list | None = None) -> dict:
    return {
        "width": 1920,
        "height": 1080,
        "duration": 2,
        "layers": layers or [{"id": "bg", "type": "video"}],
        "texts": texts or [],
    }


def test_letterbox_is_a_bar_and_a_thin_or_black_frame_is_not():
    assert has_bar(_letterbox())
    assert not has_bar(np.full((180, 320), 180, np.uint8))
    assert not has_bar(np.zeros((180, 320), np.uint8))
    thin = np.full((180, 320), 180, np.uint8)
    thin[:8, :] = 0
    assert not has_bar(thin)
    pillar = np.full((180, 320), 180, np.uint8)
    pillar[:, :40] = 0
    pillar[:, -40:] = 0
    assert has_bar(pillar)


def test_frozen_synthetic_clip_retakes_and_a_moving_one_is_ok(tmp_path):
    _touch(tmp_path, "hero.mp4")
    frozen = review_production(
        _state(), str(tmp_path), people=None, sample=_sample({"hero.mp4": _still_frames()}),
    )
    moving = review_production(
        _state(), str(tmp_path), people=None, sample=_sample({"hero.mp4": _moving()}),
    )
    assert frozen["review"]["verdict"] == "retake"
    assert frozen["retake_keys"] == ["hero"]
    assert frozen["review"]["failures"] == [{"key": "hero", "question": "frozen_shot"}]
    assert moving["review"]["verdict"] == "ok"
    assert moving["retake_keys"] == []
    assert moving["review"]["failures"] == []
    assert moving["review"]["unknown"] == ["face_consistent"]
    assert "yes" not in json.dumps(moving["review"]["unknown"])
    assert "no" not in json.dumps(moving["review"]["failures"])


def test_black_bars_on_a_scene_are_a_retake_key(tmp_path):
    _touch(tmp_path, "hero.mp4")
    result = review_production(
        _state(), str(tmp_path), people=None, sample=_sample({"hero.mp4": _moving(_letterbox())}),
    )
    assert result["review"]["verdict"] == "retake"
    assert result["retake_keys"] == ["hero"]
    assert {"key": "hero", "question": "black_bars"} in result["review"]["failures"]


def test_held_h3_still_retakes_even_when_the_pixels_move(tmp_path):
    scene = _video_scene([{"id": "bg", "type": "image"}])
    _touch(tmp_path, "hero.mp4", scene)
    result = review_production(
        _state(), str(tmp_path), people=None, sample=_sample({"hero.mp4": _moving()}),
    )
    assert result["review"]["failures"] == [{"key": "hero", "question": "frozen_shot"}]
    assert result["retake_keys"] == ["hero"]


def test_title_outside_the_frame_retakes_without_a_detector(tmp_path):
    scene = _video_scene(texts=[{
        "text": "CUT OFF", "x": 50, "y": 0, "size": 25, "start": 0, "end": 2,
    }])
    _touch(tmp_path, "hero.mp4", scene)
    result = review_production(
        _state(), str(tmp_path), people=None, sample=_sample({"hero.mp4": _moving()}),
    )
    assert result["review"]["verdict"] == "retake"
    assert {"key": "hero", "question": "title_cut_off"} in result["review"]["failures"]
    assert all(item["question"] != "text_covers_face" for item in result["review"]["failures"])


def test_title_over_a_face_retakes_and_a_short_box_does_not(tmp_path):
    scene = _video_scene(texts=[{
        "text": "NAME", "x": 50, "y": 30, "size": 12, "start": 0, "end": 2,
    }])
    _touch(tmp_path, "hero.mp4", scene)
    tall = lambda _image: [[40, 0, 280, 170]]
    short = lambda _image: [[80, 150, 240, 175]]
    covered = review_production(
        _state(cast=["hero"]), str(tmp_path), people=tall, sample=_sample({"hero.mp4": _moving()}),
    )
    ignored = review_production(
        _state(cast=["hero"]), str(tmp_path), people=short, sample=_sample({"hero.mp4": _moving()}),
    )
    assert {"key": "hero", "question": "text_covers_face"} in covered["review"]["failures"]
    assert covered["retake_keys"] == ["hero"]
    assert ignored["review"]["failures"] == []
    assert ignored["review"]["verdict"] == "ok"


def test_more_people_than_the_cast_retakes(tmp_path):
    _touch(tmp_path, "hero.mp4", _video_scene())
    def people(_image):
        return [[0, 0, 40, 160], [80, 0, 120, 160], [160, 0, 200, 160]]

    result = review_production(
        _state(cast=["hero"]), str(tmp_path), people=people, sample=_sample({"hero.mp4": _moving()}),
    )
    assert result["review"]["failures"] == [{"key": "hero", "question": "duplicate_people"}]
    assert result["retake_keys"] == ["hero"]


def test_identity_stays_unknown_unless_an_embedding_backend_is_injected(tmp_path):
    _touch(tmp_path, "hero.mp4")
    sample = _sample({"hero.mp4": _moving()})
    unknown = review_production(_state(), str(tmp_path), people=None, sample=sample)
    same = review_production(_state(), str(tmp_path), people=None, embed=lambda _samples: "no", sample=sample)
    changed = review_production(_state(), str(tmp_path), people=None, embed=lambda _samples: "yes", sample=sample)
    junk = review_production(_state(), str(tmp_path), people=None, embed=lambda _samples: "maybe", sample=sample)
    assert unknown["review"]["verdict"] == "ok"
    assert unknown["review"]["unknown"] == ["face_consistent"]
    assert unknown["retake_keys"] == []
    assert same["review"]["unknown"] == []
    assert same["review"]["verdict"] == "ok"
    assert changed["review"]["verdict"] == "retake"
    assert changed["retake_keys"] == ["hero"]
    assert {"key": "hero", "question": "face_consistent"} in changed["review"]["failures"]
    assert changed["review"]["unknown"] == []
    assert junk["review"]["verdict"] == "ok"
    assert junk["review"]["unknown"] == ["face_consistent"]
    assert junk["retake_keys"] == []


def test_status_summary_retake_keys_are_passable_and_small(tmp_path):
    summary = status_summary(_state(held=True), "ws", str(tmp_path))
    assert summary["review"]["verdict"] == "retake"
    assert summary["retake_keys"] == ["hero"]
    assert summary["review"]["failures"] == [{"key": "hero", "question": "frozen_shot"}]
    assert all(isinstance(key, str) for key in summary["retake_keys"])
    raw = json.dumps(summary)
    assert len(raw) < 4000
    assert "full_gray" not in raw


def test_missing_media_is_unreliable_and_does_not_invent_a_retake():
    result = review_production({"status": "running"}, None, people=None)
    assert result["review"]["verdict"] == "unreliable"
    assert result["review"]["failures"] == []
    assert result["retake_keys"] == []
    assert result["review"]["unknown"] == ["face_consistent"]


def _people_detector():
    if not WEIGHTS.is_file():
        return None
    from services.qa_people import open_detector, people_boxes

    session = open_detector(str(WEIGHTS))

    def detect(image):
        return people_boxes(session, image)

    return detect


def _omarchy_versions() -> tuple[dict | None, dict | None, str]:
    production = OMARCHY / "love-your-computer-20260928.production.json"
    if not production.is_file():
        return None, None, "production json missing"
    saved = json.loads(production.read_text(encoding="utf-8"))
    grouped: dict[str, list[dict]] = {}
    for meta in OMARCHY.glob("*video2d*.meta.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        scene = ((data.get("generation") or {}).get("parameters") or {}).get("scene") or {}
        name = scene.get("name")
        video = OMARCHY / meta.name.replace(".meta.json", ".mp4")
        if not isinstance(name, str) or not video.is_file():
            continue
        layers = [layer for layer in scene.get("layers") or [] if isinstance(layer, dict)]
        types = {layer.get("type") for layer in layers}
        grouped.setdefault(name, []).append({
            "file": video.name,
            "hold": "video" not in types and "image" in types,
        })
    held = [item for item in grouped.get("chorus_one") or [] if item["hold"]]
    finals = sorted(path.name for path in OMARCHY.glob("*Love_Your_Computer.mp4"))
    others = [name for name in finals if name != saved.get("final")]
    if not held or not others:
        return None, saved, "could not tell v1 from v2"
    earlier = json.loads(json.dumps(saved))
    for key, scene in earlier.get("scenes", {}).items():
        options = grouped.get(key) or []
        holds = [item for item in options if item["hold"] and item["file"] != scene.get("file")]
        previous = [item for item in options if item["file"] != scene.get("file")]
        if holds:
            scene["file"] = holds[0]["file"]
        elif previous:
            scene["file"] = sorted(previous, key=lambda item: item["file"])[0]["file"]
    earlier["final"] = others[0]
    if earlier["scenes"]["chorus_one"]["file"] == saved["scenes"]["chorus_one"]["file"]:
        return None, saved, "could not tell v1 from v2"
    return earlier, saved, ""


@pytest.mark.skipif(not OMARCHY.is_dir(), reason="Omarchy sheets are not in this checkout")
def test_omarchy_v1_retakes_the_held_chorus_and_v2_is_ok():
    earlier, saved, reason = _omarchy_versions()
    if earlier is None:
        pytest.skip(reason)
    people = _people_detector()
    first = review_production(earlier, str(OMARCHY), people=people)
    second = review_production(saved, str(OMARCHY), people=people)
    print("OMARCHY_V1", json.dumps({"verdict": first["review"]["verdict"], "failures": first["review"]["failures"], "retake_keys": first["retake_keys"], "unknown": first["review"]["unknown"]}))
    print("OMARCHY_V2", json.dumps({"verdict": second["review"]["verdict"], "failures": second["review"]["failures"], "retake_keys": second["retake_keys"], "unknown": second["review"]["unknown"], "people": people is not None}))
    assert first["review"]["verdict"] == "retake", first
    assert "chorus_one" in first["retake_keys"]
    assert second["review"]["verdict"] == "ok", second
    assert second["retake_keys"] == []
    summary = status_summary(saved, "omarchy-anthem-20260928", str(OMARCHY))
    assert summary["review"]["verdict"] == "ok"
    assert summary["retake_keys"] == []
    assert len(json.dumps(summary["review"])) < 4000
