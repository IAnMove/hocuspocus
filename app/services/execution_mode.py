"""Boot-time execution policy and cheap media executor for acceptance tests.

The Wizard and product UI never select this mode.  It is fixed by the process
environment before the API starts, and simulation is confined to a dedicated
workspace.  That keeps the normal capability/API/queue/task path intact while
replacing only expensive media inference at its final execution boundary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import threading
import time
import wave
import zlib
from typing import Any, Callable


MODE_ENV = "HOCUSPOCUS_EXECUTION_MODE"
WORKSPACE_ENV = "HOCUSPOCUS_E2E_WORKSPACE"
ALLOW_PAID_ENV = "HOCUSPOCUS_E2E_ALLOW_PAID"
STEP_DELAY_ENV = "HOCUSPOCUS_SIMULATION_STEP_DELAY"
FAIL_KIND_ENV = "HOCUSPOCUS_SIMULATION_FAIL_KIND"
FAIL_COUNT_ENV = "HOCUSPOCUS_SIMULATION_FAIL_COUNT"
DEFAULT_WORKSPACE = "e2e_wizard"
VALID_MODES = frozenset({"real", "plan", "simulate"})


class ExecutionModeError(ValueError):
    """The boot-time execution policy refused an operation."""


@dataclass(frozen=True)
class ExecutionPolicy:
    mode: str
    workspace: str
    allow_paid: bool
    step_delay: float
    fail_kind: str
    fail_count: int

    @property
    def simulated(self) -> bool:
        return self.mode == "simulate"

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("fail_kind", None)
        value.pop("fail_count", None)
        value["simulated"] = self.simulated
        value["locked_at_boot"] = True
        return value


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _load_policy() -> ExecutionPolicy:
    mode = str(os.environ.get(MODE_ENV, "real") or "real").strip().casefold()
    if mode not in VALID_MODES:
        raise RuntimeError(
            f"{MODE_ENV} must be one of {', '.join(sorted(VALID_MODES))}; got {mode!r}"
        )
    workspace = str(os.environ.get(WORKSPACE_ENV, DEFAULT_WORKSPACE) or "").strip()
    if not workspace or workspace == "default":
        raise RuntimeError(f"{WORKSPACE_ENV} must name a non-default test workspace")
    try:
        delay = max(0.0, min(5.0, float(os.environ.get(STEP_DELAY_ENV, "0.05"))))
    except (TypeError, ValueError):
        delay = 0.05
    fail_kind = str(os.environ.get(FAIL_KIND_ENV, "") or "").strip().casefold()
    try:
        fail_count = max(-1, int(os.environ.get(FAIL_COUNT_ENV, "1")))
    except (TypeError, ValueError):
        fail_count = 1
    return ExecutionPolicy(
        mode=mode,
        workspace=workspace,
        allow_paid=_truthy(os.environ.get(ALLOW_PAID_ENV)),
        step_delay=delay,
        fail_kind=fail_kind,
        fail_count=fail_count,
    )


# Intentionally immutable after import: neither an HTTP request nor the LLM can
# turn simulation on in a normal running process.
POLICY = _load_policy()
_FAILURE_LOCK = threading.RLock()
_FAILURES_EMITTED: dict[str, int] = {}


def policy() -> ExecutionPolicy:
    return POLICY


def validate_workspace(workspace: str) -> None:
    if POLICY.mode != "real" and str(workspace) != POLICY.workspace:
        raise ExecutionModeError(
            f"{POLICY.mode.title()} mode is isolated to workspace {POLICY.workspace!r}; "
            f"refusing workspace {workspace!r}"
        )


def validate_generation(workspace: str) -> None:
    validate_workspace(workspace)
    if POLICY.mode == "plan":
        raise ExecutionModeError(
            "Plan mode stops before queue submission. Restart with "
            f"{MODE_ENV}=simulate or real to execute generation."
        )


def validate_remote_provider(workspace: str, provider: str) -> None:
    validate_generation(workspace)
    if POLICY.mode != "real" and not POLICY.allow_paid:
        raise ExecutionModeError(
            f"Remote provider {provider!r} is disabled in {POLICY.mode} mode. "
            f"Set {ALLOW_PAID_ENV}=1 before boot to opt in explicitly."
        )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload)) + kind + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def _write_png(path: Path) -> None:
    width, height = 96, 54
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend((24 + x, 18 + y * 2, 72 + ((x + y) % 96), 255))
        rows.append(bytes(row))
    payload = b"".join(rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(payload, 9))
        + _png_chunk(b"IEND", b"")
    )


def _write_wav(path: Path, duration: float = 1.0) -> None:
    sample_rate = 16_000
    frame_count = max(1, int(sample_rate * duration))
    frames = bytearray()
    for index in range(frame_count):
        envelope = min(1.0, index / 800, (frame_count - index) / 800)
        value = int(2_500 * envelope * math.sin(2 * math.pi * 220 * index / sample_rate))
        frames.extend(struct.pack("<h", value))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(frames))


def _write_mp4(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Simulation needs ffmpeg to create a valid chained MP4 fixture")
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=#181248:s=96x54:r=24:d=1",
        "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=16000:duration=1",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-movflags", "+faststart", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode or not path.is_file():
        raise RuntimeError(f"Could not create simulated MP4: {result.stderr[-500:]}")


def _write_glb(path: Path) -> None:
    document = json.dumps({"asset": {"version": "2.0", "generator": "HocusPocus simulation"}}, separators=(",", ":")).encode()
    document += b" " * ((4 - len(document) % 4) % 4)
    chunk = struct.pack("<I4s", len(document), b"JSON") + document
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk)


def result_kind(params: dict[str, Any]) -> str:
    mode = str(params.get("generation_mode") or "video").strip().casefold()
    if mode in {"image", "audio", "video", "3d", "model3d"}:
        return "model3d" if mode in {"3d", "model3d"} else mode
    if params.get("image_mode"):
        return "image"
    return "video"


def _consume_injected_failure(kind: str) -> bool:
    if POLICY.fail_kind not in {"any", kind} or POLICY.fail_count == 0:
        return False
    with _FAILURE_LOCK:
        emitted = _FAILURES_EMITTED.get(kind, 0)
        if POLICY.fail_count >= 0 and emitted >= POLICY.fail_count:
            return False
        _FAILURES_EMITTED[kind] = emitted + 1
        return True


def create_artifact(
    params: dict[str, Any],
    output_dir: str,
    job_id: str,
    *,
    progress: Callable[[str, int, int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    """Create one tiny valid artifact while exposing realistic progress."""
    kind = result_kind(params)
    if _consume_injected_failure(kind):
        raise RuntimeError(f"Injected simulated {kind} executor failure")
    for step, value in enumerate((8, 32, 67, 92), start=1):
        if cancelled and cancelled():
            raise InterruptedError("Simulated generation cancelled")
        if progress:
            progress(f"Simulating {kind} inference…", value, step, 4)
        if POLICY.step_delay:
            time.sleep(POLICY.step_delay)

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    extension = {"image": ".png", "audio": ".wav", "video": ".mp4", "model3d": ".glb"}[kind]
    path = root / f"simulated_{kind}_{job_id}{extension}"
    if kind == "image":
        _write_png(path)
    elif kind == "audio":
        _write_wav(path)
    elif kind == "video":
        _write_mp4(path)
    else:
        _write_glb(path)
    return str(path)
