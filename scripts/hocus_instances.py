"""Read-only table of HocusPocus processes on this machine.

The script never stops, restarts, or signals a process. It prints the port,
pid, folder, commit, how many commits that checkout is behind
``origin/development``, RAM, VRAM, and who holds the GPU lock.

The lock coordinates only processes that already contain
``app/services/gpu_machine_lock.py``. Updating a running instance is a
separate decision.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from services.gpu_machine_lock import read_holder  # noqa: E402


def _process_ids() -> list[int]:
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    return sorted(int(entry.name) for entry in proc.iterdir() if entry.name.isdigit())


def _cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", "replace")


def _cwd(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return ""


def _environ(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    found: dict[str, str] = {}
    for item in raw.split(b"\x00"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        found[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return found


def _is_instance(command: str, folder: str) -> bool:
    if "launch.py" not in command:
        return False
    blob = f"{command} {folder}".lower()
    return "hocuspocus" in blob or "pinokio" in blob


def _rss_mib(pid: int) -> str:
    try:
        text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "-"
    for line in text.splitlines():
        if not line.startswith("VmRSS:"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            return str(int(parts[1]) // 1024)
    return "-"


def _repo_root(folder: str) -> str:
    if not folder:
        return ""
    path = Path(folder)
    if path.name == "app":
        return str(path.parent)
    return folder


def _git_output(root: str, *args: str) -> str:
    if not root:
        return ""
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _git_facts(root: str) -> tuple[str, str]:
    commit = _git_output(root, "rev-parse", "--short", "HEAD") or "-"
    behind = _git_output(root, "rev-list", "--count", "HEAD..origin/development") or "-"
    return commit, behind


def vram_by_pid() -> dict[int, int] | None:
    """Return pid to MiB from nvidia-smi, or ``None`` when the probe fails."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    found: dict[int, int] = {}
    for line in result.stdout.splitlines():
        parts = [item.strip() for item in line.split(",")]
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        found[int(parts[0])] = int(parts[1])
    return found


def _vram_cell(vram: dict[int, int] | None, pid: int) -> str:
    if vram is None:
        return "-"
    return str(vram.get(pid, 0))


def _instance_row(pid: int, vram: dict[int, int] | None) -> dict[str, str] | None:
    command = _cmdline(pid)
    folder = _cwd(pid)
    if not _is_instance(command, folder):
        return None
    env = _environ(pid)
    root = _repo_root(folder)
    commit, behind = _git_facts(root)
    return {
        "port": env.get("SERVER_PORT") or "-",
        "pid": str(pid),
        "rss_mib": _rss_mib(pid),
        "vram_mib": _vram_cell(vram, pid),
        "behind": behind,
        "commit": commit,
        "folder": root or folder or "-",
    }


def collect_instances(vram: dict[int, int] | None | object = ...) -> list[dict[str, str]]:
    """Return one row per running HocusPocus ``launch.py``.

    The default probes nvidia-smi. Pass a dict to skip that probe, or ``None``
    when the probe already failed.
    """
    measured: dict[int, int] | None
    if vram is ...:
        measured = vram_by_pid()
    elif isinstance(vram, dict):
        measured = vram
    else:
        measured = None
    rows: list[dict[str, str]] = []
    for pid in _process_ids():
        row = _instance_row(pid, measured)
        if row is not None:
            rows.append(row)
    return rows


def format_table(rows: list[dict[str, str]]) -> str:
    """Return the instance table, including the header."""
    header = (
        f"{'port':<8} {'pid':<8} {'rss_mib':<8} {'vram_mib':<10} "
        f"{'behind':<8} {'commit':<12} folder"
    )
    lines = [header]
    if not rows:
        lines.append("(no HocusPocus launch.py processes)")
        return "\n".join(lines)
    for row in rows:
        lines.append(
            f"{row['port']:<8} {row['pid']:<8} {row['rss_mib']:<8} "
            f"{row['vram_mib']:<10} {row['behind']:<8} {row['commit']:<12} {row['folder']}"
        )
    return "\n".join(lines)


def format_lock() -> str:
    """Return one line naming the live lock holder, or ``lock: free``."""
    holder = read_holder()
    if not holder:
        return "lock: free"
    return (
        "lock: pid={pid} port={port} workspace={workspace} "
        "job={job_id} model={model} since={since}"
    ).format(
        pid=holder.get("pid"),
        port=holder.get("port") or "-",
        workspace=holder.get("workspace") or "-",
        job_id=holder.get("job_id") or "-",
        model=holder.get("model") or "-",
        since=holder.get("since"),
    )


def main() -> int:
    print(format_table(collect_instances()))
    print(format_lock())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
