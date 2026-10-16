#!/usr/bin/env python3
"""Merge a ref and resolve the chores that conflict on every PR.

Changelog conflicts keep both sides. ``scripts/ci_test_groups.json`` keeps the
ref, then re-adds test files this branch added and recomputes both weights.
Fixtures are regenerated and staged. Any other conflicted file is listed and
left untouched (exit 2). A shard gap over 5 or a weight ratio over 1.25 fails
before that file is written (exit 1).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dev.merge_prep_lib import (
    BalanceError,
    apply_weights,
    format_merge_summary,
    resolve_changelog,
    resolve_test_groups,
)


CHANGELOG = "CHANGELOG.md"
GROUPS = "scripts/ci_test_groups.json"
FIXTURES = (
    "tests/fixtures/route_table.json",
    "tests/fixtures/architecture_wire_inventory.json",
    "tests/fixtures/route_table_runtime.json",
)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
    )


def _merge_head(root: Path) -> str:
    proc = _git(root, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _unmerged(root: Path) -> list[str]:
    proc = _git(root, "diff", "--name-only", "--diff-filter=U")
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def _show(root: Path, spec: str) -> str:
    proc = _git(root, "show", spec)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git show {spec} failed")
    return proc.stdout


def _branch_name(root: Path) -> str:
    proc = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    name = proc.stdout.strip()
    return name or "HEAD"


def _new_test_files(root: Path, base_sha: str) -> list[str]:
    proc = _git(root, "diff", "--name-only", "--diff-filter=A", f"{base_sha}...HEAD", "--", "tests")
    found: list[str] = []
    for raw in proc.stdout.splitlines():
        path = raw.strip().replace("\\", "/")
        name = Path(path).name
        if path.startswith("tests/") and name.startswith("test_") and name.endswith(".py"):
            found.append(path)
    return found


def _collect_weight(root: Path, paths: list[str]) -> int:
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [
            "nice", "-n", "10",
            sys.executable, "-m", "pytest",
            "--collect-only", "-q", "-p", "no:cacheprovider",
            *paths,
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    count = sum(1 for line in proc.stdout.splitlines() if "::" in line)
    if proc.returncode != 0 or count <= 0:
        detail = ""
        for line in (proc.stderr or proc.stdout).splitlines():
            if line.strip():
                detail = line.strip()
                break
        raise RuntimeError(f"pytest --collect-only failed ({proc.returncode}, {count} nodeids): {detail}")
    return count


def _resolve_changelog(root: Path) -> str:
    text = resolve_changelog(_show(root, ":2:" + CHANGELOG), _show(root, ":3:" + CHANGELOG))
    if "<<<<<<<" in text or ">>>>>>>" in text:
        raise RuntimeError("changelog resolver left conflict markers")
    (root / CHANGELOG).write_text(text, encoding="utf-8")
    added = _git(root, "add", "--", CHANGELOG)
    if added.returncode != 0:
        raise RuntimeError(added.stderr.strip() or "git add CHANGELOG.md failed")
    return "kept both sides"


def _weight_sentence(branch: str, ref_sha: str, weights: dict[str, int]) -> str:
    day = dt.date.today().isoformat()
    return (
        f"Merge of {branch} with {ref_sha} ({day}): "
        f"pytest --collect-only per group gives python-a {weights['python-a']} "
        f"and python-b {weights['python-b']}."
    )


def _resolve_groups(root: Path) -> str:
    base_sha = _git(root, "merge-base", "HEAD", "MERGE_HEAD").stdout.strip()
    if not base_sha:
        raise RuntimeError("cannot resolve merge-base of HEAD and MERGE_HEAD")
    base = json.loads(_show(root, f"{base_sha}:{GROUPS}"))
    ours = json.loads(_show(root, ":2:" + GROUPS))
    theirs = json.loads(_show(root, ":3:" + GROUPS))
    resolved = resolve_test_groups(base, ours, theirs, _new_test_files(root, base_sha))
    # A conflicted manifest breaks collection imports. Write the resolved JSON
    # first, and stage it only after the weight check passes.
    preliminary = json.dumps(resolved, indent=2, ensure_ascii=False) + "\n"
    (root / GROUPS).write_text(preliminary, encoding="utf-8")
    weights = {group["id"]: _collect_weight(root, list(group["paths"])) for group in resolved["groups"]}
    ref_sha = _git(root, "rev-parse", "--short=9", "MERGE_HEAD").stdout.strip()
    final = apply_weights(resolved, weights, _weight_sentence(_branch_name(root), ref_sha, weights))
    text = json.dumps(final, indent=2, ensure_ascii=False) + "\n"
    (root / GROUPS).write_text(text, encoding="utf-8")
    added = _git(root, "add", "--", GROUPS)
    if added.returncode != 0:
        raise RuntimeError(added.stderr.strip() or "git add ci_test_groups.json failed")
    counts = [len(group["paths"]) for group in final["groups"]]
    return (
        f"ref plus branch tests; python-a {weights['python-a']} ({counts[0]} files), "
        f"python-b {weights['python-b']} ({counts[1]} files)"
    )


def _regenerate_fixtures(root: Path) -> str:
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = ""
    proc = subprocess.run(
        [sys.executable, "scripts/architecture_contracts.py", "--write"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = ""
        for line in (proc.stderr or proc.stdout).splitlines():
            if line.strip():
                detail = line.strip()
        raise RuntimeError(f"architecture_contracts.py --write failed: {detail}")
    for rel in FIXTURES:
        if (root / rel).is_file():
            added = _git(root, "add", "--", rel)
            if added.returncode != 0:
                raise RuntimeError(added.stderr.strip() or f"git add {rel} failed")
    return "regenerated and staged"


def _start_merge(root: Path, ref: str) -> subprocess.CompletedProcess[str]:
    return _git(root, "merge", "--no-commit", "--no-ff", ref)


def _finish(root: Path, ref: str, commit: bool) -> int:
    rows = [f"ref: {ref}", f"branch: {_branch_name(root)}"]
    unmerged = _unmerged(root)
    try:
        if CHANGELOG in unmerged:
            rows.append("changelog: " + _resolve_changelog(root))
        else:
            rows.append("changelog: no conflict")
        if GROUPS in unmerged:
            rows.append("ci_test_groups: " + _resolve_groups(root))
        else:
            rows.append("ci_test_groups: no conflict")
    except BalanceError as exc:
        rows.append(f"balance: FAIL {exc}")
        sys.stdout.write(format_merge_summary(rows))
        return 1
    except (RuntimeError, ValueError, json.JSONDecodeError, OSError) as exc:
        rows.append(f"error: {exc}")
        sys.stdout.write(format_merge_summary(rows))
        return 1
    others = [path for path in _unmerged(root) if path not in {CHANGELOG, GROUPS}]
    if others:
        rows.append(f"other conflicts: {len(others)} (not touched)")
        rows.extend(others)
        sys.stdout.write(format_merge_summary(rows))
        return 2
    try:
        rows.append("fixtures: " + _regenerate_fixtures(root))
    except RuntimeError as exc:
        rows.append(f"fixtures: FAIL {exc}")
        sys.stdout.write(format_merge_summary(rows))
        return 1
    if not commit:
        rows.append("commit: not requested (--commit to finish)")
        sys.stdout.write(format_merge_summary(rows))
        return 0
    committed = _git(root, "commit", "--no-edit")
    if committed.returncode != 0:
        detail = (committed.stderr or committed.stdout).strip().splitlines()
        rows.append("commit: FAIL " + (detail[0] if detail else "git commit failed"))
        sys.stdout.write(format_merge_summary(rows))
        return 1
    sha = _git(root, "rev-parse", "--short=9", "HEAD").stdout.strip()
    rows.append(f"commit: {sha}")
    sys.stdout.write(format_merge_summary(rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="origin/development")
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args(argv)
    if not _merge_head(ROOT):
        started = _start_merge(ROOT, args.ref)
        if not _merge_head(ROOT):
            text = (started.stdout + "\n" + started.stderr).strip()
            if "Already up to date" in text:
                sys.stdout.write(format_merge_summary([
                    "merge: already up to date",
                    f"ref: {args.ref}",
                    f"branch: {_branch_name(ROOT)}",
                ]))
                return 0
            first = text.splitlines()[0] if text else "git merge failed"
            sys.stdout.write(format_merge_summary([
                "merge: refused",
                f"ref: {args.ref}",
                first,
            ]))
            return 2
    return _finish(ROOT, args.ref, args.commit)


if __name__ == "__main__":
    raise SystemExit(main())
