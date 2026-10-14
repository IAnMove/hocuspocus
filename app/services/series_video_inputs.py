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
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Metadata a take made by ``series_video_shots`` carries; an import by hand carries neither.
REQUEST_KEY = "videoRequest"
INPUTS_KEY = "videoInputs"


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
