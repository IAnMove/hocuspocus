"""Sound design for a trailer: the silence before the hit, the riser into it, the hit.

A song under a sequence of pictures does not make a trailer. What does is the gap: the music drops out a bar before
the reveal, a riser climbs through it, the reveal lands on an impact. Everything here is synthesised with ffmpeg on
the CPU (no model, no GPU, no download) and deterministic, so the same spec makes the same sound:

* riser: a rising sweep with noise whose level follows it, ending exactly on the hit;
* impact: a low sine boom with a short pink-noise crack, decaying;
* the soundtrack: the song with the silence window muted (20 ms fades so nothing clicks), and, for an
  instrumental song only, delayed by ``song.late_entry`` seconds (a song with lyrics cannot be shifted: its captions
  are timed to the original).

The cues go to the montage as ``audioCues`` (``start`` in seconds on the timeline) and the soundtrack source is the
processed file. Anchors are the ``t0`` of the planned shots of each beat, so the sound follows the picture.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

RATE = 48000
FADE_S = 0.02
IMPACT_S = 1.6
MAX_RISER_S = 6.0


def beat_starts(shots: list[dict]) -> dict[str, float]:
    """First planned start of each beat."""
    starts: dict[str, float] = {}
    for shot in shots:
        beat, t0 = shot.get("beat"), shot.get("t0")
        if isinstance(beat, str) and isinstance(t0, (int, float)) and beat not in starts:
            starts[beat] = float(t0)
    return starts


def design(shots: list[dict], bpm: float, late_entry: float = 0.0) -> dict[str, Any]:
    """Where the silence, the risers and the impacts go. Times are seconds on the timeline."""
    starts = beat_starts(shots)
    bar = 240.0 / (bpm if bpm and bpm > 0 else 120.0)
    plan: dict[str, Any] = {"silences": [], "risers": [], "impacts": [], "late_entry": max(0.0, float(late_entry))}
    reveal, escalation, close = starts.get("reveal"), starts.get("escalation"), starts.get("close")
    if reveal is not None:
        plan["silences"].append([round(max(0.0, reveal - bar), 3), round(reveal, 3)])
        plan["risers"].append({"end": round(reveal, 3), "duration": round(min(MAX_RISER_S, 2 * bar, reveal), 3)})
        plan["impacts"].append({"at": round(reveal, 3), "volume": 1.0})
    if escalation is not None and escalation > bar:
        plan["risers"].append({"end": round(escalation, 3), "duration": round(min(MAX_RISER_S, bar, escalation), 3), "volume": 0.5})
    if close is not None:
        plan["impacts"].append({"at": round(close, 3), "volume": 0.6})
    return plan


def plan_digest(plan: dict, song: str) -> str:
    return hashlib.sha256(json.dumps([plan, song], sort_keys=True).encode()).hexdigest()[:10]


# ---------------------------------------------------------------- ffmpeg commands (pure, tested)
def riser_command(out: Path, duration: float) -> list[str]:
    sweep = f"sin(2*PI*(110*t+({1500 / duration:.4f})*t*t/2))*pow(t/{duration:.3f},1.5)*0.6"
    return ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{sweep}':d={duration:.3f}:s={RATE}",
            "-f", "lavfi", "-i", f"anoisesrc=d={duration:.3f}:c=pink:r={RATE}:a=0.25",
            "-filter_complex", f"[1]highpass=f=800,afade=t=in:st=0:d={duration:.3f}[n];[0][n]amix=inputs=2:normalize=0,alimiter=limit=0.95",
            "-ar", str(RATE), "-ac", "2", str(out)]


def impact_command(out: Path) -> list[str]:
    boom = "sin(2*PI*50*t)*exp(-3.5*t)+0.3*sin(2*PI*100*t)*exp(-6*t)"
    return ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{boom}':d={IMPACT_S}:s={RATE}",
            "-f", "lavfi", "-i", f"anoisesrc=d={IMPACT_S}:c=pink:r={RATE}:a=0.35",
            "-filter_complex", "[1]lowpass=f=900,afade=t=out:st=0.04:d=0.5[n];[0][n]amix=inputs=2:normalize=0,volume=1.6,alimiter=limit=0.95",
            "-ar", str(RATE), "-ac", "2", str(out)]


def soundtrack_command(song: Path, out: Path, silences: list[list[float]], late_entry: float = 0.0) -> list[str]:
    """The song with each silence muted (short fades) and, when asked, delayed."""
    filters = [f"volume='if(between(t,{a:.3f},{b:.3f}),1-min(1,min(t-{a:.3f},{b:.3f}-t)/{FADE_S}),1)':eval=frame" for a, b in silences]
    if late_entry > 0:
        milliseconds = int(round(late_entry * 1000))
        filters.append(f"adelay={milliseconds}|{milliseconds}")
    return ["ffmpeg", "-v", "error", "-y", "-i", str(song), "-af", ",".join(filters) or "anull", "-ar", str(RATE), "-ac", "2", str(out)]


def _run(command: list[str]) -> bool:
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=180)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------- the files and the montage
def render(root: Path, prefix: str, plan: dict, song: str) -> dict[str, Any] | None:
    """Write the riser, impact and soundtrack files into the workspace; None when the song or ffmpeg is missing."""
    names: dict[str, Any] = {"risers": [], "impacts": [], "soundtrack": f"{prefix}-trailer-soundtrack.wav"}
    if not (root / song).is_file() or not _run(soundtrack_command(root / song, root / names["soundtrack"], plan["silences"], plan["late_entry"])):
        return None
    for index, riser in enumerate(plan["risers"]):
        name = f"{prefix}-trailer-riser-{index + 1}.wav"
        if riser["duration"] > 0.3 and _run(riser_command(root / name, riser["duration"])):
            names["risers"].append({**riser, "file": name})
    if plan["impacts"] and _run(impact_command(root / f"{prefix}-trailer-impact.wav")):
        names["impacts"] = [{**impact, "file": f"{prefix}-trailer-impact.wav"} for impact in plan["impacts"]]
    return names


def _source(name: str, workspace: str) -> str:
    return f"/api/v1/file/{quote(name)}?workspace={quote(workspace, safe='')}"


def audio_cues(names: dict, workspace: str) -> list[dict]:
    cues = []
    for index, riser in enumerate(names["risers"]):
        cues.append({"id": f"riser-{index + 1}", "name": "riser", "source": _source(riser["file"], workspace),
                     "start": round(max(0.0, riser["end"] - riser["duration"]), 3), "volume": riser.get("volume", 0.8)})
    for index, impact in enumerate(names["impacts"]):
        cues.append({"id": f"impact-{index + 1}", "name": "impact", "source": _source(impact["file"], workspace),
                     "start": impact["at"], "volume": impact["volume"]})
    return sorted(cues, key=lambda cue: cue["start"])


def attach(production: Any, spec: dict, montage: dict) -> dict:
    """montage() hook: for a trailer, the processed soundtrack and the cues. Any other structure: unchanged."""
    if spec.get("structure") != "trailer" or not isinstance(spec.get("shots"), list):
        return montage
    song = spec.get("song") or {}
    state_song = (production.state.get("song") or {}).get("file")
    plan = design(spec["shots"], float(song.get("bpm") or 120), float(song.get("late_entry") or 0) if not song.get("lyrics") else 0.0)
    if not state_song or not (plan["silences"] or plan["impacts"] or plan["late_entry"]):
        return montage
    digest = plan_digest(plan, state_song)
    kept = production.state.get("trailer_audio") or {}
    names = kept.get("names") if kept.get("digest") == digest else None
    if names is None:
        names = render(production.root, production.id, plan, state_song)
        if names is None:
            production.log("trailer audio: could not render, the song stays as it is")
            return montage
        production.state["trailer_audio"] = {"digest": digest, "names": names}
        production.log(f"trailer audio: {len(names['risers'])} risers, {len(names['impacts'])} impacts, silence {plan['silences']}")
    montage["soundtrack"] = {**montage["soundtrack"], "source": _source(names["soundtrack"], production.ws)}
    montage["audioCues"] = audio_cues(names, production.ws)
    return montage
