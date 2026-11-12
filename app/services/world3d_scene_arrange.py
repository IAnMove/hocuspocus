"""The Video 3D editor's door to the placing bindings of ``world3d.scene.patch``.

The editor holds its own document (a saved scene, a template, a working scene it opened), so its "Sit on" and "Real
height" controls send that document with the bindings (``height``, ``furniture``, ``beside``, ``rest``) to
``POST /api/v1/world3d/templates/arrange``. The server runs the same ``apply_bindings`` a patch runs (the same checks,
the same resolution, the same derived files) and returns the arranged document with the warnings and
``layout.contacts`` of an inspect; nothing else is stored, the editor keeps the document and saves it as it always does.
"""
from __future__ import annotations

from copy import deepcopy

from services.world3d_scenes import World3DSceneError, _view, apply_bindings


def arrange_document(workspace: str, document, bindings, workspace_dir) -> dict:
    """``{document, warnings, layout, objects}`` of ``document`` after ``bindings``."""
    if not isinstance(document, dict) or not isinstance(document.get("slots"), list):
        raise World3DSceneError("invalid_world3d_document", "arrange needs the editor's Video 3D document")
    if not isinstance(bindings, list) or not bindings:
        raise World3DSceneError("invalid_patch", "arrange needs a list of bindings")
    arranged = deepcopy(document)
    warnings: list[str] = []
    apply_bindings(arranged, {"bindings": bindings}, warnings, workspace, workspace_dir)
    view = _view("editor", {"revision": 0, "templateId": arranged.get("templateId"), "document": arranged, "warnings": warnings},
                 workspace, workspace_dir)
    return {"document": arranged, "warnings": view["warnings"], "layout": view["layout"], "objects": view["objects"]}
