"""Validate the native flat-background recipe before admitting production work."""
from __future__ import annotations

PRESET = "ps1-backplates"
ERROR = "invalid_backplate_shot"


def validate_backplate_shots(spec: dict) -> None:
    shots = spec.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("ps1-backplates needs authored shots; use the native backplate_shot recipe")
    fill = spec.get("fill") or []
    if not isinstance(fill, list):
        raise ValueError("ps1-backplates fill must be a list of authored shots")
    for shot in [*shots, *fill]:
        if not isinstance(shot, dict):
            continue  # The normal production validator reports malformed shots.
        if shot.get("kind") == "h3" or shot.get("sing"):
            raise ValueError(f"{shot.get('key', 'fill')}: use scene3d with an authored GLB clip, not H3 or lip-sync")
        if shot.get("kind") == "scene3d":
            validate_backplate_scene(shot.get("scene3d"))


def validate_backplate_scene(config: dict) -> None:
    if not isinstance(config, dict) or not isinstance(config.get("document"), dict):
        raise ValueError("ps1-backplates scene3d needs a full native document with its image and actor slots")
    document = config["document"]
    if config.get("subject"):
        raise ValueError("subject override drops the background; edit the document's actor slot instead")
    camera = document.get("camera", {})
    override = config.get("camera", {})
    if not isinstance(camera, dict) or not isinstance(override, dict):
        raise ValueError("backplate camera must be a fixed native camera")
    camera = {**camera, **override}
    if camera.get("family") != "fixed" or camera.get("framing"):
        raise ValueError("backplate camera must stay fixed; author a separate image for another view")
    _validate_set(document, config)
    _validate_slots(config.get("slots", document.get("slots")))


def _validate_set(document: dict, config: dict) -> None:
    if config.get("pixelWorld", document.get("pixelWorld")):
        raise ValueError("backplates use the Qwen image, not a procedural pixel world")
    # The native parser normalizes "none" to an omitted dressing field.
    if config.get("dressing", document.get("dressing")) not in (None, "none"):
        raise ValueError("backplate dressing must be none: the environment comes from the Qwen image")
    environment = config.get("environment", document.get("environment", {}))
    if not isinstance(environment, dict) or environment.get("floorStyle") != "none":
        raise ValueError("backplate floorStyle must be none")
    if environment.get("platform") or environment.get("reflectiveFloor"):
        raise ValueError("backplates do not render a platform or reflective floor")
    atmosphere = config.get("atmos", document.get("atmos"))
    if atmosphere and (not isinstance(atmosphere, dict) or atmosphere.get("id") != "none"):
        raise ValueError("backplates use painted atmosphere; remove the 3D atmosphere override")


def _validate_slots(slots: list) -> None:
    if not isinstance(slots, list) or any(not isinstance(slot, dict) for slot in slots):
        raise ValueError("backplates need native image and model3d slots")
    backgrounds = [slot for slot in slots if slot.get("surface") == "environment"]
    if len(backgrounds) != 1 or backgrounds[0].get("media") != "image" or not backgrounds[0].get("sourceUrl"):
        raise ValueError("backplates need exactly one environment image with a durable sourceUrl")
    if not any(slot.get("media") == "model3d" and slot.get("sourceUrl") for slot in slots):
        raise ValueError("backplates need a model3d actor with a durable sourceUrl")
