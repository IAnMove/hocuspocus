#!/usr/bin/env python3
"""Extract a bounded Story Lab -> Director audio architecture graph.

The extractor is deliberately a static, scoped map.  Python route and service
calls are collected with :mod:`ast`; TypeScript calls are collected by the
TypeScript compiler API in ``ui/scripts/graphs/typescript_graph.mjs``.  The
two fragments are combined into a deterministic schema-v1 document.

Run from the repository root::

    python scripts/graphs/story_director_audio_flow.py
    python scripts/graphs/story_director_audio_flow.py \
      --output ui/public/dev/architecture/story-director-audio.json

``--backend-only`` is intentionally available for the provider-free Python
test suite.  The full command requires the UI's installed TypeScript
development dependency so that the frontend is never guessed with regexes.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable


SCHEMA_VERSION = 1
GENERATED_BY = "scripts/graphs/story_director_audio_flow.py"
BACKEND_ROUTE_FUNCS = (
    "adopt_audio",
    "upload_audio",
    "trim_uploaded_audio",
    "start_audio_analysis_job",
    "serve_file",
)
BACKEND_HELPERS = {
    "_stream_upload": "svc.upload_pipeline",
    "_transcode_upload": "svc.upload_pipeline",
    "_safe_join": "svc.serve_file_lookup",
    "_resolve_output_file": "svc.serve_file_lookup",
    "_resolve_request_media_path": "svc.resolve_request_path",
    "_publish_audio_analysis_job": "svc.publish_job",
}
TS_SCOPE_FILES = (
    "ui/src/features/stories/StoryLabPanel.tsx",
    "ui/src/components/Sidebar/DirectorPanel.tsx",
    "ui/src/components/Sidebar/DirectorChat.tsx",
    "ui/src/features/stories/storyProductionController.ts",
    "ui/src/api/director.ts",
    "ui/src/api/outputs.ts",
    "ui/src/stores/useStore.ts",
)
BACKEND_SCOPE_FILES = (
    "app/_launch_runtime.py",
    "tests/fixtures/route_table.json",
)
LIMITATIONS = [
    "The graph is restricted to the configured Story Lab to Director audio scope.",
    "Python edges use AST names and do not resolve dynamic imports or runtime dispatch.",
    "TypeScript edges use compiler-AST syntax and do not perform type or module resolution.",
    "Aliased calls, computed property names, and calls hidden behind dynamic values may be absent.",
    "Static call-site multiplicity is not execution count and does not prove runtime behaviour.",
    "source_hash identifies scoped source bytes only; it does not prove semantic completeness or correctness.",
]


class ArchitectureGraphError(RuntimeError):
    """A required source or contract is not available for a trustworthy map."""


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _position(node: ast.AST) -> dict[str, int]:
    return {
        "line": int(getattr(node, "lineno", 1)),
        "column": int(getattr(node, "col_offset", 0)) + 1,
    }


def _evidence(root: Path, path: Path, node: ast.AST) -> dict[str, Any]:
    return {"file": _relative_path(path, root), **_position(node)}


def _merge_evidence(target: list[dict[str, Any]], values: Iterable[dict[str, Any]]) -> None:
    seen = {(item["file"], item["line"], item["column"]) for item in target}
    for value in values:
        key = (value["file"], value["line"], value["column"])
        if key not in seen:
            target.append(value)
            seen.add(key)
    target.sort(key=lambda item: (item["file"], item["line"], item["column"]))


class GraphBuilder:
    """Deduplicate graph records while preserving evidence and multiplicity."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_node(
        self,
        node_id: str,
        layer: str,
        label: str,
        detail: str = "",
        evidence: Iterable[dict[str, Any]] = (),
    ) -> None:
        record = self.nodes.setdefault(
            node_id,
            {
                "id": node_id,
                "layer": layer,
                "label": label,
                "detail": detail,
                "evidence": [],
            },
        )
        _merge_evidence(record["evidence"], evidence)

    def add_edge(
        self,
        source: str,
        target: str,
        kind: str,
        label: str = "",
        weight: int = 1,
        evidence: Iterable[dict[str, Any]] = (),
    ) -> None:
        key = (source, target, kind)
        record = self.edges.setdefault(
            key,
            {
                "source": source,
                "target": target,
                "kind": kind,
                "label": label,
                "weight": 0,
                "evidence": [],
            },
        )
        record["weight"] += weight
        if label and not record["label"]:
            record["label"] = label
        _merge_evidence(record["evidence"], evidence)

    def records(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        nodes = [self.nodes[key] for key in sorted(self.nodes)]
        edges = [
            self.edges[key]
            for key in sorted(self.edges, key=lambda item: (item[0], item[1], item[2]))
        ]
        for record in nodes:
            record["evidence"].sort(key=lambda item: (item["file"], item["line"], item["column"]))
        for record in edges:
            record["evidence"].sort(key=lambda item: (item["file"], item["line"], item["column"]))
        return nodes, edges


def _required_paths(root: Path, paths: Iterable[str]) -> list[Path]:
    resolved: list[Path] = []
    missing: list[str] = []
    for relative in paths:
        path = root / relative
        if not path.is_file():
            missing.append(relative)
        else:
            resolved.append(path)
    if missing:
        raise ArchitectureGraphError(
            "Missing required architecture graph source(s): " + ", ".join(sorted(missing))
        )
    return resolved


def _load_routes(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "tests/fixtures/route_table.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchitectureGraphError(f"Cannot read route table: {exc}") from exc
    routes = payload.get("routes") if isinstance(payload, dict) else None
    if not isinstance(routes, list):
        raise ArchitectureGraphError("Route table has no routes list")
    by_endpoint = {
        item.get("endpoint"): item
        for item in routes
        if isinstance(item, dict) and isinstance(item.get("endpoint"), str)
    }
    missing = [name for name in BACKEND_ROUTE_FUNCS if name not in by_endpoint]
    if missing:
        raise ArchitectureGraphError(
            "Route table is missing required endpoint(s): " + ", ".join(missing)
        )
    return {name: by_endpoint[name] for name in BACKEND_ROUTE_FUNCS}


def _call_target(call: ast.Call) -> str | None:
    callee = call.func
    if isinstance(callee, ast.Name):
        return BACKEND_HELPERS.get(callee.id)
    if not isinstance(callee, ast.Attribute):
        return None
    if isinstance(callee.value, ast.Name) and callee.value.id == "resource_scheduler":
        return "svc.resource_scheduler"
    return BACKEND_HELPERS.get(callee.attr)


def _function_map(tree: ast.AST) -> dict[str, ast.AST]:
    functions: dict[str, ast.AST] = {}
    for item in ast.walk(tree):
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.setdefault(item.name, item)
    return functions


def _backend_detail(target: str) -> tuple[str, str]:
    details = {
        "svc.resolve_request_path": (
            "_resolve_request_media_path()",
            "app/_launch_runtime.py — shared resolver wrapper",
        ),
        "svc.upload_pipeline": (
            "_stream_upload / _transcode_upload",
            "app/_launch_runtime.py — spools + transcodes to PCM WAV",
        ),
        "svc.serve_file_lookup": (
            "_safe_join / _resolve_output_file",
            "app/_launch_runtime.py — workspace-confined lookup",
        ),
        "svc.publish_job": (
            "_publish_audio_analysis_job()",
            "app/_launch_runtime.py — durable job record",
        ),
        "svc.resource_scheduler": (
            "resource_scheduler.*_lane()",
            "app/services — GPU/CPU lane acquisition",
        ),
        "svc.resolve_permitted_path": (
            "resolve_permitted_media_path()",
            "app/services/media_paths.py — realpath/commonpath confinement",
        ),
    }
    return details.get(target, (target, "Static backend service target"))


def extract_backend_graph(root: Path) -> dict[str, Any]:
    """Extract the Python route/service fragment without invoking Node."""
    source_paths = _required_paths(root, BACKEND_SCOPE_FILES)
    launch_path = root / "app/_launch_runtime.py"
    try:
        tree = ast.parse(launch_path.read_text(encoding="utf-8"), filename=str(launch_path))
    except (OSError, SyntaxError) as exc:
        raise ArchitectureGraphError(f"Cannot parse app/_launch_runtime.py: {exc}") from exc

    routes = _load_routes(root)
    functions = _function_map(tree)
    missing_functions = [name for name in BACKEND_ROUTE_FUNCS if name not in functions]
    if missing_functions:
        raise ArchitectureGraphError(
            "Backend source is missing required function(s): " + ", ".join(missing_functions)
        )

    builder = GraphBuilder()
    for function_name in BACKEND_ROUTE_FUNCS:
        route = routes[function_name]
        function = functions[function_name]
        route_id = f"route.{function_name}"
        builder.add_node(
            route_id,
            "route",
            f"{route['method']} {route['path']}",
            f"app/_launch_runtime.py — {function_name}()",
            [_evidence(root, launch_path, function)],
        )
        for item in ast.walk(function):
            if not isinstance(item, ast.Call):
                continue
            target = _call_target(item)
            if target is None:
                continue
            label, detail = _backend_detail(target)
            builder.add_node(target, "service", label, detail, [_evidence(root, launch_path, item)])
            builder.add_edge(
                route_id,
                target,
                "call",
                evidence=[_evidence(root, launch_path, item)],
            )

    wrapper = functions.get("_resolve_request_media_path")
    wrapper_is_referenced = any(
        edge["target"] == "svc.resolve_request_path"
        for edge in builder.edges.values()
    )
    if wrapper is not None and wrapper_is_referenced:
        for item in ast.walk(wrapper):
            if not isinstance(item, ast.Call):
                continue
            if isinstance(item.func, ast.Name) and item.func.id == "resolve_permitted_media_path":
                target = "svc.resolve_permitted_path"
                label, detail = _backend_detail(target)
                builder.add_node(
                    target,
                    "service",
                    label,
                    detail,
                    [_evidence(root, launch_path, item)],
                )
                builder.add_edge(
                    "svc.resolve_request_path",
                    target,
                    "call",
                    evidence=[_evidence(root, launch_path, item)],
                )

    nodes, edges = builder.records()
    _validate_edge_endpoints(nodes, edges)
    return {
        "nodes": nodes,
        "edges": edges,
        "limitations": list(LIMITATIONS[:2]),
        "warnings": [],
        "source_files": [_relative_path(path, root) for path in source_paths],
    }


def _scoped_paths(root: Path) -> list[Path]:
    return _required_paths(root, (*BACKEND_SCOPE_FILES, *TS_SCOPE_FILES))


def _source_hash(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: _relative_path(item, root)):
        relative = _relative_path(path, root).encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _git_metadata(root: Path, paths: Iterable[Path]) -> tuple[str | None, bool, list[str]]:
    warnings: list[str] = []
    relative = [_relative_path(path, root) for path in paths]
    try:
        commit_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        status_result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", *relative],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        warnings.append("git metadata unavailable; source_commit is null and dirty is unknown")
        return None, True, warnings
    commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None
    if commit is None:
        warnings.append("git commit unavailable; source_commit is null and cleanliness is unknown")
    status_failed = status_result.returncode != 0
    if status_failed:
        warnings.append("git status failed; cleanliness is unknown")
    has_uncommitted_changes = bool(status_result.stdout.strip())
    dirty = has_uncommitted_changes or status_failed or commit is None
    if has_uncommitted_changes:
        warnings.append("scoped source files have uncommitted changes")
    elif dirty:
        warnings.append("scoped source cleanliness is unknown; dirty is set true")
    return commit, dirty, warnings


def _validate_edge_endpoints(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    node_ids = {item["id"] for item in nodes}
    dangling = sorted(
        {
            endpoint
            for edge in edges
            for endpoint in (edge["source"], edge["target"])
            if endpoint not in node_ids
        }
    )
    if dangling:
        raise ArchitectureGraphError(
            "Architecture graph has dangling edge endpoint(s): " + ", ".join(dangling)
        )


def _merge_fragment(builder: GraphBuilder, fragment: dict[str, Any]) -> None:
    for node in fragment.get("nodes", []):
        builder.add_node(
            node["id"],
            node["layer"],
            node["label"],
            node.get("detail", ""),
            node.get("evidence", []),
        )
    for edge in fragment.get("edges", []):
        builder.add_edge(
            edge["source"],
            edge["target"],
            edge["kind"],
            edge.get("label", ""),
            int(edge.get("weight", 0)),
            edge.get("evidence", []),
        )


def _typescript_fragment(root: Path) -> dict[str, Any]:
    script = root / "ui/scripts/graphs/typescript_graph.mjs"
    if not script.is_file():
        raise ArchitectureGraphError("Missing TypeScript graph extractor: ui/scripts/graphs/typescript_graph.mjs")
    try:
        result = subprocess.run(
            ["node", str(script), "--root", str(root)],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ArchitectureGraphError(f"Cannot start TypeScript graph extractor: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or "no diagnostic"
        raise ArchitectureGraphError(f"TypeScript graph extraction failed: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ArchitectureGraphError("TypeScript graph extractor returned invalid JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes"), list) or not isinstance(payload.get("edges"), list):
        raise ArchitectureGraphError("TypeScript graph extractor returned an invalid fragment")
    return payload


def build_graph(root: Path, *, backend_only: bool = False) -> dict[str, Any]:
    """Build the complete schema-v1 graph for ``root``."""
    root = root.resolve()
    backend = extract_backend_graph(root)
    paths = (
        _required_paths(root, BACKEND_SCOPE_FILES)
        if backend_only
        else _scoped_paths(root)
    )
    builder = GraphBuilder()
    _merge_fragment(builder, backend)
    limitations = list(LIMITATIONS)
    warnings = list(backend.get("warnings", []))
    if not backend_only:
        frontend = _typescript_fragment(root)
        _merge_fragment(builder, frontend)
        limitations.extend(frontend.get("limitations", []))
        warnings.extend(frontend.get("warnings", []))
    else:
        warnings.append("frontend extraction skipped by --backend-only")
    source_commit, dirty, git_warnings = _git_metadata(root, paths)
    warnings.extend(git_warnings)
    nodes, edges = builder.records()
    _validate_edge_endpoints(nodes, edges)
    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "scope": "Story Lab -> Director audio hand-off",
            "source_commit": source_commit,
            "dirty": dirty,
            "source_hash": _source_hash(root, paths),
            "generated_by": GENERATED_BY,
            "limitations": list(dict.fromkeys(limitations)),
            "warnings": list(dict.fromkeys(warnings)),
        },
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="repository root (default: inferred from this script)")
    parser.add_argument("--output", type=Path, default=None, help="write JSON here instead of stdout")
    parser.add_argument("--backend-only", action="store_true", help="skip the TypeScript compiler-API fragment")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    root = (args.root or Path(__file__).resolve().parents[2]).resolve()
    try:
        payload = build_graph(root, backend_only=args.backend_only)
    except ArchitectureGraphError as exc:
        print(f"architecture graph: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output is None:
        print(rendered, end="")
        return 0
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
