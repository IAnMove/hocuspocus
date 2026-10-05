"""The voice sounds like the place: a room around each recorded Series line.

Lines are recorded dry (TTS), so a monk in a stone cathedral and a captain on an open deck would sound alike.
``series.soundDesign.roomByLocation`` maps a location id to a preset (``PRESETS``) and a shot's
``layout2d.voiceRoom`` overrides it for that shot; ``shot_room`` says which one a shot gets.

When the shot is built, the native render asks ``apply_room`` for a processed copy of each recorded line and the shot
plays that copy (``roomed``). The copy sits next to the dry recording, which is never touched, under a name made from
the recording, the preset and ``VERSION`` (``room_filename``), so it is made once and reused until the recording
changes. Timing and lip-sync stay the dry line's: the cues were analysed on the dry audio and the shot is timed by its
length. The only thing the room adds is a tail that may ring on past the end of the line, for at most ``MAX_RING``
seconds, faded out.

The processing is ffmpeg only and deterministic. A preset is a short generated impulse response (decaying noise,
darker as it dies, with early reflections; ``impulse_response``, cached as a wav) convolved with ``afir`` and mixed under
the dry voice, then a tone filter (low cut, EQ, distortion for the radio). The copy is levelled to the dry line's
loudness, so a room never makes a voice louder or quieter.
"""
from __future__ import annotations

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
VERSION = 1
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
    ``wet`` the room's level against the dry voice in dB, ``tone`` the ffmpeg filters on the whole voice."""
    rt60: float
    predelay: float
    early: tuple[tuple[float, float], ...]
    damping: float
    wet: float
    tone: str


ROOMS: dict[str, Room] = {
    "small_room": Room(0.30, 3, ((6, 0.6), (11, 0.45), (17, 0.35)), 6500, -12, "highpass=f=80"),
    "room": Room(0.55, 8, ((9, 0.5), (17, 0.4), (26, 0.3)), 6000, -9, "highpass=f=70"),
    "hall": Room(1.6, 22, ((15, 0.4), (31, 0.3), (47, 0.25)), 5000, -7, "highpass=f=80"),
    "cathedral": Room(3.5, 38, ((28, 0.3), (53, 0.25), (79, 0.2)), 3800, -5, "highpass=f=90"),
    # Small, metallic and close: dense alternating reflections within 10 ms, a band-limited voice with a presence peak.
    "cockpit": Room(0.14, 0.5, ((1.2, 0.9), (2.6, -0.8), (4.1, 0.7), (5.7, -0.6), (7.6, 0.5), (10.2, -0.4)), 7500, -7,
                    "highpass=f=220,lowpass=f=6500,equalizer=f=2200:t=q:w=1.4:g=4"),
    # No reverb: a gentle low cut and one very slight, dark slap off a far surface.
    "outdoor": Room(0.0, 0, ((82, 1.0),), 3000, -19, "highpass=f=90:poles=1"),
    # Telepathy and transmissions: band-passed, driven into a soft clip. No tail.
    "radio": Room(0.0, 0, (), 0, 0, "highpass=f=420:poles=2,volume=6dB,asoftclip=type=tanh:threshold=0.6,lowpass=f=3300:poles=2"),
}
PRESETS = ("none", *ROOMS)


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


def roomed(series: dict[str, Any], shot: dict[str, Any], recorded: Mapping[str, dict[str, Any]],
           process: Callable[[str, str], str]) -> Mapping[str, dict[str, Any]]:
    """``recorded`` as the shot hears it: for a shot in a room, the audio of each of its lines is ``process(filename,
    preset)``, the room's copy. Durations and cues stay the dry line's. A shot without a room gets ``recorded`` itself."""
    preset = shot_room(series, shot)
    if not preset:
        return recorded
    spoken = {beat.get("id") for beat in shot.get("dialogueBeats") or [] if str(beat.get("text") or "").strip()}
    return {beat_id: {**line, "filename": process(line["filename"], preset)} if beat_id in spoken else line
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


def room_filter(preset: str) -> str:
    """The ffmpeg graph of a preset: input 0 is the dry line and, when the preset has a tail, input 1 its impulse
    response (``impulse_response``, unit energy); output ``[out]``. The line is padded by the ring, mixed with its
    convolved copy ``wet`` dB down, toned, and the ring is faded out over the last ``FADE_SHARE`` of it."""
    room = ROOMS[preset]
    head = f"[0:a]aresample={RATE},aformat=sample_fmts=fltp:channel_layouts=mono"
    if not has_tail(room):
        return f"{head},{room.tone}[out]"
    ring = ring_seconds(preset)
    fade = round(ring * FADE_SHARE, 3)
    return (f"{head},apad=pad_dur={ring:.3f},asplit=2[dry][src];"
            f"[src][1:a]afir=gtype=none:irnorm=-1,volume={room.wet}dB[wet];"
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

    Decaying noise split in two bands, the lows lingering 1.3x and the highs fading in 0.85x ``rt60`` with a
    ``damping`` high cut, after the predelay and a short build-up; the early reflections are added ahead of it. The
    noise is seeded by the preset name, so the response is the same on every machine."""
    import numpy as np
    room = ROOMS[preset]
    if not has_tail(room):
        raise ValueError(f"The {preset} room has no tail")
    pre = room.predelay / 1000
    last = max((ms for ms, _ in room.early), default=0.0) / 1000
    length = pre + (1.3 * room.rt60 if room.rt60 else last + 0.04)
    count = max(2, int(RATE * length))
    freqs = np.fft.rfftfreq(count, 1 / RATE)
    dark = 1 / np.sqrt(1 + (freqs / room.damping) ** 2)
    response = np.zeros(count)
    if room.rt60:
        spectrum = np.fft.rfft(np.random.RandomState(zlib.crc32(preset.encode())).standard_normal(count))
        lows = 1 / np.sqrt(1 + (freqs / LOW_SPLIT_HZ) ** 4)
        age = np.maximum(np.arange(count) / RATE - pre, 0.0)
        build_up = 1 - np.exp(-age / 0.012)
        response += build_up * (np.fft.irfft(spectrum * lows, count) * np.exp(-_DECAY * age / (1.3 * room.rt60))
                                + np.fft.irfft(spectrum * (1 - lows) * dark, count) * np.exp(-_DECAY * age / (0.85 * room.rt60)))
    taps = np.zeros(count)
    for ms, gain in room.early:
        # A reflection weighs about as much as a few milliseconds of the tail.
        taps[min(count - 1, int(RATE * ms / 1000))] += gain * 5
    response += np.fft.irfft(np.fft.rfft(taps) * dark, count)
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
