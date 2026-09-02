#!/usr/bin/env python3
"""Report first-party LOC and cyclomatic complexity, with a CI ratchet.

The Python metric is calculated with the standard-library AST. UI complexity
comes from ESLint's built-in ``complexity`` rule when ``ui/node_modules`` is
installed. Only git-tracked, first-party production code affects the ratchet.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "scripts" / "code_health_baseline.json"
PYTHON_EXACT = {"app/_launch_runtime.py", "app/launch.py", "app/wgp.py"}
PYTHON_PREFIXES = ("app/services/", "app/routers/")
UI_PREFIX = "ui/src/"
UI_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
HOTSPOT_LINES = 1_000
COMPLEXITY_WARNING = 15


@dataclass(frozen=True)
class FunctionMetric:
    path: str
    name: str
    line: int
    complexity: int


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
        self.metrics.append(FunctionMetric(self.path, name, node.lineno, 1 + counter.decisions))
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
    if path in PYTHON_EXACT or (path.endswith(".py") and path.startswith(PYTHON_PREFIXES)):
        return True
    return path.startswith(UI_PREFIX) and Path(path).suffix in UI_SUFFIXES


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
    functions = _python_complexity(product) + _ui_complexity(require_ui)
    ranked = sorted(functions, key=lambda item: (-item.complexity, item.path, item.line))
    complexity_by_file: dict[str, int] = {}
    for item in functions:
        complexity_by_file[item.path] = max(complexity_by_file.get(item.path, 0), item.complexity)
    hotspots = dict(sorted(
        ((path, lines) for path, lines in file_lines.items() if lines >= HOTSPOT_LINES),
        key=lambda item: (-item[1], item[0]),
    ))
    return {
        "version": 1,
        "summary": {
            "production_files": len(product),
            "production_lines": sum(file_lines.values()),
            "production_non_blank_lines": non_blank,
            "test_files": len(tests),
            "test_lines": test_lines,
            "functions_measured": len(functions),
            "complex_functions": sum(item.complexity >= COMPLEXITY_WARNING for item in functions),
            "max_complexity": ranked[0].complexity if ranked else 0,
        },
        "hotspots": hotspots,
        "complexity_hotspots": dict(sorted(
            ((path, value) for path, value in complexity_by_file.items() if value >= COMPLEXITY_WARNING),
            key=lambda item: (-item[1], item[0]),
        )),
        "top_complexity": [asdict(item) for item in ranked[:30]],
    }


def compare(current: dict, baseline: dict) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    failures: list[str] = []
    now = current["summary"]
    old = baseline["summary"]

    line_growth = now["production_lines"] - old["production_lines"]
    if line_growth > 0:
        warnings.append(f"production LOC increased by {line_growth:+,}")
    line_budget = max(2_000, round(old["production_lines"] * 0.03))
    if line_growth > line_budget:
        failures.append(f"production LOC grew {line_growth:,}; budget is {line_budget:,}")

    complex_growth = now["complex_functions"] - old["complex_functions"]
    if complex_growth > 0:
        warnings.append(f"functions at complexity >= {COMPLEXITY_WARNING} increased by {complex_growth:+d}")
    if complex_growth > 5:
        failures.append(f"high-complexity function count grew by {complex_growth}; budget is 5")
    if now["max_complexity"] > old["max_complexity"]:
        warnings.append(f"maximum complexity rose {old['max_complexity']} -> {now['max_complexity']}")
    if now["max_complexity"] > old["max_complexity"] + 3:
        failures.append("maximum cyclomatic complexity increased by more than 3")

    old_complexity = baseline.get("complexity_hotspots", {})
    for path, new_value in current.get("complexity_hotspots", {}).items():
        old_value = old_complexity.get(path)
        if old_value is None:
            if new_value > 25:
                failures.append(f"new complexity hotspot {path} is {new_value}; limit is 25")
            continue
        if new_value > old_value:
            warnings.append(f"complexity hotspot {path} rose {old_value} -> {new_value}")
        if new_value > old_value + 5:
            failures.append(f"complexity hotspot {path} increased by more than 5")

    for path, old_lines in baseline.get("hotspots", {}).items():
        new_lines = current.get("hotspots", {}).get(path, 0)
        growth = new_lines - old_lines
        allowance = max(75, min(300, round(old_lines * 0.02)))
        if growth > 0:
            warnings.append(f"hotspot {path} increased by {growth:+,} lines")
        if growth > allowance:
            failures.append(f"hotspot {path} grew {growth:,} lines; budget is {allowance:,}")
    for path, lines in current.get("hotspots", {}).items():
        if path not in baseline.get("hotspots", {}) and lines > 1_200:
            failures.append(f"new hotspot {path} has {lines:,} lines; limit is 1,200")
    return warnings, failures


def _print_report(report: dict) -> None:
    summary = report["summary"]
    print("HocusPocus code health")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare with the committed baseline")
    parser.add_argument("--write-baseline", action="store_true", help="replace the baseline intentionally")
    parser.add_argument("--json", action="store_true", help="print the complete report as JSON")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = parser.parse_args()
    if args.check and args.write_baseline:
        parser.error("--check and --write-baseline are mutually exclusive")
    try:
        report = collect(require_ui=args.check or args.write_baseline)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    if args.write_baseline:
        args.baseline.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nWrote baseline: {args.baseline.relative_to(ROOT)}")
        return 0
    if not args.check:
        return 0
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    _print_trend(report, baseline)
    warnings, failures = compare(report, baseline)
    for warning in warnings:
        print(f"WARN: {warning}")
    for failure in failures:
        print(f"FAIL: {failure}")
    print("PASS: code-health ratchet" if not failures else f"FAIL: {len(failures)} budget regression(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
