"""POST /api/v1/recast/preview.

The handler body is the launch module's, moved verbatim. Every collaborator
it reads is imported below. The served route is the wrapper in
``routers.recast_preview``.
"""

from fastapi import HTTPException, Request

from services.recast_masks import (
    _RECAST_MASK_COLORS,
    _compose_recast_character_masks,
    _count_recast_mask_people,
    _normalize_recast_character_mappings,
)
from services.recast_reference_prepare import (
    _normalize_recast_person_count,
    _normalize_recast_resolution_profile,
    _prepare_recast_reference_conditioning,
    _recast_resolution_for_source,
    _resolve_recast_media,
)
from services.recast_shot_manifest import _compose_recast_timeline_preview
from services.recast_shot_planning import (
    _normalize_recast_tracking_target,
    _select_recast_timeline_anchor,
)


async def recast_preview_endpoint(request: Request):
    """Preview mapped people across the selected Recast timeline.

    Body: { video_path: str, target?: str, person_count?: int,
            character_mappings?: list, ref_image_path?: str,
            time?: float, end_time?: float, workspace?: str }
    """
    body = await request.json()
    workspace = body.get("workspace")
    video_path = _resolve_recast_media(body.get("video_path"), workspace)
    if not video_path:
        raise HTTPException(status_code=400, detail=f"Video not found: {body.get('video_path')}")
    raw_mappings = body.get("character_mappings")
    explicit_mappings = isinstance(raw_mappings, list) and len(raw_mappings) > 0
    if explicit_mappings:
        if len(raw_mappings) > len(_RECAST_MASK_COLORS):
            raise HTTPException(
                status_code=400,
                detail="SCAIL-2 supports at most five character mappings.",
            )
        preview_mappings = []
        for index, mapping in enumerate(raw_mappings):
            if not isinstance(mapping, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"Character mapping {index + 1} is invalid.",
                )
            target = str(mapping.get("target") or "").strip()
            if not target:
                raise HTTPException(
                    status_code=400,
                    detail=f"Character mapping {index + 1} needs a source-person description.",
                )
            preview_mappings.append({"target": target})
        person_count = len(preview_mappings)
    else:
        target = (body.get("target") or "person").strip() or "person"
        person_count = _normalize_recast_person_count(body.get("person_count"))
        preview_mappings = [{"target": target}]
    mask_colors = _RECAST_MASK_COLORS[:person_count]
    at_time = max(0.0, float(body.get("time", 0) or 0))
    try:
        import decord
        import numpy as np

        vr = decord.VideoReader(video_path)
        fps = vr.get_avg_fps() or 25
        total_video_frames = len(vr)
        if total_video_frames <= 0:
            raise ValueError("The selected video contains no frames.")
        start_index = min(
            total_video_frames - 1,
            max(0, int(round(at_time * fps))),
        )
        raw_end_time = body.get("end_time")
        end_time = (
            float(raw_end_time)
            if raw_end_time is not None
            else float(total_video_frames) / float(fps)
        )
        if end_time <= at_time:
            end_index = total_video_frames - 1
        else:
            end_index = min(
                total_video_frames - 1,
                max(start_index, int(round(end_time * fps)) - 1),
            )
        if explicit_mappings:
            span = end_index - start_index + 1
            sample_count = min(24, max(1, span))
            sample_indices = np.unique(
                np.rint(
                    np.linspace(start_index, end_index, sample_count),
                ).astype(np.int64)
            )
            sampled_frames = vr.get_batch(sample_indices).asnumpy()
        else:
            sample_indices = np.asarray([start_index], dtype=np.int64)
            sampled_frames = vr.get_batch(sample_indices).asnumpy()
        del vr
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot read video: {e}")
    try:
        from shared import magic_mask

        mapping_results = []
        mapping_anchors = None
        if explicit_mappings:
            mapping_masks = []
            found_mapping_indices = []
            for index, mapping in enumerate(preview_mappings):
                tracking_target = _normalize_recast_tracking_target(
                    mapping["target"],
                )
                mapping_mask = magic_mask.generate_keyword_masks(
                    sampled_frames,
                    tracking_target,
                    no_hole=True,
                    colorize_objects=True,
                    color_palette=[mask_colors[index]],
                    max_colored_objects=1,
                    tracking_segments=[
                        (sample_index, sample_index + 1)
                        for sample_index in range(len(sampled_frames))
                    ],
                )
                region = np.any(mapping_mask > 30, axis=-1)
                areas = region.reshape(len(region), -1).sum(axis=1)
                present_samples = np.flatnonzero(areas > 0)
                found_mapping = bool(len(present_samples))
                result = {
                    "mapping_index": index,
                    "target": mapping["target"],
                    "found": found_mapping,
                    "color": list(mask_colors[index]),
                    "overlap_fraction": 0.0,
                    "first_frame_index": None,
                    "first_time_seconds": None,
                    "anchor_frame_index": None,
                    "anchor_time_seconds": None,
                    "anchor_sample_index": None,
                }
                if found_mapping:
                    anchor_sample_index = int(np.argmax(areas))
                    first_sample_index = int(present_samples[0])
                    anchor_frame_index = int(
                        sample_indices[anchor_sample_index]
                    )
                    first_frame_index = int(
                        sample_indices[first_sample_index]
                    )
                    result.update({
                        "first_frame_index": first_frame_index,
                        "first_time_seconds": (
                            float(first_frame_index) / float(fps)
                        ),
                        "anchor_frame_index": anchor_frame_index,
                        "anchor_time_seconds": (
                            float(anchor_frame_index) / float(fps)
                        ),
                        "anchor_sample_index": anchor_sample_index,
                    })
                    mapping_masks.append(mapping_mask)
                    found_mapping_indices.append(index)
                mapping_results.append(result)
            if mapping_masks:
                sampled_mask, overlaps = _compose_recast_character_masks(
                    mapping_masks,
                    [mask_colors[index] for index in found_mapping_indices],
                )
                for mapping_index, overlap in zip(
                    found_mapping_indices, overlaps,
                ):
                    mapping_results[mapping_index][
                        "overlap_fraction"
                    ] = overlap
                common_sample_index, scene_sample_index = (
                    _select_recast_timeline_anchor(mapping_masks)
                )
            else:
                sampled_mask = np.full(
                    sampled_frames.shape,
                    255,
                    dtype=np.uint8,
                )
                common_sample_index, scene_sample_index = None, 0
            matched_people = sum(result["found"] for result in mapping_results)
            selected_sample_index = (
                common_sample_index
                if common_sample_index is not None
                else scene_sample_index
            )
            idx = int(sample_indices[selected_sample_index])
            frame = sampled_frames[selected_sample_index]
            mask = sampled_mask[selected_sample_index]
            preview_image = _compose_recast_timeline_preview(
                sampled_frames,
                [
                    mapping_mask
                    for mapping_mask in mapping_masks
                ],
                [
                    mapping_results[mapping_index]
                    for mapping_index in found_mapping_indices
                ],
            )
            if matched_people == person_count:
                mapping_anchors = []
                tracked_by_mapping = {
                    mapping_index: mapping_mask
                    for mapping_index, mapping_mask in zip(
                        found_mapping_indices,
                        mapping_masks,
                    )
                }
                for mapping_index in range(person_count):
                    result = mapping_results[mapping_index]
                    anchor_sample_index = int(
                        result["anchor_sample_index"]
                    )
                    mapping_anchors.append({
                        "frame_index": result["anchor_frame_index"],
                        "source_frame": sampled_frames[
                            anchor_sample_index
                        ],
                        "source_mask": sampled_mask[
                            anchor_sample_index
                        ],
                        "mapping_mask": tracked_by_mapping[mapping_index][
                            anchor_sample_index
                        ],
                    })
        else:
            mask = magic_mask.generate_keyword_masks(
                sampled_frames, target, no_hole=True,
                colorize_objects=True,
                color_palette=mask_colors,
                max_colored_objects=person_count,
            )[0]
            idx = int(sample_indices[0])
            frame = sampled_frames[0]
            matched_people = _count_recast_mask_people(mask, mask_colors)
            mapping_results = [{
                "mapping_index": 0,
                "target": target,
                "found": matched_people >= person_count,
                "color": list(mask_colors[0]),
                "overlap_fraction": 0.0,
                "first_frame_index": idx if matched_people else None,
                "first_time_seconds": (
                    float(idx) / float(fps)
                    if matched_people
                    else None
                ),
                "anchor_frame_index": idx if matched_people else None,
                "anchor_time_seconds": (
                    float(idx) / float(fps)
                    if matched_people
                    else None
                ),
            }]
            selected = mask.any(axis=-1)
            overlay = frame.copy()
            if bool(selected.any()):
                overlay[selected] = (
                    overlay[selected].astype(np.float32) * 0.45
                    + mask[selected].astype(np.float32) * 0.55
                ).astype(np.uint8)
            from PIL import Image as _PILImage
            preview_image = _PILImage.fromarray(overlay)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Segmentation failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Segmentation failed: {e}")
    found = matched_people >= person_count
    import base64
    import io as _io

    buf = _io.BytesIO()
    preview_image.save(buf, format="JPEG", quality=85)
    resolution_profile = _normalize_recast_resolution_profile(
        body.get("resolution_profile"),
    )
    reference_canvas = _recast_resolution_for_source(
        frame,
        resolution_profile,
    )
    reference_previews = []
    has_reference = bool(body.get("ref_image_path"))
    if explicit_mappings:
        has_reference = all(
            isinstance(mapping, dict)
            and bool(
                mapping.get("ref_image_path")
                or mapping.get("reference_image_path")
            )
            for mapping in raw_mappings
        )
    if has_reference and found:
        try:
            import tempfile

            resolved_mappings, _ = _normalize_recast_character_mappings(
                body, workspace,
            )
            with tempfile.TemporaryDirectory(
                prefix="maestro-recast-preview-",
            ) as preview_dir:
                prepared = _prepare_recast_reference_conditioning(
                    resolved_mappings,
                    mask,
                    preview_dir,
                    "preview",
                    isolate_reference=body.get("isolate_reference") is not False,
                    selected_count=person_count,
                    auto_face_detail=body.get("auto_face_detail") is not False,
                    source_frame=frame,
                    reference_canvas=reference_canvas,
                    mapping_anchors=mapping_anchors,
                )
                reference_previews = prepared["previews"]
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Reference preview failed: {exc}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Reference preview failed: {exc}",
            )
    return {
        "found": found,
        "matched_people": matched_people,
        "requested_people": person_count,
        "frame_index": idx,
        "time_seconds": float(idx) / float(fps),
        "timeline_start_seconds": float(start_index) / float(fps),
        "timeline_end_seconds": float(end_index + 1) / float(fps),
        "sampled_frame_count": int(len(sample_indices)),
        "preview": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
        "mapping_results": mapping_results,
        "reference_previews": reference_previews,
        "resolution_profile": resolution_profile,
        "output_resolution": list(reference_canvas),
    }
