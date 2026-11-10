"""What a ``model3d.*.make`` call did quietly, for its reply: rig warnings, a skipped face relief, a picture that will look wrong.

Everything here only reads. Nothing refuses a call; a caller sees the notes in the reply and decides. A note is a plain
``{"code", "message"}`` (plus ``file`` when it is about a picture) so a model can branch on the code and a person can read the sentence.
"""
from __future__ import annotations

from typing import Any

RATIO_LOW, RATIO_HIGH = 1.8, 2.2   # the atlas pictures are 2:1 (2048 x 1024); anything else is stretched to fit
FLAT_STD = 4.0                     # on a 0 to 255 scale, the spread of the pixels of a picture that is one colour
_SAMPLE = (128, 64)                # pixels looked at: a sample of the picture, not an average, so fine detail still counts


def note(code: str, message: str, **extra: Any) -> dict:
    return {"code": code, "message": message, **extra}


def humanoid_report(sidecar: dict) -> dict:
    """The rig's own verdict on the mesh (``neck_not_found``, ``arms_steep``, ``short_legs``…), as written beside the rigged GLB."""
    report: dict[str, Any] = {"warnings": [str(item) for item in sidecar.get("warnings") or []]}
    if sidecar.get("confidence") is not None:
        report["confidence"] = sidecar["confidence"]
    return report


def relief_gate(resolved: dict, relief) -> dict:
    """``{"relief": "applied" | "skipped", "warnings": [...]}`` for a realistic body with a head picture; ``{}`` for any other call."""
    if resolved["style"] != "real" or not resolved["texture_head"]:
        return {}
    if relief is not None:
        return {"relief": "applied", "warnings": []}
    from services import blob_face_relief

    checkpoint = "/".join(blob_face_relief.CHECKPOINT.parts[-3:])
    message = f"The face relief was skipped because the depth checkpoint {checkpoint} is not installed: the face stays flat, painted but without a nose or brows in relief."
    return {"relief": "skipped", "warnings": [note("relief_skipped", message)]}


def pictures_gate(resolved: dict, painted, head) -> list[dict]:
    """Notes about the pictures of a realistic body. ``head`` is None when there is no head picture."""
    rows = (("texture", resolved["texture"], painted), ("texture_head", resolved["texture_head"], head))
    return [item for label, name, picture in rows if picture is not None for item in picture_notes(label, str(name), picture)]


def picture_notes(label: str, name: str, picture) -> list[dict]:
    """A picture that is not about 2:1 is stretched into the atlas; one that is a single colour paints a body with no detail."""
    notes = []
    width, height = picture.size
    if not RATIO_LOW <= width / max(height, 1) <= RATIO_HIGH:
        message = f"{label} {name} is {width}x{height}, not about 2:1: it is stretched to 2048x1024, so the painting comes out distorted."
        notes.append(note("picture_not_2_to_1", message, file=name))
    if _spread(picture) < FLAT_STD:
        notes.append(note("picture_flat", f"{label} {name} is nearly one flat colour: the body or head will look unpainted.", file=name))
    return notes


def _spread(picture) -> float:
    """The largest spread, over the colour channels, of a sample of the picture's pixels."""
    import numpy as np
    from PIL import Image

    pixels = np.asarray(picture.convert("RGB").resize(_SAMPLE, Image.NEAREST), dtype=np.float32).reshape(-1, 3)
    return float(pixels.std(axis=0).max())


def with_gates(reply: dict, *gates: dict) -> dict:
    """The reply plus the gates' fields. ``warnings`` is always a list: the reply's own notes first, then each gate's."""
    merged = {**reply}
    warnings = list(reply.get("warnings") or [])
    for gate in gates:
        warnings.extend(gate.get("warnings") or [])
        merged.update({key: value for key, value in gate.items() if key != "warnings"})
    merged["warnings"] = warnings
    return merged
