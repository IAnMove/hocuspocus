"""Remember every song candidate and switch to one without deleting clips."""
from __future__ import annotations

import json
from typing import Any

WINDOW_MOVE = 0.3


class SongSwitchError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def remember_candidates(state: dict, candidates: dict[str, dict]) -> None:
    """Keep file, recall and tail for every candidate. The winner still lives in ``state["song"]``."""
    rows = []
    for seed, item in candidates.items():
        if not isinstance(item, dict) or not item.get("file"):
            continue
        rows.append({
            "id": str(seed),
            "file": item["file"],
            "recall": item.get("recall"),
            "tail_rms": item.get("tail_rms"),
            "score_file": item.get("score_file"),
        })
    state["song_candidates"] = rows


def find_candidate(state: dict, candidate: str) -> dict:
    wanted = str(candidate)
    for row in state.get("song_candidates") or []:
        if isinstance(row, dict) and wanted in (row.get("id"), row.get("file")):
            return row
    raise SongSwitchError("candidate_not_found", f"no song candidate {wanted}")


def windows_by_key(spec: dict, score: dict) -> dict[str, tuple[float, float]]:
    from services.music_production import shot_windows
    return {row["key"]: (float(row["t0"]), float(row["t1"])) for row in shot_windows(spec, score)}


def mark_moved_clips(state: dict, before: dict[str, tuple[float, float]], after: dict[str, tuple[float, float]],
                     limit: float = WINDOW_MOVE) -> list[str]:
    """Flag clips whose audio window moved. The files stay on disk."""
    obsolete: list[str] = []
    clips = state.get("clips") or {}
    for key, clip in clips.items():
        if not isinstance(clip, dict):
            continue
        old, new = before.get(key), after.get(key)
        # Windows are stored to the millisecond. A raw float 0.3 is slightly over 0.3 and must still count as kept.
        moved = _window_moved(old, new, limit)
        if moved:
            clip["obsolete"] = True
            obsolete.append(key)
        else:
            clip.pop("obsolete", None)
    return obsolete


def _window_moved(old: tuple[float, float] | None, new: tuple[float, float] | None, limit: float = WINDOW_MOVE) -> bool:
    return old is None or new is None or round(abs(old[0] - new[0]), 3) > limit or round(abs(old[1] - new[1]), 3) > limit


def _read_score(production: Any, name: Any) -> dict[str, Any] | None:
    if not isinstance(name, str) or not name or ".." in name:
        return None
    path = production.root / name
    if not path.is_file():
        return None
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _locked_moved(production: Any, before: dict[str, tuple[float, float]], after: dict[str, tuple[float, float]]) -> list[str]:
    from services.production_shot_review import is_locked

    blocked = []
    for key, clip in (production.state.get("clips") or {}).items():
        if not isinstance(clip, dict):
            continue
        if _window_moved(before.get(key), after.get(key)) and is_locked(production, key):
            blocked.append(key)
    return sorted(blocked)


def use_candidate(production: Any, spec: dict, candidate: str) -> dict[str, Any]:
    """Point the production at ``candidate``, re-analyse it, and flag clips whose window moved."""
    chosen = find_candidate(production.state, candidate)
    current = production.score() if production.state.get("score") else {}
    before = windows_by_key(spec, current) if current else {}
    peeked = _read_score(production, chosen.get("score_file"))
    if peeked is not None and before:
        blocked = _locked_moved(production, before, windows_by_key(spec, peeked))
        if blocked:
            raise SongSwitchError("shot_locked", "locked: " + ", ".join(blocked))
    previous_song = production.state.get("song")
    previous_score = production.state.get("score")
    production.state["song"] = {"file": chosen["file"], "recall": chosen.get("recall"), "tail_rms": chosen.get("tail_rms")}
    production.state.pop("score", None)
    production.analyze(spec)
    after = windows_by_key(spec, production.score())
    blocked = _locked_moved(production, before, after)
    if blocked:
        production.state["song"] = previous_song
        if previous_score:
            production.state["score"] = previous_score
        else:
            production.state.pop("score", None)
        production.save()
        raise SongSwitchError("shot_locked", "locked: " + ", ".join(blocked))
    obsolete = mark_moved_clips(production.state, before, after)
    production.save()
    clips = production.state.get("clips") or {}
    return {"song": production.state["song"]["file"], "obsolete": obsolete, "kept": [key for key in clips if key not in obsolete]}
