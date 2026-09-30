"""Median timings from completed runs, for dry-run minutes and progress ETA.

History lives in ``<workspace>/.production-timings.json``. A missing or unreadable
file leaves the dry-run minute constants unchanged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

TIMINGS_NAME = ".production-timings.json"
_CAP = 48
_DEFAULT_RESOLUTION = "1280x704"
_SEED_S = 120.0
_CLIP_S = 300.0
_TAIL_S = 60.0


def timings_path(workspace: str | Path) -> Path:
    return Path(workspace) / TIMINGS_NAME


def estimate(spec: Any, workspace: str | Path | None = None, windows: list | None = None) -> dict[str, Any]:
    """Minutes from medians, or the dry-run constants when history is empty."""
    spec = spec if isinstance(spec, dict) else {}
    rates = history_rates(workspace) if workspace else None
    if not rates:
        from services.production_dry_run import _minutes
        return {"minutes": _minutes(spec, len(_h3_rows(spec, windows))), "estimate_source": "defaults", "seconds": None}
    seconds = _total_seconds(spec, rates, windows)
    return {"minutes": float(round(seconds / 60.0, 1)), "estimate_source": f"history({rates['n']})", "seconds": round(seconds, 3)}


def apply_estimate(spec: Any, report: dict, workspace: str | Path | None = None) -> dict:
    """Attach ``estimate_source``. History replaces ``minutes``; defaults do not."""
    windows = report.get("windows") if isinstance(report, dict) else None
    judged = estimate(spec, workspace, windows if isinstance(windows, list) else None)
    viewed = dict(report)
    viewed["estimate_source"] = judged["estimate_source"]
    if judged["estimate_source"] != "defaults":
        viewed["minutes"] = judged["minutes"]
    return viewed


def record_completed(workspace: str | Path | None, state: Any) -> None:
    """Append one completed run. Never raises; ignores anything not completed."""
    if not workspace or not isinstance(state, dict) or state.get("status") != "completed":
        return
    try:
        _store(Path(workspace), state)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return


def history_rates(workspace: str | Path | None) -> dict[str, Any] | None:
    """Medians and the run count. ``None`` when the file is missing, empty, or corrupt."""
    data = _read(workspace)
    if not isinstance(data, dict):
        return None
    count = data.get("n")
    if type(count) is not int or count <= 0:
        return None
    return {
        "n": count,
        "clips": _bucket_medians(data.get("clips")),
        "scenes": _median(data.get("scenes") if isinstance(data.get("scenes"), list) else []),
        "images": _bucket_medians(data.get("images")),
        "seeds": _median(data.get("seeds") if isinstance(data.get("seeds"), list) else []),
    }


def history_clip_median(workspace: str | Path | None) -> float | None:
    data = _read(workspace)
    clips = data.get("clips") if isinstance(data, dict) else None
    if not isinstance(clips, dict):
        return None
    values: list = []
    for bucket in clips.values():
        if isinstance(bucket, list):
            values.extend(bucket)
    med = _median(values)
    if med is None or med <= 0:
        return None
    return med


def history_scene_median(workspace: str | Path | None) -> float | None:
    rates = history_rates(workspace)
    if not rates or rates["scenes"] is None or rates["scenes"] <= 0:
        return None
    return float(rates["scenes"])


def _total_seconds(spec: dict, rates: dict, windows: list | None) -> float:
    return _seed_seconds(spec, rates) + _clip_total(spec, rates, windows) + _scene_seconds(spec, rates, windows)


def _seed_seconds(spec: dict, rates: dict) -> float:
    rate = _SEED_S if rates["seeds"] is None else float(rates["seeds"])
    return rate * _seed_count(spec)


def _clip_total(spec: dict, rates: dict, windows: list | None) -> float:
    key = _image_key(spec)
    total = 0.0
    for row in _h3_rows(spec, windows):
        total += _one_clip(row, rates, key)
    return total


def _one_clip(row: dict, rates: dict, key: str) -> float:
    frames = row.get("frames")
    bucket = rates["clips"].get(str(frames)) if frames is not None else None
    if bucket is None:
        # A missing clip bucket is the 5-minute shot default. The image median
        # is not added on top of that default.
        return _CLIP_S
    image = rates["images"].get(key)
    return float(bucket) + (float(image) if image is not None else 0.0)


def _scene_seconds(spec: dict, rates: dict, windows: list | None) -> float:
    # No scene median: one minute of tail, once, matching the dry-run constant.
    if rates["scenes"] is None:
        return _TAIL_S
    return float(rates["scenes"]) * _scene_count(spec, windows)


def _seed_count(spec: dict) -> int:
    song = spec.get("song") if isinstance(spec.get("song"), dict) else {}
    if song.get("file"):
        return 0
    raw = song.get("seeds")
    if isinstance(raw, list) and raw:
        return len(raw)
    return 3


def _scene_count(spec: dict, windows: list | None) -> int:
    if isinstance(windows, list):
        return len(windows)
    return len(_shot_list(spec))


def _h3_rows(spec: dict, windows: list | None) -> list[dict]:
    source = windows if isinstance(windows, list) else _shot_list(spec)
    return [row for row in source if isinstance(row, dict) and row.get("kind") == "h3"]


def _image_key(spec: dict) -> str:
    style = spec.get("style") if isinstance(spec.get("style"), dict) else {}
    resolution = style.get("resolution")
    if not isinstance(resolution, str) or not resolution.strip():
        resolution = _DEFAULT_RESOLUTION
    return f"{resolution}:{_image_steps(style)}"


def _image_steps(style: dict) -> int:
    steps = style.get("image_steps")
    if type(steps) is int and steps > 0:
        return steps
    model = str(style.get("image_model") or "")
    return 40 if model.startswith("qwen_image_21") else 4


def _store(root: Path, state: dict) -> None:
    data = _read(root) or _blank()
    _ensure_shape(data)
    _absorb(data, state)
    count = data.get("n")
    data["n"] = count + 1 if type(count) is int and count > 0 else 1
    data["version"] = 1
    _write(root, data)


def _ensure_shape(data: dict) -> None:
    for name in ("clips", "images"):
        if not isinstance(data.get(name), dict):
            data[name] = {}
    for name in ("scenes", "seeds"):
        if not isinstance(data.get(name), list):
            data[name] = []


def _absorb(data: dict, state: dict) -> None:
    spec = state.get("spec") if isinstance(state.get("spec"), dict) else {}
    timing = state.get("timing") if isinstance(state.get("timing"), dict) else {}
    _absorb_clips(data, state, spec, timing)
    _absorb_scenes(data, state, timing)
    _absorb_images(data, state, spec, timing)
    _absorb_seeds(data, state, spec, timing)


def _absorb_clips(data: dict, state: dict, spec: dict, timing: dict) -> None:
    samples = _explicit_clips(state, spec, timing) or _split_clips(state, spec, timing)
    for frames, seconds in samples:
        _push(data["clips"].setdefault(str(frames), []), seconds)


def _explicit_clips(state: dict, spec: dict, timing: dict) -> list[tuple[int, float]]:
    found = []
    for key in _h3_keys(spec):
        seconds = _named_seconds(state.get("clip_seconds"), key)
        if seconds is None:
            seconds = _shot_row_seconds(timing, key)
        frames = _frames_for(spec, state, key)
        if seconds is not None and frames is not None:
            found.append((frames, seconds))
    return found


def _split_clips(state: dict, spec: dict, timing: dict) -> list[tuple[int, float]]:
    total = _positive(timing.get("clips"))
    frames = []
    for key in _h3_keys(spec):
        frame = _frames_for(spec, state, key)
        if frame is not None:
            frames.append(frame)
    if total is None or not frames:
        return []
    each = total / len(frames)
    return [(frame, each) for frame in frames]


def _absorb_scenes(data: dict, state: dict, timing: dict) -> None:
    explicit = state.get("scene_seconds")
    if isinstance(explicit, dict):
        for value in explicit.values():
            _push(data["scenes"], value)
        return
    total = _positive(timing.get("scenes"))
    count = _scene_files(state) or _segment_count(state)
    if total is None or count <= 0:
        return
    each = total / count
    for _ in range(count):
        _push(data["scenes"], each)


def _absorb_images(data: dict, state: dict, spec: dict, timing: dict) -> None:
    explicit = state.get("image_seconds")
    if isinstance(explicit, dict):
        for key, value in explicit.items():
            _push(data["images"].setdefault(str(key), []), value)
        return
    total = _positive(timing.get("frames"))
    count = _image_count(state, spec)
    if total is None or count <= 0:
        return
    bucket = data["images"].setdefault(_image_key(spec), [])
    each = total / count
    for _ in range(count):
        _push(bucket, each)


def _absorb_seeds(data: dict, state: dict, spec: dict, timing: dict) -> None:
    count = _seed_count(spec)
    if count <= 0:
        return
    explicit = state.get("seed_seconds")
    if isinstance(explicit, list):
        for value in explicit:
            _push(data["seeds"], value)
        return
    total = _positive(timing.get("song"))
    if total is None:
        return
    each = total / count
    for _ in range(count):
        _push(data["seeds"], each)


def _image_count(state: dict, spec: dict) -> int:
    frames = state.get("frames")
    if isinstance(frames, dict) and frames:
        return len(frames)
    return len(_h3_keys(spec))


def _scene_files(state: dict) -> int:
    scenes = state.get("scenes")
    if not isinstance(scenes, dict):
        return 0
    return sum(1 for scene in scenes.values() if isinstance(scene, dict) and scene.get("file"))


def _segment_count(state: dict) -> int:
    segments = state.get("segments")
    return len(segments) if isinstance(segments, list) else 0


def _frames_for(spec: dict, state: dict, key: str) -> int | None:
    shot = _shot(spec, key)
    direct = shot.get("frames")
    if type(direct) is int and direct > 0:
        return direct
    span = _span(shot.get("t0"), shot.get("t1"))
    if span is None:
        span = _segment_span(state, key)
    if span is None:
        return None
    from services.music_production import h3_frames_for
    return h3_frames_for(span)


def _segment_span(state: dict, key: str) -> float | None:
    segments = state.get("segments")
    if not isinstance(segments, list):
        return None
    for item in segments:
        if isinstance(item, (list, tuple)) and len(item) >= 3 and item[0] == key:
            return _span(item[1], item[2])
    return None


def _span(a: Any, b: Any) -> float | None:
    if isinstance(a, bool) or isinstance(b, bool):
        return None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b > a:
        return float(b - a)
    return None


def _h3_keys(spec: dict) -> list[str]:
    keys = []
    for shot in _shot_list(spec):
        if isinstance(shot, dict) and shot.get("kind") == "h3" and isinstance(shot.get("key"), str):
            keys.append(shot["key"])
    return keys


def _shot_list(spec: dict) -> list:
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else []
    fill = spec.get("fill") if isinstance(spec.get("fill"), list) else []
    return [*shots, *fill]


def _shot(spec: dict, key: str) -> dict:
    for shot in _shot_list(spec):
        if isinstance(shot, dict) and shot.get("key") == key:
            return shot
    return {}


def _named_seconds(raw: Any, key: str) -> float | None:
    if not isinstance(raw, dict):
        return None
    return _positive(raw.get(key))


def _shot_row_seconds(timing: dict, key: str) -> float | None:
    rows = timing.get("shots") if isinstance(timing.get("shots"), list) else []
    for row in rows:
        if isinstance(row, dict) and row.get("key") == key:
            return _positive(row.get("seconds"))
    return None


def _bucket_medians(raw: Any) -> dict[str, float]:
    found = {}
    if not isinstance(raw, dict):
        return found
    for key, values in raw.items():
        med = _median(values if isinstance(values, list) else [])
        if med is not None:
            found[str(key)] = med
    return found


def _median(values: Any) -> float | None:
    nums = sorted(item for item in values if _finite(item))
    if not nums:
        return None
    mid = len(nums) // 2
    if len(nums) % 2:
        return float(nums[mid])
    return (float(nums[mid - 1]) + float(nums[mid])) / 2


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value >= 0 and value == value


def _positive(value: Any) -> float | None:
    if not _finite(value) or value <= 0:
        return None
    return float(value)


def _push(bucket: Any, value: Any) -> None:
    number = _positive(value)
    if number is None or not isinstance(bucket, list):
        return
    bucket.append(round(number, 3))
    extra = len(bucket) - _CAP
    if extra > 0:
        del bucket[:extra]


def _blank() -> dict:
    return {"version": 1, "n": 0, "clips": {}, "scenes": [], "images": {}, "seeds": []}


def _read(workspace: str | Path | None) -> dict | None:
    if not workspace:
        return None
    path = timings_path(workspace)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write(root: Path, data: dict) -> None:
    path = timings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
