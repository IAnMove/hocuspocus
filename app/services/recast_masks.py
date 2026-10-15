"""Recast masks: palette colors, character masks, and the mask-locked video.

Function bodies are the launch module's, moved verbatim. They read no launch
name. The helpers they call moved too (this slice, and the Recast shot helpers
in :mod:`services.recast_shot_planning`) and are imported from their modules at
the bottom of this file.
"""

import os


# --- moved verbatim ---
_RECAST_MASK_COLORS = [
    (0, 0, 255),
    (255, 0, 0),
    (0, 255, 0),
    (255, 0, 255),
    (0, 255, 255),
]

# Extra SAM3 tracking colors used by native bystander mapping and the adaptive
# protection fallback. SCAIL-2 can condition at most five people, but the
# source or generated scene may contain additional people that must remain
# distinguishable while Maestro selects the relevant tracks.

_RECAST_PROTECTION_COLORS = _RECAST_MASK_COLORS + [
    (255, 255, 0),
    (255, 128, 0),
    (128, 0, 255),
    (0, 192, 128),
    (255, 64, 128),
]

def _build_recast_mask_lock_command(source_video, mask_video, generated_video, output_path):
    """Build the ffmpeg pass that restores every pixel outside the target.

    The SCAIL target is selected by a colored tracking mask. ``colorkey``
    converts the native Replace mask's white background to transparency;
    two tiny dilations plus a soft edge keep the replacement seam clean
    without giving the model room to alter neighboring people.
    """
    import json
    import math
    import subprocess

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration", "-of", "json",
            generated_video,
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        stream = (json.loads(probe.stdout).get("streams") or [])[0]
        width, height = int(stream["width"]), int(stream["height"])
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        width, height = 0, 0
    if width <= 0 or height <= 0:
        raise ValueError(f"Could not read generated Recast dimensions: {generated_video}")
    try:
        picture_seconds = float(stream.get("duration") or 0)
    except (TypeError, ValueError):
        picture_seconds = 0.0
    filter_graph = (
        f"[0:v]scale={width}:{height}:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[base];"
        f"[1:v]scale={width}:{height}:flags=neighbor,format=rgba,"
        "colorkey=0xFFFFFF:0.18:0.04,alphaextract,dilation,dilation,"
        "gblur=sigma=1.2[alpha];"
        "[2:v]format=rgba,setpts=PTS-STARTPTS[generated];"
        "[generated][alpha]alphamerge[foreground];"
        "[base][foreground]overlay=shortest=1:format=auto[outv]"
    )
    command = [
        "ffmpeg", "-y",
        "-i", source_video,
        "-i", mask_video,
        "-i", generated_video,
        "-filter_complex", filter_graph,
        "-map", "[outv]",
        # Preserve the generated file's embedded prompt and resolved seed.
        "-map_metadata", "2",
        "-c:v", "libx264", "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p",
    ]
    if _recast_video_has_audio(generated_video):
        # The generated clip's own audio is copied, so there is nothing to
        # pad and nothing to cut: the protected file keeps exactly the
        # generated picture. ``-shortest`` here dropped the last 1-6 frames
        # whenever that audio ended a little before the picture.
        command += ["-map", "2:a:0", "-c:a", "copy"]
    elif _recast_video_has_audio(source_video):
        # Re-encoded source audio may be shorter than the picture: pad it,
        # and let ``-shortest`` only bound a longer track to the picture.
        # ``-t`` fixes that bound just after the generated picture ends: with
        # an endless pad ffmpeg 7+ lets the audio run on for up to its 10 s
        # ``-shortest`` buffer when the machine is busy. It is rounded UP to
        # the next millisecond: audio that ends even a fraction of one before
        # the last frame ends makes ``-shortest`` drop that frame (81 frames
        # at 16 fps last 5.0625 s, and "5.062" cost the file its last frame).
        command += ["-map", "0:a:0", "-af", "apad", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        if picture_seconds > 0:
            command += ["-t", f"{(math.floor(round(picture_seconds * 1000, 6)) + 1) / 1000:.3f}"]
    else:
        command += ["-an"]
    return command + ["-movflags", "+faststart", output_path]

def _render_recast_mask_locked_video(source_video, mask_video, generated_video):
    """Render a protected sibling file and return its path."""
    import subprocess

    stem, extension = os.path.splitext(generated_video)
    protected_path = f"{stem}.recast-protected{extension}"
    command = _build_recast_mask_lock_command(
        source_video, mask_video, generated_video, protected_path,
    )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=900,
    )
    if result.returncode != 0 or not os.path.isfile(protected_path):
        if os.path.isfile(protected_path):
            try:
                os.remove(protected_path)
            except OSError:
                pass
        raise RuntimeError(
            "Recast target-mask protection failed: "
            + (result.stderr[-500:] if result.stderr else "ffmpeg produced no output")
        )
    return protected_path

def _recast_color_region(mask_frames, color, tolerance=90):
    """Return pixels close to an RGB tracking color after lossy video decode."""
    import numpy as np

    frames = np.asarray(mask_frames, dtype=np.int16)
    target = np.asarray(color, dtype=np.int16).reshape(1, 1, 1, 3)
    return np.max(np.abs(frames - target), axis=-1) <= int(tolerance)

def _select_recast_generated_regions(
    source_mask_frames, generated_people_masks, person_count,
):
    """Select generated person tracks that correspond to source targets.

    The source mask identifies who the user approved. SAM3 assigns stable
    colors to every person in the generated video. Spatiotemporal overlap
    matches those generated tracks back to the approved targets even when
    replacement changes body size or silhouette substantially.
    """
    import numpy as np

    source = np.asarray(source_mask_frames, dtype=np.uint8)
    generated = np.asarray(generated_people_masks, dtype=np.uint8)
    if source.shape != generated.shape or source.ndim != 4 or source.shape[-1] != 3:
        raise ValueError(
            "Adaptive Recast masks must have matching T/H/W/RGB dimensions; "
            f"got source={source.shape}, generated={generated.shape}."
        )

    source_white = np.all(source > 225, axis=-1)
    source_black = np.all(source < 30, axis=-1)
    source_union = ~source_white & ~source_black
    if not bool(source_union.any()):
        raise ValueError("The approved Recast target mask is empty.")

    requested_count = min(5, max(1, int(person_count or 1)))
    target_regions = []
    for color in _RECAST_MASK_COLORS[:requested_count]:
        region = _recast_color_region(source, color)
        if bool(region.any()):
            target_regions.append(region)
    if not target_regions:
        target_regions = [source_union]

    candidates = []
    for color_index, color in enumerate(_RECAST_PROTECTION_COLORS):
        region = np.all(generated == np.asarray(color, dtype=np.uint8), axis=-1)
        area = int(region.sum())
        if area:
            candidates.append((color_index, region, area))
    if not candidates:
        raise ValueError("SAM3 found no people in the generated Recast video.")

    pairings = []
    for target_index, target_region in enumerate(target_regions):
        target_area = max(1, int(target_region.sum()))
        for color_index, generated_region, generated_area in candidates:
            overlap = int(np.logical_and(target_region, generated_region).sum())
            score = overlap / np.sqrt(float(target_area * generated_area))
            pairings.append(
                (score, overlap, target_index, color_index, generated_region)
            )
    pairings.sort(key=lambda item: (item[0], item[1]), reverse=True)

    used_targets = set()
    used_colors = set()
    selected_regions = []
    selected_scores = []
    for score, overlap, target_index, color_index, generated_region in pairings:
        if target_index in used_targets or color_index in used_colors:
            continue
        # A tiny incidental crossing should not attach an unrelated bystander.
        if overlap <= 0 or score < 0.02:
            continue
        used_targets.add(target_index)
        used_colors.add(color_index)
        selected_regions.append(generated_region)
        selected_scores.append((color_index, float(score), overlap))
        if len(used_targets) == len(target_regions):
            break

    if len(used_targets) != len(target_regions):
        raise ValueError(
            "Could not match every generated replacement to its approved "
            f"source target ({len(used_targets)}/{len(target_regions)} matched)."
        )

    adaptive = source_union.copy()
    for region in selected_regions:
        adaptive |= region
    return adaptive, selected_scores

def _build_recast_adaptive_mask(
    generated_video, source_mask_video, person_count, output_dir,
    progress_callback=None,
):
    """Trace generated replacement silhouettes and return a mask-video path."""
    import cv2
    import numpy as np
    from shared import magic_mask

    generated_path, generated_frames, fps = magic_mask.prepare_video_mask_input(
        generated_video,
    )
    _, source_masks, _ = magic_mask.prepare_video_mask_input(source_mask_video)
    frame_count, height, width = generated_frames.shape[:3]
    if len(source_masks) != frame_count:
        indices = np.rint(
            np.linspace(0, len(source_masks) - 1, frame_count)
        ).astype(np.int64)
        source_masks = source_masks[indices]
    if source_masks.shape[1:3] != (height, width):
        source_masks = np.stack([
            cv2.resize(frame, (width, height), interpolation=cv2.INTER_NEAREST)
            for frame in source_masks
        ])

    generated_people = magic_mask.generate_keyword_masks(
        generated_frames,
        "person",
        no_hole=True,
        colorize_objects=True,
        color_palette=_RECAST_PROTECTION_COLORS,
        max_colored_objects=len(_RECAST_PROTECTION_COLORS),
        progress_callback=progress_callback,
    )
    adaptive, selected_scores = _select_recast_generated_regions(
        source_masks, generated_people, person_count,
    )

    # Close tiny segmentation gaps and leave a narrow safety rim for hair,
    # fingers, motion blur, and compression. The ffmpeg compositor feathers it.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    adaptive = np.stack([
        cv2.dilate(
            cv2.morphologyEx(frame.astype(np.uint8), cv2.MORPH_CLOSE, kernel),
            kernel,
        ) != 0
        for frame in adaptive
    ])
    output_masks = np.zeros((frame_count, height, width, 3), dtype=np.uint8)
    output_masks[adaptive] = np.asarray(_RECAST_MASK_COLORS[0], dtype=np.uint8)
    mask_path = magic_mask.save_mask_video(
        generated_path,
        output_masks,
        fps,
        ["adaptive recast target"],
        output_dir=output_dir,
        background_color=(255, 255, 255),
    )
    score_text = ", ".join(
        f"track {color_index}: {score:.3f} ({overlap} px)"
        for color_index, score, overlap in selected_scores
    )
    print(f"  [Recast] Adaptive protection selected {score_text}")
    return mask_path

def _count_recast_mask_people(mask, colors):
    """Count SCAIL-2 palette colors present in a colorized SAM3 mask."""
    import numpy as np

    array = np.asarray(mask)
    if array.ndim < 3 or array.shape[-1] != 3:
        return 0
    return sum(
        bool(np.all(array == np.asarray(color, dtype=array.dtype), axis=-1).any())
        for color in colors
    )

def _align_recast_reference_mask(source_mask, reference_mask, target_colors, candidate_colors):
    """Match people in an edited first frame to source targets by overlap.

    SAM3 segments every person in the edited reference.  Spatial overlap
    with the already-previewed source mask then tells us which new person
    belongs to each SCAIL slot, even when the edit changed "woman" to "man".
    """
    import itertools
    import numpy as np
    from PIL import Image as _PILImage

    source = np.asarray(source_mask, dtype=np.uint8)
    reference = np.asarray(reference_mask, dtype=np.uint8)
    if source.shape[:2] != reference.shape[:2]:
        source = np.asarray(
            _PILImage.fromarray(source, mode="RGB").resize(
                (reference.shape[1], reference.shape[0]),
                resample=_PILImage.Resampling.NEAREST,
            ),
            dtype=np.uint8,
        )

    target_regions = [
        np.all(source == np.asarray(color, dtype=np.uint8), axis=-1)
        for color in target_colors
    ]
    present_candidates = []
    for color in candidate_colors:
        region = np.all(reference == np.asarray(color, dtype=np.uint8), axis=-1)
        if bool(region.any()):
            present_candidates.append(region)

    scores = np.zeros((len(target_regions), len(present_candidates)), dtype=np.float64)
    for target_idx, target_region in enumerate(target_regions):
        for candidate_idx, candidate_region in enumerate(present_candidates):
            union = np.logical_or(target_region, candidate_region).sum()
            if union:
                scores[target_idx, candidate_idx] = np.logical_and(target_region, candidate_region).sum() / union

    assignment = ()
    if present_candidates:
        assignment_size = min(len(target_regions), len(present_candidates))
        assignment = max(
            itertools.permutations(range(len(present_candidates)), assignment_size),
            key=lambda candidate_ids: sum(
                scores[target_idx, candidate_id]
                for target_idx, candidate_id in enumerate(candidate_ids)
            ),
        )

    output = np.zeros_like(reference, dtype=np.uint8)
    matched = 0
    for target_idx, (target_color, target_region) in enumerate(zip(target_colors, target_regions)):
        selected_region = target_region
        if target_idx < len(assignment):
            candidate_idx = assignment[target_idx]
            if scores[target_idx, candidate_idx] > 0.01:
                selected_region = present_candidates[candidate_idx]
                matched += 1
        output[selected_region] = np.asarray(target_color, dtype=np.uint8)
    return output, matched

def _normalize_recast_character_mappings(body, workspace):
    """Resolve explicit Recast character mappings while retaining legacy API input.

    New clients send one mapping per source person.  Older clients send a
    single target/reference plus ``person_count``; that form is intentionally
    left grouped so existing saved settings remain loadable.
    """
    raw_mappings = body.get("character_mappings")
    explicit = isinstance(raw_mappings, list) and len(raw_mappings) > 0
    if explicit:
        if len(raw_mappings) > len(_RECAST_MASK_COLORS):
            raise ValueError("SCAIL-2 supports at most five character mappings.")
        mappings = []
        for index, raw_mapping in enumerate(raw_mappings):
            if not isinstance(raw_mapping, dict):
                raise ValueError(f"Character mapping {index + 1} is invalid.")
            target = str(raw_mapping.get("target") or "").strip()
            if not target:
                raise ValueError(
                    f"Character mapping {index + 1} needs a source-person description."
                )
            raw_reference = (
                raw_mapping.get("ref_image_path")
                or raw_mapping.get("reference_image_path")
            )
            reference_path = _resolve_recast_media(raw_reference, workspace)
            if not reference_path:
                raise ValueError(
                    f"Character mapping {index + 1} reference was not found: "
                    f"{raw_reference}"
                )
            additional_paths = []
            raw_additional = (
                raw_mapping.get("additional_ref_image_paths")
                or raw_mapping.get("additional_reference_paths")
                or []
            )
            if not isinstance(raw_additional, list):
                raise ValueError(
                    f"Character mapping {index + 1} additional views must be a list."
                )
            for raw_path in raw_additional[:4]:
                resolved = _resolve_recast_media(raw_path, workspace)
                if not resolved:
                    raise ValueError(
                        f"Character mapping {index + 1} additional view was not found: "
                        f"{raw_path}"
                    )
                additional_paths.append(resolved)
            mappings.append({
                "id": str(raw_mapping.get("id") or f"recast-{index + 1}"),
                "target": target,
                "ref_image_path": reference_path,
                "additional_ref_image_paths": additional_paths,
                "reference_aligned_to_source": (
                    raw_mapping.get("reference_aligned_to_source") is True
                ),
            })
        if len(mappings) > 1 and any(
            mapping["reference_aligned_to_source"] for mapping in mappings
        ):
            raise ValueError(
                "An edited full-frame reference can currently map one replacement. "
                "Use standalone primary references for multi-character mapping."
            )
        return mappings, True

    raw_reference = body.get("ref_image_path")
    reference_path = _resolve_recast_media(raw_reference, workspace)
    if not reference_path:
        raise ValueError(f"Reference image not found: {raw_reference}")
    additional_paths = []
    raw_additional = body.get("additional_ref_image_paths") or []
    if not isinstance(raw_additional, list):
        raise ValueError("Additional reference views must be a list.")
    for raw_path in raw_additional[:4]:
        resolved = _resolve_recast_media(raw_path, workspace)
        if not resolved:
            raise ValueError(f"Additional reference view was not found: {raw_path}")
        additional_paths.append(resolved)
    return [{
        "id": "recast-1",
        "target": str(body.get("target") or "person").strip() or "person",
        "ref_image_path": reference_path,
        "additional_ref_image_paths": additional_paths,
        "reference_aligned_to_source": (
            body.get("reference_aligned_to_source") is True
        ),
    }], False

def _compose_recast_character_masks(
    mapping_masks, colors, overlap_limit=0.35,
    background_color=(255, 255, 255),
):
    """Merge separately tracked people into deterministic SCAIL color slots."""
    import numpy as np

    if not mapping_masks or len(mapping_masks) != len(colors):
        raise ValueError("Recast needs one tracked mask per character color.")
    shape = np.asarray(mapping_masks[0]).shape
    if len(shape) not in (3, 4):
        raise ValueError(f"Unsupported Recast character-mask shape: {shape}.")
    region_shape = shape[:-1] if shape[-1] == 3 else shape
    background = np.asarray(background_color, dtype=np.uint8)
    if background.shape != (3,):
        raise ValueError("Character-mask background must be one RGB color.")
    output = np.empty((*region_shape, 3), dtype=np.uint8)
    output[...] = background
    occupied = np.zeros(region_shape, dtype=bool)
    overlaps = []
    for index, (raw_mask, color) in enumerate(zip(mapping_masks, colors)):
        mask = np.asarray(raw_mask)
        if mask.shape != shape:
            raise ValueError("Every Recast character mask must have matching dimensions.")
        region = np.any(mask > 30, axis=-1) if mask.shape[-1] == 3 else mask.astype(bool)
        area = int(region.sum())
        if area <= 0:
            raise ValueError(f"Character mapping {index + 1} matched no pixels.")
        overlap = np.logical_and(region, occupied)
        overlap_fraction = float(overlap.sum()) / float(max(1, area))
        overlaps.append(overlap_fraction)
        if overlap_fraction > float(overlap_limit):
            raise ValueError(
                f"Character mapping {index + 1} overlaps an earlier mapping by "
                f"{overlap_fraction:.0%}. Use more specific source descriptions."
            )
        # Earlier cards win the occasional occlusion pixel, making color
        # assignment stable regardless of SAM's internal object ordering.
        writable = region & ~occupied
        output[writable] = np.asarray(color, dtype=np.uint8)
        occupied |= region
    return output, overlaps

def _recast_mask_region(mask):
    """Return a boolean T/H/W or H/W region from a Recast mask."""
    import numpy as np

    array = np.asarray(mask)
    if array.ndim in (3, 4) and array.shape[-1] == 3:
        return np.any(array > 30, axis=-1)
    if array.ndim in (2, 3):
        return array.astype(bool)
    raise ValueError(f"Unsupported Recast mask shape: {array.shape}.")

def _build_recast_character_mask(
    source_video, mappings, output_dir, progress_callback=None,
    abort_callback=None,
):
    """Track mapped characters across shots, then save one color mask."""
    import numpy as np
    from shared import magic_mask

    source_path, source_frames, fps = magic_mask.prepare_video_mask_input(
        source_video,
    )
    shot_ranges = _detect_recast_shot_ranges(source_frames)
    if len(shot_ranges) > 1:
        safe_fps = float(fps or 25.0)
        cut_times = ", ".join(
            f"{start / safe_fps:.2f}s"
            for start, _end in shot_ranges[1:]
        )
        print(
            f"[Recast] Detected {len(shot_ranges)} camera shots; "
            f"reacquiring mapped characters after cuts at {cut_times}."
        )
    else:
        print(
            "[Recast] Detected one continuous camera shot; "
            "tracking mapped characters across the full timeline."
        )
    mapping_masks = []
    mapping_summaries = []
    tracking_targets = []
    total_mappings = len(mappings)
    for index, mapping in enumerate(mappings):
        if abort_callback is not None:
            abort_callback()

        def _mapping_progress(done, total, mapping_index=index):
            if abort_callback is not None:
                abort_callback()
            if progress_callback is not None:
                progress_callback(
                    mapping_index,
                    total_mappings,
                    done,
                    total,
                )

        color = _RECAST_MASK_COLORS[index]
        tracking_target = _normalize_recast_tracking_target(
            mapping["target"],
        )
        tracking_targets.append(tracking_target)
        if tracking_target != mapping["target"]:
            print(
                "[Recast] SAM3 tracking wording normalized: "
                f"'{mapping['target']}' -> '{tracking_target}'."
            )
        tracked = magic_mask.generate_keyword_masks(
            source_frames,
            tracking_target,
            no_hole=True,
            colorize_objects=True,
            color_palette=[color],
            max_colored_objects=1,
            progress_callback=_mapping_progress,
            tracking_segments=shot_ranges,
        )
        summary = _summarize_recast_mapping_mask(tracked, fps)
        if summary is None:
            raise ValueError(
                f"Character mapping {index + 1} found no "
                f"'{mapping['target']}' anywhere in the selected video. "
                "Try a more specific description or adjust the trim range."
            )
        summary.update({
            "mapping_index": index,
            "target": mapping["target"],
            "tracking_target": tracking_target,
            "color": list(color),
        })
        mapping_masks.append(tracked)
        mapping_summaries.append(summary)

    unresolved_shots = _find_recast_unmapped_shots(
        mapping_masks,
        shot_ranges,
    )
    recovered_shots = []
    if unresolved_shots:
        compact_parts = []
        compact_ranges = []
        compact_offset = 0
        for shot in unresolved_shots:
            start = int(shot["start_frame"])
            end = int(shot["end_frame"])
            compact_parts.append(source_frames[start:end])
            length = end - start
            compact_ranges.append(
                (compact_offset, compact_offset + length),
            )
            compact_offset += length
        recovery_frames = (
            compact_parts[0]
            if len(compact_parts) == 1
            else np.concatenate(compact_parts, axis=0)
        )
        shot_numbers = ", ".join(
            str(int(shot["shot_index"]) + 1)
            for shot in unresolved_shots
        )
        print(
            "[Recast] No mapped target was grounded in camera shot"
            f"{'s' if len(unresolved_shots) != 1 else ''} "
            f"{shot_numbers}; running generic-person appearance recovery."
        )

        def _recovery_progress(_done, _total):
            if abort_callback is not None:
                abort_callback()

        compact_people_mask = magic_mask.generate_keyword_masks(
            recovery_frames,
            "person",
            no_hole=True,
            colorize_objects=True,
            color_palette=_RECAST_MASK_COLORS,
            max_colored_objects=len(_RECAST_MASK_COLORS),
            progress_callback=_recovery_progress,
            tracking_segments=compact_ranges,
        )
        mapping_masks, recovered_shots = (
            _recover_recast_unmapped_shots(
                source_frames,
                mapping_masks,
                shot_ranges,
                unresolved_shots,
                compact_people_mask,
                compact_ranges,
            )
        )
        del compact_people_mask
        del recovery_frames
        if recovered_shots:
            recovery_summary = ", ".join(
                "shot "
                f"{item['shot_index'] + 1} -> character "
                f"{chr(65 + item['mapping_index'])} "
                f"({item['similarity']:.2f})"
                for item in recovered_shots
            )
            print(
                "[Recast] Appearance recovery accepted "
                f"{recovery_summary}."
            )
            refreshed_summaries = []
            for index, mapping_mask in enumerate(mapping_masks):
                refreshed = _summarize_recast_mapping_mask(
                    mapping_mask,
                    fps,
                )
                if refreshed is None:
                    refreshed = mapping_summaries[index]
                refreshed.update({
                    "mapping_index": index,
                    "target": mappings[index]["target"],
                    "tracking_target": tracking_targets[index],
                    "color": list(_RECAST_MASK_COLORS[index]),
                    "recovered_shot_indices": [
                        item["shot_index"]
                        for item in recovered_shots
                        if item["mapping_index"] == index
                    ],
                })
                refreshed_summaries.append(refreshed)
            mapping_summaries = refreshed_summaries
        else:
            print(
                "[Recast] Generic-person recovery found no sufficiently "
                "distinct identity match; unresolved shots remain unchanged."
            )
    merged, overlaps = _compose_recast_character_masks(
        mapping_masks,
        _RECAST_MASK_COLORS[:total_mappings],
    )
    common_frame_index, scene_anchor_index = (
        _select_recast_timeline_anchor(mapping_masks)
    )
    for summary, overlap in zip(mapping_summaries, overlaps):
        summary["overlap_fraction"] = float(overlap)
    mask_path = magic_mask.save_mask_video(
        source_path,
        merged,
        fps,
        [mapping["target"] for mapping in mappings],
        output_dir=output_dir,
        abort_callback=abort_callback,
        background_color=(255, 255, 255),
    )
    return {
        "video_mask": mask_path,
        "mask_frames": merged,
        "source_frames": source_frames,
        "fps": fps,
        "overlaps": overlaps,
        "mapping_masks": mapping_masks,
        "mapping_summaries": mapping_summaries,
        "recovered_shots": recovered_shots,
        "shot_ranges": [list(bounds) for bounds in shot_ranges],
        "shot_count": len(shot_ranges),
        "common_frame_index": common_frame_index,
        "scene_anchor_index": scene_anchor_index,
        "timeline_aware": (
            len(shot_ranges) > 1
            or (
                total_mappings > 1
                and common_frame_index is None
            )
            or any(
                summary["first_frame_index"] > 0
                for summary in mapping_summaries
            )
        ),
    }

def _recolor_recast_reference_mask(
    semantic_mask, global_mapping_index, local_mapping_index,
):
    """Recolor one prepared identity mask for a shot-local character slot."""
    import numpy as np

    mask = np.asarray(semantic_mask, dtype=np.uint8)
    global_color = np.asarray(
        _RECAST_MASK_COLORS[int(global_mapping_index)],
        dtype=np.uint8,
    )
    local_color = np.asarray(
        _RECAST_MASK_COLORS[int(local_mapping_index)],
        dtype=np.uint8,
    )
    region = np.all(mask == global_color, axis=-1)
    if not bool(region.any()):
        region = np.any(mask > 30, axis=-1)
    output = np.zeros_like(mask, dtype=np.uint8)
    output[region] = local_color
    return output

# --- helpers that moved with this slice ---
# Imported last: recast_reference_prepare imports this module back, and every
# name it takes from here is defined above by then.
from services.recast_reference_prepare import (
    _resolve_recast_media,
    _recast_video_has_audio,
)
from services.recast_shot_planning import (
    _detect_recast_shot_ranges,
    _find_recast_unmapped_shots,
    _normalize_recast_tracking_target,
    _recover_recast_unmapped_shots,
    _select_recast_timeline_anchor,
    _summarize_recast_mapping_mask,
)
