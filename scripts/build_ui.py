#!/usr/bin/env python3
"""Ensure/repair the production UI without installing Python engines or models."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from services.ui_distribution import (  # noqa: E402
    MANIFEST, build_status, report_identity, source_digest, source_identity, validate_artifact,
)


@contextmanager
def build_lock(ui: Path):
    # OS-owned lock releases even on process termination; no stale lock to delete.
    with (ui / ".hocus-ui-build.lock").open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another React build is running. Wait for it to finish and retry.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)


def ensure_build(root: Path = ROOT, *, force: bool = False, run=subprocess.run) -> dict:
    with build_lock(root / "ui"):
        return _build(root, force=force, run=run)


def _build(root: Path, *, force: bool, run) -> dict:
    state = build_status(root, current=True)
    if state["ready"] and not force:
        print(f"[HocusPocus] React build verified: {state['build']['build_id']}", flush=True)
        return state["build"]
    ui = root / "ui"
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise RuntimeError("npm was not found. Repair Pinokio's Node.js tools and retry Repair Web UI.")
    print(f"[HocusPocus] Preparing React UI: {state['reason'] or 'repair requested'}", flush=True)
    before = source_digest(root)
    source = source_identity(root)
    staging = Path(tempfile.mkdtemp(prefix=".hocus-ui-build-", dir=ui))
    backup = staging.with_name(staging.name.replace("-build-", "-previous-"))
    dist = ui / "dist"
    published = False
    env = {**os.environ, "HOCUSPOCUS_GRAPH_PYTHON": sys.executable,
           # Baked into the bundle so a stale browser tab can prove which commit it runs.
           "VITE_HOCUS_BUILD_COMMIT": source["commit"]}
    try:
        # Explicit dev dependencies: TypeScript/Vite are required even with NODE_ENV=production.
        for args in (["ci", "--include=dev", "--no-audit", "--no-fund"],
                     ["run", "build", "--", "--outDir", staging.name]):
            print(f"[HocusPocus] npm {' '.join(args)}", flush=True)
            run([npm, *args], cwd=ui, env=env, check=True, shell=os.name == "nt")
        validate_artifact(staging)
        if source_digest(root) != before:
            raise RuntimeError("UI sources changed during compilation. Retry after the update finishes.")
        info = {"schema": 1, **source, "source_digest": before,
                "build_id": f"{source['commit'][:12]}-{staging.name.rsplit('-', 1)[-1]}",
                "built_at": datetime.now(timezone.utc).isoformat(),
                "files": {p.relative_to(staging).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(staging.rglob("*")) if p.is_file()}}
        (staging / MANIFEST).write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        validate_artifact(staging, managed=True)
        if dist.exists():
            dist.rename(backup)
        try:
            staging.rename(dist)
            published = True
        except OSError:
            if backup.exists():
                backup.rename(dist)
            raise
        print(f"[HocusPocus] React build ready: {info['build_id']} | {info['built_at']}", flush=True)
        return info
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        # If publishing failed and restoration failed, retain the only good build.
        if published:
            shutil.rmtree(backup, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Rebuild even when the receipt is current")
    parser.add_argument("--check", action="store_true", help="Verify only; never install or compile")
    args = parser.parse_args()
    try:
        if args.check:
            state = build_status(current=True)
            print(json.dumps({"ready": state["ready"], "reason": state["reason"],
                              "build_id": state["build"].get("build_id")}))
            return 0 if state["ready"] else 1
        report_identity()
        ensure_build(force=args.force)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        # Pinokio shell.run recognises this sentinel, including silent npm failures.
        print(f"Error: HOCUS_UI_BUILD_FAILED: {exc}\nReact setup did not complete. See the npm error above, then retry Repair Web UI. Restart Start after repair.", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
