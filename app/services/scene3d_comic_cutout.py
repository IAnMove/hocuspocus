"""Subject cutouts for a comic transition, through the existing background-removal operation.

A missing model, an empty matte or any worker error leaves that panel as one layer and
returns a warning. Tests replace ``produce``; the live path calls ``image.remove_background``.
"""
from __future__ import annotations

from pathlib import Path

_PRODUCE = None


def bind_comic_cutout(produce) -> None:
    """``produce(source, dest) -> Path | None``. ``None`` restores the live remover."""
    global _PRODUCE
    _PRODUCE = produce


def cutout_panel(source: Path, dest: Path, workspace: str, workspace_dir) -> tuple[Path | None, str | None]:
    """Write a cutout PNG. ``(None, warning)`` when the panel must stay single-layer."""
    try:
        made = _PRODUCE(source, dest) if _PRODUCE is not None else _live(source, dest, workspace, workspace_dir)
    except Exception as exc:
        return None, _warning(source, exc)
    if made is None or not Path(made).is_file() or _empty(Path(made)):
        return None, _warning(source, "empty")
    return Path(made), None


def _warning(source: Path, reason) -> str:
    return f"{source.name}: cutout unavailable ({reason})"


def cutout_is_empty(path: Path) -> bool:
    return _empty(path)


def _empty(path: Path) -> bool:
    from PIL import Image
    import numpy as np

    with Image.open(path) as opened:
        alpha = np.asarray(opened.convert("RGBA"))[..., 3]
    visible = int((alpha > 32).sum())
    return visible < max(32, alpha.size // 500)


def _live(source: Path, dest: Path, workspace: str, workspace_dir) -> Path:
    from services.image_remove_background import remove_image

    root = Path(workspace_dir(workspace))
    uploads = root / "_comic_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    result = remove_image(
        {"workspace": workspace, "source": source.name, "method": "auto", "crop": False},
        workspace_dir, lambda: str(uploads), start_job=_inline_u2net,
    )
    made = root / str(result["file"])
    if made.resolve() != dest.resolve():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(made.read_bytes())
        return dest
    return made


def _inline_u2net(job: dict) -> None:
    """Run the shared U2Net worker on this thread. Screen colours never reach here."""
    from shared.tools.background_removal import remove_background_file

    params = job.get("params") or {}
    try:
        result = remove_background_file(
            params["_source_path"],
            uploads_root=params["_uploads_root"],
            workspace_root=params["_workspace_root"],
            output_dir=params["_destination_workspace_root"],
        )
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
        return
    job["status"] = "completed"
    job["output_files"] = [result["filename"]]
