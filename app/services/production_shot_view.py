"""Read-only shots for one production, from the files each producer already wrote.

Music, Director, Series and montage keep their own records. This module does
not create a shot, pick a take, or fill in a lyric, duration or scene that the
source file does not already contain.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from services.production_project_link import read_link_store
from services.production_run import adapt_pipeline_record
from services.production_shot_actions import annotate_actions, stored_revision
from services.production_shot_review import load_review
from services.production_work_catalog import find_work


_MAX_SHOTS = 200
_MAX_TAKES = 20
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,180}$")
_ATTEMPT_STATUS = frozenset({"queued", "running", "cancelling", "completed", "failed", "cancelled"})
_REVIEW_DECISION = frozenset({"approved", "rejected"})


def shot_view(workspace_dir: str, workspace_id: str, production_id: str) -> dict[str, Any] | None:
    work = find_work(workspace_dir, workspace_id, production_id)
    if work is None:
        return None
    shots, sources, limits = _collect(workspace_dir, workspace_id, production_id, work)
    _attach_review(workspace_dir, production_id, shots)
    full = len(shots)
    truncated = full > _MAX_SHOTS
    if truncated:
        limits.append("shot_list_truncated")
    if full == 0:
        limits.append("no_shots")
    shown = shots[:_MAX_SHOTS]
    annotate_actions(shown)
    view = _envelope(work, _dedupe(sources), _dedupe(limits), shown, full, truncated)
    view["revision"] = stored_revision(workspace_dir, production_id)
    return view


def _collect(workspace_dir: str, workspace_id: str, production_id: str, work: dict[str, Any]):
    music, music_limits = _music(workspace_dir, production_id)
    series, series_limits = _series(workspace_dir, work)
    director, director_limits = _director(workspace_dir, workspace_id, production_id)
    montage, montage_limits = _montage(workspace_dir, production_id, _montage_hint(workspace_dir, production_id))
    primary, extras = _pick(music, series, director, montage, work)
    return (
        _merge(primary, extras),
        _present(("music", music), ("series", series), ("director", director), ("montage", montage)),
        music_limits + series_limits + director_limits + montage_limits,
    )


def _pick(music, series, director, montage, work: dict[str, Any] | None = None):
    # A leftover music-shaped shots.json beside series-{episode} is not the
    # render. Review then listed those lyrics, and regenerate fired a song redo.
    episode = isinstance((work or {}).get("project"), dict) and work["project"].get("kind") == "episode"
    if episode and series is not None:
        return series, [music, director, montage]
    if music is not None:
        return music, [series, director, montage]
    if series is not None:
        return series, [director, montage]
    if director is not None:
        return director, [montage]
    if montage is not None:
        return montage, []
    return [], []


def _merge(primary: list[dict[str, Any]], extras: list) -> list[dict[str, Any]]:
    by_id = {shot["id"]: shot for shot in primary}
    for group in extras:
        for shot in group or []:
            current = by_id.get(shot["id"])
            if current is not None:
                _fill(current, shot)
    return list(primary)


def _fill(target: dict[str, Any], extra: dict[str, Any]) -> None:
    for key in ("start", "end", "duration", "text", "text_kind", "technical_status", "scene", "montage", "review"):
        if target.get(key) is None and extra.get(key) is not None:
            target[key] = extra[key]
    if not target["takes"] and extra.get("takes"):
        target["takes"] = extra["takes"]
        target["selected_take_id"] = extra.get("selected_take_id")


def _music(workspace_dir: str, production_id: str):
    body, problem = _read_json(os.path.join(workspace_dir, f"{production_id}.shots.json"))
    if problem:
        return [], ["shots_unreadable"]
    if body is None:
        return None, []
    raw = body.get("shots")
    if not isinstance(raw, list):
        return [], ["shots_unreadable"]
    return [shot for index, item in enumerate(raw) if (shot := _music_shot(item, index))], []


def _music_shot(item: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(item, dict) or not isinstance(item.get("key"), str) or not item["key"].strip():
        return None
    start, end = _number(item.get("start")), _number(item.get("end"))
    preview = _safe_name(item.get("clip")) or _safe_name(item.get("start_frame")) or _safe_name(item.get("scene_video"))
    rows = item.get("takes") or ([{"file": preview}] if preview else [])
    takes = _file_takes(rows, preview)
    scene_name = _safe_name(item.get("scene_doc"))
    stale = _stored_bool(item, "video_stale", "export_stale")
    result = _shot(
        item["key"].strip()[:80], index + 1, "music",
        start=start, end=end, duration=_span(start, end),
        text=_text(item.get("lyric")), text_kind="lyric" if _text(item.get("lyric")) else None,
        takes=takes[0], selected_take_id=takes[1],
        scene={"kind": "scene2d", "id": scene_name} if scene_name else None,
        montage={"stale": stale} if stale is not None else None,
    )
    result["regenerable"] = item.get("kind") != "clip"
    return result


def _series(workspace_dir: str, work: dict[str, Any]):
    project = work.get("project") if isinstance(work.get("project"), dict) else None
    if not project or project.get("kind") != "episode":
        return None, []
    body, problem = _read_json(os.path.join(workspace_dir, ".series-library-v1.json"))
    if problem:
        return None, ["series_unreadable"]
    if body is None:
        return None, ["series_missing"]
    episode = _episode(body, str(project.get("id") or ""))
    if episode is None:
        return None, ["episode_missing"]
    raw = episode.get("shots")
    if not isinstance(raw, list):
        return [], ["series_unreadable"]
    return [shot for index, item in enumerate(raw) if (shot := _series_shot(item, index))], []


def _series_shot(item: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    identifier = item.get("id") if isinstance(item.get("id"), str) and item["id"].strip() else ""
    if not identifier:
        return None
    dialogue = _dialogue(item.get("dialogueBeats"))
    action = _text(item.get("action"))
    takes, selected, technical, review = _series_takes(item)
    scene_id = _text(item.get("sceneId"))
    result = _shot(
        identifier[:80], _order(item.get("order"), index + 1), "series",
        duration=_number(item.get("durationSeconds")),
        text=dialogue or action, text_kind="dialogue" if dialogue else ("action" if action else None),
        takes=takes, selected_take_id=selected, technical_status=technical, review=review,
        scene={"kind": None, "id": scene_id} if scene_id else None,
    )
    result["regenerable"] = item.get("productionMethod") in {None, "generated_video", "animation_2d"}
    return result


def _series_takes(item: dict[str, Any]):
    approved = item.get("approvedAttemptId") if isinstance(item.get("approvedAttemptId"), str) else None
    takes, technical, review = [], None, None
    for attempt in _list(item.get("attempts"))[:_MAX_TAKES]:
        if not isinstance(attempt, dict) or not isinstance(attempt.get("id"), str) or not attempt["id"].strip():
            continue
        assets = attempt.get("outputAssetIds") if isinstance(attempt.get("outputAssetIds"), list) else []
        file_name = _safe_name(assets[0]) if assets else None
        selected = approved == attempt["id"]
        takes.append({"id": attempt["id"].strip()[:80], "file": file_name, "selected": selected})
        if selected:
            technical = attempt.get("status") if attempt.get("status") in _ATTEMPT_STATUS else None
            decision = attempt.get("reviewDecision")
            review = {"status": decision, "locked": None, "notes": None} if decision in _REVIEW_DECISION else None
    selected_id = approved if any(take["selected"] for take in takes) else None
    return takes, selected_id, technical, review


def _director(workspace_dir: str, workspace_id: str, production_id: str):
    try:
        names = os.listdir(workspace_dir)
    except OSError:
        return None, []
    rows, limits, seen = [], [], False
    for name in names:
        if not name.startswith("_director_pipeline_") or not name.endswith(".json"):
            continue
        body, problem = _read_json(os.path.join(workspace_dir, name))
        if problem:
            limits.append("director_unreadable")
            continue
        if body is None or not _pipeline_matches(body, workspace_id, production_id):
            continue
        seen = True
        clips = body.get("clips") if isinstance(body.get("clips"), list) else []
        rows.extend(shot for index, clip in enumerate(clips) if (shot := _director_shot(clip, index)))
    return (rows, limits) if seen else (None, limits)


def _pipeline_matches(body: dict[str, Any], workspace_id: str, production_id: str) -> bool:
    if str(body.get("production_id") or "") == production_id:
        return True
    try:
        adapted = adapt_pipeline_record(body, workspace_id)
    except ValueError:
        return False
    return adapted["production"]["id"] == production_id


def _director_shot(item: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    identifier = item.get("shot_id") if isinstance(item.get("shot_id"), str) and item["shot_id"].strip() else f"clip-{index + 1}"
    selected_name = _safe_name(item.get("selected_video_filename")) or _safe_name(item.get("video_filename"))
    takes = _attempt_takes(item.get("video_attempts"), selected_name)
    if not takes[0] and selected_name:
        takes = _named_take(selected_name)
    stale = _stored_bool(item, "video_stale")
    return _shot(
        identifier.strip()[:80], index + 1, "director",
        takes=takes[0], selected_take_id=takes[1],
        montage={"stale": stale} if isinstance(stale, bool) else None,
    )


def _montage(workspace_dir: str, production_id: str, hint: str | None):
    names = _montage_names(workspace_dir, production_id, hint)
    if not names and hint and not os.path.isfile(os.path.join(workspace_dir, _safe_name(hint) or "")):
        return None, ["montage_missing"]
    rows, limits, seen = [], [], False
    owned_name = _safe_name(hint)
    for name in names:
        body, problem = _read_json(os.path.join(workspace_dir, name))
        if problem:
            limits.append("montage_unreadable")
            continue
        if body is None:
            continue
        seen = True
        clips = body.get("clips") if isinstance(body.get("clips"), list) else []
        rows.extend(_montage_rows(clips, production_id, owned=name == owned_name))
    return (rows, limits) if seen else (None, limits)


def _montage_names(workspace_dir: str, production_id: str, hint: str | None) -> list[str]:
    names: list[str] = []
    hinted = _safe_name(hint)
    if hinted and hinted.endswith(".montage.json"):
        names.append(hinted)
    try:
        listing = os.listdir(workspace_dir)
    except OSError:
        return names
    for name in listing:
        if not name.endswith(".montage.json") or name in names or not _NAME.fullmatch(name):
            continue
        if _montage_mentions(os.path.join(workspace_dir, name), production_id):
            names.append(name)
        if len(names) >= 8:
            break
    return names


def _montage_mentions(path: str, production_id: str) -> bool:
    body, problem = _read_json(path)
    if problem or body is None:
        return False
    for clip in _list(body.get("clips")):
        origin = clip.get("origin") if isinstance(clip, dict) and isinstance(clip.get("origin"), dict) else {}
        if str(origin.get("productionId") or "") == production_id:
            return True
    return False


def _montage_rows(clips: list, production_id: str, *, owned: bool) -> list[dict[str, Any]]:
    rows = []
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict):
            continue
        origin = clip.get("origin") if isinstance(clip.get("origin"), dict) else {}
        if not owned and str(origin.get("productionId") or "") != production_id:
            continue
        row = _montage_shot(clip, index, origin)
        if row:
            rows.append(row)
    return rows


def _clip_id(origin: dict[str, Any], clip: dict[str, Any]) -> str:
    shot_id = origin.get("shotId") if isinstance(origin.get("shotId"), str) else ""
    clip_id = clip.get("id") if isinstance(clip.get("id"), str) else ""
    return (shot_id.strip() or clip_id.strip())[:80]


def _origin_scene(origin: dict[str, Any]) -> dict[str, Any] | None:
    kind = origin.get("kind") if origin.get("kind") in {"scene2d", "scene3d"} else None
    scene_id = _safe_name(origin.get("scene"))
    if not kind and not scene_id:
        return None
    return {"kind": kind, "id": scene_id}


def _stored_bool(item: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if isinstance(item.get(key), bool):
            return item[key]
    return None


def _named_take(name: str):
    return ([{"id": name, "file": name, "selected": True}], name)


def _prefer_take(takes: list[dict[str, Any]], fallback: str | None, explicit: str | None):
    if not explicit:
        return takes, fallback
    hit = False
    for take in takes:
        take["selected"] = take["id"] == explicit
        hit = hit or take["selected"]
    return takes, explicit if hit else fallback


def _history_id(record: dict[str, Any]) -> str | None:
    history = record.get("history")
    if not isinstance(history, list) or not history or not isinstance(history[-1], dict):
        return None
    value = history[-1].get("id")
    return value if isinstance(value, str) and value else None


def _montage_shot(clip: dict[str, Any], index: int, origin: dict[str, Any]) -> dict[str, Any] | None:
    identifier = _clip_id(origin, clip)
    if not identifier:
        return None
    start, end = _number(clip.get("trimStart")), _number(clip.get("trimEnd"))
    selected_name = _safe_name(clip.get("source"))
    rows, selected = _source_takes(clip.get("takes"), selected_name)
    if not rows and selected_name:
        rows, selected = _named_take(selected_name)
    rows, selected = _prefer_take(rows, selected, _text(clip.get("selectedTakeId")))
    lyric = _text(clip.get("lyric"))
    stale = _stored_bool(clip, "video_stale", "export_stale")
    return _shot(
        identifier, index + 1, "montage",
        start=start, end=end, duration=_span(start, end),
        text=lyric, text_kind="lyric" if lyric else None,
        takes=rows, selected_take_id=selected, scene=_origin_scene(origin),
        montage={"stale": stale} if stale is not None else None,
    )


def _montage_hint(workspace_dir: str, production_id: str) -> str | None:
    production, _problem = _read_json(os.path.join(workspace_dir, f"{production_id}.production.json"))
    if isinstance(production, dict) and isinstance(production.get("montage_file"), str):
        return production["montage_file"]
    manifest, _problem = _read_json(os.path.join(workspace_dir, f"{production_id}.shots.json"))
    if isinstance(manifest, dict) and isinstance(manifest.get("montage"), str):
        return manifest["montage"]
    for record in read_link_store(workspace_dir)["links"].values():
        if production_id in (record.get("production_ids") or []) and isinstance(record.get("montage_file"), str):
            return record["montage_file"]
    return None


def _attach_review(workspace_dir: str, production_id: str, shots: list[dict[str, Any]]) -> None:
    body = load_review(workspace_dir, production_id)
    rows = body.get("shots") if isinstance(body, dict) and isinstance(body.get("shots"), dict) else None
    if rows is None:
        return
    for shot in shots:
        record = rows.get(shot["id"])
        if isinstance(record, dict):
            notes = record.get("notes") if isinstance(record.get("notes"), str) else None
            shot["review"] = {
                "status": record.get("status") or "pending",
                "locked": bool(record.get("locked")),
                "notes": notes[:200] if notes else None,
                "history_id": _history_id(record),
            }


def _shot(identifier: str, order: int, source: str, **fields: Any) -> dict[str, Any]:
    row = {
        "id": identifier,
        "order": order,
        "start": None,
        "end": None,
        "duration": None,
        "text": None,
        "text_kind": None,
        "takes": [],
        "selected_take_id": None,
        "review": None,
        "technical_status": None,
        "scene": None,
        "montage": None,
        "provenance": {"source": source},
    }
    for key, value in fields.items():
        if value is not None:
            row[key] = value
    return row


def _envelope(work, sources, limits, shots, full: int, truncated: bool) -> dict[str, Any]:
    return {
        "workspace_id": work.get("workspace_id"),
        "production_id": work["production_id"],
        "project": work.get("project"),
        "title": work.get("title"),
        "status": work.get("status"),
        "format": work.get("format"),
        "sources": sources,
        "limits": limits,
        "shots": shots,
        "shot_count": full,
        "truncated": truncated,
    }


def _file_takes(raw: Any, selected_name: str | None):
    takes = []
    for item in _list(raw)[:_MAX_TAKES]:
        if not isinstance(item, dict):
            continue
        file_name = _safe_name(item.get("file"))
        if not file_name:
            continue
        takes.append({"id": file_name, "file": file_name, "selected": file_name == selected_name})
    selected = next((item["id"] for item in takes if item["selected"]), None)
    return takes, selected


def _attempt_takes(raw: Any, selected_name: str | None):
    takes = []
    for item in _list(raw)[:_MAX_TAKES]:
        if not isinstance(item, dict):
            continue
        file_name = _safe_name(item.get("filename") or item.get("id"))
        if not file_name:
            continue
        takes.append({"id": file_name, "file": file_name, "selected": file_name == selected_name})
    selected = next((item["id"] for item in takes if item["selected"]), None)
    return takes, selected


def _source_takes(raw: Any, selected_name: str | None):
    takes = []
    for item in _list(raw)[:_MAX_TAKES]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            continue
        file_name = _safe_name(item.get("source"))
        takes.append({
            "id": item["id"].strip()[:80],
            "file": file_name,
            "selected": bool(selected_name and file_name == selected_name),
        })
    selected = next((item["id"] for item in takes if item["selected"]), None)
    return takes, selected


def _dialogue(raw: Any) -> str | None:
    parts = []
    for beat in _list(raw):
        if isinstance(beat, dict):
            text = _text(beat.get("text"))
            if text:
                parts.append(text)
    return " / ".join(parts)[:500] if parts else None


def _episode(body: dict[str, Any], episode_id: str) -> dict[str, Any] | None:
    pools = []
    if isinstance(body.get("episodesById"), dict):
        pools.append(body["episodesById"])
    series = body.get("seriesById") if isinstance(body.get("seriesById"), dict) else {}
    for item in series.values():
        if isinstance(item, dict) and isinstance(item.get("episodesById"), dict):
            pools.append(item["episodesById"])
    for pool in pools:
        episode = pool.get(episode_id)
        if isinstance(episode, dict):
            return episode
    return None


def _present(*pairs: tuple[str, Any]) -> list[str]:
    return [name for name, value in pairs if value is not None]


def _read_json(path: str):
    if not os.path.isfile(path):
        return None, None
    try:
        body = json.loads(open(path, encoding="utf-8").read())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "unreadable"
    if not isinstance(body, dict):
        return None, "unreadable"
    return body, None


def _safe_name(value: Any) -> str | None:
    if not isinstance(value, str) or ".." in value:
        return None
    text = value.replace("\\", "/").split("?")[0].rstrip("/").split("/")[-1].strip()
    if not text or not _NAME.fullmatch(text):
        return None
    return text


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _span(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or end < start:
        return None
    return round(end - start, 3)


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text[:500] if text else None


def _order(value: Any, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dedupe(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen


__all__ = ["shot_view"]
