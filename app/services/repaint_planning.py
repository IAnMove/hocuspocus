"""Repaint planning.

Region normalisation, the aspect check, the edited frame, semantic and
reference conditioning, the shot prompt and the shot manifest. The function
bodies are the ones that used to live in ``_launch_runtime``. Launch hands
this module the recast mask colours and the recast helpers once, through
:func:`bind`. The recast helpers are leaving launch in other PRs, so launch
passes forwarders that call its own names when a function runs.
"""
import os
import uuid

# Bound by bind(); None until the full server binds them.
_RECAST_MASK_COLORS = None
_build_recast_source_scene_reference = None
_compose_recast_cast_reference_frame = None
_compose_recast_character_masks = None
_compose_recast_group_reference_frame = None
_detect_recast_shot_ranges = None
_plan_recast_shot_segments = None
_quantize_recast_shot_frame_count = None
_recolor_recast_reference_mask = None
_remap_recast_shot_mask = None
_resample_recast_tracking_timeline = None
_resize_recast_shot_frames = None
_save_recast_reference_pair = None
_summarize_recast_mapping_mask = None
_write_recast_shot_video = None


def bind(
    *, recast_mask_colors, build_recast_source_scene_reference, compose_recast_cast_reference_frame,
    compose_recast_character_masks, compose_recast_group_reference_frame, detect_recast_shot_ranges,
    plan_recast_shot_segments, quantize_recast_shot_frame_count, recolor_recast_reference_mask,
    remap_recast_shot_mask, resample_recast_tracking_timeline, resize_recast_shot_frames,
    save_recast_reference_pair, summarize_recast_mapping_mask, write_recast_shot_video,
):
    """Take the launch objects this module reads. Launch calls this once, after it defines them."""
    globals().update(
        _RECAST_MASK_COLORS=recast_mask_colors,
        _build_recast_source_scene_reference=build_recast_source_scene_reference,
        _compose_recast_cast_reference_frame=compose_recast_cast_reference_frame,
        _compose_recast_character_masks=compose_recast_character_masks,
        _compose_recast_group_reference_frame=compose_recast_group_reference_frame,
        _detect_recast_shot_ranges=detect_recast_shot_ranges,
        _plan_recast_shot_segments=plan_recast_shot_segments,
        _quantize_recast_shot_frame_count=quantize_recast_shot_frame_count,
        _recolor_recast_reference_mask=recolor_recast_reference_mask,
        _remap_recast_shot_mask=remap_recast_shot_mask,
        _resample_recast_tracking_timeline=resample_recast_tracking_timeline,
        _resize_recast_shot_frames=resize_recast_shot_frames,
        _save_recast_reference_pair=save_recast_reference_pair,
        _summarize_recast_mapping_mask=summarize_recast_mapping_mask,
        _write_recast_shot_video=write_recast_shot_video,
    )


def _normalize_repaint_region_mappings(raw_mappings):
    """Validate optional source-video → edited-frame semantic mappings."""
    if raw_mappings in (None, []):
        return []
    if not isinstance(raw_mappings, list):
        raise ValueError("Repaint region_mappings must be a list.")
    if len(raw_mappings) > len(_RECAST_MASK_COLORS):
        raise ValueError("SCAIL-2 supports at most five Repaint regions.")
    mappings = []
    for index, raw in enumerate(raw_mappings):
        if not isinstance(raw, dict):
            raise ValueError(f"Repaint region {index + 1} is invalid.")
        source = str(
            raw.get("source")
            or raw.get("source_target")
            or raw.get("source_description")
            or ""
        ).strip()
        target = str(
            raw.get("target")
            or raw.get("target_description")
            or raw.get("edited_target")
            or ""
        ).strip()
        if not source or not target:
            raise ValueError(
                f"Repaint region {index + 1} needs both a source-video "
                "description and an edited-frame description."
            )
        mappings.append({
            "id": str(raw.get("id") or f"repaint-{index + 1}"),
            "source": source,
            "target": target,
        })
    return mappings

def _repaint_resolution_for_aspect(
    width, height, pixel_budget=848 * 480, block_size=16,
):
    """Return a SCAIL-sized canvas while preserving the source aspect."""
    import math

    source_width = int(width)
    source_height = int(height)
    block = max(1, int(block_size))
    budget = max(block * block, int(pixel_budget))
    if source_width <= 0 or source_height <= 0:
        raise ValueError("Repaint source dimensions must be positive.")
    ratio = float(source_width) / float(source_height)
    ideal_width = math.sqrt(float(budget) * ratio)
    ideal_height = math.sqrt(float(budget) / ratio)
    output_width = max(block, int(round(ideal_width / block)) * block)
    output_height = max(block, int(round(ideal_height / block)) * block)
    return output_width, output_height

def _validate_repaint_target_aspect(
    source_width, source_height, target_width, target_height,
    tolerance=0.025,
):
    """Reject edited frames that would require a destructive crop."""
    values = [
        int(source_width), int(source_height),
        int(target_width), int(target_height),
    ]
    if any(value <= 0 for value in values):
        raise ValueError("Repaint source and edited-frame dimensions must be positive.")
    source_ratio = float(values[0]) / float(values[1])
    target_ratio = float(values[2]) / float(values[3])
    difference = abs(target_ratio - source_ratio) / source_ratio
    if difference > float(tolerance):
        raise ValueError(
            "The edited first frame must keep the source video's aspect ratio "
            f"({values[0]}×{values[1]} source vs "
            f"{values[2]}×{values[3]} edited frame). "
            "Edit the extracted frame in Image Mode or resize without cropping."
        )
    return difference

def _prepare_repaint_target_frame(
    target_path, source_width, source_height, output_width, output_height,
    output_dir, job_id,
):
    """Orient, validate, and resize the edited frame without cropping."""
    from PIL import Image as _PILImage
    from PIL import ImageOps as _PILImageOps

    with _PILImage.open(target_path) as image:
        target = _PILImageOps.exif_transpose(image).convert("RGB")
        target_width, target_height = target.size
        _validate_repaint_target_aspect(
            source_width,
            source_height,
            target_width,
            target_height,
        )
        target = target.resize(
            (int(output_width), int(output_height)),
            resample=_PILImage.Resampling.LANCZOS,
        )
        os.makedirs(output_dir, exist_ok=True)
        prepared_path = os.path.join(
            output_dir,
            f"repaint_target_{job_id}.png",
        )
        target.save(prepared_path)
    return prepared_path, (target_width, target_height)

def _repaint_preview_data_uri(frame, semantic_mask, background="black"):
    """Blend a semantic mask over one RGB frame and return a JPEG data URI."""
    import base64
    import io as _io
    import numpy as np
    from PIL import Image as _PILImage

    rgb = np.asarray(frame, dtype=np.uint8)
    mask = np.asarray(semantic_mask, dtype=np.uint8)
    if rgb.shape != mask.shape:
        raise ValueError(
            f"Repaint preview frame/mask mismatch: {rgb.shape} vs {mask.shape}."
        )
    selected = (
        ~np.all(mask > 225, axis=-1)
        if background == "white"
        else np.any(mask > 30, axis=-1)
    )
    overlay = rgb.copy()
    if bool(selected.any()):
        overlay[selected] = (
            overlay[selected].astype(np.float32) * 0.45
            + mask[selected].astype(np.float32) * 0.55
        ).astype(np.uint8)
    buffer = _io.BytesIO()
    _PILImage.fromarray(overlay).save(buffer, format="JPEG", quality=85)
    return (
        "data:image/jpeg;base64,"
        + base64.b64encode(buffer.getvalue()).decode()
    )

def _build_repaint_semantic_conditioning(
    source_video, target_frame_path, mappings, output_dir,
    progress_callback=None, abort_callback=None,
):
    """Track mapped regions independently inside every detected camera shot."""
    import numpy as np
    from PIL import Image as _PILImage
    from shared import magic_mask

    source_path, source_frames, fps = magic_mask.prepare_video_mask_input(
        source_video,
    )
    shot_ranges = _detect_recast_shot_ranges(source_frames)
    if len(shot_ranges) > 1:
        print(
            "[Repaint] Detected "
            f"{len(shot_ranges)} camera shots; SAM3 will reacquire each "
            "mapped region after every cut."
        )
    with _PILImage.open(target_frame_path) as target_image:
        target_frame = np.asarray(target_image.convert("RGB"), dtype=np.uint8)

    source_masks = []
    target_masks = []
    mapping_summaries = []
    total = len(mappings)
    for index, mapping in enumerate(mappings):
        if abort_callback is not None:
            abort_callback()

        def _source_progress(done, frame_total, mapping_index=index):
            if abort_callback is not None:
                abort_callback()
            if progress_callback is not None:
                progress_callback(
                    mapping_index,
                    total,
                    done,
                    frame_total,
                )

        color = _RECAST_MASK_COLORS[index]
        source_mask = magic_mask.generate_keyword_masks(
            source_frames,
            mapping["source"],
            no_hole=True,
            colorize_objects=True,
            color_palette=[color],
            max_colored_objects=1,
            progress_callback=_source_progress,
            tracking_segments=shot_ranges,
        )
        summary = _summarize_recast_mapping_mask(source_mask, fps)
        if summary is None:
            raise ValueError(
                f"Repaint region {index + 1} found no "
                f"'{mapping['source']}' anywhere in the selected video."
            )
        target_mask = magic_mask.generate_keyword_masks(
            target_frame[None],
            mapping["target"],
            no_hole=True,
            colorize_objects=True,
            color_palette=[color],
            max_colored_objects=1,
        )[0]
        if not bool(target_mask.any()):
            raise ValueError(
                f"Repaint region {index + 1} found no "
                f"'{mapping['target']}' in the edited first frame."
            )
        source_masks.append(source_mask)
        target_masks.append(target_mask)
        mapping_summaries.append(summary)

    driving_mask, _ = _compose_recast_character_masks(
        source_masks,
        _RECAST_MASK_COLORS[:total],
        background_color=(0, 0, 0),
    )
    reference_mask, _ = _compose_recast_character_masks(
        target_masks,
        _RECAST_MASK_COLORS[:total],
        background_color=(255, 255, 255),
    )
    video_mask_path = magic_mask.save_mask_video(
        source_path,
        driving_mask,
        fps,
        [mapping["source"] for mapping in mappings],
        output_dir=output_dir,
        abort_callback=abort_callback,
        background_color=(0, 0, 0),
    )
    os.makedirs(output_dir, exist_ok=True)
    reference_mask_path = os.path.join(
        output_dir,
        "repaint_reference_mask_"
        + uuid.uuid4().hex[:8]
        + ".png",
    )
    _PILImage.fromarray(reference_mask).save(reference_mask_path)
    return {
        "source_video": source_path,
        "source_frames": source_frames,
        "fps": float(fps),
        "mapping_masks": source_masks,
        "mapping_summaries": mapping_summaries,
        "target_frame": target_frame,
        "target_masks": target_masks,
        "shot_ranges": [list(bounds) for bounds in shot_ranges],
        "shot_count": len(shot_ranges),
        "video_mask": video_mask_path,
        "reference_mask": reference_mask_path,
        "region_count": total,
    }

def _build_repaint_shot_prompt(
    active_count, *, finished_video_prompt=None, total_mapping_count=None,
):
    """Avoid mentioning mapped subjects that are absent from a camera shot."""
    count = max(1, min(5, int(active_count)))
    try:
        total_count = max(1, min(5, int(total_mapping_count)))
    except (TypeError, ValueError):
        total_count = None
    requested_prompt = str(finished_video_prompt or "").strip()
    if (
        total_count == count
        and any(character.isalnum() for character in requested_prompt)
    ):
        return requested_prompt
    noun = "region" if count == 1 else "regions"
    return (
        f"The {count} mapped edited {noun} move naturally with the exact "
        "source action and camera motion. Their edited appearance remains "
        "consistent, while the surrounding original scene, people, objects, "
        "lighting, and composition remain coherent and unchanged."
    )

def _build_repaint_shot_reference_conditioning(
    target_frame, target_masks, active_mapping_indices, source_frame,
    local_semantic_mask, output_dir, job_id, shot_index, *,
    cooccurring, reference_canvas, use_exact_target_frame=False,
):
    """Build one shot-local edited-region reference plus a clean scene anchor."""
    active = [int(index) for index in active_mapping_indices]
    if not active:
        raise ValueError("A generated Repaint shot needs an active region.")
    if any(
        index < 0 or index >= len(target_masks)
        for index in active
    ):
        raise ValueError("Repaint shot references contain an invalid mapping.")

    target_layers = []
    for local_index, mapping_index in enumerate(active):
        target_layers.append((
            target_frame,
            _recolor_recast_reference_mask(
                target_masks[mapping_index],
                mapping_index,
                local_index,
            ),
        ))

    if use_exact_target_frame:
        primary_image = target_frame
        primary_mask, _ = _compose_recast_character_masks(
            [layer[1] for layer in target_layers],
            _RECAST_MASK_COLORS[:len(active)],
            background_color=(255, 255, 255),
        )
        primary_mode = "edited_first_frame"
    else:
        primary_mode = "shot_layout"
        try:
            if len(active) > 1 and not cooccurring:
                raise ValueError(
                    "active edited regions never share one frame in this shot"
                )
            primary_image, primary_mask = (
                _compose_recast_group_reference_frame(
                    source_frame,
                    local_semantic_mask,
                    target_layers,
                    len(active),
                )
            )
        except ValueError as composition_error:
            print(
                f"[Repaint] Shot {shot_index + 1} has no usable shared "
                f"layout; using a balanced region sheet: "
                f"{composition_error}"
            )
            primary_image, primary_mask = (
                _compose_recast_cast_reference_frame(
                    target_layers,
                    len(active),
                    reference_canvas,
                )
            )
            primary_mode = "region_sheet"

    stem = f"repaint_shot_ref_{job_id}_{shot_index + 1}"
    primary_path, primary_mask_path = _save_recast_reference_pair(
        output_dir,
        stem,
        primary_image,
        primary_mask,
    )
    scene_reference = _build_recast_source_scene_reference(
        source_frame,
        local_semantic_mask,
        len(active),
        output_dir,
        f"repaint_{job_id}_shot_{shot_index + 1}",
        output_size=tuple(reference_canvas),
    )
    return {
        "image_start": primary_path,
        "primary_mask": primary_mask_path,
        "expected_colors": [
            list(_RECAST_MASK_COLORS[0])
            if len(active) == 1
            else None
        ],
        "source_scene_reference": scene_reference,
        "primary_mode": primary_mode,
    }

def _build_repaint_shot_manifest(
    base_params, conditioning, output_dir, job_id, *,
    reference_canvas, target_frame_count, generation_fps,
    minimum_frames, latent_size,
):
    """Create silent, exact-length mapped Repaint tasks per camera shot."""
    import copy
    import numpy as np

    source_frames, mapping_masks, shot_ranges = (
        _resample_recast_tracking_timeline(
            conditioning["source_frames"],
            conditioning["mapping_masks"],
            conditioning["shot_ranges"],
            target_frame_count,
        )
    )
    plans = _plan_recast_shot_segments(mapping_masks, shot_ranges)

    global_semantic = np.zeros(
        (*source_frames.shape[:-1], 3),
        dtype=np.uint8,
    )
    occupied = np.zeros(source_frames.shape[:-1], dtype=bool)
    for mapping_index, mapping_mask in enumerate(mapping_masks):
        region = (
            np.any(mapping_mask > 30, axis=-1)
            if mapping_mask.ndim == 4
            else mapping_mask.astype(bool)
        )
        writable = region & ~occupied
        global_semantic[writable] = np.asarray(
            _RECAST_MASK_COLORS[mapping_index],
            dtype=np.uint8,
        )
        occupied |= region

    os.makedirs(output_dir, exist_ok=True)
    tasks = []
    published_plans = []
    for plan in plans:
        shot_index = int(plan["shot_index"])
        start, end = int(plan["start_frame"]), int(plan["end_frame"])
        active = list(plan["active_mapping_indices"])
        resized_source = _resize_recast_shot_frames(
            source_frames[start:end],
            reference_canvas,
        )
        published = dict(plan)
        published["active_mapping_indices"] = list(active)

        if not active:
            passthrough_path = os.path.join(
                output_dir,
                f"repaint_{job_id}_shot_{shot_index + 1}_source.mp4",
            )
            _write_recast_shot_video(
                passthrough_path,
                resized_source,
                generation_fps,
            )
            plan["passthrough_path"] = passthrough_path
            published["generation_mode"] = "source_passthrough"
            published_plans.append(published)
            continue

        local_mask = _remap_recast_shot_mask(
            global_semantic[start:end],
            active,
            background_color=(0, 0, 0),
        )
        resized_mask = _resize_recast_shot_frames(
            local_mask,
            reference_canvas,
            semantic=True,
        )
        use_exact_target_frame = (
            shot_index == 0
            and len(active) == len(mapping_masks)
            and all(
                bool(np.any(mapping_masks[index][start] > 30))
                for index in active
            )
        )
        # The user's edited image is the selected first source frame. Keep
        # its clean scene anchor on that same frame; pairing it with a later
        # camera position would create contradictory background references.
        anchor_index = (
            start
            if use_exact_target_frame
            else int(plan["anchor_frame_index"])
        )
        anchor_mask = _remap_recast_shot_mask(
            global_semantic[anchor_index],
            active,
            background_color=(0, 0, 0),
        )
        shot_refs = _build_repaint_shot_reference_conditioning(
            conditioning["target_frame"],
            conditioning["target_masks"],
            active,
            source_frames[anchor_index],
            anchor_mask,
            output_dir,
            job_id,
            shot_index,
            cooccurring=bool(plan["cooccurring"]),
            reference_canvas=reference_canvas,
            use_exact_target_frame=use_exact_target_frame,
        )

        generated_frames, trim_tail = (
            _quantize_recast_shot_frame_count(
                end - start,
                minimum_frames,
                latent_size,
            )
        )
        pad_count = generated_frames - (end - start)
        if pad_count > 0:
            resized_source = np.concatenate([
                resized_source,
                np.repeat(resized_source[-1:], pad_count, axis=0),
            ])
            resized_mask = np.concatenate([
                resized_mask,
                np.repeat(resized_mask[-1:], pad_count, axis=0),
            ])

        guide_path = os.path.join(
            output_dir,
            f"repaint_{job_id}_shot_{shot_index + 1}_guide.mp4",
        )
        mask_path = os.path.join(
            output_dir,
            f"repaint_{job_id}_shot_{shot_index + 1}_mask.mp4",
        )
        _write_recast_shot_video(
            guide_path,
            resized_source,
            generation_fps,
        )
        _write_recast_shot_video(
            mask_path,
            resized_mask,
            generation_fps,
            semantic=True,
        )

        custom_settings = copy.deepcopy(
            base_params.get("custom_settings") or {},
        )
        custom_settings.update({
            "scail2_reference_mask_path": shot_refs["primary_mask"],
            "scail2_additional_reference_mask_paths": [],
            "scail2_reference_expected_colors": list(
                shot_refs["expected_colors"],
            ),
            "scail2_clip_reference_path": shot_refs["image_start"],
            "scail2_primary_reference_people": len(active),
            "scail2_dynamic_source_scene_reference": True,
            "scail2_timeline_source_scene_reference": False,
            "scail2_source_scene_reference_path": shot_refs[
                "source_scene_reference"
            ]["image"],
            "scail2_source_scene_mask_path": shot_refs[
                "source_scene_reference"
            ]["mask"],
        })
        shot_prompt = _build_repaint_shot_prompt(
            len(active),
            finished_video_prompt=base_params.get("prompt"),
            total_mapping_count=len(mapping_masks),
        )
        tasks.append({
            "shot_index": shot_index,
            "params": {
                "prompt": shot_prompt,
                "video_guide": guide_path,
                "video_mask": mask_path,
                "image_start": shot_refs["image_start"],
                "image_refs": [],
                "video_length": generated_frames,
                "trim_tail_frames": trim_tail,
                "video_prompt_type": f"V{len(active)}A",
                "image_prompt_type": "S",
                # Internal shots remain silent. The finishing worker restores
                # one pristine source track after exact-frame assembly.
                "audio_prompt_type": "",
                "audio_guide": None,
                "audio_source": None,
                "force_fps": "control",
                "custom_settings": custom_settings,
                "output_filename": (
                    f"repaint_{job_id}_shot_{shot_index + 1}.mp4"
                ),
            },
        })
        plan["generated_task_index"] = len(tasks) - 1
        published.update({
            "generation_mode": "scail2",
            "generated_frame_count": generated_frames,
            "trim_tail_frames": trim_tail,
            "reference_mode": shot_refs["primary_mode"],
            "reference_anchor_frame_index": anchor_index,
            "native_scene_preservation": True,
        })
        published_plans.append(published)

    return {
        "tasks": tasks,
        "shots": plans,
        "published_shots": published_plans,
        "frame_count": int(target_frame_count),
        "fps": float(generation_fps),
    }
