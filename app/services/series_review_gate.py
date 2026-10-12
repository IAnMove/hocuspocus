"""What an episode's staged review (``series_review``) lets the server render and assemble.

``direct`` episodes are not gated at all. In ``plan`` mode a shot renders once its plan is approved, as it always
rendered. In ``preview`` mode each shot the native render is asked for gets one pass:

* ``preview``: the first look at an approved plan. It is the cheapest faithful render the server has: a 2D shot is
  rendered exactly as its final would be (the headless Video 2D export has one quality, and it is quick), a 3D shot
  is exported at ``draft`` quality (no supersampling or motion blur) whatever its ``scene3d.quality``. The take is
  marked ``reviewStage: "preview"`` and is never approved for the assembly.
* ``final``: after the preview is approved. A 3D shot is exported at its own quality; the take is marked ``final``
  and approved.
* ``promote``: the approved preview already is the final (a 2D shot, or a 3D shot at draft quality) and nothing it was
  made from changed: it is approved as the shot's take, nothing renders.

A generated or imported take is never rendered by the server (only its foley is): once its preview is approved it is
promoted to the shot's take, and its foley is made as in plan mode.

A shot whose plan is not approved, or whose current preview waits for the user, is reported as waiting, not failed.
Language versions follow the original's review: a version renders a shot once the original's plan (``plan``) or
preview (``preview``) is approved, at full quality.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from services.series_library import VIDEO_TAKE_METHODS
from services.series_review import (
    approved_take, episode_mode, full_quality, latest_take, preview_ready, shot_entry,
)


def take_inputs(series: dict, attempt: dict | None) -> str | None:
    """The render inputs a take was made from (``series_take_inputs.render_inputs``, kept on its asset)."""
    outputs = (attempt or {}).get("outputAssetIds") or []
    asset = (series.get("assets") or {}).get(outputs[0]) if outputs else None
    return ((asset or {}).get("metadata") or {}).get("renderInputs")


def _attempt(shot: dict, attempt_id: Any) -> dict | None:
    return next((item for item in shot.get("attempts") or [] if attempt_id and item.get("id") == attempt_id), None)


def _preview_pass(series: dict, shot: dict, entry: dict, inputs: Callable[[dict], str], explicit: bool) -> tuple[str, str | None]:
    current = inputs(shot)
    if entry["preview"] == "approved":
        if not explicit and preview_ready(shot, entry) and take_inputs(series, approved_take(shot)) == current:
            return "skip", None
        reviewed = _attempt(shot, entry.get("previewAttemptId"))
        if (not explicit and reviewed and full_quality(shot, reviewed) and take_inputs(series, reviewed) == current
                and reviewed.get("id") != shot.get("approvedAttemptId")):
            return "promote", reviewed["id"]
        return "final", None
    latest = latest_take(shot)
    if not explicit and latest is not None and take_inputs(series, latest) == current:
        return "wait", "preview"
    return "preview", None


def _video_pass(shot: dict, entry: dict) -> tuple[str, str | None]:
    """A generated or imported take is not rendered here (only its foley is): an approved preview of it becomes the
    shot's take, and its foley is made like in plan mode."""
    reviewed = entry.get("previewAttemptId")
    if entry["preview"] == "approved" and reviewed and reviewed != shot.get("approvedAttemptId"):
        return "promote", reviewed
    return "render", None


def video_promotion(episode: dict, shot: dict) -> str | None:
    """The reviewed video take still to approve, including videos with no foley prompt."""
    if episode_mode(episode) != "preview" or shot.get("productionMethod") not in VIDEO_TAKE_METHODS:
        return None
    entry = shot_entry(episode, str(shot.get("id")))
    return _video_pass(shot, entry)[1] if entry["plan"] == "approved" else None


def shot_pass(series: dict, episode: dict, shot: dict, inputs: Callable[[dict], str], *, explicit: bool,
              original: bool = True) -> tuple[str, str | None]:
    """(pass, detail) for one shot: ``render`` (plan mode or direct), ``preview``, ``final``, ``promote`` (detail: the
    take to approve), ``skip`` (up to date) or ``wait`` (detail: ``plan`` or ``preview``)."""
    mode = episode_mode(episode)
    if mode == "direct":
        return "render", None
    entry = shot_entry(episode, str(shot.get("id")))
    if entry["plan"] != "approved":
        return "wait", "plan"
    if mode == "plan":
        return "render", None
    if shot.get("productionMethod") in VIDEO_TAKE_METHODS:
        return _video_pass(shot, entry)
    if not original:
        return ("final", None) if entry["preview"] == "approved" else ("wait", "preview")
    return _preview_pass(series, shot, entry, inputs, explicit)


def render_passes(series: dict, episode: dict, shots: list[dict], inputs: Callable[[dict], str], *, explicit: bool,
                  original: bool = True) -> tuple[list[dict], list[dict]]:
    """The work the native render does for ``shots`` in the episode's mode: ``[{shot, pass, attemptId?}]`` (pass None
    in direct and plan modes) and the shots that wait for an approval ``[{shotId, reason}]``."""
    planned: list[dict] = []
    waiting: list[dict] = []
    for shot in shots:
        kind, detail = shot_pass(series, episode, shot, inputs, explicit=explicit, original=original)
        if kind == "wait":
            waiting.append({"shotId": shot["id"], "reason": detail})
        elif kind != "skip":
            planned.append({"shot": shot, "pass": None if kind == "render" else kind,
                            **({"attemptId": detail} if detail else {})})
    return planned, waiting


def actionable_shots(series: dict, episode: dict, shots: list[dict], inputs: Callable[[dict], str], stale: list[str],
                     *, original: bool = True) -> list[str]:
    """Shots ``series.episode.produce`` renders: the out-of-date ones (``stale``) that the review lets through, and in
    preview mode every shot that needs a preview, a final or a promotion."""
    mode = episode_mode(episode)
    if mode == "direct":
        return list(stale)
    if mode == "preview" and original:
        shots = [shot for shot in shots if shot.get("productionMethod") not in VIDEO_TAKE_METHODS
                 or shot["id"] in stale or video_promotion(episode, shot)]
        planned, _waiting = render_passes(series, episode, shots, inputs, explicit=False)
        return [item["shot"]["id"] for item in planned]
    planned, _waiting = render_passes(series, episode, [shot for shot in shots if shot["id"] in set(stale)], inputs,
                                      explicit=False, original=original)
    return [item["shot"]["id"] for item in planned]


def waiting_shots(episode: dict) -> list[dict]:
    """``[{shotId, order, reason}]`` the assembly of a staged episode waits for: ``plan`` (not approved), ``preview``
    (preview mode, not approved) or ``final`` (preview approved, the final take not made yet)."""
    mode = episode_mode(episode)
    if mode == "direct":
        return []
    blockers = []
    for shot in sorted((item for item in episode.get("shots") or [] if isinstance(item, dict)),
                       key=lambda item: (int(item.get("order") or 0), str(item.get("id") or ""))):
        reason = _blocker(mode, shot, shot_entry(episode, str(shot.get("id"))))
        if reason:
            blockers.append({"shotId": shot.get("id"), "order": shot.get("order"), "reason": reason})
    return blockers


def _blocker(mode: str, shot: dict, entry: dict) -> str | None:
    if entry["plan"] != "approved":
        return "plan"
    if mode == "plan":
        return None
    if entry["preview"] != "approved":
        return "preview"
    return None if preview_ready(shot, entry) else "final"


def assembly_blockers(episode: dict, *, original: bool = True) -> list[dict]:
    """What keeps a staged episode from being assembled. A language version needs the original's approvals only:
    its takes are rendered as finals."""
    blockers = waiting_shots(episode)
    return blockers if original else [item for item in blockers if item["reason"] != "final"]


def blocker_message(blockers: list[dict]) -> str:
    counts = {reason: sum(1 for item in blockers if item["reason"] == reason) for reason in ("plan", "preview", "final")}
    parts = [f"{counts['plan']} shot plans to approve" if counts["plan"] else "",
             f"{counts['preview']} previews to approve" if counts["preview"] else "",
             f"{counts['final']} final takes to render" if counts["final"] else ""]
    first = ", ".join(f"#{item['order']}" for item in blockers[:6])
    return (f"This episode is produced with a staged review and is not ready to assemble: "
            f"{'; '.join(part for part in parts if part)} (shots {first}{'…' if len(blockers) > 6 else ''}). "
            "Approve them in Series Lab (Validation) or with series.shot.review.set, render what is missing, or force the assembly.")
