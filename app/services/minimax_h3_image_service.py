"""MiniMax H3-Image over the public API.

The open weights are not loaded. They are a large BF16 checkpoint and are
not for local inference from the EU. Text-to-image is
``POST /v1/images/generations``. One to sixteen reference pictures is
``POST /v1/images/edits``. Prompt enhancement stays on unless the caller
turns it off for text-to-image. The key is passed in and is never written
to a sidecar.
"""
from __future__ import annotations

import math
import os
import re
import threading
import time

import requests

from services import resource_scheduler
from services.asset_manifest import publish_generation_sidecar
from services.generation_output_name import chosen_image_filename
from services.minimax_image_service import MiniMaxImageError, local_image_data_uri
from services.output_names import reserve


API_ORIGIN = "https://api.minimax.io"
GENERATIONS_URL = f"{API_ORIGIN}/v1/images/generations"
EDITS_URL = f"{API_ORIGIN}/v1/images/edits"
MODEL_STANDARD = "minimax:h3-image"
MODEL_FAST = "minimax:h3-image-highspeed"
API_NAMES = {
    MODEL_STANDARD: "MiniMax-H3-Image",
    MODEL_FAST: "MiniMax-H3-Image-Highspeed",
}
MAX_REFERENCES = 16
MAX_PROMPT_CHARS = 32000
MIN_AREA = 655_360
MAX_AREA = 20_000_000
MIN_RATIO = 1 / 3
MAX_RATIO = 3.0
# 2K table from the image guide. Exact pixels, so the API is not asked to invent a size.
_NAMED_2K = {
    "1:1": (2048, 2048),
    "4:3": (2368, 1760),
    "3:4": (1760, 2368),
    "16:9": (2720, 1536),
    "9:16": (1536, 2720),
    "3:1": (3552, 1184),
    "1:3": (1184, 3552),
}
_SIZE = re.compile(r"^\s*(\d+)\s*[xX×]\s*(\d+)\s*$")


def is_h3_image_model(model_type: object) -> bool:
    return isinstance(model_type, str) and model_type in API_NAMES


def api_model_name(model_type: str) -> str:
    try:
        return API_NAMES[model_type]
    except KeyError as exc:
        raise MiniMaxImageError(f"Unknown MiniMax H3-Image model: {model_type}", 422) from exc


def prepare_prompt(prompt: str) -> str:
    """The prompt H3-Image will read. It is not shortened the way Image-01 is."""
    value = " ".join(str(prompt or "").split()).strip()
    if not value:
        raise MiniMaxImageError("A prompt is required", 400)
    if len(value) > MAX_PROMPT_CHARS:
        raise MiniMaxImageError("A prompt of at most 32000 characters is required", 400)
    return value


def _grow_to_area(width: int, height: int) -> tuple[int, int]:
    scale = math.sqrt(MIN_AREA / (width * height))
    width = math.ceil(width * scale)
    height = math.ceil(height * scale)
    while width * height < MIN_AREA:
        if width <= height:
            width += 1
        else:
            height += 1
    return width, height


def _shrink_to_area(width: int, height: int) -> tuple[int, int]:
    scale = math.sqrt(MAX_AREA / (width * height))
    width = max(1, math.floor(width * scale))
    height = max(1, math.floor(height * scale))
    while width * height > MAX_AREA and (width > 1 or height > 1):
        if width >= height and width > 1:
            width -= 1
        elif height > 1:
            height -= 1
        else:
            break
    return width, height


def _fit_pair(width: int, height: int) -> tuple[int, int]:
    """A legal H3 size: area 655360–20000000 and aspect ratio between 1:3 and 3:1."""
    width = max(1, int(width))
    height = max(1, int(height))
    ratio = width / height
    if ratio > MAX_RATIO:
        width = max(1, int(height * MAX_RATIO))
    elif ratio < MIN_RATIO:
        height = max(1, int(width / MIN_RATIO))
    if width * height < MIN_AREA:
        width, height = _grow_to_area(width, height)
    elif width * height > MAX_AREA:
        width, height = _shrink_to_area(width, height)
    return width, height


def output_size(resolution: str) -> str:
    """``WIDTHxHEIGHT`` for the API. A named ratio uses the published 2K size."""
    text = str(resolution or "").strip()
    named = _NAMED_2K.get(text)
    if named:
        width, height = named
    else:
        match = _SIZE.match(text)
        if not match:
            width, height = _NAMED_2K["1:1"]
        else:
            width, height = _fit_pair(int(match.group(1)), int(match.group(2)))
    return f"{width}x{height}"


def _check_dimensions(path: str) -> None:
    """Refuse a picture the API will reject. A file PIL cannot open is left to the API."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            width, height = image.size
    except (OSError, ValueError):
        return
    if width < 128 or height < 128 or width > 8192 or height > 8192:
        raise MiniMaxImageError(
            "Each reference picture must be between 128 and 8192 pixels on each side",
            422,
        )
    long_side, short_side = max(width, height), min(width, height)
    if short_side and long_side / short_side > 4:
        raise MiniMaxImageError(
            "A reference picture cannot be more than four times as long as it is wide",
            422,
        )


def _one_reference(path: str) -> str:
    text = str(path or "")
    if text.startswith("data:image/"):
        if len(text) > 25 * 1024 * 1024:
            raise MiniMaxImageError("A reference picture is too large", 413)
        return text
    _check_dimensions(text)
    return local_image_data_uri(text)


def _reference_inputs(paths: list[str]) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    total = 0
    for path in paths:
        uri = _one_reference(path)
        # Base64 is about 4/3 of the file. The whole JSON body must stay under 64 MiB.
        total += len(uri)
        if total > 48 * 1024 * 1024:
            raise MiniMaxImageError(
                "The reference pictures together are larger than the MiniMax request limit. Use fewer or smaller pictures.",
                413,
            )
        images.append({"image_url": uri})
    return images


def _error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return (response.text or "")[:500]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])[:500]
    return (response.text or "")[:500]


def _status_for(code: int) -> int:
    if code == 402:
        return 402
    if code == 422:
        return 422
    if code == 429:
        return 429
    if code == 400:
        return 422
    return 502


def _post(url: str, body: dict, api_key: str) -> dict:
    response = None
    try:
        lane = resource_scheduler.remote_lane("minimax", API_ORIGIN)
        with resource_scheduler.coordinator.acquire(
            lane,
            task_id=f"minimax-h3-image-{threading.get_ident()}-{time.time_ns()}",
            description="MiniMax H3-Image request",
        ):
            response = requests.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=(20, 600),
            )
        if response.status_code >= 400:
            raise MiniMaxImageError(
                f"MiniMax H3-Image request failed: {_error_message(response) or response.status_code}",
                _status_for(response.status_code),
            )
        payload = response.json()
    except MiniMaxImageError:
        raise
    except requests.RequestException as exc:
        detail = _error_message(response) if response is not None else ""
        raise MiniMaxImageError(f"MiniMax H3-Image request failed: {detail or exc}") from exc
    except (TypeError, ValueError) as exc:
        raise MiniMaxImageError("MiniMax H3-Image returned an invalid response") from exc
    if not isinstance(payload, dict):
        raise MiniMaxImageError("MiniMax H3-Image returned an invalid response")
    return payload


def _first_image(payload: dict) -> dict:
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise MiniMaxImageError("MiniMax H3-Image returned no image")
    item = data[0]
    error = item.get("error")
    if isinstance(error, dict):
        raise MiniMaxImageError(str(error.get("message") or "MiniMax H3-Image returned no image"))
    if not item.get("url"):
        raise MiniMaxImageError("MiniMax H3-Image returned no image")
    return item


def _download(url: str) -> bytes:
    try:
        response = requests.get(url, timeout=(20, 120))
        response.raise_for_status()
    except requests.RequestException as exc:
        raise MiniMaxImageError("MiniMax H3-Image image could not be downloaded") from exc
    content = response.content
    if not content or len(content) > 50 * 1024 * 1024:
        raise MiniMaxImageError("MiniMax H3-Image image is empty or too large", 413)
    return content


def _write_image(output_dir: str, filename_prefix: str, output_name: str | None, content: bytes) -> tuple[str, str, bool]:
    os.makedirs(output_dir, exist_ok=True)
    chosen = chosen_image_filename(output_name, filename_prefix=filename_prefix)
    name, taken = reserve(output_dir, chosen)
    path = os.path.join(output_dir, name)
    temporary = f"{path}.{os.getpid()}.tmp"
    with open(temporary, "wb") as handle:
        handle.write(content)
    os.replace(temporary, path)
    return name, path, taken


def _filled(paths: list[str] | None) -> list[str]:
    return [path for path in (paths or []) if path]


def _request_target(
    model_type: str,
    prompt: str,
    resolution: str,
    paths: list[str],
    disable_prompt_enhanced: bool,
) -> tuple[str, dict, str, str]:
    if len(paths) > MAX_REFERENCES:
        raise MiniMaxImageError("MiniMax H3-Image takes at most 16 reference pictures", 422)
    api_model = api_model_name(model_type)
    size = output_size(resolution)
    body: dict = {
        "model": api_model,
        "prompt": prompt,
        "size": size,
        "n": 1,
        "response_format": "url",
        "output_format": "jpeg",
    }
    if paths:
        body["images"] = _reference_inputs(paths)
        return EDITS_URL, body, api_model, size
    if disable_prompt_enhanced:
        body["disable_prompt_enhanced"] = True
    return GENERATIONS_URL, body, api_model, size


def _file_prefix(model_type: str, filename_prefix: str) -> str:
    if filename_prefix:
        return filename_prefix
    if model_type == MODEL_FAST:
        return "minimax-h3-image-fast"
    return "minimax-h3-image"


def _store_result(
    *,
    item: dict,
    payload: dict,
    content: bytes,
    output_dir: str,
    prefix: str,
    output_name: str | None,
    clean_prompt: str,
    size: str,
    api_model: str,
    model_type: str,
    paths: list[str],
    task_id: str,
    root_task_id: str,
) -> dict:
    name, path, taken = _write_image(output_dir, prefix, output_name, content)
    revised = str(item.get("revised_prompt") or clean_prompt)
    actual_size = str(item.get("size") or size)
    request_id = str(payload.get("request_id") or "")
    publish_generation_sidecar(
        path,
        {
            "generation_mode": "image",
            "task_id": str(task_id or "") or None,
            "root_task_id": str(root_task_id or task_id or "") or None,
            "params": {
                "prompt": clean_prompt,
                "provider": "minimax",
                "model_type": model_type,
                "api_model": api_model,
                "resolution": actual_size,
                "revised_prompt": revised,
                "request_id": request_id,
                "reference_count": len(paths),
            },
            "created_at": time.time(),
        },
        tool="minimax-h3-image",
    )
    requested = chosen_image_filename(output_name, filename_prefix=prefix) if output_name else name
    return {
        "name": name,
        "path": path,
        "prompt": clean_prompt,
        "aspect_ratio": actual_size,
        "size": actual_size,
        "revised_prompt": revised,
        "request_id": request_id,
        "subject_reference": bool(paths),
        "reference_count": len(paths),
        "requested_name": requested,
        "output_name_taken": taken,
        "model_type": model_type,
    }


def generate_image(
    *,
    api_key: str,
    model_type: str,
    prompt: str,
    resolution: str,
    output_dir: str,
    reference_paths: list[str] | None = None,
    disable_prompt_enhanced: bool = False,
    filename_prefix: str = "",
    task_id: str = "",
    root_task_id: str = "",
    output_name: str | None = None,
) -> dict:
    """Generate one H3-Image still and store it next to other studio images."""
    if not str(api_key or "").strip():
        raise MiniMaxImageError("Set the MiniMax API key in Settings → Services", 400)
    clean_prompt = prepare_prompt(prompt)
    paths = _filled(reference_paths)
    url, body, api_model, size = _request_target(
        model_type, clean_prompt, resolution, paths, disable_prompt_enhanced,
    )
    payload = _post(url, body, api_key)
    item = _first_image(payload)
    return _store_result(
        item=item,
        payload=payload,
        content=_download(str(item["url"])),
        output_dir=output_dir,
        prefix=_file_prefix(model_type, filename_prefix),
        output_name=output_name,
        clean_prompt=clean_prompt,
        size=size,
        api_model=api_model,
        model_type=model_type,
        paths=paths,
        task_id=task_id,
        root_task_id=root_task_id,
    )
