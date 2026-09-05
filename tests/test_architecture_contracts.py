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
    (
        "app/services/generation/bootstrap.py",
        "_import_wgp",
        "importlib.import_module('wgp')",
    ),
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
    assert generation_imports == {
        (
            "app/services/generation/bootstrap.py",
            "_import_wgp",
            "importlib.import_module('wgp')",
        ),
    }, (
        "Only the explicit standalone bootstrap may import WanGP inside the "
        f"generation boundary. found={sorted(generation_imports)!r}"
    )
    assert found == WGP_ALLOWLIST, (
        "First-party WanGP imports may only be the two explicit bootstraps. "
        f"Added={sorted(found - WGP_ALLOWLIST)!r}, "
        f"removed={sorted(WGP_ALLOWLIST - found)!r}"
    )


def test_launch_binds_live_wgp_immediately_after_bootstrap_import() -> None:
    tree = ast.parse(
        (ROOT / "app" / "_launch_runtime.py").read_text(encoding="utf-8"),
        filename="app/_launch_runtime.py",
    )
    events: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name == "wgp" for alias in node.names):
            events.append("import_wgp")
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module == "services.generation"
            and any(alias.name == "bind_wgp" for alias in node.names)
        ):
            events.append("import_bind_wgp")
        elif (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "bind_wgp"
            and node.value.args
            and isinstance(node.value.args[0], ast.Name)
            and node.value.args[0].id == "wgp"
        ):
            events.append("bind_wgp")
    assert events == ["import_wgp", "import_bind_wgp", "bind_wgp"]
