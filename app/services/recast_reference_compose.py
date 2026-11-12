"""Recast reference composition: group, cast, native people, and source scene.

Function bodies are the launch module's, moved verbatim. Nothing here reads a
launch name: the colors, regions, person count and subject crop it uses moved
with this slice and are imported from their modules at the bottom of this file.
"""

import os

# --- moved verbatim ---
def _recast_reference_canvas_size(
    source_frame, base_width=832, base_height=480, block_size=32,
):
    """Choose a SCAIL output/reference canvas for the control orientation.

    Recast profiles advertise a landscape resolution budget, but SCAIL-2
    reallocates that budget to follow the control video's aspect ratio.
    Preparing hidden references at a literal landscape size makes portrait
    controls consume references that are cropped again later. Preserve the
    source orientation on SCAIL-2's documented 32px boundary.
    """
    import math
    import numpy as np

    frame = np.asarray(source_frame)
    if frame.ndim != 3 or frame.shape[-1] != 3:
        raise ValueError(
            "Recast reference canvas needs an H/W/RGB source frame; "
            f"got {frame.shape}."
        )
    try:
        base_width = int(base_width)
        base_height = int(base_height)
        block_size = int(block_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("Recast reference canvas dimensions must be integers.") from exc
    if min(base_width, base_height, block_size) <= 0:
        raise ValueError("Recast reference canvas dimensions must be positive.")

    source_height, source_width = frame.shape[:2]
    aspect = float(source_width) / float(max(1, source_height))
    short_edge = min(base_width, base_height)
    long_edge = max(base_width, base_height)

    def _floor_block(value):
        return max(
            block_size,
            int(math.floor(float(value) / block_size)) * block_size,
        )

    if aspect >= 1.0:
        height = short_edge
        width = min(long_edge, _floor_block(height * aspect))
    else:
        width = short_edge
        height = min(long_edge, _floor_block(width / max(aspect, 1e-6)))
    return int(width), int(height)

def _build_recast_source_scene_layers(
    source_frame, target_mask, selected_count, output_size=None,
):
    """Return a target-free scene image and its official visibility mask."""
    import cv2
    import numpy as np
    from PIL import Image as _PILImage
    from PIL import ImageFilter as _PILImageFilter

    frame = np.asarray(source_frame, dtype=np.uint8)
    mask = np.asarray(target_mask, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[-1] != 3:
        raise ValueError(
            "Recast source-scene reference needs an H/W/RGB source frame; "
            f"got {frame.shape}."
        )
    if mask.shape != frame.shape:
        raise ValueError(
            "Recast source frame and target-anchor mask must have "
            f"matching dimensions; got frame={frame.shape}, mask={mask.shape}."
        )
    if output_size is not None:
        try:
            output_width, output_height = (
                int(output_size[0]),
                int(output_size[1]),
            )
        except (TypeError, ValueError, IndexError) as exc:
            raise ValueError(
                "Recast source-scene output size must contain width and height."
            ) from exc
        if output_width <= 0 or output_height <= 0:
            raise ValueError(
                "Recast source-scene output dimensions must be positive."
            )
        frame = np.asarray(
            _PILImage.fromarray(frame).resize(
                (output_width, output_height),
                resample=_PILImage.Resampling.LANCZOS,
            ),
            dtype=np.uint8,
        )
        mask = np.asarray(
            _PILImage.fromarray(mask).resize(
                (output_width, output_height),
                resample=_PILImage.Resampling.NEAREST,
            ),
            dtype=np.uint8,
        )

    requested_count = _normalize_recast_person_count(selected_count)
    target_region = np.zeros(frame.shape[:2], dtype=bool)
    mask_frames = mask[None]
    for color in _RECAST_MASK_COLORS[:requested_count]:
        target_region |= _recast_color_region(mask_frames, color)[0]
    if not bool(target_region.any()):
        raise ValueError(
            "Could not build the Recast source-scene reference because the "
            "selected target is missing from the anchor mask."
        )

    # Hide a small margin around the old target. The semantic mask is exact,
    # but VAE receptive fields can otherwise retain hair, clothing, or edge
    # pixels just outside the segmentation boundary.
    expansion = max(
        2,
        min(16, int(round(min(frame.shape[:2]) * 0.01))),
    )
    expanded = _PILImage.fromarray(
        target_region.astype(np.uint8) * 255,
    ).filter(_PILImageFilter.MaxFilter(expansion * 2 + 1))
    hidden_region = np.asarray(expanded, dtype=np.uint8) > 127

    # A neutral gray hole is not truly invisible to the VAE; the reference
    # mask is learned conditioning rather than a hard RGB gate. Inpaint the
    # hidden pixels from their surrounding scene so any latent leakage carries
    # compatible scene color/texture instead of replacing the whole background
    # with the matte color. The black semantic mask still tells SCAIL-2 not to
    # treat the synthesized hole as authoritative visible content.
    inpaint_mask = hidden_region.astype(np.uint8) * 255
    reference_frame = cv2.inpaint(
        frame,
        inpaint_mask,
        max(3, expansion * 2),
        cv2.INPAINT_TELEA,
    )
    reference_mask = np.full_like(frame, 255, dtype=np.uint8)
    reference_mask[hidden_region] = 0
    return {
        "image": reference_frame,
        "mask": reference_mask,
        "hidden_fraction": float(hidden_region.mean()),
        "expansion_pixels": expansion,
    }

def _build_recast_source_scene_reference(
    source_frame, target_mask, selected_count, output_dir, job_id,
    neutral_value=127, output_size=None,
):
    """Build an official-style clean-background reference for Recast.

    SCAIL-2's multi-reference mask semantics use white for source content that
    should remain visible and black for content that must be ignored. Preserve
    the selected source frame everywhere except the old target, then inpaint
    and black-mask that target so neither its identity nor a gray matte can
    leak through the VAE. This reuses one target anchor from Recast's tracked
    timeline; it does not add another SAM3 tracking pass.
    """
    import os
    from PIL import Image as _PILImage
    layers = _build_recast_source_scene_layers(
        source_frame,
        target_mask,
        selected_count,
        output_size=output_size,
    )
    try:
        int(neutral_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Recast source-scene neutral value must be an integer."
        ) from exc
    if not 0 <= int(neutral_value) <= 255:
        raise ValueError(
            "Recast source-scene neutral value must be between 0 and 255."
        )

    os.makedirs(output_dir, exist_ok=True)
    reference_path = os.path.join(
        output_dir, f"recast_source_scene_ref_{job_id}.png",
    )
    reference_mask_path = os.path.join(
        output_dir, f"recast_source_scene_mask_{job_id}.png",
    )
    _PILImage.fromarray(layers["image"]).save(reference_path)
    _PILImage.fromarray(layers["mask"]).save(reference_mask_path)
    return {
        "image": reference_path,
        "mask": reference_mask_path,
        "hidden_fraction": layers["hidden_fraction"],
        "expansion_pixels": layers["expansion_pixels"],
    }

def _enable_recast_dynamic_source_scene_reference(
    params, source_frame, target_mask, selected_count, output_dir, job_id,
):
    """Enable target-free source-scene conditioning for Recast.

    The historical helper/flag names say ``dynamic`` for saved-project
    compatibility. Dedicated single-shot Recast reuses this persisted pair.
    Timeline-aware jobs retain it as a fallback and ask SCAIL-2 to rebuild the
    pair from each current control window.
    """
    if not isinstance(params, dict):
        raise ValueError("Recast generation parameters must be a dictionary.")
    image_refs = params.get("image_refs")
    custom_settings = params.get("custom_settings")
    if not isinstance(image_refs, list) or not image_refs:
        raise ValueError(
            "Recast needs a primary identity reference before adding the "
            "source-scene reference."
        )
    if not isinstance(custom_settings, dict):
        raise ValueError("Recast custom settings are missing.")
    additional_masks = custom_settings.get(
        "scail2_additional_reference_mask_paths",
    )
    expected_colors = custom_settings.get(
        "scail2_reference_expected_colors",
    )
    if not isinstance(additional_masks, list):
        raise ValueError("Recast additional reference masks are missing.")
    if not isinstance(expected_colors, list):
        raise ValueError("Recast expected reference colors are missing.")
    if len(additional_masks) != len(image_refs) - 1:
        raise ValueError(
            "Recast image references and additional masks are out of sync."
        )
    if len(expected_colors) != len(image_refs):
        raise ValueError(
            "Recast image references and expected colors are out of sync."
        )

    output_size = params.get("edit_recast_reference_canvas")
    if (
        not isinstance(output_size, (list, tuple))
        or len(output_size) != 2
    ):
        output_size = _recast_reference_canvas_size(source_frame)
    else:
        try:
            output_size = tuple(int(value) for value in output_size)
        except (TypeError, ValueError):
            output_size = _recast_reference_canvas_size(source_frame)
        if min(output_size) <= 0:
            output_size = _recast_reference_canvas_size(source_frame)
    scene_reference = _build_recast_source_scene_reference(
        source_frame,
        target_mask,
        selected_count,
        output_dir,
        job_id,
        output_size=output_size,
    )
    # Keep this pair out of ``image_refs`` so it does not become a user-facing
    # character slot.  The dedicated conditioner loads it as a separate,
    # stable additional reference for every segment.
    custom_settings["scail2_dynamic_source_scene_reference"] = True
    custom_settings["scail2_source_scene_reference_path"] = (
        scene_reference["image"]
    )
    custom_settings["scail2_source_scene_mask_path"] = (
        scene_reference["mask"]
    )
    params["edit_recast_source_scene_reference"] = scene_reference["image"]
    params["edit_recast_source_scene_mask"] = scene_reference["mask"]
    params["edit_recast_source_scene_hidden_fraction"] = scene_reference[
        "hidden_fraction"
    ]
    params["edit_recast_reference_canvas"] = list(output_size)
    params["edit_recast_source_scene_conditioning"] = (
        "stable_official_reference"
    )
    return scene_reference

def _compose_recast_group_reference_frame(
    source_frame, semantic_mask, target_reference_layers, selected_count,
    neutral_value=127,
):
    """Build one native multi-person SCAIL reference on a neutral canvas.

    The selected shared frame supplies only the tracked bystanders. Each selected
    source target is replaced by the corresponding prepared replacement
    cutout, positioned inside that target's shared-frame slot. The returned
    semantic mask therefore describes every visible conditioned person in one
    ordinary multi-color reference instead of making bystanders compete as a
    separate, target-free multi-reference image.
    """
    import numpy as np
    from PIL import Image as _PILImage

    source = np.asarray(source_frame, dtype=np.uint8)
    group_mask = np.asarray(semantic_mask, dtype=np.uint8)
    if (
        source.ndim != 3
        or source.shape[-1] != 3
        or group_mask.shape != source.shape
    ):
        raise ValueError(
            "Recast group reference needs matching H/W/RGB source and mask "
            f"arrays; got source={source.shape}, mask={group_mask.shape}."
        )
    layers = list(target_reference_layers or [])
    if not layers:
        raise ValueError("Recast group reference needs a prepared target layer.")
    try:
        neutral = int(neutral_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Recast group neutral value must be an integer.") from exc
    if not 0 <= neutral <= 255:
        raise ValueError("Recast group neutral value must be between 0 and 255.")

    normalized_layers = []
    canvas_width = canvas_height = None
    for layer_index, layer in enumerate(layers):
        if not isinstance(layer, (list, tuple)) or len(layer) != 2:
            raise ValueError(
                "Each Recast group target layer must contain an RGB image and "
                "its semantic mask."
            )
        layer_rgb = np.asarray(layer[0], dtype=np.uint8)
        layer_mask = np.asarray(layer[1], dtype=np.uint8)
        if (
            layer_rgb.ndim != 3
            or layer_rgb.shape[-1] != 3
            or layer_mask.shape != layer_rgb.shape
        ):
            raise ValueError(
                f"Recast group target layer {layer_index + 1} has mismatched "
                f"RGB/mask dimensions: image={layer_rgb.shape}, "
                f"mask={layer_mask.shape}."
            )
        if canvas_width is None:
            canvas_height, canvas_width = layer_rgb.shape[:2]
        elif layer_rgb.shape[:2] != (canvas_height, canvas_width):
            layer_rgb = np.asarray(
                _PILImage.fromarray(layer_rgb).resize(
                    (canvas_width, canvas_height),
                    resample=_PILImage.Resampling.LANCZOS,
                ),
                dtype=np.uint8,
            )
            layer_mask = np.asarray(
                _PILImage.fromarray(layer_mask).resize(
                    (canvas_width, canvas_height),
                    resample=_PILImage.Resampling.NEAREST,
                ),
                dtype=np.uint8,
            )
        normalized_layers.append((layer_rgb, layer_mask))

    if source.shape[:2] != (canvas_height, canvas_width):
        source = np.asarray(
            _PILImage.fromarray(source).resize(
                (canvas_width, canvas_height),
                resample=_PILImage.Resampling.LANCZOS,
            ),
            dtype=np.uint8,
        )
        group_mask = np.asarray(
            _PILImage.fromarray(group_mask).resize(
                (canvas_width, canvas_height),
                resample=_PILImage.Resampling.NEAREST,
            ),
            dtype=np.uint8,
        )

    requested_count = _normalize_recast_person_count(selected_count)
    composite = np.full_like(source, neutral, dtype=np.uint8)
    composite_mask = np.zeros_like(group_mask, dtype=np.uint8)

    # Retain source pixels only for the explicitly color-mapped bystanders.
    # The old selected subject and the surrounding scene never enter this RGB
    # reference, so neither can compete with the requested replacement.
    for color in _RECAST_MASK_COLORS[requested_count:]:
        color_array = np.asarray(color, dtype=np.uint8)
        region = np.all(group_mask == color_array, axis=-1)
        if bool(region.any()):
            composite[region] = source[region]
            composite_mask[region] = color_array

    for target_index, color in enumerate(
        _RECAST_MASK_COLORS[:requested_count],
    ):
        color_array = np.asarray(color, dtype=np.uint8)
        target_region = np.all(group_mask == color_array, axis=-1)
        target_ys, target_xs = np.nonzero(target_region)
        if len(target_xs) == 0:
            raise ValueError(
                "Could not place replacement target "
                f"{target_index + 1}: its first-frame color is missing."
            )

        # Legacy "replace N people" reuses one identity for every selected
        # slot; explicit character mappings provide one primary layer each.
        layer_rgb, layer_mask = normalized_layers[
            min(target_index, len(normalized_layers) - 1)
        ]
        subject = np.any(layer_mask > 30, axis=-1)
        subject_ys, subject_xs = np.nonzero(subject)
        if len(subject_xs) == 0:
            raise ValueError(
                f"Prepared replacement target {target_index + 1} is empty."
            )
        sx0, sx1 = int(subject_xs.min()), int(subject_xs.max()) + 1
        sy0, sy1 = int(subject_ys.min()), int(subject_ys.max()) + 1
        subject_rgb = layer_rgb[sy0:sy1, sx0:sx1]
        subject_alpha = (
            subject[sy0:sy1, sx0:sx1].astype(np.uint8) * 255
        )

        tx0, tx1 = int(target_xs.min()), int(target_xs.max()) + 1
        ty0, ty1 = int(target_ys.min()), int(target_ys.max()) + 1
        target_width, target_height = max(1, tx1 - tx0), max(1, ty1 - ty0)
        scale = min(
            target_width / max(1, subject_rgb.shape[1]),
            target_height / max(1, subject_rgb.shape[0]),
        )
        placed_width = max(
            1,
            min(canvas_width, int(round(subject_rgb.shape[1] * scale))),
        )
        placed_height = max(
            1,
            min(canvas_height, int(round(subject_rgb.shape[0] * scale))),
        )
        placed_rgb = np.asarray(
            _PILImage.fromarray(subject_rgb).resize(
                (placed_width, placed_height),
                resample=_PILImage.Resampling.LANCZOS,
            ),
            dtype=np.uint8,
        )
        placed_alpha = np.asarray(
            _PILImage.fromarray(subject_alpha).resize(
                (placed_width, placed_height),
                resample=_PILImage.Resampling.BILINEAR,
            ),
            dtype=np.float32,
        ) / 255.0

        left = int(round((tx0 + tx1 - placed_width) / 2.0))
        top = ty1 - placed_height
        left = max(0, min(left, canvas_width - placed_width))
        top = max(0, min(top, canvas_height - placed_height))
        right, bottom = left + placed_width, top + placed_height

        alpha = placed_alpha[..., None]
        destination = composite[top:bottom, left:right].astype(np.float32)
        composite[top:bottom, left:right] = np.rint(
            placed_rgb.astype(np.float32) * alpha
            + destination * (1.0 - alpha)
        ).clip(0, 255).astype(np.uint8)
        visible = placed_alpha > 0.05
        mask_destination = composite_mask[top:bottom, left:right]
        mask_destination[visible] = color_array

    return composite, composite_mask

def _compose_recast_cast_reference_frame(
    target_reference_layers, selected_count, canvas_size, neutral_value=127,
):
    """Arrange independently prepared characters in one native SCAIL cast.

    SCAIL-2's trained multi-person path expects all mapped identities and their
    semantic colors in one primary reference.  A timeline may never show every
    requested character at once, so this neutral cast sheet is the fallback
    when no shared source frame can provide natural target positions.
    """
    import numpy as np
    from PIL import Image as _PILImage

    layers = list(target_reference_layers or [])
    requested_count = _normalize_recast_person_count(selected_count)
    if len(layers) < requested_count:
        raise ValueError(
            "Recast cast reference needs one prepared target layer per "
            f"character ({len(layers)}/{requested_count})."
        )
    try:
        canvas_width, canvas_height = (
            int(canvas_size[0]),
            int(canvas_size[1]),
        )
        neutral = int(neutral_value)
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError(
            "Recast cast reference needs a valid canvas and neutral value."
        ) from exc
    if min(canvas_width, canvas_height) <= 0:
        raise ValueError("Recast cast reference canvas must be positive.")
    if not 0 <= neutral <= 255:
        raise ValueError(
            "Recast cast reference neutral value must be between 0 and 255."
        )

    composite = np.full(
        (canvas_height, canvas_width, 3),
        neutral,
        dtype=np.uint8,
    )
    composite_mask = np.zeros_like(composite)
    outer_margin = max(4, int(round(min(canvas_width, canvas_height) * 0.025)))
    gap = max(4, int(round(canvas_width * 0.012)))
    available_width = max(
        requested_count,
        canvas_width - 2 * outer_margin - gap * (requested_count - 1),
    )
    cell_width = float(available_width) / float(requested_count)
    maximum_height = max(1, canvas_height - 2 * outer_margin)

    for target_index in range(requested_count):
        layer = layers[target_index]
        if not isinstance(layer, (list, tuple)) or len(layer) != 2:
            raise ValueError(
                "Each Recast cast target layer must contain an RGB image and "
                "its semantic mask."
            )
        layer_rgb = np.asarray(layer[0], dtype=np.uint8)
        layer_mask = np.asarray(layer[1], dtype=np.uint8)
        if (
            layer_rgb.ndim != 3
            or layer_rgb.shape[-1] != 3
            or layer_mask.shape != layer_rgb.shape
        ):
            raise ValueError(
                f"Recast cast target layer {target_index + 1} has mismatched "
                f"RGB/mask dimensions: image={layer_rgb.shape}, "
                f"mask={layer_mask.shape}."
            )
        color_array = np.asarray(
            _RECAST_MASK_COLORS[target_index],
            dtype=np.uint8,
        )
        subject = np.all(layer_mask == color_array, axis=-1)
        if not bool(subject.any()):
            # Prepared PNG masks are normally exact, but tolerate masks from
            # older saved jobs whose semantic color was not persisted.
            subject = np.any(layer_mask > 30, axis=-1)
        subject_ys, subject_xs = np.nonzero(subject)
        if len(subject_xs) == 0:
            raise ValueError(
                f"Prepared replacement target {target_index + 1} is empty."
            )
        sx0, sx1 = int(subject_xs.min()), int(subject_xs.max()) + 1
        sy0, sy1 = int(subject_ys.min()), int(subject_ys.max()) + 1
        subject_rgb = layer_rgb[sy0:sy1, sx0:sx1]
        subject_alpha = (
            subject[sy0:sy1, sx0:sx1].astype(np.uint8) * 255
        )

        maximum_width = max(1, int(round(cell_width * 0.90)))
        scale = min(
            maximum_width / max(1, subject_rgb.shape[1]),
            maximum_height / max(1, subject_rgb.shape[0]),
        )
        placed_width = max(1, int(round(subject_rgb.shape[1] * scale)))
        placed_height = max(1, int(round(subject_rgb.shape[0] * scale)))
        placed_rgb = np.asarray(
            _PILImage.fromarray(subject_rgb).resize(
                (placed_width, placed_height),
                resample=_PILImage.Resampling.LANCZOS,
            ),
            dtype=np.uint8,
        )
        placed_alpha = np.asarray(
            _PILImage.fromarray(subject_alpha).resize(
                (placed_width, placed_height),
                resample=_PILImage.Resampling.BILINEAR,
            ),
            dtype=np.float32,
        ) / 255.0

        cell_left = outer_margin + target_index * (cell_width + gap)
        left = int(round(cell_left + (cell_width - placed_width) / 2.0))
        top = int(round((canvas_height - placed_height) / 2.0))
        left = max(0, min(left, canvas_width - placed_width))
        top = max(0, min(top, canvas_height - placed_height))
        right, bottom = left + placed_width, top + placed_height

        alpha = placed_alpha[..., None]
        destination = composite[top:bottom, left:right].astype(np.float32)
        composite[top:bottom, left:right] = np.rint(
            placed_rgb.astype(np.float32) * alpha
            + destination * (1.0 - alpha)
        ).clip(0, 255).astype(np.uint8)
        visible = placed_alpha > 0.05
        mask_destination = composite_mask[top:bottom, left:right]
        mask_destination[visible] = color_array

    return composite, composite_mask

def _build_recast_target_group_reference(
    prepared_refs, output_dir, job_id, selected_count, *,
    shared_source_frame=None, shared_semantic_mask=None,
):
    """Persist one primary multi-character reference for SCAIL-2 Recast."""
    import numpy as np
    from PIL import Image as _PILImage

    target_layers = []
    for item in prepared_refs.get("primary_target_refs", []):
        if (
            not isinstance(item, dict)
            or not item.get("image")
            or not item.get("mask")
        ):
            raise ValueError(
                "Multi-character Recast needs prepared target image/mask "
                "pairs."
            )
        with _PILImage.open(item["image"]) as target_image:
            target_rgb = np.asarray(
                target_image.convert("RGB"),
                dtype=np.uint8,
            )
        with _PILImage.open(item["mask"]) as target_mask:
            target_semantic = np.asarray(
                target_mask.convert("RGB"),
                dtype=np.uint8,
            )
        target_layers.append((target_rgb, target_semantic))

    mode = "cast_sheet"
    if shared_source_frame is not None and shared_semantic_mask is not None:
        try:
            reference_frame, reference_mask = (
                _compose_recast_group_reference_frame(
                    shared_source_frame,
                    shared_semantic_mask,
                    target_layers,
                    selected_count,
                )
            )
        except ValueError as shared_error:
            print(
                "[Recast] Shared-frame cast layout was unavailable; "
                f"using a neutral cast sheet: {shared_error}"
            )
            reference_frame, reference_mask = (
                _compose_recast_cast_reference_frame(
                    target_layers,
                    selected_count,
                    prepared_refs["reference_canvas"],
                )
            )
        else:
            mode = "shared_timeline_frame"
    else:
        reference_frame, reference_mask = (
            _compose_recast_cast_reference_frame(
                target_layers,
                selected_count,
                prepared_refs["reference_canvas"],
            )
        )

    os.makedirs(output_dir, exist_ok=True)
    reference_path = os.path.join(
        output_dir,
        f"recast_cast_ref_{job_id}.png",
    )
    reference_mask_path = os.path.join(
        output_dir,
        f"recast_cast_mask_{job_id}.png",
    )
    _PILImage.fromarray(reference_frame).save(reference_path)
    _PILImage.fromarray(reference_mask).save(reference_mask_path)
    return {
        "image": reference_path,
        "mask": reference_mask_path,
        "mode": mode,
        "character_count": _normalize_recast_person_count(selected_count),
    }

def _compose_recast_native_people_masks(
    target_mask_frames, all_people_masks, selected_count,
    reference_frame_index=0,
):
    """Build native SCAIL-2 masks for targets plus visible bystanders.

    The user's selected targets retain the first SCAIL colors. Other people
    visible in the selected shared frame are assigned the remaining colors (up
    to SCAIL-2's five-person limit). The driving mask carries all of those
    correspondences, while the shared-frame reference mask identifies every
    target and bystander for one ordinary multi-person reference.
    """
    import numpy as np

    targets = np.asarray(target_mask_frames, dtype=np.uint8)
    people = np.asarray(all_people_masks, dtype=np.uint8)
    if targets.shape != people.shape or targets.ndim != 4 or targets.shape[-1] != 3:
        raise ValueError(
            "Native Recast people masks must have matching T/H/W/RGB dimensions; "
            f"got targets={targets.shape}, people={people.shape}."
        )
    try:
        reference_index = int(reference_frame_index)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Native Recast reference frame index must be an integer."
        ) from exc
    if not 0 <= reference_index < len(targets):
        raise ValueError(
            "Native Recast reference frame index is outside the mask timeline."
        )

    requested_count = _normalize_recast_person_count(selected_count)
    target_regions = []
    for color in _RECAST_MASK_COLORS[:requested_count]:
        region = _recast_color_region(targets, color)
        if bool(region.any()):
            target_regions.append(region)
    if len(target_regions) != requested_count:
        raise ValueError(
            "Could not recover every selected target from the tracked Recast mask "
            f"({len(target_regions)}/{requested_count})."
        )

    candidates = []
    for color_index, color in enumerate(_RECAST_PROTECTION_COLORS):
        region = np.all(people == np.asarray(color, dtype=np.uint8), axis=-1)
        area = int(region.sum())
        reference_frame_area = int(region[reference_index].sum())
        if area and reference_frame_area:
            candidates.append({
                "source_color_index": color_index,
                "region": region,
                "area": area,
                "reference_frame_area": reference_frame_area,
            })
    if not candidates:
        raise ValueError("SAM3 found no people to map for native Recast preservation.")

    # Match the broad "person" tracks back to the user's more specific target
    # tracks. Anything matched here must never be reused as a bystander ref.
    pairings = []
    for target_index, target_region in enumerate(target_regions):
        target_area = max(1, int(target_region.sum()))
        for candidate_index, candidate in enumerate(candidates):
            overlap = int(np.logical_and(target_region, candidate["region"]).sum())
            score = overlap / np.sqrt(float(target_area * candidate["area"]))
            pairings.append((score, overlap, target_index, candidate_index))
    pairings.sort(key=lambda item: (item[0], item[1]), reverse=True)

    used_targets = set()
    target_candidate_indices = set()
    for score, overlap, target_index, candidate_index in pairings:
        if target_index in used_targets or candidate_index in target_candidate_indices:
            continue
        if overlap <= 0 or score < 0.02:
            continue
        used_targets.add(target_index)
        target_candidate_indices.add(candidate_index)
        if len(used_targets) == len(target_regions):
            break
    if len(used_targets) != len(target_regions):
        raise ValueError(
            "Could not match every selected target to the source person tracks "
            f"({len(used_targets)}/{len(target_regions)})."
        )

    target_union = np.logical_or.reduce(target_regions)
    bystanders = []
    for candidate_index, candidate in enumerate(candidates):
        if candidate_index in target_candidate_indices:
            continue
        overlap = int(np.logical_and(target_union, candidate["region"]).sum())
        overlap_fraction = overlap / max(
            1, min(candidate["area"], int(target_union.sum())),
        )
        # Avoid treating a fragmented duplicate of a target track as another
        # person when SAM's broad prompt splits loose clothing or an occlusion.
        # A high threshold deliberately retains real dancers who pass behind
        # or partly overlap the selected subject.
        if overlap_fraction > 0.65:
            continue
        bystanders.append(candidate)
    bystanders.sort(
        key=lambda candidate: (
            candidate["area"],
            candidate["reference_frame_area"],
        ),
        reverse=True,
    )
    capacity = max(0, len(_RECAST_MASK_COLORS) - len(target_regions))
    bystanders = bystanders[:capacity]

    driving_mask = np.full_like(targets, 255, dtype=np.uint8)
    group_ref_mask = np.zeros(targets.shape[1:], dtype=np.uint8)
    assignments = []
    for offset, candidate in enumerate(bystanders):
        assigned_index = len(target_regions) + offset
        assigned_color = _RECAST_MASK_COLORS[assigned_index]
        driving_mask[candidate["region"]] = np.asarray(assigned_color, dtype=np.uint8)
        group_ref_mask[candidate["region"][reference_index]] = np.asarray(
            assigned_color, dtype=np.uint8,
        )
        assignments.append((
            candidate["source_color_index"],
            assigned_index,
            candidate["area"],
        ))

    # The explicit target mask wins wherever people overlap or cross.
    for target_index, target_region in enumerate(target_regions):
        driving_mask[target_region] = np.asarray(
            _RECAST_MASK_COLORS[target_index], dtype=np.uint8,
        )
    # A broad bystander track can overlap the selected subject in the shared
    # frame. The selected target wins there, keeping one unambiguous color per
    # pixel in the native group reference.
    group_ref_mask[target_union[reference_index]] = 0
    for target_index, target_region in enumerate(target_regions):
        group_ref_mask[target_region[reference_index]] = np.asarray(
            _RECAST_MASK_COLORS[target_index], dtype=np.uint8,
        )
    return (
        driving_mask,
        group_ref_mask,
        len(target_regions) + len(bystanders),
        assignments,
    )

def _build_recast_native_people_conditioning(
    source_video, target_mask_video, selected_count, output_dir, job_id,
    target_references=None, progress_callback=None, reference_frame_index=0,
):
    """Track source bystanders and write one SCAIL-native group reference."""
    import cv2
    import numpy as np
    from PIL import Image as _PILImage
    from shared import magic_mask

    source_path, source_frames, fps = magic_mask.prepare_video_mask_input(source_video)
    _, target_masks, _ = magic_mask.prepare_video_mask_input(target_mask_video)
    frame_count, height, width = source_frames.shape[:3]
    if len(target_masks) != frame_count:
        indices = np.rint(
            np.linspace(0, len(target_masks) - 1, frame_count),
        ).astype(np.int64)
        target_masks = target_masks[indices]
    if target_masks.shape[1:3] != (height, width):
        target_masks = np.stack([
            cv2.resize(frame, (width, height), interpolation=cv2.INTER_NEAREST)
            for frame in target_masks
        ])

    all_people_masks = magic_mask.generate_keyword_masks(
        source_frames,
        "person",
        no_hole=True,
        colorize_objects=True,
        color_palette=_RECAST_PROTECTION_COLORS,
        max_colored_objects=len(_RECAST_PROTECTION_COLORS),
        progress_callback=progress_callback,
    )
    driving_mask, group_ref_mask, conditioning_count, assignments = (
        _compose_recast_native_people_masks(
            target_masks,
            all_people_masks,
            selected_count,
            reference_frame_index=reference_frame_index,
        )
    )
    if conditioning_count <= _normalize_recast_person_count(selected_count):
        return {
            "video_mask": target_mask_video,
            "reference_image": None,
            "reference_mask": None,
            "conditioning_count": conditioning_count,
            "assignments": assignments,
        }

    os.makedirs(output_dir, exist_ok=True)
    driving_mask_path = magic_mask.save_mask_video(
        source_path,
        driving_mask,
        fps,
        ["recast people"],
        output_dir=output_dir,
    )
    reference_path = os.path.join(
        output_dir, f"recast_group_ref_{job_id}.png",
    )
    reference_mask_path = os.path.join(
        output_dir, f"recast_group_mask_{job_id}.png",
    )
    target_layers = []
    for item in target_references or []:
        if not isinstance(item, dict) or not item.get("image") or not item.get("mask"):
            raise ValueError(
                "Native Recast preservation needs prepared target image/mask pairs."
            )
        with _PILImage.open(item["image"]) as target_image:
            target_rgb = np.asarray(target_image.convert("RGB"), dtype=np.uint8)
        with _PILImage.open(item["mask"]) as target_mask:
            target_semantic = np.asarray(
                target_mask.convert("RGB"), dtype=np.uint8,
            )
        target_layers.append((target_rgb, target_semantic))
    reference_frame, reference_mask = _compose_recast_group_reference_frame(
        source_frames[int(reference_frame_index)],
        group_ref_mask,
        target_layers,
        selected_count,
    )
    _PILImage.fromarray(reference_frame).save(reference_path)
    _PILImage.fromarray(reference_mask).save(reference_mask_path)
    return {
        "video_mask": driving_mask_path,
        "reference_image": reference_path,
        "reference_mask": reference_mask_path,
        "conditioning_count": conditioning_count,
        "assignments": assignments,
    }

def _recast_appearance_descriptor(source_frame, subject_region):
    """Build a compact clothing/appearance descriptor for shot reacquisition."""
    import cv2
    import numpy as np

    frame = np.asarray(source_frame, dtype=np.uint8)
    region = np.asarray(subject_region).astype(bool)
    if (
        frame.ndim != 3
        or frame.shape[-1] != 3
        or region.shape != frame.shape[:2]
        or not bool(region.any())
    ):
        return None

    # Erode away SAM's boundary pixels so the descriptor represents the
    # person rather than the changing background around their silhouette.
    edge = max(3, int(round(min(region.shape) * 0.012)))
    if edge % 2 == 0:
        edge += 1
    core = cv2.erode(
        region.astype(np.uint8),
        np.ones((edge, edge), dtype=np.uint8),
        iterations=1,
    ).astype(bool)
    if int(core.sum()) < 100:
        core = region
    mask = core.astype(np.uint8)

    hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
    lab = cv2.cvtColor(frame, cv2.COLOR_RGB2LAB)
    hue_saturation = cv2.calcHist(
        [hsv],
        [0, 1],
        mask,
        [24, 8],
        [0, 180, 0, 256],
    ).reshape(-1)
    perceptual_color = cv2.calcHist(
        [lab],
        [0, 1, 2],
        mask,
        [8, 8, 8],
        [0, 256, 0, 256, 0, 256],
    ).reshape(-1)
    hue_saturation /= max(1.0, float(hue_saturation.sum()))
    perceptual_color /= max(1.0, float(perceptual_color.sum()))
    descriptor = np.concatenate(
        [hue_saturation, perceptual_color],
    ).astype(np.float32, copy=False)
    norm = float(np.linalg.norm(descriptor))
    return descriptor / norm if norm > 1e-8 else None

def _build_recast_mapping_appearance_prototypes(
    source_frames, mapping_masks, shot_ranges, max_per_mapping=6,
):
    """Collect high-confidence per-shot source appearances for each card."""
    import numpy as np

    frames = np.asarray(source_frames, dtype=np.uint8)
    prototypes = []
    for raw_mask in mapping_masks or []:
        region = _recast_mask_region(raw_mask)
        candidates = []
        for raw_start, raw_end in shot_ranges or [(0, len(frames))]:
            start = max(0, min(len(frames), int(raw_start)))
            end = max(start, min(len(frames), int(raw_end)))
            if end <= start:
                continue
            areas = (
                region[start:end]
                .reshape(end - start, -1)
                .sum(axis=1)
            )
            if not int(areas.max(initial=0)):
                continue
            frame_index = start + int(np.argmax(areas))
            descriptor = _recast_appearance_descriptor(
                frames[frame_index],
                region[frame_index],
            )
            if descriptor is not None:
                candidates.append((
                    int(areas[frame_index - start]),
                    descriptor,
                ))
        candidates.sort(key=lambda item: item[0], reverse=True)
        prototypes.append([
            descriptor
            for _area, descriptor in candidates[:max_per_mapping]
        ])
    return prototypes

def _fit_recast_reference_layers(
    rgb, semantic_rgb, width, height, *, aligned=False,
    crop_to_subject=True, canvas_color=(127, 127, 127),
):
    """Apply the exact shared image/mask transform used by Recast."""
    import numpy as np
    from PIL import Image as _PILImage

    rgb_image = _PILImage.fromarray(np.asarray(rgb, dtype=np.uint8))
    mask_image = _PILImage.fromarray(np.asarray(semantic_rgb, dtype=np.uint8))
    if aligned:
        scale = max(width / rgb_image.width, height / rgb_image.height)
        resized_size = (
            max(width, int(round(rgb_image.width * scale))),
            max(height, int(round(rgb_image.height * scale))),
        )
        rgb_image = rgb_image.resize(
            resized_size, resample=_PILImage.Resampling.LANCZOS,
        )
        mask_image = mask_image.resize(
            resized_size, resample=_PILImage.Resampling.NEAREST,
        )
        left = (resized_size[0] - width) // 2
        top = (resized_size[1] - height) // 2
        box = (left, top, left + width, top + height)
        return rgb_image.crop(box), mask_image.crop(box)

    subject = np.any(np.asarray(semantic_rgb, dtype=np.uint8) > 30, axis=-1)
    crop_box = (
        _recast_subject_crop_box(subject)
        if crop_to_subject
        else (0, 0, rgb_image.width, rgb_image.height)
    )
    rgb_image = rgb_image.crop(crop_box)
    mask_image = mask_image.crop(crop_box)
    scale = min(width / rgb_image.width, height / rgb_image.height)
    resized_size = (
        max(1, min(width, int(round(rgb_image.width * scale)))),
        max(1, min(height, int(round(rgb_image.height * scale)))),
    )
    rgb_image = rgb_image.resize(
        resized_size, resample=_PILImage.Resampling.LANCZOS,
    )
    mask_image = mask_image.resize(
        resized_size, resample=_PILImage.Resampling.NEAREST,
    )
    rgb_canvas = _PILImage.new(
        "RGB",
        (width, height),
        tuple(int(value) for value in canvas_color),
    )
    mask_canvas = _PILImage.new("RGB", (width, height), (0, 0, 0))
    offset = ((width - resized_size[0]) // 2, (height - resized_size[1]) // 2)
    rgb_canvas.paste(rgb_image, offset)
    mask_canvas.paste(mask_image, offset)
    return rgb_canvas, mask_canvas

# --- helpers that moved with this slice ---
# Imported last: these modules import this one back, and every name they take
# from here is defined above by then.
from services.recast_masks import (
    _RECAST_MASK_COLORS,
    _RECAST_PROTECTION_COLORS,
    _recast_color_region,
    _recast_mask_region,
)
from services.recast_reference_prepare import (
    _normalize_recast_person_count,
    _recast_subject_crop_box,
)
