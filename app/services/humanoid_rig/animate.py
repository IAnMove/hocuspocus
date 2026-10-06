"""Add clips to a GLB that already has the standard skeleton.

The clips are baked for that exact body: its proportions, floor and comfort
limits come from the file. Rigs made before canonical frames (identity rest
rotations) get the same motion through a per-bone correction.
"""

from __future__ import annotations

from services.humanoid_rig.errors import InvalidInput


def animate_humanoid(
    source: bytes,
    clip_ids: list[str] | None,
    bpm: float,
    import_file: bytes | None = None,
    import_suffix: str = "",
    import_label: str = "Imported",
    path: dict | None = None,
    interactions: list[dict] | None = None,
) -> tuple[bytes, list[dict], list[str]]:
    """Return ``(glb, clips, warnings)``. ``clips`` is ``[{index, name, duration, contacts}]``, plus ``loop`` for library clips.

    ``path`` (``{points: [[x, z], ...], duration, name?}``, model-space metres) adds one walk along it
    with the feet planted in the world; the clip moves the hips, so the slot itself stays still.
    """
    from services.humanoid_rig.gltf_export import append_animation_clips

    rig = stored_rig(bytes(source))
    clips, warnings = _clips(rig, clip_ids, bpm, import_file, import_suffix, import_label)
    if path:
        from services.humanoid_rig.path_walk import path_clip

        walk = path_clip(rig, path.get("points"), path.get("duration", 0), str(path.get("name") or "Path Walk"))
        warnings.extend(item for item in walk.pop("warnings") if item not in warnings)
        clips.append(walk)
    for spec in interactions or []:
        made = interaction_clip(rig, spec)
        warnings.extend(f"{made['name']}: {item}" for item in made.pop("warnings"))
        clips.append(made)
    if not clips:
        raise InvalidInput("Select at least one animation")
    data, start = append_animation_clips(bytes(source), clips)
    listed = [
        {"index": start + index, "name": str(clip["name"]), "duration": float(clip["duration"]),
         **({"loop": bool(clip["loop"])} if "loop" in clip else {}), "contacts": list(clip.get("contacts", []))}
        for index, clip in enumerate(clips)
    ]
    return data, listed, warnings


def interaction_clip(rig, spec: dict) -> dict:
    """One clip that meets the scene: ``{kind: sit|reach|look, ...}`` with model-space points."""
    from services.humanoid_rig.interactions import look_clip, reach_clip, sit_clip

    kind = spec.get("kind")
    duration = spec.get("duration")
    if kind == "sit":
        return sit_clip(rig, spec.get("seat"), duration or 3.0, bool(spec.get("stand_up")), spec.get("look"), str(spec.get("name") or "Sit"))
    if kind == "reach":
        return reach_clip(rig, spec.get("target"), str(spec.get("hand") or "auto"), duration or 2.0, spec.get("hold", True) is not False,
                          spec.get("look", True) is not False, str(spec.get("name") or "Reach"))
    if kind == "look":
        return look_clip(rig, spec.get("target"), duration or 2.0, str(spec.get("name") or "Look"))
    raise InvalidInput("interaction kind must be sit, reach or look")


def stored_rig(source: bytes):
    """The motion rig of a GLB rigged with the standard skeleton."""
    from services.humanoid_rig.gltf_export import read_rig
    from services.humanoid_rig.motion import Rig
    from services.humanoid_rig.skeleton import canonical_frames, joint_positions

    stored = read_rig(source)
    marker = stored["marker"]
    facing = int(marker.get("facing", 1))
    bones = stored["bones"]
    frames = canonical_frames(joint_positions(bones), facing)
    limits = {name: float(marker[name]) for name in ("arm_down", "arm_up", "swing_up", "chest_front") if name in marker}
    return Rig(bones, frames, facing=facing, floor=stored["floor"], scale=float(bones[0]["scale"][0]), limits=limits)


def _clips(rig, clip_ids: list[str] | None, bpm: float, import_file: bytes | None, import_suffix: str, import_label: str):
    from services.humanoid_rig.clips import clip_library
    from services.humanoid_rig.retarget import retarget_file

    built = clip_library(float(bpm), list(clip_ids), rig) if clip_ids else []
    warnings: list[str] = []
    if import_file:
        if import_suffix.lower() not in (".bvh", ".glb", ".gltf"):
            raise InvalidInput("import file must be .bvh, .glb or .gltf")
        for clip in retarget_file(import_file, import_suffix, rig, import_label):
            warnings.extend(item for item in clip.pop("warnings") if item not in warnings)
            built.append(clip)
    return built, warnings
