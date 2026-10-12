"""A part of a sound file as a cue: ``{"file": "sfx-steps.wav", "in": 1.2, "length": 0.4}``.

A cue used to play its whole file, so one footstep out of an 8 s walk had to be
cut with ffmpeg outside the app. A cue's ``in`` (the second of the file it
starts at) and ``length`` (seconds) now name the part. Before a shot is mixed,
``materialize_cuts`` writes that part once as a workspace file
(``<stem>-cut-<hash>.wav``, with a ``.meta.json`` that names its source and the
cut) and points the track at it, so every consumer (the Video 2D mixer, a Video
3D soundtrack, a video take at the cut, the take's editable scene in the
editor) plays exactly that part. The same file and cut reuse the same file.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

from services.audio_mix import track_source

MAX_IN = 3600.0
MIN_LENGTH, MAX_LENGTH = 0.02, 600.0
EDGE_FADE = 0.005
TOOL = "series-sound-cut"


def _number(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if low <= value <= high else None


def cut_fields(value: dict[str, Any]) -> dict[str, float]:
    """``in`` and ``length`` of a cue, when valid (``in`` 0-3600 s, ``length`` 0.02-600 s)."""
    found: dict[str, float] = {}
    start, length = _number(value.get("in"), 0.0, MAX_IN), _number(value.get("length"), MIN_LENGTH, MAX_LENGTH)
    if start:
        found["in"] = start
    if length is not None:
        found["length"] = length
    return found


def track_cut(cue: dict[str, Any]) -> dict[str, float]:
    """The track keys a cue's cut becomes (``sfx_tracks``)."""
    return {**({"trimStart": cue["in"]} if cue.get("in") else {}), **({"trimLength": cue["length"]} if cue.get("length") else {})}


def cut_name(source: Path, relative: str, start: float, length: float | None) -> str:
    """Same file content and cut, same name: a second render reuses it."""
    stat = source.stat()
    digest = hashlib.sha1(repr((relative, stat.st_size, int(stat.st_mtime), round(start, 3),
                                None if length is None else round(length, 3))).encode()).hexdigest()[:10]
    # At the workspace root, beside the files a bible names, so every exporter finds it by name.
    return f"{Path(relative).stem[:60] or 'sound'}-cut-{digest}.wav"


def cut_audio(source: Path, target: Path, start: float, length: float | None, *, fade: float = EDGE_FADE) -> None:
    """Exactly ``length`` seconds from ``start`` (to the end without a length), 5 ms fades so the cut does not click.
    Keeps the file's sample rate and channels; written beside the target first, then moved into place."""
    chain = [f"atrim=start={start:.4f}" + (f":duration={length:.4f}" if length is not None else ""), "asetpts=PTS-STARTPTS"]
    if fade > 0:
        chain.append(f"afade=t=in:d={fade:.4f}")
        if length is not None and length > 4 * fade:
            chain.append(f"afade=t=out:st={max(0.0, length - fade):.4f}:d={fade:.4f}")
    partial = target.with_name(f".{target.name}.part.wav")
    command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(source), "-vn", "-af", ",".join(chain),
               "-c:a", "pcm_s16le", str(partial)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
        if result.returncode != 0 or not partial.is_file() or partial.stat().st_size <= 44:
            raise ValueError(("could not cut " + source.name + ": " + (result.stderr or "")).strip()[-400:])
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)


def _sidecar(target: Path, relative: str, start: float, length: float | None) -> None:
    try:
        from services.asset_manifest import build_asset_manifest, write_asset_manifest
        manifest = build_asset_manifest(
            target, kind="audio", tool=TOOL, actor="system",
            parameters={"source": relative, "in": start, "length": length},
            parents=[{"id": relative, "kind": "audio", "uri": relative, "role": "source"}],
            transformations=[{"operation": "trim", "in": start, "length": length}],
        )
        write_asset_manifest(target, manifest)
    except Exception:  # the cut plays without its provenance file
        pass


def materialize_cuts(root: str | Path, tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Point every track with ``trimStart``/``trimLength`` at a file of just that part (written once).

    A track whose file is missing keeps its name, so the usual missing-file checks name the file the author wrote."""
    made = []
    for track in tracks:
        start, length = float(track.get("trimStart") or 0.0), track.get("trimLength")
        if not start and length is None:
            continue
        relative = str(track.get("filename") or "")
        source = track_source(root, relative)
        if source is None or not source.is_file():
            continue
        name = cut_name(source, relative, start, length)
        target = Path(root) / name
        if not target.is_file():
            cut_audio(source, target, start, length)
            _sidecar(target, relative, start, length)
        track.pop("trimStart", None)
        track.pop("trimLength", None)
        track.update(filename=name, cutFrom={"file": relative, "in": start, **({"length": length} if length is not None else {})})
        made.append({"file": name, "source": relative, "in": start, "length": length})
    return made


__all__ = ["cut_audio", "cut_fields", "cut_name", "materialize_cuts", "track_cut"]
