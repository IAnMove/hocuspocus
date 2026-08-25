"""Product identity. The repo-root VERSION file is the only version source."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
VERSION_PATH = _ROOT / "VERSION"


def read_app_version() -> str:
    """Return the HocusPocus release string from the repo-root VERSION file."""
    try:
        return VERSION_PATH.read_text(encoding="utf-8").splitlines()[0].strip()
    except OSError:
        return ""
