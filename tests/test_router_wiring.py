"""Router wiring contracts, read from the source without importing either server.

- Every router factory in ``app/routers`` is mounted by the main server
  (``app/_launch_runtime.py``), directly or through a mounted router, or is
  listed below with the reason it is not.
- No method and path is defined twice in a server.
- The routes of the route table fixture and the routes of the core server
  (``app/core_runtime.py``) exist in the main server.
- A server never reads a global name it does not define (a slice that moved a
  function out must leave an import for every caller that stayed).

Routes added at run time (``api.add_api_route`` in a loop) are not seen here.
"""

from __future__ import annotations

import ast
import builtins
import json
import re
import symtable
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.architecture_contracts import ROOT, ROUTE_FIXTURE, _decorated_routes, _router_factory_routes


APP = ROOT / "app"
ROUTERS = APP / "routers"
MAIN = APP / "_launch_runtime.py"
CORE = APP / "core_runtime.py"

PENDING = "Pending owner decision (2026-10-13): neither wired nor deleted."
# Router factories the main server does not mount, as "module:factory".
CORE_SERVER_ONLY = {
    "core_labs:create_core_labs_router": "Core server only: the main server serves these Labs routes itself.",
    "core_remote:create_core_remote_router": "Core server only: remote generation routes without a local engine.",
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
# None are left: a new one fails test_no_method_and_path_is_defined_twice_in_a_server.
KNOWN_DUPLICATES: dict[tuple[str, str, str], str] = {}


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
        # The routes below are read without an include-time prefix; fail rather than misread paths.
        assert not any(keyword.arg == "prefix" for keyword in node.keywords), (
            f"include_router(prefix=...) is not expanded by this check: {ast.unparse(node)}"
        )
        mounted.append(target)
    return mounted


def _factory_node(module: str, factory: str) -> tuple[ast.Module, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = _parse(ROUTERS / f"{module}.py")
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == factory
    )
    return tree, node


def _nested_includes(module: str, factory: str) -> list[tuple[str, str]]:
    tree, node = _factory_node(module, factory)
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


def _factory_routes(module: str, factory: str, prefix: str = "") -> list[dict]:
    """A router's routes, and those of the routers it includes under its own prefix.

    ``_router_factory_routes`` expands the included routers itself, as the
    route table fixtures need.
    """
    return [
        {**route, "path": prefix + route["path"]}
        for route in _router_factory_routes(ROUTERS / f"{module}.py", factory)
    ]


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
    # A request that reaches "/x/{id}" also reaches "/x/{job_id}" or "/x/{id:path}": compare the
    # shape of the path, not the names or converters of its parameters.
    return route["method"], re.sub(r"\{[^}]*\}", "{}", route["path"])


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


def test_gallery_routes_keep_the_service_docstring_as_their_openapi_description() -> None:
    """The thin route wrappers in workspace_outputs.py carry no text; the moved service function does."""
    import inspect

    from fastapi import FastAPI

    from routers.workspace_outputs import (
        create_list_outputs_router,
        create_serve_file_router,
        create_storage_usage_router,
    )
    from services import output_listing, storage_usage

    app = FastAPI()
    for router in (create_list_outputs_router(), create_serve_file_router(), create_storage_usage_router()):
        app.include_router(router)
    paths = app.openapi()["paths"]
    for path, function in (
        ("/api/v1/outputs", output_listing.list_outputs),
        ("/api/v1/file/{filename}", output_listing.serve_file),
        ("/api/v1/storage/usage", storage_usage.storage_usage),
    ):
        assert paths[path]["get"].get("description") == inspect.cleandoc(function.__doc__), path


def test_director_music_and_character_description_keep_their_docstring_as_openapi_description(monkeypatch) -> None:
    """The route wrappers in llm_director.py carry no text; the module-level handlers do."""
    import inspect

    from fastapi import FastAPI

    from routers import llm_director

    # The factories assign the launch objects onto the module; give them placeholders and let monkeypatch undo it.
    for name in (
        "wgp", "_get_active_workspace", "_workspace_dir", "_init_pipeline", "_effective_llm_routing",
        "_llm_default_device", "_DEFAULT_LLM_REPO", "_resolve_model3d_input_path",
    ):
        monkeypatch.setattr(llm_director, name, None, raising=False)
    app = FastAPI()
    app.include_router(llm_director.create_director_music_router(
        wgp=None, _get_active_workspace=None, _workspace_dir=None, _init_pipeline=None,
        _effective_llm_routing=None, _llm_default_device=None, _DEFAULT_LLM_REPO=None,
    ))
    app.include_router(llm_director.create_character_describe_router(_resolve_model3d_input_path=None))
    paths = app.openapi()["paths"]
    for path, function in (
        ("/api/v1/director/generate-music", llm_director.director_generate_music),
        ("/api/v1/characters/describe-refs", llm_director.describe_character_refs),
    ):
        assert paths[path]["post"].get("description") == inspect.cleandoc(function.__doc__), path


def test_core_mcp_returns_the_shared_wangp_router() -> None:
    tree = _parse(ROUTERS / "core_mcp.py")
    factory = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_core_mcp_router"
    )
    calls = [
        node for node in ast.walk(factory)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "create_wangp_mcp_router"
    ]
    assert len(calls) == 1
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "APIRouter"
        for node in ast.walk(factory)
    )


def test_video_editor_routers_are_mounted_once_by_the_main_server() -> None:
    mounted = Counter(_mounted(MAIN))
    assert mounted[("video_editor", "create_video_editor_router")] == 1
    assert mounted[("video_editor", "create_video_editor_jobs_router")] == 1
    assert all(count == 1 for count in mounted.values()), mounted
    core = Counter(_mounted(CORE))
    assert core[("video_editor", "create_video_editor_router")] == 1
    assert core[("video_editor", "create_video_editor_jobs_router")] == 1


def test_no_method_and_path_is_defined_twice_in_a_server() -> None:
    duplicates = {}
    for server in (MAIN, CORE):
        counts = Counter(_route_key(route) for route in _server_routes(server))
        duplicates.update({(server.name, *key): count for key, count in counts.items() if count > 1})
    known = {
        (server, *_route_key({"method": method, "path": path}))
        for server, method, path in KNOWN_DUPLICATES
    }
    assert set(duplicates) == known, (
        f"Defined twice: {sorted(set(duplicates) - known)}; "
        f"listed but fixed: {sorted(known - set(duplicates))}"
    )


def test_routers_mounted_inside_routers_keep_the_parent_prefix() -> None:
    # character_kit_face (prefix /api/v1/character-kits) includes the Lips Creator router
    # (prefix /lips-creator); the running server answers on the joined path.
    paths = {_route_key(route) for route in _server_routes(MAIN)}
    assert ("GET", "/api/v1/character-kits/lips-creator/library") in paths
    assert ("GET", "/lips-creator/library") not in paths


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


def _undefined_global_names(path: Path) -> dict[str, list[str]]:
    """Global names some function reads that the module never defines, with the functions that read them."""
    top = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
    bound = {item.get_name() for item in top.get_symbols() if item.is_assigned() or item.is_imported() or item.is_namespace()}

    def declare(table: symtable.SymbolTable) -> None:
        # ``global NAME`` followed by an assignment inside a function defines the module name.
        bound.update(item.get_name() for item in table.get_symbols() if item.is_declared_global() and item.is_assigned())
        for child in table.get_children():
            declare(child)

    declare(top)
    missing: dict[str, list[str]] = {}

    def walk(table: symtable.SymbolTable) -> None:
        for item in table.get_symbols():
            name = item.get_name()
            if (
                table is not top and item.is_global() and item.is_referenced()
                and name not in bound and not hasattr(builtins, name) and not name.startswith("__")
            ):
                missing.setdefault(name, []).append(table.get_name())
        for child in table.get_children():
            walk(child)

    walk(top)
    return missing


def test_a_server_never_reads_a_name_it_does_not_define() -> None:
    # R4a moved the Series plan handlers out of launch and left two callers behind (the Activity
    # cancel and resume of a Series plan task): a NameError on the first click, invisible to the
    # route tables and to every test that extracts launch functions.
    for server in (MAIN, CORE):
        assert _undefined_global_names(server) == {}, f"{server.name} reads names it does not define"


def _repaint_modules_with_bind_lists() -> list[Path]:
    """Service and router modules that read launch names through a generated list."""
    found = [
        path for path in sorted((APP / "services").glob("repaint_*.py"))
        if path.name != "repaint_binding.py"
    ]
    router = APP / "routers" / "repaint.py"
    if router.is_file():
        found.append(router)
    return found


def _statically_bound_module_names(tree: ast.AST) -> set[str]:
    """Names a module binds in a way symtable can see: imports, defs, and assignments.

    ``globals()[name] = ...`` is not one of these. A launch proxy installed that way stays free,
    so the bind list has to name it.
    """
    bound: set[str] = set()

    def target(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            bound.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                target(item)

    for node in tree.body:  # type: ignore[attr-defined]
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for item in node.targets:
                target(item)
        elif isinstance(node, ast.AnnAssign):
            target(node.target)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            target(node.target)
    return bound


def _free_globals_of_functions(path: Path) -> set[str]:
    """Globals the functions of ``path`` read that the module does not itself define."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    bound = _statically_bound_module_names(tree)
    table = symtable.symtable(source, str(path), "exec")
    free: set[str] = set()

    def walk(child: symtable.SymbolTable) -> None:
        if child.get_type() == "function":
            for symbol in child.get_symbols():
                name = symbol.get_name()
                if (
                    symbol.is_global() and symbol.is_referenced() and not symbol.is_declared_global()
                    and name not in bound and not hasattr(builtins, name) and not name.startswith("__")
                ):
                    free.add(name)
        for nested in child.get_children():
            walk(nested)

    walk(table)
    return free


def _declared_launch_names(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "_LAUNCH_NAMES" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Tuple) or not all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.value.elts):
            raise AssertionError(f"{path.name} must declare _LAUNCH_NAMES as a tuple of strings")
        return tuple(item.value for item in node.value.elts)
    raise AssertionError(f"{path.name} does not declare _LAUNCH_NAMES")


def test_repaint_bind_lists_are_exactly_the_free_globals() -> None:
    """The bind list is generated. A name the functions read, or one they no longer read, fails this."""
    modules = _repaint_modules_with_bind_lists()
    assert modules, "Repaint modules with a bind list"
    for path in modules:
        declared = _declared_launch_names(path)
        free = _free_globals_of_functions(path)
        assert declared == tuple(sorted(declared)), f"{path.name} _LAUNCH_NAMES is not sorted"
        assert len(declared) == len(set(declared)), f"{path.name} _LAUNCH_NAMES has a duplicate"
        assert declared == tuple(sorted(free)), (
            f"{path.name} bind list drifted: missing {sorted(free.difference(declared))}, "
            f"extra {sorted(set(declared).difference(free))}"
        )


def test_repaint_bind_once_refuses_a_different_namespace() -> None:
    """A second bind cannot hide a wrong first one. The same dict may be bound again."""
    from services.repaint_binding import bind_once

    holder: list[dict | None] = [None]
    first = {"kept": True}
    bind_once(holder, first, "probe")
    bind_once(holder, first, "probe")
    assert holder[0] is first
    with pytest.raises(RuntimeError, match="already bound"):
        bind_once(holder, {}, "probe")
    assert holder[0] is first
