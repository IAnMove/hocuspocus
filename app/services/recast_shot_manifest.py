"""Recast shot prompts, references, the shot manifest, and its sidecar.

The bodies are the launch module's, moved verbatim. Launch keeps the names
the recast endpoints and the shot worker call. ``os`` and ``time`` are this
module's own. The planning helper and the reference helpers are imported
from the modules that define them.
"""

import os
import time

from services.recast_masks import _RECAST_MASK_COLORS
from services.recast_reference_compose import (
    _build_recast_source_scene_reference,
    _compose_recast_cast_reference_frame,
    _compose_recast_group_reference_frame,
)
from services.recast_reference_prepare import (
    _load_recast_reference_pair,
    _save_recast_reference_pair,
)
from services.recast_shot_planning import _plan_recast_shot_segments

def _resample_recast_tracking_timeline(
    source_frames, mapping_masks, shot_ranges, target_frame_count,
):
    """Resample tracked frames and cuts onto Recast's generation timeline."""
    import numpy as np

    source = np.asarray(source_frames)
    source_count = int(len(source))
    target_count = int(target_frame_count)
    if source_count <= 0 or target_count <= 0:
        raise ValueError("Recast timeline frame counts must be positive.")
    masks = [np.asarray(mask) for mask in mapping_masks or []]
    if any(len(mask) != source_count for mask in masks):
        raise ValueError("Recast masks do not match the source timeline.")

    indices = np.floor(
        np.arange(target_count, dtype=np.float64)
        * float(source_count)
        / float(target_count)
    ).astype(np.int64)
    indices = np.clip(indices, 0, source_count - 1)
    resampled_source = source[indices]
    resampled_masks = [mask[indices] for mask in masks]

    ranges = list(shot_ranges or [(0, source_count)])
    if not ranges:
        ranges = [(0, source_count)]
    shot_count = min(len(ranges), target_count)
    ranges = ranges[:shot_count]
    boundaries = [0]
    for boundary_index, (_start, raw_end) in enumerate(ranges[:-1], 1):
        remaining = shot_count - boundary_index
        scaled = int(round(
            max(0, min(source_count, int(raw_end)))
            * float(target_count)
            / float(source_count)
        ))
        lower = boundaries[-1] + 1
        upper = target_count - remaining
        boundaries.append(max(lower, min(upper, scaled)))
    boundaries.append(target_count)
    resampled_ranges = [
        (start, end)
        for start, end in zip(boundaries, boundaries[1:])
        if end > start
    ]
    return resampled_source, resampled_masks, resampled_ranges
def _remap_recast_shot_mask(
    semantic_mask, active_mapping_indices,
    background_color=(255, 255, 255),
):
    """Convert global card colors to contiguous per-shot SCAIL colors."""
    import numpy as np

    mask = np.asarray(semantic_mask, dtype=np.uint8)
    if mask.ndim not in (3, 4) or mask.shape[-1] != 3:
        raise ValueError(
            f"Recast semantic mask must be H/W/RGB or T/H/W/RGB; got {mask.shape}."
        )
    output = np.empty_like(mask, dtype=np.uint8)
    output[...] = np.asarray(background_color, dtype=np.uint8)
    for local_index, mapping_index in enumerate(active_mapping_indices or []):
        global_color = np.asarray(
            _RECAST_MASK_COLORS[int(mapping_index)],
            dtype=np.uint8,
        )
        local_color = np.asarray(
            _RECAST_MASK_COLORS[local_index],
            dtype=np.uint8,
        )
        output[np.all(mask == global_color, axis=-1)] = local_color
    return output
def _quantize_recast_shot_frame_count(
    frame_count, minimum_frames, latent_size,
):
    """Return a valid model length and tail trim for one exact-length shot."""
    count = int(frame_count)
    minimum = max(1, int(minimum_frames))
    latent = max(1, int(latent_size))
    if count <= 0:
        raise ValueError("A Recast shot must contain at least one frame.")
    generated = ((count - 1 + latent - 1) // latent) * latent + 1
    generated = max(generated, minimum)
    if (generated - 1) % latent:
        generated = (
            (generated - 1 + latent - 1) // latent
        ) * latent + 1
    return generated, generated - count
def _build_recast_shot_prompt(
    active_count, *, finished_video_prompt=None, total_mapping_count=None,
):
    """Build text that cannot introduce identities absent from this shot."""
    count = max(1, min(5, int(active_count)))
    try:
        total_count = max(1, min(5, int(total_mapping_count)))
    except (TypeError, ValueError):
        total_count = None
    requested_prompt = str(finished_video_prompt or "").strip()
    if (
        count > 1
        and total_count == count
        and any(character.isalnum() for character in requested_prompt)
    ):
        # When the whole requested cast shares a shot, the user's
        # finished-video description is safe and materially helps SCAIL-2
        # retain clothing details that may be outside a portrait reference.
        # Solo/subset shots stay neutral so an absent identity cannot leak in.
        return requested_prompt
    if count == 1:
        return (
            "A clearly defined character performs naturally within the "
            "original scene. The character's face, hair, body shape, and "
            "complete outfit remain visually consistent while following the "
            "visible action and camera movement. The environment, lighting, "
            "shadows, and nearby objects form one coherent natural shot."
        )
    return (
        f"{count} clearly defined characters perform naturally within the "
        "original scene. Each character's face, hair, body shape, and complete "
        "outfit remain visually distinct and consistent while following the "
        "visible action and interactions. The environment, lighting, shadows, "
        "and nearby objects form one coherent natural shot."
    )
def _compose_recast_timeline_preview(
    source_frames, mapping_masks, mapping_results, max_tile_width=420,
):
    """Build one compact card per mapping at its best sampled anchor."""
    import numpy as np
    from PIL import Image as _PILImage, ImageDraw as _PILImageDraw

    frames = np.asarray(source_frames, dtype=np.uint8)
    if frames.ndim != 4 or frames.shape[-1] != 3:
        raise ValueError("Recast timeline preview needs T/H/W/RGB frames.")
    tiles = []
    for result, raw_mask in zip(mapping_results, mapping_masks):
        if not result.get("found"):
            continue
        sample_index = int(result["anchor_sample_index"])
        frame = frames[sample_index].copy()
        mask = np.asarray(raw_mask, dtype=np.uint8)[sample_index]
        selected = np.any(mask > 30, axis=-1)
        if bool(selected.any()):
            frame[selected] = (
                frame[selected].astype(np.float32) * 0.45
                + mask[selected].astype(np.float32) * 0.55
            ).astype(np.uint8)
        image = _PILImage.fromarray(frame)
        if image.width > int(max_tile_width):
            tile_height = max(
                1,
                int(round(image.height * int(max_tile_width) / image.width)),
            )
            image = image.resize(
                (int(max_tile_width), tile_height),
                resample=_PILImage.Resampling.LANCZOS,
            )
        header_height = 24
        tile = _PILImage.new(
            "RGB",
            (image.width, image.height + header_height),
            (22, 24, 29),
        )
        tile.paste(image, (0, header_height))
        draw = _PILImageDraw.Draw(tile)
        color = tuple(int(value) for value in result["color"])
        draw.rectangle((6, 6, 16, 16), fill=color, outline=(235, 235, 235))
        label = (
            f"Character {chr(65 + int(result['mapping_index']))} - "
            f"{float(result['anchor_time_seconds']):.1f}s"
        )
        draw.text((22, 5), label, fill=(235, 238, 244))
        tiles.append(tile)
    if not tiles:
        return _PILImage.fromarray(frames[0])
    columns = min(2, len(tiles))
    rows = (len(tiles) + columns - 1) // columns
    cell_width = max(tile.width for tile in tiles)
    cell_height = max(tile.height for tile in tiles)
    sheet = _PILImage.new(
        "RGB",
        (columns * cell_width, rows * cell_height),
        (14, 16, 20),
    )
    for index, tile in enumerate(tiles):
        x = (index % columns) * cell_width
        y = (index // columns) * cell_height
        sheet.paste(tile, (x, y))
    return sheet
def _resize_recast_shot_frames(frames, canvas_size, *, semantic=False):
    """Resize T/H/W/RGB frames to the exact generation canvas."""
    import numpy as np
    from PIL import Image as _PILImage

    array = np.asarray(frames, dtype=np.uint8)
    if array.ndim != 4 or array.shape[-1] != 3:
        raise ValueError(
            f"Recast shot frames must be T/H/W/RGB; got {array.shape}."
        )
    width, height = int(canvas_size[0]), int(canvas_size[1])
    if min(width, height) <= 0:
        raise ValueError("Recast shot canvas dimensions must be positive.")
    if array.shape[1:3] == (height, width):
        return array.copy()
    resample = (
        _PILImage.Resampling.NEAREST
        if semantic
        else _PILImage.Resampling.LANCZOS
    )
    return np.stack([
        np.asarray(
            _PILImage.fromarray(frame).resize(
                (width, height),
                resample=resample,
            ),
            dtype=np.uint8,
        )
        for frame in array
    ])
def _write_recast_shot_video(path, frames, fps, *, semantic=False):
    """Persist one silent internal guide or semantic-mask clip."""
    import imageio.v2 as imageio
    import numpy as np

    array = np.asarray(frames, dtype=np.uint8)
    if array.ndim != 4 or array.shape[-1] != 3 or len(array) == 0:
        raise ValueError("Cannot write an empty or malformed Recast shot.")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if semantic:
        from shared import magic_mask

        codec_params = magic_mask._magic_mask_video_codec_params()
    else:
        codec_params = {
            "codec": "libx264",
            "quality": 9,
            "pixelformat": "yuv420p",
            "macro_block_size": 1,
        }
    writer = imageio.get_writer(
        path,
        fps=float(fps),
        ffmpeg_log_level="error",
        **codec_params,
    )
    try:
        for frame in array:
            writer.append_data(frame)
    finally:
        writer.close()
    return path
def _build_recast_shot_reference_conditioning(
    prepared_refs, active_mapping_indices, source_frame,
    local_semantic_mask, output_dir, job_id, shot_index, *,
    cooccurring, reference_canvas,
):
    """Build balanced, composition-aware references for one camera shot."""
    import numpy as np

    active = [int(index) for index in active_mapping_indices]
    if not active:
        raise ValueError("A generated Recast shot needs an active character.")
    active_count = len(active)
    all_images = list(prepared_refs.get("image_refs") or [])
    all_masks = [
        prepared_refs.get("primary_mask"),
        *list(prepared_refs.get("additional_masks") or []),
    ]
    all_colors = list(prepared_refs.get("expected_colors") or [])
    if (
        len(all_images) != len(all_masks)
        or len(all_images) != len(all_colors)
    ):
        raise ValueError("Prepared Recast reference pairs are out of sync.")

    views_by_mapping = {mapping_index: [] for mapping_index in active}
    for image_path, mask_path, raw_color in zip(
        all_images, all_masks, all_colors,
    ):
        if not image_path or not mask_path or raw_color is None:
            continue
        try:
            color = tuple(int(channel) for channel in raw_color)
        except (TypeError, ValueError):
            continue
        for mapping_index in active:
            if color == tuple(_RECAST_MASK_COLORS[mapping_index]):
                views_by_mapping[mapping_index].append(
                    (image_path, mask_path),
                )
                break

    primary_items = {
        int(item["mapping_index"]): item
        for item in prepared_refs.get("primary_target_refs") or []
        if isinstance(item, dict) and "mapping_index" in item
    }
    primary_layers = []
    for local_index, mapping_index in enumerate(active):
        item = primary_items.get(mapping_index)
        if not item:
            raise ValueError(
                f"Missing primary reference for Recast mapping "
                f"{mapping_index + 1}."
            )
        primary_layers.append(
            _load_recast_reference_pair(
                item["image"],
                item["mask"],
                mapping_index,
                local_index,
            )
        )

    primary_mode = "shot_layout"
    try:
        if active_count > 1 and not cooccurring:
            raise ValueError(
                "active characters never share one frame in this shot"
            )
        primary_image, primary_mask = (
            _compose_recast_group_reference_frame(
                source_frame,
                local_semantic_mask,
                primary_layers,
                active_count,
            )
        )
    except ValueError as composition_error:
        print(
            f"[Recast] Shot {shot_index + 1} has no usable shared layout; "
            f"using a balanced cast sheet: {composition_error}"
        )
        primary_image, primary_mask = (
            _compose_recast_cast_reference_frame(
                primary_layers,
                active_count,
                reference_canvas,
            )
        )
        primary_mode = "cast_sheet"

    stem = f"recast_shot_ref_{job_id}_{shot_index + 1}"
    primary_path, primary_mask_path = _save_recast_reference_pair(
        output_dir,
        stem,
        primary_image,
        primary_mask,
    )
    image_refs = [primary_path]
    mask_paths = [primary_mask_path]
    expected_colors = [
        list(_RECAST_MASK_COLORS[0])
        if active_count == 1
        else None
    ]

    if active_count == 1:
        mapping_index = active[0]
        for view_index, (image_path, mask_path) in enumerate(
            views_by_mapping.get(mapping_index) or [],
            1,
        ):
            _rgb, recolored_mask = _load_recast_reference_pair(
                image_path,
                mask_path,
                mapping_index,
                0,
            )
            recolored_mask_path = os.path.join(
                output_dir,
                f"{stem}_identity_{view_index}_mask.png",
            )
            from PIL import Image as _PILImage

            _PILImage.fromarray(recolored_mask).save(recolored_mask_path)
            image_refs.append(image_path)
            mask_paths.append(recolored_mask_path)
            expected_colors.append(list(_RECAST_MASK_COLORS[0]))
    else:
        # A spatial group primary already contains every active identity in
        # the tracked left/right slots. Extra side-by-side cast/detail sheets
        # can disagree with those positions when the source actors cross or
        # appear in reverse card order. SCAIL-2 then follows the sheet layout
        # instead of its semantic colors, swapping and enlarging characters.
        # Keep the native group pair singular; the dedicated source-scene
        # reference below remains the only supporting reference.
        omitted_views = sum(
            len(views_by_mapping.get(mapping_index) or [])
            for mapping_index in active
        )
        reference_kind = (
            "spatial"
            if primary_mode == "shot_layout"
            else "balanced"
        )
        print(
            f"[Recast] Shot {shot_index + 1} uses one {reference_kind} "
            f"{active_count}-character reference; omitted "
            f"{omitted_views} separate identity view(s) that could override "
            "tracked color correspondence."
        )

    scene_reference = _build_recast_source_scene_reference(
        source_frame,
        local_semantic_mask,
        active_count,
        output_dir,
        f"{job_id}_shot_{shot_index + 1}",
        output_size=tuple(reference_canvas),
    )
    return {
        "image_refs": image_refs,
        "primary_mask": mask_paths[0],
        "additional_masks": mask_paths[1:],
        "expected_colors": expected_colors,
        "clip_identity_ref": (
            (views_by_mapping.get(active[0]) or [(primary_path, None)])[0][0]
            if active_count == 1
            else primary_path
        ),
        "source_scene_reference": scene_reference,
        "primary_mode": primary_mode,
    }
def _build_recast_shot_manifest(
    base_params, mapped_tracking, prepared_refs, output_dir, job_id, *,
    reference_canvas, target_frame_count, generation_fps,
    minimum_frames, latent_size,
):
    """Create internal, exact-length generation tasks per detected shot."""
    import copy
    import numpy as np

    source_frames, mapping_masks, shot_ranges = (
        _resample_recast_tracking_timeline(
            mapped_tracking["source_frames"],
            mapped_tracking["mapping_masks"],
            mapped_tracking["shot_ranges"],
            target_frame_count,
        )
    )
    cast_transition_hold_frames = max(
        4,
        min(12, int(round(max(1.0, float(generation_fps)) * 0.2))),
    )
    transition_plans = _plan_recast_shot_segments(
        mapping_masks,
        shot_ranges,
        split_cast_transitions=True,
        min_cast_run_frames=cast_transition_hold_frames,
    )
    plans = _plan_recast_shot_segments(
        mapping_masks,
        shot_ranges,
        # Keep every camera shot continuous. Splitting at a cast entrance
        # created tiny independent clips that could leave the source actor
        # untouched and made SCAIL-2 relearn color/identity correspondence at
        # the join. A hidden identity-aware pre-roll below gives late entrants
        # an initialization frame without publishing a new boundary.
        split_cast_transitions=False,
        min_cast_run_frames=cast_transition_hold_frames,
    )
    cast_transition_count = max(
        0,
        len(transition_plans) - len(shot_ranges),
    )

    global_semantic = np.empty(
        (*source_frames.shape[:-1], 3),
        dtype=np.uint8,
    )
    global_semantic[...] = (255, 255, 255)
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
        shot_frames = source_frames[start:end]
        resized_source = _resize_recast_shot_frames(
            shot_frames,
            reference_canvas,
        )
        published = dict(plan)
        published["active_mapping_indices"] = list(active)

        if not active:
            passthrough_path = os.path.join(
                output_dir,
                f"recast_{job_id}_shot_{shot_index + 1}_source.mp4",
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
        )
        resized_mask = _resize_recast_shot_frames(
            local_mask,
            reference_canvas,
            semantic=True,
        )
        anchor_index = int(plan["anchor_frame_index"])
        anchor_mask = _remap_recast_shot_mask(
            global_semantic[anchor_index],
            active,
            background_color=(0, 0, 0),
        )
        shot_refs = _build_recast_shot_reference_conditioning(
            prepared_refs,
            active,
            source_frames[anchor_index],
            anchor_mask,
            output_dir,
            job_id,
            shot_index,
            cooccurring=bool(plan["cooccurring"]),
            reference_canvas=reference_canvas,
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
            f"recast_{job_id}_shot_{shot_index + 1}_guide.mp4",
        )
        mask_path = os.path.join(
            output_dir,
            f"recast_{job_id}_shot_{shot_index + 1}_mask.mp4",
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
        try:
            requested_warmup = max(
                0,
                int(custom_settings.get(
                    "scail2_recast_warmup_frames",
                    8,
                ) or 0),
            )
        except (TypeError, ValueError):
            requested_warmup = 8
        identity_warmup_anchor = None
        if (
            len(active) > 1
            and bool(plan.get("cooccurring"))
            and not bool(plan.get("starts_with_all_active_mappings"))
        ):
            first_all_active = plan.get("first_all_active_frame_index")
            if first_all_active is not None:
                latent = max(1, int(latent_size))
                # Keep the normal hidden-frame budget whenever possible. The
                # remote anchor supplies the missing identity; increasing the
                # budget from 8 to 16 can needlessly create another diffusion
                # window on common 5-second shots.
                desired_warmup = min(
                    16,
                    max(latent, requested_warmup or 8),
                )
                desired_warmup = min(
                    16,
                    max(
                        latent,
                        (
                            (desired_warmup + latent - 1)
                            // latent
                        ) * latent,
                    ),
                )
                identity_warmup_anchor = max(
                    1,
                    int(plan["anchor_frame_index"]) - start,
                )
                custom_settings["scail2_recast_warmup_frames"] = (
                    desired_warmup
                )
                custom_settings[
                    "scail2_recast_warmup_anchor_offset"
                ] = identity_warmup_anchor
                published["identity_warmup_frames"] = desired_warmup
                published["identity_warmup_anchor_frame_index"] = int(
                    plan["anchor_frame_index"]
                )
                print(
                    f"[Recast] Shot {shot_index + 1} stays continuous; "
                    f"a hidden {desired_warmup}-frame identity pre-roll "
                    f"starts from mapped frame "
                    f"{int(plan['anchor_frame_index'])} before returning "
                    "to the shot boundary."
                )
        custom_settings.update({
            "scail2_reference_mask_path": shot_refs["primary_mask"],
            "scail2_additional_reference_mask_paths": list(
                shot_refs["additional_masks"],
            ),
            "scail2_reference_expected_colors": list(
                shot_refs["expected_colors"],
            ),
            "scail2_clip_reference_path": shot_refs["clip_identity_ref"],
            "scail2_primary_reference_people": len(active),
            "scail2_dynamic_source_scene_reference": True,
            "scail2_timeline_source_scene_reference": False,
            "scail2_source_scene_reference_path": shot_refs[
                "source_scene_reference"
            ]["image"],
            "scail2_source_scene_mask_path": shot_refs[
                "source_scene_reference"
            ]["mask"],
            "scail2_identity_latent_reference_index": 0,
        })
        shot_prompt = _build_recast_shot_prompt(
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
                "image_refs": list(shot_refs["image_refs"]),
                "video_length": generated_frames,
                "trim_tail_frames": trim_tail,
                "video_prompt_type": f"V0{len(active)}AI",
                "image_prompt_type": "",
                # Each internal clip is silent. One pristine source track is
                # attached only after exact-frame assembly.
                "audio_prompt_type": "",
                "audio_guide": None,
                "audio_source": None,
                "force_fps": "control",
                "custom_settings": custom_settings,
                "_recast_protect_bystanders": False,
                "output_filename": (
                    f"recast_{job_id}_shot_{shot_index + 1}.mp4"
                ),
            },
        })
        plan["generated_task_index"] = len(tasks) - 1
        published.update({
            "generation_mode": "scail2",
            "generated_frame_count": generated_frames,
            "trim_tail_frames": trim_tail,
            "reference_mode": shot_refs["primary_mode"],
        })
        published_plans.append(published)

    return {
        "tasks": tasks,
        "shots": plans,
        "published_shots": published_plans,
        "frame_count": int(target_frame_count),
        "fps": float(generation_fps),
        "camera_shot_count": len(shot_ranges),
        "cast_transition_count": cast_transition_count,
    }
def _write_recast_shot_aware_sidecar(
    job, output_path, shot_bundle, generation_time,
):
    """Persist restorable settings without leaking disposable shot paths."""
    import copy
    from services.asset_manifest import publish_generation_sidecar

    output_name = os.path.basename(output_path)
    params = copy.deepcopy(job.get("params") or {})
    for key in (
        "_defer_output_publication",
        "_recast_shot_manifest",
        "_recast_shot_temp_dir",
        "_recast_final_out_dir",
        "_recast_shot_bundle",
    ):
        params.pop(key, None)
    params["video_length"] = int(shot_bundle["frame_count"])
    params["seed"] = int(shot_bundle["resolved_seed"])
    params["edit_recast_shot_aware"] = True
    params["edit_recast_shot_plan"] = list(
        shot_bundle.get("published_shots") or [],
    )

    upload_filenames = {}
    for key in (
        "image_start", "image_end", "video_guide", "audio_guide",
        "audio_guide2", "audio_guide3", "audio_guide4",
        "audio_guide5", "audio_guide6",
    ):
        value = params.get(key)
        if isinstance(value, str) and value:
            upload_filenames[key] = os.path.basename(value)
        elif isinstance(value, list):
            upload_filenames[key] = [
                os.path.basename(item)
                if isinstance(item, str) and item else ""
                for item in value
            ]

    sidecar = {
        "params": params,
        "upload_filenames": upload_filenames,
        "generation_mode": params.get("generation_mode"),
        "job_id": job.get("id"),
        "generation_time": int(round(float(generation_time))),
        "created_at": time.time(),
        "output_filename": output_name,
    }
    publish_generation_sidecar(
        output_path,
        sidecar,
        workspace_id=job.get("workspace"),
        tool="recast",
    )
