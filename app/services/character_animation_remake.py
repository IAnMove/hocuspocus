"""Remake the poses of a walk that fail, before the sheet is joined (``services/character_animation_job.py`` calls ``run`` once per job).

The first pass draws every pose over its guide and keeps the closest of up to ``guide.tries`` drawings by the width of the legs. That cannot
see the order of the poses or which foot is lower, so a sheet came out with poses that no single measure had judged and the owner remade
them by hand. After the first pass this module reads the keyed pictures the way the sheet checks will (``services/walk_gait_metrics.py``) and
redraws, in up to ``guide.remake.rounds`` rounds, only the poses that fail: a pose whose legs missed its guide, or one that a failing check
blames. Each round redraws at most ``guide.remake.poses`` poses, the worst first, with ``guide.remake.tries`` new seeds each.

Of all the drawings a pose has, the one that is best in the context of the other poses stays: first not blamed by a failing check, then
with the legs near its guide, then with the lowest ``cell_scores``. Every drawing is recorded (``attempts`` of the take: round, seed, raw
and keyed picture, gait; the job's ``autoRemake`` lists them with their score and which one was kept), so a person can see what was tried.

A tool error while remaking never fails the job: the pose keeps the drawing it had and the rounds stop (``error``). A cancel goes on to
the job, which is cancelled. Only a catalog walk drawn pose by pose and asked for the ``gait`` check is remade (``applies``); a single pose
the person asked to make again is not followed by more.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PIL import Image

from services.character_animation_directions import contract_of
from services.character_animations import catalog
from services.walk_gait_metrics import blamed_cells, cell_scores, mask_of

# What a take keeps of one drawing: restored when another drawing of the pose is the better one.
DRAWING = ("raw", "keyed", "seed", "gait")


def settings(rounds: int | None = None) -> dict[str, int]:
    """``rounds`` (0 turns the remake off), ``poses`` per round and ``tries`` per pose: the catalog's ``guide.remake``, ``rounds`` overridable."""
    spec = (catalog().get("guide") or {}).get("remake") or {}
    return {"rounds": max(0, int(spec.get("rounds", 2) if rounds is None else rounds)), "poses": max(1, int(spec.get("poses", 4))),
            "tries": max(1, int(spec.get("tries", 2)))}


def applies(job: dict[str, Any]) -> bool:
    """A catalog walk drawn pose by pose whose animation asks for the gait check, and not one pose made again on a person's request."""
    definition = job["definition"]
    return (job.get("method") not in ("video", "puppet") and not job.get("remake") and not definition.get("custom")
            and definition.get("guide") == "walk" and "gait" in (definition.get("checks") or []))


def _masks(job: dict[str, Any], resolve: Callable[[str], str], floor: int) -> list[Any]:
    found = []
    for take in job["takes"]:
        try:
            with Image.open(resolve(take["keyed"])) as opened:
                found.append(mask_of(opened.convert("RGBA"), floor))
        except (OSError, ValueError, KeyError):
            found.append(None)  # a picture that cannot be read is an empty cell: the checks do not judge it
    return found


def _missed(take: dict[str, Any]) -> bool:
    return isinstance(take.get("gait"), dict) and not take["gait"].get("ok")


def failing(job: dict[str, Any], masks: list[Any], direction: str | None) -> list[int]:
    """The indexes of the poses to remake: those a failing check blames and those whose legs missed their guide, worst first."""
    wanted = set(blamed_cells(masks, direction)) | {index for index, take in enumerate(job["takes"]) if _missed(take)}
    scores = cell_scores(masks, direction)
    return sorted(wanted, key=lambda index: (-scores[index], index))


def _fields(take: dict[str, Any]) -> dict[str, Any]:
    return {key: take[key] for key in DRAWING if key in take}


def _judge(job: dict[str, Any], masks: list[Any], index: int, candidate: dict[str, Any], resolve: Callable[[str], str], floor: int,
           direction: str | None) -> tuple[int, int, float]:
    """The sort key of one drawing of pose ``index`` in the context of the others (lower is better)."""
    try:
        with Image.open(resolve(candidate["keyed"])) as opened:
            placed = [*masks[:index], mask_of(opened.convert("RGBA"), floor), *masks[index + 1:]]
    except (OSError, ValueError, KeyError):
        return 2, 2, 9e9
    gait = candidate.get("gait")
    return (int(index in blamed_cells(placed, direction)), int(isinstance(gait, dict) and not gait.get("ok")), cell_scores(placed, direction)[index])


def _keep_best(job: dict[str, Any], masks: list[Any], index: int, resolve: Callable[[str], str], floor: int, direction: str | None) -> dict[str, Any]:
    """Put the best drawing of the pose back on its take and return the record of every drawing with its score and which one stays."""
    take = job["takes"][index]
    drawings = take.get("attempts") or [{"round": 0, **_fields(take)}]
    keys = [_judge(job, masks, index, drawing, resolve, floor, direction) for drawing in drawings]
    best = min(range(len(drawings)), key=lambda place: keys[place])
    take.update({key: drawings[best][key] for key in DRAWING if key in drawings[best]})
    masks[index] = _masks({"takes": [take]}, resolve, floor)[0]
    return {"id": take["id"], "attempts": [{**drawing, "score": round(keys[place][2], 3), "kept": place == best} for place, drawing in enumerate(drawings)]}


def run(job: dict[str, Any], *, resolve: Callable[[str], str], redraw: Callable[[dict[str, Any], int, int, int], None], stop: Callable[[], None],
        update: Callable[[], None], floor: int = 8, rounds: int | None = None) -> dict[str, Any] | None:
    """The rounds of remakes. ``redraw(take, tries, offset, round)`` draws a pose again into its take (``offset`` keeps the file names of the
    drawings apart); ``stop()`` raises when the job was cancelled. Returns what ``autoRemake`` records, None when nothing needed redrawing."""
    plan = settings(rounds)
    direction = contract_of(job["definition"]["id"], job["definition"]).get("dir")
    summary: dict[str, Any] = {"rounds": 0, "max": plan["rounds"], "poses": [], "records": {}}
    done = 0
    for number in range(1, plan["rounds"] + 1):
        masks = _masks(job, resolve, floor)
        picks = failing(job, masks, direction)[:plan["poses"]]
        if not picks:
            break
        summary["rounds"] = number
        for index in picks:
            stop()
            take = job["takes"][index]
            held = _fields(take)
            take.setdefault("attempts", [{"round": 0, **held}])
            try:
                redraw(take, plan["tries"], 10 * number, number)
            except Exception as error:  # noqa: BLE001 - a remake never costs the sheet that was already drawn
                if getattr(error, "code", "") == "cancelled":
                    take.update(held, status="ready")
                    raise
                take.update(held, status="ready")
                summary["error"] = str(error)[:300]
                return _closed(job, summary, masks, resolve, floor, direction)
            summary["records"][take["id"]] = _keep_best(job, masks, index, resolve, floor, direction)
            update()
            done += 1
    return _closed(job, summary, _masks(job, resolve, floor), resolve, floor, direction) if done else None


def _closed(job: dict[str, Any], summary: dict[str, Any], masks: list[Any], resolve: Callable[[str], str], floor: int, direction: str | None) -> dict[str, Any]:
    """The summary as the job records it: the poses that were remade, each with every drawing, and the poses that still fail."""
    summary["poses"] = list(summary.pop("records").values())
    summary["failing"] = [job["takes"][index]["id"] for index in failing(job, masks, direction)]
    return summary
