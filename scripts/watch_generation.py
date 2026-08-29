#!/usr/bin/env python3
"""Every 20 minutes: if Loreframe Lab or the overnight runners died, bring them back."""
from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT.parent / "app"
LOG = ROOT / "watch_generation.log"
INTERVAL = int(os.environ.get("WATCH_INTERVAL_SEC", "1200"))
API_PORTS = (42004, 42003, 42005, 42006)


def log(message: str) -> None:
    line = time.strftime("%H:%M:%S") + " " + message
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def process_has(needle: str) -> bool:
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="ignore")
        except OSError:
            continue
        if needle in cmdline:
            return True
    return False


def maestro_url() -> str | None:
    for port in API_PORTS:
        url = f"http://127.0.0.1:{port}"
        try:
            urllib.request.urlopen(url, timeout=3)
            return url
        except Exception:
            continue
    return None


def restart_lab() -> None:
    log("restarting Loreframe Lab on 0.0.0.0:42004")
    env = os.environ.copy()
    env["PINOKIO_SHARE_LOCAL"] = "true"
    env["SERVER_PORT"] = "42004"
    subprocess.Popen(
        [str(APP / "env" / "bin" / "python"), "launch.py"],
        cwd=str(APP),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def start_runner(script: str, api: str) -> None:
    log(f"starting {script} api={api}")
    env = os.environ.copy()
    env["MAESTRO_API"] = api
    subprocess.Popen(
        ["python3", "-u", str(ROOT / script)],
        cwd=str(ROOT.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def work_finished() -> bool:
    outputs = APP / "outputs"
    return (outputs / "overnight_scarface_gatos_multiclip.mp4").is_file()


def tick() -> None:
    url = maestro_url()
    if not url:
        log("Lab is down")
        restart_lab()
        return
    log(f"Lab ok {url}")
    if work_finished():
        log("Ryan and Enemy Mine mixes exist; watch idle")
        return
    if (
        process_has("overnight_resume.py")
        or process_has("overnight_more_films.py")
        or process_has("overnight_parodies2.py")
    ):
        log("overnight runner still alive")
        return
    start_runner("overnight_parodies2.py", url)


def main() -> None:
    log(f"watch start interval={INTERVAL}s")
    while True:
        try:
            tick()
        except Exception as exc:
            log(f"watch tick failed: {exc}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
