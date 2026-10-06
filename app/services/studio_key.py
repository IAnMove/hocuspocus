"""CPU chroma key for one workspace image or video.

Green (or blue / magenta) screen pixels become transparent and the foreground
is despilled. Pick blue or magenta when the subject itself is green.
Interior mattes use weights 0.15, 0.7, 0.15. A heavier neighbor weight
leaves a halo on motion, so those weights stay fixed. ``isnet-anime``
runs only when that ONNX file is already installed, on CPU, and never
downloads a model.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable, Iterator

import numpy as np
from fastapi import HTTPException
from PIL import Image

from services.media_paths import MediaPathNotAllowed, resolve_permitted_media_path
from services.wangp_submission import wangp_media_url


# Neighbor weight above 0.15 halos moving edges. Do not increase it.
TEMPORAL_WEIGHTS = (0.15, 0.7, 0.15)
_GREEN_START = 0.12
_GREEN_SPAN = 0.25
_DESPILL_GAIN = 1.02
_DESPILL_LIFT = 0.02
_ISNET_NAME = "isnet-anime.onnx"
_ISNET_MEAN = (0.485, 0.456, 0.406)
_ISNET_SIZE = (1024, 1024)
_IMAGE_EXTENSIONS = {".jpeg", ".jpg", ".png", ".webp"}
_ENVELOPE_KEYS = frozenset({"version", "input", "intent_id"})
SCREENS = ("green", "blue", "magenta")
_INPUT_KEYS = frozenset({"workspace", "source", "mode"})
MAX_SECONDS = 60
MAX_FRAMES = 1800
MAX_EDGE = 1920
_MODEL_NOT_INSTALLED = "isnet-anime is not installed. Use mode green."


class StudioKeyError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def command_catalog() -> list[dict]:
    payload = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
            "source": {"type": "string", "minLength": 1, "maxLength": 2000},
            "mode": {"type": "string", "enum": [*SCREENS, "isnet-anime"],
                     "description": "Screen colour (default green). Use blue or magenta when the subject contains green."},
        },
        "required": ["workspace", "source"],
    }
    return [{
        "name": "studio.key",
        "version": 1,
        "domain": "studio",
        "mutation": True,
        "description": (
            "Key a workspace image or video on the CPU. Green, blue or magenta screen "
            "pixels become transparent, foreground spill is removed, and interior mattes are "
            "smoothed with fixed weights 0.15, 0.7, 0.15. Stronger smoothing leaves "
            "halos, so those weights do not change. mode isnet-anime runs only when "
            "that model is already installed; otherwise the call fails with "
            "model_not_installed and green remains available. Returns file, url, "
            "sha256, and frames. Does not return pixels, use the GPU, or download a model. "
            "An optional intent_id replays the stored result instead of keying again."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "intent_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "input": payload,
            },
            "required": ["version", "input"],
        },
    }]


def command_handlers(workspace_dir, uploads_dir, find_model: Callable[[], str | None] | None = None):
    finder = find_model or find_isnet_model

    async def handle(arguments: dict) -> dict:
        try:
            result = _key_once(arguments, workspace_dir, lambda: _with_sidecar(key_request(
                arguments,
                workspace_dir=workspace_dir,
                uploads_dir=uploads_dir,
                find_model=finder,
            ), arguments, workspace_dir))
        except StudioKeyError as exc:
            raise HTTPException(exc.status, {
                "code": exc.code,
                "message": exc.message,
                "retryable": False,
            }) from exc
        return {"version": 1, "status": "completed", "operation": "studio.key", "result": result}

    return {"studio.key": handle}


def _with_sidecar(result: dict, arguments, workspace_dir) -> dict:
    """The keyed file's sidecar: its source, screen mode and options (services/tool_sidecars.py)."""
    from services.tool_sidecars import key_sidecar
    payload = _input(arguments)
    return key_sidecar(result, payload, _folder(workspace_dir, payload["workspace"]))


def _key_once(arguments, workspace_dir, run: Callable[[], dict]) -> dict:
    """Same intent_id and input: the stored result, not a second keyed file."""
    intent = arguments.get("intent_id") if isinstance(arguments, dict) else None
    if intent is None:
        return run()
    from pathlib import Path
    from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent
    payload = _input(arguments)
    try:
        intent_id = check_intent_id(intent)
        digest = intent_digest(payload)
        root = Path(_folder(workspace_dir, payload["workspace"]))
        previous = load_intent(root, "studio.key", intent_id, digest)
    except IntentConflict as exc:
        raise StudioKeyError("intent_conflict", str(exc), 409) from exc
    if previous is not None:
        return {**previous, "replayed": True}
    result = run()
    store_intent(root, "studio.key", intent_id, digest, result)
    return result


def key_request(arguments, *, workspace_dir, uploads_dir, find_model: Callable[[], str | None]) -> dict:
    payload = _input(arguments)
    workspace = payload["workspace"]
    folder = _folder(workspace_dir, workspace)
    uploads_root = uploads_dir() if callable(uploads_dir) else uploads_dir
    if not isinstance(uploads_root, str) or not uploads_root:
        raise StudioKeyError("invalid_command", "workspace is not available.")
    mode = _mode(payload)
    session = _session_for(mode, find_model)
    source = _source(payload["source"], workspace, uploads_root, folder)
    suffix = ".png" if _is_image(source) else ".webm"
    destination = _destination(folder, source, suffix)
    frames = _key_file(source, destination, mode, session)
    return _published(destination, workspace, uploads_root, folder, frames)


def screen_rgba(rgb: np.ndarray, screen: str = "green") -> np.ndarray:
    """Despill one RGB frame and attach a matte for a green, blue or magenta screen."""
    color = np.asarray(rgb, dtype=np.float32) / 255.0
    red, green, blue = color[..., 0], color[..., 1], color[..., 2]
    color = np.array(color, copy=True)
    if screen == "magenta":
        # Magenta is strong red and blue over weak green.
        keyness = np.minimum(red, blue) - green
        excess = np.clip(np.minimum(red, blue) - (green * _DESPILL_GAIN + _DESPILL_LIFT), 0.0, None)
        color[..., 0] = red - excess
        color[..., 2] = blue - excess
    else:
        index = 1 if screen == "green" else 2
        others = np.maximum(red, blue) if index == 1 else np.maximum(red, green)
        keyness = color[..., index] - others
        color[..., index] = np.minimum(color[..., index], others * _DESPILL_GAIN + _DESPILL_LIFT)
    alpha = 1.0 - np.clip((keyness - _GREEN_START) / _GREEN_SPAN, 0.0, 1.0)
    rgba = np.concatenate([color, alpha[..., None]], axis=-1)
    return np.clip(np.rint(rgba * 255.0), 0, 255).astype(np.uint8)


def green_rgba(rgb: np.ndarray) -> np.ndarray:
    """Despill one RGB frame and attach a green-screen matte."""
    return screen_rgba(rgb, "green")


def smooth_alpha(frames: list[np.ndarray]) -> list[np.ndarray]:
    """Blend interior mattes only. The first and last frame stay put."""
    if len(frames) < 3:
        return [np.array(frame, copy=True) for frame in frames]
    blended = [np.array(frames[0], copy=True)]
    for index in range(1, len(frames) - 1):
        blended.append(_mix_alpha(frames[index - 1], frames[index], frames[index + 1]))
    blended.append(np.array(frames[-1], copy=True))
    return blended


def find_isnet_model() -> str | None:
    """Return an installed isnet-anime ONNX file, never a download URL."""
    roots = []
    home = os.environ.get("U2NET_HOME")
    if home:
        roots.append(home)
    roots.append(os.path.join(os.getcwd(), "ckpts", "rembg"))
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    roots.append(os.path.join(app_dir, "ckpts", "rembg"))
    xdg = os.environ.get("XDG_DATA_HOME", "~")
    roots.append(os.path.expanduser(os.path.join(xdg, ".u2net")))
    return existing_isnet(roots)


def existing_isnet(roots) -> str | None:
    for root in roots:
        if not root:
            continue
        candidate = os.path.join(root, _ISNET_NAME)
        if os.path.isfile(candidate):
            return candidate
    return None


class AlphaWindow:
    """Stream mattes with one frame of delay. Ends are not smoothed."""

    def __init__(self) -> None:
        self._queue: list[np.ndarray] = []
        self._seen = 0
        self._next = 0

    def push(self, frame: np.ndarray) -> list[np.ndarray]:
        self._queue.append(np.array(frame, copy=True))
        self._seen += 1
        return self._drain(False)

    def finish(self) -> list[np.ndarray]:
        return self._drain(True)

    def _drain(self, final: bool) -> list[np.ndarray]:
        ready = []
        limit = self._seen if final else max(0, self._seen - 1)
        while self._next < limit:
            ready.append(self._at(self._next))
            self._next += 1
            self._drop()
        return ready

    def _at(self, index: int) -> np.ndarray:
        start = self._seen - len(self._queue)
        local = index - start
        frame = self._queue[local]
        interior = 0 < index < self._seen - 1 and self._seen >= 3
        if not interior:
            return np.array(frame, copy=True)
        mixed = _mix_alpha(self._queue[local - 1][..., 3], frame[..., 3], self._queue[local + 1][..., 3])
        out = np.array(frame, copy=True)
        out[..., 3] = np.clip(np.rint(mixed), 0, 255).astype(np.uint8)
        return out

    def _drop(self) -> None:
        start = self._seen - len(self._queue)
        while self._queue and start < self._next - 1:
            self._queue.pop(0)
            start += 1


def _mix_alpha(left, mid, right):
    previous, current, following = TEMPORAL_WEIGHTS
    return previous * left + current * mid + following * right


def _input(arguments) -> dict:
    if not isinstance(arguments, dict) or arguments.get("version") != 1:
        raise StudioKeyError("invalid_command", "Use version 1 and an input object.")
    if set(arguments) - _ENVELOPE_KEYS:
        raise StudioKeyError("invalid_command", "Use version 1 and an input object.")
    payload = arguments.get("input")
    if not isinstance(payload, dict) or set(payload) - _INPUT_KEYS:
        raise StudioKeyError("invalid_command", "Use version 1 and an input object.")
    if "workspace" not in payload or "source" not in payload:
        raise StudioKeyError("invalid_command", "workspace and source are required.")
    return payload


def _mode(payload: dict) -> str:
    mode = payload.get("mode", "green")
    if mode in SCREENS or mode == "isnet-anime":
        return mode
    raise StudioKeyError("invalid_command", "mode must be green, blue, magenta or isnet-anime.")


def _folder(workspace_dir, name: str) -> str:
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise StudioKeyError("invalid_command", "workspace is required.")
    try:
        folder = workspace_dir(name)
    except HTTPException:
        raise
    except Exception as exc:
        raise StudioKeyError("invalid_command", "workspace is not available.") from exc
    if not isinstance(folder, str) or not folder:
        raise StudioKeyError("invalid_command", "workspace is not available.")
    os.makedirs(folder, exist_ok=True)
    return folder


def _source(value, workspace: str, uploads_root: str, folder: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StudioKeyError("invalid_command", "source is required.")
    try:
        return resolve_permitted_media_path(
            value,
            uploads_root=uploads_root,
            workspace_root=folder,
            kinds=("image", "video"),
            workspace_name=workspace,
        )
    except MediaPathNotAllowed as exc:
        code = "unsupported_media" if str(exc) == "Media type is not allowed" else "path_not_allowed"
        raise StudioKeyError(code, "Media path is not allowed.") from exc
    except FileNotFoundError as exc:
        raise StudioKeyError("media_not_found", "Media file was not found.", 404) from exc


def _session_for(mode: str, find_model: Callable[[], str | None]):
    if mode != "isnet-anime":
        return None
    path = find_model()
    if not path or not os.path.isfile(path):
        raise StudioKeyError("model_not_installed", _MODEL_NOT_INSTALLED)
    try:
        return _cpu_session(path)
    except (OSError, RuntimeError, ImportError) as exc:
        raise StudioKeyError("model_not_installed", _MODEL_NOT_INSTALLED) from exc


def _cpu_session(model_path: str):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    return ort.InferenceSession(model_path, sess_options=options, providers=["CPUExecutionProvider"])


def _is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTENSIONS


def _destination(folder: str, source: str, suffix: str) -> str:
    stem = os.path.splitext(os.path.basename(source))[0][:80] or "key"
    candidate = os.path.join(folder, f"{stem}-key{suffix}")
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{stem}-key-{index}{suffix}")
        index += 1
        if index > 1000:
            raise StudioKeyError("key_failed", "Keying failed.")
    return candidate


def _key_file(source: str, destination: str, mode: str, session) -> int:
    try:
        frames = _key_image(source, destination, mode, session) if _is_image(source) else _key_video(source, destination, mode, session)
    except StudioKeyError:
        _remove(destination)
        raise
    except Exception as exc:
        _remove(destination)
        raise StudioKeyError("key_failed", "Keying failed.") from exc
    if frames < 1:
        _remove(destination)
        raise StudioKeyError("key_failed", "Keying failed.")
    return frames


def _key_image(source: str, destination: str, mode: str, session) -> int:
    with Image.open(source) as opened:
        rgb = np.asarray(opened.convert("RGB"))
    Image.fromarray(_rgba_frame(rgb, mode, session)).save(destination, format="PNG")
    return 1


def _rgba_frame(rgb: np.ndarray, mode: str, session) -> np.ndarray:
    if mode in SCREENS:
        return screen_rgba(rgb, mode)
    alpha = _isnet_alpha(Image.fromarray(np.asarray(rgb)), session)
    rgba = np.empty(rgb.shape[:-1] + (4,), dtype=np.uint8)
    rgba[..., :3] = np.asarray(rgb)[..., :3]
    rgba[..., 3] = alpha
    return rgba


def _isnet_alpha(image: Image.Image, session) -> np.ndarray:
    resized = image.convert("RGB").resize(_ISNET_SIZE, Image.Resampling.LANCZOS)
    array = np.asarray(resized, dtype=np.float32)
    peak = float(array.max()) or 1.0
    array = array / peak
    for channel, mean in enumerate(_ISNET_MEAN):
        array[..., channel] = array[..., channel] - mean
    blob = np.expand_dims(array.transpose(2, 0, 1), 0).astype(np.float32)
    pred = np.squeeze(session.run(None, {session.get_inputs()[0].name: blob})[0][:, 0, :, :])
    low = float(pred.min())
    span = float(pred.max()) - low or 1.0
    pred = (pred - low) / span
    mask = Image.fromarray(np.clip(np.rint(pred * 255.0), 0, 255).astype(np.uint8))
    return np.asarray(mask.resize(image.size, Image.Resampling.LANCZOS), dtype=np.uint8)


def _key_video(source: str, destination: str, mode: str, session) -> int:
    info = _probe(source)
    window = AlphaWindow()
    encoder = _encoder(destination, info)
    count = emitted = 0
    try:
        for rgb in _decode(source, info):
            count += 1
            if count > MAX_FRAMES:
                raise StudioKeyError("source_too_large", "Video exceeds 1800 frames.")
            emitted += _write_ready(encoder, window.push(_rgba_frame(rgb, mode, session)))
        emitted += _write_ready(encoder, window.finish())
        _finish_encoder(encoder)
    finally:
        _stop(encoder)
    if emitted != count or count < 1:
        raise StudioKeyError("key_failed", "Keying failed.")
    return count


def _write_ready(encoder: subprocess.Popen, frames: list[np.ndarray]) -> int:
    for frame in frames:
        encoder.stdin.write(frame.tobytes())
    return len(frames)


def _finish_encoder(encoder: subprocess.Popen) -> None:
    if encoder.stdin is not None:
        encoder.stdin.close()
        encoder.stdin = None
    try:
        code = encoder.wait(timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise StudioKeyError("key_failed", "Keying failed.") from exc
    if code != 0:
        raise StudioKeyError("key_failed", "Keying failed.")


def _probe(source: str) -> dict:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", source],
            capture_output=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StudioKeyError("key_failed", "Keying failed.") from exc
    if result.returncode != 0:
        raise StudioKeyError("key_failed", "Keying failed.")
    width, height, fps, duration = _probe_fields(result.stdout)
    if duration <= 0 or duration > MAX_SECONDS:
        raise StudioKeyError("source_too_large", "Video must be 60 seconds or less.")
    if duration * fps > MAX_FRAMES + 0.1:
        raise StudioKeyError("source_too_large", "Video exceeds 1800 frames.")
    fitted = _fit(width, height)
    return {"width": fitted[0], "height": fitted[1], "fps": f"{fps:.6f}"}


def _probe_fields(payload: bytes) -> tuple[int, int, float, float]:
    try:
        data = json.loads(payload.decode("utf-8", "replace"))
        video = next(stream for stream in data.get("streams", []) if stream.get("codec_type") == "video")
        width, height = int(video["width"]), int(video["height"])
        rate = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "")
        duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
    except (StopIteration, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise StudioKeyError("key_failed", "Keying failed.") from exc
    return width, height, _fps(rate), duration


def _fps(rate: str) -> float:
    parts = rate.split("/")
    try:
        value = float(parts[0]) / float(parts[1]) if len(parts) == 2 else float(rate)
    except (ValueError, ZeroDivisionError) as exc:
        raise StudioKeyError("key_failed", "Keying failed.") from exc
    if not 0 < value <= 60:
        raise StudioKeyError("source_too_large", "Video must be 60 fps or less.")
    return value


def _fit(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        raise StudioKeyError("key_failed", "Keying failed.")
    scale = 1.0 if max(width, height) <= MAX_EDGE else MAX_EDGE / max(width, height)
    return _even(width * scale), _even(height * scale)


def _even(value: float) -> int:
    rounded = int(value) // 2 * 2
    return rounded if rounded >= 2 else 2


def _decode(source: str, info: dict) -> Iterator[np.ndarray]:
    width, height = info["width"], info["height"]
    process = subprocess.Popen(
        [
            "ffmpeg", "-v", "error", "-nostdin", "-i", source, "-map", "0:v:0", "-an",
            "-vf", f"fps={info['fps']},scale={width}:{height}:flags=neighbor,setsar=1",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    frame_bytes = width * height * 3
    try:
        while True:
            blob = process.stdout.read(frame_bytes)
            if not blob:
                break
            if len(blob) != frame_bytes:
                raise StudioKeyError("key_failed", "Keying failed.")
            yield np.frombuffer(blob, dtype=np.uint8).reshape((height, width, 3)).copy()
    finally:
        _stop(process)


def _encoder(destination: str, info: dict) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "ffmpeg", "-v", "error", "-nostdin", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{info['width']}x{info['height']}", "-r", info["fps"], "-i", "pipe:0", "-an",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "18",
            "-deadline", "realtime", "-cpu-used", "5", "-auto-alt-ref", "0",
            "-f", "webm", destination,
        ],
        stdin=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )


def _stop(process: subprocess.Popen | None) -> None:
    if process is None:
        return
    for pipe in (process.stdin, process.stdout):
        if pipe is None:
            continue
        try:
            pipe.close()
        except OSError:
            pass
    if process.poll() is None:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return


def _published(path: str, workspace: str, uploads_root: str, folder: str, frames: int) -> dict:
    try:
        url = wangp_media_url(path, workspace, uploads_dir=uploads_root, workspace_dir=folder)
    except ValueError as exc:
        raise StudioKeyError("path_not_allowed", "Media path is not allowed.") from exc
    return {"file": os.path.basename(path), "url": url, "sha256": _sha256(path), "frames": frames}


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove(path: str) -> None:
    if path and os.path.isfile(path):
        os.remove(path)
