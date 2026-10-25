"""Gaussian-splat sets: a .ply or .spz already in the workspace.

``spec.sets.NAME = {kind: "splat", file | image | prompt, floorY?, scale?}``.

``file`` is a workspace-relative ``.ply`` or ``.spz``. It needs no GPU and no
optional component, and it works on every platform. ``image`` and ``prompt``
are the shape a generator would take. The FlashWorld weights
(``imlixinyang/FlashWorld`` ``model.ckpt``, 19.50 GiB) are CC-BY-NC-SA-4.0,
which forbids commercial use, so they are not integrated. Those fields fail
with that reason and do not download or enqueue anything. Spark
(``@sparkjsdev/spark``, MIT) draws the file.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

FIELDS = {"kind", "file", "image", "prompt", "floorY", "scale"}
SUFFIXES = {".ply", ".spz"}
LICENCE = ("FlashWorld weights (imlixinyang/FlashWorld model.ckpt) are CC-BY-NC-SA-4.0 "
           "and are not integrated. Use kind splat with file, a .ply or .spz already in the workspace.")
RECIPE = 1


def is_splat(entry: Any) -> bool:
    return isinstance(entry, dict) and entry.get("kind") == "splat"


def check_splat(name: str, entry: dict, text) -> str | None:
    """Why the entry is not a splat set, or None. image and prompt are valid fields that still fail closed."""
    if set(entry) - FIELDS:
        return f"sets.{name}: a splat set takes only {', '.join(sorted(FIELDS))}"
    sources = [key for key in ("file", "image", "prompt") if key in entry]
    if len(sources) != 1:
        return f"sets.{name}: a splat set needs exactly one of file, image or prompt"
    if "file" in entry:
        why = _file_shape(name, entry.get("file"))
        if why:
            return why
    elif not text(entry.get(sources[0])):
        return f"sets.{name}.{sources[0]} is text"
    if "floorY" in entry and not _number(entry["floorY"], -50, 50):
        return f"sets.{name}.floorY is metres, from -50 to 50"
    if "scale" in entry and not _number(entry["scale"], 0.05, 100):
        return f"sets.{name}.scale is from 0.05 to 100"
    return None


def recipe(entry: dict) -> dict:
    return {**entry, "recipe": RECIPE}


def is_built(record: dict) -> bool:
    return bool(record.get("url")) and not record.get("error")


def picture_jobs(production: Any, name: str, entry: dict, look: str, choice: tuple) -> dict:
    """No picture jobs. A file is recorded as a URL. image and prompt record the licence stop."""
    del look, choice
    record = production.state["sets"][name]
    record["floorY"] = float(entry.get("floorY", 0))
    record["scale"] = float(entry.get("scale", 1))
    if "file" not in entry:
        record["error"] = LICENCE
        record.pop("url", None)
        return {}
    relative = _relative(entry.get("file"))
    path = Path(production.root) / relative if relative else None
    if relative is None or Path(relative).suffix.lower() not in SUFFIXES or path is None or not path.is_file():
        record["error"] = f"sets.{name}.file is a .ply or .spz inside the workspace"
        record.pop("url", None)
        return {}
    record["file"] = relative
    record["url"] = f"/api/v1/file/{quote(relative)}?workspace={quote(production.ws)}"
    record.pop("error", None)
    production.log(f"set {name}: splat file {relative}")
    return {}


def build(production: Any, name: str, record: dict) -> None:
    """A file splat is already a URL. Nothing is assembled from pictures."""
    del production, name, record


def refusals(spec: dict, sets: dict) -> list[str]:
    """Set names whose splat record holds an error (the licence stop, or a missing file)."""
    names = spec.get("sets") or {}
    if not isinstance(names, dict) or not isinstance(sets, dict):
        return []
    return [f"set {name}" for name in names if (sets.get(name) or {}).get("kind") == "splat" and (sets.get(name) or {}).get("error")]


def refusal_error(spec: dict, sets: dict) -> str | None:
    """The make_models failure for refused splat sets, or None."""
    names = refusals(spec, sets)
    if not names:
        return None
    bits = [f"{label} ({(sets.get(label.removeprefix('set ')) or {}).get('error')})" for label in names]
    return "models failed: " + "; ".join(bits)


def _splat_file(entry: Any, made: dict, url):
    """The workspace file for a splat background, or None when this entry is another kind."""
    if isinstance(entry, dict) and "splat" in entry and entry.get("splat") is not True:
        raise ValueError("scene3d.background for a splat is {source, splat: true, floorY?, scale?}")
    inline = isinstance(entry, dict) and entry.get("splat") is True
    if made.get("kind") != "splat" and not inline:
        return None
    if made.get("kind") == "splat" and made.get("error") and not made.get("url"):
        raise ValueError(str(made["error"]))
    source = made.get("url") or (url(entry["source"]) if isinstance(entry, dict) and entry.get("source") else None)
    if not source:
        raise ValueError("scene3d.background splat has no file")
    return source


def background_of(entry: Any, made: Any, url) -> dict | None:
    """The resolved scene3d background for a splat set, or None when this is another kind."""
    made = made if isinstance(made, dict) else {}
    source = _splat_file(entry, made, url)
    if source is None:
        return None
    floor = _taken(made, entry, "floorY", 0)
    scale = _taken(made, entry, "scale", 1)
    return {"source": source, "splat": True, "floorY": float(floor), "scale": float(scale)}


def check_background(entry: dict) -> None:
    """A splat background is {source, splat: true, floorY?, scale?}."""
    if set(entry) - {"source", "splat", "floorY", "scale"} or entry.get("splat") is not True or not _text(entry.get("source")):
        raise ValueError("scene3d.background for a splat is {source, splat: true, floorY?, scale?}")
    if "floorY" in entry and not _number(entry["floorY"], -50, 50):
        raise ValueError("scene3d.background.floorY is metres, from -50 to 50")
    if "scale" in entry and not _number(entry["scale"], 0.05, 100):
        raise ValueError("scene3d.background.scale is from 0.05 to 100")


def _file_shape(name: str, value: Any) -> str | None:
    relative = _relative(value) if isinstance(value, str) else None
    if relative is None or Path(relative).suffix.lower() not in SUFFIXES:
        return f"sets.{name}.file is a .ply or .spz inside the workspace"
    return None


def _relative(path: Any) -> str | None:
    from services.production_models import workspace_rel
    return workspace_rel(path) if isinstance(path, str) else None


def _number(value: Any, low: float, high: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 2000


def _taken(made: dict, entry: Any, key: str, fallback: float):
    if key in made:
        return made[key]
    if isinstance(entry, dict) and key in entry:
        return entry[key]
    return fallback
