"""Product identity. The repo-root VERSION file is the only version source.

The deployed source (commit, branch, local edits) is read once, when the
backend process starts, so every page, export and asset manifest reports the
code that is actually running even if the checkout changes afterwards.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import subprocess

_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = _ROOT / "VERSION"
REPOSITORY_URL = "https://github.com/IAnMove/hocuspocus"
AUTHOR_X_HANDLE = "theinaog"
CREDITS = (
    {"name": "Maestro", "role": "fork origin"},
    {"name": "WanGP", "role": "local generation engine"},
    {"name": "ACE-Step", "role": "music"},
    {"name": "Qwen", "role": "images, voice and language"},
    {"name": "MiniMax H3", "role": "video"},
    {"name": "Pinokio", "role": "installer and launcher"},
)


def read_app_version() -> str:
    """Return the HocusPocus release string from the repo-root VERSION file."""
    try:
        return VERSION_PATH.read_text(encoding="utf-8").splitlines()[0].strip()
    except OSError:
        return ""


def _git(*args: str, root: Path = _ROOT) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                              timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


@lru_cache(maxsize=1)
def startup_identity() -> dict:
    """Source identity captured on first use; call it at startup to pin it."""
    status = _git("status", "--porcelain", "--untracked-files=no")
    commit = _git("rev-parse", "HEAD")
    return {
        "version": read_app_version(),
        "commit": commit or "unknown",
        "branch": _git("branch", "--show-current") or ("detached" if commit else "unknown"),
        "dirty": bool(status) if commit else None,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def manifest_app_ref() -> dict:
    """Small identity stamped into every asset manifest."""
    identity = startup_identity()
    return {"version": identity["version"], "commit": identity["commit"]}


def ui_build_identity(ui_dist: Path) -> dict:
    """The React build receipt written by scripts/build_ui.py (empty for plain npm builds)."""
    try:
        info = json.loads((Path(ui_dist) / "build-info.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(info, dict):
        return {}
    return {key: info[key] for key in ("commit", "branch", "dirty", "build_id", "built_at") if key in info}


def about_payload(ui_dist: Path) -> dict:
    backend = startup_identity()
    ui = ui_build_identity(ui_dist)
    return {
        "name": "HocusPocus",
        "version": backend["version"],
        "repository": REPOSITORY_URL,
        "author": {"x_handle": AUTHOR_X_HANDLE, "x_url": f"https://x.com/{AUTHOR_X_HANDLE}"},
        "backend": backend,
        "ui": ui,
        "in_sync": bool(ui.get("commit")) and ui.get("commit") == backend["commit"],
        "credits": [dict(item) for item in CREDITS],
    }
