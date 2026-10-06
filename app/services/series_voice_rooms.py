"""The voice sounds like the place: a room around each recorded Series line.

Lines are recorded dry (TTS), so a monk in a stone cathedral and a captain on an open deck would sound alike.
``series.soundDesign.roomByLocation`` maps a location id to a preset (``PRESETS``) and a shot's
``layout2d.voiceRoom`` overrides it for that shot; ``shot_room`` says which one a shot gets. A place reaches only the
speakers in the shot (a narrator over the plate stays dry), a transmission (``radio``) every line of it, and a line's
own ``voiceRoom`` wins over both; ``line_rooms`` says which room each line is heard in.

When the shot is built, the native render asks ``apply_room`` for a processed copy of each recorded line and the shot
plays that copy (``roomed``). The copy sits next to the dry recording, which is never touched, under a name made from
the recording, the preset and ``VERSION`` (``room_filename``), so it is made once and reused until the recording
changes. Timing and lip-sync stay the dry line's: the cues were analysed on the dry audio and the shot is timed by its
length. The only thing the room adds is a tail that may ring on past the end of the line, for at most ``MAX_RING``
seconds, faded out.

The processing is ffmpeg only and deterministic. A preset is a short generated impulse response (early reflections
and a decaying noise tail, darker as it dies; ``impulse_response``, cached as a wav) convolved with ``afir``,
band-limited and mixed well under the dry voice, then a tone filter (low cut, EQ, distortion for the radio). The copy
is levelled to the dry line's loudness, so a room never makes a voice louder or quieter. The graph uses only what
ffmpeg 6.0 and later all have and do alike (``ir_makeup_db``).
"""
from __future__ import annotations

import functools
import math
import os
import shutil
import struct
import subprocess
import threading
import zlib
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

from services.audio_levels import integrated_lufs

# Bump it when the processing changes: the copies made before are not reused.
VERSION = 2
RATE = 44100
# The most a room's tail rings past the end of a line, and the share of it that is faded out.
MAX_RING = 0.8
FADE_SHARE = 0.75
# The most the levelling moves a copy, in dB.
MAX_RELEVEL_DB = 12.0
# Lows below this linger in a room longer than highs; a tail decays 60 dB over its ``rt60``.
LOW_SPLIT_HZ = 500.0
_DECAY = 6.9078


class Room(NamedTuple):
    """One preset. ``rt60`` seconds for the tail to fall 60 dB (0: no diffuse tail), ``predelay`` in ms before it
    starts, ``early`` reflections as (ms, gain; a negative gain is a phase flip), ``damping`` the tail's high cut in Hz,
    ``wet`` the room's level against the dry voice in dB, ``tone`` the ffmpeg filters on the whole voice, ``band`` the
    low and high cut of the room's sound alone (Hz; 0 for none) and ``late`` the diffuse tail's level against the early
    reflections in dB."""
    rt60: float
    predelay: float
    early: tuple[tuple[float, float], ...]
    damping: float
    wet: float
    tone: str
    band: tuple[float, float] = (0.0, 0.0)
    late: float = 0.0


# The places are felt, never in the way: the room sits 14-22 dB under the voice, is mostly early reflections (which
# the ear fuses with the voice), its tail starts after a predelay and is short, and it carries neither the lows that
# mask speech nor the highs that smear consonants. Every one keeps the speech transmission index (STI) of the voice
# above 0.9 and its clarity (C50, 500 Hz-2 kHz) above 12 dB, where the first presets measured 0.53 and -0.9 dB in the
# cathedral. The cockpit and the radio are effects on the voice.
ROOMS: dict[str, Room] = {
    "small_room": Room(0.28, 4, ((4, 0.6), (8, 0.45), (13, 0.35)), 6000, -17, "highpass=f=80", (250, 6000), -5),
    "room": Room(0.45, 10, ((7, 0.5), (14, 0.4), (22, 0.3)), 5500, -16, "highpass=f=70", (250, 5500), -4),
    "hall": Room(1.1, 25, ((11, 0.4), (23, 0.3), (36, 0.25)), 4500, -15, "highpass=f=80", (300, 5000), -2),
    "cathedral": Room(2.2, 50, ((14, 0.35), (29, 0.3), (43, 0.25)), 3500, -14, "highpass=f=90", (350, 4000), -1),
    # Small, metallic and close: dense alternating reflections within 10 ms, a band-limited voice with a presence peak.
    "cockpit": Room(0.14, 0.5, ((1.2, 0.9), (2.6, -0.8), (4.1, 0.7), (5.7, -0.6), (7.6, 0.5), (10.2, -0.4)), 7500, -10,
                    "highpass=f=220,lowpass=f=6500,equalizer=f=2200:t=q:w=1.4:g=4"),
    # No reverb: a gentle low cut and one very slight, dark slap off a far surface.
    "outdoor": Room(0.0, 0, ((82, 1.0),), 3000, -22, "highpass=f=90:poles=1", (200, 0)),
    # Telepathy and transmissions: band-passed, driven into a soft clip. No tail.
    "radio": Room(0.0, 0, (), 0, 0, "highpass=f=420:poles=2,volume=6dB,asoftclip=type=tanh:threshold=0.6,lowpass=f=3300:poles=2"),
}
PRESETS = ("none", *ROOMS)
# Effects on the voice, not places: they reach every line of a shot, on screen or not.
TRANSMISSIONS = frozenset({"radio"})


class RoomError(RuntimeError):
    """A room could not be made (ffmpeg missing or failed, the recording gone)."""


def check_room(value: Any, label: str) -> None:
    if not isinstance(value, str) or value not in PRESETS:
        raise ValueError(f"{label} must be one of: {', '.join(PRESETS)}")


def check_voice_rooms(design: Any) -> None:
    """``soundDesign.roomByLocation`` is a map of location id to preset."""
    rooms = design.get("roomByLocation") if isinstance(design, dict) else None
    if rooms is None:
        return
    if not isinstance(rooms, dict):
        raise ValueError("soundDesign.roomByLocation must map a location id to a room preset")
    for location, preset in rooms.items():
        check_room(preset, f'soundDesign.roomByLocation["{location}"]')


def shot_room(series: dict[str, Any], shot: dict[str, Any]) -> str | None:
    """The room a shot's voices are heard in: its own ``layout2d.voiceRoom`` (``none`` keeps them dry), else its
    location's entry of ``soundDesign.roomByLocation``. None for dry."""
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    design = series.get("soundDesign") if isinstance(series.get("soundDesign"), dict) else {}
    rooms = design.get("roomByLocation") if isinstance(design.get("roomByLocation"), dict) else {}
    preset = layout["voiceRoom"] if layout.get("voiceRoom") in PRESETS else rooms.get(shot.get("locationId") or "")
    return preset if isinstance(preset, str) and preset in ROOMS else None


def _people(entries: Any) -> set[str]:
    return {entry["characterId"] for entry in entries or [] if isinstance(entry, dict) and entry.get("characterId")}


def on_screen(shot: dict[str, Any]) -> set[str]:
    """The characters physically in a shot: a Video 3D shot's ``scene3d.cast``, else its 2D cast (``layout2d.cast``,
    else ``visibleCharacterIds``). Nobody is in a ``title`` shot."""
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    if shot.get("productionMethod") == "animation_3d" and isinstance(shot.get("scene3d"), dict):
        return _people(shot["scene3d"].get("cast"))
    if layout.get("framing") == "title":
        return set()
    return _people(layout.get("cast")) or _people({"characterId": cid} for cid in shot.get("visibleCharacterIds") or [])


def line_rooms(series: dict[str, Any], shot: dict[str, Any]) -> dict[str, str]:
    """The room each spoken line of a shot is heard in, by beat id; a dry line is left out.

    A line's own ``voiceRoom`` wins (``none`` keeps it dry), whoever speaks it. Otherwise the shot's room
    (``shot_room``) reaches only the speakers physically in the shot (``on_screen``): a narrator over a church plate is
    not in the church. A transmission (``TRANSMISSIONS``: a voice over the radio, a thought) is not a place, so it
    reaches every line of the shot."""
    preset, present, rooms = shot_room(series, shot), None, {}
    for beat in shot.get("dialogueBeats") or []:
        if not isinstance(beat, dict) or not str(beat.get("text") or "").strip():
            continue
        own = beat.get("voiceRoom")
        if own in PRESETS:
            heard = own
        elif preset in TRANSMISSIONS:
            heard = preset
        else:
            present = on_screen(shot) if present is None else present
            heard = preset if beat.get("characterId") in present else None
        if heard in ROOMS:
            rooms[str(beat.get("id"))] = heard
    return rooms


def roomed(series: dict[str, Any], shot: dict[str, Any], recorded: Mapping[str, dict[str, Any]],
           process: Callable[[str, str], str]) -> Mapping[str, dict[str, Any]]:
    """``recorded`` as the shot hears it: the audio of each line in a room (``line_rooms``) is ``process(filename,
    preset)``, the room's copy. Durations and cues stay the dry line's. A shot without a room gets ``recorded`` itself."""
    rooms = line_rooms(series, shot)
    if not rooms:
        return recorded
    return {beat_id: {**line, "filename": process(line["filename"], rooms[beat_id])} if beat_id in rooms else line
            for beat_id, line in recorded.items()}


# Planning -------------------------------------------------------------------

def has_tail(room: Room) -> bool:
    return bool(room.rt60 or room.early)


def ring_seconds(preset: str) -> float:
    """How long the room rings past the end of a line: its predelay, last reflection and decay, at most ``MAX_RING``."""
    room = ROOMS.get(preset)
    if room is None or not has_tail(room):
        return 0.0
    last = max((ms for ms, _ in room.early), default=0.0)
    return round(min(MAX_RING, (room.predelay + last + 20) / 1000 + room.rt60), 3)


def wet_band(room: Room) -> str:
    """The filters on the room's sound alone (not the voice): its low and high cut, or nothing."""
    low, high = room.band
    return "".join(f",{kind}=f={value:g}:poles=2" for kind, value in (("highpass", low), ("lowpass", high)) if value)


@functools.lru_cache(maxsize=None)
def ir_makeup_db(preset: str) -> float:
    """The gain in dB that gives back what ``afir`` takes off the preset's impulse response.

    ``afir`` divides a response by the sum of its absolute taps unless it is told not to, and the option that tells
    it changed: ``gtype=none`` up to ffmpeg 6.1, ``irnorm=-1`` from 7.0 (6.x refuses ``irnorm``, 7.0 and later
    ignore ``gtype``). The default is the same on every version, so the graph keeps it and gains the sum back: the
    response is convolved as generated, at unit energy, to within a thousandth of a dB (ffmpeg sums the taps in
    float)."""
    import numpy as np
    return 20 * math.log10(float(np.sum(np.abs(impulse_response(preset)))))


def room_filter(preset: str) -> str:
    """The ffmpeg graph of a preset: input 0 is the dry line and, when the preset has a tail, input 1 its impulse
    response (``impulse_response``, unit energy); output ``[out]``. The line is padded by the ring, mixed with its
    convolved copy (``ir_makeup_db``) band-limited (``band``) and ``wet`` dB down, toned, and the ring is faded out
    over the last ``FADE_SHARE`` of it."""
    room = ROOMS[preset]
    head = f"[0:a]aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=mono"
    if not has_tail(room):
        return f"{head},{room.tone}[out]"
    ring = ring_seconds(preset)
    fade = round(ring * FADE_SHARE, 3)
    return (f"{head},apad=pad_dur={ring:.3f},asplit=2[dry][src];"
            f"[src][1:a]afir,volume={ir_makeup_db(preset):.6f}dB{wet_band(room)},volume={room.wet}dB[wet];"
            f"[dry][wet]amix=inputs=2:normalize=0:duration=longest,{room.tone},"
            f"areverse,afade=t=in:d={fade:.3f}:curve=qsin,areverse[out]")


def room_filename(filename: str, preset: str) -> str:
    """Where a recording's copy in a room is kept: next to it, named by the recording, the preset and ``VERSION``."""
    return f"{os.path.splitext(filename)[0]}.room-{preset}-v{VERSION}.wav"


def impulse_response_filename(preset: str) -> str:
    # Starts with ``ln-`` like the recordings, so the series guide does not list it as a sound to use.
    return f"ln-room-{preset}-ir-v{VERSION}.wav"


def impulse_response(preset: str) -> Any:
    """The preset's impulse response as a float array of unit energy (a numpy array; the dry sound is not in it).

    The early reflections, darkened by ``damping``, and a diffuse tail ``late`` dB against them: decaying noise split
    in two bands, the lows lingering 1.3x and the highs fading in 0.85x ``rt60`` with the ``damping`` high cut, after
    the predelay and a short build-up. The noise is seeded by the preset name, so the response is the same on every
    machine."""
    import numpy as np
    room = ROOMS[preset]
    if not has_tail(room):
        raise ValueError(f"The {preset} room has no tail")
    pre = room.predelay / 1000
    last = max((ms for ms, _ in room.early), default=0.0) / 1000
    length = max(pre + 1.3 * room.rt60, last + 0.04) if room.rt60 else last + 0.04
    count = max(2, int(RATE * length))
    freqs = np.fft.rfftfreq(count, 1 / RATE)
    dark = 1 / np.sqrt(1 + (freqs / room.damping) ** 2)
    tail = np.zeros(count)
    if room.rt60:
        spectrum = np.fft.rfft(np.random.RandomState(zlib.crc32(preset.encode())).standard_normal(count))
        lows = 1 / np.sqrt(1 + (freqs / LOW_SPLIT_HZ) ** 4)
        age = np.maximum(np.arange(count) / RATE - pre, 0.0)
        build_up = 1 - np.exp(-age / 0.012)
        tail = build_up * (np.fft.irfft(spectrum * lows, count) * np.exp(-_DECAY * age / (1.3 * room.rt60))
                           + np.fft.irfft(spectrum * (1 - lows) * dark, count) * np.exp(-_DECAY * age / (0.85 * room.rt60)))
    taps = np.zeros(count)
    for ms, gain in room.early:
        taps[min(count - 1, int(RATE * ms / 1000))] += gain
    early = np.fft.irfft(np.fft.rfft(taps) * dark, count)
    parts = [(part, weight) for part, weight in ((early, 1.0), (tail, 10 ** (room.late / 20))) if np.any(part)]
    response = sum(weight * part / math.sqrt(float(np.sum(part ** 2))) for part, weight in parts)
    return response / math.sqrt(float(np.sum(response ** 2)))


def _write_float_wav(path: str, samples: Any) -> None:
    data = samples.astype("<f4").tobytes()
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 3, 1, RATE, RATE * 4, 4, 32)
              + b"data" + struct.pack("<I", len(data)))
    with open(path, "wb") as handle:
        handle.write(header + data)


def _ready(path: str, source: str | None = None) -> bool:
    """A finished file that is not older than ``source``."""
    try:
        return os.path.getsize(path) > 0 and (source is None or os.path.getmtime(path) >= os.path.getmtime(source))
    except OSError:
        return False


def _part(path: str, step: str = "") -> str:
    """A scratch name beside ``path`` that no other thread or process shares, so a copy appears whole or not at all."""
    return f"{os.path.splitext(path)[0]}.part{step}-{os.getpid()}-{threading.get_ident()}.wav"


def ensure_impulse_response(root: str, preset: str) -> str:
    """The preset's impulse response file in ``root``, written the first time."""
    path = os.path.join(root, impulse_response_filename(preset))
    if _ready(path):
        return path
    part = _part(path)
    try:
        _write_float_wav(part, impulse_response(preset))
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.remove(part)
    return path


# Processing -----------------------------------------------------------------

def _ffmpeg() -> str:
    found = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not found:
        raise RoomError("ffmpeg is not installed")
    return found


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise RoomError(f"ffmpeg did not run: {error}") from error
    if result.returncode != 0:
        raise RoomError(f"ffmpeg failed: {(result.stderr or '').strip()[-300:]}")


def apply_room(root: str, filename: str, preset: str) -> str:
    """The file name of ``filename`` heard in ``preset``: a copy beside it that is made once, reused while the recording
    is not newer, and levelled to the recording's loudness. ``none`` (or any name that is not a room) is the recording."""
    room = ROOMS.get(preset)
    if room is None:
        return filename
    source, name = os.path.join(root, filename), room_filename(filename, preset)
    target = os.path.join(root, name)
    if _ready(target, source):
        return name
    if not os.path.isfile(source):
        raise RoomError(f"{filename} is not in the workspace")
    ffmpeg = _ffmpeg()
    mixed, leveled = _part(target, "-mix"), _part(target, "-level")
    try:
        inputs = ["-i", source] + (["-i", ensure_impulse_response(root, preset)] if has_tail(room) else [])
        _run([ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", room_filter(preset), "-map", "[out]", "-c:a", "pcm_f32le", mixed])
        wanted, got = integrated_lufs(source), integrated_lufs(mixed)
        gain = 0.0 if wanted is None or got is None else max(-MAX_RELEVEL_DB, min(MAX_RELEVEL_DB, wanted - got))
        _run([ffmpeg, "-y", "-v", "error", "-i", mixed, "-af", f"volume={gain:.2f}dB,alimiter=limit=0.95:level=disabled:latency=1",
              "-c:a", "pcm_s16le", leveled])
        os.replace(leveled, target)
    finally:
        for scratch in (mixed, leveled):
            if os.path.exists(scratch):
                os.remove(scratch)
    return name
