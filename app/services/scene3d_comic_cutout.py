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
_DILATE = 3
_HALO = 2.0
_AA = 1.5
_SPECK = 0.005
_INPAINT_RADIUS = 3
# Unsure U2Net pixels per sure one. Busy scenes (small figures, furniture) come out around 2.7
# and smear or leave a head behind; clean subjects stay near 0.1-1.0.
_UNSURE_LIMIT = 1.5


def finish_cutout(picture: Path, cutout: Path) -> None:
    """Turn a soft matte into a paper sticker and fill the picture behind it.

    The matte is binarized at one half, holes are filled and specks below half a percent of the
    panel are dropped. A 3 px dilation carries a halo of the original background, then 2 px more
    so the fill under that halo is covered, and the edge falls off over 1.5 px. The cutout's
    colour is the picture. Telea runs under that whole sticker. The outer 3 percent of the panel
    keeps the original picture, so a subject that touches the frame can ghost only inside that
    band. The cutout is saved first: a failed fill leaves the picture untouched.
    """
    import numpy as np
    from PIL import Image

    with Image.open(picture) as opened:
        original = np.asarray(opened.convert("RGBA")).copy()
    with Image.open(cutout) as opened:
        mask = np.asarray(opened.convert("RGBA"))
    if mask.shape != original.shape:
        return
    _require_sure_matte(mask[..., 3])
    sticker, support = _sticker(mask[..., 3])
    edge = _edge_ramp(sticker.shape[0], sticker.shape[1])
    painted = original.copy()
    painted[..., 3] = np.rint(np.clip(sticker * edge, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(painted).save(cutout)
    _inpaint_base(picture, original, support, edge)


def _require_sure_matte(alpha) -> None:
    """Raise before anything is written when the matte is mostly guesswork, so the panel stays flat."""
    sure = int((alpha >= 230).sum())
    unsure = int(((alpha > 25) & (alpha < 230)).sum())
    if unsure > _UNSURE_LIMIT * max(sure, 1):
        raise ValueError("uncertain matte")


def _sticker(alpha):
    """Float coverage of the sticker, and the pixels Telea must replace (before the edge ramp)."""
    import cv2
    import numpy as np

    core = _components(_fill_holes(np.where(alpha >= 128, np.uint8(255), np.uint8(0))))
    if int(core.max()) == 0:
        return np.zeros(alpha.shape, np.float32), np.zeros(alpha.shape, np.bool_)
    dilated = cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (_DILATE * 2 + 1, _DILATE * 2 + 1)))
    outside = np.where(dilated > 0, np.uint8(0), np.uint8(255))
    dist = cv2.distanceTransform(outside, cv2.DIST_L2, 5)
    cover = np.clip((_HALO + _AA - dist) / _AA, 0, 1).astype(np.float32)
    kept = np.rint(np.clip(cover, 0, 1) * 255).astype(np.uint8) > 0
    return cover, kept


def _fill_holes(mask):
    import cv2
    import numpy as np

    height, width = mask.shape
    padded = np.pad(np.where(mask > 0, np.uint8(0), np.uint8(255)), 1, constant_values=255)
    cv2.floodFill(padded, np.zeros((height + 4, width + 4), np.uint8), (0, 0), 0, flags=8)
    holes = padded[1:-1, 1:-1] > 0
    filled = mask.copy()
    filled[holes] = 255
    return filled


def _components(mask):
    import cv2
    import numpy as np

    count, labels, stats, _centroids = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), connectivity=8)
    if count <= 1:
        return mask
    limit = max(1, int(round(mask.size * _SPECK)))
    kept = np.zeros(mask.shape, np.uint8)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= limit:
            kept[labels == label] = 255
    return kept


def _edge_ramp(height: int, width: int):
    import numpy as np

    band_x = max(1.0, _FEATHER * width)
    band_y = max(1.0, _FEATHER * height)
    xs = np.arange(width, dtype=np.float32)
    ys = np.arange(height, dtype=np.float32)
    ramp_x = np.clip(np.minimum(xs, (width - 1) - xs) / band_x, 0, 1)
    ramp_y = np.clip(np.minimum(ys, (height - 1) - ys) / band_y, 0, 1)
    return np.minimum(ramp_x[None, :], ramp_y[:, None])


def _inpaint_base(picture: Path, original, support, edge) -> None:
    import cv2
    import numpy as np
    from PIL import Image

    mask = np.where(support, np.uint8(255), np.uint8(0))
    if int(mask.max()) == 0:
        return
    bgr = cv2.cvtColor(original[..., :3], cv2.COLOR_RGB2BGR)
    filled = cv2.cvtColor(cv2.inpaint(bgr, mask, _INPAINT_RADIUS, cv2.INPAINT_TELEA), cv2.COLOR_BGR2RGB)
    out = original.copy()
    paint = mask > 0
    out[paint, :3] = filled[paint]
    keep = edge < 1
    out[keep] = original[keep]
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
