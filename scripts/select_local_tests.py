#!/usr/bin/env python3
"""Select pytest targets for local runs and CI shards.

Unknown or empty inputs fail closed: they never produce an empty suite.
CI ``--group`` also refuses a broken partition so a shard cannot silently
drop tests.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "scripts" / "ci_test_groups.json"


class ManifestError(ValueError):
    """Invalid or unusable shard manifest."""


def posix_path(path: str | Path) -> str:
    text = str(path).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def discover_suite_files(root: Path) -> list[str]:
    """Automated pytest modules under tests/ (pytest python_files test_*.py)."""
    tests = root / "tests"
    if not tests.is_dir():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in tests.rglob("test_*.py")
        if path.is_file()
    )


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ManifestError(f"missing manifest: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"invalid manifest JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ManifestError("manifest must be an object")
    groups = payload.get("groups")
    if not isinstance(groups, list) or not groups:
        raise ManifestError("manifest groups must be a non-empty list")
    seen_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ManifestError("each group must be an object")
        group_id = group.get("id")
        paths = group.get("paths")
        if not isinstance(group_id, str) or not group_id:
            raise ManifestError("group id is required")
        if group_id in seen_ids:
            raise ManifestError(f"duplicate group id: {group_id}")
        seen_ids.add(group_id)
        if not isinstance(paths, list) or not paths:
            raise ManifestError(f"group {group_id} has no paths")
        if any(not isinstance(item, str) or not item for item in paths):
            raise ManifestError(f"group {group_id} paths must be non-empty strings")
    rules = payload.get("path_rules") or []
    if not isinstance(rules, list):
        raise ManifestError("path_rules must be a list")
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("prefix"), str):
            raise ManifestError("path rule prefix is required")
        paths = rule.get("paths")
        if not isinstance(paths, list) or not paths:
            raise ManifestError(f"path rule {rule.get('prefix')!r} has no paths")
    return payload


def grouped_paths(manifest: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for group in manifest["groups"]:
        for item in group["paths"]:
            path = posix_path(item)
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def group_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(group["id"]): group for group in manifest["groups"]}


def partition_errors(root: Path, manifest: dict[str, Any]) -> list[str]:
    discovered = discover_suite_files(root)
    discovered_set = set(discovered)
    owner: dict[str, str] = {}
    overlap: list[str] = []
    extra: list[str] = []
    for group in manifest["groups"]:
        group_id = str(group["id"])
        for raw in group["paths"]:
            path = posix_path(raw)
            if path in owner:
                overlap.append(path)
            else:
                owner[path] = group_id
            if path not in discovered_set:
                extra.append(path)
    missing = [path for path in discovered if path not in owner]
    errors: list[str] = []
    if missing:
        errors.append("missing from groups: " + ", ".join(missing))
    if extra:
        errors.append("not in automated suite: " + ", ".join(extra))
    if overlap:
        unique = []
        seen: set[str] = set()
        for path in overlap:
            if path not in seen:
                seen.add(path)
                unique.append(path)
        errors.append("in multiple groups: " + ", ".join(unique))
    return errors


def check_partition(root: Path, manifest: dict[str, Any]) -> None:
    errors = partition_errors(root, manifest)
    if errors:
        raise ManifestError("; ".join(errors))


def full_suite_paths(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Union of groups when the partition is exact; otherwise ``tests``."""
    if partition_errors(root, manifest):
        return ["tests"]
    paths = sorted(grouped_paths(manifest))
    return paths if paths else ["tests"]


def _prefix_matches(path: str, prefix: str) -> bool:
    prefix = posix_path(prefix)
    path = posix_path(path)
    if path == prefix:
        return True
    if prefix.endswith("/"):
        return path.startswith(prefix)
    return path.startswith(prefix + "/")


def match_rule_paths(path: str, manifest: dict[str, Any]) -> list[str] | None:
    best: list[str] | None = None
    best_len = -1
    for rule in manifest.get("path_rules") or []:
        prefix = posix_path(rule["prefix"])
        if _prefix_matches(path, prefix) and len(prefix) > best_len:
            best = [posix_path(item) for item in rule["paths"]]
            best_len = len(prefix)
    return best


def unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        item = posix_path(path)
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def select_paths(
    changed: list[str],
    root: Path,
    manifest: dict[str, Any],
) -> tuple[list[str], str, list[str]]:
    """Return ``(pytest_args, reason, unknown_paths)``.

    Reasons:
    - ``mapped``: every input resolved to test paths
    - ``unknown-path``: at least one input had no mapping (full suite)
    - ``empty-input``: no paths given (full suite)
    - ``empty-match``: mapping produced nothing (full suite)
    """
    grouped = set(grouped_paths(manifest))
    if not changed:
        return full_suite_paths(root, manifest), "empty-input", []
    targets: list[str] = []
    unknown: list[str] = []
    for raw in changed:
        path = posix_path(raw)
        if path in grouped:
            targets.append(path)
            continue
        mapped = match_rule_paths(path, manifest)
        if mapped is None:
            unknown.append(path)
        else:
            targets.extend(mapped)
    if unknown:
        return full_suite_paths(root, manifest), "unknown-path", unknown
    targets = unique_paths(targets)
    if not targets:
        return full_suite_paths(root, manifest), "empty-match", []
    return targets, "mapped", []


def ungrouped_suite_files(root: Path, manifest: dict[str, Any]) -> list[str]:
    """Automated tests that the committed manifest does not list yet."""
    owned: set[str] = set()
    for group in manifest["groups"]:
        owned.update(posix_path(item) for item in group["paths"])
    return [path for path in discover_suite_files(root) if path not in owned]


def group_paths(group_id: str, root: Path, manifest: dict[str, Any]) -> list[str]:
    """Return one shard. Ungrouped suite files go to the first group.

    ``--check-partition`` still fails on a stale manifest. ``--group`` must
    not drop those files: a new test module would otherwise turn every PR red
    and skip the tests.
    """
    groups = group_by_id(manifest)
    if group_id not in groups:
        known = ", ".join(sorted(groups))
        raise ManifestError(f"unknown group {group_id!r}; known: {known}")
    paths = unique_paths([posix_path(item) for item in groups[group_id]["paths"]])
    first_id = str(manifest["groups"][0]["id"])
    extra = ungrouped_suite_files(root, manifest) if group_id == first_id else []
    if extra:
        print(
            "select_local_tests: assigning ungrouped files to "
            + group_id
            + ": "
            + ", ".join(extra),
            file=sys.stderr,
        )
        paths = unique_paths(paths + extra)
    if not paths:
        raise ManifestError(f"empty group {group_id!r}")
    return paths


def _print_paths(paths: list[str]) -> None:
    sys.stdout.write("\n".join(paths) + ("\n" if paths else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        help="Changed files. Unknown paths select the full suite.",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--group", help="Emit one CI shard after a partition check")
    parser.add_argument(
        "--check-partition",
        action="store_true",
        help="Exit 2 if groups do not partition the automated suite",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a JSON object instead of pytest path lines",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run pytest -q on the selected paths (never with an empty list)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        manifest = load_manifest(args.manifest)
        if args.check_partition and args.group is None and not args.paths and not args.run:
            check_partition(root, manifest)
            print("partition ok", file=sys.stderr)
            return 0
        unknown: list[str] = []
        if args.group:
            if args.paths:
                print("do not combine --group with path arguments", file=sys.stderr)
                return 2
            selected = group_paths(args.group, root, manifest)
            reason = "group"
        else:
            selected, reason, unknown = select_paths(args.paths, root, manifest)
        if not selected:
            print("select_local_tests: refused empty suite", file=sys.stderr)
            return 2
        if reason == "unknown-path":
            print(
                "select_local_tests: unknown path "
                + ", ".join(unknown)
                + "; running full suite",
                file=sys.stderr,
            )
        elif reason == "empty-input":
            print(
                "select_local_tests: no paths given; running full suite",
                file=sys.stderr,
            )
        elif reason == "empty-match":
            print(
                "select_local_tests: mapping produced no tests; running full suite",
                file=sys.stderr,
            )
        elif reason == "group":
            print(
                f"select_local_tests: group {args.group} ({len(selected)} files)",
                file=sys.stderr,
            )
        else:
            print(
                f"select_local_tests: mapped {len(selected)} path(s)",
                file=sys.stderr,
            )
        if args.json:
            json.dump(
                {
                    "reason": reason,
                    "paths": selected,
                    "unknown": unknown,
                    "group": args.group,
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            _print_paths(selected)
        if args.run:
            return subprocess.call(
                [sys.executable, "-m", "pytest", "-q", *selected],
                cwd=root,
            )
        return 0
    except ManifestError as exc:
        print(f"select_local_tests: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
