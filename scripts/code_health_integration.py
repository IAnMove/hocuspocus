#!/usr/bin/env python3
"""Verify cumulative release budgets without relaxing current code-health limits."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import code_health as health

ROOT = Path(__file__).resolve().parents[1]
MEASUREMENT_INPUTS = (
    "scripts/code_health.py", "scripts/code_quality_score.py",
    "ui/eslint.config.js", "ui/package.json", "ui/package-lock.json",
)
AGGREGATE_PREFIXES = ("production LOC grew ", "high-complexity function count grew ")


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def tree_entries(sha: str) -> list[tuple[str, str, str, str]]:
    output = subprocess.check_output(["git", "-C", str(ROOT), "ls-tree", "-r", "-z", sha])
    entries = []
    for entry in output.decode("utf-8").split("\0"):
        if entry:
            metadata, path = entry.split("\t", 1)
            mode, kind, blob = metadata.split()
            entries.append((mode, kind, blob, path))
    return entries


def main_push_source(base: str, head: str, development: str) -> str | None:
    """Recognize only an unchanged development tree published by a merge commit."""
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
        return None
    if git("rev-parse", "HEAD") != head:
        return None
    parents = git("rev-list", "--parents", "-n", "1", head).split()
    if len(parents) != 3 or parents[0] != head or parents[1] != base:
        return None
    source = parents[2]
    if git("rev-parse", f"{head}^{{tree}}") != git("rev-parse", f"{source}^{{tree}}"):
        return None
    if subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", source, development],
        capture_output=True,
    ).returncode != 0:
        return None
    return source


def measurement_manifest(source: str) -> str:
    manifest = json.loads(source)
    # The directly invoked ESLint scanner does not run the test command.
    # Lifecycle/install hooks remain inputs because they can modify dependencies.
    manifest.get("scripts", {}).pop("test", None)
    return json.dumps(manifest, sort_keys=True)


def release_chain(base: str, head: str) -> list[str]:
    """Require complete history and a release tree identical to its fork point."""
    if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
        raise ValueError("Release base/head must be exact commit SHAs")
    if git("rev-parse", "--is-shallow-repository") != "false":
        raise ValueError("Release verification requires complete history")
    common = git("merge-base", base, head)
    if git("rev-parse", f"{base}^{{tree}}") != git("rev-parse", f"{common}^{{tree}}"):
        raise ValueError("Release base tree differs from the integration merge-base")
    if git("rev-parse", "HEAD^{tree}") != git("rev-parse", f"{head}^{{tree}}"):
        raise ValueError("Checked-out candidate tree differs from the source HEAD")
    dirty = git("diff", "HEAD", "--name-only", "--", "app", "ui/src", *MEASUREMENT_INPUTS)
    if dirty:
        raise ValueError("Commit candidate changes before verifying release history")
    commits = git("rev-list", "--first-parent", "--reverse", f"{common}..{head}").splitlines()
    previous = common
    for commit in commits:
        if git("rev-parse", f"{commit}^1") != previous:
            raise ValueError("Integration history has a gap in its first-parent chain")
        previous = commit
    if previous != head:
        raise ValueError("Integration history does not reach the requested HEAD")
    return [base, *commits]


def read_trees(chain: list[str]) -> tuple[list[dict[str, str]], dict[str, str]]:
    trees, blobs, inputs = [], set(), None
    for sha in chain:
        tree = {}
        measurement = {}
        for mode, kind, blob, path in tree_entries(sha):
            if path in MEASUREMENT_INPUTS:
                measurement[path] = blob
            if health._is_product(path):
                if kind != "blob" or mode not in {"100644", "100755"}:
                    raise ValueError(f"Unsupported product entry at {sha}: {path}")
                tree[path] = blob
                blobs.add(blob)
        if set(measurement) != set(MEASUREMENT_INPUTS):
            raise ValueError(f"Missing measurement inputs at {sha}")
        measurement["ui/package.json"] = measurement_manifest(git("show", f"{sha}:ui/package.json"))
        if inputs is not None and measurement != inputs:
            raise ValueError(f"Policy, analyzer or UI measurement inputs changed at {sha}")
        inputs = measurement
        trees.append(tree)
    batch = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "--batch"],
        input="\n".join(sorted(blobs)).encode() + b"\n", capture_output=True, check=True,
    ).stdout
    sources, offset = {}, 0
    for expected in sorted(blobs):
        end = batch.index(b"\n", offset)
        actual, kind, size = batch[offset:end].decode().split()
        if actual != expected or kind != "blob":
            raise ValueError(f"Missing source blob: {expected}")
        offset = end + 1
        sources[expected] = batch[offset:offset + int(size)].decode("utf-8")
        offset += int(size) + 1
    return trees, sources


def source_complexity(trees: list[dict[str, str]], sources: dict[str, str]) -> dict:
    """Measure each unique source once with the same AST/ESLint rules as the gate."""
    metrics = {}
    with tempfile.TemporaryDirectory(prefix="hocus-release-health-") as temporary:
        folder = Path(temporary)
        (folder / "src").mkdir()
        # Resolve the installed packages without reinstalling or modifying them.
        (folder / "node_modules").symlink_to(ROOT / "ui/node_modules", target_is_directory=True)
        shutil.copy(ROOT / "ui/eslint.config.js", folder / "eslint.config.js")
        (folder / "package.json").write_text('{"type":"module"}', encoding="utf-8")
        for tree in trees:
            for path, blob in tree.items():
                suffix = Path(path).suffix
                key = (blob, suffix)
                if key in metrics:
                    continue
                if suffix == ".py":
                    collector = health._PythonFunctionCollector(path)
                    collector.visit(health.ast.parse(sources[blob], filename=path))
                    metrics[key] = [item.complexity for item in collector.metrics]
                else:
                    (folder / "src" / f"{blob}{suffix}").write_text(sources[blob], encoding="utf-8")
                    metrics[key] = []
        result = subprocess.run(
            ["node", str(ROOT / "ui/node_modules/eslint/bin/eslint.js"), "src", "--format", "json",
             "--rule", 'complexity: ["error", 0]'], cwd=folder, text=True, capture_output=True,
        )
        if result.returncode not in {0, 1}:
            raise ValueError(f"Historical UI measurement failed: {result.stderr.strip()}")
        seen = set()
        for report in json.loads(result.stdout):
            path = Path(report["filePath"])
            key = (path.stem, path.suffix)
            if key not in metrics:
                raise ValueError(f"Unexpected UI measurement: {path.name}")
            seen.add(key)
            for message in report["messages"]:
                if message.get("fatal"):
                    raise ValueError(f"Historical source cannot be parsed: {path.name}")
                if message.get("ruleId") == "complexity":
                    match = re.search(r"complexity of (\d+)", message["message"])
                    if not match:
                        raise ValueError("Unrecognized ESLint complexity result")
                    metrics[key].append(int(match.group(1)))
        if seen != {key for key in metrics if key[1] != ".py"}:
            raise ValueError("Historical UI measurement omitted source files")
    return metrics


def checkpoint(tree: dict[str, str], sources: dict[str, str], metrics: dict) -> dict:
    lines = {path: len(sources[blob].splitlines()) for path, blob in tree.items()}
    functions = {path: metrics[(blob, Path(path).suffix)] for path, blob in tree.items()}
    values = [value for items in functions.values() for value in items]
    return {
        "policy": health.POLICY, "policy_version": health.POLICY_VERSION,
        "measurement": {"ui": "complete"}, "product_paths": sorted(tree),
        "summary": {
            "production_lines": sum(lines.values()),
            "complex_functions": sum(value >= health.COMPLEXITY_WARNING for value in values),
            "max_complexity": max(values, default=0), "functions_measured": len(values),
        },
        "hotspots": {path: count for path, count in lines.items() if count >= health.HOTSPOT_LINES},
        "complexity_hotspots": {
            path: max(items) for path, items in functions.items()
            if items and max(items) >= health.COMPLEXITY_WARNING
        },
    }


def compare_release(current: dict, baseline: dict, chain: list[str], reports: list[dict]) -> tuple[list[str], list[str], list]:
    """Check aggregate budgets at every step and every local rule on the final tree."""
    if len(chain) != len(reports) or not reports:
        raise ValueError("Missing integration checkpoint reports")
    for expected, measured in ((baseline, reports[0]), (current, reports[-1])):
        for key in ("production_lines", "complex_functions", "max_complexity", "functions_measured"):
            if expected.get("summary", {}).get(key) != measured["summary"][key]:
                raise ValueError(f"Historical and full-tree measurements disagree: {key}")
        for key in ("product_paths", "hotspots", "complexity_hotspots"):
            if expected.get(key) != measured[key]:
                raise ValueError(f"Historical and full-tree measurements disagree: {key}")
    warnings, total_failures = health.compare(current, baseline)
    failures = [item for item in total_failures if not item.startswith(AGGREGATE_PREFIXES)]
    historical = []
    for before, after, sha in zip(reports, reports[1:], chain[1:]):
        _, step_failures = health.compare(after, before)
        aggregate = [item for item in step_failures if item.startswith(AGGREGATE_PREFIXES)]
        failures.extend(f"Integration {sha}: {item}" for item in aggregate)
        if step_failures:
            historical.append({"sha": sha, "aggregate_failures": aggregate,
                               "local_findings": [item for item in step_failures if item not in aggregate]})
    return warnings, failures, historical


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        chain = release_chain(args.base, args.head)
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        current = health.collect(require_ui=True)
        trees, sources = read_trees(chain)
        metrics = source_complexity(trees, sources)
        reports = [checkpoint(tree, sources, metrics) for tree in trees]
        warnings, failures, historical = compare_release(current, baseline, chain, reports)
        if args.evidence:
            args.evidence.write_text(json.dumps({
                "base": args.base, "source_head": args.head,
                "policy": health.POLICY, "failures": failures, "historical_findings": historical,
                "checkpoints": [
                    {"sha": sha, "tree": git("rev-parse", f"{sha}^{{tree}}"), **report["summary"]}
                    for sha, report in zip(chain, reports)
                ],
            }, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"FAIL: release code-health verification: {error}")
        return 2
    print(health._markdown_report(current, baseline, warnings, failures, score_baseline_label="PR base"), end="")
    print("\n### Release integration budgets\n")
    print(f"Base `{args.base}` → source HEAD `{args.head}`; **{len(chain) - 1} verified first-parent transitions**.")
    print("LOC and complex-function growth use the unchanged budget at every transition. "
          "All other limits compare the complete current tree with the release base. "
          "The cumulative deltas above remain visible; no baseline or exception is changed.")
    for item in historical:
        for finding in item["local_findings"]:
            print(f"- Historical local finding at `{item['sha']}`: {finding}. "
                  "Current local limits are checked against the release base above.")
    if failures:
        print("\n**Release verification failed.**")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
