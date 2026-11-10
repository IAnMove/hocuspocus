"""What an animation job says about its own sheet when it ends, whatever the approval mode.

The automatic checks of ``services/character_animation_checks.py`` and the gait of each pose (how wide its legs came out against its guide,
measured while the pose was drawn: ``frames[].gait``) used to reach nobody unless the owner's «Modo un solo disparo» was on. Now every job
result carries them, and approval is still decided exactly as before (only ``autoApprove`` approves; a sheet that fails stays pending):

* ``checks``   every check, each ``{"id", "ok", "value", "limit", "detail"}``.
* ``verdict``  ``{"ok", "failed": [check ids]}``, the one line of it.
* ``gait``     ``{"checked", "missed": [pose ids]}`` for a walk drawn pose by pose, where each pose has a guide to be measured against.
* ``warnings`` ``[{"code", "message", "hint"}]`` when a check failed or a pose missed its gait, or the checks could not be read. The hint
  names a remedy that exists already: make only the failing poses again (``pose``), or, for a catalog walk, ``method`` ``puppet``. A walk
  that was remade automatically says so (``autoRemake`` of the job) before the remedy: the job never switches method on its own.
"""
from __future__ import annotations

from typing import Any

from services.character_animation_checks import failed

# What each warning code means to a person or an agent reading the job.
PUPPET_NO_LAYERS = "The puppet was cut without See-through layers: the drawing needs the legs apart and no skirt."
CHECKS_UNAVAILABLE = "The automatic checks could not read the sheet, so nobody has judged it yet."
_NOTES = {"puppet_no_layers": PUPPET_NO_LAYERS}


def verdict_of(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """The sheet's checks as one line: whether every one passed and the ids of those that did not."""
    return {"ok": not failed(checks), "failed": [check["id"] for check in failed(checks)]}


def gait_of_takes(takes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Which poses missed their guide: the takes that were measured (a walk pose by pose), None when no take has a measure."""
    measured = [take for take in takes if isinstance(take.get("gait"), dict)]
    if not measured:
        return None
    return {"checked": len(measured), "missed": [take["id"] for take in measured if not take["gait"].get("ok")]}


def _remade(job: dict[str, Any]) -> str:
    """What the job already did about the poses that failed (``services/character_animation_remake.py``), as a sentence, or nothing."""
    found = job.get("autoRemake") or {}
    if not found.get("poses"):
        return ""
    ids = ", ".join(item["id"] for item in found["poses"])
    return f"The job already remade {len(found['poses'])} pose{'s' if len(found['poses']) > 1 else ''} ({ids}) in {found['rounds']} round{'s' if found['rounds'] > 1 else ''} and kept the best drawing of each. "


def _remedy(definition: dict[str, Any], job: dict[str, Any]) -> str:
    """The way out that exists: puppet only for a catalog walk (``accept_puppet`` refuses any other) that was not made that way."""
    puppet = not definition.get("custom") and definition.get("guide") == "walk" and job.get("method") != "puppet"
    again = ' or make the whole walk again with method "puppet" (one drawing cut by the walk mould, not redrawn pose by pose)' if puppet else ""
    return f"{_remade(job)}Look at the sheet, then make only the poses that are off again (pose: the pose id; the others stay){again}."


def _failed_text(checks: list[dict[str, Any]]) -> str:
    bad = failed(checks)
    listed = ", ".join(f"{check['id']} {check['value']} (limit {check['limit']})" for check in bad)
    return f"The sheet failed {len(bad)} automatic check{'s' if len(bad) > 1 else ''}: {listed}."


def _warning(code: str, message: str, hint: str | None = None) -> dict[str, str]:
    return {"code": code, "message": message, **({"hint": hint} if hint else {})}


def warnings_of(checks: list[dict[str, Any]] | None, gait: dict[str, Any] | None, definition: dict[str, Any], job: dict[str, Any]) -> list[dict[str, str]]:
    """The warnings a finished job lists: the ones its method recorded (``job["warnings"]``, codes) first, then what the checks and the
    gait say. ``checks`` is None when they could not be read."""
    found = [_warning(code, _NOTES.get(code, code)) for code in job.get("warnings") or [] if isinstance(code, str)]
    if checks is None:
        why = f" ({job['checksError']})" if job.get("checksError") else ""
        found.append(_warning("checks_unavailable", CHECKS_UNAVAILABLE[:-1] + why + "."))
    elif failed(checks):
        found.append(_warning("sheet_checks_failed", _failed_text(checks), _remedy(definition, job)))
    if gait and gait["missed"]:
        found.append(_warning("gait_missed", f"{len(gait['missed'])} of {gait['checked']} poses have the legs far from their guide: {', '.join(gait['missed'])}.",
                              _remedy(definition, job)))
    return found


def report_of(checks: list[dict[str, Any]] | None, definition: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    """The fields every job result carries about the sheet: ``checks``, ``verdict``, ``gait`` (when poses were measured) and ``warnings``
    (when there are any). ``checks`` None means they could not be read: no verdict, and a warning that says so."""
    gait = gait_of_takes(job["takes"])
    warnings = warnings_of(checks, gait, definition, job)
    return {**({"checks": checks, "verdict": verdict_of(checks)} if checks is not None else {}),
            **({"gait": gait} if gait else {}), **({"warnings": warnings} if warnings else {})}
