"""Remember every song candidate and switch to one without deleting clips."""
from __future__ import annotations

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
        moved = old is None or new is None or round(abs(old[0] - new[0]), 3) > limit or round(abs(old[1] - new[1]), 3) > limit
        if moved:
            clip["obsolete"] = True
            obsolete.append(key)
        else:
            clip.pop("obsolete", None)
    return obsolete


def use_candidate(production: Any, spec: dict, candidate: str) -> dict[str, Any]:
    """Point the production at ``candidate``, re-analyse it, and flag clips whose window moved."""
    chosen = find_candidate(production.state, candidate)
    current = production.score() if production.state.get("score") else {}
    before = windows_by_key(spec, current) if current else {}
    production.state["song"] = {"file": chosen["file"], "recall": chosen.get("recall"), "tail_rms": chosen.get("tail_rms")}
    production.state.pop("score", None)
    production.analyze(spec)
    obsolete = mark_moved_clips(production.state, before, windows_by_key(spec, production.score()))
    production.save()
    clips = production.state.get("clips") or {}
    return {"song": production.state["song"]["file"], "obsolete": obsolete, "kept": [key for key in clips if key not in obsolete]}
