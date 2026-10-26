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


_FEATHER = 0.03
_ERODE = 3
_INPAINT_RADIUS = 3


def finish_cutout(picture: Path, cutout: Path) -> None:
    """Feather the matte at the panel edge, then fill the picture behind the opaque subject.

    The picture keeps every pixel whose final alpha is below 255. Inpaint runs only where that
    alpha is 255, after eroding the mask by a few pixels. The cutout is saved first, so a failed
    fill leaves the picture untouched and the caller can drop the layer.
    """
    import numpy as np
    from PIL import Image

    with Image.open(picture) as opened:
        original = np.asarray(opened.convert("RGBA")).copy()
    with Image.open(cutout) as opened:
        mask = np.asarray(opened.convert("RGBA"))
    if mask.shape != original.shape:
        return
    alpha = _feather_alpha(mask[..., 3])
    painted = original.copy()
    painted[..., 3] = alpha
    Image.fromarray(painted).save(cutout)
    _inpaint_base(picture, original, alpha)


def _feather_alpha(alpha):
    import numpy as np

    height, width = alpha.shape
    band_x = max(1.0, _FEATHER * width)
    band_y = max(1.0, _FEATHER * height)
    xs = np.arange(width, dtype=np.float32)
    ys = np.arange(height, dtype=np.float32)
    ramp_x = np.clip(np.minimum(xs, (width - 1) - xs) / band_x, 0, 1)
    ramp_y = np.clip(np.minimum(ys, (height - 1) - ys) / band_y, 0, 1)
    ramp = np.minimum(ramp_x[None, :], ramp_y[:, None])
    return np.rint(alpha.astype(np.float32) * ramp).astype(np.uint8)


def _inpaint_base(picture: Path, original, alpha) -> None:
    import cv2
    import numpy as np
    from PIL import Image

    opaque = np.where(alpha == 255, np.uint8(255), np.uint8(0))
    kernel = np.ones((_ERODE * 2 + 1, _ERODE * 2 + 1), np.uint8)
    mask = cv2.erode(opaque, kernel)
    if int(mask.max()) == 0:
        return
    bgr = cv2.cvtColor(original[..., :3], cv2.COLOR_RGB2BGR)
    filled = cv2.cvtColor(cv2.inpaint(bgr, mask, _INPAINT_RADIUS, cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)
    out = original.copy()
    paint = mask > 0
    out[paint, :3] = filled[paint]
    Image.fromarray(out).save(picture)


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
