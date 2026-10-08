"""Pin a Series episode to Character Kit revisions.

The kit library already compare-and-swaps the whole file and keeps the last
ten full-library snapshots (``character_kit_library``). That counter is the
library's, so one save of another character advances it, and the snapshot
window drops older documents. A per-kit ``revision`` is the one an episode
can pin.

``characters.save``, a flat re-rig and a voice edit all call
``patch_character_kit``. That writes the previous kit, complete, to
``.character-kit-revisions/<id>.v<N>.json`` and bumps only that kit. The
image files stay: poses and mouths are content-named, and the history write
never deletes them.

An episode without ``kitPins`` renders and fingerprints the latest kit, the
same document it used before pinning existed. With pins, both use the stored
revision, and so do a line's recording and retake (``series_line_voice``). A
render refuses a pin whose revision is no longer kept (``lost_pins``,
``kit_revision_missing``) before it starts. ``series.episode.kits.update``
moves pins forward and reports the shots of that character that become stale.
"""
from __future__ import annotations

import copy
from typing import Any, Callable

from services.character_kit_library import kit_revision, read_character_kit_library, read_kit_revision
from services.series_shot_plan import kit_ref
from services.series_take_inputs import stale_shot_ids


class KitPinError(ValueError):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def normalize_kit_pins(value: Any) -> dict[str, int] | None:
    """``{kitId: revision}`` or nothing. A missing or empty field stays absent."""
    if not isinstance(value, dict) or not value:
        return None
    pins: dict[str, int] = {}
    for key, revision in value.items():
        kit_id = str(key or "").strip()
        if not kit_id or len(kit_id) > 120:
            continue
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            continue
        pins[kit_id] = revision
    return pins or None


def kits_for_episode(kits: dict[str, Any], episode: dict[str, Any] | None, workspace_dir: str | None) -> dict[str, Any]:
    """Latest kits, or the pinned documents. No pins returns the same dict."""
    pins = normalize_kit_pins((episode or {}).get("kitPins"))
    if not pins:
        return kits
    resolved = dict(kits)
    for kit_id, revision in pins.items():
        found = _pinned(kits, kit_id, revision, workspace_dir)
        if found is None:
            # A render refuses this before it starts (``lost_pins``); a listing just has no kit for it.
            resolved.pop(kit_id, None)
        else:
            resolved[kit_id] = found
    return resolved


def lost_pins(kits: dict[str, Any], episode: dict[str, Any] | None, workspace_dir: str | None,
              kit_ids: set[str] | None = None) -> dict[str, int]:
    """The pins (of ``kit_ids``, or all) whose revision is neither the live kit nor kept in the history."""
    pins = normalize_kit_pins((episode or {}).get("kitPins")) or {}
    return {kit_id: revision for kit_id, revision in pins.items()
            if (kit_ids is None or kit_id in kit_ids) and _pinned(kits, kit_id, revision, workspace_dir) is None}


def _pinned(kits: dict[str, Any], kit_id: str, revision: int, workspace_dir: str | None) -> dict[str, Any] | None:
    current = kits.get(kit_id)
    if isinstance(current, dict) and kit_revision(current) == revision:
        return current
    return read_kit_revision(workspace_dir, kit_id, revision) if workspace_dir else None


def _people(shot: dict[str, Any]) -> list[str]:
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    scene = shot.get("scene3d") if isinstance(shot.get("scene3d"), dict) else {}
    cast = [entry.get("characterId") for entry in [*(layout.get("cast") or []), *(scene.get("cast") or [])] if isinstance(entry, dict)]
    heard = [beat.get("characterId") for beat in shot.get("dialogueBeats") or [] if isinstance(beat, dict)]
    return [item for item in dict.fromkeys([*(shot.get("visibleCharacterIds") or []), *heard, *cast]) if item]


def cast_kit_ids(series: dict[str, Any], episode: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for shot in episode.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        for character_id in _people(shot):
            ref = kit_ref(series, character_id) or {}
            kit_id = ref.get("id")
            if kit_id and kit_id not in found:
                found.append(kit_id)
    return found


def _require_revision(kits: dict[str, Any], workspace_dir: str, kit_id: str, revision: int) -> None:
    if _pinned(kits, kit_id, revision, workspace_dir) is None:
        raise KitPinError(f"Character kit {kit_id} has no revision {revision}", status=404)


def _fresh_pins(series: dict, episode: dict, kits: dict, workspace_dir: str, requested: Any) -> dict[str, int]:
    if requested is None:
        pins = {}
        for kit_id in cast_kit_ids(series, episode):
            kit = kits.get(kit_id)
            if not isinstance(kit, dict):
                raise KitPinError(f"Character kit {kit_id} is not in this workspace", status=404)
            pins[kit_id] = kit_revision(kit)
        return pins
    if not isinstance(requested, dict):
        raise KitPinError("kits must be an object of kit id to revision")
    pins = normalize_kit_pins(requested) or {}
    if len(pins) != len(requested):
        raise KitPinError("Each kit pin is a kit id and a revision number")
    for kit_id, revision in pins.items():
        _require_revision(kits, workspace_dir, kit_id, revision)
    return pins


def _shots_of(series: dict, episode: dict, kit_ids: set[str]) -> dict[str, list[str]]:
    """Shot id to the characters in it whose kit is in ``kit_ids``."""
    found: dict[str, list[str]] = {}
    for shot in episode.get("shots") or []:
        if not isinstance(shot, dict) or not shot.get("id"):
            continue
        matched = []
        for character_id in _people(shot):
            ref = kit_ref(series, character_id) or {}
            if ref.get("id") in kit_ids:
                matched.append(character_id)
        if matched:
            found[shot["id"]] = matched
    return found


def _became_stale(series: dict, episode: dict, kits: dict, workspace_dir: str, pins: dict[str, int], moved: set[str]) -> list[dict[str, str]]:
    before = set(stale_shot_ids(series, episode, kits_for_episode(kits, episode, workspace_dir), workspace_dir))
    after_episode = {**episode, "kitPins": pins}
    after = set(stale_shot_ids(series, after_episode, kits_for_episode(kits, after_episode, workspace_dir), workspace_dir))
    owned = _shots_of(series, episode, moved)
    stale = []
    for shot_id in sorted(after - before):
        for character_id in owned.get(shot_id) or []:
            ref = kit_ref(series, character_id) or {}
            stale.append({"shotId": shot_id, "characterId": character_id, "kitId": ref.get("id") or ""})
    return stale


def _episode_of(library: dict, series_id: str, episode_id: str) -> tuple[dict, dict]:
    series = (library.get("seriesById") or {}).get(series_id)
    episode = (series or {}).get("episodesById", {}).get(episode_id) if isinstance(series, dict) else None
    if not isinstance(series, dict) or not isinstance(episode, dict):
        raise KitPinError("Series episode not found", status=404)
    return series, episode


def _with_library_lock(action: Callable[[], Any]) -> Any:
    """The server lock, when launch has bound one. The folder stays the caller's."""
    from routers import series_library as routes

    lock = getattr(routes, "_library_lock", None)
    if lock is None:
        return action()
    with lock:
        return action()


def _read(workspace_name: str | None, folder: str) -> dict:
    from services.series_library import read_series_library

    # ``folder`` is already ``workspace_dir(workspace)``. The bound reader resolves
    # the name through the process-global root, which a test can point elsewhere.
    return _with_library_lock(lambda: read_series_library(folder, workspace_name or "default"))


def _save_pins(workspace_name: str | None, folder: str, series_id: str, episode_id: str, pins: dict[str, int]) -> dict:
    """Read, set the pins and write the workspace folder under the server lock."""
    from services.series_library import read_series_library, update_series_episode, write_series_library

    workspace_id = workspace_name or "default"

    def change(library: dict) -> dict:
        series, _episode = _episode_of(library, series_id, episode_id)
        updated = update_series_episode(series, episode_id, {"kitPins": pins}, base_series_revision=series.get("revision"))
        stored = copy.deepcopy(library)
        stored.setdefault("seriesById", {})[series_id] = updated
        return stored

    def store() -> dict:
        return write_series_library(folder, change(read_series_library(folder, workspace_id)), workspace_id)

    saved = _with_library_lock(store)
    episode = saved["seriesById"][series_id]["episodesById"][episode_id]
    return {"kitPins": episode.get("kitPins") or {}, "revision": saved["seriesById"][series_id]["revision"]}


def pin_episode_kits(folder: str, series_id: str, episode_id: str, requested: Any = None, *, workspace_name: str | None = None) -> dict[str, Any]:
    """Pin the cast at the current revisions, or the revisions in ``requested``."""
    library = _read(workspace_name, folder)
    series, episode = _episode_of(library, series_id, episode_id)
    kits = (read_character_kit_library(folder).get("kits") or {})
    pins = _fresh_pins(series, episode, kits, folder, requested)
    if not pins:
        raise KitPinError("This episode's cast has no Character Kits to pin")
    return _save_pins(workspace_name, folder, series_id, episode_id, pins)


def update_episode_kits(folder: str, series_id: str, episode_id: str, kit_id: str | None = None, *, workspace_name: str | None = None) -> dict[str, Any]:
    """Move pins to the latest revision. Stale shots are only that character's."""
    library = _read(workspace_name, folder)
    series, episode = _episode_of(library, series_id, episode_id)
    pins = dict(normalize_kit_pins(episode.get("kitPins")) or {})
    if kit_id and kit_id not in pins:
        raise KitPinError(f"{kit_id} is not pinned on this episode", status=404)
    kits = (read_character_kit_library(folder).get("kits") or {})
    targets = [kit_id] if kit_id else list(pins)
    moved: set[str] = set()
    for target in targets:
        current = kits.get(target)
        if not isinstance(current, dict):
            raise KitPinError(f"Character kit {target} is not in this workspace", status=404)
        latest = kit_revision(current)
        if pins.get(target) != latest:
            pins[target] = latest
            moved.add(target)
    stale = _became_stale(series, episode, kits, folder, pins, moved) if moved else []
    saved = _save_pins(workspace_name, folder, series_id, episode_id, pins) if moved else {
        "kitPins": pins, "revision": series.get("revision")}
    return {**saved, "stale": stale}


def run_episode_kits(name: str, data: dict[str, Any], workspace_dir: Callable[[str], str]) -> dict[str, Any]:
    folder = str(workspace_dir(data["workspace"]))
    if name == "series.episode.kits.pin":
        return pin_episode_kits(folder, data["series_id"], data["episode_id"], data.get("kits"), workspace_name=data["workspace"])
    if name == "series.episode.kits.update":
        return update_episode_kits(folder, data["series_id"], data["episode_id"], data.get("kit_id"), workspace_name=data["workspace"])
    raise KitPinError("Unknown kit pin operation")

