"""The clips a Video 3D model really carries, and which of them a beat's words mean.

A ``do`` beat says ``wave``, ``bow`` or ``hover``; the renderer plays ``{index, name}`` of the model's own GLB animations. This
reads the animation names (and lengths) from the GLB's JSON chunk, in the order the renderer indexes them (``animations[]``;
an unnamed one is ``animation_<index>``, as three.js names it), and matches a word to a clip *by name* so a cue never points at
a clip the model lacks:

1. the exact clip name, ignoring case, spaces and punctuation (``Dance Bounce`` is ``dance_bounce``);
2. the rig's id or label (``wobble`` is the procedural clip ``Wobble Dance``);
3. a clip whose name contains the word, when only one does.

No guess beyond that: a model with no such clip answers with the clips it has, and the beat becomes a warning.
"""
from __future__ import annotations

from pathlib import Path

from services.procedural_3d.glb_bounds import MAX_JSON_BYTES, _read_document
from services.world3d_scene_bounds import resolve_workspace_glb

LOCOMOTION = {"walk": ("walk", "walkcycle"), "run": ("run", "runcycle")}
IDLE = ("idle", "idlesway")
HOLDS = frozenset({"crouch", "kneelpray"})      # the clips that end in the pose they keep: play them once
_CACHE: dict = {}


def key(text) -> str:
    """A word as the matcher compares it: letters and digits, lower case."""
    return "".join(char for char in str(text).lower() if char.isalnum())


def clip_info(slot: dict, workspace: str | None, workspace_dir) -> dict:
    """``{names, lengths}`` of the model a slot points at, in the renderer's clip order; empty for a marker, an image or a rigid model."""
    empty = {"names": [], "lengths": []}
    if (slot.get("media") or "model3d") != "model3d" or not workspace or workspace_dir is None:
        return empty
    path, _reason = resolve_workspace_glb(slot.get("sourceUrl"), workspace, workspace_dir)
    return _read(path) if path is not None else empty


def _read(path: Path) -> dict:
    try:
        stat = path.stat()
        token = (str(path), stat.st_mtime_ns, stat.st_size)
        if token not in _CACHE:
            _CACHE[token] = _clips(_read_document(path, MAX_JSON_BYTES))
            if len(_CACHE) > 128:
                _CACHE.pop(next(iter(_CACHE)))
        return _CACHE[token]
    except Exception:  # noqa: BLE001 - a model we cannot read has no clips we can name
        return {"names": [], "lengths": []}


def _clips(document: dict) -> dict:
    accessors = document.get("accessors") if isinstance(document.get("accessors"), list) else []
    names, lengths = [], []
    for index, animation in enumerate(document.get("animations") or []):
        animation = animation if isinstance(animation, dict) else {}
        names.append(str(animation.get("name") or f"animation_{index}"))
        lengths.append(_length(animation, accessors))
    return {"names": names, "lengths": lengths}


def _length(animation: dict, accessors: list) -> float | None:
    """A clip's length: the largest time any of its samplers reaches (the ``max`` of their input accessors)."""
    longest = None
    for sampler in animation.get("samplers") or []:
        index = sampler.get("input") if isinstance(sampler, dict) else None
        high = accessors[index].get("max") if type(index) is int and 0 <= index < len(accessors) and isinstance(accessors[index], dict) else None
        if isinstance(high, list) and high and type(high[0]) in (int, float):
            longest = max(longest or 0.0, float(high[0]))
    return longest


def find(info: dict, words) -> dict | None:
    """The clip ``{index, name, length}`` a word (or any of several) means, or None. See the module doc for the order."""
    wanted = [words] if isinstance(words, str) else list(words)
    keys = [key(name) for name in info["names"]]
    for word in wanted:
        for spelling in _spellings(word):
            if spelling in keys:
                return _clip(info, keys.index(spelling))
    for word in wanted:
        hits = [index for index, name in enumerate(keys) if len(key(word)) >= 3 and key(word) in name]
        if len(hits) == 1:
            return _clip(info, hits[0])
    return None


def _spellings(word: str) -> list[str]:
    spellings = [key(word)]
    label = _rig_label(word)
    if label:
        spellings.append(key(label))
    return spellings


def _rig_label(word: str) -> str | None:
    from services.rig_service import ANIMATIONS
    return next((item["label"] for item in ANIMATIONS if item["id"] == word or key(item["id"]) == key(word)), None)


def _clip(info: dict, index: int) -> dict:
    return {"index": index, "name": info["names"][index], "length": info["lengths"][index]}


def locomotion(info: dict, fast: bool) -> dict | None:
    """The walk clip, or with ``fast`` the run clip when the model has one (else its walk)."""
    order = ("run", "walk") if fast else ("walk",)
    for name in order:
        found = find(info, LOCOMOTION[name])
        if found:
            return found
    return None


def idle(info: dict) -> dict | None:
    return find(info, IDLE)


def is_hold(clip: dict) -> bool:
    return key(clip["name"]) in HOLDS


def ref(clip: dict) -> dict:
    """The clip as a cue stores it."""
    return {"index": clip["index"], "name": clip["name"]}
