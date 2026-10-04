"""Run the headless Series shot compiler (``ui/scripts/series-shot.ts``) through the tsx bridge.

Same mechanism as the Video 2D compile tools: Python plans, the editor's own
TypeScript mounts Character Kits and compiles mouths, nothing is saved here.
Pose sizes are read from the workspace files when a kit does not store them,
because mounting needs them to fit a pose in the frame.
"""
from __future__ import annotations

import copy
import json
import subprocess
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from services import resource_scheduler
from services.video2d_compile import TSX, UI_ROOT

SCRIPT = UI_ROOT / "scripts" / "series-shot.ts"
TIMEOUT = 90


class SeriesShotError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _workspace_path(source: str, workspace_dir: str) -> Path | None:
    parsed = urlparse(str(source or ""))
    if not parsed.path.startswith("/api/v1/file/"):
        return None
    root = Path(workspace_dir).resolve()
    path = (root / unquote(parsed.path[len("/api/v1/file/"):])).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


def with_pose_sizes(kit: dict[str, Any], workspace_dir: str) -> dict[str, Any]:
    """A copy of the kit whose base and poses carry width and height."""
    from PIL import Image

    kit = copy.deepcopy(kit)
    for asset in [kit.get("base"), *(kit.get("poses") or {}).values()]:
        if not isinstance(asset, dict) or (asset.get("width") and asset.get("height")):
            continue
        path = _workspace_path(asset.get("source", ""), workspace_dir)
        if path is None:
            continue
        with Image.open(path) as image:
            asset["width"], asset["height"] = image.size
    return kit


def run_series_shot(payload: dict[str, Any]) -> dict[str, Any]:
    """One compile on the video2d-compile CPU lane; returns the scene document."""
    with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("video2d-compile"),
                                                task_id=f"series-shot-{uuid.uuid4().hex}", description="Series shot compile"):
        try:
            completed = subprocess.run(
                ["node", str(TSX), "--tsconfig", "tsconfig.app.json", str(SCRIPT)],
                input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, encoding="utf-8",
                timeout=TIMEOUT, cwd=UI_ROOT, check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise SeriesShotError("compile_timeout", "The shot compile timed out") from error
        except OSError as error:
            raise SeriesShotError("compile_unavailable", "Node.js could not start the shot compiler") from error
    if completed.returncode != 0:
        raise SeriesShotError("compile_failed", (completed.stderr or completed.stdout or "compile failed").strip()[-400:])
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise SeriesShotError("compile_failed", "The shot compiler returned invalid JSON") from error
    if not result.get("ok"):
        raise SeriesShotError(str(result.get("code") or "compile_failed"), str(result.get("message") or "compile failed"))
    return result["document"]


def workspace_of(source: str, fallback: str) -> str:
    return (parse_qs(urlparse(str(source or "")).query).get("workspace") or [fallback])[0]
