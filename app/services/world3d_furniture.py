"""``furniture`` in a ``world3d.scene.patch`` binding: a plain chair, table, bed... made in the workspace at its real size.

``{"object_id": "chair_1", "add": true, "furniture": {"kind": "chair", "seat": 0.46}}`` writes
``world3d-furniture/<kind>-<hash>.glb`` (named boxes from ``procedural_3d.furniture``, made once per size), binds it as
the object's ``sourceUrl``, stands it on the floor (``grounded``) and sets ``scale`` so it is drawn at its real height
(a model is drawn 1.7 m x scale tall). The declaration stays on the object, so a later patch with another size remakes
it; ``furniture: null`` forgets the declaration and keeps the bound file.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from services.procedural_3d.furniture import KINDS, furniture_glb, furniture_spec
from services.world3d_scene_bounds import MODEL_HEIGHT, native_bounds

FOLDER = "world3d-furniture"
FURNITURE_DOC = ("furniture: {kind: " + " | ".join(KINDS) + ", height?, seat?, width?, depth?, color? #rrggbb} (metres) makes a plain "
                 "piece in the workspace with named parts (seat, back, top, mattress...) at its real size, front +z, length along x, "
                 "and binds it to the object (add: true creates the object); a chair is 0.9 m with its seat at 0.46, a table 0.75, a bed's "
                 "mattress 0.55 (seat sets a chair's or sofa's seat height and its height follows). null forgets the declaration.")


def _refuse(code: str, message: str):
    from services.world3d_scenes import World3DSceneError
    return World3DSceneError(code, message)


def bind_furniture(slot: dict, binding: dict, workspace: str | None, workspace_dir) -> None:
    """Make and bind the binding's ``furniture``; ``null`` removes the declaration."""
    if "furniture" not in binding:
        return
    value = binding["furniture"]
    if value is None:
        slot.pop("furniture", None)
        return
    if any(key in binding for key in ("sourceUrl", "source_url", "scale", "fit", "height")):
        raise _refuse("invalid_furniture", f"{slot.get('id')}: furniture makes its own file and size; give it without source_url, scale, fit or height")
    if (slot.get("media") or "model3d") != "model3d":
        raise _refuse("invalid_furniture", f"{slot.get('id')}: furniture is a 3D model; bind it on a model3d object")
    try:
        spec = furniture_spec(value)
    except ValueError as error:
        raise _refuse("invalid_furniture", f"{slot.get('id')}: {error}") from error
    if not workspace or workspace_dir is None:
        raise _refuse("invalid_furniture", "furniture needs a workspace to write its file")
    relative, path = _written(spec, Path(workspace_dir(workspace)))
    from services.cc0_props import workspace_file_url
    slot.update(sourceUrl=workspace_file_url(relative, workspace), media="model3d", clip=None, grounded=True, furniture=spec,
                scale=round(native_bounds(path)["size"][1] / MODEL_HEIGHT, 6))
    slot.pop("sourceRef", None)


def _written(spec: dict, root: Path) -> tuple[str, Path]:
    """``world3d-furniture/<kind>-<hash>.glb``, written once for these sizes."""
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
    relative = f"{FOLDER}/{spec['kind']}-{digest}.glb"
    path = root / relative
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".glb.tmp")
        temporary.write_bytes(furniture_glb(spec))
        temporary.replace(path)
    return relative, path
