#!/usr/bin/env python3
"""Boot one worktree's server on a free port, isolated from the live install, and smoke-test it.

Usage (normally through scripts/boot_smoke.sh):

    python scripts/boot_smoke.py <worktree> [--port N] [--list scripts/boot_smoke/<slice>.txt] [--core]

What it does, in order:

1. Refuses the live checkout (the repo's main worktree), a worktree that
   already runs a server, a busy port, and (unless ``--cpu``) less than
   ``--min-free-vram-mb`` of free VRAM on GPU 0.
2. Makes a scratch folder next to the worktree (same disk, so every move is
   a rename) for outputs, uploads, settings, caches, LoRAs and an empty
   checkpoint folder. Nothing the server writes reaches the live install.
3. Full server: sets aside whatever the worktree has at ``app/wgp_config.json``,
   ``app/settings``, ``app/uploads``, ``app/outputs``, ``app/loras`` and
   ``cache``, and puts links into the scratch folder there, plus a seeded
   ``wgp_config.json`` (no first-boot auto-tune, every path in the scratch
   folder, checkpoints only from the empty folder, so no model can load).
   ``app/env`` and ``ui/dist`` are linked from the live install when the
   worktree has none. Core server (``--core``): runs ``app/core_runtime.py``
   from a working folder inside the scratch folder; it keeps all its state
   under its working folder.
4. Starts the server with ``HOCUS_GPU_MACHINE_LOCK=0`` and ``HF_HUB_OFFLINE=1``
   and waits for the URL line Pinokio waits for.
5. Calls every line of ``scripts/boot_smoke/default.txt`` and of each
   ``--list`` file, reads ``/openapi.json``, counts the routes, looks for
   duplicate operation ids and, for the full server, compares the routes with
   ``tests/fixtures/route_table_runtime.json``.
6. Stops the server by its exact PID (SIGTERM, then SIGKILL after a wait;
   never a pattern match), puts the worktree back as it was, and leaves the
   log, the report and the scratch folder in place for review.

A smoke list line is ``METHOD /path [status[,status]] [json body]``; a line
that starts with ``#`` is a comment. The status defaults to 200.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SMOKE_LISTS = ROOT / "scripts" / "boot_smoke"
RUNTIME_FIXTURE = ROOT / "tests" / "fixtures" / "route_table_runtime.json"
PORTS = range(42080, 42100)
READY = re.compile(r"(?:HocusPocus Lab UI|Web UI repair page \(API only\)):\s+http://[0-9.]+:(\d+)/")
MARKER = "hocus_boot_smoke"
# Engine defaults of a first boot (as WanGP writes them), with paths replaced below.
WGP_DEFAULTS: dict[str, Any] = {
    "UI_theme": "default", "attention_mode": "auto", "audio_output_codec": "aac_128", "audio_profile": 3,
    "audio_stand_alone_output_codec": "wav", "boost": 1, "clear_file_list": 5, "compile": "",
    "embed_source_images": False, "enable_4k_resolutions": 0, "enable_int8_kernels": 1, "flashvsr_backend": "auto",
    "flashvsr_mode": 1, "flashvsr_persistence": 1, "flashvsr_topk_ratio": 0.0, "image_output_codec": "jpeg_95",
    "image_profile": 3, "lm_decoder_engine": "", "matanyone_version": "v1", "max_reserved_loras": -1,
    "metadata_type": "metadata", "mmaudio_mode": 0, "mmaudio_persistence": 1, "model_hierarchy_type": 1,
    "preload_model_policy": [], "profile": 4, "prompt_enhancer_quantization": "quanto_int8",
    "prompt_enhancer_randomize_seed": True, "prompt_enhancer_temperature": 0.6, "prompt_enhancer_top_p": 0.9,
    "queue_color_scheme": "pastel", "rife_version": "v4", "save_queue_if_crash": 1, "text_encoder_quantization": "int8",
    "transformer_quantization": "int8", "transformer_types": [], "vae_config": 1, "video_container": "mp4",
    "video_output_codec": "libx264_8", "video_profile": 3, "vram_safety_coefficient": 0.8,
}
# Worktree paths the full server writes to, and the scratch folder each one points to.
REDIRECTS = {
    "app/settings": "settings",
    "app/uploads": "uploads",
    "app/outputs": "outputs",
    "app/loras": "loras",
    "cache": "cache",
}


class SmokeError(RuntimeError):
    """A precondition failed, or the server did not boot."""


@dataclass
class Check:
    method: str
    path: str
    statuses: tuple[int, ...] = (200,)
    body: Any = None


def parse_list(path: Path) -> list[Check]:
    checks = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 3)
        if len(parts) < 2 or not parts[1].startswith("/"):
            raise SmokeError(f"{path}:{number}: expected 'METHOD /path [status] [json]'")
        statuses = tuple(int(item) for item in parts[2].split(",")) if len(parts) > 2 else (200,)
        body = json.loads(parts[3]) if len(parts) > 3 else None
        checks.append(Check(parts[0].upper(), parts[1], statuses, body))
    return checks


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout


def live_checkout(worktree: Path) -> Path:
    """The repo's main worktree: the checkout the running servers use."""
    first = _git(worktree, "worktree", "list", "--porcelain").splitlines()[0]
    return Path(first.split(" ", 1)[1]).resolve()


def running_instances() -> list[dict[str, str]]:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from hocus_instances import collect_instances
    except Exception:  # The table is a courtesy; the port probe below still refuses a busy port.
        return []
    return collect_instances(vram={})


def port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return False
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def choose_port(requested: int | None, taken: set[str]) -> int:
    candidates = [requested] if requested else list(PORTS)
    for port in candidates:
        if str(port) not in taken and port_is_free(port):
            return port
    raise SmokeError(f"no free port in {candidates[0]}-{candidates[-1]}")


def free_vram_mib() -> int | None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    values = [int(line) for line in result.stdout.split() if line.strip().isdigit()]
    return values[0] if values else None


def seeded_config(scratch: Path) -> dict[str, Any]:
    outputs = str(scratch / "outputs")
    return {
        **WGP_DEFAULTS,
        MARKER: {"scratch": str(scratch), "note": "written by scripts/boot_smoke.py"},
        "save_path": outputs,
        "image_save_path": outputs,
        "audio_save_path": outputs,
        "loras_root": str(scratch / "loras"),
        "checkpoints_paths": [str(scratch / "ckpts")],
        "services": {"auto_performance": False, "auto_performance_applied": True, "active_workspace": "default"},
    }


@dataclass
class WorktreeState:
    """Swap worktree paths for links into the scratch folder, by renames only, and swap them back."""

    worktree: Path
    scratch: Path
    swapped: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)

    def _aside(self, relative: str) -> Path:
        return self.scratch / "set-aside" / relative.replace("/", "__")

    def swap(self, relative: str, make) -> None:
        target = self.worktree / relative
        if target.exists() or target.is_symlink():
            aside = self._aside(relative)
            aside.parent.mkdir(parents=True, exist_ok=True)
            os.rename(target, aside)
            self.swapped.append(relative)
        else:
            self.created.append(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        make(target)

    def link_if_missing(self, relative: str, source: Path) -> None:
        target = self.worktree / relative
        if target.exists() or target.is_symlink():
            return
        if not source.exists():
            raise SmokeError(f"{source} does not exist in the live install")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)
        self.created.append(relative)

    def restore(self) -> list[str]:
        """Move what the smoke made into the scratch folder and put set-aside paths back."""
        notes = []
        kept = self.scratch / "worktree-state"
        kept.mkdir(parents=True, exist_ok=True)
        for relative in [*self.swapped, *self.created]:
            target = self.worktree / relative
            if target.exists() or target.is_symlink():
                os.rename(target, kept / relative.replace("/", "__"))
        for relative in self.swapped:
            os.rename(self._aside(relative), self.worktree / relative)
            notes.append(f"restored {relative}")
        return notes


def prepare_full(state: WorktreeState, live: Path) -> None:
    scratch = state.scratch
    for name in ("outputs", "uploads", "settings", "cache", "loras", "ckpts"):
        (scratch / name).mkdir(parents=True, exist_ok=True)
    state.link_if_missing("app/env", live / "app" / "env")
    state.link_if_missing("ui/dist", live / "ui" / "dist")
    config = json.dumps(seeded_config(scratch), indent=4)
    state.swap("app/wgp_config.json", lambda path: path.write_text(config, encoding="utf-8"))
    for relative, folder in REDIRECTS.items():
        state.swap(relative, lambda path, folder=folder: path.symlink_to(scratch / folder, target_is_directory=True))


def server_env(port: int, *, cpu: bool, core: bool) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update({
        "SERVER_PORT": str(port),
        "SERVER_NAME": "127.0.0.1",
        "PINOKIO_SHARE_LOCAL": "false",
        "HOCUS_GPU_MACHINE_LOCK": "0",
        "HF_HUB_OFFLINE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    })
    if cpu:
        env["CUDA_VISIBLE_DEVICES"] = ""
    if core:
        env["HOCUS_RUNTIME"] = "core"
    return env


def wait_ready(process: subprocess.Popen, log: Path, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        match = READY.search(log.read_text(encoding="utf-8", errors="replace"))
        if match:
            port = int(match.group(1))
            if _get(port, "/openapi.json")[0] == 200:
                return port
        if process.poll() is not None:
            raise SmokeError(f"the server exited with {process.returncode} before it was ready; see {log}")
        time.sleep(1)
    raise SmokeError(f"the server was not ready after {timeout:.0f} s; see {log}")


def _get(port: int, path: str, method: str = "GET", body: Any = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def run_checks(port: int, checks: list[Check]) -> list[dict[str, Any]]:
    results = []
    for check in checks:
        started = time.monotonic()
        status, _body = _get(port, check.path, check.method, check.body)
        results.append({
            "method": check.method, "path": check.path, "status": status, "expected": list(check.statuses),
            "ok": status in check.statuses, "ms": int((time.monotonic() - started) * 1000),
        })
    return results


def _openapi_path(path: str) -> str:
    return re.sub(r"\{([^}:]+):[^}]+\}", r"{\1}", path)


def known_duplicates(profile: str) -> set[str]:
    """``METHOD /path`` lines of scripts/boot_smoke/<profile>.known-duplicates.txt (each with its reason)."""
    path = SMOKE_LISTS / f"{profile}.known-duplicates.txt"
    if not path.is_file():
        return set()
    lines = (line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines())
    return {" ".join(line.split()[:2]) for line in lines if line}


def core_served_routes(python: str, worktree: Path, cwd: Path, env: dict[str, str]) -> list[str]:
    """The core server's served (method, path) list, from an import in a child process (no torch, under a second)."""
    code = (
        "import json, sys\n"
        f"sys.path[:0] = [{str(worktree)!r}, {str(worktree / 'app')!r}]\n"
        "import core_runtime\n"
        "from tests.support.full_server import served_route_table\n"
        "print(json.dumps([row['method'] + ' ' + row['path'] for row in served_route_table(core_runtime.api)]))\n"
    )
    result = subprocess.run([python, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise SmokeError(f"could not list the core server's routes: {result.stderr.strip()[-600:]}")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _openapi_operations(port: int) -> list[tuple[str, str, str | None]]:
    status, raw = _get(port, "/openapi.json")
    if status != 200:
        raise SmokeError(f"/openapi.json answered {status}")
    return [
        (method.upper(), path, operation.get("operationId"))
        for path, item in json.loads(raw).get("paths", {}).items()
        for method, operation in item.items() if isinstance(operation, dict)
    ]


def _fixture_diff(operations: list[tuple[str, str, str | None]]) -> dict[str, Any]:
    fixture = json.loads(RUNTIME_FIXTURE.read_text(encoding="utf-8"))["routes"]
    # A real boot serves "/" from ui/dist (a mount), not the repair page the test import records.
    expected = {(row["method"], _openapi_path(row["path"])) for row in fixture
                if row["include_in_schema"] and row["method"] != "MOUNT" and row["path"] != "/"}
    served = {(method, path) for method, path, _id in operations}
    return {
        "fixture_routes": len(expected),
        "missing": sorted(" ".join(item) for item in expected - served),
        "extra": sorted(" ".join(item) for item in served - expected),
    }


def route_report(port: int, log: Path, *, profile: str, served: list[str] | None = None) -> dict[str, Any]:
    """Route count, duplicates and (full server) the comparison with route_table_runtime.json.

    OpenAPI keeps one operation per method and path, so it cannot show a route
    registered twice under two handler names. With ``served`` (the flattened
    table) the duplicates are exact; without it, the log's FastAPI warning
    "Duplicate Operation ID" is the signal, and the test import
    (tests/characterization) checks the full server's table itself.
    """
    operations = _openapi_operations(port)
    ids = [operation_id for _method, _path, operation_id in operations if operation_id]
    report: dict[str, Any] = {
        "routes": len(operations),
        "duplicate_operation_ids": sorted({item for item in ids if ids.count(item) > 1}),
    }
    allowed = known_duplicates(profile)
    if served is not None:
        report["served_routes"] = len(served)
        twice = sorted({route for route in served if served.count(route) > 1})
        report["duplicate_routes"] = [route for route in twice if route not in allowed]
        report["known_duplicate_routes"] = [route for route in twice if route in allowed]
        ok = not report["duplicate_routes"]
    else:
        warned = "Duplicate Operation ID" in log.read_text(encoding="utf-8", errors="replace")
        report["duplicate_warning_in_log"] = warned
        ok = not report["duplicate_operation_ids"] and not warned
    if profile == "full":
        report.update(_fixture_diff(operations))
        ok = ok and not report["missing"] and not report["extra"]
    report["ok"] = ok
    return report


def _children(pid: int) -> list[int]:
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            continue
        if int(fields[1]) == pid:
            found.append(int(entry.name))
            found.extend(_children(int(entry.name)))
    return found


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop(process: subprocess.Popen, wait: float = 45) -> dict[str, Any]:
    """SIGTERM the server's own PID, then SIGKILL that PID; then any child it left, by PID."""
    children = _children(process.pid) if Path("/proc").is_dir() else []
    result: dict[str, Any] = {"pid": process.pid, "signal": "SIGTERM"}
    if process.poll() is None:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            process.kill()
            result["signal"] = "SIGKILL"
            process.wait(timeout=wait)
    result["returncode"] = process.returncode
    leftovers = [pid for pid in children if _alive(pid)]
    for pid in leftovers:
        os.kill(pid, signal.SIGTERM)
    result["children_stopped"] = leftovers
    return result


def _preflight(args, worktree: Path, live: Path) -> int:
    if worktree == live:
        raise SmokeError(f"{worktree} is the live checkout; boot a separate worktree")
    if not (worktree / "app" / "launch.py").is_file():
        raise SmokeError(f"{worktree} is not a HocusPocus checkout")
    instances = running_instances()
    same = [row for row in instances if Path(row.get("folder", "")).resolve() == worktree]
    if same:
        raise SmokeError(f"a server already runs from {worktree} (pid {same[0]['pid']})")
    port = choose_port(args.port, {row.get("port", "") for row in instances})
    if not args.cpu:
        free = free_vram_mib()
        if free is not None and free < args.min_free_vram_mb:
            raise SmokeError(f"GPU 0 has {free} MiB free; the smoke needs {args.min_free_vram_mb} MiB (or use --cpu)")
    return port


def _scratch(args, worktree: Path, port: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = Path(args.scratch) if args.scratch else worktree.parent / f"{worktree.name}.boot-smoke"
    scratch = (base / f"{stamp}-{'core' if args.core else 'full'}-{port}").resolve()
    scratch.mkdir(parents=True)
    if not args.core and os.stat(scratch).st_dev != os.stat(worktree).st_dev:
        raise SmokeError(f"{scratch} must be on the worktree's disk, so the worktree is restored by renames")
    return scratch


def run(args) -> dict[str, Any]:
    worktree = Path(args.worktree).resolve()
    live = Path(args.live).resolve() if args.live else live_checkout(worktree)
    port = _preflight(args, worktree, live)
    scratch = _scratch(args, worktree, port)
    checks = parse_list(SMOKE_LISTS / ("core.txt" if args.core else "default.txt"))
    for extra in args.list or []:
        checks.extend(parse_list(Path(extra)))
    state = WorktreeState(worktree, scratch)
    report: dict[str, Any] = {"worktree": str(worktree), "scratch": str(scratch), "profile": "core" if args.core else "full"}
    log = scratch / "server.log"
    process = None
    try:
        env = server_env(port, cpu=args.cpu, core=args.core)
        served = None
        if args.core:
            state.link_if_missing("ui/dist", live / "ui" / "dist")
            cwd = scratch / "core-root"
            cwd.mkdir()
            python = str(live / "app" / "env" / "bin" / "python")
            command = [python, str(worktree / "app" / "core_runtime.py")]
            served = core_served_routes(python, worktree, cwd, env)
        else:
            prepare_full(state, live)
            cwd = worktree / "app"
            command = [str(worktree / "app" / "env" / "bin" / "python"), "launch.py"]
        started = time.monotonic()
        with log.open("wb") as handle:
            process = subprocess.Popen(command, cwd=cwd, env=env,
                                       stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        report["pid"] = process.pid
        report["port"] = wait_ready(process, log, args.timeout)
        report["boot_seconds"] = round(time.monotonic() - started, 1)
        report["checks"] = run_checks(report["port"], checks)
        report["routes"] = route_report(report["port"], log, profile=report["profile"], served=served)
    finally:
        if process is not None:
            report["stop"] = stop(process)
        report["restored"] = state.restore()
        (scratch / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["ok"] = all(item["ok"] for item in report["checks"]) and report["routes"]["ok"]
    return report


def _print(report: dict[str, Any]) -> None:
    print(f"[boot-smoke] {report['profile']} server pid {report.get('pid')} on port {report.get('port')}, "
          f"ready in {report.get('boot_seconds')} s")
    for item in report.get("checks", []):
        mark = "ok  " if item["ok"] else "FAIL"
        print(f"[boot-smoke] {mark} {item['method']} {item['path']} -> {item['status']} ({item['ms']} ms)")
    routes = report.get("routes", {})
    print(f"[boot-smoke] routes in OpenAPI: {routes.get('routes')}"
          + (f" (fixture: {routes['fixture_routes']})" if "fixture_routes" in routes else "")
          + (f", served: {routes['served_routes']}" if "served_routes" in routes else "")
          + f"; duplicate operation ids: {routes.get('duplicate_operation_ids')}")
    for key, label in (("missing", "missing against route_table_runtime.json"),
                       ("extra", "extra against route_table_runtime.json"),
                       ("duplicate_routes", "routes served twice"),
                       ("known_duplicate_routes", "known duplicates (listed with a reason)")):
        if routes.get(key):
            print(f"[boot-smoke] {label}: {routes[key]}")
    stopped = report.get("stop", {})
    print(f"[boot-smoke] stopped pid {stopped.get('pid')} with {stopped.get('signal')} "
          f"(exit {stopped.get('returncode')}); report and log in {report['scratch']}")
    print(f"[boot-smoke] {'PASS' if report.get('ok') else 'FAIL'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("worktree", help="the worktree to boot (never the live checkout)")
    parser.add_argument("--port", type=int, help=f"default: the first free port in {PORTS.start}-{PORTS.stop - 1}")
    parser.add_argument("--list", action="append", help="an extra smoke list, e.g. scripts/boot_smoke/series.txt")
    parser.add_argument("--core", action="store_true", help="boot app/core_runtime.py (the no-local-AI server)")
    parser.add_argument("--cpu", action="store_true", help="hide the GPU from the server (CUDA_VISIBLE_DEVICES='')")
    parser.add_argument("--live", help="the live checkout to link app/env and ui/dist from (default: main worktree)")
    parser.add_argument("--scratch", help="where to keep the run (default: <worktree>.boot-smoke next to it)")
    parser.add_argument("--timeout", type=float, default=300, help="seconds to wait for the URL line")
    parser.add_argument("--min-free-vram-mb", type=int, default=3072)
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except SmokeError as error:
        print(f"[boot-smoke] {error}", file=sys.stderr)
        return 2
    _print(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
