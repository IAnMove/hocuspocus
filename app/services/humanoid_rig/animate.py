"""Add reusable clips to a GLB that already has the standard skeleton."""

from __future__ import annotations

import json

from services.humanoid_rig.names import NORMAL_HEIGHT


def animate_humanoid(
    source: bytes,
    clip_ids: list[str] | None,
    bpm: float,
    import_file: bytes | None = None,
    import_suffix: str = "",
) -> tuple[bytes, list[dict], list[str]]:
    """Return ``(glb, clips, warnings)``. ``clips`` is ``[{index, name, duration}]``."""
    from services.humanoid_rig.gltf_export import append_animation_clips, hips_scale

    clips, warnings = _clips(source, clip_ids, bpm, import_file, import_suffix)
    if not clips:
        raise ValueError("Select at least one animation")
    data, start = append_animation_clips(bytes(source), clips)
    listed = [
        {"index": start + index, "name": str(clip["name"]), "duration": float(clip["duration"])}
        for index, clip in enumerate(clips)
    ]
    return data, listed, warnings


def _clips(source: bytes, clip_ids: list[str] | None, bpm: float, import_file: bytes | None, import_suffix: str):
    from services.humanoid_rig.clips import clip_library
    from services.humanoid_rig.gltf_export import hips_scale

    built = clip_library(float(bpm), list(clip_ids)) if clip_ids else []
    warnings: list[str] = []
    if import_file:
        imported, notes = _imported(import_file, import_suffix, float(hips_scale(source)) * NORMAL_HEIGHT)
        built.append(imported)
        warnings.extend(notes)
    return built, warnings


def _imported(payload: bytes, suffix: str, target_height: float) -> tuple[dict, list[str]]:
    from services.humanoid_rig.retarget import retarget_bvh, retarget_glb, retarget_gltf

    kind = suffix.lower()
    if kind == ".bvh":
        result = retarget_bvh(payload.decode("utf-8"), target_height)
    elif kind == ".glb":
        result = retarget_glb(payload, target_height)
    elif kind == ".gltf":
        result = retarget_gltf(json.loads(payload.decode("utf-8")), target_height)
    else:
        raise ValueError("import file must be .bvh, .glb or .gltf")
    clip = {
        "name": "Imported",
        "times": result["times"],
        "duration": result["duration"],
        "rotations": result["rotations"],
        "hips_translation": result["hips_translation"],
    }
    return clip, list(result["warnings"])
