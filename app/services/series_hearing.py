"""Subjective hearing for one shot (``layout2d.hearing``) or a whole series (``soundDesign.hearingDefault``).

``normal`` is the default and leaves the mix alone. ``muffled`` is a 700 Hz low-pass, 10 dB down, and the
voice room is skipped (a drier take). ``deaf`` drops dialogue, music and sound effects unless the effect says
``keepInDeaf``, and the assembly adds a low rumble plus a 4–6 kHz tone at -30 dB with fades. ``ringing`` keeps
the mix and adds that tone. The spectral part runs once, at episode assembly, after the ambience and the score,
which is where those beds are mixed: each clip's piece of the joined sound runs from its start to the next clip's,
so the soft join's and the transitions' overlaps are filtered once. A shot that omits the field, and a default of
``normal``, keep today's mix.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import wave
from collections.abc import Callable, Sequence
from typing import Any

KINDS = ("normal", "muffled", "deaf", "ringing")
_LOWPASS_HZ = 700
_MUFFLED_DB = -10
_BEEP_HZ = 5000
_BEEP_DB = -30
_RUMBLE_HZ = 80
_RUMBLE_DB = -14


def _kind(value: Any) -> str:
    return value if value in KINDS else "normal"


def hearing_of(series: dict[str, Any] | None, shot: dict[str, Any] | None) -> str:
    """The shot's own hearing, else the series default, else ``normal``. An unknown value is ``normal``."""
    shot = shot if isinstance(shot, dict) else {}
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    own = layout.get("hearing", shot.get("hearing"))
    if own in KINDS:
        return own
    design = series.get("soundDesign") if isinstance(series, dict) and isinstance(series.get("soundDesign"), dict) else {}
    return design["hearingDefault"] if design.get("hearingDefault") in KINDS else "normal"


def dries(series: dict[str, Any] | None, shot: dict[str, Any] | None) -> bool:
    """``muffled`` hears the lines dry: less room than the location's preset."""
    return hearing_of(series, shot) == "muffled"


def check_kind(value: Any, label: str) -> None:
    if value not in KINDS:
        raise ValueError(f"{label} must be one of: {', '.join(KINDS)}")


def check_default(design: Any) -> None:
    """``soundDesign.hearingDefault``, when present, is one of the four hearings."""
    if isinstance(design, dict) and "hearingDefault" in design:
        check_kind(design.get("hearingDefault"), "soundDesign.hearingDefault")


def check_shot(shot: dict[str, Any], where: str, problems: list[str]) -> None:
    """Append script problems for a bad ``hearing`` or a ``keepInDeaf`` that is not a boolean."""
    if not isinstance(shot, dict):
        return
    if shot.get("hearing") is not None and shot.get("hearing") not in KINDS:
        problems.append(f"{where}: hearing must be one of {', '.join(KINDS)}")
    for index, cue in enumerate(shot.get("sfx") or []):
        if isinstance(cue, dict) and "keepInDeaf" in cue and cue.get("keepInDeaf") not in (True, False):
            problems.append(f"{where}: sfx {index} keepInDeaf must be true or false")


def layout_hearing(shot: dict[str, Any]) -> dict[str, str]:
    """The hearing stored on the shot. ``normal`` and an omission store nothing, so the layout stays as it was."""
    kind = shot.get("hearing") if isinstance(shot, dict) else None
    if kind in (None, "normal") or kind not in KINDS:
        return {}
    return {"hearing": kind}


def layout_field(value: dict[str, Any]) -> dict[str, str]:
    """``layout2d.hearing`` kept by the shot editor. ``normal`` clears it. A bad value is refused."""
    if not isinstance(value, dict) or value.get("hearing") is None:
        return {}
    check_kind(value.get("hearing"), "layout2d.hearing")
    return {} if value["hearing"] == "normal" else {"hearing": value["hearing"]}


def shape(series: dict[str, Any] | None, shot: dict[str, Any] | None, lines: list[Any],
          tracks: list[Any]) -> tuple[list[Any], list[Any]]:
    """Dialogue and tracks as this hearing mixes them. Anything but ``deaf`` is returned unchanged."""
    if hearing_of(series, shot) != "deaf":
        return lines, tracks
    kept = [track for track in tracks if isinstance(track, dict) and track.get("keepInDeaf") is True]
    return [], kept


def heard_bed(series: dict[str, Any] | None, shot: dict[str, Any] | None, entry: Any) -> Any:
    """A deaf shot does not get the location's episode ambience: the rumble replaces it."""
    return None if hearing_of(series, shot) == "deaf" else entry


def quiet_under_deaf(score: Any, series: dict[str, Any] | None, episode: dict[str, Any] | None,
                     clips: Sequence[dict[str, Any]]) -> Any:
    """The episode score is silent under a deaf shot, the way it is silent under a shot's own music."""
    if not isinstance(score, dict):
        return score
    shots = {str(item.get("id")): item for item in (episode or {}).get("shots") or [] if isinstance(item, dict)}
    music = list(score.get("music") or [])
    changed = False
    for index, clip in enumerate(clips):
        shot = shots.get(str((clip or {}).get("shotId") if isinstance(clip, dict) else "")) or {}
        if index < len(music) and not music[index] and hearing_of(series, shot) == "deaf":
            music[index] = True
            changed = True
    return {**score, "music": music} if changed else score


def clip_kinds(series: dict[str, Any] | None, episode: dict[str, Any] | None,
               clips: Sequence[dict[str, Any]]) -> list[str] | None:
    """One hearing per joined clip, or None when every clip is ``normal`` (the assembly job stays as it was)."""
    shots = {str(item.get("id")): item for item in (episode or {}).get("shots") or [] if isinstance(item, dict)}
    kinds = [hearing_of(series, shots.get(str((clip or {}).get("shotId") if isinstance(clip, dict) else "")) or {})
             for clip in clips]
    return None if all(kind == "normal" for kind in kinds) else kinds


def active(kinds: Sequence[Any] | None) -> bool:
    return any(_kind(kind) != "normal" for kind in kinds or [])


def _fade(duration: float) -> float:
    return min(0.35, max(0.05, duration / 4))


def _tone(frequency: float, duration: float, gain_db: float, index: int, name: str) -> str:
    fade = _fade(duration)
    return (f"sine=frequency={frequency:g}:sample_rate=48000:duration={duration:.4f},volume={gain_db:g}dB,"
            f"afade=t=in:st=0:d={fade:.4f},afade=t=out:st={max(0.0, duration - fade):.4f}:d={fade:.4f},"
            f"aformat=channel_layouts=stereo[{name}{index}]")


def _span(kind: str, start: str, end: str | None, length: float, index: int, *, source: str) -> str:
    """One clip's hearing as an ffmpeg chain whose output is ``[h{index}]``: the sound from ``start`` to ``end``
    (None: to its end), ``length`` seconds long."""
    length = max(0.05, float(length))
    trim = f"atrim=start={start}" + (f":end={end}" if end is not None else "")
    head = f"{source}{trim},asetpts=PTS-STARTPTS,aformat=channel_layouts=stereo"
    if kind == "muffled":
        return f"{head},lowpass=f={_LOWPASS_HZ}:poles=2,lowpass=f={_LOWPASS_HZ}:poles=2,volume={_MUFFLED_DB:g}dB[h{index}]"
    if kind == "normal":
        return f"{head}[h{index}]"
    tone = _tone(_BEEP_HZ, length, _BEEP_DB, index, "beep")
    if kind == "ringing":
        return f"{head}[dry{index}];{tone};[dry{index}][beep{index}]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[h{index}]"
    rumble = _tone(_RUMBLE_HZ, length, _RUMBLE_DB, index, "rumble")
    return (f"{head}[dry{index}];{rumble};{tone};[dry{index}][rumble{index}][beep{index}]"
            f"amix=inputs=3:duration=first:normalize=0:dropout_transition=0[h{index}]")


def filter_graph(spans: Sequence[tuple[float, float]], kinds: Sequence[Any]) -> str:
    """The assembly graph for these clips (``spans``: where each plays on the joined timeline). The output pad is
    ``[a]``.

    Joined clips overlap where they dissolve into each other, so the sound is cut at the clips' starts instead: each
    clip's piece runs to the next clip's start, the first from the start of the sound and the last to its end. The
    pieces tile the sound, which keeps its length and every clip where its pictures are.
    """
    count = len(spans)
    labels = [_kind(kind) for kind in kinds]
    sources = ["[0:a]"] if count == 1 else [f"[s{index}]" for index in range(count)]
    split = "" if count == 1 else "[0:a]asplit=" + str(count) + "".join(sources) + ";"
    starts = [0.0, *(float(start) for start, _end in spans[1:])]
    lengths = [*(after - before for before, after in zip(starts, starts[1:])), float(spans[-1][1]) - starts[-1]]
    # One spelling per cut, so the piece before it and the piece after it meet on the same sample.
    cuts = [f"{start:.4f}" for start in starts]
    parts = [_span(kind, cuts[index], cuts[index + 1] if index + 1 < count else None, lengths[index], index,
                   source=sources[index])
             for index, kind in enumerate(labels)]
    tail = "".join(f"[h{index}]" for index in range(count)) + f"concat=n={count}:v=0:a=1[a]"
    return split + ";".join(parts) + ";" + tail


def _wav_seconds(path: str) -> float:
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / float(handle.getframerate() or 1)


def _run(source: str, target: str, graph: str, *, video: bool, ffmpeg: str | None = None) -> bool:
    ffmpeg = ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    temporary = f"{target}.part.mp4" if video else f"{target}.part.wav"
    if video:
        command = [ffmpeg, "-v", "error", "-y", "-i", source, "-filter_complex", graph, "-map", "0:v:0", "-map", "[a]",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", temporary]
    else:
        command = [ffmpeg, "-v", "error", "-y", "-i", source, "-filter_complex", graph, "-map", "[a]", "-f", "wav", temporary]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if result.returncode != 0 or not os.path.isfile(temporary):
        if os.path.isfile(temporary):
            os.remove(temporary)
        return False
    os.replace(temporary, target)
    return True


def apply_wav(source: str, target: str, kind: str) -> bool:
    """Write ``kind``'s hearing of a WAV. ``normal`` copies the file unchanged and returns True."""
    if _kind(kind) == "normal":
        if os.path.abspath(source) != os.path.abspath(target):
            shutil.copyfile(source, target)
        return True
    return _run(source, target, filter_graph([(0.0, _wav_seconds(source))], [kind]), video=False)


def color_episode(path: str, spans: Sequence[tuple[float, float]], kinds: Sequence[Any], *, ffmpeg: str,
                  abort_callback: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Filter the joined episode in place. A normal episode is not opened. Failure leaves the file and says why."""
    if abort_callback and abort_callback():
        return {"applied": False, "reason": "Cancelled"}
    if not active(kinds):
        return {"applied": False, "reason": "Every shot is heard normally"}
    if len(spans) != len(list(kinds)):
        return {"applied": False, "reason": "Hearing does not line up with the clips"}
    if not ffmpeg or not _run(path, path, filter_graph(spans, kinds), video=True, ffmpeg=ffmpeg):
        return {"applied": False, "reason": "ffmpeg could not apply the hearing"}
    return {"applied": True, "kinds": [_kind(kind) for kind in kinds]}
