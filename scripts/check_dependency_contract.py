#!/usr/bin/env python3
"""Small, offline smoke check for the dependency installation contract.

This intentionally validates launcher text and lock metadata instead of
installing Maestro's large CUDA/AI stack.  Pass ``--npm-ci`` when a real npm
lockfile smoke is wanted; ``npm ci --dry-run`` is still non-mutating.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_REQUIREMENTS = ROOT / "app" / "requirements.txt"
INSTALL_SCRIPT = ROOT / "install.js"
UPDATE_SCRIPT = ROOT / "update.js"
UI_DIR = ROOT / "ui"
PACKAGE_JSON = UI_DIR / "package.json"
PACKAGE_LOCK = UI_DIR / "package-lock.json"
PYTHON_RESOLVER = "uv pip install -r requirements.txt --index-strategy unsafe-best-match"


def _normalise_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_declarations() -> dict[tuple[str, str], list[int]]:
    declarations: dict[tuple[str, str], list[int]] = {}
    for line_number, raw_line in enumerate(APP_REQUIREMENTS.read_text().splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        requirement, _, marker = line.partition(";")
        match = re.match(r"([A-Za-z0-9][A-Za-z0-9_.-]*)", requirement.strip())
        if not match:
            raise AssertionError(f"cannot parse requirement at line {line_number}: {raw_line}")
        key = (_normalise_name(match.group(1)), marker.strip())
        declarations.setdefault(key, []).append(line_number)
    return declarations


def _assert_python_manifest() -> None:
    duplicate_declarations = {
        key: lines for key, lines in _requirement_declarations().items() if len(lines) > 1
    }
    if duplicate_declarations:
        raise AssertionError(f"duplicate requirement declarations: {duplicate_declarations}")


def _assert_launcher_parity() -> None:
    install = INSTALL_SCRIPT.read_text()
    update = UPDATE_SCRIPT.read_text()
    for name, text in (("install.js", install), ("update.js", update)):
        if text.count(PYTHON_RESOLVER) != 1:
            raise AssertionError(f"{name} must use the shared Python resolver exactly once")
        if "npm install" in text:
            raise AssertionError(f"{name} still uses npm install instead of npm ci")
        if "npm ci" not in text:
            raise AssertionError(f"{name} does not install the UI from the npm lockfile")


def _assert_npm_lock_matches_manifest() -> None:
    manifest = json.loads(PACKAGE_JSON.read_text())
    lock = json.loads(PACKAGE_LOCK.read_text())
    if lock.get("lockfileVersion", 0) < 2:
        raise AssertionError("ui/package-lock.json must be a lockfileVersion 2 or newer")
    root = lock.get("packages", {}).get("")
    if root is None:
        raise AssertionError("ui/package-lock.json has no root package entry")
    for field in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        expected = manifest.get(field, {})
        actual = root.get(field, {})
        if actual != expected:
            raise AssertionError(f"package-lock root {field} differs from package.json")


def _run_npm_smoke() -> None:
    subprocess.run(
        ["npm", "ci", "--dry-run", "--ignore-scripts"],
        cwd=UI_DIR,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--npm-ci",
        action="store_true",
        help="also run npm ci --dry-run --ignore-scripts in ui/",
    )
    args = parser.parse_args()
    _assert_python_manifest()
    _assert_launcher_parity()
    _assert_npm_lock_matches_manifest()
    if args.npm_ci:
        _run_npm_smoke()
    print("dependency contract smoke: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"dependency contract smoke: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
