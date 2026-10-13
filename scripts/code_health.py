#!/usr/bin/env python3
"""Report first-party LOC and cyclomatic complexity, with a CI ratchet.

The Python metric is calculated with the standard-library AST. UI complexity
comes from ESLint's built-in ``complexity`` rule when ``ui/node_modules`` is
installed. Only git-tracked, first-party production code affects the ratchet.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from code_quality_score import COMPONENT_WEIGHTS, quality_score, score_delta  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "scripts" / "code_health_baseline.json"
DEFAULT_EXCEPTIONS = ROOT / "scripts" / "code_health_exceptions.json"
PYTHON_EXACT = {"app/_launch_runtime.py", "app/launch.py", "app/wgp.py"}
PYTHON_PREFIXES = ("app/services/", "app/routers/")
UI_PREFIX = "ui/src/"
UI_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
HOTSPOT_LINES = 1_000
COMPLEXITY_WARNING = 15
POLICY_VERSION = "code-health-policy-v1"
POLICY = {
    "complexity_warning": COMPLEXITY_WARNING,
    "line_growth_pct": 0.03,
    "line_growth_min": 2_000,
    "complex_growth_budget": 5,
    "max_complexity_delta": 3,
    "complexity_hotspot_delta": 5,
    "new_complexity_hotspot_limit": 25,
    "hotspot_lines": HOTSPOT_LINES,
    "new_hotspot_limit": 1_200,
    "hotspot_growth_pct": 0.02,
    "hotspot_growth_min": 75,
    "hotspot_growth_max": 600,
}
EXCEPTION_FIELDS = ("path", "rule", "reason", "owner", "issue", "expires")
WAIVABLE_RULES = {"hotspot_growth", "complexity_hotspot"}
# The failure subject (text before the first ";") each waivable rule covers;
# group 1 is the file, which must equal the waiver's path exactly.
WAIVER_SUBJECTS = {
    "hotspot_growth": re.compile(r"hotspot (.+) grew [\d,]+ lines"),
    "complexity_hotspot": re.compile(r"(?:new )?complexity hotspot (.+) (?:is \d+|increased by more than \d+)"),
}
# Tracked app/**/*.py outside the measured scope fails as unmeasured product
# code, except vendored engine code and the files that were already there on
# 2026-10-13. Neither list may grow versus the PR base (compare() checks it).
UNMEASURED_VENDOR_PREFIXES = (
    "app/models/",
    "app/plugins/",
    "app/postprocessing/",
    "app/preprocessing/",
    "app/shared/",
)
UNMEASURED_BASELINE = (
    "app/app_identity.py",
    "app/core_runtime.py",
    "app/scripts/benchmark_h3.py",
    "app/scripts/benchmark_h3_memory.py",
    "app/scripts/benchmark_h3_report.py",
    "app/scripts/benchmark_h3_review.py",
    "app/scripts/benchmark_h3_speech.py",
    "app/scripts/benchmark_qwen21_turbo.py",
    "app/scripts/install_gguf_kernels.py",
    "app/scripts/task_db_maintenance.py",
    "app/setup.py",
)
# Move and split notes are reported with the warnings but are not warnings.
NOTE_PREFIXES = ("moved: ", "split: ", "split not credited: ")


@dataclass(frozen=True)
class FunctionMetric:
    path: str
    name: str
    line: int
    complexity: int
    # Normalized-AST hash, only for Python functions at COMPLEXITY_WARNING+.
    fingerprint: str = field(default="", compare=False)

    def as_dict(self) -> dict:
        return {"path": self.path, "name": self.name, "line": self.line, "complexity": self.complexity}


class _DecisionCounter(ast.NodeVisitor):
    """Classic McCabe-style decisions inside one Python function."""

    def __init__(self) -> None:
        self.decisions = 0

    def visit_If(self, node: ast.If) -> None:
        self.decisions += 1
        self.generic_visit(node)

    visit_IfExp = visit_If

    def visit_For(self, node: ast.For) -> None:
        self.decisions += 1
        self.generic_visit(node)

    visit_AsyncFor = visit_For
    visit_While = visit_For

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.decisions += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.decisions += 1
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.decisions += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.decisions += max(0, len(node.cases) - 1)
        self.generic_visit(node)

    def visit_match_case(self, node: ast.match_case) -> None:
        if node.guard is not None:
            self.decisions += 1
        self.generic_visit(node)

    # A nested callable has its own metric and must not inflate its parent.
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef


_DOCSTRING_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _has_docstring(body: list) -> bool:
    first = body[0] if body else None
    return (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    )


def _serialize(node: object, out: list[str], *, top: bool = False) -> None:
    """``ast.dump`` without positions, docstrings or the top def's name/decorators."""
    if isinstance(node, ast.AST):
        out.append(type(node).__name__ + "(")
        for name, value in ast.iter_fields(node):
            if top and name in {"name", "decorator_list"}:
                continue
            if name == "body" and isinstance(node, _DOCSTRING_SCOPES) and _has_docstring(value):
                value = value[1:]
            out.append(name + "=")
            _serialize(value, out)
            out.append(",")
        out.append(")")
    elif isinstance(node, list):
        out.append("[")
        for item in node:
            _serialize(item, out)
            out.append(",")
        out.append("]")
    else:
        out.append(repr(node))


def python_fingerprint(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Hash a function's code, ignoring docstrings, comments and positions.

    Nothing is renamed. The node type (sync or async), arguments, return
    annotation and body are hashed, with the docstring of every def and class
    inside removed. The function's own name and its decorators are left out:
    moves are matched by name separately, and a route moved from
    ``@app.post`` in launch to ``@router.post`` in a router changes only its
    decorator, which does not count towards complexity. Comments never reach
    the AST and positions are not serialized.
    """
    out: list[str] = []
    _serialize(node, out, top=True)
    return hashlib.sha256("".join(out).encode("utf-8")).hexdigest()[:20]


class _PythonFunctionCollector(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.scope: list[str] = []
        self.metrics: list[FunctionMetric] = []

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        counter = _DecisionCounter()
        for statement in node.body:
            counter.visit(statement)
        name = ".".join((*self.scope, node.name))
        complexity = 1 + counter.decisions
        fingerprint = ""
        if complexity >= COMPLEXITY_WARNING:
            fingerprint = python_fingerprint(node)
        self.metrics.append(FunctionMetric(self.path, name, node.lineno, complexity, fingerprint))
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        capture_output=True,
        check=True,
    )
    return [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]


def _is_product(path: str) -> bool:
    if path.endswith((".md", ".mdx", ".txt", ".json")):
        return False
    if path in PYTHON_EXACT or (path.endswith(".py") and path.startswith(PYTHON_PREFIXES)):
        return True
    return path.startswith(UI_PREFIX) and Path(path).suffix in UI_SUFFIXES


def _unmeasured_product(tracked: list[str]) -> list[str]:
    """Tracked app/**/*.py that the ratchet does not measure and is not vendored."""
    return sorted(
        path for path in tracked
        if path.startswith("app/") and path.endswith(".py")
        and not _is_product(path)
        and not path.startswith(UNMEASURED_VENDOR_PREFIXES)
    )


def _unmeasured_scope(tracked: list[str]) -> dict:
    """What the ratchet does not measure, for compare() to hold it in place.

    ``files`` gives each baseline file's lines and highest function
    complexity, so a baseline file cannot quietly absorb code moved out of
    the measured scope. ``vendor_files`` lets compare() list new vendored
    files for reviewers.
    """
    tracked_set = set(tracked)
    files = {}
    for path in UNMEASURED_BASELINE:
        if path in tracked_set and (ROOT / path).is_file():
            complexities = [item.complexity for item in _python_complexity([path])]
            files[path] = {"lines": _line_count(ROOT / path)[0], "max_complexity": max(complexities, default=0)}
    return {
        "paths": _unmeasured_product(tracked),
        "vendor_prefixes": list(UNMEASURED_VENDOR_PREFIXES),
        "allowed": list(UNMEASURED_BASELINE),
        "files": files,
        "vendor_files": sorted(
            path for path in tracked if path.endswith(".py") and path.startswith(UNMEASURED_VENDOR_PREFIXES)
        ),
    }


def _ui_name(label: str) -> str:
    """The identifier in an ESLint label such as "Async method 'startGeneration'".

    Anonymous functions ("Arrow function", "Constructor") have no name and so
    can never be matched as a move or a split.
    """
    match = re.search(r"'([^']+)'$", label)
    return match.group(1) if match else ""


def _matchable_name(item: FunctionMetric) -> str:
    return item.name if item.path.endswith(".py") else _ui_name(item.name)


def _split_stem(name: str) -> str:
    return name.rsplit(".", 1)[-1].lstrip("_")


def _parent_candidates(name: str) -> tuple[list[str], list[str]]:
    """Names a split piece called ``name`` may come from (see ``_carved_from``).

    Returns (qualified names it is nested in, last-part stems it extends).
    """
    nested = [name[:index] for index, char in enumerate(name) if char == "."]
    stem = _split_stem(name)
    stems = [
        stem[:index] for index in range(1, len(stem))
        if stem[index] == "_" or stem[index].isupper() or stem[index].isdigit()
    ]
    return nested, stems


def _related_below_warning(functions: list[FunctionMetric], complex_: list[FunctionMetric]) -> list[FunctionMetric]:
    """Functions under COMPLEXITY_WARNING that split accounting needs.

    These are every function that shares a name with a complex one, plus every
    function whose name makes it a split parent of a complex one (see
    ``_carved_from``). With them, every instance of a parent's name is in both
    reports, so compare() sees the parent's full drop even below the warning
    level, without recording all functions.
    """
    by_name: dict[tuple[bool, str], list[FunctionMetric]] = {}
    by_stem: dict[tuple[bool, str], list[FunctionMetric]] = {}
    for item in functions:
        name = _matchable_name(item)
        if item.complexity >= COMPLEXITY_WARNING or not name:
            continue
        python = item.path.endswith(".py")
        by_name.setdefault((python, name), []).append(item)
        by_stem.setdefault((python, _split_stem(name)), []).append(item)
    found: dict[int, FunctionMetric] = {}
    for item in complex_:
        python = item.path.endswith(".py")
        name = _matchable_name(item)
        nested, stems = _parent_candidates(name)
        groups = [by_name.get((python, key), []) for key in (name, *nested)]
        groups += [by_stem.get((python, key), []) for key in stems]
        for group in groups:
            found.update((id(candidate), candidate) for candidate in group)
    return list(found.values())


def _fingerprint_records(functions: list[FunctionMetric]) -> list[dict]:
    """Move and split evidence: every function at COMPLEXITY_WARNING+.

    Also the weaker functions that split accounting needs (see
    ``_related_below_warning``). Python records at COMPLEXITY_WARNING+ carry a normalized-AST hash.
    UI records carry only the name and complexity (``hash`` is None): ESLint
    reports where a function's head is, not its body, so there is nothing to
    hash without a second parse.
    """
    complex_ = [item for item in functions if item.complexity >= COMPLEXITY_WARNING]
    records = []
    for item in [*complex_, *_related_below_warning(functions, complex_)]:
        python = item.path.endswith(".py")
        records.append({
            "path": item.path,
            "name": _matchable_name(item),
            "line": item.line,
            "complexity": item.complexity,
            "hash": (item.fingerprint or None) if python else None,
        })
    return sorted(records, key=lambda record: (record["path"], record["line"], record["name"]))


def _line_count(path: Path) -> tuple[int, int]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return len(lines), sum(bool(line.strip()) for line in lines)


def _python_complexity(paths: list[str]) -> list[FunctionMetric]:
    metrics: list[FunctionMetric] = []
    for relative in paths:
        if not relative.endswith(".py"):
            continue
        source = (ROOT / relative).read_text(encoding="utf-8")
        collector = _PythonFunctionCollector(relative)
        collector.visit(ast.parse(source, filename=relative))
        metrics.extend(collector.metrics)
    return metrics


def _ui_complexity(required: bool) -> list[FunctionMetric]:
    eslint = ROOT / "ui" / "node_modules" / "eslint" / "bin" / "eslint.js"
    if not eslint.exists():
        if required:
            raise RuntimeError("UI dependencies are missing; run `cd ui && npm ci`")
        print("WARN: UI complexity unavailable (run `cd ui && npm ci`).", file=sys.stderr)
        return []
    result = subprocess.run(
        [
            "node", str(eslint), "src", "--format", "json", "--rule",
            'complexity: ["error", 0]',
        ],
        cwd=ROOT / "ui",
        text=True,
        capture_output=True,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(f"ESLint complexity scan failed: {result.stderr.strip()}")
    if not result.stdout.strip():
        raise RuntimeError(f"ESLint produced no JSON: {result.stderr.strip()}")
    reports = json.loads(result.stdout)
    metrics: list[FunctionMetric] = []
    pattern = re.compile(r"complexity of (\d+)")
    for report in reports:
        fatal = next((item for item in report["messages"] if item.get("fatal")), None)
        if fatal:
            raise RuntimeError(f"ESLint could not parse {report['filePath']}: {fatal['message']}")
        path = Path(report["filePath"]).resolve().relative_to(ROOT).as_posix()
        for message in report["messages"]:
            if message.get("ruleId") != "complexity":
                continue
            match = pattern.search(message["message"])
            if not match:
                continue
            label = message["message"].split(" has a complexity", 1)[0]
            metrics.append(FunctionMetric(path, label, int(message["line"]), int(match.group(1))))
    return metrics


def collect(*, require_ui: bool) -> dict:
    tracked = _tracked_files()
    product = sorted(path for path in tracked if _is_product(path))
    tests = sorted(
        path for path in tracked
        if path.startswith(("tests/", "ui/tests/", "ui/e2e/"))
        and Path(path).suffix in ({".py"} | UI_SUFFIXES)
    )
    file_lines: dict[str, int] = {}
    non_blank = 0
    for relative in product:
        physical, source = _line_count(ROOT / relative)
        file_lines[relative] = physical
        non_blank += source
    test_lines = sum(_line_count(ROOT / relative)[0] for relative in tests)
    python_functions = _python_complexity(product)
    ui_product = [path for path in product if path.startswith(UI_PREFIX)]
    ui_functions = _ui_complexity(require_ui)
    if require_ui and ui_product and not ui_functions:
        raise RuntimeError(
            "UI complexity produced no function metrics; missing UI measurement is not a pass"
        )
    functions = python_functions + ui_functions
    ranked = sorted(functions, key=lambda item: (-item.complexity, item.path, item.line))
    complexity_by_file: dict[str, int] = {}
    for item in functions:
        complexity_by_file[item.path] = max(complexity_by_file.get(item.path, 0), item.complexity)
    hotspots = dict(sorted(
        ((path, lines) for path, lines in file_lines.items() if lines >= HOTSPOT_LINES),
        key=lambda item: (-item[1], item[0]),
    ))
    head_sha = str(os.environ.get("HEAD_SHA") or "").strip()
    base_sha = str(os.environ.get("BASE_SHA") or "").strip()
    if not head_sha:
        try:
            head_sha = subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                text=True,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            head_sha = ""
    report = {
        "version": 1,
        "policy_version": POLICY_VERSION,
        "policy": dict(POLICY),
        "measurement": {
            "python": "complete",
            "ui": "complete" if ui_functions or not ui_product else "missing",
            "head_sha": head_sha,
            "base_sha": base_sha,
        },
        "product_paths": product,
        "summary": {
            "production_files": len(product),
            "production_lines": sum(file_lines.values()),
            "production_non_blank_lines": non_blank,
            "test_files": len(tests),
            "test_lines": test_lines,
            "functions_measured": len(functions),
            "complex_functions": sum(item.complexity >= COMPLEXITY_WARNING for item in functions),
            "max_complexity": ranked[0].complexity if ranked else 0,
            # Decision points over every measured function (complexity - 1
            # each). Moving or splitting code keeps it; new logic raises it.
            "decisions": sum(item.complexity - 1 for item in functions),
        },
        "hotspots": hotspots,
        "complexity_hotspots": dict(sorted(
            ((path, value) for path, value in complexity_by_file.items() if value >= COMPLEXITY_WARNING),
            key=lambda item: (-item[1], item[0]),
        )),
        "top_complexity": [item.as_dict() for item in ranked[:30]],
        "fingerprints": _fingerprint_records(functions),
        "unmeasured": _unmeasured_scope(tracked),
    }
    report["quality"] = quality_score(report)
    return report


def _records(report: dict) -> list[dict] | None:
    """Function fingerprints of a report; None when the analyzer did not record them."""
    records = report.get("fingerprints")
    return records if isinstance(records, list) else None


def _is_python(record: dict) -> bool:
    return str(record["path"]).endswith(".py")


Indexed = tuple[int, dict]


def _without_paths(records: list[Indexed], stayed: Counter) -> list[Indexed]:
    """Drop, per path, as many records as stayed at that path."""
    left = Counter(stayed)
    kept = []
    for index, record in sorted(records, key=lambda item: (item[1]["path"], item[1]["line"], item[0])):
        if left[record["path"]] > 0:
            left[record["path"]] -= 1
            continue
        kept.append((index, record))
    return kept


def _pair_moves(before: list[Indexed], after: list[Indexed], *, by_hash: bool) -> dict[int, dict]:
    stayed = Counter(item["path"] for _, item in before) & Counter(item["path"] for _, item in after)
    gone = [record for _, record in _without_paths(before, stayed)]
    arrived = _without_paths(after, stayed)
    if by_hash:
        # Identical code: pair in file order; any surplus in `arrived` is a copy.
        return {index: source for (index, _), source in zip(arrived, gone)}
    moves: dict[int, dict] = {}
    available = sorted(gone, key=lambda item: item["complexity"])
    for index, target in sorted(arrived, key=lambda item: item[1]["complexity"]):
        source = next((item for item in available if item["complexity"] >= target["complexity"]), None)
        if source is not None:
            available.remove(source)
            moves[index] = source
    return moves


def verified_moves(current: dict, baseline: dict) -> dict[int, dict]:
    """Functions at COMPLEXITY_WARNING+ that left their base file for another file.

    Keyed by the index of the current record in ``current["fingerprints"]``
    (two UI functions can share a line); each value is the base record. A
    Python move needs the same qualified name and the same normalized-AST
    hash. UI records have no hash, so a UI move needs the same name and a
    complexity no higher than the base function's, which is its ceiling. A
    base function still at its old path cannot be claimed: a copy is new code.
    """
    now, old = _records(current), _records(baseline)
    if now is None or old is None:
        return {}
    groups: dict[tuple, tuple[list[Indexed], list[Indexed]]] = {}
    for side, records in ((0, old), (1, now)):
        for index, record in enumerate(records):
            python = _is_python(record)
            if record["complexity"] < COMPLEXITY_WARNING or not record.get("name"):
                continue
            if python and not record.get("hash"):
                continue
            key = (python, record["name"], record.get("hash") if python else None)
            groups.setdefault(key, ([], []))[side].append((index, record))
    moves: dict[int, dict] = {}
    for (python, _, _), (before, after) in groups.items():
        moves.update(_pair_moves(before, after, by_hash=python))
    return moves


def _move_notes(current: dict, moves: dict[int, dict]) -> list[str]:
    records = _records(current) or []
    notes = []
    for index in sorted(moves, key=lambda key: (-records[key]["complexity"], records[key]["path"], records[key]["line"])):
        target, source = records[index], moves[index]
        ceiling = "" if target["complexity"] == source["complexity"] else f", ceiling {source['complexity']}"
        notes.append(
            f"moved: {target['name']} (complexity {target['complexity']}{ceiling}) "
            f"from {source['path']} to {target['path']}"
        )
    limit = 30
    if len(notes) > limit:
        notes = notes[:limit] + [f"moved: +{len(notes) - limit} more functions at complexity >= {COMPLEXITY_WARNING}"]
    return notes


def _where(records: list[dict]) -> str:
    return ", ".join(sorted({f"{item['path']} ({item['complexity']})" for item in records})[:3])


def _not_moved_reason(record: dict, current: dict, baseline: dict) -> str:
    """Why a function over a limit did not get move credit (for the failure text)."""
    label = f"{record['name'] or 'an anonymous function'} ({record['complexity']})"
    if not record["name"]:
        return f"{label} has no name to match"
    old = _records(baseline)
    if old is None:
        return f"{label}: the base report has no function fingerprints"
    python = _is_python(record)
    same = [item for item in old if item.get("name") == record["name"] and _is_python(item) == python]
    if not same:
        return f"{label} is not in the base"
    if python:
        matching = [item for item in same if item.get("hash") == record["hash"]]
    else:
        matching = [item for item in same if item["complexity"] >= record["complexity"]]
    if not matching:
        if python:
            return f"{label} has the name of base {_where(same)} but different code, so it counts as new"
        return f"{label} rose above its base ceiling {_where(same)}"
    present = {(item["path"], item["name"], item.get("hash")) for item in _records(current) or []}
    still = [item for item in matching if (item["path"], item["name"], item.get("hash")) in present]
    if still:
        return f"{label} is a copy: the base function is still at {_where(still)}"
    return f"{label} is a copy: another file already took base {_where(matching)} as its move"


def _complexity_rise_failure(
    path: str, limit: int, message: str, current: dict, baseline: dict, moves: dict[int, dict],
) -> str | None:
    """None when every function over ``limit`` in ``path`` is a verified move."""
    above = [
        (index, item) for index, item in enumerate(_records(current) or [])
        if item["path"] == path and item["complexity"] > limit
    ]
    unmoved = [item for index, item in above if index not in moves]
    if above and not unmoved:
        return None
    if unmoved:
        reasons = [_not_moved_reason(item, current, baseline) for item in unmoved[:3]]
        more = "" if len(unmoved) <= 3 else f"; +{len(unmoved) - 3} more"
        message += "; not a verified move: " + "; ".join(reasons) + more
    return message


def _complexity_hotspot_findings(
    current: dict, baseline: dict, moves: dict[int, dict],
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    failures: list[str] = []
    old_complexity = baseline.get("complexity_hotspots", {})
    delta = int(POLICY["complexity_hotspot_delta"])
    for path, new_value in current.get("complexity_hotspots", {}).items():
        old_value = old_complexity.get(path)
        if old_value is None:
            limit = int(POLICY["new_complexity_hotspot_limit"])
            message = f"new complexity hotspot {path} is {new_value}; limit is {limit}"
        else:
            if new_value > old_value:
                warnings.append(f"complexity hotspot {path} rose {old_value} -> {new_value}")
            limit = old_value + delta
            message = f"complexity hotspot {path} increased by more than {delta}"
        if new_value <= limit:
            continue
        failure = _complexity_rise_failure(path, limit, message, current, baseline, moves)
        if failure:
            failures.append(failure)
    return warnings, failures


def _carved_from(child: str, parent: str) -> bool:
    """Name rule for a split: a nested def of the parent, or the parent's name plus a suffix.

    ``_run_generation`` -> ``_run_generation_prepare`` or ``_run_generation.prepare``;
    ``startGeneration`` -> ``startGenerationAudio``. Leading underscores and
    class or module qualifiers are ignored when comparing the last name part.
    """
    if child.startswith(parent + "."):
        return True
    stem, root = _split_stem(child), _split_stem(parent)
    if not root or len(stem) <= len(root) or not stem.startswith(root):
        return False
    following = stem[len(root)]
    return following == "_" or following.isupper() or following.isdigit()


def _split_parent(child: dict, parents: dict[tuple[bool, str], list[dict]]) -> tuple[bool, str] | None:
    python = _is_python(child)
    candidates = [
        key for key in parents
        if key[0] == python and _carved_from(child["name"], key[1])
    ]
    return max(candidates, key=lambda key: len(key[1])) if candidates else None


def _added_decisions(current: dict, baseline: dict) -> int | None:
    """Decision points the change adds over all measured code; None if unknown."""
    now = (current.get("summary") or {}).get("decisions")
    old = (baseline.get("summary") or {}).get("decisions")
    if not isinstance(now, int) or not isinstance(old, int):
        return None
    return now - old


def _not_only_a_split(added: int | None) -> str:
    if added is None:
        return "the base report has no decision total"
    decisions = "decision" if added == 1 else "decisions"
    return (
        f"the change adds {added} {decisions} overall, so the pieces count against the budget; "
        "for split credit, keep the split in a PR of its own and add logic in another"
    )


def split_credit(current: dict, baseline: dict) -> tuple[int, list[str]]:
    """New functions at COMPLEXITY_WARNING+ carved out of a base function.

    A piece is a named function at COMPLEXITY_WARNING+ whose name is not in
    the base records, named after a base function at COMPLEXITY_WARNING+
    (see ``_carved_from``; the longest matching parent wins). The pieces of
    one parent are credited only when the parent's complexity, summed over
    every function of that name, drops by at least the pieces' decisions
    (complexity - 1 each): extracting a block with d decisions lowers the
    parent by d and creates a piece of complexity d + 1. Both reports record
    every function of a parent's name at any complexity (see
    ``_related_below_warning``), so a parent that is not recorded has been
    deleted.

    The change as a whole must also add no decisions (``summary.decisions``).
    Without that check, a parent could shed its logic into helpers under
    COMPLEXITY_WARNING (which no rule counts) while the "pieces" hold new
    logic. A split moves logic; it does not add any.
    """
    now, old = _records(current), _records(baseline)
    if now is None or old is None:
        return 0, []
    added = _added_decisions(current, baseline)
    known: dict[tuple[bool, str], list[dict]] = {}
    for item in old:
        if item.get("name"):
            known.setdefault((_is_python(item), item["name"]), []).append(item)
    parents = {
        key: items for key, items in known.items()
        if max(item["complexity"] for item in items) >= COMPLEXITY_WARNING
    }
    pieces: dict[tuple[bool, str], list[dict]] = {}
    for item in now:
        if item["complexity"] < COMPLEXITY_WARNING or not item.get("name"):
            continue
        if (_is_python(item), item["name"]) in known:
            continue
        parent = _split_parent(item, parents)
        if parent:
            pieces.setdefault(parent, []).append(item)
    credit = 0
    notes = []
    for key, items in sorted(pieces.items()):
        before = sum(item["complexity"] for item in parents[key])
        after = sum(
            item["complexity"] for item in now
            if item.get("name") == key[1] and _is_python(item) == key[0]
        )
        needed = sum(item["complexity"] - 1 for item in items)
        names = ", ".join(f"{item['name']} ({item['complexity']})" for item in items)
        if before - after < needed:
            notes.append(
                f"split not credited: {names} named after {key[1]}, but {key[1]} dropped "
                f"{before - after} ({before} -> {after}) and their decisions sum to {needed}"
            )
        elif added is None or added > 0:
            notes.append(
                f"split not credited: {names} carved out of {key[1]} ({before} -> {after}), "
                f"but {_not_only_a_split(added)}"
            )
        else:
            credit += len(items)
            notes.append(
                f"split: {names} carved out of {key[1]} ({before} -> {after}); "
                "not counted against the complex-function budget"
            )
    return credit, notes


def _complex_growth_findings(now: dict, old: dict, current: dict, baseline: dict) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    failures: list[str] = []
    complex_growth = now["complex_functions"] - old["complex_functions"]
    if complex_growth > 0:
        warnings.append(f"functions at complexity >= {COMPLEXITY_WARNING} increased by {complex_growth:+d}")
    credit, notes = split_credit(current, baseline) if complex_growth > 0 else (0, [])
    warnings.extend(notes)
    counted = complex_growth - credit
    budget = int(POLICY["complex_growth_budget"])
    if counted > budget:
        after_splits = f" ({counted} after {credit} credited split pieces)" if credit else ""
        # code_health_integration.py matches the "high-complexity function count grew " prefix.
        uncredited = "; split pieces were not credited (see the split notes)" if any(
            note.startswith("split not credited: ") for note in notes
        ) else ""
        failures.append(
            f"high-complexity function count grew by {complex_growth}{after_splits}; "
            f"budget is {budget}{uncredited}"
        )
    return warnings, failures


def _hotspot_allowance(old_lines: int) -> int:
    return max(
        int(POLICY["hotspot_growth_min"]),
        min(int(POLICY["hotspot_growth_max"]), round(old_lines * float(POLICY["hotspot_growth_pct"]))),
    )


def _baseline_file_findings(scope: dict, old_scope: dict) -> list[str]:
    """A baseline file keeps the hotspot growth allowance and gains no complex function."""
    failures = []
    # Splitting the change across PRs does not help: a development -> main
    # release measures this growth over the whole release, with no waiver.
    measured = f"a module under {' or '.join(PYTHON_PREFIXES)}, where the ratchet measures it"
    old_files = old_scope.get("files") if isinstance(old_scope.get("files"), dict) else {}
    for path, now in sorted((scope.get("files") or {}).items()):
        old = old_files.get(path)
        if not isinstance(old, dict):
            continue
        growth = int(now["lines"]) - int(old["lines"])
        allowance = _hotspot_allowance(int(old["lines"]))
        if growth > allowance:
            failures.append(
                f"unmeasured baseline file {path} grew {growth:,} lines; budget is {allowance:,}; "
                f"move the new code into {measured}, and call it from {path}"
            )
        ceiling = max(int(old["max_complexity"]), COMPLEXITY_WARNING - 1)
        if int(now["max_complexity"]) > ceiling:
            failures.append(
                f"unmeasured baseline file {path} has a function at complexity {now['max_complexity']}; "
                f"its ceiling is {ceiling}; move that function into {measured}"
            )
    return failures


def _new_vendor_files_warning(scope: dict, old_scope: dict) -> list[str]:
    if not isinstance(old_scope.get("vendor_files"), list):
        return []
    added = sorted(set(scope.get("vendor_files") or []) - set(old_scope["vendor_files"]))
    if not added:
        return []
    shown = ", ".join(added[:10]) + ("" if len(added) <= 10 else f" (+{len(added) - 10} more)")
    return [
        f"{len(added)} new Python file(s) under vendored folders are not measured: {shown}; "
        "reviewers: confirm they are engine code, not product code moved out of the ratchet"
    ]


def _unmeasured_findings(current: dict, baseline: dict) -> tuple[list[str], list[str]]:
    """Fail on product Python outside the measured scope that is not baselined."""
    scope = current.get("unmeasured")
    if not isinstance(scope, dict):
        return [], []
    warnings: list[str] = []
    failures: list[str] = []
    paths = list(scope.get("paths") or [])
    allowed = set(scope.get("allowed") or [])
    old_scope = baseline.get("unmeasured") if isinstance(baseline.get("unmeasured"), dict) else None
    for path in paths:
        if path not in allowed:
            failures.append(
                f"unmeasured product code {path}: put it under "
                f"{', '.join(PYTHON_PREFIXES)} (tools go in scripts/); the ratchet would not see it"
            )
        elif old_scope is not None and path not in (old_scope.get("paths") or []):
            failures.append(f"unmeasured product code {path} is new versus the base")
    for path in sorted(allowed - set(paths)):
        warnings.append(f"stale unmeasured baseline entry {path}; remove it from UNMEASURED_BASELINE")
    if old_scope is not None:
        failures.extend(_baseline_file_findings(scope, old_scope))
        warnings.extend(_new_vendor_files_warning(scope, old_scope))
        for key in ("vendor_prefixes", "allowed"):
            added = sorted(set(scope.get(key) or []) - set(old_scope.get(key) or []))
            if added:
                failures.append(
                    f"unmeasured exclusions ({key}) grew versus the base: {', '.join(added)}; "
                    "code outside the ratchet needs owner review"
                )
    return warnings, failures


def compare(current: dict, baseline: dict) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    failures: list[str] = []
    now = current.get("summary") or {}
    old = baseline.get("summary") or {}
    required = ("production_lines", "complex_functions", "max_complexity")
    missing = [key for key in required if key not in now or key not in old]
    if missing:
        failures.append(
            "incomplete baseline or current summary; missing "
            + ", ".join(missing)
            + " (missing metrics are not a pass)"
        )
        return warnings, failures

    current_policy = current.get("policy")
    baseline_policy = baseline.get("policy")
    if isinstance(baseline_policy, dict) and isinstance(current_policy, dict):
        if current_policy != baseline_policy:
            failures.append(
                "code-health policy changed vs baseline "
                f"{baseline.get('policy_version') or 'unknown'} -> "
                f"{current.get('policy_version') or 'unknown'}; "
                "review rule diffs instead of silently tightening or loosening budgets"
            )

    current_measure = current.get("measurement") or {}
    if current_measure.get("ui") == "missing":
        failures.append("UI complexity was not measured; missing metrics are not a pass")
    baseline_measure = baseline.get("measurement") or {}
    if baseline_measure.get("ui") == "complete" and current_measure.get("ui") != "complete":
        failures.append("UI complexity disappeared versus the baseline measurement")

    baseline_paths = set(baseline.get("product_paths") or [])
    current_paths = set(current.get("product_paths") or [])
    if baseline_paths:
        if not current_paths:
            failures.append(
                "product_paths missing or empty versus a baseline that listed "
                "product files (empty scope is not a pass)"
            )
        else:
            excluded = sorted(
                path for path in baseline_paths - current_paths if (ROOT / path).exists()
            )
            if excluded:
                failures.append(
                    "product scope excluded still-present files: "
                    + ", ".join(excluded[:8])
                    + ("" if len(excluded) <= 8 else f" (+{len(excluded) - 8} more)")
                )

    line_growth = now["production_lines"] - old["production_lines"]
    if line_growth > 0:
        warnings.append(f"production LOC increased by {line_growth:+,}")
    line_budget = max(
        int(POLICY["line_growth_min"]),
        round(old["production_lines"] * float(POLICY["line_growth_pct"])),
    )
    if line_growth > line_budget:
        failures.append(f"production LOC grew {line_growth:,}; budget is {line_budget:,}")

    found_warnings, found_failures = _complex_growth_findings(now, old, current, baseline)
    warnings.extend(found_warnings)
    failures.extend(found_failures)
    if now["max_complexity"] > old["max_complexity"]:
        warnings.append(f"maximum complexity rose {old['max_complexity']} -> {now['max_complexity']}")
    if now["max_complexity"] > old["max_complexity"] + int(POLICY["max_complexity_delta"]):
        failures.append(
            f"maximum cyclomatic complexity increased by more than {int(POLICY['max_complexity_delta'])}"
        )

    moves = verified_moves(current, baseline)
    warnings.extend(_move_notes(current, moves))
    found_warnings, found_failures = _complexity_hotspot_findings(current, baseline, moves)
    warnings.extend(found_warnings)
    failures.extend(found_failures)

    for path, old_lines in baseline.get("hotspots", {}).items():
        new_lines = current.get("hotspots", {}).get(path, 0)
        growth = new_lines - old_lines
        # Legacy integration hubs such as _launch_runtime.py occasionally
        # need a cohesive feature-sized change. Keep the ratchet active while
        # allowing up to 600 lines in one PR; larger growth still fails and
        # should be extracted into a dedicated module.
        allowance = _hotspot_allowance(old_lines)
        if growth > 0:
            warnings.append(f"hotspot {path} increased by {growth:+,} lines")
        if growth > allowance:
            failures.append(f"hotspot {path} grew {growth:,} lines; budget is {allowance:,}")
    for path, lines in current.get("hotspots", {}).items():
        if path not in baseline.get("hotspots", {}) and lines > int(POLICY["new_hotspot_limit"]):
            failures.append(
                f"new hotspot {path} has {lines:,} lines; "
                f"limit is {int(POLICY['new_hotspot_limit']):,}"
            )
    found_warnings, found_failures = _unmeasured_findings(current, baseline)
    warnings.extend(found_warnings)
    failures.extend(found_failures)
    return warnings, failures


def _print_report(report: dict) -> None:
    summary = report["summary"]
    quality = report.get("quality") or quality_score(report)
    print("HocusPocus code health")
    print(f"Quality:    {quality['score']:.1f}/100 (higher is better)")
    print(
        f"Production: {summary['production_lines']:,} lines / "
        f"{summary['production_files']:,} files "
        f"({summary['production_non_blank_lines']:,} non-blank)"
    )
    print(f"Tests:      {summary['test_lines']:,} lines / {summary['test_files']:,} files")
    print(
        f"Complexity: {summary['functions_measured']:,} functions, "
        f"{summary['complex_functions']} >= {COMPLEXITY_WARNING}, "
        f"maximum {summary['max_complexity']}"
    )
    print("\nLargest first-party files:")
    for path, lines in list(report["hotspots"].items())[:15]:
        print(f"  {lines:>7,}  {path}")
    print("\nMost complex functions:")
    for item in report["top_complexity"][:15]:
        print(f"  {item['complexity']:>3}  {item['path']}:{item['line']}  {item['name']}")


def _markdown_report(
    report: dict,
    baseline: dict | None = None,
    warnings: list[str] | None = None,
    failures: list[str] | None = None,
    score_baseline: dict | None = None,
    score_baseline_label: str = "comparison base",
) -> str:
    summary = report["summary"]
    measurement = report.get("measurement") or {}
    quality = report.get("quality") or quality_score(report)
    comparison_report = score_baseline or baseline
    previous_quality = quality_score(comparison_report) if comparison_report else None
    lines = [
        "<!-- code-health-report -->",
        "## Code health",
        "",
        f"### Quality score: {quality['score']:.1f}/100",
        "",
        "Higher is better. The score is a trend dashboard; the independent ratchet below remains the CI gate.",
        "",
        "| Component | Weight | Current | Change |",
        "|---|---:|---:|---:|",
    ]
    component_labels = {
        "cyclomatic": "Cyclomatic health",
        "concentration": "File concentration",
        "oversized_files": "Oversized-file debt",
        "modularity": "Modularity",
    }
    for key, weight in COMPONENT_WEIGHTS.items():
        current_value = quality["components"][key]
        change = "—"
        if previous_quality:
            change = f"{current_value - previous_quality['components'][key]:+.1f}"
        lines.append(f"| {component_labels[key]} | {weight:.0%} | {current_value:.1f} | {change} |")
    if previous_quality:
        lines.extend([
            "",
            f"**Change vs {score_baseline_label}: {score_delta(quality, previous_quality):+.1f} points.**",
        ])
    lines.extend([
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Production LOC | {summary['production_lines']:,} |",
        f"| Production files | {summary['production_files']:,} |",
        f"| Test LOC | {summary['test_lines']:,} |",
        f"| Functions measured | {summary['functions_measured']:,} |",
        f"| Functions complexity ≥ {COMPLEXITY_WARNING} | {summary['complex_functions']} |",
        f"| Maximum complexity | {summary['max_complexity']} |",
        f"| Policy | {report.get('policy_version') or POLICY_VERSION} |",
        f"| HEAD | `{measurement.get('head_sha') or 'unknown'}` |",
        f"| Base | `{measurement.get('base_sha') or 'unset'}` |",
        f"| UI measurement | {measurement.get('ui') or 'unknown'} |",
        "",
        "Markdown, JSON catalogs and tests are out of this table. Only `app/` runtime + `ui/src` TS/JS count.",
        "",
        "### Most complex functions",
        "",
        "| Complexity | Where |",
        "|---:|---|",
    ])
    for item in report["top_complexity"][:12]:
        lines.append(f"| {item['complexity']} | `{item['path']}:{item['line']}` `{item['name']}` |")
    if baseline:
        now = report["summary"]
        old = baseline["summary"]
        lines.extend([
            "",
            "### Trend vs baseline",
            "",
            "| Metric | Δ |",
            "|---|---:|",
        ])
        for label, key in (
            ("Production LOC", "production_lines"),
            ("Test LOC", "test_lines"),
            (f"Functions ≥ {COMPLEXITY_WARNING}", "complex_functions"),
            ("Maximum complexity", "max_complexity"),
        ):
            lines.append(f"| {label} | {now[key] - old[key]:+,} |")
    notes = [item for item in warnings or [] if item.startswith(NOTE_PREFIXES)]
    plain = [item for item in warnings or [] if not item.startswith(NOTE_PREFIXES)]
    if notes:
        lines.extend(["", "### Moves and splits", ""])
        lines.extend(f"- {item}" for item in notes)
    if plain:
        lines.extend(["", "### Warnings", ""])
        lines.extend(f"- {item}" for item in plain)
    if failures:
        lines.extend(["", "### Failures", ""])
        lines.extend(f"- {item}" for item in failures)
        lines.append("")
        lines.append("**Ratchet failed.**")
    elif baseline is not None:
        lines.extend(["", "**Ratchet passed.**"])
    else:
        lines.extend(["", "**Ratchet not evaluated.**"])
    return "\n".join(lines) + "\n"


def publish_pr_comment(markdown: str) -> None:
    repository = os.environ.get("GITHUB_REPOSITORY")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not repository or not event_path:
        raise RuntimeError("GITHUB_REPOSITORY and GITHUB_EVENT_PATH are required to comment")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    number = (event.get("pull_request") or {}).get("number")
    if not number:
        return
    listed = subprocess.run(
        ["gh", "api", f"repos/{repository}/issues/{number}/comments", "--paginate"],
        capture_output=True,
        text=True,
        check=True,
    )
    comments = json.loads(listed.stdout or "[]")
    existing = next(
        (item["id"] for item in comments if "<!-- code-health-report -->" in str(item.get("body") or "")),
        None,
    )
    payload = json.dumps({"body": markdown})
    if existing:
        subprocess.run(
            ["gh", "api", "-X", "PATCH", f"repos/{repository}/issues/comments/{existing}", "--input", "-"],
            input=payload,
            text=True,
            check=True,
            capture_output=True,
        )
        return
    subprocess.run(
        ["gh", "api", "-X", "POST", f"repos/{repository}/issues/{number}/comments", "--input", "-"],
        input=payload,
        text=True,
        check=True,
        capture_output=True,
    )


def _print_trend(current: dict, baseline: dict) -> None:
    now = current["summary"]
    old = baseline["summary"]
    print("\nTrend vs committed baseline:")
    for label, key in (
        ("production LOC", "production_lines"),
        ("test LOC", "test_lines"),
        (f"functions >= {COMPLEXITY_WARNING}", "complex_functions"),
        ("maximum complexity", "max_complexity"),
    ):
        change = now[key] - old[key]
        print(f"  {label:<24} {change:+,}")
    changed_hotspots = []
    paths = set(current.get("hotspots", {})) | set(baseline.get("hotspots", {}))
    for path in paths:
        change = current.get("hotspots", {}).get(path, 0) - baseline.get("hotspots", {}).get(path, 0)
        if change:
            changed_hotspots.append((abs(change), change, path))
    for _, change, path in sorted(changed_hotspots, reverse=True)[:10]:
        print(f"  hotspot {change:+7,}  {path}")


def load_exceptions(path: Path = DEFAULT_EXCEPTIONS) -> list[dict]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload in (None, []):
        return []
    if not isinstance(payload, list):
        raise RuntimeError(f"{path} must be a JSON array of exception objects")
    today = datetime.date.today().isoformat()
    exceptions: list[dict] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise RuntimeError(f"{path}[{index}] must be an object")
        missing = [field for field in EXCEPTION_FIELDS if not str(item.get(field) or "").strip()]
        if missing:
            raise RuntimeError(
                f"{path}[{index}] missing {', '.join(missing)}; "
                "exceptions need path, rule, reason, owner, issue and expires"
            )
        rule = str(item["rule"]).strip()
        if rule not in WAIVABLE_RULES:
            raise RuntimeError(
                f"{path}[{index}] rule {rule!r} is not waivable; "
                f"allowed: {', '.join(sorted(WAIVABLE_RULES))}"
            )
        expires = str(item["expires"]).strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expires):
            raise RuntimeError(f"{path}[{index}] expires {expires!r} is not a YYYY-MM-DD date")
        try:
            datetime.date.fromisoformat(expires)
        except ValueError as exc:
            raise RuntimeError(f"{path}[{index}] expires {expires!r} is not a YYYY-MM-DD date") from exc
        if expires < today:
            continue
        exceptions.append(item)
    return exceptions


def apply_exceptions(
    failures: list[str],
    warnings: list[str],
    exceptions: list[dict],
) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    for failure in failures:
        matched = None
        # A waiver matches only its own rule's failure about exactly its file:
        # the subject (the text before the first ";") must have the rule's
        # wording and name that path. A "not a verified move" reason names
        # other files, such as the base file a function came from, and a path
        # fragment such as "app/routers/" or "LOC" must not match anything.
        subject = failure.split(";", 1)[0]
        for item in exceptions:
            pattern = WAIVER_SUBJECTS.get(str(item["rule"]))
            found = pattern.fullmatch(subject) if pattern else None
            if found and found.group(1) == str(item["path"]):
                matched = item
                break
        if matched:
            warnings.append(
                f"waived {matched['rule']} for {matched['path']} "
                f"until {matched['expires']} ({matched['issue']})"
            )
            continue
        kept.append(failure)
    return warnings, kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare with the committed baseline")
    parser.add_argument("--write-baseline", action="store_true", help="replace the baseline intentionally")
    parser.add_argument("--json", action="store_true", help="print the complete report as JSON")
    parser.add_argument("--require-ui", action="store_true", help="fail if UI complexity cannot be measured")
    parser.add_argument("--markdown", action="store_true", help="print a GitHub-flavored table")
    parser.add_argument("--publish-pr-comment", action="store_true", help="upsert the markdown table on the current PR")
    parser.add_argument("--score-baseline", type=Path, help="code-health JSON for an exact score comparison")
    parser.add_argument("--score-baseline-label", default="comparison base")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()
    if args.check and args.write_baseline:
        parser.error("--check and --write-baseline are mutually exclusive")
    try:
        report = collect(require_ui=args.check or args.write_baseline or args.require_ui)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    if args.write_baseline:
        args.baseline.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nWrote baseline: {args.baseline.relative_to(ROOT)}")
        return 0
    baseline = None
    score_baseline = None
    warnings: list[str] = []
    failures: list[str] = []
    if args.check:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        warnings, failures = compare(report, baseline)
        try:
            warnings, failures = apply_exceptions(failures, warnings, load_exceptions())
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 2
    if args.score_baseline:
        score_baseline = json.loads(args.score_baseline.read_text(encoding="utf-8"))
    elif baseline is not None:
        score_baseline = baseline
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.markdown:
        markdown = _markdown_report(
            report, baseline, warnings, failures,
            score_baseline=score_baseline,
            score_baseline_label=args.score_baseline_label,
        )
        print(markdown, end="")
        if args.publish_pr_comment:
            try:
                publish_pr_comment(markdown)
            except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
                print(f"WARN: could not comment on the PR: {exc}", file=sys.stderr)
    else:
        _print_report(report)
        if baseline is not None:
            _print_trend(report, baseline)
            for warning in warnings:
                print(f"{'NOTE' if warning.startswith(NOTE_PREFIXES) else 'WARN'}: {warning}")
            for failure in failures:
                print(f"FAIL: {failure}")
            print("PASS: code-health ratchet" if not failures else f"FAIL: {len(failures)} budget regression(s)")
    if args.check:
        return 1 if failures else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
