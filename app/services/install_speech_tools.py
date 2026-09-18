"""Install the pinned offline lip-sync engine during app Install/Update."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import platform
import shutil
import tempfile
import urllib.request
import zipfile

VERSION = "1.14.0"
ROOT = Path(__file__).resolve().parents[1] / ".runtime" / "speech"
RELEASES = {
    "Linux": "a9a9074862cff47b2d59b8bf399a678a3b0b74f9452ad6ad94cb292913dd8667",
    "Windows": "62fa416a8d5e382a3828ee4bef358ce520d0b4cabdeaea75a7ac266d098d1fe3",
    "Darwin": "f991deacac6c973a14a4431a16a58b842f436531e120cfaea142c87c0d3ab4c5",
}


def bundled_executable() -> Path:
    return ROOT / f"rhubarb-{VERSION}" / ("rhubarb.exe" if os.name == "nt" else "rhubarb")


def install() -> Path | None:
    configured = os.environ.get("RHUBARB_EXECUTABLE", "")
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute() or not candidate.is_file():
            raise RuntimeError("RHUBARB_EXECUTABLE must point to an existing absolute file path.")
        return candidate
    available = shutil.which("rhubarb")
    if available:
        return Path(available)
    target = bundled_executable()
    if target.is_file():
        return target
    system = platform.system()
    if system not in RELEASES or platform.machine().lower() not in {"x86_64", "amd64"}:
        print("Offline lip sync is unavailable on this architecture. Install a native Rhubarb build and set RHUBARB_EXECUTABLE; the rest of the app can still be installed.")
        return None
    name = f"Rhubarb-Lip-Sync-{VERSION}-{'macOS' if system == 'Darwin' else system}"
    ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="install-", dir=ROOT) as temporary:
        folder = Path(temporary)
        archive = folder / "release.zip"
        request = urllib.request.Request(f"https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v{VERSION}/{name}.zip", headers={"User-Agent": "HocusPocus-installer"})
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != RELEASES[system]:
            raise RuntimeError("Rhubarb download checksum mismatch; nothing was installed.")
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(folder / "unpacked")  # Exact pinned archive, verified above.
        source = folder / "unpacked" / name
        executable = source / target.name
        if not executable.is_file():
            raise RuntimeError("The Rhubarb archive is incomplete.")
        executable.chmod(executable.stat().st_mode | 0o111)
        source.rename(target.parent)
    return target


if __name__ == "__main__":
    installed = install()
    if installed:
        print(f"Offline lip sync ready: {installed}")
