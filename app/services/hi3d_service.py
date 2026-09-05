"""Hi3D / Hitem3D image-to-3D client.

Hi3D is image-to-3D only. Callers that have a text prompt and no photo should
render a still first (MiniMax Image or a local image model) and pass that path.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

import requests


API_ROOT = "https://api.hitem3d.ai/open-api/v1"
GET_TOKEN_URL = f"{API_ROOT}/get-token"
SUBMIT_URL = f"{API_ROOT}/submit-task"
QUERY_URL = f"{API_ROOT}/query-task"
DEFAULT_MODEL = "hitem3dv2.1"


class Hi3DError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _extract_token(payload: dict[str, Any]) -> str:
    for key in ("accessToken", "access_token", "token"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("accessToken", "access_token", "token"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
        value = str(data.get("result") or "").strip()
        if value:
            return value
    result = payload.get("result")
    if isinstance(result, dict):
        return str(result.get("token") or result.get("accessToken") or "").strip()
    if isinstance(result, str):
        return result.strip()
    return ""


def _extract_task_id(payload: dict[str, Any]) -> str:
    for key in ("task_id", "taskId", "id"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("task_id", "taskId", "id"):
            value = str(data.get(key) or "").strip()
            if value:
                return value
    result = payload.get("result")
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        return str(result.get("task_id") or result.get("id") or "").strip()
    return ""


def _extract_glb_url(payload: dict[str, Any]) -> str:
    for key in ("model_url", "glb_url", "file_url", "url"):
        value = str(payload.get(key) or "").strip()
        if value.startswith("http"):
            return value
    urls = payload.get("model_urls") or payload.get("files") or {}
    if isinstance(urls, dict):
        for key in ("glb", "model", "file"):
            value = str(urls.get(key) or "").strip()
            if value.startswith("http"):
                return value
    data = payload.get("data")
    if isinstance(data, dict):
        nested = _extract_glb_url(data)
        if nested:
            return nested
    result = payload.get("result")
    if isinstance(result, dict):
        return _extract_glb_url(result)
    return ""


def get_access_token(api_key: str) -> str:
    key = str(api_key or "").strip()
    if not key:
        raise Hi3DError("Configure the Hi3D API key in Settings → Services first", 400)
    response = requests.post(
        GET_TOKEN_URL,
        headers={"Authorization": f"Bearer {key}"},
        timeout=(15, 30),
    )
    payload = _json(response)
    token = _extract_token(payload)
    if response.ok and token:
        return token
    if response.ok and not token:
        # Some accounts treat the configured key as the bearer token already.
        return key
    message = str(payload.get("message") or payload.get("msg") or f"HTTP {response.status_code}")
    raise Hi3DError(f"Hi3D token request failed: {message}", response.status_code or 502)


def generate_model(
    *,
    api_key: str,
    image_path: str,
    output_dir: str,
    model: str = DEFAULT_MODEL,
    cancelled: Callable[[], bool] | None = None,
    filename_stem: str = "hi3d",
) -> dict[str, Any]:
    if not image_path or not os.path.isfile(image_path):
        raise Hi3DError("Hi3D needs a reference image. Add a photo or generate a still first.", 400)
    token = get_access_token(api_key)
    headers = {"Authorization": f"Bearer {token}"}
    with open(image_path, "rb") as handle:
        files = {"images": (os.path.basename(image_path), handle, "application/octet-stream")}
        data = {
            "request_type": "3",
            "model": model or DEFAULT_MODEL,
            "format": "2",
        }
        created = requests.post(
            SUBMIT_URL,
            headers=headers,
            data=data,
            files=files,
            timeout=(15, 60),
        )
    payload = _json(created)
    if not created.ok:
        raise Hi3DError(
            str(payload.get("message") or payload.get("msg") or "Hi3D submit failed"),
            created.status_code or 502,
        )
    task_id = _extract_task_id(payload)
    if not task_id:
        raise Hi3DError("Hi3D did not return a task id")
    started = time.time()
    task: dict[str, Any] = {}
    while True:
        if cancelled and cancelled():
            raise Hi3DError("Hi3D generation cancelled", 499)
        status_resp = requests.get(
            QUERY_URL,
            headers=headers,
            params={"task_id": task_id, "id": task_id},
            timeout=(15, 60),
        )
        task = _json(status_resp)
        if not status_resp.ok:
            raise Hi3DError(
                str(task.get("message") or task.get("msg") or "Hi3D status failed"),
                status_resp.status_code or 502,
            )
        status = str(
            task.get("status")
            or (task.get("data") or {}).get("status")
            or ""
        ).upper()
        if status in {"SUCCESS", "SUCCEEDED", "DONE", "COMPLETED"}:
            break
        if status in {"FAILED", "ERROR", "CANCELLED", "CANCELED"}:
            raise Hi3DError(str(task.get("message") or f"Hi3D {status.lower()}"))
        if time.time() - started > 15 * 60:
            raise Hi3DError("Hi3D timed out waiting for the 3D model")
        time.sleep(3)
    glb_url = _extract_glb_url(task)
    if not glb_url:
        raise Hi3DError("Hi3D returned no GLB")
    download = requests.get(glb_url, timeout=(15, 180))
    download.raise_for_status()
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{filename_stem}.glb")
    with open(path, "wb") as handle:
        handle.write(download.content)
    return {
        "path": path,
        "filename": os.path.basename(path),
        "provider": "hi3d",
        "model": model or DEFAULT_MODEL,
    }
