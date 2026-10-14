"""Recast reference mattes: cutout, edge cleanup, and the one U2Net session.

Function bodies are the launch module's, except the two session helpers,
which now store the session on the single state holder below.
"""

import os
import threading

from services.recast_launch_binding import bindable

# --- moved verbatim ---
_RECAST_U2NET_CACHE_LIMIT = 8


class RecastU2NetState:
    """The one U2Net session, its locks, and the matte cache."""

    def __init__(self) -> None:
        self.session = None
        self.session_lock = threading.Lock()
        self.run_lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self.cache = {}


_recast_u2net = RecastU2NetState()

def _matte_recast_reference_frame(reference_frame, semantic_mask, neutral_value=127):
    """Remove pixels that an additional SCAIL reference must not describe.

    SCAIL-2 encodes reference RGB and its semantic mask separately. A black
    semantic region therefore does not stop identity detail in the original
    RGB image from reaching the reference latent. Replace hidden pixels with
    model-neutral gray so a bystander reference cannot reintroduce the old
    target or condition the surrounding scene.
    """
    import numpy as np

    frame = np.asarray(reference_frame, dtype=np.uint8)
    mask = np.asarray(semantic_mask, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[-1] != 3:
        raise ValueError(
            f"Recast reference frame must have H/W/RGB dimensions; got {frame.shape}."
        )
    if mask.shape != frame.shape:
        raise ValueError(
            "Recast reference frame and semantic mask must have matching "
            f"H/W/RGB dimensions; got frame={frame.shape}, mask={mask.shape}."
        )
    try:
        neutral = int(neutral_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Recast reference neutral value must be an integer.") from exc
    if not 0 <= neutral <= 255:
        raise ValueError("Recast reference neutral value must be between 0 and 255.")

    visible = np.any(mask > 30, axis=-1)
    matted = np.full_like(frame, neutral, dtype=np.uint8)
    matted[visible] = frame[visible]
    return matted

def _clean_recast_reference_region(region):
    """Keep the dominant connected subject and discard detached people."""
    import cv2
    import numpy as np

    binary = np.ascontiguousarray(
        np.asarray(region).astype(np.uint8, copy=False),
    )
    if binary.ndim != 2 or not bool(binary.any()):
        return binary.astype(bool), 0
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary,
        connectivity=8,
    )
    foreground_count = max(0, int(component_count) - 1)
    if foreground_count <= 1:
        return binary.astype(bool), foreground_count
    areas = stats[1:, cv2.CC_STAT_AREA]
    selected_label = 1 + int(np.argmax(areas))
    return labels == selected_label, foreground_count

def _select_recast_reference_instance(colored_mask, palette):
    """Select one prominent central SAM3 instance from a reference image."""
    import numpy as np

    mask = np.asarray(colored_mask)
    if mask.ndim == 2:
        cleaned, component_count = _clean_recast_reference_region(mask)
        return cleaned, {
            "instance_count": component_count,
            "selected_index": 0,
        }
    if mask.ndim != 3 or mask.shape[-1] != 3:
        raise ValueError(
            "SAM3 returned an unsupported reference mask shape: "
            f"{mask.shape}."
        )

    height, width = mask.shape[:2]
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    max_distance = max(1.0, (center_x ** 2 + center_y ** 2) ** 0.5)
    candidates = []
    for palette_index, color in enumerate(palette):
        color_array = np.asarray(color, dtype=np.uint8)
        region = np.all(mask == color_array, axis=-1)
        if not bool(region.any()):
            continue
        cleaned, component_count = _clean_recast_reference_region(region)
        ys, xs = np.nonzero(cleaned)
        if len(xs) == 0:
            continue
        area = int(len(xs))
        distance = (
            (float(xs.mean()) - center_x) ** 2
            + (float(ys.mean()) - center_y) ** 2
        ) ** 0.5
        centrality = max(0.0, 1.0 - distance / max_distance)
        # Area remains the dominant signal. Centrality breaks close calls in
        # favor of the foreground subject users normally place near the middle.
        score = float(area) * (1.0 + 0.25 * centrality)
        candidates.append({
            "region": cleaned,
            "score": score,
            "area": area,
            "palette_index": palette_index,
            "component_count": component_count,
        })

    if not candidates:
        fallback, component_count = _clean_recast_reference_region(
            np.any(mask > 30, axis=-1),
        )
        return fallback, {
            "instance_count": component_count,
            "selected_index": 0,
        }
    selected = max(candidates, key=lambda item: item["score"])
    return selected["region"], {
        "instance_count": len(candidates),
        "selected_index": selected["palette_index"],
        "discarded_components": max(0, selected["component_count"] - 1),
    }

def _recast_reference_subject_mask(reference_frame, alpha_channel=None):
    """Find the single person represented by a standalone reference view."""
    import numpy as np
    from shared import magic_mask

    if alpha_channel is not None:
        alpha = np.asarray(alpha_channel, dtype=np.uint8)
        transparent_fraction = (
            float(np.count_nonzero(alpha < 250)) / float(alpha.size)
            if alpha.size else 0.0
        )
        if transparent_fraction >= 0.02 and int(alpha.max()) > 5:
            selected, component_count = _clean_recast_reference_region(
                alpha > 5,
            )
            opacity = alpha.astype(np.float32) / 255.0
            opacity[~selected] = 0.0
            return (
                selected,
                opacity,
                "png alpha"
                + (
                    f" (dominant of {component_count} regions)"
                    if component_count > 1 else ""
                ),
            )

    frame = np.asarray(reference_frame, dtype=np.uint8)
    instance_palette = [
        (0, 0, 255),
        (255, 0, 0),
        (0, 255, 0),
        (255, 0, 255),
        (0, 255, 255),
    ]
    for keyword in ("person", "human character", "woman", "man"):
        mask = magic_mask.generate_keyword_masks(
            frame[None],
            keyword,
            no_hole=True,
            colorize_objects=True,
            color_palette=instance_palette,
            max_colored_objects=len(instance_palette),
        )[0]
        region, selection = _select_recast_reference_instance(
            mask,
            instance_palette,
        )
        if bool(region.any()):
            instance_count = int(selection.get("instance_count") or 1)
            selected_number = int(selection.get("selected_index") or 0) + 1
            source = (
                f"{keyword} instance {selected_number}/{instance_count}"
                if instance_count > 1
                else f"{keyword} instance"
            )
            discarded = int(selection.get("discarded_components") or 0)
            if discarded:
                source += f" (removed {discarded} detached region(s))"
            return region, region.astype(np.float32), source
    raise ValueError(
        "SAM3 could not find one person in the replacement reference. "
        "Try a clearer full- or half-body image."
    )

def _decontaminate_recast_reference_edges(reference_frame, subject, width=3):
    """Replace bright boundary contamination with nearby foreground color."""
    import cv2
    import numpy as np

    frame = np.asarray(reference_frame, dtype=np.uint8)
    region = np.asarray(subject).astype(bool)
    if frame.ndim != 3 or frame.shape[-1] != 3:
        raise ValueError(
            "Recast edge cleanup needs an H/W/RGB reference image."
        )
    if region.shape != frame.shape[:2]:
        raise ValueError(
            "Recast edge cleanup mask does not match its reference image."
        )
    cleaned = frame.copy()
    current = region.copy()
    kernel = np.ones((3, 3), dtype=np.uint8)
    for _ in range(max(1, int(width))):
        inner = cv2.erode(
            current.astype(np.uint8),
            kernel,
            iterations=1,
        ).astype(bool)
        boundary = current & ~inner
        if not bool(boundary.any()) or not bool(inner.any()):
            break
        neighbor_count = cv2.filter2D(
            inner.astype(np.float32),
            cv2.CV_32F,
            kernel.astype(np.float32),
            borderType=cv2.BORDER_REPLICATE,
        )
        replace = boundary & (neighbor_count > 0.0)
        for channel in range(3):
            neighbor_sum = cv2.filter2D(
                cleaned[..., channel].astype(np.float32)
                * inner.astype(np.float32),
                cv2.CV_32F,
                kernel.astype(np.float32),
                borderType=cv2.BORDER_REPLICATE,
            )
            values = neighbor_sum / np.maximum(neighbor_count, 1.0)
            cleaned[..., channel][replace] = np.rint(
                values[replace],
            ).clip(0, 255).astype(np.uint8)
        current = inner
    return cleaned

def _constrain_recast_u2net_matte(subject, opacity, u2net_alpha):
    """Keep a soft U2Net edge inside the person instance selected by SAM3."""
    import cv2
    import numpy as np

    region = np.asarray(subject).astype(bool)
    original_opacity = np.clip(
        np.asarray(opacity, dtype=np.float32),
        0.0,
        1.0,
    )
    matte = np.asarray(u2net_alpha, dtype=np.float32)
    if matte.size and float(matte.max()) > 1.0:
        matte = matte / 255.0
    matte = np.clip(matte, 0.0, 1.0)
    if (
        region.shape != original_opacity.shape
        or region.shape != matte.shape
    ):
        raise ValueError(
            "U2Net matte dimensions do not match the selected SAM3 person."
        )
    if not bool(region.any()):
        raise ValueError("The selected SAM3 person mask is empty.")

    # SAM3 owns identity selection. U2Net is allowed only a small perimeter
    # around that instance so another person in the reference cannot leak
    # back into the conditioning image.
    edge_width = max(
        1,
        min(4, int(round(min(region.shape[:2]) * 0.004))),
    )
    kernel_size = edge_width * 2 + 1
    kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
    guard = cv2.dilate(
        region.astype(np.uint8),
        kernel,
        iterations=1,
    ).astype(bool)
    guard_soft = cv2.GaussianBlur(
        guard.astype(np.float32),
        (0, 0),
        sigmaX=max(0.75, edge_width * 0.55),
        sigmaY=max(0.75, edge_width * 0.55),
    )
    guard_soft[~guard] = 0.0

    # Retain a feathered SAM3 silhouette even if U2Net misses a hand, hair
    # curl, or dark clothing. U2Net still supplies the cleaner outer alpha.
    inside_distance = cv2.distanceTransform(
        region.astype(np.uint8),
        cv2.DIST_L2,
        3,
    )
    sam_feather = np.clip(
        inside_distance / float(edge_width + 0.5),
        0.0,
        1.0,
    )
    sam_feather *= original_opacity
    refined = np.maximum(matte * guard_soft, sam_feather)
    refined[~guard] = 0.0
    return np.clip(refined, 0.0, 1.0).astype(np.float32)

def _get_recast_u2net_session():
    """Load the existing local background-removal model once on CPU."""
    state = _recast_u2net
    if state.session is not None:
        return state.session
    with state.session_lock:
        if state.session is None:
            model_home = os.path.join(_app_dir, "ckpts", "rembg")
            os.makedirs(model_home, exist_ok=True)
            os.environ.setdefault("U2NET_HOME", model_home)
            from services.rembg_adapter import background_session

            print(
                "[Recast] Loading U2Net edge refinement on CPU "
                "(SAM3 remains the person selector; shared rembg adapter)"
            )
            state.session = background_session("u2net", force_cpu=True)
    return state.session


def _run_recast_u2net_matte(reference_frame, reference_path=None):
    """Return decontaminated foreground RGB and alpha, with a small cache."""
    import numpy as np
    from PIL import Image as _PILImage
    from services.rembg_adapter import remove_background_image

    frame = np.asarray(reference_frame, dtype=np.uint8)
    cache_key = None
    if reference_path:
        try:
            stat = os.stat(reference_path)
            cache_key = (
                os.path.normcase(os.path.realpath(reference_path)),
                int(stat.st_mtime_ns),
                int(stat.st_size),
            )
        except OSError:
            cache_key = None
    if cache_key is not None:
        with _recast_u2net.cache_lock:
            cached = _recast_u2net.cache.get(cache_key)
            if cached is not None:
                return cached[0].copy(), cached[1].copy()

    session = _get_recast_u2net_session()
    with _recast_u2net.run_lock:
        cutout = remove_background_image(
            _PILImage.fromarray(frame),
            model="u2net",
            session=session,
            alpha_matting=True,
            alpha_matting_erode_size=1,
            bgcolor=(0, 0, 0, 0),
        )
    if not isinstance(cutout, _PILImage.Image):
        raise ValueError("U2Net returned an unsupported Recast matte.")
    cutout_array = np.asarray(cutout.convert("RGBA"), dtype=np.uint8)
    foreground = cutout_array[..., :3].copy()
    alpha = cutout_array[..., 3].astype(np.float32) / 255.0
    if foreground.shape != frame.shape or alpha.shape != frame.shape[:2]:
        raise ValueError("U2Net returned a mismatched Recast matte size.")

    if cache_key is not None:
        with _recast_u2net.cache_lock:
            _recast_u2net.cache[cache_key] = (
                foreground.copy(),
                alpha.copy(),
            )
            while len(_recast_u2net.cache) > _RECAST_U2NET_CACHE_LIMIT:
                oldest_key = next(iter(_recast_u2net.cache))
                _recast_u2net.cache.pop(oldest_key, None)
    return foreground, alpha

def _refine_recast_reference_cutout(
    reference_frame,
    subject,
    opacity,
    mask_source,
    *,
    reference_path=None,
    matte_runner=None,
):
    """Clean one selected reference subject without changing its identity."""
    import cv2
    import numpy as np

    frame = np.asarray(reference_frame, dtype=np.uint8)
    selected = np.asarray(subject).astype(bool)
    selected_opacity = np.clip(
        np.asarray(opacity, dtype=np.float32),
        0.0,
        1.0,
    )
    # Respect a user's authored transparent cutout. It already has the most
    # precise alpha available and should not be reinterpreted by U2Net.
    if str(mask_source).lower().startswith("png alpha"):
        return selected, selected_opacity, mask_source, frame.copy()

    runner = matte_runner or _run_recast_u2net_matte
    edge_width = max(
        1,
        min(4, int(round(min(selected.shape[:2]) * 0.004))),
    )
    fallback_rgb = _decontaminate_recast_reference_edges(
        frame,
        selected,
        width=edge_width,
    )
    try:
        u2net_rgb, u2net_alpha = runner(
            frame,
            reference_path=reference_path,
        )
        u2net_rgb = np.asarray(u2net_rgb, dtype=np.uint8)
        u2net_alpha = np.asarray(u2net_alpha, dtype=np.float32)
        if u2net_rgb.shape != frame.shape:
            raise ValueError("U2Net foreground RGB size is invalid.")
        if u2net_alpha.shape != selected.shape:
            raise ValueError("U2Net alpha size is invalid.")
        normalized_alpha = (
            u2net_alpha / 255.0
            if u2net_alpha.size and float(u2net_alpha.max()) > 1.0
            else u2net_alpha
        )
        coverage = float(np.count_nonzero(
            (normalized_alpha > 0.05) & selected,
        )) / float(max(1, np.count_nonzero(selected)))
        if coverage < 0.45:
            raise ValueError(
                f"U2Net covered only {coverage:.0%} of the selected person."
            )
        refined_opacity = _constrain_recast_u2net_matte(
            selected,
            selected_opacity,
            normalized_alpha,
        )
        refined_subject = refined_opacity > 0.02
        cleaned_rgb = fallback_rgb
        valid_foreground = normalized_alpha > 0.01
        cleaned_rgb[valid_foreground] = u2net_rgb[valid_foreground]
        return (
            refined_subject,
            refined_opacity,
            f"{mask_source} + U2Net soft edge",
            cleaned_rgb,
        )
    except Exception as exc:
        # Recast must still work offline or when the optional matte runtime is
        # unavailable. The local fallback removes the most obvious fringe and
        # feathers only the boundary of the SAM-selected person.
        distance = cv2.distanceTransform(
            selected.astype(np.uint8),
            cv2.DIST_L2,
            3,
        )
        fallback_opacity = np.minimum(
            selected_opacity,
            np.clip(
                distance / float(edge_width + 0.5),
                0.0,
                1.0,
            ),
        ).astype(np.float32)
        print(
            "[Recast] U2Net edge refinement unavailable; using local "
            f"boundary cleanup ({exc})"
        )
        return (
            selected,
            fallback_opacity,
            f"{mask_source} + local edge cleanup",
            fallback_rgb,
        )

# --- collaborators ---
_app_dir = bindable("_app_dir")
