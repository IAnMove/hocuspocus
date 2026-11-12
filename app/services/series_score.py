"""An episode's score: background music under a joined Series episode, lowered while someone speaks.

``episode.score`` lists the cues (``series.episode.update``), each over a run of shots in episode order::

    {"fromShotId": "e3s04", "toShotId": "e3s12", "file": "mus-theme.wav", "volume": 0.18, "fadeIn": 1.5,
     "fadeOut": 2.0, "duck": true}

``{"sceneId": "e3_cold_open", "file": ...}`` covers one scene, from its first shot to its last. Cues may not
overlap. The assembly lays them after the ambience and before the loudness pass (``episode_finishing.lay_score``),
the same way in every clip kind and language version:

- a cue plays from the cut before its first shot to the cut after its last, on the clips actually joined, its file
  looped like an ambience bed when it is shorter (``series_ambience``) and faded in and out inside the cue;
- its ``volume`` (0-2, relative to the dialogue) is balanced against the file's own loudness like a shot's music;
- with ``duck`` (the default) it dips ``DUCK_DB`` under every recorded line (the times the subtitles come from),
  ramping down over ``DUCK_ATTACK`` before the line and back up over ``DUCK_RELEASE`` after it; lines less than
  ``DUCK_MERGE`` apart share one dip, so the music does not pump between them;
- a shot with its own music (``layout2d.music``) keeps it, and the score is silent under it, with the same ramps.

The score belongs to the episode, not to a shot, so no take depends on it: changing it needs only a new cut.
Everything here is pure; ``series_ambience.mix_beds`` runs the ffmpeg pass.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple

from services.series_ambience import Bed, cut_points, loop_plan

DEFAULT_VOLUME = 0.18
DEFAULT_FADE_IN = 1.5
DEFAULT_FADE_OUT = 2.0
MAX_FADE = 30.0
MAX_CUES = 100
DUCK_DB = 9.0
DUCK_ATTACK = 0.25
DUCK_RELEASE = 0.6
DUCK_MERGE = 1.5
_FIELDS = ("fromShotId", "toShotId", "sceneId", "file", "volume", "fadeIn", "fadeOut", "duck")
_SOUND = ("file", "volume", "fadeIn", "fadeOut", "duck")


# The cues -------------------------------------------------------------------

def _number(cue: dict[str, Any], key: str, default: float, high: float, label: str) -> float:
    value = cue.get(key, default)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= high:
        raise ValueError(f"{label}.{key} must be a number from 0 to {high:g}")
    return float(value)


def _shot_ref(cue: dict[str, Any], key: str, label: str) -> str:
    value = cue.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{label}.{key} must be a shot or scene id")
    return (value or "").strip()


def _cue(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    unknown = sorted(set(value) - set(_FIELDS))
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(unknown)} (it takes {', '.join(_FIELDS)})")
    file = value.get("file")
    if not isinstance(file, str) or not file.strip():
        raise ValueError(f"{label}.file must name a workspace audio file")
    first, last, scene = (_shot_ref(value, key, label) for key in ("fromShotId", "toShotId", "sceneId"))
    if scene and (first or last):
        raise ValueError(f"{label} takes sceneId or fromShotId/toShotId, not both")
    if not scene and not first:
        raise ValueError(f"{label} needs fromShotId (and toShotId) or sceneId")
    duck = value.get("duck", True)
    if not isinstance(duck, bool):
        raise ValueError(f"{label}.duck must be true or false")
    cue: dict[str, Any] = {"sceneId": scene} if scene else {"fromShotId": first, "toShotId": last or first}
    cue.update(file=file.strip()[:300], volume=_number(value, "volume", DEFAULT_VOLUME, 2.0, label),
               fadeIn=_number(value, "fadeIn", DEFAULT_FADE_IN, MAX_FADE, label),
               fadeOut=_number(value, "fadeOut", DEFAULT_FADE_OUT, MAX_FADE, label), duck=duck)
    return cue


def _order(shot: dict[str, Any]) -> int:
    try:
        return int(shot.get("order") or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def ordered_shots(shots: Any) -> list[dict[str, Any]]:
    """The shots in episode order, as the assembly joins them."""
    return sorted((shot for shot in shots or [] if isinstance(shot, dict)), key=lambda shot: (_order(shot), str(shot.get("id") or "")))


def cue_shots(cue: dict[str, Any], shots: Sequence[dict[str, Any]]) -> tuple[int, int] | None:
    """Positions of a cue's first and last shot among ``shots`` (in episode order); None when they are not there."""
    if cue.get("sceneId"):
        found = [position for position, shot in enumerate(shots) if shot.get("sceneId") == cue["sceneId"]]
        return (found[0], found[-1]) if found else None
    positions = {str(shot.get("id")): position for position, shot in enumerate(shots)}
    first, last = positions.get(str(cue.get("fromShotId"))), positions.get(str(cue.get("toShotId") or cue.get("fromShotId")))
    return None if first is None or last is None else (first, last)


def _unplaced(cue: dict[str, Any], shots: Sequence[dict[str, Any]]) -> str:
    if cue.get("sceneId"):
        return f"scene {cue['sceneId']} has no shots in the episode"
    known = {str(shot.get("id")) for shot in shots}
    missing = [str(name) for name in dict.fromkeys((cue.get("fromShotId"), cue.get("toShotId"))) if name and str(name) not in known]
    return f"the episode has no shot {', '.join(missing)}"


def normalize_score(value: Any, shots: Any, *, strict: bool = False, kept: Sequence[Any] = ()) -> list[dict[str, Any]]:
    """``episode.score`` with its defaults, checked against the episode's shots: a cue that ends before it starts,
    or overlaps another, is refused. A cue whose shots the episode no longer has (after a rewrite) is kept and left
    out at assembly, which says so; ``strict`` (the score was just sent) refuses it instead, unless it is one of the
    cues already stored (``kept``), so an editor that sends the whole episode back can still save it."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("episode.score must be a list of cues")
    if len(value) > MAX_CUES:
        raise ValueError(f"episode.score takes at most {MAX_CUES} cues")
    cues = [_cue(item, f"episode.score[{index}]") for index, item in enumerate(value)]
    ordered = ordered_shots(shots)
    placed: list[tuple[tuple[int, int], int]] = []
    for index, cue in enumerate(cues):
        found = cue_shots(cue, ordered)
        if found is None:
            if strict and cue not in kept:
                raise ValueError(f"episode.score[{index}]: {_unplaced(cue, ordered)}")
            continue
        if found[0] > found[1]:
            raise ValueError(f"episode.score[{index}] ends at shot {ordered[found[1]].get('id')}, before it starts "
                             f"at shot {ordered[found[0]].get('id')}")
        placed.append((found, index))
    placed.sort()
    for (before, first), (after, second) in zip(placed, placed[1:]):
        if after[0] <= before[1]:
            raise ValueError(f"episode.score[{first}] and episode.score[{second}] overlap at shot "
                             f"{ordered[after[0]].get('id')}: score cues may not overlap")
    return cues


def own_music(shot: dict[str, Any]) -> bool:
    """A shot that mixes its own music (``layout2d.music`` with a file, not at volume 0)."""
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    music = layout.get("music")
    if not isinstance(music, dict) or not music.get("file"):
        return False
    volume = music.get("volume", 0.5)
    return not (isinstance(volume, (int, float)) and volume <= 0)


def clip_score(episode: dict[str, Any], clips: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """What the assembly needs to lay the score on these clips (``series_assembly.episode_assembly_plan``): each
    cue with its first and last clip, which clips have their own music, and why a cue was left out. None when the
    episode has no score. Kept on the job, so a resume lays the same score."""
    cues = episode.get("score")
    if not isinstance(cues, list) or not cues:
        return None
    shots = {str(shot.get("id")): shot for shot in episode.get("shots") or [] if isinstance(shot, dict)}
    joined = [shots.get(str(clip.get("shotId"))) or {"id": clip.get("shotId")} for clip in clips]
    placed, skipped = [], []
    for number, cue in enumerate(cues, start=1):
        if not isinstance(cue, dict):
            continue
        found = cue_shots(cue, joined)
        if found is None or found[0] > found[1]:
            skipped.append(f"Score cue {number}: {_unplaced(cue, joined) if found is None else 'it ends before it starts'}")
            continue
        sound = {key: cue[key] for key in _SOUND if key in cue}
        placed.append({"volume": DEFAULT_VOLUME, "fadeIn": DEFAULT_FADE_IN, "fadeOut": DEFAULT_FADE_OUT, "duck": True,
                       **sound, "firstClip": found[0], "lastClip": found[1]})
    return {"cues": placed, "music": [own_music(shot) for shot in joined], **({"skipped": skipped} if skipped else {})}


# On the joined timeline -----------------------------------------------------

def plan_cues(cues: Sequence[dict[str, Any]], spans: Sequence[tuple[float, float]],
              seconds: Mapping[str, float | None] | None = None) -> list[Bed]:
    """One bed per cue (``clip_score``): from the cut before its first clip to the cut after its last (``spans`` as
    for ``series_ambience.plan_beds``), looping a shorter file, with its fades inside it (at most half each)."""
    cuts = cut_points(spans)
    beds = []
    for cue in cues:
        first, last = int(cue["firstClip"]), int(cue["lastClip"])
        if not 0 <= first <= last < len(spans):
            raise ValueError("a score cue lies outside the joined clips")
        start, end = cuts[first], cuts[last + 1]
        length = end - start
        seam, passes = loop_plan(length, (seconds or {}).get(cue["file"]))
        beds.append(Bed(cue["file"], round(start, 3), round(end, 3), float(cue["volume"]),
                        round(min(float(cue["fadeIn"]), length / 2), 3), round(min(float(cue["fadeOut"]), length / 2), 3),
                        round(seam, 3), passes))
    return beds


def merge_spans(spans: Sequence[tuple[float, float]], gap: float = DUCK_MERGE) -> list[tuple[float, float]]:
    """Spans in time order, those overlapping or less than ``gap`` apart joined into one."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted((float(start), float(end)) for start, end in spans if end > start):
        if merged and start - merged[-1][1] < gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [(round(start, 3), round(end, 3)) for start, end in merged]


def touching(bed: Bed, spans: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """The spans whose ramps reach into the bed."""
    return [(start, end) for start, end in spans if end + DUCK_RELEASE > bed.start and start - DUCK_ATTACK < bed.end]


class Dip(NamedTuple):
    """One factor of a bed's gain, in the bed's own time: down to ``1 - depth`` from ``down`` + ``DUCK_ATTACK``,
    back up from ``up`` - ``DUCK_RELEASE`` to ``up``."""
    depth: float
    down: float
    up: float

    def gain(self, moment: float) -> float:
        lower = min(1.0, max(0.0, (moment - self.down) / DUCK_ATTACK))
        upper = min(1.0, max(0.0, (self.up - moment) / DUCK_RELEASE))
        return 1 - self.depth * lower * upper


def bed_dips(bed: Bed, dips: Sequence[tuple[float, float]], silences: Sequence[tuple[float, float]] = (), *,
             duck_db: float = DUCK_DB) -> list[Dip]:
    """Where the bed is lowered: ``duck_db`` over each dip and silent over each silence (episode times, merged),
    ramping down over ``DUCK_ATTACK`` before and back up over ``DUCK_RELEASE`` after. Its gain is the product of
    the factors, so a dip inside a silence stays silent."""
    factors = []
    for spans, depth in ((dips, 1 - 10 ** (-duck_db / 20)), (silences, 1.0)):
        if depth > 0:
            factors += [Dip(round(depth, 4), round(start - DUCK_ATTACK - bed.start, 3), round(end + DUCK_RELEASE - bed.start, 3))
                        for start, end in touching(bed, spans)]
    return factors


def gain_at(factors: Sequence[Dip], moment: float) -> float:
    """The bed's gain ``moment`` seconds after its start."""
    return math.prod(factor.gain(moment) for factor in factors)


def _since(moment: float) -> str:
    return f"t-{moment:.3f}" if moment >= 0 else f"t+{-moment:.3f}"


def envelope(factors: Sequence[Dip]) -> str | None:
    """``bed_dips`` as an ffmpeg ``volume`` expression of the bed's time (``t``); None when the bed stays level."""
    return "*".join(f"(1-{factor.depth:.4f}*clip(({_since(factor.down)})/{DUCK_ATTACK:.3f},0,1)"
                    f"*clip(({factor.up:.3f}-t)/{DUCK_RELEASE:.3f},0,1))" for factor in factors) or None
