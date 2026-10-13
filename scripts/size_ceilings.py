#!/usr/bin/env python3
"""Line ceilings for the files the architecture refactor is splitting.

``scripts/size_ceilings.json`` names each file and the most lines it may have.
Three rules:

1. A file may not be longer than its ceiling. Move code out instead.
2. A file more than ``SLACK`` lines under its ceiling must lower it in the same
   PR, so the ceiling follows the real size (``--lower`` does it).
3. A ceiling may not rise against the PR base, and a file may not leave the
   list (``--base-file``; ``scripts/check_code_health_pr_base.sh`` runs it).

Lines are counted like ``wc -l``: the number of newline characters.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CEILINGS = ROOT / "scripts" / "size_ceilings.json"
SLACK = 100
LOWER = "python scripts/size_ceilings.py --lower"


def load(path: Path = CEILINGS) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(name): int(limit) for name, limit in payload["ceilings"].items()}


def line_count(path: Path) -> int:
    return path.read_bytes().count(b"\n")


def size_errors(root: Path, ceilings: dict[str, int], *, slack: int = SLACK) -> list[str]:
    """Rules 1 and 2 for every listed file."""
    errors = []
    for name, limit in sorted(ceilings.items()):
        path = root / name
        if not path.is_file():
            errors.append(f"{name} is listed in scripts/size_ceilings.json but does not exist; remove its entry.")
            continue
        lines = line_count(path)
        if lines > limit:
            errors.append(
                f"{name} has {lines:,} lines; its ceiling is {limit:,}. This file may only shrink: "
                "move the new code into app/routers or app/services (or a ui/src slice) instead."
            )
        elif limit - lines > slack:
            errors.append(
                f"{name} has {lines:,} lines, {limit - lines:,} under its ceiling of {limit:,}. "
                f"Lower the ceiling in this PR: run `{LOWER}` (it sets {name} to {lines:,}) "
                "and commit scripts/size_ceilings.json."
            )
    return errors


def raised_errors(base: dict[str, int], head: dict[str, int], root: Path = ROOT) -> list[str]:
    """Rule 3: no ceiling above the base's, no file dropped while it still exists."""
    errors = []
    for name, limit in sorted(base.items()):
        if name not in head:
            if (root / name).exists():
                errors.append(f"{name} left scripts/size_ceilings.json; ceilings may only go down.")
            continue
        if head[name] > limit:
            errors.append(
                f"The ceiling of {name} rose from {limit:,} to {head[name]:,}; ceilings may only go down. "
                "Move code out of the file instead."
            )
    return errors


def lower(root: Path = ROOT, path: Path = CEILINGS) -> list[str]:
    """Set every ceiling above its file's size to that size. Returns what changed."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed = []
    for name, limit in payload["ceilings"].items():
        file = root / name
        if not file.is_file():
            continue
        lines = line_count(file)
        if lines < int(limit):
            payload["ceilings"][name] = lines
            changed.append(f"{name}: {int(limit):,} -> {lines:,}")
    if changed:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lower", action="store_true", help="lower each ceiling to its file's current size")
    parser.add_argument("--base-file", type=Path, help="the PR base's size_ceilings.json: fail if a ceiling rose")
    args = parser.parse_args(argv)
    if args.lower:
        for line in lower() or ["no ceiling to lower"]:
            print(line)
        return 0
    if args.base_file is not None:
        if not args.base_file.is_file():
            return 0  # The base predates the ceilings.
        errors = raised_errors(load(args.base_file), load())
    else:
        errors = size_errors(ROOT, load())
    for error in errors:
        print(f"[size-ceilings] {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
