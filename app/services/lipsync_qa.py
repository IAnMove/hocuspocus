"""Lip-sync check for a clip generated with driving audio.

``qa.lipsync`` measures mouth opening per frame with DWPose (already in ckpts/pose) and
correlates it with the vocal envelope of the matching audio, searching ±8 frames of lag.
It returns a verdict so an agent never has to watch the clip to decide a retake:
ok (best_r >= 0.35 and |lag| <= 0.2 s), retake, or unreliable (the face is not
detected well enough, e.g. an extreme close-up; no misleading number is reported).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import numpy as np

POSE = Path(__file__).resolve().parents[1] / "ckpts" / "pose"
OPERATION = "qa.lipsync"
MIN_R, MAX_LAG_S, MIN_FACE = 0.35, 0.2, 0.5
LAGS = range(-8, 9)


def best_lag(mouth: np.ndarray, envelope: np.ndarray, fps: float = 24.0) -> tuple[float, float, float]:
    """(r at lag 0, best r, best lag in seconds; positive = mouth late)."""
    n = len(mouth)
    results = []
    for lag in LAGS:
        a = mouth[max(0, lag):n + min(0, lag)]
        b = envelope[max(0, -lag):max(0, -lag) + len(a)]
        k = min(len(a), len(b))
        if k < 8 or np.std(a[:k]) == 0 or np.std(b[:k]) == 0:
            results.append((0.0, lag / fps))
            continue
        results.append((float(np.corrcoef(a[:k], b[:k])[0, 1]), lag / fps))
    at_zero = next(r for r, lag in results if lag == 0)
    r, lag = max(results)
    return round(at_zero, 3), round(r, 3), round(lag, 3)


def verdict(face_conf: float, best_r: float, lag_s: float) -> str:
    if face_conf < MIN_FACE:
        return "unreliable"
    return "ok" if best_r >= MIN_R and abs(lag_s) <= MAX_LAG_S else "retake"


class _Pose:
    def __init__(self) -> None:
        import onnxruntime as ort
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.det = ort.InferenceSession(str(POSE / "yolox_l.onnx"), providers=providers)
        self.pose = ort.InferenceSession(str(POSE / "dw-ll_ucoco_384.onnx"), providers=providers)

    def box(self, img: np.ndarray) -> np.ndarray:
        import cv2
        h, w = img.shape[:2]
        s = min(640 / h, 640 / w)
        canvas = np.full((640, 640, 3), 114, np.uint8)
        resized = cv2.resize(img, (int(w * s), int(h * s)))
        canvas[:resized.shape[0], :resized.shape[1]] = resized
        out = self.det.run(None, {self.det.get_inputs()[0].name: canvas.transpose(2, 0, 1)[None].astype(np.float32)})[0][0]
        grids, strides = [], []
        for stride in (8, 16, 32):
            n = 640 // stride
            yv, xv = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
            grids.append(np.stack((xv, yv), 2).reshape(-1, 2))
            strides.append(np.full((n * n, 1), stride))
        grid, stride = np.concatenate(grids), np.concatenate(strides)
        out[:, :2] = (out[:, :2] + grid) * stride
        out[:, 2:4] = np.exp(out[:, 2:4]) * stride
        i = int(np.argmax(out[:, 4] * out[:, 5]))
        cx, cy, bw, bh = out[i, :4] / s
        return np.array([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2])

    def mouth(self, img: np.ndarray, box: np.ndarray) -> tuple[float, float]:
        import cv2
        x0, y0, x1, y1 = box
        cx, cy, bw, bh = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) * 1.25, (y1 - y0) * 1.25
        if bw / bh > 192 / 256:
            bh = bw * 256 / 192
        else:
            bw = bh * 192 / 256
        src = np.float32([[cx - bw / 2, cy - bh / 2], [cx + bw / 2, cy - bh / 2], [cx - bw / 2, cy + bh / 2]])
        m = cv2.getAffineTransform(src, np.float32([[0, 0], [288, 0], [0, 384]]))
        crop = cv2.warpAffine(img, m, (288, 384))
        x = ((crop[:, :, ::-1] - [123.675, 116.28, 103.53]) / [58.395, 57.12, 57.375]).transpose(2, 0, 1)[None].astype(np.float32)
        sx, sy = self.pose.run(None, {self.pose.get_inputs()[0].name: x})
        px, py = sx[0].argmax(1) / 2.0, sy[0].argmax(1) / 2.0
        conf = np.minimum(sx[0].max(1), sy[0].max(1))
        pts = np.stack([px, py, np.ones_like(px)], 1) @ cv2.invertAffineTransform(m).T
        face = pts[23:91]
        height = np.linalg.norm(face[8] - face[27]) + 1e-6
        gap = np.linalg.norm(face[65:68].mean(0) - face[61:64].mean(0))
        return float(gap / height), float(conf[23:91].mean())


def measure(clip: str, audio: str, offset: float = 0.0) -> dict[str, Any]:
    import cv2
    import librosa
    pose, cap, values, box, index = _Pose(), cv2.VideoCapture(clip), [], None, 0
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if box is None or index % 12 == 0:
            box = pose.box(frame)
        values.append(pose.mouth(frame, box))
        index += 1
    if not values:
        return {"verdict": "unreliable", "frames": 0}
    data = np.array(values)
    mouth = np.convolve(data[:, 0], np.ones(3) / 3, "same")
    wave, sr = librosa.load(audio, sr=16000, offset=max(0.0, offset), duration=len(mouth) / fps + 0.5)
    envelope = np.convolve(librosa.feature.rms(y=wave, frame_length=1024, hop_length=int(sr / fps))[0], np.ones(3) / 3, "same")
    r0, r, lag = best_lag(mouth, envelope, fps)
    face = round(float(data[:, 1].mean()), 3)
    result = {"frames": len(mouth), "face_conf": face, "r_at_0": r0, "best_r": r, "best_lag_s": lag, "verdict": verdict(face, r, lag)}
    result["suggested_sync_s"] = lag if result["verdict"] == "ok" else 0.0
    return result


def command_catalog() -> list[dict[str, Any]]:
    return [{
        "name": OPERATION,
        "description": ("Check lip-sync of a workspace video against the audio that drove it: DWPose mouth opening vs vocal "
                        "envelope, ±8 frames of lag. Returns verdict ok|retake|unreliable, best_r, best_lag_s and "
                        "suggested_sync_s (seconds to shift the clip). audio is a workspace file (the song or its "
                        "isolated vocals); offset is where the clip starts inside it. CPU lane, no downloads."),
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"], "properties": {
            "version": {"type": "integer", "const": 1},
            "input": {"type": "object", "additionalProperties": False, "required": ["workspace", "clip", "audio"], "properties": {
                "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                "clip": {"type": "string", "minLength": 1, "maxLength": 300},
                "audio": {"type": "string", "minLength": 1, "maxLength": 300},
                "offset": {"type": "number", "minimum": 0, "maximum": 3600},
            }},
        }},
    }]


def _inside(root: Path, name: str) -> Path:
    from fastapi import HTTPException
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(404, {"code": "file_not_found", "message": f"{name} is not a workspace file", "retryable": False})
    return path


def command_handlers(workspace_dir: Callable[[str], str]) -> dict[str, Callable[[Any], Any]]:
    async def handle(arguments: Any) -> dict[str, Any]:
        import uuid
        from fastapi import HTTPException
        from starlette.concurrency import run_in_threadpool
        from services import resource_scheduler
        data = (arguments or {}).get("input") if isinstance(arguments, dict) else None
        if not isinstance(data, dict) or not all(isinstance(data.get(k), str) for k in ("workspace", "clip", "audio")):
            raise HTTPException(422, {"code": "invalid_command", "message": "Use version 1 with input.workspace, clip and audio", "retryable": False})
        root = Path(workspace_dir(data["workspace"])).resolve()
        clip, audio = _inside(root, data["clip"]), _inside(root, data["audio"])

        def run() -> dict[str, Any]:
            with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("audio-analysis"),
                                                        task_id=f"lipsync-{uuid.uuid4().hex}", description="Lip-sync check"):
                return measure(str(clip), str(audio), float(data.get("offset") or 0))
        return {"version": 1, "status": "completed", "operation": OPERATION, "result": await run_in_threadpool(run)}

    return {OPERATION: handle}
