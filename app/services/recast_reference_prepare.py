"""Recast reference preparation: media, profiles, prompts, crops, and conditioning.

Function bodies are the launch module's, moved verbatim. Launch hands this
module its ``_workspace_dir`` once, through :func:`bind`. Helpers that moved
with this slice are imported from their modules at the bottom of this file.
"""

import os

# Bound by bind(); None until the full server binds it.
_workspace_dir = None


def bind(*, workspace_dir):
    """Take the launch workspace-folder lookup media paths resolve under. Launch calls this once."""
    globals().update(_workspace_dir=workspace_dir)


# --- moved verbatim ---
# Official replacement-specific SCAIL-2 Relighting LoRA. Upstream publishes a
# SAT/PyTorch checkpoint, so Maestro downloads the immutable revision, verifies
# its official hash, and converts it once to Wan safetensors on first use.
_RECAST_RELIGHTING_LORA_FILENAME = "scail2_relighting_lora.safetensors"
_RECAST_RELIGHTING_LORA_REVISION = "150cc0ca4e98e50e60b9295dacde39442fdccab2"
_RECAST_RELIGHTING_LORA_REMOTE_PATH = "model/relighting-lora.pt"
_RECAST_RELIGHTING_LORA_SHA256 = "80d338a7969c1b286c8f5c4996b37eb198d0864837fecb6c87c106ca74571a2b"
_RECAST_RELIGHTING_LORA_SIZE = 1_227_381_060

_RECAST_FAST_MODEL_TYPE = "scail2_14B_recast_fast"
_RECAST_LEGACY_FAST_MODEL_TYPE = "scail2_14B_fast"
_RECAST_RESOLUTION_PROFILES = {
    # Width/height describe the landscape budget. The source video's
    # orientation and aspect ratio are applied below on a 32px boundary.
    "480p": (832, 480),
    "512p": (896, 512),
    "704p": (1280, 704),
}
_RECAST_WARMUP_FRAMES = 8

def _normalize_recast_lora_settings(
    activated_loras, loras_multipliers, use_relighting,
):
    """Return aligned, single-phase LoRA settings for a Recast run.

    Wan exposes as many as three LoRA phases in the shared Studio UI, while
    SCAIL-2 Recast deliberately runs one guidance phase. Old/stale UI state
    can therefore contain ``1;1;1`` even when Recast has only one selected
    LoRA. Pair multipliers with their LoRA *before* appending the managed
    relighting LoRA, discard orphan multipliers, and retain only the first
    phase for every selected LoRA.

    Selecting the official relighting LoRA directly in Advanced is also an
    explicit opt-in. The main Recast toggle adds it at 1.0 only when Advanced
    has not already supplied it, preserving a user-adjusted Advanced weight.
    """

    if isinstance(activated_loras, (list, tuple)):
        source_loras = [
            str(item).strip()
            for item in activated_loras
            if isinstance(item, str) and item.strip()
        ]
    else:
        source_loras = []

    if isinstance(loras_multipliers, (list, tuple)):
        source_multipliers = [
            str(item).strip() for item in loras_multipliers
        ]
    else:
        source_multipliers = []
        for line in str(loras_multipliers or "").replace("\r", "").split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            source_multipliers.extend(line.replace("|", " ").split())

    def _single_phase_multiplier(index):
        if index >= len(source_multipliers):
            return "1.0"
        first_phase = source_multipliers[index].split(";", 1)[0].strip()
        return first_phase or "1.0"

    def _lora_key(value):
        return str(value).replace("\\", "/").rsplit("/", 1)[-1].casefold()

    normalized_loras = []
    normalized_multipliers = []
    seen = set()
    for index, name in enumerate(source_loras):
        key = _lora_key(name)
        if key in seen:
            continue
        seen.add(key)
        normalized_loras.append(name)
        normalized_multipliers.append(_single_phase_multiplier(index))

    relighting_key = _lora_key(_RECAST_RELIGHTING_LORA_FILENAME)
    if use_relighting and relighting_key not in seen:
        normalized_loras.append(_RECAST_RELIGHTING_LORA_FILENAME)
        normalized_multipliers.append("1.0")
        seen.add(relighting_key)

    return (
        normalized_loras,
        " ".join(normalized_multipliers),
        relighting_key in seen,
    )

def _resolve_recast_media(raw, workspace):
    """Resolve a media reference the way edit endpoints do: absolute path
    first, then workspace outputs, then uploads/, then outputs/."""
    if not raw:
        return None
    raw = str(raw)
    if os.path.isabs(raw) and os.path.isfile(raw):
        return raw
    for base in (
        _workspace_dir(workspace),
        os.path.join(os.getcwd(), "uploads"),
        os.path.join(os.getcwd(), "outputs"),
    ):
        cand = os.path.join(base, os.path.basename(raw))
        if os.path.isfile(cand):
            return cand
    if os.path.isfile(raw):
        return raw
    return None

def _normalize_recast_person_count(value):
    """Clamp the SCAIL-2 person slot count to its supported 1-5 range."""
    try:
        return min(5, max(1, int(value)))
    except (TypeError, ValueError):
        return 1

def _normalize_recast_resolution_profile(value):
    """Return a supported SCAIL-2 edit resolution without changing models."""
    normalized = str(value or "").strip().lower().replace(" ", "")
    aliases = {
        "480": "480p",
        "832x480": "480p",
        "fast": "480p",
        "512": "512p",
        "896x512": "512p",
        "quality": "512p",
        "704": "704p",
        "1280x704": "704p",
        "high": "704p",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in _RECAST_RESOLUTION_PROFILES:
        return "480p"
    return normalized

def _recast_window_size_for_profile(resolution_profile, total_vram_gb):
    """Choose a VAE-aligned SCAIL-2 edit window without changing model steps.

    SCAIL-2 activation pressure scales approximately with spatial pixels times
    frames in the active window. A 1280x704 frame has almost twice the pixels
    of 896x512, so retaining the ordinary 81-frame window would nearly double
    the non-streamable attention workspace. Shorter 4n+1 windows keep 704p
    practical while MMGP independently streams model weights.

    A zero return means the detected GPU is below the currently supported
    704p floor. Unknown hardware uses the conservative middle window rather
    than rejecting a valid NVIDIA setup because a probe was unavailable.
    """
    profile = _normalize_recast_resolution_profile(resolution_profile)
    if profile != "704p":
        return 81
    try:
        vram_gb = float(total_vram_gb)
    except (TypeError, ValueError):
        vram_gb = 0.0
    if vram_gb <= 0:
        return 41
    if vram_gb >= 24.0:
        return 49
    if vram_gb >= 20.0:
        return 41
    if vram_gb >= 16.0:
        return 33
    return 0

def _build_recast_prompt(raw_prompt, person_count, enhance=True):
    """Return an idempotent finished-video description for SCAIL-2.

    Upstream explicitly asks for a description of the completed video, not an
    editing command. Convert the most common ``replace X with Y`` phrasing and
    append descriptive continuity language without imperative "keep" clauses.
    When enhancement is disabled, preserve the user's prompt verbatim apart
    from surrounding whitespace so A/B tests can isolate the model behavior.
    """
    import re

    prompt = str(raw_prompt or "").strip()
    if not enhance:
        if not prompt:
            raise ValueError(
                "Enter a Recast prompt when automatic prompt enhancement is disabled."
            )
        return prompt

    detail_marker = "The surrounding people, environment, camera framing"
    count = _normalize_recast_person_count(person_count)
    plural = count != 1
    if prompt:
        instruction_patterns = (
            r"^(?:please\s+)?(?:replace|swap)\s+.+?\s+(?:with|for)\s+(.+)$",
            r"^(?:please\s+)?change\s+.+?\s+(?:into|to)\s+(.+)$",
        )
        for pattern in instruction_patterns:
            match = re.match(pattern, prompt, flags=re.IGNORECASE | re.DOTALL)
            if match:
                prompt = match.group(1).strip()
                break
    if not prompt:
        prompt = (
            "Several clearly defined characters perform naturally within the scene"
            if plural else
            "A clearly defined character performs naturally within the scene"
        )
    prompt = prompt[0].upper() + prompt[1:] if prompt else prompt
    if detail_marker in prompt:
        return prompt
    prompt = prompt.rstrip()
    if prompt[-1:] not in ".!?":
        prompt += "."
    identity = (
        "The characters' faces, hair, body shapes, and complete outfits remain "
        "visually consistent as they follow the visible action and interactions."
        if plural else
        "The character's face, hair, body shape, and complete outfit remain "
        "visually consistent as the character follows the visible action and interactions."
    )
    return (
        f"{prompt} {identity} {detail_marker}, lighting, shadows, and nearby "
        "objects form one coherent, naturally lit scene throughout the video."
    )

def _recast_video_has_audio(video_path):
    """Return whether ffprobe finds an audio stream in a video."""
    import subprocess

    probe = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-select_streams", "a:0",
            "-show_entries", "stream=codec_type", "-of", "csv=p=0",
            video_path,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return probe.returncode == 0 and bool(probe.stdout.strip())

def _recast_resolution_for_source(source_frame, resolution_profile=None):
    """Resolve a SCAIL-2 edit profile to the source-oriented output size."""
    profile = _normalize_recast_resolution_profile(resolution_profile)
    base_width, base_height = _RECAST_RESOLUTION_PROFILES[profile]
    return _recast_reference_canvas_size(
        source_frame,
        base_width=base_width,
        base_height=base_height,
        block_size=32,
    )

def _recast_subject_crop_box(subject, margin_fraction=0.08):
    """Return a padded subject box without discarding any identity pixels."""
    import numpy as np

    region = np.asarray(subject).astype(bool)
    ys, xs = np.nonzero(region)
    if len(xs) == 0:
        return 0, 0, region.shape[1], region.shape[0]
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    margin = max(4, int(round(max(x1 - x0, y1 - y0) * margin_fraction)))
    return (
        max(0, x0 - margin),
        max(0, y0 - margin),
        min(region.shape[1], x1 + margin),
        min(region.shape[0], y1 + margin),
    )

def _recast_face_detail_crop_box(subject):
    """Frame the upper identity region while retaining hair and shoulders.

    Recast references are expected to contain one clear replacement subject.
    A second, tighter view of that same subject gives SCAIL-2 substantially
    more facial detail without sacrificing the primary image's outfit/body
    information.  The semantic subject silhouette keeps this deterministic
    and avoids introducing a separate face-model download.
    """
    import numpy as np

    region = np.asarray(subject).astype(bool)
    height, width = region.shape[:2]
    ys, xs = np.nonzero(region)
    if len(xs) == 0 or width < 2 or height < 2:
        return 0, 0, width, height

    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    subject_width = max(1, x1 - x0)
    subject_height = max(1, y1 - y0)

    # The upper 56% of an upright subject is a reliable head-and-shoulders
    # detail view.  A roughly 4:5 crop matches the successful manual Recast
    # close-up workflow while leaving room for hair, neck, and clothing cues.
    crop_height = max(2, int(round(subject_height * 0.56)))
    crop_width = max(
        2,
        int(round(crop_height * 0.80)),
        int(round(subject_width * 0.66)),
    )
    crop_height = max(crop_height, int(round(crop_width / 0.82)))
    crop_width = min(width, crop_width)
    crop_height = min(height, crop_height)

    upper_limit = y0 + max(1, int(round(subject_height * 0.40)))
    upper_xs = np.nonzero(region & (
        np.arange(height, dtype=np.int32)[:, None] < upper_limit
    ))[1]
    center_x = (
        float(np.median(upper_xs))
        if len(upper_xs)
        else (x0 + x1) / 2.0
    )

    left = int(round(center_x - crop_width / 2.0))
    top = int(round(y0 - subject_height * 0.02))
    left = max(0, min(left, width - crop_width))
    top = max(0, min(top, height - crop_height))
    return left, top, left + crop_width, top + crop_height

def _derive_recast_face_detail_reference(
    reference_path,
    output_path,
    *,
    refine_cutout=True,
):
    """Persist an automatic head-and-shoulders view of one reference."""
    import numpy as np
    from PIL import Image as _PILImage, ImageOps as _PILImageOps

    with _PILImage.open(reference_path) as source:
        rgba = _PILImageOps.exif_transpose(source).convert("RGBA")
        rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
        alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)

    subject, opacity, mask_source = _recast_reference_subject_mask(rgb, alpha)
    foreground_rgb = rgb
    if refine_cutout:
        subject, opacity, mask_source, foreground_rgb = (
            _refine_recast_reference_cutout(
                rgb,
                subject,
                opacity,
                mask_source,
                reference_path=reference_path,
            )
        )
    crop_box = _recast_face_detail_crop_box(subject)
    if crop_box == (0, 0, rgba.width, rgba.height):
        return None
    clean_rgba = np.concatenate(
        (
            np.asarray(foreground_rgb, dtype=np.uint8),
            np.rint(np.clip(opacity, 0.0, 1.0) * 255.0)
            .astype(np.uint8)[..., None],
        ),
        axis=-1,
    )
    detail = _PILImage.fromarray(clean_rgba).crop(crop_box)
    if detail.width < 2 or detail.height < 2:
        return None
    detail.save(output_path, format="PNG")
    left, top, right, bottom = crop_box
    metadata = {
        "path": output_path,
        "crop_box": list(crop_box),
        "source_size": [rgba.width, rgba.height],
        "detail_size": [detail.width, detail.height],
        "detail_source": f"upper-subject crop from {mask_source}",
    }
    return {
        "metadata": metadata,
        # Reuse this one segmentation pass for both generated SCAIL views.
        # Without these cached layers, the primary plus derived crop would
        # make SAM3 analyze the same identity three times.
        "source_conditioning": (
            subject,
            opacity,
            mask_source,
            foreground_rgb,
        ),
        "detail_conditioning": (
            subject[top:bottom, left:right],
            opacity[top:bottom, left:right],
            mask_source,
            foreground_rgb[top:bottom, left:right],
        ),
    }

def _recast_region_bbox_aspect(region):
    """Return width/height for the visible bounding box of a mask."""
    import numpy as np

    ys, xs = np.nonzero(np.asarray(region).astype(bool))
    if len(xs) == 0:
        return None
    width = max(1, int(xs.max()) - int(xs.min()) + 1)
    height = max(1, int(ys.max()) - int(ys.min()) + 1)
    return float(width) / float(height)

def _recast_face_detail_upscale_factor(detail_size, canvas_size):
    """Return the enlargement needed to contain a detail view on its canvas."""
    try:
        detail_width, detail_height = (
            float(detail_size[0]),
            float(detail_size[1]),
        )
        canvas_width, canvas_height = (
            float(canvas_size[0]),
            float(canvas_size[1]),
        )
    except (IndexError, TypeError, ValueError):
        return None
    if min(
        detail_width,
        detail_height,
        canvas_width,
        canvas_height,
    ) <= 0:
        return None
    return min(
        canvas_width / detail_width,
        canvas_height / detail_height,
    )

def _recast_should_add_auto_face_detail(
    mapping,
    enabled=True,
    *,
    source_probe_mask=None,
    semantic_color=None,
    reference_subject=None,
    detail_size=None,
    canvas_size=None,
    max_upscale=1.75,
):
    """Use auto detail only when it will not compete with an explicit view."""
    eligible = bool(
        enabled
        and not mapping.get("reference_aligned_to_source")
        and not mapping.get("additional_ref_image_paths")
    )
    if not eligible:
        return False

    upscale_factor = _recast_face_detail_upscale_factor(
        detail_size,
        canvas_size,
    )
    if (
        upscale_factor is not None
        and upscale_factor > float(max_upscale)
    ):
        return False

    if (
        source_probe_mask is None
        or semantic_color is None
        or reference_subject is None
    ):
        return eligible

    import numpy as np

    source_mask = np.asarray(source_probe_mask)
    if source_mask.ndim == 3 and source_mask.shape[-1] == 3:
        target_region = np.all(
            source_mask == np.asarray(semantic_color, dtype=np.uint8),
            axis=-1,
        )
    else:
        target_region = source_mask.astype(bool)
    target_aspect = _recast_region_bbox_aspect(target_region)
    reference_aspect = _recast_region_bbox_aspect(reference_subject)
    if target_aspect is None or reference_aspect is None:
        return eligible

    # A tall/narrow driving silhouette normally means a full-body shot. If
    # the supplied identity is a substantially wider upper-body portrait,
    # another enlarged face crop becomes a second competing spatial subject.
    # Keep the primary identity view but omit that redundant extra region.
    if (
        target_aspect < 0.65
        and reference_aspect > target_aspect * 1.45
    ):
        return False
    return eligible

def _prepare_recast_reference_frame(
    reference_path, color, *, isolate_reference=True,
    aligned_semantic_mask=None, subject_conditioning=None,
    spatial_background=None, width=832, height=480,
):
    """Build separate CLIP-identity and spatial RGB inputs for SCAIL-2."""
    import numpy as np
    from PIL import Image as _PILImage, ImageOps as _PILImageOps

    with _PILImage.open(reference_path) as source:
        rgba = _PILImageOps.exif_transpose(source).convert("RGBA")
        rgb = np.asarray(rgba.convert("RGB"), dtype=np.uint8)
        alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)

    aligned = aligned_semantic_mask is not None
    foreground_rgb = rgb
    if aligned:
        semantic_rgb = np.asarray(aligned_semantic_mask, dtype=np.uint8)
        if semantic_rgb.shape[:2] != rgb.shape[:2]:
            semantic_rgb = np.asarray(
                _PILImage.fromarray(semantic_rgb, mode="RGB").resize(
                    (rgb.shape[1], rgb.shape[0]),
                    resample=_PILImage.Resampling.NEAREST,
                ),
                dtype=np.uint8,
            )
        subject = np.any(semantic_rgb > 30, axis=-1)
        opacity = subject.astype(np.float32)
        mask_source = "aligned source overlap"
    else:
        if subject_conditioning is None:
            subject, opacity, mask_source = _recast_reference_subject_mask(
                rgb, alpha,
            )
            if isolate_reference:
                subject, opacity, mask_source, foreground_rgb = (
                    _refine_recast_reference_cutout(
                        rgb,
                        subject,
                        opacity,
                        mask_source,
                        reference_path=reference_path,
                    )
                )
        else:
            if len(subject_conditioning) == 4:
                (
                    subject,
                    opacity,
                    mask_source,
                    foreground_rgb,
                ) = subject_conditioning
            elif len(subject_conditioning) == 3:
                subject, opacity, mask_source = subject_conditioning
            else:
                raise ValueError(
                    "Cached Recast reference conditioning is invalid."
                )
            subject = np.asarray(subject).astype(bool)
            opacity = np.asarray(opacity, dtype=np.float32)
            foreground_rgb = np.asarray(foreground_rgb, dtype=np.uint8)
            if (
                subject.shape != rgb.shape[:2]
                or opacity.shape != rgb.shape[:2]
                or foreground_rgb.shape != rgb.shape
            ):
                raise ValueError(
                    "Cached Recast reference mask does not match its image."
                )
        semantic_rgb = np.zeros_like(rgb, dtype=np.uint8)
        semantic_rgb[subject] = np.asarray(color, dtype=np.uint8)

    if isolate_reference:
        foreground_image, prepared_mask = _fit_recast_reference_layers(
            foreground_rgb,
            semantic_rgb,
            int(width),
            int(height),
            aligned=aligned,
            crop_to_subject=True,
        )
        opacity_rgb = np.repeat(
            np.rint(np.clip(opacity, 0.0, 1.0) * 255.0)
            .astype(np.uint8)[..., None],
            3,
            axis=-1,
        )
        opacity_image, _ = _fit_recast_reference_layers(
            opacity_rgb,
            semantic_rgb,
            int(width),
            int(height),
            aligned=aligned,
            crop_to_subject=True,
            canvas_color=(0, 0, 0),
        )
        if spatial_background is None:
            background = np.full(
                (int(height), int(width), 3),
                127,
                dtype=np.uint8,
            )
        else:
            background = np.asarray(spatial_background, dtype=np.uint8)
            if background.ndim != 3 or background.shape[-1] != 3:
                raise ValueError(
                    "Recast spatial background must be an H/W/RGB image; "
                    f"got {background.shape}."
                )
            if background.shape[:2] != (int(height), int(width)):
                background = np.asarray(
                    _PILImage.fromarray(background).resize(
                        (int(width), int(height)),
                        resample=_PILImage.Resampling.LANCZOS,
                    ),
                    dtype=np.uint8,
                )
        foreground_array = np.asarray(
            foreground_image.convert("RGB"),
            dtype=np.uint8,
        )
        prepared_opacity = (
            np.asarray(
                opacity_image.convert("RGB"),
                dtype=np.float32,
            )[..., :1]
            / 255.0
        )
        semantic_region = np.any(
            np.asarray(
                prepared_mask.convert("RGB"),
                dtype=np.uint8,
            ) > 30,
            axis=-1,
        )
        prepared_opacity[~semantic_region] = 0.0
        prepared_array = np.rint(
            foreground_array.astype(np.float32) * prepared_opacity
            + background.astype(np.float32) * (1.0 - prepared_opacity)
        ).clip(0, 255).astype(np.uint8)
        prepared_image = _PILImage.fromarray(prepared_array)
    else:
        prepared_image, prepared_mask = _fit_recast_reference_layers(
            rgb,
            semantic_rgb,
            int(width),
            int(height),
            aligned=aligned,
            crop_to_subject=False,
        )
    if isolate_reference:
        # Keep the original, uncropped reference composition for CLIP identity.
        # Only the VAE/spatial reference gets the source-scene background and
        # tighter subject framing. This preserves the strong face signal
        # observed with isolation disabled without allowing the reference
        # room/background to leak through SCAIL-2's spatial latent.
        identity_image, _ = _fit_recast_reference_layers(
            rgb,
            semantic_rgb,
            int(width),
            int(height),
            aligned=aligned,
            crop_to_subject=False,
        )
    else:
        identity_image = prepared_image.copy()
    return {
        "image": prepared_image,
        "identity_image": identity_image,
        "mask": prepared_mask,
        "mask_source": mask_source,
        "source_size": (int(rgb.shape[1]), int(rgb.shape[0])),
        "prepared_size": (int(width), int(height)),
    }

def _recast_image_data_uri(image, image_format="PNG"):
    import base64
    import io

    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    mime = "image/png" if image_format.upper() == "PNG" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(buffer.getvalue()).decode()

def _recast_reference_preview_payload(
    prepared, mapping_index, view_index, kind, view_metadata=None,
):
    image = prepared["image"].convert("RGB")
    identity_image = prepared["identity_image"].convert("RGB")
    mask = prepared["mask"].convert("RGB")
    payload = {
        "mapping_index": mapping_index,
        "view_index": view_index,
        "kind": kind,
        "mask_source": prepared["mask_source"],
        "source_size": list(prepared["source_size"]),
        "prepared_size": list(prepared["prepared_size"]),
        "prepared_image": _recast_image_data_uri(image),
        "semantic_mask": _recast_image_data_uri(mask),
    }
    if view_metadata:
        payload.update({
            key: value
            for key, value in view_metadata.items()
            if key in {
                "crop_box", "detail_size", "detail_source",
                "detail_upscale_factor",
            }
        })
    if mapping_index == 0 and view_index == 0:
        payload["clip_identity_image"] = _recast_image_data_uri(identity_image)
    return payload

def _prepare_recast_reference_conditioning(
    mappings, source_probe_mask, output_dir, job_id, *,
    isolate_reference, selected_count, auto_face_detail=True,
    source_frame=None, reference_canvas=None, mapping_anchors=None,
):
    """Prepare reference pairs using each character's own timeline anchor."""
    import numpy as np
    from PIL import Image as _PILImage, ImageOps as _PILImageOps
    from shared import magic_mask

    os.makedirs(output_dir, exist_ok=True)
    image_paths = []
    mask_paths = []
    clip_identity_path = None
    expected_colors = []
    previews = []
    auto_face_detail_refs = []
    primary_target_refs = []
    canvas_width, canvas_height = 832, 480
    anchor_list = (
        mapping_anchors
        if isinstance(mapping_anchors, list)
        else []
    )
    first_anchor_frame = None
    if anchor_list and isinstance(anchor_list[0], dict):
        first_anchor_frame = anchor_list[0].get("source_frame")
    if reference_canvas is not None:
        try:
            canvas_width, canvas_height = (
                int(reference_canvas[0]),
                int(reference_canvas[1]),
            )
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                "Recast reference canvas must contain width and height."
            ) from exc
        if (
            min(canvas_width, canvas_height) <= 0
            or canvas_width % 32
            or canvas_height % 32
        ):
            raise ValueError(
                "Recast reference canvas dimensions must be positive and "
                "divisible by 32."
            )
    elif source_frame is not None:
        canvas_width, canvas_height = _recast_reference_canvas_size(
            source_frame,
        )
    elif first_anchor_frame is not None:
        canvas_width, canvas_height = _recast_reference_canvas_size(
            first_anchor_frame,
        )
    for mapping_index, mapping in enumerate(mappings):
        color = _RECAST_MASK_COLORS[mapping_index]
        mapping_source_frame = source_frame
        mapping_source_mask = source_probe_mask
        if (
            mapping_index < len(anchor_list)
            and isinstance(anchor_list[mapping_index], dict)
        ):
            mapping_source_frame = anchor_list[mapping_index].get(
                "source_frame",
                mapping_source_frame,
            )
            mapping_source_mask = anchor_list[mapping_index].get(
                "source_mask",
                mapping_source_mask,
            )
        spatial_background = None
        if mapping_source_frame is not None:
            scene_layers = _build_recast_source_scene_layers(
                mapping_source_frame,
                mapping_source_mask,
                selected_count,
                output_size=(canvas_width, canvas_height),
            )
            spatial_background = scene_layers["image"]
        views = [{
            "kind": "primary",
            "path": mapping["ref_image_path"],
        }]
        if _recast_should_add_auto_face_detail(mapping, auto_face_detail):
            detail_path = os.path.join(
                output_dir,
                f"recast_auto_face_detail_{job_id}_{mapping_index + 1}.png",
            )
            detail_result = _derive_recast_face_detail_reference(
                mapping["ref_image_path"],
                detail_path,
                refine_cutout=isolate_reference,
            )
            if detail_result:
                views[0]["subject_conditioning"] = detail_result[
                    "source_conditioning"
                ]
                detail_upscale_factor = _recast_face_detail_upscale_factor(
                    detail_result["metadata"]["detail_size"],
                    (canvas_width, canvas_height),
                )
                detail_result["metadata"]["detail_upscale_factor"] = (
                    round(detail_upscale_factor, 3)
                    if detail_upscale_factor is not None
                    else None
                )
                if _recast_should_add_auto_face_detail(
                    mapping,
                    auto_face_detail,
                    source_probe_mask=mapping_source_mask,
                    semantic_color=color,
                    reference_subject=detail_result[
                        "source_conditioning"
                    ][0],
                    detail_size=detail_result["metadata"]["detail_size"],
                    canvas_size=(canvas_width, canvas_height),
                ):
                    views.append({
                        "kind": "auto_face_detail",
                        "path": detail_path,
                        "metadata": detail_result["metadata"],
                        "subject_conditioning": detail_result[
                            "detail_conditioning"
                        ],
                    })
                    auto_face_detail_refs.append({
                        "mapping_index": mapping_index,
                        **detail_result["metadata"],
                    })
                else:
                    try:
                        os.remove(detail_path)
                    except OSError:
                        pass
                    if (
                        detail_upscale_factor is not None
                        and detail_upscale_factor > 1.75
                    ):
                        reason = (
                            "the crop would require "
                            f"{detail_upscale_factor:.2f}x enlargement"
                        )
                    else:
                        reason = (
                            "the source target is full-body while the identity "
                            "reference is already a tighter upper-body view"
                        )
                    print(
                        "[Recast] Skipped automatic face-detail spatial view "
                        f"for mapping {mapping_index + 1}: {reason}."
                    )
        views.extend({
            "kind": "additional",
            "path": path,
        } for path in mapping.get("additional_ref_image_paths", []))
        for view_index, view in enumerate(views):
            kind = view["kind"]
            reference_path = view["path"]
            aligned_mask = None
            if view_index == 0 and mapping.get("reference_aligned_to_source"):
                with _PILImage.open(reference_path) as reference_image:
                    reference_frame = np.asarray(
                        _PILImageOps.exif_transpose(reference_image).convert("RGB"),
                        dtype=np.uint8,
                    )
                reference_people = magic_mask.generate_keyword_masks(
                    reference_frame[None],
                    "person",
                    no_hole=True,
                    colorize_objects=True,
                    color_palette=_RECAST_MASK_COLORS,
                    max_colored_objects=len(_RECAST_MASK_COLORS),
                )[0]
                aligned_colors = (
                    _RECAST_MASK_COLORS[:selected_count]
                    if len(mappings) == 1 and selected_count > 1
                    else [color]
                )
                aligned_mask, matched = _align_recast_reference_mask(
                    mapping_source_mask,
                    reference_people,
                    aligned_colors,
                    _RECAST_MASK_COLORS,
                )
                if matched < len(aligned_colors):
                    raise ValueError(
                        "The edited first-frame reference could not be aligned "
                        f"to every selected source person ({matched}/"
                        f"{len(aligned_colors)})."
                    )
            prepared = _prepare_recast_reference_frame(
                reference_path,
                color,
                isolate_reference=isolate_reference,
                aligned_semantic_mask=aligned_mask,
                subject_conditioning=view.get("subject_conditioning"),
                spatial_background=spatial_background,
                width=canvas_width,
                height=canvas_height,
            )
            suffix = f"{mapping_index + 1}_{view_index + 1}"
            prepared_path = os.path.join(
                output_dir, f"recast_prepared_ref_{job_id}_{suffix}.png",
            )
            mask_path = os.path.join(
                output_dir, f"recast_prepared_mask_{job_id}_{suffix}.png",
            )
            prepared["image"].save(prepared_path)
            prepared["mask"].save(mask_path)
            if clip_identity_path is None:
                if isolate_reference:
                    clip_identity_path = os.path.join(
                        output_dir,
                        f"recast_clip_identity_ref_{job_id}_{suffix}.png",
                    )
                    prepared["identity_image"].save(clip_identity_path)
                else:
                    clip_identity_path = prepared_path
            image_paths.append(prepared_path)
            mask_paths.append(mask_path)
            expected_colors.append(list(color))
            if view_index == 0:
                primary_target_refs.append({
                    "mapping_index": mapping_index,
                    "image": prepared_path,
                    "mask": mask_path,
                    "color": list(color),
                })
            previews.append(
                _recast_reference_preview_payload(
                    prepared,
                    mapping_index,
                    view_index,
                    kind,
                    view.get("metadata"),
                )
            )
    if not image_paths:
        raise ValueError("Recast needs at least one prepared reference.")
    return {
        "image_refs": image_paths,
        "clip_identity_ref": clip_identity_path,
        "primary_mask": mask_paths[0],
        "additional_masks": mask_paths[1:],
        "expected_colors": expected_colors,
        "previews": previews,
        "auto_face_detail_refs": auto_face_detail_refs,
        "primary_target_refs": primary_target_refs,
        "reference_canvas": [canvas_width, canvas_height],
    }

def _load_recast_reference_pair(
    image_path, mask_path, global_mapping_index, local_mapping_index,
):
    """Load a prepared image/mask pair and assign its shot-local color."""
    import numpy as np
    from PIL import Image as _PILImage

    with _PILImage.open(image_path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    with _PILImage.open(mask_path) as mask:
        semantic = np.asarray(mask.convert("RGB"), dtype=np.uint8)
    if semantic.shape != rgb.shape:
        raise ValueError(
            "Prepared Recast reference image and mask dimensions differ."
        )
    return (
        rgb,
        _recolor_recast_reference_mask(
            semantic,
            global_mapping_index,
            local_mapping_index,
        ),
    )

def _save_recast_reference_pair(
    output_dir, stem, image, semantic_mask,
):
    """Save an internal SCAIL reference pair and return both paths."""
    from PIL import Image as _PILImage

    os.makedirs(output_dir, exist_ok=True)
    image_path = os.path.join(output_dir, f"{stem}.png")
    mask_path = os.path.join(output_dir, f"{stem}_mask.png")
    _PILImage.fromarray(image).save(image_path)
    _PILImage.fromarray(semantic_mask).save(mask_path)
    return image_path, mask_path

def _recast_video_frame_count(video_path):
    """Return the exact decoded video-frame count for final validation."""
    import decord

    reader = decord.VideoReader(video_path)
    try:
        return int(len(reader))
    finally:
        del reader

# --- helpers that moved with this slice ---
# Imported last: these modules import this one back, and every name they take
# from here is defined above by then.
from services.recast_masks import (
    _RECAST_MASK_COLORS,
    _align_recast_reference_mask,
    _recolor_recast_reference_mask,
)
from services.recast_reference_compose import (
    _recast_reference_canvas_size,
    _build_recast_source_scene_layers,
    _fit_recast_reference_layers,
)
from services.recast_matte import (
    _recast_reference_subject_mask,
    _refine_recast_reference_cutout,
)
