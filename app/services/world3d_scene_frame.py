"""The frame of a Video 3D working scene and an empty stage to start one from, so an agent never writes a document by hand.

- ``world3d.scene.patch`` takes ``width``, ``height`` (even pixels, ``FRAME_PIXELS``; 1080 x 1920 is a vertical 9:16,
  1920 x 1080 a 16:9) and ``fps`` (24, 30 or 60).
- ``world3d.scene.instantiate`` with ``template_id: "blank"`` makes an empty stage (a fixed camera on the origin, one
  sun, no objects) of ``width`` x ``height`` and ``duration``: a sitter, a table, a bed need no card.
- ``world3d.scene.publish`` takes ``name``: the saved scene is ``<name>-<scene id>``.
"""
from __future__ import annotations

from services.world3d_blank_scene import CAMERA_FAMILIES, blank_document

BLANK_ID = "blank"
FRAME_PIXELS = (128, 4096)
FPS = (24, 30, 60)
FRAME_DOC = ("width and height: the frame in even pixels (128-4096; 1080 x 1920 is a vertical 9:16, 1920 x 1080 a 16:9), and fps "
             "24, 30 or 60.")
CAMERA_DOC = ("Camera fields to merge (family, fov, eye, look, framing, ...). family is one of " + ", ".join(CAMERA_FAMILIES)
              + ": fixed holds eye and look still (use it for a still shot), orbit circles look (orbitRadius, orbitHeight, orbitTurns), "
              "encounter, follow, pursuit, side and front frame and follow the subjects, the others are moving presets; a framing "
              "{targetSlot, anchor, from, to, lookFrom, lookTo} moves any family but fixed. shake: [{start, end, amplitude (m), "
              "frequency (Hz), seed?, decay? (1/s)}] in scene seconds; [] removes it.")
BLANK_DOC = ("template_id \"blank\" makes an empty stage (a fixed camera on the origin, one sun, no objects) of width x height pixels "
             "(1280 x 720 unless given) lasting duration seconds (5): add objects to it with world3d.scene.patch bindings "
             "(add: true). No card is needed to seat people at a table or on a bed.")


def _refuse(code: str, message: str):
    from services.world3d_scenes import World3DSceneError
    return World3DSceneError(code, message)


def _pixels(value, key: str) -> int:
    if type(value) is not int or value % 2 or not FRAME_PIXELS[0] <= value <= FRAME_PIXELS[1]:
        raise _refuse("invalid_frame", f"{key} is an even number of pixels from {FRAME_PIXELS[0]} to {FRAME_PIXELS[1]}")
    return value


def set_frame(document: dict, changes: dict) -> None:
    """``width``, ``height`` and ``fps`` of a patch."""
    for key in ("width", "height"):
        if key in changes:
            document[key] = _pixels(changes[key], key)
    if "fps" in changes:
        if changes["fps"] not in FPS:
            raise _refuse("invalid_frame", "fps is 24, 30 or 60")
        document["fps"] = changes["fps"]


def blank_scene(data: dict) -> dict:
    """The document of ``template_id: "blank"``."""
    duration = data.get("duration", 5)
    if type(duration) not in (int, float) or not 0 < duration <= 600:
        raise _refuse("invalid_duration", "duration must be between 0 and 600 seconds")
    width, height = (_pixels(data.get(key, fallback), key) for key, fallback in (("width", 1280), ("height", 720)))
    return blank_document(width=width, height=height, duration=duration)
