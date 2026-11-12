"""Meshy image-to-3D and text-to-3D client. Polls until a GLB is ready.

The HTTP plumbing is ``meshy_http``; the option rules and request bodies are ``meshy_options``;
rigging and animation are ``meshy_rig_service``.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import requests  # noqa: F401  (tests patch ``requests`` through this module)

from . import meshy_http as http
from . import meshy_options as options_module
from .meshy_http import MeshyError
from .minimax_image_service import local_image_data_uri


API_ROOT = http.API_ROOT
IMAGE_TO_3D = f"{API_ROOT}/v1/image-to-3d"
TEXT_TO_3D = f"{API_ROOT}/v2/text-to-3d"
DEFAULT_MODEL = options_module.DEFAULT_AI_MODEL
MAX_PROMPT_CHARS = options_module.MAX_PROMPT_CHARS

Meshy3DError = MeshyError


def _write_atomic(path: str, data: bytes) -> None:
    part = f"{path}.part"
    try:
        with open(part, "wb") as handle:
            handle.write(data)
        os.replace(part, path)
    finally:
        if os.path.exists(part):
            os.unlink(part)


def _download_glb(task: dict[str, Any], output_dir: str, stem: str) -> str:
    urls = task.get("model_urls") or {}
    glb_url = str(urls.get("glb") or "").strip()
    if not glb_url:
        raise Meshy3DError("Meshy returned no GLB")
    data = http.download(glb_url)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{stem}.glb")
    _write_atomic(path, data)
    return path


def _download_preview(task: dict[str, Any], output_dir: str, stem: str) -> None:
    """The gallery picture, saved beside the GLB because Meshy's thumbnail link dies in 3 days."""
    url = str(task.get("thumbnail_url") or "").strip()
    if not url:
        return
    try:
        data = http.download(url)
        if data[:4] == b"\x89PNG":
            _write_atomic(os.path.join(output_dir, f"{stem}.preview.png"), data)
    except Exception:
        pass  # a missing picture never costs the model


def _create(url: str, key: str, body: dict[str, Any], *, cancelled, fallback: str) -> str:
    return http.task_id(http.call("post", url, key, body=body, cancelled=cancelled, fallback=fallback))


def _image_task(key: str, image_path: str, opts: dict[str, Any], cancelled) -> tuple[dict[str, Any], dict[str, str], list[dict]]:
    body = options_module.image_body(local_image_data_uri(image_path), opts)
    task_id = _create(IMAGE_TO_3D, key, body, cancelled=cancelled, fallback="Meshy image-to-3D failed")
    task = http.poll_task(f"{IMAGE_TO_3D}/{task_id}", key, cancelled=cancelled)
    return task, {"image": task_id}, [http.task_facts(task)]


def _text_task(key: str, prompt: str, opts: dict[str, Any], cancelled) -> tuple[dict[str, Any], dict[str, str], list[dict]]:
    preview_id = _create(TEXT_TO_3D, key, options_module.text_preview_body(prompt, opts), cancelled=cancelled,
                         fallback="Meshy text-to-3D preview failed")
    preview = http.poll_task(f"{TEXT_TO_3D}/{preview_id}", key, cancelled=cancelled)
    refine_id = _create(TEXT_TO_3D, key, options_module.text_refine_body(preview_id, opts), cancelled=cancelled,
                        fallback="Meshy text-to-3D refine failed")
    task = http.poll_task(f"{TEXT_TO_3D}/{refine_id}", key, cancelled=cancelled)
    return task, {"preview": preview_id, "refine": refine_id}, [http.task_facts(preview), http.task_facts(task)]


def generate_model(
    *,
    api_key: str,
    output_dir: str,
    prompt: str = "",
    image_path: str | None = None,
    model: str = DEFAULT_MODEL,
    cancelled: Callable[[], bool] | None = None,
    filename_stem: str = "meshy",
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a GLB from a prompt or an image and save it (plus its picture) in ``output_dir``.

    ``options`` are the optional Meshy parameters (see ``meshy_options``). The result carries a
    ``meshy`` block (task ids, credits spent, expiry, model, options) for the asset manifest.
    """
    key = http.require_key(api_key)
    prompt = str(prompt or "").strip()[:MAX_PROMPT_CHARS]
    if not image_path and not prompt:
        raise Meshy3DError("A prompt or a reference image is required", 400)
    opts = options_module.normalize_options(options, model=model or DEFAULT_MODEL)
    if image_path:
        task, task_ids, facts = _image_task(key, image_path, opts, cancelled)
    else:
        task, task_ids, facts = _text_task(key, prompt, opts, cancelled)
    path = _download_glb(task, output_dir, filename_stem)
    _download_preview(task, output_dir, filename_stem)
    return {
        "path": path,
        "filename": os.path.basename(path),
        "provider": "meshy",
        "model": model or DEFAULT_MODEL,
        "meshy": {"task_ids": task_ids, "ai_model": opts["ai_model"], "options": opts, **http.combine_facts(*facts)},
    }
