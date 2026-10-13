from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from scripts import architecture_contracts
from scripts.architecture_contracts import (
    ROOT,
    ROUTE_FIXTURE,
    WIRE_FIXTURE,
    extract_route_table,
    extract_wire_inventory,
)

RUNTIME_ROUTE_FIXTURE = ROOT / "tests" / "fixtures" / "route_table_runtime.json"


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


def test_static_route_table_names_the_served_routes_in_served_order() -> None:
    """The static table (no import) and the served table (fake-wgp import) list the same app routes.

    tests/characterization/test_route_table_runtime.py checks the served table
    against its fixture; this keeps the two fixtures in step without importing.
    """
    def rows(path, *, served: bool) -> list[tuple]:
        routes = json.loads(path.read_text(encoding="utf-8"))["routes"]
        return [
            (route["method"], route["path"], route["endpoint"], route["source"], route["status_code"])
            for route in routes
            if not served or str(route["source"]).startswith("app/")
        ]

    assert rows(ROUTE_FIXTURE, served=False) == rows(RUNTIME_ROUTE_FIXTURE, served=True), (
        "route_table.json and route_table_runtime.json disagree. Run scripts/architecture_contracts.py --write "
        "with the app's Python and review both diffs."
    )


def _routes_of(source: str) -> list[dict]:
    function = ast.parse(source).body[0]
    return architecture_contracts._decorated_routes(function, owner="app/routers/example.py")


def test_route_paths_must_be_string_literals(monkeypatch) -> None:
    computed = "@router.get(f'{PREFIX}/items')\ndef list_items():\n    pass\n"
    with pytest.raises(ValueError, match="not a string literal"):
        _routes_of(computed)
    with pytest.raises(ValueError, match="not a string literal"):
        _routes_of("@router.post(PREFIX + '/items')\ndef add_item():\n    pass\n")
    monkeypatch.setitem(
        architecture_contracts.NON_LITERAL_ROUTE_PATHS,
        ("app/routers/example.py", "list_items"),
        "example: listed with a reason",
    )
    assert [route["path"] for route in _routes_of(computed)] == ["f'{PREFIX}/items'"]


def test_stacked_route_decorators_register_bottom_up() -> None:
    routes = _routes_of(
        "@router.get('/first')\n@router.head('/second')\ndef both():\n    pass\n"
    )
    assert [(route["method"], route["path"]) for route in routes] == [("HEAD", "/second"), ("GET", "/first")]


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


def test_full_root_builds_the_runtime_context_after_binding_wgp_and_core_does_not() -> None:
    launch = ast.parse((ROOT / "app" / "_launch_runtime.py").read_text(encoding="utf-8"))
    order: list[str] = []
    for node in launch.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "bind_wgp"
        ):
            order.append("bind_wgp")
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "build_context"
        ):
            order.append("build_context")
            assert [keyword.arg for keyword in node.value.keywords if keyword.arg == "profile"] == ["profile"]
            assert ast.literal_eval(
                next(keyword.value for keyword in node.value.keywords if keyword.arg == "profile")
            ) == "full"
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "FastAPI"
        ):
            order.append("FastAPI")
    assert order == ["bind_wgp", "build_context", "FastAPI"]
    core = (ROOT / "app" / "core_runtime.py").read_text(encoding="utf-8")
    assert "services.kernel" not in core and "build_context" not in core
