from __future__ import annotations

import ast
import json
from pathlib import Path

from scripts.architecture_contracts import (
    ROOT,
    ROUTE_FIXTURE,
    WIRE_FIXTURE,
    extract_route_table,
    extract_wire_inventory,
)


WGP_ALLOWLIST = {
    ("app/_launch_runtime.py", "<module>", "import wgp"),
    ("app/_launch_runtime.py", "rejoin_clips", "from wgp import concatenate_multi_clip_videos"),
    ("app/services/alternative_songs.py", "remount_clips", "from wgp import concatenate_multi_clip_videos"),
    ("app/services/director/prompt_polish.py", "load_lora_guides", "import wgp"),
    ("app/services/director/prompt_polish.py", "polish_prompts_third_pass._build_lora_hints", "import wgp"),
    ("app/services/director_pipeline.py", "_run_pipeline", "import wgp as _wgp_mod"),
    ("app/services/enhance_guides.py", "get_enhance_guide", "from wgp import get_model_def"),
    ("app/services/llm_service.py", "enhance_prompt", "from wgp import get_model_def"),
    ("app/services/model3d_service.py", "_active_profile", "import wgp"),
    ("app/services/model3d_service.py", "_minimax_api_key", "import wgp"),
    ("app/services/model3d_service.py", "_services", "import wgp"),
    ("app/shared/api.py", "WanGPSession._ensure_runtime", "importlib.import_module('wgp')"),
    ("app/shared/magic_mask.py", "_ensure_sam3_assets", "import wgp"),
    ("app/shared/magic_mask.py", "_video_to_numpy", "from wgp import get_resampled_video"),
}

IGNORED_WGP_TREES = (
    "app/models/",
    "app/plugins/",
    "app/postprocessing/mmaudio/",
    "app/postprocessing/seedvc/",
    "app/postprocessing/rife/",
    "app/postprocessing/flashvsr/",
    "app/preprocessing/sam3/",
)


_DYNAMIC_WGP_LOADERS = frozenset({
    "__import__",
    "import_module",
    "importlib.__import__",
    "importlib.import_module",
})


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        if parent is None:
            return None
        return f"{parent}.{node.attr}"
    return None


def _literal_module_name(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_wgp_module(name: str | None) -> bool:
    return name == "wgp" or bool(name and name.startswith("wgp."))


def _is_wgp_import(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(_is_wgp_module(alias.name) for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return _is_wgp_module(node.module)
    if isinstance(node, ast.Call) and node.args:
        callee = _qualified_name(node.func)
        if callee in _DYNAMIC_WGP_LOADERS:
            return _is_wgp_module(_literal_module_name(node.args[0]))
    return False


def _wgp_imports() -> set[tuple[str, str, str]]:
    found = set()
    for path in (ROOT / "app").rglob("*.py"):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(IGNORED_WGP_TREES) or "/env/" in relative or "/vendor/" in relative:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not _is_wgp_import(node):
                continue
            scopes = []
            current = node
            while current in parents:
                current = parents[current]
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    scopes.append(current.name)
            scope = ".".join(reversed(scopes)) or "<module>"
            found.add((relative, scope, ast.unparse(node)))
    return found


def test_static_route_table_matches_launch_and_mounted_router_order() -> None:
    fixture = json.loads(ROUTE_FIXTURE.read_text(encoding="utf-8"))
    assert fixture == {"version": 1, "routes": extract_route_table()}
    assert [route["ordinal"] for route in fixture["routes"]] == list(range(len(fixture["routes"])))


def test_architecture_wire_inventory_has_no_unclassified_readers() -> None:
    fixture = json.loads(WIRE_FIXTURE.read_text(encoding="utf-8"))
    assert fixture == {"version": 1, "entries": extract_wire_inventory()}
    assert all(entry["classification"] in {
        "behavior", "symbol_importable", "architecture_rule", "fragile_source",
    } for entry in fixture["entries"])


def test_wgp_import_detector_names_static_and_dynamic_forms() -> None:
    tree = ast.parse(
        "\n".join([
            "import wgp",
            "from wgp import get_model_def",
            "importlib.import_module('wgp')",
            "import_module('wgp')",
            "__import__('wgp')",
            "importlib.import_module('unrelated')",
            "import other",
        ])
    )
    detected = {ast.unparse(node) for node in ast.walk(tree) if _is_wgp_import(node)}
    assert detected == {
        "import wgp",
        "from wgp import get_model_def",
        "importlib.import_module('wgp')",
        "import_module('wgp')",
        "__import__('wgp')",
    }


def test_first_party_wgp_imports_are_named_and_cannot_grow() -> None:
    found = _wgp_imports()
    generation_imports = {item for item in found if item[0].startswith("app/services/generation/")}
    assert found - generation_imports == WGP_ALLOWLIST, (
        "First-party WanGP imports changed. Add no new site; Step 1 must remove named entries "
        f"from the allowlist. Added={sorted(found - generation_imports - WGP_ALLOWLIST)!r}, "
        f"removed={sorted(WGP_ALLOWLIST - found)!r}"
    )
