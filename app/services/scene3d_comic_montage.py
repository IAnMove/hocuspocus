"""Place a comic chapter change on a saved montage and keep the previous revision.

``between`` is a clip index when it is an int in ``0 .. len(clips)-2`` (the boundary
after that clip). Any other number is a time in seconds. ``insert`` adds the two
halves. ``replace`` trims the clips around the cut so the timeline stays the same
length and a song that starts with the picture stays in sync.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from services.montage_documents import SUFFIX, MontageError, MontageStore
from services.scene3d_comic import _read_path, _timing
from services.video_editor import extract_frame, probe_media
from services.world3d_scenes import World3DSceneError

_GAP = 0.05
_NEIGHBOUR = 0.5
_INTERSTITIAL = frozenset({"later-clock", "later-tropical", "later-cinematic"})


def comic_from_montage(data: dict, workspace_dir, transition) -> dict:
    try:
        return _place(data, workspace_dir, transition)
    except MontageError as exc:
        raise World3DSceneError(exc.code, str(exc), exc.status) from exc


def _place(data: dict, workspace_dir, transition) -> dict:
    workspace = str(data.get("workspace") or "")
    mode = _mode(data.get("mode", "insert"))
    exit_d, enter_d, hold = _timing(data)
    root = Path(workspace_dir(workspace))
    store = MontageStore(workspace_dir)
    loaded, file, previous, revision = _open(store, root, workspace, data.get("montage"))
    pristine = copy.deepcopy(loaded) if file is None else None
    clips = [dict(clip) for clip in loaded.get("clips") or []]
    if not clips:
        raise World3DSceneError("invalid_montage", "A montage needs at least one clip")
    cache: dict = {}
    spans = _spans(clips, root, cache)
    starts = _starts(clips, spans)
    kind, index, cut = _locate(clips, spans, starts, data.get("between"))
    anchor, split, from_source, to_source = _plan(kind, index, cut, mode, exit_d, enter_d, starts, spans)
    samples = _samples(clips, anchor, split, from_source, to_source, root, cache)
    panels = _extract(samples, root, cache)
    if mode == "replace":
        # The entering panel plays the frames the trim removed, so it moves in time with the song.
        panels[2] = {"video": str(_probe(samples[2][0], root, cache)["path"]), "at": float(samples[2][1])}
    fmt = _format(data, samples[1][0], root, cache)
    inner = _inner(workspace, fmt, panels, data.get("seed", 0), exit_d, enter_d, hold)
    for key in ("paper", "live_enter"):
        if key in data:
            inner[key] = data[key]
    built = transition(inner, workspace_dir)
    edited = _assemble(clips, anchor, split, from_source, to_source, built, exit_d, enter_d)
    _audio(loaded, edited, clips, spans, anchor, _duration(clips, spans), root, cache)
    saved = _keep(store, root, workspace, file, previous, revision, loaded, pristine)
    warnings = _repeats(list(built.get("warnings") or []), samples)
    return {**built, "warnings": warnings, "montage": saved}


def _mode(value) -> str:
    if value in ("insert", "replace"):
        return str(value)
    raise World3DSceneError("invalid_mode", "mode is insert or replace")


def _open(store: MontageStore, root: Path, workspace: str, montage):
    """A file name is revised in place. A document is not written until the render succeeds."""
    if isinstance(montage, str):
        found = store.get(workspace, montage)
        path = root / found["file"]
        previous = path.read_text(encoding="utf-8")
        loaded = json.loads(previous)
        return loaded, found["file"], previous, int(loaded.get("revision") or 1)
    if isinstance(montage, dict):
        return copy.deepcopy(montage), None, None, 0
    raise World3DSceneError("invalid_montage", "montage is a .montage.json name or a document")


def _probe(source: str, root: Path, cache: dict) -> dict:
    if source not in cache:
        path = _read_path(source, root)
        try:
            facts = probe_media(str(path))
        except ValueError as exc:
            raise World3DSceneError("missing_source", str(exc)) from exc
        facts["path"] = path
        cache[source] = facts
    return cache[source]


def _spans(clips: list[dict], root: Path, cache: dict) -> list[tuple[float, float, float]]:
    spans = []
    for clip in clips:
        start = float(clip.get("trimStart") or 0)
        end = float(clip.get("trimEnd") or 0)
        if end <= start:
            end = float(_probe(str(clip.get("source") or ""), root, cache)["duration"])
        if end - start < _GAP:
            raise World3DSceneError("clip_too_short", "A clip is shorter than a frame")
        spans.append((end - start, start, end))
    return spans


def _overlap(clips: list[dict], spans, index: int) -> float:
    if index + 1 >= len(clips):
        return 0.0
    kind = str(clips[index].get("transition") or "none")
    if kind == "none":
        return 0.0
    raw = float(clips[index].get("transitionDuration") or 0.5)
    if kind in _INTERSTITIAL:
        return max(0.5, min(raw, 5.0))
    own, nxt = spans[index][0], spans[index + 1][0]
    return max(0.05, min(raw, own * 0.45, nxt * 0.45))


def _starts(clips: list[dict], spans) -> list[float]:
    cursor = 0.0
    starts = []
    for index, span in enumerate(spans):
        starts.append(cursor)
        overlap = _overlap(clips, spans, index)
        kind = str(clips[index].get("transition") or "none")
        cursor += span[0] + (overlap if kind in _INTERSTITIAL else -overlap)
    return starts


def _duration(clips: list[dict], spans) -> float:
    total = 0.0
    for index, span in enumerate(spans):
        overlap = _overlap(clips, spans, index)
        kind = str(clips[index].get("transition") or "none")
        total += span[0] + (overlap if kind in _INTERSTITIAL else -overlap)
    return max(0.0, total)


def _boundary_time(clips, spans, starts, index: int) -> float:
    start, duration = starts[index], spans[index][0]
    kind = str(clips[index].get("transition") or "none")
    if kind == "none" or kind in _INTERSTITIAL:
        return start + duration
    return max(start, start + duration - _overlap(clips, spans, index))


def _as_index(between, count: int):
    if isinstance(between, bool) or not isinstance(between, int):
        return None
    if 0 <= between <= count - 2:
        return between
    return None


def _nearest(clips, spans, starts, seconds: float):
    found = None
    for index in range(len(clips) - 1):
        at = _boundary_time(clips, spans, starts, index)
        gap = abs(at - seconds)
        if found is None or gap < found[0]:
            found = (gap, index, at)
    if found and found[0] <= _GAP:
        return "boundary", found[1], found[2]
    return None


def _locate(clips, spans, starts, between):
    indexed = _as_index(between, len(clips))
    if indexed is not None:
        return "boundary", indexed, _boundary_time(clips, spans, starts, indexed)
    if isinstance(between, bool) or not isinstance(between, (int, float)) or float(between) < 0:
        raise World3DSceneError("invalid_between", "between is a clip index or a time in seconds")
    seconds = float(between)
    snapped = _nearest(clips, spans, starts, seconds)
    if snapped is not None:
        return snapped
    end = starts[-1] + spans[-1][0]
    if seconds > end + 1e-3:
        raise World3DSceneError("invalid_between", "between is past the end of the montage")
    for index in range(len(starts) - 1, -1, -1):
        if seconds >= starts[index] - 1e-6:
            return "split", index, seconds
    return "split", 0, seconds


def _plan(kind, index, cut, mode, exit_d, enter_d, starts, spans):
    if mode == "insert":
        return _insert_plan(kind, index, cut, starts, spans)
    return _replace_plan(kind, index, cut, exit_d, enter_d, starts, spans)


def _insert_plan(kind, index, cut, starts, spans):
    if kind == "boundary":
        return index, False, spans[index][2], spans[index + 1][1]
    at = _along(spans[index], starts[index], cut)
    if at - spans[index][1] < _GAP or spans[index][2] - at < _GAP:
        raise World3DSceneError("clip_too_short", "The clip is too short to split here")
    return index, True, at, at


def _replace_plan(kind, index, cut, exit_d, enter_d, starts, spans):
    opening, closing = cut - exit_d, cut + enter_d
    if kind == "boundary":
        _room(opening, starts[index], closing, starts[index + 1] + spans[index + 1][0])
        from_source = _along(spans[index], starts[index], opening)
        to_source = _along(spans[index + 1], starts[index + 1], closing)
        _leftover(spans[index], spans[index + 1], from_source, to_source)
        return index, False, from_source, to_source
    _room(opening, starts[index], closing, starts[index] + spans[index][0])
    from_source = _along(spans[index], starts[index], opening)
    to_source = _along(spans[index], starts[index], closing)
    _leftover(spans[index], spans[index], from_source, to_source)
    return index, True, from_source, to_source


def _room(opening, start, closing, end) -> None:
    if opening < start + _GAP or closing > end - _GAP:
        raise World3DSceneError("clip_too_short", "replace needs room on both sides of the cut")


def _leftover(left, right, from_source, to_source) -> None:
    if from_source - left[1] < _GAP or right[2] - to_source < _GAP:
        raise World3DSceneError("clip_too_short", "replace needs room on both sides of the cut")


def _along(span, start: float, time: float) -> float:
    return min(span[2], max(span[1], span[1] + (time - start)))


def _apart(anchor: float, delta: float, duration: float) -> float:
    limit = max(0.0, duration - 0.04)
    candidate = min(max(0.0, anchor + delta), limit)
    if abs(candidate - anchor) >= _GAP:
        return candidate
    other = min(max(0.0, anchor - delta), limit)
    if abs(other - anchor) > abs(candidate - anchor):
        return other
    return candidate


def _samples(clips, anchor, split, from_source, to_source, root, cache):
    left = str(clips[anchor].get("source") or "")
    right = left if split else str(clips[anchor + 1].get("source") or "")
    before = _apart(from_source, -_NEIGHBOUR, float(_probe(left, root, cache)["duration"]))
    after = _apart(to_source, _NEIGHBOUR, float(_probe(right, root, cache)["duration"]))
    return [(left, before), (left, from_source), (right, to_source), (right, after)]


def _extract(samples, root: Path, cache: dict) -> list[str]:
    panels = []
    root.mkdir(parents=True, exist_ok=True)
    for index, (source, at) in enumerate(samples):
        dest = root / f"comic-boundary-{index}.png"
        path = _probe(source, root, cache)["path"]
        try:
            extract_frame(str(path), str(dest), float(at))
        except (RuntimeError, ValueError, OSError) as exc:
            raise World3DSceneError("missing_source", f"could not read a boundary frame: {exc}") from exc
        panels.append(str(dest))
    return panels


def _format(data, source: str, root: Path, cache: dict) -> str:
    fmt = data.get("format")
    if fmt in ("landscape", "portrait"):
        return str(fmt)
    if fmt is not None:
        raise World3DSceneError("invalid_format", "format is landscape or portrait")
    media = _probe(source, root, cache)
    if int(media["height"]) > int(media["width"]):
        return "portrait"
    return "landscape"


def _inner(workspace, fmt, panels, seed, exit_d, enter_d, hold) -> dict:
    return {
        "workspace": workspace, "format": fmt, "panels": panels, "from_panel": 1, "to_panel": 2,
        "export": True, "seed": seed, "exit_duration": exit_d, "enter_duration": enter_d, "hold": hold,
    }


def _fresh(clips, base: str) -> str:
    taken = {clip.get("id") for clip in clips}
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"


def _comic_clip(clips, role: str, url: str, duration: float, scene_id: str) -> dict:
    base = "comic-exit" if role == "exit" else "comic-enter"
    return {
        "id": _fresh(clips, base), "name": "Comic exit" if role == "exit" else "Comic enter",
        "source": url, "trimStart": 0, "trimEnd": duration, "volume": 0, "muted": True,
        "transition": "none", "transitionDuration": 0.5, "fit": "fit",
        "origin": {"kind": "scene3d", "scene": scene_id},
    }


def _pair(built: dict, role: str):
    clip = next(item for item in built.get("clips") or [] if item.get("role") == role)
    scene = next(item for item in built.get("scenes") or [] if item.get("role") == role)
    url = clip.get("url")
    if not url:
        raise World3DSceneError("export_failed", "The comic clip has no file")
    return str(url), str(scene.get("sceneId") or "")


def _assemble(clips, anchor, split, from_source, to_source, built, exit_d, enter_d):
    left = dict(clips[anchor])
    left["trimEnd"] = from_source
    left["transition"] = "none"
    if split:
        right = dict(clips[anchor])
        right.pop("takes", None)
        right.pop("lyric", None)
        right["id"] = _fresh(clips, f"{left.get('id') or 'clip'}-next")
        right["trimStart"] = to_source
        tail = clips[anchor + 1:]
    else:
        right = dict(clips[anchor + 1])
        right["trimStart"] = to_source
        tail = clips[anchor + 2:]
    exit_url, exit_scene = _pair(built, "exit")
    enter_url, enter_scene = _pair(built, "enter")
    exit_clip = _comic_clip([*clips, left, right], "exit", exit_url, exit_d, exit_scene)
    enter_clip = _comic_clip([*clips, left, right, exit_clip], "enter", enter_url, enter_d, enter_scene)
    return [*clips[:anchor], left, exit_clip, enter_clip, right, *tail]


def _audio(document, edited, original, spans, anchor, duration, root, cache) -> None:
    source = str(original[anchor].get("source") or "")
    document["clips"] = edited
    if document.get("soundtrack") or not _probe(source, root, cache).get("has_audio"):
        return
    for clip in edited:
        clip["muted"] = True
        clip["volume"] = 0
    same = str(original[0].get("source") or "") == source
    trim_start = spans[0][1] if same else spans[anchor][1]
    document["soundtrack"] = {
        "name": "song", "source": source, "trimStart": trim_start, "trimEnd": trim_start + duration,
        "volume": 1, "loop": False,
    }


def _keep(store, root, workspace, file, previous, revision, loaded, pristine) -> dict:
    if file is None:
        stored = store.save(workspace, pristine)
        file = stored["file"]
        previous = (root / file).read_text(encoding="utf-8")
        revision = int(stored["revision"])
    backup = f"{file.removesuffix(SUFFIX)}.r{revision}.montage.json"
    (root / backup).write_text(previous, encoding="utf-8")
    saved = store.save(workspace, loaded, file=file, expected_revision=revision)
    return {"file": saved["file"], "revision": saved["revision"], "backup": backup}


def _repeats(warnings: list, samples) -> list:
    if abs(samples[0][1] - samples[1][1]) < _GAP:
        warnings.append("neighbour panel repeats the exit frame")
    if abs(samples[3][1] - samples[2][1]) < _GAP:
        warnings.append("neighbour panel repeats the enter frame")
    return warnings
