"""A Character Kit cutout that talks inside a Video 3D scene.

The 2D series already make a kit speak: pose, mouth drawing per cue, blink.
``talk_block`` builds the same thing for an image object of a Video 3D scene
(``slot.screen.talk``, painted by ``ui/src/features/scene3d/talkingCutout.ts``)
and ``apply_talk`` binds it, with each line's audio as a scene soundtrack
track, so the export hears what the mouth says.

Lines carry their mouth cues as ``audio.mouth_cues`` returns them (Rhubarb
letters A-H/X, or phonetic names) and the second the line starts in the scene.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

# Rhubarb letters -> the phonetic names Scene3D uses (speech/track.ts RHUBARB).
RHUBARB = {"X": "rest", "A": "M", "B": "I", "C": "E", "D": "A", "E": "O", "F": "U", "G": "F", "H": "L"}
# Phonetic names -> the kit's mouth drawings (lib/characterMouthStates.ts PHONETIC_MOUTH_STATE).
PHONETIC = {"rest": "closed", "M": "pressed", "I": "small", "E": "medium", "A": "wide", "O": "round", "U": "pucker", "F": "bite", "L": "tongue"}
# A missing drawing falls back to one of the four basic mouths (MOUTH_STATE_FALLBACK).
FALLBACK = {"closed": "closed", "small": "small", "wide": "wide", "round": "round",
            "pressed": "closed", "medium": "wide", "pucker": "round", "bite": "small", "tongue": "small"}
DEFAULT_MOUTH = {"offsetX": 0.0, "offsetY": -18.0, "scale": 0.05, "rotation": 0.0}
DEFAULT_BLINK = {"offsetX": 0.0, "offsetY": -28.0, "scale": 0.12, "rotation": 0.0}
MAX_LINES = 24
TRACK_PREFIX = "talk-"


class TalkError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


def _approved(asset: Any) -> bool:
    return isinstance(asset, dict) and asset.get("reviewState") == "approved" and bool(asset.get("source"))


def kit_state(sound: str, mapping: dict[str, str] | None, mouths: dict[str, str]) -> str:
    """The kit drawing for a cue: its own mapping first, then the standard one, then a basic mouth it has."""
    phonetic = RHUBARB.get(sound, sound)
    state = (mapping or {}).get(phonetic) or PHONETIC.get(phonetic) or "closed"
    if state in mouths:
        return state
    return FALLBACK.get(state, "closed") if FALLBACK.get(state) in mouths else ""


def _number(value: Any, label: str, low: float = 0.0, high: float = 600.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= float(value) <= high:
        raise TalkError("invalid_line", f"{label} must be a number between {low:g} and {high:g}")
    return float(value)


def _line_cues(line: dict, index: int, mapping: dict | None, mouths: dict[str, str]) -> list[dict]:
    start = _number(line.get("start", 0), f"lines[{index}].start")
    raw = line.get("cues") if isinstance(line.get("cues"), list) else (line.get("mouthCues") or [])
    cues = []
    for cue in raw if isinstance(raw, list) else []:
        if not isinstance(cue, dict):
            continue
        state = kit_state(str(cue.get("value") or cue.get("shape") or cue.get("viseme") or ""), mapping, mouths)
        begin, end = _number(cue.get("start"), "cue start"), _number(cue.get("end"), "cue end")
        if state and end > begin:
            cues.append({"start": round(start + begin, 3), "end": round(start + end, 3), "state": state})
    return cues


def blink_times(seed: str, duration: float) -> list[float]:
    """A blink every 2.6-4.6 s, the same for the same seed (like the 2D series shots)."""
    times, at, step = [], 0.9, 0
    while at < duration - 0.2 and len(times) < 400:
        times.append(round(at, 3))
        digest = hashlib.sha256(f"{seed}:{step}".encode()).digest()
        at += 2.6 + digest[0] / 255 * 2.0
        step += 1
    return times


def _ready_art(kit: dict, pose: str) -> tuple[dict, dict[str, str]]:
    """The approved pose asset and the approved mouth drawings by state."""
    asset = kit.get("base") if pose == "base" else (kit.get("poses") or {}).get(pose)
    if not _approved(asset):
        raise TalkError("pose_not_ready", f"Character Kit {kit.get('name') or kit.get('id')} has no approved {pose} pose")
    mouths = {state: item["source"] for state, item in (kit.get("mouth") or {}).items() if _approved(item)}
    if not mouths:
        raise TalkError("mouths_not_ready", "Approve the kit's mouth drawings in the Face Rig before making it talk")
    return asset, mouths


def _cues(lines: list[dict], mapping: dict | None, mouths: dict[str, str]) -> list[dict]:
    if not isinstance(lines, list) or len(lines) > MAX_LINES:
        raise TalkError("invalid_line", f"lines must be a list of at most {MAX_LINES}")
    found = (cue for index, line in enumerate(lines) if isinstance(line, dict) for cue in _line_cues(line, index, mapping, mouths))
    return sorted(found, key=lambda cue: cue["start"])


def _blink(kit: dict, anchors: dict, duration: float) -> dict:
    eyes = (kit.get("eyes") or {}).get("blink")
    if not _approved(eyes):
        return {}
    return {"blink": {"source": eyes["source"], "anchor": dict(anchors.get("eyes") or DEFAULT_BLINK)},
            "blinks": blink_times(str(kit.get("id") or ""), duration)}


def talk_block(kit: dict, lines: list[dict], *, pose: str = "base", duration: float = 10.0, blink: bool = True) -> dict:
    """``screen.talk`` for ``kit`` in ``pose`` saying ``lines``; only approved drawings are used."""
    asset, mouths = _ready_art(kit, pose)
    mapping = kit.get("mouthMapping") if isinstance(kit.get("mouthMapping"), dict) else None
    anchors = (kit.get("anchors") or {}).get(pose) or (kit.get("anchors") or {}).get("base") or {}
    talk: dict[str, Any] = {"base": asset["source"], "mouths": mouths, "mouth": dict(anchors.get("mouth") or DEFAULT_MOUTH),
                            "rest": kit_state("rest", mapping, mouths) or next(iter(mouths)), "cues": _cues(lines, mapping, mouths)}
    per_state = {state: dict(anchor) for state, anchor in (anchors.get("mouthStates") or {}).items() if state in mouths}
    if per_state:
        talk["mouthAnchors"] = per_state
    # A pose with hidden eyes (sunglasses) is marked ``blink: false`` by the rig and keeps them still.
    return {**talk, **(_blink(kit, anchors, duration) if blink and anchors.get("blink") is not False else {})}


def _audio(line: dict, index: int, workspace: str) -> dict | None:
    audio = line.get("audio")
    if audio is None:
        return None
    if isinstance(audio, str):
        audio = {"url": audio}
    url = str(audio.get("url") or "").strip() if isinstance(audio, dict) else ""
    if not url.startswith("/") or url.startswith("//"):
        raise TalkError("invalid_audio", f"lines[{index}].audio needs a workspace or upload URL")
    filename = str(audio.get("filename") or url.split("?")[0].rsplit("/", 1)[-1])
    return {"workspaceId": str(audio.get("workspaceId") or workspace), "filename": filename, "url": url}


def _bind_screen(slot: dict, kit: dict, talk: dict) -> None:
    slot["sourceUrl"] = talk["base"]
    slot.pop("sourceRef", None)
    screen = slot.get("screen") if isinstance(slot.get("screen"), dict) else {}
    kept = {key: value for key, value in screen.items() if key not in {"poseSequence", "media", "sourceRef"}}
    slot["screen"] = {**kept, "media": "image", "sourceUrl": talk["base"], "talk": talk}
    character = slot.get("character") if isinstance(slot.get("character"), dict) else {}
    slot["character"] = {**character, "id": str(kit.get("id")), "name": str(kit.get("name") or kit.get("id"))[:300]}


def _replace_tracks(document: dict, prefix: str, lines: list[dict], workspace: str) -> list[str]:
    """This object's line audio replaces its previous tracks; other tracks stay."""
    tracks = [track for track in document.get("soundtrack") or [] if not str(track.get("id", "")).startswith(prefix)]
    added = []
    for index, line in enumerate(lines):
        audio = _audio(line, index, workspace)
        if audio:
            added.append({"id": f"{prefix}{index}", "audio": audio, "start": round(float(line.get("start") or 0), 3),
                          "offset": 0, "gain": _number(line.get("gain", 1), "gain", 0, 1)})
    if len(tracks) + len(added) > 32:
        raise TalkError("too_many_tracks", "A Video 3D scene holds at most 32 soundtrack tracks")
    if tracks or added or document.get("soundtrack") is not None:
        document["soundtrack"] = tracks + added
    return [track["id"] for track in added]


def apply_talk(document: dict, slot: dict, kit: dict, lines: list[dict], *, workspace: str, pose: str = "base", blink: bool = True) -> dict:
    """Make an image object talk: its screen paints the kit, the soundtrack plays each line's audio."""
    if slot.get("media") != "image":
        raise TalkError("not_a_cutout", f"Object {slot.get('id')} is {slot.get('media')}; a talking cutout needs an image object")
    talk = talk_block(kit, lines, pose=pose, duration=float(document.get("duration") or 10), blink=blink)
    tracks = _replace_tracks(document, f"{TRACK_PREFIX}{slot.get('id')}-", lines, workspace)
    _bind_screen(slot, kit, talk)
    return {"objectId": slot.get("id"), "cues": len(talk["cues"]), "mouths": sorted(talk["mouths"]),
            "blinks": len(talk.get("blinks") or []), "tracks": tracks, "talk": deepcopy(talk)}
