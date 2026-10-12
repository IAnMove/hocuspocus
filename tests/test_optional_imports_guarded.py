"""Optional heavy modules must not break pytest collection on a core install.

A module-level ``import torch`` (or pygltflib, librosa, cv2) turns a missing
optional dependency into a collection error for the whole file and hides every
other test in it. Guard such imports with ``pytest.importorskip`` first, or
import inside the test.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPTIONAL_MODULES = ("torch", "pygltflib", "librosa", "cv2")


def _imported_roots(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name.split(".", 1)[0] for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        return [node.module.split(".", 1)[0]]
    return []


def _importorskip_targets(node: ast.stmt) -> set[str]:
    """Modules named by ``pytest.importorskip("...")`` anywhere in one module-level statement."""
    targets: set[str] = set()
    for call in ast.walk(node):
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == "importorskip" and call.args
                and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str)):
            targets.add(call.args[0].value.split(".", 1)[0])
    return targets


def unguarded_optional_imports(path: Path) -> list[str]:
    """Module-level imports of optional modules with no earlier importorskip.

    Only direct children of the module count: imports inside functions, classes
    or ``try`` blocks already fail (or skip) one test at a time.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    guarded: set[str] = set()
    offenders: list[str] = []
    for node in tree.body:
        guarded |= _importorskip_targets(node)
        for name in _imported_roots(node):
            if name in OPTIONAL_MODULES and name not in guarded:
                offenders.append(f"{path.name}:{node.lineno} imports {name} without pytest.importorskip")
    return offenders


def test_suite_modules_guard_optional_imports():
    offenders = [item for path in sorted((ROOT / "tests").glob("test_*.py"))
                 for item in unguarded_optional_imports(path)]
    assert offenders == []


def test_detector_flags_bare_module_level_imports(tmp_path):
    source = tmp_path / "test_bare.py"
    source.write_text(
        "import json\nimport torch\nfrom cv2 import imread\nimport librosa as lb\n"
        "from pygltflib.utils import glb2gltf\n",
        encoding="utf-8",
    )
    assert unguarded_optional_imports(source) == [
        "test_bare.py:2 imports torch without pytest.importorskip",
        "test_bare.py:3 imports cv2 without pytest.importorskip",
        "test_bare.py:4 imports librosa without pytest.importorskip",
        "test_bare.py:5 imports pygltflib without pytest.importorskip",
    ]


def test_detector_accepts_importorskip_and_nested_imports(tmp_path):
    source = tmp_path / "test_guarded.py"
    source.write_text(
        "import pytest\n"
        "pytest.importorskip('pygltflib')\n"
        "torch = pytest.importorskip('torch')\n"
        "from pygltflib import GLTF2\n"
        "import torch\n"
        "try:\n    import cv2\nexcept ImportError:\n    cv2 = None\n"
        "def test_x():\n    import librosa\n",
        encoding="utf-8",
    )
    assert unguarded_optional_imports(source) == []
