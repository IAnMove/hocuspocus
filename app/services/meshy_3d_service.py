"""Meshy image-to-3D and text-to-3D client. Polls until a GLB is ready."""

from __future__ import annotations

import os
import time
from typing import Any, Callable

import requests

from .minimax_image_service import local_image_data_uri


API_ROOT = "https://api.meshy.ai/openapi"
IMAGE_TO_3D = f"{API_ROOT}/v1/image-to-3d"
TEXT_TO_3D = f"{API_ROOT}/v2/text-to-3d"
DEFAULT_MODEL = "latest"


class Meshy3DError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _raise_http(response: requests.Response, fallback: str) -> None:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    message = (
        str(payload.get("message") or payload.get("error") or "").strip()
        or fallback
        or f"HTTP {response.status_code}"
    )
    raise Meshy3DError(message, response.status_code or 502)


def _task_id(payload: Any) -> str:
    if isinstance(payload, dict):
        result = payload.get("result") or payload.get("id")
        if result:
            return str(result)
    raise Meshy3DError("Meshy did not return a task id")


def _poll(
    url: str,
    headers: dict[str, str],
    *,
    cancelled: Callable[[], bool] | None,
    timeout_s: float = 15 * 60,
) -> dict[str, Any]:
    started = time.time()
    while True:
        if cancelled and cancelled():
            raise Meshy3DError("Meshy generation cancelled", 499)
        response = requests.get(url, headers=headers, timeout=(15, 60))
        if not response.ok:
            _raise_http(response, "Meshy status request failed")
        payload = response.json() if response.content else {}
        status = str(payload.get("status") or "").upper()
        if status == "SUCCEEDED":
            return payload
        if status in {"FAILED", "CANCELED", "CANCELLED"}:
            error = payload.get("task_error") or {}
            raise Meshy3DError(str(error.get("message") or f"Meshy {status.lower()}"))
        if time.time() - started > timeout_s:
            raise Meshy3DError("Meshy timed out waiting for the 3D model")
        time.sleep(3)


def _download_glb(task: dict[str, Any], output_dir: str, stem: str) -> str:
    urls = task.get("model_urls") or {}
    glb_url = str(urls.get("glb") or "").strip()
    if not glb_url:
        raise Meshy3DError("Meshy returned no GLB")
    download = requests.get(glb_url, timeout=(15, 180))
    download.raise_for_status()
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{stem}.glb")
    with open(path, "wb") as handle:
        handle.write(download.content)
    return path


def generate_model(
    *,
    api_key: str,
    output_dir: str,
    prompt: str = "",
    image_path: str | None = None,
    model: str = DEFAULT_MODEL,
    cancelled: Callable[[], bool] | None = None,
    filename_stem: str = "meshy",
) -> dict[str, Any]:
    key = str(api_key or "").strip()
    if not key:
        raise Meshy3DError("Configure the Meshy API key in Settings → Services first", 400)
    headers = _headers(key)
    prompt = str(prompt or "").strip()[:600]
    if image_path:
        payload = {
            "image_url": local_image_data_uri(image_path),
            "ai_model": model or DEFAULT_MODEL,
            "target_formats": ["glb"],
        }
        created = requests.post(IMAGE_TO_3D, headers=headers, json=payload, timeout=(15, 60))
        if not created.ok:
            _raise_http(created, "Meshy image-to-3D failed")
        task_id = _task_id(created.json())
        task = _poll(f"{IMAGE_TO_3D}/{task_id}", headers, cancelled=cancelled)
    else:
        if not prompt:
            raise Meshy3DError("A prompt or a reference image is required", 400)
        preview = requests.post(
            TEXT_TO_3D,
            headers=headers,
            json={
                "mode": "preview",
                "prompt": prompt,
                "ai_model": model or DEFAULT_MODEL,
                "target_formats": ["glb"],
            },
            timeout=(15, 60),
        )
        if not preview.ok:
            _raise_http(preview, "Meshy text-to-3D preview failed")
        preview_id = _task_id(preview.json())
        _poll(f"{TEXT_TO_3D}/{preview_id}", headers, cancelled=cancelled)
        refine = requests.post(
            TEXT_TO_3D,
            headers=headers,
            json={
                "mode": "refine",
                "preview_task_id": preview_id,
                "ai_model": model or DEFAULT_MODEL,
                "target_formats": ["glb"],
            },
            timeout=(15, 60),
        )
        if not refine.ok:
            _raise_http(refine, "Meshy text-to-3D refine failed")
        task_id = _task_id(refine.json())
        task = _poll(f"{TEXT_TO_3D}/{task_id}", headers, cancelled=cancelled)
    path = _download_glb(task, output_dir, filename_stem)
    return {
        "path": path,
        "filename": os.path.basename(path),
        "provider": "meshy",
        "model": model or DEFAULT_MODEL,
        "thumbnail_url": str(task.get("thumbnail_url") or ""),
    }
