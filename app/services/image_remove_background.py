"""One idempotent image cutout operation over the existing screen and U2Net workers."""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import numpy as np
from fastapi import HTTPException
from PIL import Image
from starlette.concurrency import run_in_threadpool

from services.game_image_ops import clean_alpha, crop_figure
from services.mcp_intent import IntentConflict, check_intent_id, intent_digest, load_intent, store_intent
from services.scene_documents import WORKSPACE_RE
from services.set_molds import defaults
from services.studio_key import key_request, find_isnet_model, StudioKeyError
from services.media_paths import resolve_permitted_media_path
from shared.tools.background_removal_job import build_background_removal_job

OPERATION = "image.remove_background"
_LOCK = threading.RLock()
SCREENS = {"green": (0, 255, 0), "blue": (0, 0, 255), "magenta": (255, 0, 255)}


def command_catalog():
    return [{"name": OPERATION, "version": 1, "domain": "image", "mutation": True, "destructive": False,
             "description": "Remove an image background with auto, screen or U2Net, optionally cropping the result. Returns a PNG, the chosen method, bounding box and alpha/haze report; reuse intent_id on retries.",
             "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "intent_id", "input"],
                 "properties": {"version": {"const": 1}, "intent_id": {"type": "string"}, "input": {"type": "object", "additionalProperties": False,
                     "required": ["workspace", "source"], "properties": {"workspace": {"type": "string"}, "source": {"type": "string"},
                         "method": {"enum": ["auto", "u2net", "screen"]}, "screen": {"enum": list(SCREENS)}, "crop": {"type": "boolean"}}}}}}]


def detect_screen(image: Image.Image) -> tuple[str | None, float]:
    rgb = np.asarray(image.convert("RGB"), dtype=float)
    edge = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]))
    config = defaults()["removeBackground"]
    shares = {name: float(np.mean(np.linalg.norm(edge-color, axis=1) <= config["colorDistance"])) for name, color in SCREENS.items()}
    name = max(shares, key=shares.get)
    return (name if shares[name] >= config["borderShare"] else None), shares[name]


def alpha_report(image: Image.Image) -> dict:
    alpha = np.asarray(image.convert("RGBA"))[..., 3]
    visible = max(1, int(np.count_nonzero(alpha)))
    semi = float(np.count_nonzero((alpha > 0) & (alpha < 255)) / visible)
    haze = float(np.count_nonzero((alpha > 0) & (alpha < 128)) / visible)
    return {"semiTransparentShare": semi, "haze": haze, "hazeExceeded": haze > defaults()["removeBackground"]["hazeMax"]}


def crop_result(image: Image.Image, crop: bool) -> tuple[Image.Image, list[int]]:
    rgba = clean_alpha(np.asarray(image.convert("RGBA")))
    ys, xs = np.nonzero(rgba[..., 3] > 128)
    if not len(xs):
        raise ValueError("no visible figure")
    if not crop:
        return image, [0, 0, image.width, image.height]
    margin = defaults()["removeBackground"]["cropMargin"]
    pad = int(max(image.size) * margin)
    bbox = [max(0, int(xs.min())-pad), max(0, int(ys.min())-pad), min(image.width, int(xs.max())+pad+1), min(image.height, int(ys.max())+pad+1)]
    return Image.fromarray(crop_figure(rgba, margin=margin)), bbox


def _u2net(source, workspace, root, uploads, start_job, register_job):
    if start_job is None:
        raise HTTPException(503, "Background removal worker unavailable")
    job = build_background_removal_job(job_id=f"prop-key-{uuid.uuid4().hex[:16]}", workspace=workspace, output_dir=str(root),
        source_path=source, source_filename=Path(source).name, source_workspace=workspace, source_asset_id="",
        uploads_root=uploads, source_root=str(root), provenance={}, instruction="Remove the image background")
    if register_job:
        job = register_job(job)
    start_job(job)
    deadline = time.monotonic() + 1800
    while job.get("status") not in {"completed", "failed", "cancelled", "error"}:
        if time.monotonic() > deadline:
            raise HTTPException(504, "Background removal still running")
        time.sleep(0.1)
    if job.get("status") != "completed" or not job.get("output_files"):
        raise HTTPException(422, str(job.get("error") or "Background removal failed"))
    return root / Path(job["output_files"][0]).name


def remove_image(data, workspace_dir, uploads_dir, start_job=None, register_job=None):
    workspace = data.get("workspace")
    if not isinstance(workspace, str) or not WORKSPACE_RE.fullmatch(workspace):
        raise ValueError("valid workspace required")
    method = data.get("method", "auto")
    if method not in {"auto", "screen", "u2net"} or ("crop" in data and not isinstance(data["crop"], bool)):
        raise ValueError("invalid method or crop")
    root = Path(workspace_dir(workspace)); root.mkdir(parents=True, exist_ok=True)
    uploads = str(uploads_dir() if callable(uploads_dir) else uploads_dir)
    source = resolve_permitted_media_path(data["source"], uploads_root=uploads, workspace_root=str(root), kinds=("image",), workspace_name=workspace)
    with Image.open(source) as opened:
        screen, confidence = detect_screen(opened)
    if method == "auto":
        method = "screen" if screen else "u2net"
    if method == "screen":
        screen = data.get("screen") or screen
        if screen not in SCREENS:
            raise ValueError("screen is required when the border is not a screen colour")
        keyed = key_request({"version": 1, "input": {"workspace": workspace, "source": source, "mode": screen}},
                            workspace_dir=workspace_dir, uploads_dir=uploads, find_model=find_isnet_model)
        output = root / keyed["file"]
    else:
        output = _u2net(source, workspace, root, uploads, start_job, register_job)
    with Image.open(output) as opened:
        image, bbox = crop_result(opened.convert("RGBA"), data.get("crop", False))
        report = alpha_report(image)
        image.save(output, format="PNG")
    return {"file": output.name, "url": f"/api/v1/file/{output.name}?workspace={workspace}", "bbox": bbox,
            "method": method, "screen": screen if method == "screen" else None, "decision": {"requested": data.get("method", "auto"), "borderShare": confidence}, "report": report}


def execute(arguments, workspace_dir, uploads_dir, start_job=None, register_job=None):
    try:
        if arguments.get("version") != 1 or not isinstance(arguments.get("input"), dict):
            raise ValueError("version 1 and input required")
        data = arguments["input"]
        intent = check_intent_id(arguments.get("intent_id")); digest = intent_digest(data)
        if not WORKSPACE_RE.fullmatch(str(data.get("workspace", ""))):
            raise ValueError("valid workspace required")
        root = Path(workspace_dir(data["workspace"]))
        with _LOCK:
            result = load_intent(root, OPERATION, intent, digest)
            replayed = result is not None
            if result is None:
                result = remove_image(data, workspace_dir, uploads_dir, start_job, register_job)
                store_intent(root, OPERATION, intent, digest, result)
        return {"version": 1, "operation": OPERATION, "status": "completed", "result": result, "replayed": replayed}
    except IntentConflict as error:
        raise HTTPException(409, {"code": "intent_conflict", "message": str(error)}) from error
    except (ValueError, KeyError, FileNotFoundError, StudioKeyError) as error:
        raise HTTPException(422, {"code": "invalid_image", "message": str(error)}) from error


def command_handlers(workspace_dir, uploads_dir, start_job=None, register_job=None):
    async def run(arguments):
        return await run_in_threadpool(execute, arguments, workspace_dir, uploads_dir, start_job, register_job)
    return {OPERATION: run}
