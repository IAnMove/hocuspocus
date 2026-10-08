"""Location ambience as one continuous bed under a joined Series episode.

``series.soundDesign.ambienceByLocation`` maps a location id to a workspace
sound (``{"file": "sfx-rain.wav", "volume": 0.22}``) and
``soundDesign.ambienceMode`` says where it is mixed:

- ``"shot"`` (the default): every shot mixes its location's ambience from its
  own first frame (``series_shot_plan.sound_tracks``). The bed restarts at
  each cut, and a new level renders every shot again.
- ``"episode"``: the shots leave it out, so their takes do not depend on it,
  and the assembly lays it once under the joined audio, before the loudness
  pass. Each run of consecutive shots in one location gets one bed: the file
  looped to cover the run (``LOOP_FADE`` crossfade at each seam), faded in and
  out at the run's edges (``EDGE_FADE``) or crossfading into the next
  location's bed, at the entry's ``volume`` balanced like a shot's (relative
  to the dialogue). Shots whose location has no ambience get nothing.
  ``soundDesign.ambienceDuckDb`` (0-24 dB, default 0: off) lowers the beds
  under the recorded lines like the episode score (``series_score``).

``plan_beds`` is the plan (pure); ``bed_filter`` and ``mix_beds`` the one
ffmpeg pass that lays it. The episode score (``series_score``) is laid by
``mix_beds`` too, in a pass of its own.
"""
from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any, NamedTuple

from services import series_hearing
from services.audio_mix import AUDIO_FILTER_TAIL
from services.mix_concat import _run_ffmpeg_command

AMBIENCE_MODES = ("shot", "episode")
DEFAULT_VOLUME = 0.22
MAX_DUCK_DB = 24.0
EDGE_FADE = 0.8
LOOP_FADE = 1.0
# A ducking envelope is evaluated once per 5 ms (at 48 kHz): a 0.25 s ramp takes 50 steps, no zipper noise.
ENVELOPE_SAMPLES = 240
# ``aloop`` keeps what it was given when its input ends first: the whole loop unit.
_LOOP_SAMPLES = 2**31 - 1
_FORMAT = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


class Bed(NamedTuple):
    """One run's ambience on the episode timeline, in seconds. ``seam`` is the loop crossfade (0 when the file
    covers the bed) and ``passes`` how many times the file plays."""
    file: str
    start: float
    end: float
    volume: float
    fade_in: float
    fade_out: float
    seam: float = 0.0
    passes: int = 1

    def report(self) -> dict[str, Any]:
        return {"file": self.file, "start": self.start, "end": self.end, "volume": self.volume, "fadeIn": self.fade_in,
                "fadeOut": self.fade_out, "seam": self.seam, "passes": self.passes}


def ambience_mode(design: Any) -> str:
    """``soundDesign.ambienceMode``: ``"episode"``, or ``"shot"`` for anything else."""
    return "episode" if isinstance(design, dict) and design.get("ambienceMode") == "episode" else "shot"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def check_sound_design(design: Any) -> None:
    if isinstance(design, dict) and "ambienceMode" in design and design["ambienceMode"] not in AMBIENCE_MODES:
        raise ValueError('soundDesign.ambienceMode must be "shot" or "episode"')
    if isinstance(design, dict) and "ambienceDuckDb" in design and not (
            _is_number(design["ambienceDuckDb"]) and 0 <= design["ambienceDuckDb"] <= MAX_DUCK_DB):
        raise ValueError(f"soundDesign.ambienceDuckDb must be a number of dB from 0 to {MAX_DUCK_DB:.0f}")
    series_hearing.check_default(design)


def ambience_duck_db(design: Any) -> float:
    """How far episode-mode beds dip under the lines (``soundDesign.ambienceDuckDb``); 0 leaves them level."""
    value = design.get("ambienceDuckDb") if isinstance(design, dict) else None
    return max(0.0, min(MAX_DUCK_DB, float(value))) if _is_number(value) else 0.0


def shot_sound_design(design: Any) -> Any:
    """The sound design a shot's render depends on. In episode mode the beds are laid at assembly, so the take does
    not depend on them; shot mode is the design as stored, so takes from before the mode keep their digest. The
    beds' ducking is assembly-only in both modes. The rooms are left out too: a shot depends on its own room only
    (``series_voice_rooms.shot_room``, kept apart)."""
    if not isinstance(design, dict):
        return design
    left_out = {"roomByLocation", "ambienceMode", "ambienceDuckDb"} & design.keys()
    if ambience_mode(design) == "episode":
        left_out.add("ambienceByLocation")
    # A default of normal is the absence of a default: takes from before the field keep their digest.
    if design.get("hearingDefault") == "normal":
        left_out.add("hearingDefault")
    return {key: value for key, value in design.items() if key not in left_out} if left_out else design


def _volume(entry: dict[str, Any]) -> float:
    value = entry.get("volume", DEFAULT_VOLUME)
    if not _is_number(value):
        return DEFAULT_VOLUME
    return max(0.0, min(2.0, float(value)))


def clip_ambience(series: dict[str, Any], episode: dict[str, Any],
                  clips: Sequence[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Each joined clip's location, with its ambience ``file`` and ``volume`` when it has one (and ``duckDb`` when the
    beds dip under the lines); None in shot mode."""
    design = series.get("soundDesign")
    if ambience_mode(design) != "episode":
        return None
    entries = design.get("ambienceByLocation") if isinstance(design.get("ambienceByLocation"), dict) else {}
    duck = ambience_duck_db(design)
    shots = {str(shot.get("id")): shot for shot in episode.get("shots") or [] if isinstance(shot, dict)}
    result = []
    for clip in clips:
        shot = shots.get(str(clip.get("shotId"))) or {}
        location = str(shot.get("locationId") or "")
        entry = series_hearing.heard_bed(series, shot, entries.get(location) if location else None)
        item: dict[str, Any] = {"locationId": location}
        if isinstance(entry, dict) and isinstance(entry.get("file"), str) and entry["file"].strip():
            item.update(file=entry["file"].strip(), volume=_volume(entry), **({"duckDb": duck} if duck else {}))
        result.append(item)
    return result


def _runs(shots: Sequence[dict[str, Any]], cuts: Sequence[float]) -> list[dict[str, Any]]:
    """Consecutive clips in one location, from the cut before the first to the cut after the last."""
    runs: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        location = shot.get("locationId") or ""
        if runs and location and runs[-1]["location"] == location:
            runs[-1]["end"] = cuts[index + 1]
            continue
        runs.append({"location": location, "start": cuts[index], "end": cuts[index + 1], "file": shot.get("file") or "",
                     "volume": float(shot.get("volume", DEFAULT_VOLUME))})
    return runs


def loop_plan(length: float, seconds: float | None) -> tuple[float, int]:
    """``(seam, passes)`` for a file of ``seconds`` covering ``length``: a shorter one loops with a crossfaded seam."""
    if seconds is None or seconds <= 0 or seconds >= length:
        return 0.0, 1
    seam = min(LOOP_FADE, seconds / 4)
    return seam, math.ceil(length / (seconds - seam))


def cut_points(spans: Sequence[tuple[float, float]]) -> list[float]:
    """The start, each cut and the end of a joined timeline: a cut is the middle of two clips' dissolve overlap."""
    if not spans:
        return []
    middles = ((float(spans[index - 1][1]) + float(spans[index][0])) / 2 for index in range(1, len(spans)))
    return [0.0, *middles, float(spans[-1][1])]


def plan_beds(shots: Sequence[dict[str, Any]], spans: Sequence[tuple[float, float]],
              seconds: Mapping[str, float | None] | None = None) -> list[Bed]:
    """The ambience beds under a joined episode.

    ``shots`` are the clips in episode order (``clip_ambience``); ``spans`` where each plays on the joined timeline,
    overlapping where the join dissolves: the cut between two clips is the middle of their overlap. ``seconds`` is
    each file's length; a bed longer than its file loops it, and a file not listed is taken to cover its bed.
    A bed fades in and out over ``EDGE_FADE`` inside its run, except next to another bed: there both crossfade
    over ``EDGE_FADE`` centred on the cut (never longer than either run).
    """
    if len(shots) != len(spans):
        raise ValueError("one span per shot")
    if not spans:
        return []
    runs = [run for run in _runs(shots, cut_points(spans)) if run["end"] > run["start"]]
    crossfades = [min(EDGE_FADE, before["end"] - before["start"], after["end"] - after["start"])
                  if before["file"] and after["file"] and before["end"] == after["start"] else 0.0
                  for before, after in zip(runs, runs[1:])]
    beds = []
    for index, run in enumerate(runs):
        if not run["file"]:
            continue
        edge = min(EDGE_FADE, (run["end"] - run["start"]) / 2)
        left = crossfades[index - 1] if index > 0 else 0.0
        right = crossfades[index] if index < len(crossfades) else 0.0
        start, end = run["start"] - left / 2, run["end"] + right / 2
        seam, passes = loop_plan(end - start, (seconds or {}).get(run["file"]))
        beds.append(Bed(run["file"], round(start, 3), round(end, 3), run["volume"], round(left or edge, 3),
                        round(right or edge, 3), round(seam, 3), passes))
    return beds


def bed_filter(beds: Sequence[Bed], gains: Sequence[float], *, has_audio: bool, duration: float,
               envelopes: Sequence[str | None] | None = None) -> str:
    """The ffmpeg graph: input 0 is the joined episode and input ``i`` the file of ``beds[i - 1]``; output ``[mix]``.
    A looping bed plays its file from ``seam`` on, the end crossfading into the start it skipped, so the unit
    repeats without a seam. That crossfade is two qsin fades mixed on the reversed file, where the end and the start
    it skipped line up at the first sample whatever the file's length. It is not ``acrossfade``: ffmpeg 6.x ends that
    filter's output when its second input is done before the first, as it always is when both are cut from one file.
    ``gains`` balance each file like a shot's music (``audio_levels.gain_to``).
    ``envelopes`` (one per bed, or None) are ``volume`` expressions of the bed's own time, ``t`` = 0 at its start,
    evaluated every ``ENVELOPE_SAMPLES`` so their ramps are smooth: the ducking under the lines."""
    main = (f"[0:a]{_FORMAT}[main]" if has_audio
            else f"anullsrc=channel_layout=stereo:sample_rate=48000:d={duration:.3f},{_FORMAT}[main]")
    parts, labels = [main], []
    for index, (bed, gain) in enumerate(zip(beds, gains), start=1):
        source = f"[{index}:a]{_FORMAT},asetpts=PTS-STARTPTS"
        if bed.seam:
            fade = f"afade=t=in:d={bed.seam:.3f}:curve=qsin"
            parts += [f"{source},asplit=2[file{index}a][file{index}b]",
                      f"[file{index}a]atrim=start={bed.seam:.3f},asetpts=PTS-STARTPTS,areverse,{fade}[rest{index}]",
                      f"[file{index}b]atrim=end={bed.seam:.3f},asetpts=PTS-STARTPTS,{fade},areverse[head{index}]"]
            source = (f"[rest{index}][head{index}]amix=inputs=2:normalize=0:duration=first,areverse,"
                      f"aloop=loop=-1:size={_LOOP_SAMPLES},asetpts=N/SR/TB")
        length = bed.end - bed.start
        delay = round(bed.start * 1000)
        fades = [*([f"afade=t=in:d={bed.fade_in:.3f}:curve=qsin"] if bed.fade_in > 0 else []),
                 *([f"afade=t=out:st={length - bed.fade_out:.3f}:d={bed.fade_out:.3f}:curve=qsin"] if bed.fade_out > 0 else [])]
        envelope = envelopes[index - 1] if envelopes else None
        shaped = [*fades, f"volume={min(2.0, bed.volume * gain):.4f}",
                  *([f"asetnsamples=n={ENVELOPE_SAMPLES}:p=0", f"volume='{envelope}':eval=frame"] if envelope else [])]
        parts.append(f"{source},atrim=end={length:.3f},{','.join(shaped)},adelay={delay}|{delay}[bed{index}]")
        labels.append(f"[bed{index}]")
    parts.append(f"[main]{''.join(labels)}amix=inputs={len(labels) + 1}:normalize=0:duration=first,{AUDIO_FILTER_TAIL}[mix]")
    return ";".join(parts)


def mix_beds(path: str, beds: Sequence[Bed], sources: Sequence[str], gains: Sequence[float], *, ffmpeg: str,
             has_audio: bool, duration: float, abort_callback: Callable[[], bool] | None = None,
             envelopes: Sequence[str | None] | None = None, label: str = "ambience") -> bool:
    """Lay ``beds`` (their files at ``sources``) under ``path`` in place; the video is stream-copied."""
    temporary = f"{os.path.splitext(path)[0]}.{label}-tmp.mp4"
    command = [ffmpeg, "-y", "-hide_banner", "-i", path]
    for source in sources:
        command += ["-i", source]
    command += ["-filter_complex", bed_filter(beds, gains, has_audio=has_audio, duration=duration, envelopes=envelopes),
                "-map", "0:v?", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                "-movflags", "+faststart", temporary]
    if not _run_ffmpeg_command(command, temporary, abort_callback=abort_callback):
        return False
    os.replace(temporary, path)
    return True
