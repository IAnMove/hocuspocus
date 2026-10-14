"""Recast shot ranges, unmapped shots, and the tracking timeline.

The bodies are the launch module's, moved verbatim. Launch keeps the names
the recast endpoints and the mask helper call. Collaborators that already
live in the recast services are imported from those modules.
"""

from services.recast_masks import (
    _RECAST_MASK_COLORS,
    _RECAST_PROTECTION_COLORS,
    _recast_mask_region,
)
from services.recast_reference_compose import (
    _build_recast_mapping_appearance_prototypes,
    _compose_recast_native_people_masks,
    _recast_appearance_descriptor,
)
from services.recast_reference_prepare import _normalize_recast_person_count

def _recast_probe_needs_bystander_tracking(
    probe_frame, target_probe_mask, selected_count,
):
    """Cheaply decide whether Recast needs a second full SAM3 tracking pass.

    Native group preservation can only use people visible in the first frame,
    so a one-frame broad ``person`` segmentation is sufficient to determine
    whether any usable bystander exists. If the probe is ambiguous, return
    True and retain the conservative full-pass behavior.
    """
    import numpy as np
    from shared import magic_mask

    frame = np.asarray(probe_frame, dtype=np.uint8)
    target = np.asarray(target_probe_mask, dtype=np.uint8)
    if frame.ndim != 3 or frame.shape[-1] != 3 or target.shape != frame.shape:
        return True
    try:
        people = magic_mask.generate_keyword_masks(
            frame[None],
            "person",
            no_hole=True,
            colorize_objects=True,
            color_palette=_RECAST_PROTECTION_COLORS,
            max_colored_objects=len(_RECAST_PROTECTION_COLORS),
        )
        _, _, conditioning_count, _ = _compose_recast_native_people_masks(
            target[None],
            people,
            selected_count,
        )
    except Exception:
        return True
    return conditioning_count > _normalize_recast_person_count(selected_count)
def _detect_recast_shot_ranges(
    source_frames, min_shot_frames=4, absolute_cut_threshold=0.12,
):
    """Return half-open camera-shot ranges for timeline-aware SAM3 tracking.

    A hard cut needs a fresh text anchor: carrying a segmentation track
    through the cut can attach one character card to whichever person happens
    to occupy the same screen position in the next shot. The detector combines
    low-resolution pixel change with color-histogram change and uses the
    video's own motion baseline, so ordinary camera motion is not treated as a
    cut. The absolute floor remains deliberately below typical same-location
    shot/reverse-shot edits: their shared lighting and background can keep the
    combined score below 0.30 even though the subject changes completely.
    """
    import cv2
    import numpy as np

    frames = np.asarray(source_frames, dtype=np.uint8)
    if frames.ndim != 4 or frames.shape[-1] != 3:
        raise ValueError(
            "Recast shot detection needs T/H/W/RGB source frames."
        )
    frame_count = int(len(frames))
    if frame_count <= 1:
        return [(0, frame_count)] if frame_count else []

    thumbnails = []
    histograms = []
    for frame in frames:
        thumbnail = cv2.resize(
            frame,
            (64, 36),
            interpolation=cv2.INTER_AREA,
        )
        thumbnails.append(thumbnail.astype(np.float32) / 255.0)
        histogram = cv2.calcHist(
            [thumbnail],
            [0, 1],
            None,
            [16, 16],
            [0, 256, 0, 256],
        )
        cv2.normalize(histogram, histogram)
        histograms.append(histogram)

    scores = []
    for index in range(1, frame_count):
        pixel_change = float(
            np.mean(np.abs(thumbnails[index] - thumbnails[index - 1]))
        )
        histogram_change = float(
            cv2.compareHist(
                histograms[index - 1],
                histograms[index],
                cv2.HISTCMP_BHATTACHARYYA,
            )
        )
        scores.append(0.60 * pixel_change + 0.40 * histogram_change)
    score_array = np.asarray(scores, dtype=np.float32)
    median = float(np.median(score_array))
    mad = float(np.median(np.abs(score_array - median)))
    adaptive_threshold = median + max(0.10, 6.0 * mad)
    threshold = max(float(absolute_cut_threshold), adaptive_threshold)

    minimum = max(2, int(min_shot_frames))
    boundaries = [0]
    for frame_index, score in enumerate(scores, start=1):
        if score < threshold:
            continue
        previous = scores[frame_index - 2] if frame_index > 1 else -1.0
        following = (
            scores[frame_index]
            if frame_index < len(scores)
            else -1.0
        )
        if score < previous or score < following:
            continue
        if frame_index - boundaries[-1] < minimum:
            continue
        if frame_count - frame_index < minimum:
            continue
        boundaries.append(frame_index)
    boundaries.append(frame_count)
    return [
        (start, end)
        for start, end in zip(boundaries, boundaries[1:])
        if end > start
    ]
def _summarize_recast_mapping_mask(mask, fps=25.0):
    """Describe where one independently tracked mapping appears."""
    import numpy as np

    array = np.asarray(mask)
    if array.ndim == 4 and array.shape[-1] == 3:
        region = np.any(array > 30, axis=-1)
    elif array.ndim == 3:
        region = array.astype(bool)
    else:
        raise ValueError(
            f"Unsupported Recast mapping-mask shape: {array.shape}."
        )
    areas = region.reshape(len(region), -1).sum(axis=1)
    present_indices = np.flatnonzero(areas > 0)
    if not len(present_indices):
        return None

    appearance_ranges = []
    range_start = int(present_indices[0])
    previous = range_start
    for raw_index in present_indices[1:]:
        frame_index = int(raw_index)
        if frame_index > previous + 1:
            appearance_ranges.append([range_start, previous + 1])
            range_start = frame_index
        previous = frame_index
    appearance_ranges.append([range_start, previous + 1])

    anchor_index = int(np.argmax(areas))
    safe_fps = float(fps or 25.0)
    return {
        "first_frame_index": int(present_indices[0]),
        "last_frame_index": int(present_indices[-1]),
        "anchor_frame_index": anchor_index,
        "first_time_seconds": float(present_indices[0]) / safe_fps,
        "anchor_time_seconds": float(anchor_index) / safe_fps,
        "appearance_ranges": appearance_ranges,
        "anchor_area": int(areas[anchor_index]),
        "present_frame_count": int(len(present_indices)),
    }
def _select_recast_timeline_anchor(mapping_masks):
    """Choose a useful shared scene frame and report true co-occurrence."""
    import numpy as np

    if not mapping_masks:
        return None, None
    regions = []
    areas = []
    for raw_mask in mapping_masks:
        mask = np.asarray(raw_mask)
        region = (
            np.any(mask > 30, axis=-1)
            if mask.ndim == 4 and mask.shape[-1] == 3
            else mask.astype(bool)
        )
        regions.append(region)
        areas.append(region.reshape(len(region), -1).sum(axis=1))
    frame_count = len(regions[0])
    if any(len(region) != frame_count for region in regions):
        raise ValueError("Recast mapping timelines have different lengths.")

    present = np.stack([area > 0 for area in areas], axis=0)
    common_indices = np.flatnonzero(np.all(present, axis=0))
    if len(common_indices):
        common_scores = np.stack(areas, axis=0)[:, common_indices].sum(axis=0)
        common_index = int(common_indices[int(np.argmax(common_scores))])
    else:
        common_index = None

    visible_counts = present.sum(axis=0)
    total_areas = np.stack(areas, axis=0).sum(axis=0)
    scene_index = int(np.lexsort((total_areas, visible_counts))[-1])
    return common_index, scene_index
def _normalize_recast_tracking_target(target):
    """Use wording SAM3 grounds reliably without changing user metadata."""
    import re

    text = " ".join(str(target or "").split())
    # SAM3 consistently grounds "person in red/black/..." more reliably than
    # the equivalent "person wearing ..." phrasing in camera-shot close-ups.
    return re.sub(r"\bwearing\b", "in", text, flags=re.IGNORECASE)
def _find_recast_unmapped_shots(
    mapping_masks, shot_ranges, min_area_ratio=0.0001,
):
    """Return camera shots where no mapped character was grounded."""
    import numpy as np

    regions = [_recast_mask_region(mask) for mask in mapping_masks or []]
    if not regions:
        return []
    frame_count = int(len(regions[0]))
    frame_area = int(regions[0].shape[-2] * regions[0].shape[-1])
    minimum_pixels = max(
        16,
        int(round(frame_area * max(0.0, float(min_area_ratio)))),
    )
    unresolved = []
    for shot_index, (raw_start, raw_end) in enumerate(shot_ranges or []):
        start = max(0, min(frame_count, int(raw_start)))
        end = max(start, min(frame_count, int(raw_end)))
        if end <= start:
            continue
        largest = max(
            (
                int(
                    region[start:end]
                    .reshape(end - start, -1)
                    .sum(axis=1)
                    .max()
                )
                for region in regions
            ),
            default=0,
        )
        if largest < minimum_pixels:
            unresolved.append({
                "shot_index": shot_index,
                "start_frame": start,
                "end_frame": end,
            })
    return unresolved
def _recover_recast_unmapped_shots(
    source_frames, mapping_masks, shot_ranges, unresolved_shots,
    compact_people_mask, compact_ranges, *,
    minimum_similarity=0.72, minimum_margin=0.06,
):
    """Assign generic SAM people in blank shots by source appearance.

    Text grounding remains authoritative. This fallback is used only when an
    entire camera shot has no mapped target, and only accepts a generic person
    when their clothing/color descriptor clearly favors one established
    mapping prototype.
    """
    import numpy as np

    frames = np.asarray(source_frames, dtype=np.uint8)
    people = np.asarray(compact_people_mask, dtype=np.uint8)
    # These masks are private products of the current tracking job. Mutate
    # them in place instead of duplicating several full-resolution video
    # tensors (which can consume multiple gigabytes on a 20-second clip).
    output_masks = [
        np.asarray(mask, dtype=np.uint8)
        for mask in mapping_masks
    ]
    prototypes = _build_recast_mapping_appearance_prototypes(
        frames,
        output_masks,
        shot_ranges,
    )
    recovered = []

    for shot, compact_bounds in zip(
        unresolved_shots,
        compact_ranges,
    ):
        compact_start, compact_end = (
            int(compact_bounds[0]),
            int(compact_bounds[1]),
        )
        source_start, source_end = (
            int(shot["start_frame"]),
            int(shot["end_frame"]),
        )
        if (
            compact_end <= compact_start
            or source_end - source_start != compact_end - compact_start
        ):
            continue

        candidates = []
        shot_people = people[compact_start:compact_end]
        for candidate_index, color in enumerate(_RECAST_MASK_COLORS):
            color_array = np.asarray(color, dtype=np.uint8)
            region = np.all(shot_people == color_array, axis=-1)
            areas = region.reshape(len(region), -1).sum(axis=1)
            if not int(areas.max(initial=0)):
                continue
            local_anchor = int(np.argmax(areas))
            descriptor = _recast_appearance_descriptor(
                frames[source_start + local_anchor],
                region[local_anchor],
            )
            if descriptor is None:
                continue
            scores = []
            for mapping_prototypes in prototypes:
                scores.append(max(
                    (
                        float(np.dot(descriptor, prototype))
                        for prototype in mapping_prototypes
                    ),
                    default=0.0,
                ))
            candidates.append({
                "candidate_index": candidate_index,
                "region": region,
                "scores": scores,
                "area": int(areas[local_anchor]),
            })

        pairings = []
        for candidate in candidates:
            scores = list(candidate["scores"])
            for mapping_index, score in enumerate(scores):
                alternatives = [
                    other_score
                    for other_index, other_score in enumerate(scores)
                    if other_index != mapping_index
                ]
                margin = score - max(alternatives, default=0.0)
                if (
                    score >= float(minimum_similarity)
                    and margin >= float(minimum_margin)
                    and prototypes[mapping_index]
                ):
                    pairings.append((
                        score,
                        margin,
                        candidate["area"],
                        candidate["candidate_index"],
                        mapping_index,
                        candidate["region"],
                    ))
        pairings.sort(reverse=True, key=lambda item: item[:3])

        used_candidates = set()
        used_mappings = set()
        for (
            score, margin, _area, candidate_index, mapping_index, region,
        ) in pairings:
            if (
                candidate_index in used_candidates
                or mapping_index in used_mappings
            ):
                continue
            color_array = np.asarray(
                _RECAST_MASK_COLORS[mapping_index],
                dtype=np.uint8,
            )
            target = output_masks[mapping_index][source_start:source_end]
            target[region] = color_array
            used_candidates.add(candidate_index)
            used_mappings.add(mapping_index)
            recovered.append({
                "shot_index": int(shot["shot_index"]),
                "mapping_index": mapping_index,
                "similarity": round(float(score), 4),
                "margin": round(float(margin), 4),
            })
    return output_masks, recovered
def _plan_recast_shot_segments(
    mapping_masks, shot_ranges, min_area_ratio=0.0001, *,
    split_cast_transitions=False, min_cast_run_frames=4,
):
    """Resolve active mappings and the best composition anchor per segment.

    Presence is evaluated inside each detected camera shot rather than across
    a diffusion window. This prevents two characters in adjacent
    shot/reverse-shot frames from being mistaken for a simultaneous cast.

    Recast can additionally divide one camera shot when its stable set of
    mapped characters changes. SCAIL-2 then starts every generated segment
    with the same semantic colors represented by its primary reference,
    instead of asking it to introduce a second identity partway through a
    window. Short presence/dropout runs are absorbed into their neighbors so
    detector flicker and momentary occlusion do not create tiny jobs.
    """
    import numpy as np

    masks = [np.asarray(mask) for mask in mapping_masks or []]
    if not masks:
        raise ValueError("Shot-aware Recast needs tracked mapping masks.")
    frame_count = int(len(masks[0]))
    if frame_count <= 0:
        raise ValueError("Shot-aware Recast received an empty timeline.")
    if any(len(mask) != frame_count for mask in masks):
        raise ValueError("Shot-aware Recast mapping timelines differ in length.")

    regions = []
    areas = []
    for mask in masks:
        if mask.ndim == 4 and mask.shape[-1] == 3:
            region = np.any(mask > 30, axis=-1)
        elif mask.ndim == 3:
            region = mask.astype(bool)
        else:
            raise ValueError(
                f"Unsupported Recast mapping-mask shape: {mask.shape}."
            )
        regions.append(region)
        areas.append(region.reshape(frame_count, -1).sum(axis=1))

    frame_area = int(regions[0].shape[-2] * regions[0].shape[-1])
    minimum_pixels = max(
        16,
        int(round(frame_area * max(0.0, float(min_area_ratio)))),
    )
    try:
        minimum_cast_run = max(1, int(min_cast_run_frames))
    except (TypeError, ValueError):
        minimum_cast_run = 4

    def _runs(values):
        values = np.asarray(values, dtype=bool)
        if not len(values):
            return []
        result = []
        run_start = 0
        run_value = bool(values[0])
        for index in range(1, len(values)):
            value = bool(values[index])
            if value == run_value:
                continue
            result.append((run_start, index, run_value))
            run_start, run_value = index, value
        result.append((run_start, len(values), run_value))
        return result

    def _stabilize_presence(values):
        stable = np.asarray(values, dtype=bool).copy()
        if minimum_cast_run <= 1 or len(stable) <= 1:
            return stable
        while True:
            presence_runs = _runs(stable)
            if len(presence_runs) <= 1:
                return stable
            short = [
                (end - start, run_index, start, end)
                for run_index, (start, end, _value) in enumerate(
                    presence_runs
                )
                if end - start < minimum_cast_run
            ]
            if not short:
                return stable
            _length, run_index, start, end = min(short)
            if run_index == 0:
                replacement = presence_runs[1][2]
            elif run_index == len(presence_runs) - 1:
                replacement = presence_runs[-2][2]
            else:
                # Boolean runs alternate, so both neighbors normally agree.
                # The duration tie-break keeps this safe if the representation
                # ever expands beyond a single presence bit.
                left = presence_runs[run_index - 1]
                right = presence_runs[run_index + 1]
                replacement = (
                    left[2]
                    if (
                        left[2] == right[2]
                        or left[1] - left[0] >= right[1] - right[0]
                    )
                    else right[2]
                )
            stable[start:end] = replacement

    def _signature_runs(stable_presence):
        if stable_presence.shape[1] <= 0:
            return []
        signatures = [
            tuple(np.flatnonzero(stable_presence[:, frame_index]).tolist())
            for frame_index in range(stable_presence.shape[1])
        ]
        result = []
        run_start = 0
        run_signature = signatures[0]
        for frame_index in range(1, len(signatures)):
            signature = signatures[frame_index]
            if signature == run_signature:
                continue
            result.append([run_start, frame_index, run_signature])
            run_start, run_signature = frame_index, signature
        result.append([run_start, len(signatures), run_signature])

        # Two long tracks can overlap or hand off for only a frame or two even
        # after each individual presence timeline is stable. Fold that brief
        # combined signature into the most compatible neighboring segment.
        while len(result) > 1:
            short = [
                (end - start, run_index)
                for run_index, (start, end, _signature) in enumerate(result)
                if end - start < minimum_cast_run
            ]
            if not short:
                break
            _length, run_index = min(short)
            current = set(result[run_index][2])
            neighbor_indices = [
                index
                for index in (run_index - 1, run_index + 1)
                if 0 <= index < len(result)
            ]
            replacement_index = max(
                neighbor_indices,
                key=lambda index: (
                    len(current.intersection(result[index][2])),
                    -len(current.symmetric_difference(result[index][2])),
                    result[index][1] - result[index][0],
                    -abs(index - run_index),
                ),
            )
            result[run_index][2] = result[replacement_index][2]
            merged = []
            for start, end, signature in result:
                if merged and merged[-1][2] == signature:
                    merged[-1][1] = end
                else:
                    merged.append([start, end, signature])
            result = merged
        return result

    normalized_ranges = []
    for raw_start, raw_end in shot_ranges or [(0, frame_count)]:
        start = max(0, min(frame_count, int(raw_start)))
        end = max(start, min(frame_count, int(raw_end)))
        if end > start:
            normalized_ranges.append((start, end))
    if not normalized_ranges:
        normalized_ranges = [(0, frame_count)]

    plans = []
    for camera_shot_index, (shot_start, shot_end) in enumerate(
        normalized_ranges
    ):
        shot_areas = np.stack(
            [area[shot_start:shot_end] for area in areas],
            axis=0,
        )
        if split_cast_transitions:
            stable_presence = np.stack([
                _stabilize_presence(mapping_area >= minimum_pixels)
                for mapping_area in shot_areas
            ])
            local_segments = _signature_runs(stable_presence)
        else:
            active = tuple(
                index
                for index in range(len(masks))
                if int(shot_areas[index].max(initial=0)) >= minimum_pixels
            )
            local_segments = [[0, shot_end - shot_start, active]]

        for cast_segment_index, (
            local_start, local_end, active_signature,
        ) in enumerate(local_segments):
            start = shot_start + int(local_start)
            end = shot_start + int(local_end)
            active_indices = [int(index) for index in active_signature]
            segment_areas = np.stack(
                [area[start:end] for area in areas],
                axis=0,
            )
            if active_indices:
                active_areas = segment_areas[active_indices]
                visible = active_areas >= minimum_pixels
                common = np.all(visible, axis=0)
                if bool(common.any()):
                    candidates = np.flatnonzero(common)
                    first_all_active = start + int(candidates[0])
                    # Favor a frame where the least-visible active character
                    # is still large, then total area as the tie-breaker.
                    minimum_area = active_areas[:, candidates].min(axis=0)
                    total_area = active_areas[:, candidates].sum(axis=0)
                    local_anchor = int(
                        candidates[
                            np.lexsort((total_area, minimum_area))[-1]
                        ]
                    )
                    cooccurring = True
                else:
                    first_all_active = None
                    visible_count = visible.sum(axis=0)
                    total_area = active_areas.sum(axis=0)
                    local_anchor = int(
                        np.lexsort((total_area, visible_count))[-1]
                    )
                    cooccurring = False
                anchor = start + local_anchor
            else:
                anchor = start
                first_all_active = None
                cooccurring = False

            initial_active = [
                index
                for index in active_indices
                if int(areas[index][start]) >= minimum_pixels
            ]
            active_count = len(active_indices)
            plans.append({
                "shot_index": len(plans),
                "camera_shot_index": camera_shot_index,
                "cast_segment_index": cast_segment_index,
                "segment_reason": (
                    "camera_shot"
                    if cast_segment_index == 0
                    else "cast_change"
                ),
                "start_frame": start,
                "end_frame": end,
                "frame_count": end - start,
                "anchor_frame_index": anchor,
                "first_all_active_frame_index": first_all_active,
                "active_mapping_indices": active_indices,
                "initial_active_mapping_indices": initial_active,
                "starts_with_all_active_mappings": (
                    initial_active == active_indices
                ),
                "cooccurring": cooccurring,
                "mode": (
                    "passthrough"
                    if active_count == 0
                    else "solo"
                    if active_count == 1
                    else "group"
                ),
            })
    return plans
