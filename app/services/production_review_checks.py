"""Deterministic checks for one music-video production.

Black bars, a held or frozen scene, a title outside the frame or over a face,
and more people than the shot's cast. No weights are downloaded. The people
detector and the protagonist embedding are optional callers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np

# Ken Burns stills on the Omarchy sheet move by about 18. Only a near-zero
# clip is frozen; a held H3 start frame is an image layer, not this threshold.
FROZEN_MEAN = 2.0
# A real letterbox or pillarbox is a thick black edge, not a vignette or a dark wall.
BAR_FRACTION = 0.08
BAR_MAX = 16
BAR_MEAN = 10.0
# qa.people boxes are people. The face is the top of a tall box; a short box is a hand or a plate.
FACE_TOP = 0.4
MIN_PERSON = 0.20
_OUTSIDE = 0.05
_SAMPLES = 4


def run_review(
    state: Any,
    root: str | None,
    *,
    people: Callable[..., Any] | None,
    embed: Callable[..., Any] | None,
    sample: Callable[[str], Any] | None,
) -> dict[str, Any]:
    jobs = collect_jobs(state, root)
    if jobs is None:
        pending = empty_review()
        from services.production_review_layers import artistic_verdict

        pending["review"]["artistic"]["verdict"] = artistic_verdict(state, root)
        return pending
    reader = sample_clip if sample is None else sample
    clips = [_safe_sample(reader, job.get("path")) for job in jobs]
    failures: list[dict[str, str]] = []
    evaluated = False
    for job, clip in zip(jobs, clips):
        if clip is not None or job.get("document") is not None or job.get("held"):
            evaluated = True
        failures.extend(scene_failures(job, clip, people))
    saw_final, final_keys = final_bars(state, root)
    evaluated = evaluated or saw_final
    failures.extend(_final_bar_failures(jobs, final_keys))
    identity = identity_value(embed, _samples(jobs, clips))
    if identity in {"yes", "no"}:
        evaluated = True
    failures.extend(identity_failures(identity, jobs))
    from services.production_review_layers import apply

    return apply(pack(failures, jobs, identity, evaluated), state, _execution(state, root, reader), root)


def empty_review() -> dict[str, Any]:
    from services.production_review_layers import pending_review

    return pending_review()


def collect_jobs(state: Any, root: str | None) -> list[dict[str, Any]] | None:
    if not isinstance(state, dict) or not isinstance(root, str) or not root:
        return None
    base = Path(root)
    if not base.is_dir():
        return None
    shots = _shots(state)
    counts = _cast_counts(state)
    return [_job(base, key, _scene_row(state, key), shots.get(key), counts) for key in _scene_order(state)]


def scene_failures(job: dict, clip: Any, people: Callable[..., Any] | None) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    key = job["key"]
    if (job.get("held") or frozen_clip(clip)) and _report(job, "frozen_shot"):
        found.append(_fail(key, "frozen_shot"))
    if isinstance(clip, dict) and has_bar(clip.get("full_gray")) and _report(job, "black_bars"):
        found.append(_fail(key, "black_bars"))
    boxes = detect_boxes(clip, people)
    found.extend(title_failures(key, job.get("document"), boxes))
    found.extend(duplicate_failures(key, job.get("expected"), boxes))
    return [item for item in found if _report(job, item["question"])]


def title_failures(key: str, document: Any, boxes: list | None) -> list[dict[str, str]]:
    if not isinstance(document, dict):
        return []
    found = []
    if text_outside(document):
        found.append(_fail(key, "title_cut_off"))
    if boxes and text_hits(document, _face_percents(boxes)):
        found.append(_fail(key, "text_covers_face"))
    return found


def duplicate_failures(key: str, expected: Any, boxes: list | None) -> list[dict[str, str]]:
    if boxes is None or not isinstance(expected, int) or len(boxes) <= expected:
        return []
    return [_fail(key, "duplicate_people")]


def identity_value(embed: Callable[..., Any] | None, samples: list) -> str:
    if embed is None or not samples:
        return "unknown"
    try:
        value = embed(samples)
    except Exception:
        return "unknown"
    if value in {"yes", "no"}:
        return value
    return "unknown"


def identity_failures(identity: str, jobs: list[dict]) -> list[dict[str, str]]:
    if identity != "yes" or not jobs:
        return []
    keys = [job["key"] for job in jobs if job.get("kind") == "h3" and _report(job, "appearance_changed")]
    if not keys and _report(jobs[0], "appearance_changed"):
        keys = [jobs[0]["key"]]
    return [_fail(key, "appearance_changed") for key in keys]


def pack(failures: list[dict[str, str]], jobs: list[dict], identity: str, evaluated: bool) -> dict[str, Any]:
    unique = _dedupe(failures)
    if unique:
        verdict = "retake"
    elif evaluated:
        verdict = "ok"
    else:
        verdict = "unreliable"
    unknown = [] if identity in {"yes", "no"} else ["appearance_changed"]
    return {"review": {"verdict": verdict, "failures": unique, "unknown": unknown}, "retake_keys": _retake_keys(unique, jobs)}


def has_bar(gray: Any) -> bool:
    if not isinstance(gray, np.ndarray) or gray.ndim != 2 or gray.size == 0:
        return False
    return _axis_bar(gray, 1) or _axis_bar(gray, 0)


def is_frozen(frames: Any) -> bool:
    score = mean_diff(frames)
    return score is not None and score < FROZEN_MEAN


def mean_diff(frames: Any) -> float | None:
    if not isinstance(frames, list) or len(frames) < 2:
        return None
    total = 0.0
    pairs = 0
    for left, right in zip(frames, frames[1:]):
        total += float(np.mean(np.abs(left.astype(np.int16) - right.astype(np.int16))))
        pairs += 1
    if pairs == 0:
        return None
    return total / pairs


def text_outside(document: dict) -> bool:
    for box in placements(document):
        if box["left"] < -_OUTSIDE or box["top"] < -_OUTSIDE or box["right"] > 100 + _OUTSIDE or box["bottom"] > 100 + _OUTSIDE:
            return True
    return False


def text_hits(document: dict, faces: list[dict]) -> bool:
    for box in placements(document):
        for face in faces:
            if _overlap(box, face):
                return True
    return False


def placements(document: dict) -> list[dict]:
    from services.scene2d_text_boxes import lyric_placements, text_placements

    return text_placements(document) + lyric_placements(document)


def sample_clip(path: str, count: int = _SAMPLES) -> dict[str, Any] | None:
    try:
        import cv2
    except Exception:
        return None
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        capture.release()
        return None
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    grays: list[np.ndarray] = []
    color = None
    width = height = 0
    try:
        for index in _indexes(total, count):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            height, width = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            grays.append(cv2.resize(gray, (160, 90)))
            color = frame
    finally:
        capture.release()
    if color is None:
        return None
    full = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    return {"gray": grays, "full_gray": full, "color": color, "width": width, "height": height}


def final_bars(state: Any, root: str | None) -> tuple[bool, list[str]]:
    if not isinstance(state, dict) or not isinstance(root, str):
        return False, []
    path = _contained(Path(root), state.get("final"))
    if path is None:
        return False, []
    points = _midpoints(state.get("segments"))
    if points:
        return bars_at(str(path), points)
    clip = _safe_sample(sample_clip, str(path))
    if clip is None:
        return False, []
    if not has_bar(clip.get("full_gray")):
        return True, []
    scenes = state.get("scenes") if isinstance(state.get("scenes"), dict) else {}
    return True, [key for key in scenes if isinstance(key, str)]


def bars_at(path: str, points: list[tuple[str, float]]) -> tuple[bool, list[str]]:
    try:
        import cv2
    except Exception:
        return False, []
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        capture.release()
        return False, []
    keys: list[str] = []
    saw = False
    try:
        for key, seconds in points:
            capture.set(cv2.CAP_PROP_POS_MSEC, float(seconds) * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            saw = True
            if has_bar(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)):
                keys.append(key)
    finally:
        capture.release()
    return saw, keys


def load_people_detector() -> Callable[..., Any] | None:
    cached = getattr(load_people_detector, "fn", None)
    if cached is not None:
        return cached
    try:
        from services.qa_people import find_weights, open_detector, people_boxes
        weights = find_weights()
        if not weights:
            return None
        session = open_detector(weights)
    except Exception:
        return None

    def detect(image: Any) -> list:
        return people_boxes(session, image)

    load_people_detector.fn = detect  # type: ignore[attr-defined]
    return detect


def detect_boxes(clip: Any, people: Callable[..., Any] | None) -> list | None:
    if people is None or not isinstance(clip, dict):
        return None
    color = clip.get("color")
    width = clip.get("width") or 0
    height = clip.get("height") or 0
    if color is None or width <= 0 or height <= 0:
        return None
    try:
        found = people(color)
    except Exception:
        return None
    if not isinstance(found, list):
        return None
    return [_percent_box(box, width, height) for box in found if _tall(box, height)]


def frozen_clip(clip: Any) -> bool:
    if not isinstance(clip, dict):
        return False
    return is_frozen(clip.get("gray"))


def _face_percents(boxes: list) -> list[dict[str, float]]:
    faces = []
    for box in boxes:
        if not isinstance(box, dict):
            continue
        span = box["bottom"] - box["top"]
        faces.append({
            "left": box["left"],
            "top": box["top"],
            "right": box["right"],
            "bottom": box["top"] + span * FACE_TOP,
        })
    return faces


def _percent_box(box: Any, width: int, height: int) -> dict[str, float]:
    return {
        "left": float(box[0]) / width * 100.0,
        "top": float(box[1]) / height * 100.0,
        "right": float(box[2]) / width * 100.0,
        "bottom": float(box[3]) / height * 100.0,
    }


def _tall(box: Any, height: int) -> bool:
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return False
    try:
        top = float(box[1])
        bottom = float(box[3])
    except (TypeError, ValueError):
        return False
    return bottom - top >= height * MIN_PERSON


def _axis_bar(gray: np.ndarray, reduce_axis: int) -> bool:
    peak = gray.max(axis=reduce_axis)
    mean = gray.mean(axis=reduce_axis)
    dark = (peak <= BAR_MAX) & (mean <= BAR_MEAN)
    need = max(2, int(dark.size * BAR_FRACTION))
    return _bar_run(dark, need)


def _bar_run(dark: np.ndarray, need: int) -> bool:
    size = int(dark.size)
    if _fit(_leading(dark), size, need):
        return True
    return _fit(_leading(dark[::-1]), size, need)


def _fit(run: int, size: int, need: int) -> bool:
    return need <= run < size * 0.45


def _leading(dark: np.ndarray) -> int:
    if dark.size == 0 or not bool(dark[0]):
        return 0
    flipped = ~dark
    index = int(np.argmax(flipped))
    if not bool(flipped[index]):
        return int(dark.size)
    return index


def _overlap(box: dict, face: dict) -> bool:
    return box["left"] < face["right"] and face["left"] < box["right"] and box["top"] < face["bottom"] and face["top"] < box["bottom"]


def _fail(key: str, question: str) -> dict[str, str]:
    return {"key": key, "question": question}


def _dedupe(failures: list[dict[str, str]]) -> list[dict[str, str]]:
    unique = []
    seen: set[tuple[str, str]] = set()
    for item in failures:
        token = (item["key"], item["question"])
        if token in seen:
            continue
        seen.add(token)
        unique.append({"key": item["key"], "question": item["question"]})
    return unique


def _retake_keys(failures: list[dict[str, str]], jobs: list[dict]) -> list[str]:
    wanted = {item["key"] for item in failures}
    keys: list[str] = []
    for job in jobs:
        if job["key"] in wanted and job["key"] not in keys:
            keys.append(job["key"])
    for item in failures:
        if item["key"] not in keys:
            keys.append(item["key"])
    return keys


def _samples(jobs: list[dict], clips: list) -> list[dict]:
    samples = []
    for job, clip in zip(jobs, clips):
        if isinstance(clip, dict) and clip.get("gray"):
            samples.append({"key": job["key"], "gray": clip["gray"]})
    return samples


def _safe_sample(reader: Callable[[str], Any], path: str | None) -> dict | None:
    if not path:
        return None
    try:
        clip = reader(path)
    except Exception:
        return None
    return clip if isinstance(clip, dict) else None


def _scene_order(state: dict) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for item in state.get("segments") or []:
        key = item[0] if isinstance(item, (list, tuple)) and item else None
        if isinstance(key, str) and key not in seen:
            seen.add(key)
            ordered.append(key)
    scenes = state.get("scenes")
    if isinstance(scenes, dict):
        for key in scenes:
            if isinstance(key, str) and key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def _shots(state: dict) -> dict[str, dict]:
    spec = state.get("spec") if isinstance(state.get("spec"), dict) else {}
    shots = {}
    for shot in spec.get("shots") or []:
        if isinstance(shot, dict) and isinstance(shot.get("key"), str):
            shots[shot["key"]] = shot
    return shots


def _scene_row(state: dict, key: str) -> dict:
    scenes = state.get("scenes")
    if isinstance(scenes, dict) and isinstance(scenes.get(key), dict):
        return scenes[key]
    return {}


def _job(base: Path, key: str, row: dict, shot: dict | None, counts: dict[str, int] | None = None) -> dict[str, Any]:
    kind = ""
    if isinstance(shot, dict) and isinstance(shot.get("kind"), str):
        kind = shot["kind"]
    path = _contained(base, row.get("file"))
    document = _document(path)
    return {
        "key": key,
        "kind": kind,
        "held": _marked(row, shot) or _image_hold(document, kind),
        "expected": _expected(shot, counts),
        "allow": _allow(shot),
        "path": None if path is None else str(path),
        "document": document,
    }


def _final_bar_failures(jobs: list[dict], keys: list[str]) -> list[dict[str, str]]:
    dark = {job["key"] for job in jobs if "dark" in (job.get("allow") or ())}
    return [_fail(key, "black_bars") for key in keys if key not in dark]


def _allow(shot: dict | None) -> tuple[str, ...]:
    if not isinstance(shot, dict) or not isinstance(shot.get("allow"), list):
        return ()
    return tuple(item for item in shot["allow"] if item in {"still", "dark", "secondary"})


def _report(job: dict, question: str) -> bool:
    """A deliberate still, dark frame, or secondary figure is not that failure."""
    allow = job.get("allow") or ()
    if question == "frozen_shot":
        return "still" not in allow
    if question == "black_bars":
        return "dark" not in allow
    if question in {"duplicate_people", "appearance_changed"}:
        return "secondary" not in allow
    return True


def _execution(state: Any, root: str | None, reader: Callable[[str], Any]) -> str:
    """ok when the named final opens, fail when that name is missing or unreadable, unreliable when no final was claimed."""
    name = state.get("final") if isinstance(state, dict) else None
    if not isinstance(name, str) or not name or not isinstance(root, str) or not root:
        return "unreliable"
    path = _contained(Path(root), name)
    if path is None:
        return "fail"
    return "ok" if _safe_sample(reader, str(path)) is not None else "fail"


def _marked(row: dict, shot: dict | None) -> bool:
    if isinstance(row, dict) and row.get("held") is True:
        return True
    return isinstance(shot, dict) and shot.get("held") is True


def _image_hold(document: dict | None, kind: str) -> bool:
    if kind != "h3" or not isinstance(document, dict):
        return False
    layers = [layer for layer in document.get("layers") or [] if isinstance(layer, dict)]
    if not layers:
        return False
    types = {layer.get("type") for layer in layers}
    return "video" not in types and "image" in types


def _cast_counts(state: dict) -> dict[str, int]:
    """How many distinct subjects each cast id stands for (``count``, or the size of ``group``, else 1)."""
    spec = state.get("spec") if isinstance(state.get("spec"), dict) else {}
    counts: dict[str, int] = {}
    for item in spec.get("cast") or []:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            continue
        raw = item.get("count", len(item.get("group") or []) or 1)
        try:
            number = int(raw)
        except (TypeError, ValueError):
            number = 1
        counts[item["id"]] = number if number > 0 else 1
    return counts


def _expected(shot: dict | None, counts: dict[str, int] | None = None) -> int | None:
    """People this shot may show: the sum of each referenced cast entry's ``count``."""
    if not isinstance(shot, dict) or not isinstance(shot.get("cast"), list):
        return None
    total = 0
    seen = False
    for cid in shot["cast"]:
        if not isinstance(cid, str) or not cid:
            continue
        seen = True
        total += (counts or {}).get(cid, 1)
    return total if seen else None


def _document(path: Path | None) -> dict | None:
    if path is None:
        return None
    meta = path.with_suffix(".meta.json")
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    scene = ((data.get("generation") or {}).get("parameters") or {}).get("scene")
    return scene if isinstance(scene, dict) else None


def _contained(base: Path, name: Any) -> Path | None:
    if not isinstance(name, str) or not name or "/" in name or "\\" in name or name in {".", ".."}:
        return None
    try:
        candidate = (base / name).resolve()
        root = base.resolve()
    except OSError:
        return None
    if candidate == root or root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _midpoints(segments: Any) -> list[tuple[str, float]]:
    points = []
    if not isinstance(segments, list):
        return points
    for item in segments:
        if not isinstance(item, (list, tuple)) or len(item) < 3 or not isinstance(item[0], str):
            continue
        try:
            start = float(item[1])
            end = float(item[2])
        except (TypeError, ValueError):
            continue
        points.append((item[0], (start + end) / 2.0))
    return points


def _indexes(total: int, count: int) -> list[int]:
    if total <= 1:
        return [0] if total == 1 else []
    if total <= count:
        return list(range(total))
    span = total - 1
    return [round(step * span / (count - 1)) for step in range(count)]
