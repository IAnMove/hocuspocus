#!/usr/bin/env python3
"""One command, one screen: the local gates an agent would otherwise re-run by hand.

Unknown changed paths are not expanded to the full suite. ``select_local_tests``
would do that, and this gate would then reprint thousands of tests. Mapped
tests still run. The full suite stays a separate, explicit step.

``--quick`` skips characterization and the code-health ratchet.
``--ui`` adds the UI checks. It does not install or build.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dev.gates_lib import failure_details, format_summary, gate_exit_code
from scripts.select_local_tests import (
    grouped_paths,
    load_manifest,
    match_rule_paths,
    posix_path,
    unique_paths,
)
LOG_DIR = ROOT / ".dev-gates"
GUARDS = (
    "verify_clean_repo.py",
    "check_dependency_contract.py",
    "check_documentation_links.py",
    "check_brand_contract.py",
)
CONTRACT_TESTS = (
    "tests/test_ci_shards.py",
    "tests/test_router_wiring.py",
    "tests/test_architecture_contracts.py",
    "tests/test_size_ceilings.py",
    "tests/test_import_layers.py",
)
FIXTURES = (
    "tests/fixtures/route_table.json",
    "tests/fixtures/architecture_wire_inventory.json",
    "tests/fixtures/route_table_runtime.json",
)
UI_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["PYTHON"] = sys.executable
    return env


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
    )


def _write_log(name: str, text: str) -> str:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / f"{name}.log").write_text(text, encoding="utf-8")
    return f".dev-gates/{name}.log"


def _run(command: list[str], cwd: Path) -> tuple[int, str, float]:
    started = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=cwd,
        env=_env(),
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started
    text = proc.stdout
    if proc.stderr:
        text = text + ("\n" if text else "") + proc.stderr
    return proc.returncode, text, elapsed


def _result(name: str, status: str, seconds: float, log_text: str, details: list[str] | None = None) -> dict:
    log = _write_log(name, log_text)
    return {
        "name": name,
        "status": status,
        "seconds": seconds,
        "details": details or [],
        "log": log,
    }


def _command_gate(name: str, command: list[str], cwd: Path | None = None) -> dict:
    code, text, elapsed = _run(command, cwd or ROOT)
    status = "PASS" if code == 0 else "FAIL"
    details = failure_details(text) if status == "FAIL" else []
    return _result(name, status, elapsed, text, details)


def _skip(name: str, reason: str) -> dict:
    return _result(name, "SKIP", 0.0, reason + "\n", [])


def _pytest(name: str, paths: list[str]) -> dict:
    command = [
        "nice", "-n", "10",
        sys.executable, "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider",
        *paths,
    ]
    return _command_gate(name, command)


def _changed(base: str) -> list[str]:
    names: list[str] = []
    commands = (
        ["diff", "--name-only", f"{base}...HEAD"],
        ["diff", "--name-only"],
        ["diff", "--name-only", "--cached"],
        ["ls-files", "--others", "--exclude-standard"],
    )
    for command in commands:
        proc = _git(*command)
        if proc.returncode == 0:
            names.extend(proc.stdout.splitlines())
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in names:
        path = raw.strip().replace("\\", "/")
        if path and path not in seen:
            seen.add(path)
            ordered.append(path)
    ordered.sort()
    return ordered


def _mapped_tests(changed: list[str]) -> tuple[list[str], list[str]]:
    manifest = load_manifest(ROOT / "scripts" / "ci_test_groups.json")
    grouped = set(grouped_paths(manifest))
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
    return unique_paths(targets), unknown


def _selected_gate(base: str) -> dict:
    changed = _changed(base)
    if not changed:
        return _skip("selected-tests", "no changed files")
    targets, unknown = _mapped_tests(changed)
    note = (
        f"changed {len(changed)}; mapped {len(targets)}; "
        f"unmapped {len(unknown)} (not expanded to the full suite)\n"
    )
    if unknown:
        note += "\n".join(unknown) + "\n"
    if not targets:
        result = _skip("selected-tests", note.strip())
        return result
    gate = _pytest("selected-tests", targets)
    log_path = ROOT / ".dev-gates" / "selected-tests.log"
    log_path.write_text(note + log_path.read_text(encoding="utf-8"), encoding="utf-8")
    return gate


def _head_bytes(rel: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"HEAD:{rel}"],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _architecture_gate() -> dict:
    code, text, elapsed = _run(
        [sys.executable, "scripts/architecture_contracts.py", "--write"],
        ROOT,
    )
    changed = []
    for rel in FIXTURES:
        path = ROOT / rel
        current = path.read_bytes() if path.is_file() else None
        if current != _head_bytes(rel):
            changed.append(rel)
    if code != 0:
        details = failure_details(text)
        if changed:
            details = changed[:5]
        return _result("architecture-contracts", "FAIL", elapsed, text, details)
    if changed:
        message = "fixture diff beyond HEAD:\n" + "\n".join(changed) + "\n"
        return _result("architecture-contracts", "FAIL", elapsed, text + message, changed[:5])
    return _result("architecture-contracts", "PASS", elapsed, text, [])


def _diff_check(base: str) -> dict:
    return _command_gate("diff-check", ["git", "diff", "--check", f"{base}...HEAD"])


def _ui_eslint(changed: list[str]) -> dict:
    files = []
    for path in changed:
        if not path.startswith("ui/"):
            continue
        if Path(path).suffix not in UI_SOURCE_SUFFIXES:
            continue
        if (ROOT / path).is_file():
            files.append(str(Path(path).relative_to("ui")))
    if not files:
        return _skip("ui-eslint", "no changed UI source files")
    binary = ROOT / "ui" / "node_modules" / ".bin" / "eslint"
    if binary.is_file():
        command = [str(binary), "--max-warnings=0", *files]
    else:
        command = ["npx", "--no-install", "eslint", "--max-warnings=0", *files]
    return _command_gate("ui-eslint", command, ROOT / "ui")


def _ui_gates(base: str) -> list[dict]:
    changed = _changed(base)
    tsc = ROOT / "ui" / "node_modules" / ".bin" / "tsc"
    if tsc.is_file():
        tsc_cmd = [str(tsc), "--noEmit", "-p", "tsconfig.app.json"]
    else:
        tsc_cmd = ["npx", "--no-install", "tsc", "--noEmit", "-p", "tsconfig.app.json"]
    return [
        _command_gate("ui-tsc", tsc_cmd, ROOT / "ui"),
        _command_gate("ui-i18n", ["npm", "run", "i18n:check"], ROOT / "ui"),
        _command_gate("ui-unreachable", ["npm", "run", "unreachable:check"], ROOT / "ui"),
        _ui_eslint(changed),
        _command_gate("ui-test", ["npm", "run", "test"], ROOT / "ui"),
    ]


def _code_health(base: str) -> dict:
    env_note = f"BASE_REF={base}\n"
    started = time.perf_counter()
    env = _env()
    env["BASE_REF"] = base
    proc = subprocess.run(
        ["bash", "scripts/check_code_health_pr_base.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - started
    text = env_note + proc.stdout + ("\n" if proc.stderr else "") + proc.stderr
    status = "PASS" if proc.returncode == 0 else "FAIL"
    details = failure_details(text) if status == "FAIL" else []
    return _result("code-health", status, elapsed, text, details)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/development")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--ui", action="store_true")
    args = parser.parse_args(argv)
    results = _collect(args.base, args.quick, args.ui)
    sys.stdout.write(format_summary(results))
    return gate_exit_code(results)


def _collect(base: str, quick: bool, ui: bool) -> list[dict]:
    results = [_command_gate(name, [sys.executable, f"scripts/{name}"]) for name in GUARDS]
    results.append(_architecture_gate())
    results.append(_pytest("contract-tests", list(CONTRACT_TESTS)))
    results.append(_selected_gate(base))
    if quick:
        results.append(_skip("characterization", "skipped by --quick"))
        results.append(_skip("code-health", "skipped by --quick"))
    else:
        results.append(_pytest("characterization", ["tests/characterization"]))
        results.append(_code_health(base))
    results.append(_diff_check(base))
    if ui:
        results.extend(_ui_gates(base))
    return results


if __name__ == "__main__":
    raise SystemExit(main())
