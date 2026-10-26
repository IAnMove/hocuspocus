"""Place a flat rig's blink and mouth from See-through layers (``style.faceSource: "layers"``).

The usual rig still guesses two white eyes. This path runs the See-through worker once per pose, on the
same GPU lane as the other GPU workers, saves the source-aligned PNGs on the kit, builds the blink from
the eyewhite, irides and eyelash masks, and feeds the mouth layer to the warp, paper and ink mouths.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from services.flat_rig_base import SPRITE, FlatRigError, _anchor
from services.flat_rig_eyes import _blink_box, _eye_skin, blink_sprite
from services.runtime_environment import engine_python
from services.runtime_profiles import APP_DIR, managed_ready
from services.see_through.worker import REQUIRED

EYE_CLASSES = ("eyewhite", "irides", "eyelash")
MARKER = Path("app/services/see_through/env/.maestro_see_through_v1.installed")
VENDOR_SCRIPT = Path("app/services/see_through/vendor/see-through/inference/scripts/inference_psd_quantized.py")
ALPHA_MIN = 16


def installed() -> bool:
    """True when this machine has the component's interpreter, marker and vendor script."""
    root = APP_DIR.parent
    try:
        python = engine_python("see_through", root=root)
    except KeyError:
        return False
    ready = python.is_file() and (root / MARKER).is_file() and (root / VENDOR_SCRIPT).is_file()
    return ready and managed_ready("see_through")


def ensure_available() -> None:
    """Refuse before any pose is read. Linux only; a missing install leaves the kit alone."""
    if sys.platform != "linux":
        raise FlatRigError(
            "see_through_unsupported",
            "See-through layers need Linux with an NVIDIA GPU. The flat rig still places the eyes and the mouth without them.")
    if not installed():
        raise FlatRigError(
            "see_through_not_installed",
            "See-through is not installed. Install it from Settings > Installation. The flat rig still places the eyes and the mouth without it.")


def decompose_image(image: Image.Image, pose: str) -> dict:
    """Run the worker and return source-aligned ``{images, missing}``. Tests replace this."""
    from services.see_through.worker import publish_layers, run_pipeline
    with tempfile.TemporaryDirectory(prefix="see-through-") as folder:
        root = Path(folder)
        source = root / "pose.png"
        image.save(source, format="PNG")
        try:
            canvas = run_pipeline(source, root / "canvas")
        except (OSError, subprocess.CalledProcessError) as error:
            raise FlatRigError("see_through_failed", f"See-through did not finish pose {pose}: {error}") from error
        out = root / "layers"
        manifest = publish_layers(canvas, out, image.width, image.height, pose)
        return {"images": _load_layers(out, manifest), "missing": list(manifest["missing"])}


def _load_layers(folder: Path, manifest: dict) -> dict[str, Image.Image]:
    images = {}
    for name, filename in manifest["classes"].items():
        with Image.open(folder / filename) as layer:
            images[name] = layer.convert("RGBA")
    return images


def _pose_list(kit: dict, pose_ids) -> list[str]:
    assets = {"base": kit.get("base"), **(kit.get("poses") or {})}
    if not assets.get("base"):
        raise FlatRigError("missing_base", "Approve a base pose before rigging; the blink comes from it", 409)
    wanted = list(dict.fromkeys(["base", *pose_ids])) if pose_ids else [pose for pose, asset in assets.items() if asset]
    unknown = [pose for pose in wanted if not assets.get(pose)]
    if unknown:
        raise FlatRigError("unknown_pose", f"The character has no pose {unknown[0]}")
    return wanted


def prepare_face_layers(kit, look, workspace: str, workspace_dir: str, pose_ids, hints: dict) -> tuple[dict, dict]:
    """Decompose each pose when ``faceSource`` is ``layers``. Otherwise return the hints unchanged."""
    if look.get("faceSource") != "layers":
        return hints, {}
    ensure_available()
    poses = _pose_list(kit, pose_ids)
    from services import resource_scheduler
    lane = resource_scheduler.local_gpu_lane(0)
    task = f"see-through-{kit.get('id') or 'rig'}"
    with resource_scheduler.coordinator.acquire(lane, task_id=task, description="See-through layers"):
        return _decompose_all(kit, workspace, workspace_dir, poses, hints)


def _decompose_all(kit, workspace: str, workspace_dir: str, poses: list[str], hints: dict) -> tuple[dict, dict]:
    merged, pack = dict(hints), {}
    for pose in poses:
        merged[pose], pack[pose] = _one_pose(kit, workspace, workspace_dir, pose, merged.get(pose) or {})
    return merged, pack


def _open_pose(kit, workspace: str, workspace_dir: str, pose: str) -> Image.Image:
    from services.flat_rig import _workspace_file, pose_source
    return Image.open(_workspace_file(pose_source(kit, pose), workspace, workspace_dir)).convert("RGBA")


def _one_pose(kit, workspace: str, workspace_dir: str, pose: str, hint: dict) -> tuple[dict, dict]:
    with _open_pose(kit, workspace, workspace_dir, pose) as image:
        width, height = image.size
        layer = decompose_image(image, pose)
    images = dict(layer.get("images") or {})
    box = _mouth_box(images.get("mouth"))
    missing = _required_missing(images, layer.get("missing") or [])
    if box is None and "mouth" not in missing:
        missing = sorted({*missing, "mouth"})
    merged, derived = _merge_mouth(hint, box, width, height) if box else (hint, set())
    return merged, {"images": images, "missing": missing, "mouth_box": box, "derived": derived}


def _required_missing(images: dict, missing) -> list[str]:
    found = set(missing)
    found.update(name for name in REQUIRED if name not in images)
    return sorted(found)


def _alpha(image: Image.Image) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim == 2:
        return array > ALPHA_MIN
    channel = array[..., 3] if array.shape[-1] == 4 else array.max(axis=-1)
    return channel > ALPHA_MIN


def _bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _mouth_box(image: Image.Image | None):
    return None if image is None else _bbox(_alpha(image))


def _merge_mouth(hint: dict, box, width: int, height: int) -> tuple[dict, set[str]]:
    """Fill mouth keys the caller did not set, and name the keys this call filled.

    A point the user gave stays. The filled keys place this rig only. They are not an ``exact`` user hint:
    a later rig, a new pose and the anime landmarks may move the mouth.
    """
    merged = dict(hint)
    derived: set[str] = set()
    x0, y0, x1, y1 = box
    if "mouth" not in merged:
        merged["mouth"] = [round((x0 + x1) / 2 / width * 100, 3), round((y0 + y1) / 2 / height * 100, 3)]
        derived.add("mouth")
    if "mouthWidth" not in merged:
        merged["mouthWidth"] = round(min(100.0, max(0.5, (x1 - x0) / width * 100)), 3)
        derived.add("mouthWidth")
    return merged, derived


def drop_derived_hints(placed: dict, pack: dict) -> dict:
    """The hints to save: a mouth See-through filled is left out. A hint the caller sent stays."""
    cleaned = {}
    for pose, hint in placed.items():
        if not isinstance(hint, dict):
            continue
        drop = set((pack.get(pose) or {}).get("derived") or ())
        kept = {key: value for key, value in hint.items() if key not in drop}
        if kept:
            cleaned[pose] = kept
    return cleaned


def apply_face_layers(rigs: dict, pack: dict, look: dict, hints: dict) -> None:
    """Replace the guessed blink, and the paper or ink mouth anchor, from the saved masks."""
    for pose, layer in pack.items():
        if pose in rigs:
            _apply_one(rigs[pose], layer, look, hints.get(pose) or {})


def _warn(rig: dict, code: str) -> None:
    if code not in rig["warnings"]:
        rig["warnings"].append(code)


def _apply_one(rig: dict, layer: dict, look: dict, hint: dict) -> None:
    for name in layer.get("missing") or []:
        _warn(rig, f"layer_missing_{name.replace(' ', '_')}")
    labelled = _eye_labels(layer.get("images") or {}, rig)
    if labelled is not None:
        _place_blink(rig, labelled, look, hint.get("blink") is not False)
    if look.get("mouthStyle") != "warp" and layer.get("mouth_box"):
        _set_mouth(rig, layer["mouth_box"])


def _eye_labels(images: dict, rig: dict):
    mask = _union_eyes(images, rig)
    if mask is None or not mask.any():
        return None
    return _label_pair(mask)


def _union_eyes(images: dict, rig: dict):
    mask = np.zeros((rig["height"], rig["width"]), bool)
    found = False
    for name in EYE_CLASSES:
        part = _figure_alpha(images.get(name), rig)
        if part is None:
            continue
        mask |= part
        found = True
    return mask if found else None


def _figure_alpha(image: Image.Image | None, rig: dict):
    if image is None:
        return None
    mask = _alpha(image)
    frame = rig["frame"]
    if mask.shape[0] != int(frame[3]) or mask.shape[1] != int(frame[2]):
        return None
    x0, y0 = int(frame[0]), int(frame[1])
    return mask[y0:y0 + rig["height"], x0:x0 + rig["width"]]


def _label_pair(mask: np.ndarray) -> np.ndarray:
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    parts = _largest(stats, centroids, count)
    if len(parts) == 1:
        return _split_one(labels, parts[0][1])
    return _paint_two(labels, parts)


def _largest(stats, centroids, count: int) -> list:
    found = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area > 0:
            found.append((area, label, float(centroids[label][0])))
    found.sort(reverse=True)
    return found[:2]


def _paint_two(labels: np.ndarray, parts: list) -> np.ndarray:
    out = np.zeros(labels.shape, np.uint8)
    for value, (_area, label, _x) in enumerate(sorted(parts, key=lambda item: item[2]), start=1):
        out[labels == label] = value
    return out


def _split_one(labels: np.ndarray, label: int) -> np.ndarray:
    region = labels == label
    xs = np.nonzero(region)[1]
    cut = float(np.median(xs)) if len(xs) else 0.0
    columns = np.arange(labels.shape[1])[None, :]
    out = np.zeros(labels.shape, np.uint8)
    out[region & (columns <= cut)] = 1
    out[region & (columns > cut)] = 2
    return out


def _place_blink(rig: dict, labelled: np.ndarray, look: dict, blink_ok: bool) -> None:
    ys, xs = np.nonzero(labelled)
    ox0, oy0, ox1, oy1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    height, width = labelled.shape
    pad = int((oy1 - oy0) * 0.25)
    bx0, by0, bx1, by1 = _blink_box(
        max(0, ox0 - pad), max(0, oy0 - pad), min(width, ox1 + pad), min(height, oy1 + pad), height)
    pixels = np.asarray(rig["before"].convert("RGBA"))
    rgb, alpha = pixels[..., :3], pixels[..., 3]
    skin = np.asarray(rig["skin"], dtype=float)
    lids = skin if look.get("screen") else _eye_skin(rgb, alpha, (ox0, oy0, ox1, oy1), skin)
    rig["blink"] = blink_sprite(
        rgb[by0:by1, bx0:bx1], labelled[by0:by1, bx0:bx1], lids, look.get("screen") is True, alpha[by0:by1, bx0:bx1])
    rig["eyes"] = _anchor((bx0 + bx1) / 2, (by0 + by1) / 2, by1 - by0, rig["width"], rig["height"])
    rig["eyes_box"] = [ox0, oy0, ox1, oy1]
    if blink_ok:
        rig["blinks"] = True


def _set_mouth(rig: dict, box) -> None:
    x0, y0, x1, y1 = box
    left, top = int(rig["frame"][0]), int(rig["frame"][1])
    sprite = max(1.0, float(x1 - x0))
    rig["mouth"] = _anchor((x0 + x1) / 2 - left, (y0 + y1) / 2 - top, sprite * SPRITE[1] / SPRITE[0], rig["width"], rig["height"])
    rig["mouth_box"] = [x0 - left, y0 - top, x1 - left, y1 - top]


def save_layers(pack: dict, kit_id: str, workspace_dir: str, workspace: str) -> tuple[dict, dict]:
    """Content-hashed PNGs under the workspace. Empty when this rig did not use layers."""
    from services.flat_rig import _save, _url
    urls, missing = {}, {}
    for pose, layer in pack.items():
        pose_urls = {}
        for name, image in (layer.get("images") or {}).items():
            filename = _save(image, workspace_dir, f"kit-{kit_id}-{pose}-layer-{_slug(name)}")
            pose_urls[name] = _url(filename, workspace)
        if pose_urls:
            urls[pose] = pose_urls
        missing[pose] = list(layer.get("missing") or [])
    return urls, missing


def _slug(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in name).strip("-")
    return cleaned or "layer"
