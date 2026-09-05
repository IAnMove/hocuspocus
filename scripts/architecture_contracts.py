#!/usr/bin/env python3
"""Static architecture contracts that never import the HocusPocus runtime."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"
ROUTE_FIXTURE = ROOT / "tests" / "fixtures" / "route_table.json"
WIRE_FIXTURE = ROOT / "tests" / "fixtures" / "architecture_wire_inventory.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _literal(node: ast.AST | None):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node)


def _decorated_routes(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    owner: str,
    prefix: str = "",
) -> list[dict]:
    routes = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        method = decorator.func.attr.lower()
        if method not in HTTP_METHODS or not decorator.args:
            continue
        path = _literal(decorator.args[0])
        if not isinstance(path, str):
            raise ValueError(f"Non-static route path at {owner}:{decorator.lineno}")
        keywords = {item.arg: item.value for item in decorator.keywords if item.arg}
        routes.append({
            "method": method.upper(),
            "path": f"{prefix}{path}",
            "endpoint": node.name,
            "status_code": _literal(keywords.get("status_code")),
            "response_model": _literal(keywords.get("response_model")),
            "include_in_schema": _literal(keywords.get("include_in_schema")),
            "source": owner,
            "_line": decorator.lineno,
        })
    return routes


def _router_factory_routes(path: Path, factory_name: str) -> list[dict]:
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
            parsed_prefix = _literal(prefix_node)
            if parsed_prefix is not None and not isinstance(parsed_prefix, str):
                raise ValueError(f"Non-static router prefix in {path}")
            prefix = parsed_prefix or ""
            break
    owner = path.relative_to(ROOT).as_posix()
    routes = []
    for node in ast.walk(factory):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            routes.extend(_decorated_routes(node, owner=owner, prefix=prefix))
    return sorted(routes, key=lambda item: item["_line"])


def extract_route_table() -> list[dict]:
    """Expand mounted routers at their exact include position in launch."""
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    router_imports: dict[str, Path] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("routers."):
            module_path = ROOT / "app" / Path(*node.module.split(".")).with_suffix(".py")
            for alias in node.names:
                router_imports[alias.asname or alias.name] = module_path

    launch_owner = LAUNCH.relative_to(ROOT).as_posix()
    routes: list[dict] = []

    def visit(statements: Iterable[ast.stmt]) -> None:
        for node in statements:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                routes.extend(_decorated_routes(node, owner=launch_owner))
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                call = node.value
                if (
                    isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "api"
                    and call.func.attr == "include_router"
                    and call.args
                    and isinstance(call.args[0], ast.Call)
                    and isinstance(call.args[0].func, ast.Name)
                ):
                    factory_name = call.args[0].func.id
                    router_path = router_imports.get(factory_name)
                    if router_path is None:
                        raise ValueError(f"Cannot resolve mounted router factory {factory_name!r}")
                    routes.extend(_router_factory_routes(router_path, factory_name))
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


def extract_wire_inventory() -> list[dict]:
    entries = []
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        if path.name == "test_architecture_contracts.py":
            continue
        source = path.read_text(encoding="utf-8")
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="refresh committed fixtures")
    args = parser.parse_args()
    payloads = {
        ROUTE_FIXTURE: {"version": 1, "routes": extract_route_table()},
        WIRE_FIXTURE: {"version": 1, "entries": extract_wire_inventory()},
    }
    if args.write:
        for path, value in payloads.items():
            _write_json(path, value)
        return 0
    stale = []
    for path, expected in payloads.items():
        actual = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if actual != expected:
            stale.append(path.relative_to(ROOT).as_posix())
    if stale:
        raise SystemExit(f"Architecture fixtures are stale: {', '.join(stale)}. Run with --write and review the diff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
