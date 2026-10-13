"""Router wiring contracts, read from the source without importing either server.

- Every router factory in ``app/routers`` is mounted by the main server
  (``app/_launch_runtime.py``), directly or through a mounted router, or is
  listed below with the reason it is not.
- No method and path is defined twice in a server.
- The routes of the route table fixture and the routes of the core server
  (``app/core_runtime.py``) exist in the main server.

Routes added at run time (``api.add_api_route`` in a loop) are not seen here.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from scripts.architecture_contracts import ROOT, ROUTE_FIXTURE, _decorated_routes, _router_factory_routes


APP = ROOT / "app"
ROUTERS = APP / "routers"
MAIN = APP / "_launch_runtime.py"
CORE = APP / "core_runtime.py"

PENDING = "Pending owner decision (2026-10-13): neither wired nor deleted."
# Router factories the main server does not mount, as "module:factory".
CORE_SERVER_ONLY = {
    "core_labs:create_core_labs_router": "Core server only: the main server serves these Labs routes itself.",
    "core_mcp:create_core_mcp_router": "Core server only: the main server mounts wangp_mcp.",
    "core_remote:create_core_remote_router": "Core server only: remote generation routes without a local engine.",
    "core_series_plan:create_core_series_plan_router": "Core server only: the main server plans Series itself.",
}
NOT_MOUNTED_IN_MAIN = {
    **CORE_SERVER_ONLY,
    "procedural_3d_assets:create_procedural_3d_assets_router": f"{PENDING} No server mounts it.",
    "scene_packages:create_scene_packages_router": (
        f"{PENDING} Only the core server mounts it; the UI project transfer that calls it is unreachable."
    ),
    "user_diagnostics:create_user_diagnostics_router": (
        f"{PENDING} Only the core server mounts it; the UI diagnostics panel is unreachable."
    ),
}
# Pre-existing duplicates. Starlette serves the first registration; the later one never runs.
KNOWN_DUPLICATES = {
    ("core_runtime.py", "GET", "/api/v1/series/{series_id}"): (
        f"{PENDING} core_labs mounts series_library first, so its own get_series never runs."
    ),
    ("core_runtime.py", "POST", "/api/v1/llm/load"): (
        f"{PENDING} The core's inline llm_load (local_llm capability check) shadows the llm router's."
    ),
}


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _router_factories() -> set[tuple[str, str]]:
    """(module, factory) for every top-level function in app/routers that builds an APIRouter."""
    found = set()
    for path in sorted(ROUTERS.glob("*.py")):
        for node in _parse(path).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "APIRouter"
                for call in ast.walk(node)
            ):
                found.add((path.stem, node.name))
    return found


def _router_imports(tree: ast.AST) -> dict[str, tuple[str, str | None]]:
    """Local name -> (router module, imported name) for imports in any scope."""
    names: dict[str, tuple[str, str | None]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        for alias in node.names:
            if node.module.startswith("routers."):
                names[alias.asname or alias.name] = (node.module.split(".", 1)[1], alias.name)
            elif node.module == "routers":
                names[alias.asname or alias.name] = (alias.name, None)
    return names


def _include_target(call: ast.Call, imports: dict) -> tuple[str, str] | None:
    """The (module, factory) an ``include_router(factory(...))`` call mounts."""
    if not call.args or not isinstance(call.args[0], ast.Call):
        return None
    func = call.args[0].func
    if isinstance(func, ast.Name) and func.id in imports and imports[func.id][1]:
        return imports[func.id]
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in imports:
        return imports[func.value.id][0], func.attr
    return None


def _includes(scope: ast.AST, imports: dict, receiver: str | None = None) -> list[tuple[str, str]]:
    """Factories mounted inside ``scope``; an include this cannot resolve fails loudly."""
    mounted = []
    for node in ast.walk(scope):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router"
            and (receiver is None or (isinstance(node.func.value, ast.Name) and node.func.value.id == receiver))
        ):
            continue
        target = _include_target(node, imports)
        assert target is not None, f"Cannot resolve router include: {ast.unparse(node)}"
        mounted.append(target)
    return mounted


def _nested_includes(module: str, factory: str) -> list[tuple[str, str]]:
    tree = _parse(ROUTERS / f"{module}.py")
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == factory
    )
    return _includes(node, _router_imports(tree))


def _mounted(server: Path) -> list[tuple[str, str]]:
    """Factories a server mounts, in order, with routers mounted inside routers expanded."""
    mounted: list[tuple[str, str]] = []

    def add(target: tuple[str, str]) -> None:
        mounted.append(target)
        for nested in _nested_includes(*target):
            add(nested)

    tree = _parse(server)
    for target in _includes(tree, _router_imports(tree), receiver="api"):
        add(target)
    return mounted


def _factory_routes(module: str, factory: str) -> list[dict]:
    routes = list(_router_factory_routes(ROUTERS / f"{module}.py", factory))
    for nested in _nested_includes(module, factory):
        routes.extend(_factory_routes(*nested))
    return routes


def _server_routes(server: Path) -> list[dict]:
    """Inline ``@api`` routes and mounted router routes, as extract_route_table visits them."""
    tree = _parse(server)
    imports = _router_imports(tree)
    owner = server.relative_to(ROOT).as_posix()
    routes: list[dict] = []

    def visit(statements) -> None:
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                api_decorators = [
                    item for item in node.decorator_list
                    if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute)
                    and isinstance(item.func.value, ast.Name) and item.func.value.id == "api"
                ]
                decorated = SimpleNamespace(name=node.name, decorator_list=api_decorators)
                routes.extend(_decorated_routes(decorated, owner=owner))
            elif isinstance(node, ast.If):
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, (ast.Try, ast.With, ast.AsyncWith)):
                visit(node.body)
                if isinstance(node, ast.Try):
                    for handler in node.handlers:
                        visit(handler.body)
                    visit(node.orelse)
                    visit(node.finalbody)
            elif not isinstance(node, ast.ClassDef):
                for target in _includes(node, imports, receiver="api"):
                    routes.extend(_factory_routes(*target))

    visit(tree.body)
    return routes


def _route_key(route: dict) -> tuple[str, str]:
    # "{name:path}" and "{name}" name the same route; only the converter differs.
    return route["method"], re.sub(r"\{(\w+):\w+\}", r"{\1}", route["path"])


def test_every_router_factory_is_mounted_by_the_main_server_or_listed() -> None:
    mounted = set(_mounted(MAIN))
    unmounted = {f"{module}:{factory}" for module, factory in _router_factories() - mounted}
    assert unmounted == set(NOT_MOUNTED_IN_MAIN), (
        "Mount new routers in app/_launch_runtime.py, or list them with a reason. "
        f"Unlisted: {sorted(unmounted - set(NOT_MOUNTED_IN_MAIN))}; "
        f"listed but mounted or gone: {sorted(set(NOT_MOUNTED_IN_MAIN) - unmounted)}"
    )
    assert all(reason.strip() for reason in NOT_MOUNTED_IN_MAIN.values())
    core = {f"{module}:{factory}" for module, factory in _mounted(CORE)}
    assert set(CORE_SERVER_ONLY) <= core


def test_video_editor_routers_are_mounted_once_by_the_main_server() -> None:
    mounted = Counter(_mounted(MAIN))
    assert mounted[("video_editor", "create_video_editor_router")] == 1
    assert mounted[("video_editor", "create_video_editor_jobs_router")] == 1
    assert all(count == 1 for count in mounted.values()), mounted


def test_no_method_and_path_is_defined_twice_in_a_server() -> None:
    duplicates = {}
    for server in (MAIN, CORE):
        counts = Counter(_route_key(route) for route in _server_routes(server))
        duplicates.update({(server.name, *key): count for key, count in counts.items() if count > 1})
    assert set(duplicates) == set(KNOWN_DUPLICATES), (
        f"Defined twice: {sorted(set(duplicates) - set(KNOWN_DUPLICATES))}; "
        f"listed but fixed: {sorted(set(KNOWN_DUPLICATES) - set(duplicates))}"
    )


def test_route_table_routes_exist_in_the_main_server() -> None:
    served = {(route["method"], route["path"], route["source"]) for route in _server_routes(MAIN)}
    fixture = json.loads(ROUTE_FIXTURE.read_text(encoding="utf-8"))["routes"]
    assert fixture
    missing = [
        (route["method"], route["path"], route["source"]) for route in fixture
        if (route["method"], route["path"], route["source"]) not in served
    ]
    assert missing == []


def test_core_server_routes_exist_in_the_main_server() -> None:
    main = {_route_key(route) for route in _server_routes(MAIN)}
    pending_sources = {
        f"app/routers/{name.split(':', 1)[0]}.py"
        for name, reason in NOT_MOUNTED_IN_MAIN.items() if reason.startswith(PENDING)
    }
    core = _server_routes(CORE)
    assert core
    missing = sorted(
        (*_route_key(route), route["source"]) for route in core
        if _route_key(route) not in main and route["source"] not in pending_sources
    )
    assert missing == [], "The UI calls the same paths on both servers; serve these in the main server too."
