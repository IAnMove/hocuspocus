"""Timing smoothness of a clip, its exported scene, and the final video.

Packet times show a held frame, a cadence hitch, and a stretch that runs at
another speed. Frames that look the same but keep a steady cadence are not
visible here. A file that cannot be read records nothing, and an animatic
preview is skipped so a held still is not blamed on the finished cut.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

# A step this many times the clip's own cadence is one frame held too long.
_HOLD = 2.5
# A single step this many times the cadence, with normal neighbors, is a hitch.
_HITCH = 1.6
# A run of steps this far from the cadence is a speed change, not the clip's rate.
_SPEED = 1.35
_SPEED_RUN = 4
# Steps shorter than this fraction of the cadence are repeated timestamps.
_DUP = 0.35
_DUP_RUN = 2
# A held or repeated stretch this long fails. A shorter one is only a watch.
_FAIL_HOLD = 0.4
_MARKS = 8


def assess(times: list[float]) -> dict:
    """Judge presentation timestamps. Fewer than four, or a clock that runs backwards, is not a verdict."""
    steps = _steps(times)
    if steps is None:
        return {"verdict": "unreliable", "marks": []}
    cadence = _cadence(steps)
    marks = _marks(times, steps, cadence)
    return {"verdict": _verdict(marks), "cadence": round(cadence, 4), "marks": marks}


def note_outputs(production: Any, stage: str) -> None:
    """Measure one stage and refresh the blame from clip to scene to final."""
    if production.state.get("caption_gate"):
        return
    reader = getattr(production, "frame_times", None) or read_times
    bucket = production.state.setdefault("smoothness", {})
    if stage == "final":
        report = _report(production.root, production.state.get("final"), reader)
        if report is None:
            bucket.pop("final", None)
        else:
            bucket["final"] = report
    else:
        store = production.state.get("clips" if stage == "clip" else "scenes") or {}
        bucket[stage] = _reports(production.root, store, reader)
    bucket["blame"] = blame(bucket)


def blame(bucket: dict) -> list[dict]:
    """A jerk in the clip stays the clip's. One that starts in the scene is the retime. One that starts in the final is the export."""
    clips = bucket.get("clip") if isinstance(bucket.get("clip"), dict) else {}
    scenes = bucket.get("scene") if isinstance(bucket.get("scene"), dict) else {}
    rows = [_rows("clip", key, "clip", report) for key, report in clips.items()]
    flat = [row for group in rows for row in group]
    flat.extend(_scene_rows(clips, scenes))
    flat.extend(_final_rows(clips, scenes, bucket.get("final")))
    return flat


def for_status(state: dict) -> dict | None:
    """Stages that are not ok, with at most eight marks. A clean measurement adds no status key."""
    bucket = state.get("smoothness") if isinstance(state, dict) else None
    if not isinstance(bucket, dict):
        return None
    stages = _stage_verdicts(bucket)
    if not stages:
        return None
    marks = []
    for row in bucket.get("blame") or []:
        if stages.get(row.get("stage")) not in ("watch", "fail") or len(marks) >= _MARKS:
            continue
        marks.append({key: row[key] for key in ("stage", "key", "t", "kind", "source", "seconds") if key in row})
    return {"stages": stages, "marks": marks}


def read_times(path: Any) -> list[float] | None:
    """Packet presentation times. Missing ffprobe or an unreadable file yields None."""
    file = Path(path)
    if not file.is_file():
        return None
    binary = shutil.which("ffprobe")
    if not binary:
        return None
    probe = subprocess.run(
        [binary, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,dts_time", "-of", "json", str(file)],
        capture_output=True, text=True, check=False,
    )
    if probe.returncode != 0:
        return None
    try:
        packets = json.loads(probe.stdout).get("packets") or []
    except json.JSONDecodeError:
        return None
    return _packet_times(packets)


def _packet_times(packets: list) -> list[float] | None:
    times = []
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        try:
            stamp = float(packet.get("pts_time", packet.get("dts_time")))
        except (TypeError, ValueError):
            continue
        if stamp >= 0:
            times.append(stamp)
    return times or None


def _steps(times: list[float]) -> list[float] | None:
    if len(times) < 4:
        return None
    steps = []
    for earlier, later in zip(times, times[1:]):
        try:
            step = float(later) - float(earlier)
        except (TypeError, ValueError):
            return None
        if step < -1e-4:
            return None
        steps.append(step)
    return steps


def _cadence(steps: list[float]) -> float:
    usable = sorted(step for step in steps if step >= 1 / 120)
    chosen = usable or sorted(steps)
    return chosen[len(chosen) // 2] or (1 / 24)


def _marks(times: list[float], steps: list[float], cadence: float) -> list[dict]:
    held = _holds(times, steps, cadence)
    consumed = {mark["index"] for mark in held}
    speeds = _speeds(times, steps, cadence, consumed)
    consumed.update(mark["index"] for mark in speeds)
    hitches = _hitches(times, steps, cadence, consumed)
    return [_public(mark) for mark in [*held, *speeds, *hitches]]


def _holds(times: list[float], steps: list[float], cadence: float) -> list[dict]:
    marks = []
    tiny = _DUP * cadence
    index = 0
    while index < len(steps):
        if steps[index] >= _HOLD * cadence:
            marks.append({"index": index, "t": times[index], "kind": "duplicate", "seconds": steps[index]})
            index += 1
            continue
        if steps[index] >= tiny:
            index += 1
            continue
        start = index
        while index < len(steps) and steps[index] < tiny:
            index += 1
        if index - start >= _DUP_RUN:
            marks.append({"index": start, "t": times[start], "kind": "duplicate", "seconds": (index - start) * cadence})
    return marks


def _speeds(times: list[float], steps: list[float], cadence: float, consumed: set[int]) -> list[dict]:
    marks = []
    index = 0
    while index < len(steps):
        if index in consumed or not _off_cadence(steps[index], cadence):
            index += 1
            continue
        start = index
        while index < len(steps) and index not in consumed and _off_cadence(steps[index], cadence):
            index += 1
        if index - start >= _SPEED_RUN:
            consumed.update(range(start, index))
            marks.append({"index": start, "t": times[start], "kind": "speed", "seconds": sum(steps[start:index])})
    return marks


def _hitches(times: list[float], steps: list[float], cadence: float, consumed: set[int]) -> list[dict]:
    marks = []
    near = 1.25 * cadence
    for index, step in enumerate(steps):
        if index in consumed or not (_HITCH * cadence <= step < _HOLD * cadence):
            continue
        if not _neighbors_near(steps, index, near):
            continue
        marks.append({"index": index, "t": times[index], "kind": "cadence", "seconds": step})
    return marks


def _off_cadence(step: float, cadence: float) -> bool:
    return (_SPEED * cadence <= step < _HOLD * cadence) or (_DUP * cadence <= step <= cadence / _SPEED)


def _neighbors_near(steps: list[float], index: int, near: float) -> bool:
    if index > 0 and steps[index - 1] > near:
        return False
    return index + 1 >= len(steps) or steps[index + 1] <= near


def _verdict(marks: list[dict]) -> str:
    for mark in marks:
        if mark["kind"] == "speed" or (mark["kind"] == "duplicate" and mark["seconds"] >= _FAIL_HOLD):
            return "fail"
    return "watch" if marks else "ok"


def _public(mark: dict) -> dict:
    return {"t": round(float(mark["t"]), 3), "kind": mark["kind"], "seconds": round(float(mark["seconds"]), 3)}


def _report(root: Any, name: Any, reader: Any) -> dict | None:
    if not isinstance(name, str) or not name:
        return None
    times = reader(Path(root) / name)
    if not isinstance(times, list):
        return None
    report = assess(times)
    return None if report["verdict"] == "unreliable" else report


def _reports(root: Any, store: Any, reader: Any) -> dict:
    rows = {}
    if not isinstance(store, dict):
        return rows
    for key, item in store.items():
        name = item.get("file") if isinstance(item, dict) else None
        report = _report(root, name, reader)
        if report is not None:
            rows[key] = report
    return rows


def _rows(stage: str, key: str, source: str, report: Any) -> list[dict]:
    if not isinstance(report, dict):
        return []
    return [_row(stage, key, source, mark) for mark in report.get("marks") or [] if isinstance(mark, dict)]


def _scene_rows(clips: dict, scenes: dict) -> list[dict]:
    rows = []
    for key, report in scenes.items():
        inherited = _kinds(clips.get(key))
        for mark in (report.get("marks") if isinstance(report, dict) else []) or []:
            if not isinstance(mark, dict):
                continue
            source = "clip" if mark.get("kind") in inherited else "retime"
            rows.append(_row("scene", key, source, mark))
    return rows


def _final_rows(clips: dict, scenes: dict, final: Any) -> list[dict]:
    if not isinstance(final, dict):
        return []
    inherited = {}
    for key, report in scenes.items():
        clip_kinds = _kinds(clips.get(key))
        for mark in (report.get("marks") if isinstance(report, dict) else []) or []:
            if isinstance(mark, dict) and mark.get("kind"):
                inherited.setdefault(mark["kind"], "clip" if mark["kind"] in clip_kinds else "retime")
    return [_row("final", "", inherited.get(mark.get("kind"), "export"), mark) for mark in final.get("marks") or [] if isinstance(mark, dict)]


def _kinds(report: Any) -> set[str]:
    if not isinstance(report, dict):
        return set()
    return {mark.get("kind") for mark in report.get("marks") or [] if isinstance(mark, dict)}


def _row(stage: str, key: str, source: str, mark: dict) -> dict:
    return {"stage": stage, "key": key, "t": mark.get("t"), "kind": mark.get("kind"), "source": source, "seconds": mark.get("seconds")}


def _stage_verdicts(bucket: dict) -> dict[str, str]:
    stages = {}
    for name in ("clip", "scene"):
        verdict = _worst(bucket.get(name))
        if verdict:
            stages[name] = verdict
    final = bucket.get("final")
    if isinstance(final, dict) and final.get("verdict") in ("watch", "fail"):
        stages["final"] = final["verdict"]
    return stages


def _worst(reports: Any) -> str | None:
    if not isinstance(reports, dict):
        return None
    rank = {"watch": 1, "fail": 2}
    found = [report.get("verdict") for report in reports.values() if isinstance(report, dict)]
    worst = max((rank.get(verdict, 0) for verdict in found), default=0)
    if worst == 2:
        return "fail"
    return "watch" if worst == 1 else None
