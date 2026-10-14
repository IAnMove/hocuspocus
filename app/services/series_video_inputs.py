"""What else a scripted H3 clip depends on, kept on its take as ``videoInputs``, and the one rule that reads it.

``videoRequest`` (``series_video_shots.digest_request``) digests the script's ``video`` object and the clip's size
tier. It stays exactly as it was, so every take made before keeps matching. Three more inputs choose the picture and
were never in it; they travel in one more optional digest per take:

* ``orientation``: the series frame is portrait (704x1280, not 1280x704);
* ``plan``: for ``start: "plan"``, the 2D cast (character, pose, position) and the location plate the start frame is
  composed from;
* ``start``: for a named start (``pose:<character>/<pose>``, a workspace file or an asset), the pixels of that file.

Only the parts that apply are hashed, and a take always records the digest it was made with, even when no part
applied, so a cast member added later is seen. A take without ``videoInputs`` was made before this existed: it
matches on ``videoRequest`` alone. That is the cost of not generating again what is probably right: a legacy take
that was already out of date (a series turned portrait last week, a plate overwritten) is not seen; remake it by
hand. ``inputs`` is None when a current part cannot be read (a named start that resolves to no file); nothing is
then compared, because remaking a clip on a read that failed would spend a generation for nothing.

``matching_attempts`` is the one matcher: completed takes that asked for this request with these inputs.
``repair_approval`` points the shot's approval at such a take when it points at none or at a take of another request,
and never over a take a person chose.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Metadata a take made by ``series_video_shots`` carries; an import by hand carries neither.
REQUEST_KEY = "videoRequest"
INPUTS_KEY = "videoInputs"
# Who approves a take on purpose (``approvedBy``); ``server`` is a produce or render run approving what it made.
_PEOPLE = ("user", "agent", "wizard")


def inputs_digest(parts: dict[str, Any]) -> str:
    """The digest of the parts that apply. No part at all is a digest too: it is not the absence of one."""
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:12]


def inputs_match(metadata: dict[str, Any], inputs: str | None) -> bool:
    """A take without ``videoInputs`` is a legacy take and matches; so does any take when ``inputs`` is unknown."""
    stored = metadata.get(INPUTS_KEY)
    return stored is None or inputs is None or stored == inputs


def matching_attempts(series: dict[str, Any], shot: dict[str, Any], request: str, inputs: str | None) -> list[dict[str, Any]]:
    """Completed attempts of the shot whose take asked for ``request`` with ``inputs``, latest first."""
    assets = series.get("assets") or {}
    found = []
    for attempt in reversed(shot.get("attempts") or []):
        if not isinstance(attempt, dict) or attempt.get("status") != "completed":
            continue
        for asset_id in attempt.get("outputAssetIds") or []:
            metadata = (assets.get(asset_id) or {}).get("metadata") or {}
            if metadata.get(REQUEST_KEY) == request and inputs_match(metadata, inputs):
                found.append(attempt)
                break
    return found


def repair_approval(series: dict[str, Any], episode: dict[str, Any], index: int, request: str, inputs: str | None,
                    *, preview: bool) -> str | None:
    """Approve the shot's latest matching take when the shot is approved on none, or on a take another request made.

    Returns the attempt id it approved, None when it left the shot alone. It is left alone when the approved take
    itself matches (a person may have chosen the older of two), when it was imported by hand, when a person (in
    Series Lab, through an agent or the Wizard: ``approvedBy``) approved it, when a person rejected the matching take,
    and in a preview review when nothing is approved or the matching take was never approved: a draft nobody looked
    at is not approved here. The language versions' approvals are their own and are never touched."""
    from services.series_library import approve_shot_render_attempt

    shot = episode["shots"][index]
    matching = matching_attempts(series, shot, request, inputs)
    held = _held(shot)
    if not matching or (held is None and preview):
        return None
    if held is not None and (_matches(held, matching) or not _made_by_produce(series, held) or _chosen(held)):
        return None
    candidates = [item for item in matching if item.get("reviewDecision") != "rejected"
                  and (not preview or item.get("approvedAt"))]
    if not candidates:
        return None
    try:
        episode["shots"][index] = approve_shot_render_attempt(shot, str(candidates[0].get("id")), "server")
    except ValueError:
        return None
    return str(candidates[0].get("id"))


def _held(shot: dict[str, Any]) -> dict[str, Any] | None:
    """The shot's approved attempt when it is a usable take; a dangling or unfinished approval counts as none."""
    wanted = shot.get("approvedAttemptId")
    attempt = next((item for item in shot.get("attempts") or [] if isinstance(item, dict) and item.get("id") == wanted), None)
    return attempt if attempt and attempt.get("status") == "completed" and attempt.get("outputAssetIds") else None


def _chosen(attempt: dict[str, Any]) -> bool:
    """Approved by a person, an agent or the Wizard (``series_library.REVIEWERS``), not by a produce run (``server``).
    Every take produce makes has carried ``approvedBy`` since before scripted video existed; none means produce."""
    return attempt.get("approvedBy") in _PEOPLE


def _matches(attempt: dict[str, Any], matching: list[dict[str, Any]]) -> bool:
    return any(item.get("id") == attempt.get("id") for item in matching)


def _made_by_produce(series: dict[str, Any], attempt: dict[str, Any]) -> bool:
    """The take carries the request digest produce writes; an import by hand does not."""
    assets = series.get("assets") or {}
    return any(((assets.get(asset_id) or {}).get("metadata") or {}).get(REQUEST_KEY) is not None
               for asset_id in attempt.get("outputAssetIds") or [])
