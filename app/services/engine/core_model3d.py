"""Core server's Model3D engine.

Meshy and Hi3D stay in ``core_remote_3d``. This module only matches the
signature the shared Model3D router uses for the local Hunyuan service.
"""
from __future__ import annotations

from typing import Any


def _engine():
    from services import core_remote_3d
    return core_remote_3d


def capabilities() -> dict[str, Any]:
    return _engine().capabilities()


def start_job(
    *,
    body: dict[str, Any],
    image_paths: dict[str, str],
    output_dir: str,
    source_mesh_path: str | None = None,
    workspace: str = "default",
) -> dict[str, Any]:
    merged = dict(body)
    if source_mesh_path:
        merged["source_model"] = source_mesh_path
    # The router already resolved each reference to one real file. It travels as an argument, not inside
    # the request body, so the engine uses it as is and a client cannot supply it.
    return _engine().start_job(
        merged, workspace=str(workspace or "default"), output_dir=output_dir,
        resolved_images={view: path for view, path in image_paths.items() if path},
    )


def get_job(job_id: str) -> dict[str, Any] | None:
    return _engine().get_job(job_id)


def cancel_job(job_id: str) -> dict[str, Any] | None:
    return _engine().cancel_job(job_id)


def cancel_all_jobs() -> int:
    return _engine().cancel_all_jobs()
