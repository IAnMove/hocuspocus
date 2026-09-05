"""MiniMax Image-01 client shared by Comic Studio and Director.

The endpoint and model identifier are intentionally fixed here. Credentials are
provided at call time from Maestro's ignored server configuration and are never
written to generation metadata.
"""

from __future__ import annotations

import base64
import math
import mimetypes
import os
import re
import time
import threading
import uuid

import requests

from . import resource_scheduler
from .asset_manifest import publish_generation_sidecar


MODEL_ID = "minimax:image-01"
API_MODEL = "image-01"
API_URL = "https://api.minimax.io/v1/image_generation"
SUPPORTED_ASPECT_RATIOS = (
    "1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9",
)


class MiniMaxImageError(RuntimeError):
    """Provider/configuration error safe to surface to an API client."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def prepare_prompt(prompt: str) -> str:
    """Normalize Director prose and respect Image-01's 1,500-char limit."""
    value = " ".join(str(prompt or "").split()).strip()
    if not value:
        raise MiniMaxImageError("A prompt is required", 400)
    if len(value) > 10000:
        raise MiniMaxImageError("A prompt of at most 10000 characters is required", 400)
    if len(value) >= 1500:
        head = value[:480].rsplit(" ", 1)[0].rstrip(" ,;:-")
        tail = value[-960:].split(" ", 1)[-1].lstrip(" ,;:-")
        value = f"{head}. {tail}"
    return value


def aspect_ratio_for_resolution(resolution: str, default: str = "16:9") -> str:
    """Map an arbitrary WxH resolution to the nearest supported API ratio."""
    value = str(resolution or "").strip()
    if value in SUPPORTED_ASPECT_RATIOS:
        return value
    match = re.search(r"(\d+)\s*[xX×]\s*(\d+)", value)
    if not match:
        return default
    width, height = int(match.group(1)), int(match.group(2))
    if width <= 0 or height <= 0:
        return default
    target = width / height
    return min(
        SUPPORTED_ASPECT_RATIOS,
        key=lambda ratio: abs(math.log(target / (int(ratio.split(":")[0]) / int(ratio.split(":")[1])))),
    )


def local_image_data_uri(path: str) -> str:
    """Encode one validated local identity reference for Image-01."""
    if not path or not os.path.isfile(path):
        raise MiniMaxImageError("MiniMax identity reference is unavailable", 400)
    if os.path.getsize(path) > 20 * 1024 * 1024:
        raise MiniMaxImageError("MiniMax identity reference is too large", 413)
    mime = mimetypes.guess_type(path)[0] or "image/png"
    if not mime.startswith("image/"):
        raise MiniMaxImageError("MiniMax identity reference must be an image", 400)
    with open(path, "rb") as handle:
        encoded = base64.b64encode(handle.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def generate_image(
    *,
    api_key: str,
    prompt: str,
    aspect_ratio: str,
    output_dir: str,
    subject_reference: str = "",
    filename_prefix: str = "minimax-image-01",
    task_id: str = "",
    root_task_id: str = "",
) -> dict:
    """Generate and persist one Image-01 image plus secret-free metadata."""
    if not str(api_key or "").strip():
        raise MiniMaxImageError("Set the MiniMax API key in Settings → Services", 400)
    clean_prompt = prepare_prompt(prompt)
    if aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
        raise MiniMaxImageError("Unsupported MiniMax image aspect ratio", 400)

    request_body = {
        "model": API_MODEL,
        "prompt": clean_prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": "base64",
        "n": 1,
        "prompt_optimizer": False,
    }
    if subject_reference:
        request_body["subject_reference"] = [{
            "type": "character",
            "image_file": subject_reference,
        }]

    response = None
    try:
        lane = resource_scheduler.remote_lane("minimax", API_URL)
        with resource_scheduler.coordinator.acquire(
            lane,
            task_id=f"minimax-image-{threading.get_ident()}-{time.time_ns()}",
            description="MiniMax Image-01 request",
        ):
            response = requests.post(
                API_URL,
                json=request_body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=(15, 300),
            )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        detail = ""
        if response is not None:
            detail = str(getattr(response, "text", ""))[:500]
        raise MiniMaxImageError(f"MiniMax request failed: {detail or exc}") from exc
    except (TypeError, ValueError) as exc:
        raise MiniMaxImageError("MiniMax returned an invalid response") from exc

    base_resp = payload.get("base_resp") or {}
    if base_resp.get("status_code", 0) != 0:
        raise MiniMaxImageError(base_resp.get("status_msg") or "MiniMax returned an error")
    encoded = (payload.get("data") or {}).get("image_base64")
    if not isinstance(encoded, list) or not encoded:
        raise MiniMaxImageError("MiniMax returned no image")
    try:
        image_bytes = base64.b64decode(encoded[0], validate=True)
    except Exception as exc:
        raise MiniMaxImageError("MiniMax returned invalid image data") from exc
    if len(image_bytes) > 50 * 1024 * 1024:
        raise MiniMaxImageError("MiniMax image is too large", 413)

    os.makedirs(output_dir, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%Hh%Mm%Ss")
    name = f"{stamp}_{filename_prefix}_{uuid.uuid4().hex[:8]}.jpg"
    path = os.path.join(output_dir, name)
    with open(path + ".tmp", "wb") as handle:
        handle.write(image_bytes)
    os.replace(path + ".tmp", path)

    publish_generation_sidecar(
        path,
        {
            "generation_mode": "image",
            "task_id": str(task_id or "") or None,
            "root_task_id": str(root_task_id or task_id or "") or None,
            "params": {
                "prompt": clean_prompt,
                "provider": "minimax",
                "model_type": API_MODEL,
                "aspect_ratio": aspect_ratio,
            },
            "created_at": time.time(),
        },
        tool="minimax-image",
    )
    return {
        "name": name,
        "path": path,
        "prompt": clean_prompt,
        "aspect_ratio": aspect_ratio,
        "subject_reference": bool(subject_reference),
    }
