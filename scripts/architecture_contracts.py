#!/usr/bin/env python3
"""Static architecture contracts that never import the HocusPocus runtime.

The served route table (``tests/fixtures/route_table_runtime.json``) comes from
the running app instead. ``--write`` refreshes it too, in a child process that
imports the full server with a fake WanGP (``tests/support/full_server.py``),
so this module itself still never imports the runtime.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"
ROUTE_FIXTURE = ROOT / "tests" / "fixtures" / "route_table.json"
WIRE_FIXTURE = ROOT / "tests" / "fixtures" / "architecture_wire_inventory.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

# R7: a route path is one string literal, so this table names the path that is
# served and a search for it finds its handler. A path built from an f-string,
# a constant or any other expression fails the contract, unless its route is
# listed here as (source file, endpoint) with the reason it cannot be literal.
# The runtime table (tests/fixtures/route_table_runtime.json) still records the
# resolved path of a listed route.
NON_LITERAL_ROUTE_PATHS: dict[tuple[str, str], str] = {}


def _literal(node: ast.AST | None):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node)


def _route_path(node: ast.AST, *, owner: str, endpoint: str, line: int) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if (owner, endpoint) in NON_LITERAL_ROUTE_PATHS:
        return ast.unparse(node)
    raise ValueError(
        f"Route path is not a string literal at {owner}:{line} ({endpoint}): {ast.unparse(node)}. "
        "Write the whole path as one literal, or list (source, endpoint) in "
        "NON_LITERAL_ROUTE_PATHS in scripts/architecture_contracts.py with the reason."
    )


def _decorated_routes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    owner: str,
    prefix: str = "",
) -> list[dict]:
    """Routes in registration order: stacked decorators apply bottom-up."""
    routes = []
    first_line = min((decorator.lineno for decorator in node.decorator_list), default=getattr(node, "lineno", 0))
    for decorator in reversed(node.decorator_list):
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.lower()
        if method not in HTTP_METHODS or not decorator.args:
            continue
        path = _route_path(decorator.args[0], owner=owner, endpoint=node.name, line=decorator.lineno)
        keywords = {item.arg: item.value for item in decorator.keywords if item.arg}
        routes.append({
            "method": method.upper(),
            "path": f"{prefix}{path}",
            "endpoint": node.name,
            "status_code": _literal(keywords.get("status_code")),
            "response_model": _literal(keywords.get("response_model")),
            "include_in_schema": _literal(keywords.get("include_in_schema")),
            "source": owner,
            "_line": (first_line, len(routes)),
        })
    return routes


def _router_imports(tree: ast.Module) -> dict[str, Path]:
    """Local name -> router module file, for ``from routers.x import y`` in any scope."""
    imports: dict[str, Path] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("routers."):
            module_path = ROOT / "app" / Path(*node.module.split(".")).with_suffix(".py")
            for alias in node.names:
                imports[alias.asname or alias.name] = module_path
    return imports


def _include_call(node: ast.AST) -> tuple[str, ast.Call] | None:
    """``<router>.include_router(create_x(...), ...)``: the factory name and the call."""
    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
        return None
    call = node.value
    if (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "include_router"
        and call.args
        and isinstance(call.args[0], ast.Call)
        and isinstance(call.args[0].func, ast.Name)
    ):
        return call.args[0].func.id, call
    return None


def _include_prefix(call: ast.Call, *, owner: str) -> str:
    node = next((item.value for item in call.keywords if item.arg == "prefix"), None)
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    raise ValueError(f"Non-static include_router prefix at {owner}:{call.lineno}")


def _router_factory_routes(path: Path, factory_name: str, *, outer_prefix: str = "") -> list[dict]:
    """A router factory's routes, nested ``include_router`` calls expanded in place."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    factory = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == factory_name
        ),
        None,
    )
    if factory is None:
        raise ValueError(f"Router factory {factory_name!r} not found in {path}")
    prefix = ""
    for node in ast.walk(factory):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "router" for target in targets):
            continue
        if isinstance(value, ast.Call) and (
            isinstance(value.func, ast.Name) and value.func.id == "APIRouter"
        ):
            prefix_node = next((item.value for item in value.keywords if item.arg == "prefix"), None)
            if prefix_node is not None and not (
                isinstance(prefix_node, ast.Constant) and isinstance(prefix_node.value, str)
            ):
                raise ValueError(f"Non-static router prefix in {path}")
            prefix = prefix_node.value if prefix_node is not None else ""
            break
    prefix = outer_prefix + prefix
    owner = path.relative_to(ROOT).as_posix()
    imports = _router_imports(tree)
    routes = []
    for node in ast.walk(factory):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            routes.extend(_decorated_routes(node, owner=owner, prefix=prefix))
            continue
        include = _include_call(node)
        if include is None or include[0] not in imports:
            continue
        nested = _router_factory_routes(
            imports[include[0]],
            include[0],
            outer_prefix=prefix + _include_prefix(include[1], owner=owner),
        )
        for index, route in enumerate(nested):
            route["_line"] = (include[1].lineno, index)
        routes.extend(nested)
    return sorted(routes, key=lambda item: item["_line"])


def extract_route_table() -> list[dict]:
    """Expand mounted routers at their exact include position in launch."""
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    router_imports = _router_imports(tree)

    launch_owner = LAUNCH.relative_to(ROOT).as_posix()
    routes: list[dict] = []

    def visit(statements: Iterable[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                routes.extend(_decorated_routes(node, owner=launch_owner))
                continue
            include = _include_call(node)
            if (
                include is not None
                and isinstance(include[1].func.value, ast.Name)
                and include[1].func.value.id == "api"
            ):
                factory_name, call = include
                router_path = router_imports.get(factory_name)
                if router_path is None:
                    raise ValueError(f"Cannot resolve mounted router factory {factory_name!r}")
                routes.extend(_router_factory_routes(
                    router_path, factory_name, outer_prefix=_include_prefix(call, owner=launch_owner),
                ))
                continue
            if isinstance(node, ast.If):
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, (ast.Try, ast.With, ast.AsyncWith)):
                visit(node.body)
                if isinstance(node, ast.Try):
                    for handler in node.handlers:
                        visit(handler.body)
                    visit(node.orelse)
                    visit(node.finalbody)

    visit(tree.body)
    for ordinal, route in enumerate(routes):
        route.pop("_line", None)
        route["ordinal"] = ordinal
    return routes


def _reads(path: Path, pattern: str) -> bool:
    return re.search(pattern, path.read_text(encoding="utf-8")) is not None


def _wire_entry(path: Path, target: str, classification: str, reason: str) -> dict:
    return {
        "file": path.relative_to(ROOT).as_posix(),
        "target": target,
        "classification": classification,
        "reason": reason,
    }


# Tests that name the refactor targets only to count their lines (scripts/size_ceilings.json).
LINE_COUNT_READERS = {"test_size_ceilings.py"}
LINE_COUNT_REASON = "Counts the file's lines against scripts/size_ceilings.json; never reads its contents."


def extract_wire_inventory() -> list[dict]:
    entries = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        if path.name == "test_architecture_contracts.py":
            continue
        source = path.read_text(encoding="utf-8")
        if path.name in LINE_COUNT_READERS:
            for target in ("app/_launch_runtime.py", "ui/src/stores/useStore.ts"):
                entries.append(_wire_entry(path, target, "architecture_rule", LINE_COUNT_REASON))
            continue
        if "_launch_runtime" in source:
            if path.name == "test_architecture_factory.py":
                classification = "behavior"
                reason = "Imports the lazy factory and checks its runtime boundary without reading launch source."
            elif path.name == "test_architecture_graph.py":
                classification = "architecture_rule"
                reason = "Tests the static graph extractor against synthetic launch-source fixtures, without importing runtime."
            elif "exec(compile(" in source:
                classification = "symbol_importable"
                reason = "Extracts selected launch symbols with AST/exec; migrate to direct imports when that domain moves."
            elif "ast.parse" in source:
                classification = "architecture_rule"
                reason = "Parses launch wiring intentionally; preserve the rule while changing its source location."
            else:
                classification = "fragile_source"
                reason = "Reads launch text directly and may need conversion when the referenced domain is extracted."
            entries.append(_wire_entry(path, "app/_launch_runtime.py", classification, reason))
        if "useStore.ts" in source:
            entries.append(_wire_entry(
                path,
                "ui/src/stores/useStore.ts",
                "fragile_source",
                "Python inspects TypeScript source; splitting useStore requires converting or relocating this contract.",
            ))
    for path in sorted((ROOT / "ui" / "tests").glob("*")):
        if not path.is_file() or path.suffix not in {".mjs", ".ts", ".tsx"}:
            continue
        if _reads(path, r"(?:from|import).*useStore|useStore\.ts"):
            graph_fixture = path.name == "architectureExtractor.test.mjs"
            entries.append(_wire_entry(
                path,
                "ui/src/stores/useStore.ts",
                "architecture_rule" if graph_fixture else "behavior",
                "Tests compiler-AST extraction against synthetic store fixtures, not the runtime facade."
                if graph_fixture else "Imports the public Zustand facade; it should survive slice extraction unchanged.",
            ))
    return entries


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _runtime_route_table(write: bool) -> int:
    """Write or check the served route table in a child process (it imports the full server)."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(
        [str(ROOT), str(ROOT / "app"), *filter(None, [os.environ.get("PYTHONPATH")])]
    )}
    command = [sys.executable, "-m", "tests.support.full_server", *(["--write"] if write else [])]
    result = subprocess.run(command, cwd=ROOT, env=env, check=False, capture_output=True, text=True)
    # The server prints its whole boot log; show it only when something failed.
    output = result.stdout + result.stderr
    if result.returncode != 0:
        print(output, file=sys.stderr)
    elif write:
        print(result.stdout.strip().splitlines()[-1])
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="refresh committed fixtures")
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="skip the served route table, which imports the full server (torch, FastAPI) in a child process",
    )
    args = parser.parse_args()
    payloads = {
        ROUTE_FIXTURE: {"version": 1, "routes": extract_route_table()},
        WIRE_FIXTURE: {"version": 1, "entries": extract_wire_inventory()},
    }
    if args.write:
        for path, value in payloads.items():
            _write_json(path, value)
        return 0 if args.static_only else _runtime_route_table(write=True)
    stale = []
    for path, expected in payloads.items():
        actual = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if actual != expected:
            stale.append(path.relative_to(ROOT).as_posix())
    if not args.static_only and _runtime_route_table(write=False) != 0:
        stale.append("tests/fixtures/route_table_runtime.json")
    if stale:
        raise SystemExit(f"Architecture fixtures are stale: {', '.join(stale)}. Run with --write and review the diff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
