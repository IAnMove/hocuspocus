#!/usr/bin/env python3
"""Verify cumulative release budgets without relaxing current code-health limits."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

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


# npm runs these by itself on install; they can change the dependencies ESLint measures with.
LIFECYCLE_SCRIPTS = frozenset({"preinstall", "install", "postinstall", "prepublish", "preprepare", "prepare",
                               "postprepare", "dependencies"})


DEPENDENCY_FIELDS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def config_packages(source: str) -> set[str]:
    """Only static package imports are supported; local/dynamic config needs review."""
    if re.search(r"\b(?:import|from|require)\s*(?:/\*|//)", source):
        raise ValueError("Comment-separated ESLint configuration imports are unsupported")
    if re.search(r"\b(?:import|require)\s*\(", source):
        raise ValueError("Dynamic ESLint configuration imports are unsupported")
    packages = {"eslint"}  # source_complexity invokes this package's bin directly.
    for specifier in re.findall(r"\b(?:from\s*|import\s*)['\"]([^'\"]+)['\"]", source):
        if not re.fullmatch(r"(?:@[\w.-]+/)?[\w-][\w.-]*(?:/[\w.-]+)*", specifier):
            raise ValueError(f"Unsupported ESLint configuration import: {specifier}")
        parts = specifier.split("/")
        packages.add("/".join(parts[:2]) if specifier.startswith("@") else parts[0])
    return packages


def dependency_map(record: dict, field: str) -> dict[str, str]:
    value = record.get(field, {})
    if not isinstance(value, dict) or any(not isinstance(name, str) or not isinstance(spec, str)
                                          for name, spec in value.items()):
        raise ValueError(f"Invalid measurement dependency map: {field}")
    return value


def resolve_package(packages: dict, importer: str, name: str) -> str | None:
    if not re.fullmatch(r"(?:@[\w.-]+/)?[\w-][\w.-]*", name):
        raise ValueError(f"Invalid measurement dependency name: {name}")
    folder = PurePosixPath(importer)
    for parent in (folder, *folder.parents):
        if parent.name != "node_modules":
            candidate = str(parent / "node_modules" / name)
            if candidate in packages:
                return candidate
    return None


def dependency_edges(packages: dict, path: str, record: dict) -> dict:
    dependencies = dependency_map(record, "dependencies")
    optional = dependency_map(record, "optionalDependencies")
    peers = dependency_map(record, "peerDependencies")
    meta = record.get("peerDependenciesMeta", {})
    if not isinstance(meta, dict) or any(not isinstance(value, dict) for value in meta.values()):
        raise ValueError(f"Invalid peer dependency metadata: {path}")
    edges = {}
    for name in dependencies.keys() | optional.keys() | peers.keys():
        target = resolve_package(packages, path, name)
        optional_only = name in optional or (name not in dependencies and meta.get(name, {}).get("optional") is True)
        if target is None and not optional_only:
            raise ValueError(f"Missing measurement dependency: {path} -> {name}")
        edges[name] = target
    return edges


def measurement_manifest(source: str, lock_source: str, config_source: str) -> str:
    """Fingerprint the installed analyzer closure and every install-script package."""
    manifest, lock = json.loads(source), json.loads(lock_source)
    if not isinstance(manifest, dict) or not isinstance(lock, dict) or lock.get("lockfileVersion") != 3:
        raise ValueError("Measurement requires a package manifest and npm v3 lockfile")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or not isinstance(packages.get(""), dict):
        raise ValueError("Missing measurement lockfile root")
    if any(not isinstance(record, dict) or record.get("link") for record in packages.values()):
        raise ValueError("Unsupported linked or invalid measurement lockfile package")
    scripts = dependency_map(manifest, "scripts")
    root_hooks = bool(LIFECYCLE_SCRIPTS.intersection(scripts))
    # A root hook can call other scripts or inspect any installed dependency.
    manifest["scripts"] = scripts if root_hooks else {}
    pending = {path for path, record in packages.items() if path and (
        root_hooks or record.get("hasInstallScript") or record.get("gypfile")
        or LIFECYCLE_SCRIPTS.intersection(dependency_map(record, "scripts"))
    )}
    for name in config_packages(config_source):
        path = resolve_package(packages, "", name)
        if path is None:
            raise ValueError(f"Missing ESLint measurement package: {name}")
        pending.add(path)
    selected = {}
    while pending:
        path = pending.pop()
        if path in selected:
            continue
        record = packages[path]
        if any(not isinstance(record.get(key), str) or not record[key] for key in ("version", "resolved", "integrity")):
            raise ValueError(f"Missing locked measurement package identity: {path}")
        edges = dependency_edges(packages, path, record)
        selected[path] = {"record": record, "resolved_dependencies": edges}
        pending.update(target for target in edges.values() if target is not None)
    for record in (manifest, packages[""]):
        for field in DEPENDENCY_FIELDS:
            if field in record:
                record[field] = {name: spec for name, spec in dependency_map(record, field).items()
                                 if root_hooks or resolve_package(packages, "", name) in selected}
    # Keep all other root metadata (including overrides and package-manager settings).
    lock["packages"] = {"": packages[""], **selected}
    return json.dumps({"manifest": manifest, "lock": lock}, sort_keys=True)


def unmeasured_inputs(source: str, lock_source: str, fingerprint: str) -> dict[tuple[str, ...], object]:
    """Keep the complement: npm can execute undeclared native install hooks."""
    manifest, lock = json.loads(source), json.loads(lock_source)
    packages = lock["packages"]
    selected = set(json.loads(fingerprint)["lock"]["packages"]) - {""}
    inputs = {("package", path): record for path, record in packages.items() if path and path not in selected}
    for origin, record in (("manifest", manifest), ("lock", packages[""])):
        for field in DEPENDENCY_FIELDS:
            for name, spec in dependency_map(record, field).items():
                if resolve_package(packages, "", name) not in selected:
                    inputs[(origin, field, name)] = spec
    return inputs


def removed_only(previous: dict, current: dict) -> bool:
    return all(key in previous and previous[key] == value for key, value in current.items())


def release_chain(base: str, head: str) -> list[str]:
    """Verify development history, including a main sync through a second parent."""
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
    checkpoints = [base]
    if commits:
        previous = git("rev-parse", f"{commits[0]}^1")
        if previous != common:
            # A main -> development sync makes main the merge-base without
            # putting it on development's first-parent chain. Keep the actual
            # fork checkpoint so its first feature still gets its full budget
            # check, rather than comparing that feature with a newer main tree.
            if not re.fullmatch(r"[0-9a-f]{40}", previous) or git("merge-base", previous, common) != previous:
                raise ValueError("Integration history has a gap before its first-parent chain")
            checkpoints.append(previous)
    for commit in commits:
        if git("rev-parse", f"{commit}^1") != previous:
            raise ValueError("Integration history has a gap in its first-parent chain")
        previous = commit
    if previous != head:
        raise ValueError("Integration history does not reach the requested HEAD")
    return [*checkpoints, *commits]


def read_trees(chain: list[str]) -> tuple[list[dict[str, str]], dict[str, str]]:
    trees, blobs, inputs = [], set(), None
    fingerprints = {}
    previous_unmeasured = None
    for sha in chain:
        tree = {}
        measurement = {}
        for mode, kind, blob, path in tree_entries(sha):
            if path in MEASUREMENT_INPUTS:
                if kind != "blob" or mode not in {"100644", "100755"}:
                    raise ValueError(f"Unsupported measurement inputs at {sha}: {path}")
                measurement[path] = blob
            if health._is_product(path):
                if kind != "blob" or mode not in {"100644", "100755"}:
                    raise ValueError(f"Unsupported product entry at {sha}: {path}")
                tree[path] = blob
                blobs.add(blob)
        if set(measurement) != set(MEASUREMENT_INPUTS):
            raise ValueError(f"Missing measurement inputs at {sha}")
        dependency_inputs = ("ui/package.json", "ui/package-lock.json", "ui/eslint.config.js")
        key = tuple(measurement[path] for path in dependency_inputs)
        if key not in fingerprints:
            sources = [git("show", f"{sha}:{path}") for path in dependency_inputs]
            fingerprint = measurement_manifest(*sources)
            fingerprints[key] = fingerprint, unmeasured_inputs(*sources[:2], fingerprint)
        measurement["ui/package.json"], unmeasured = fingerprints[key]
        del measurement["ui/package-lock.json"]
        if inputs is not None and measurement != inputs:
            raise ValueError(f"Policy, analyzer or UI measurement inputs changed at {sha}")
        if previous_unmeasured is not None and not removed_only(previous_unmeasured, unmeasured):
            raise ValueError(f"Unmeasured UI dependencies added or changed at {sha}; separate review required")
        inputs = measurement
        previous_unmeasured = unmeasured
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
    print(f"Base `{args.base}` → source HEAD `{args.head}`; **{len(chain) - 1} verified checkpoint transitions**.")
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
