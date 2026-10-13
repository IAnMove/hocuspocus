"""Golden responses: record a route's status and body once, then compare.

A golden file is JSON, one per test module, ``{case: {"status": int, "body": ...}}``.
Bodies are normalised first, so they do not depend on the machine or the clock:

- known directories (the test's state folder, the repo) become placeholders;
- ISO date-times and WanGP file-name stamps (``2026-10-13-11h47m51s``)
  become ``<TIME>``, today's date ``<TODAY>``, UUIDs and 32-digit hex ids
  ``<ID>``;
- numbers under clock-like keys (``created_at``, ``mtime``, ``updatedAt`` ...)
  become ``<TIME>`` when they read "now" (within a day of the test's clock, in
  seconds, milliseconds, microseconds or nanoseconds). A fixed stamp the test
  set itself (``tests/characterization/media.py`` ``BASE_MTIME``) is kept, so
  a change to which time a route reports still fails the golden. A measured
  duration under such a key (``elapsed_time``) is not a clock: ``mask`` it;
- keys the caller names in ``mask`` become ``<MASKED>`` (sizes that depend on
  an encoder version, for example), and each ``(pattern, replacement)`` in
  ``replace`` is applied to every string (the same size inside a URL).

``HOCUS_UPDATE_GOLDENS=1`` writes the observed values instead of comparing.
Record goldens on ``development`` before you move code, never after.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

UPDATE_ENV = "HOCUS_UPDATE_GOLDENS"

_TIME_PATTERNS = (
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\d{4}-\d{2}-\d{2}-\d{2}h\d{2}m\d{2}s(?:-\d+)?"),
)
# Not inside a longer run of hex digits, but after "_" or "-" too ("series_<32 hex>").
_ID_PATTERNS = (
    re.compile(r"(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"),
    re.compile(r"(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])"),
)
_CLOCK_KEY = re.compile(
    r"(?:^|_)(?:at|time|timestamp|mtime|ctime|created|updated|modified|started|finished)$"
    r"|(?:At|Time|Timestamp|Mtime)$",
)
# A clock value counts as "now" within this many seconds of the test's clock.
_NOW_WINDOW_SECONDS = 86_400
_CLOCK_SCALES = (1, 1_000, 1_000_000, 1_000_000_000)


def normalise(value: Any, *, paths: dict[str, str] | None = None, mask: Iterable[str] = (),
              replace: Iterable[tuple[str, str]] = ()) -> Any:
    """``value`` with machine- and clock-dependent parts replaced by placeholders."""
    replacements = _path_replacements(paths or {})
    masked = set(mask)
    patterns = [(re.compile(pattern), replacement) for pattern, replacement in replace]

    def walk(item: Any, key: str | None = None) -> Any:
        if key is not None and key in masked:
            return "<MASKED>"
        if isinstance(item, dict):
            # Keys too: a library maps generated ids to records.
            return {
                _normalise_text(name, replacements) if isinstance(name, str) else name: walk(child, str(name))
                for name, child in item.items()
            }
        if isinstance(item, list):
            return [walk(child) for child in item]
        if isinstance(item, str):
            text = _normalise_text(item, replacements)
            for pattern, replacement in patterns:
                text = pattern.sub(replacement, text)
            return text
        if isinstance(item, (int, float)) and not isinstance(item, bool) and key and _CLOCK_KEY.search(key):
            return "<TIME>" if _reads_now(item) else item
        return item

    return walk(value)


def _reads_now(value: float) -> bool:
    """True for a clock reading taken while the test ran, in any common unit."""
    now = time.time()
    return any(abs(value / scale - now) <= _NOW_WINDOW_SECONDS for scale in _CLOCK_SCALES)


def _path_replacements(paths: dict[str, str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for path, placeholder in paths.items():
        for variant in {path, os.path.realpath(path), Path(path).as_posix()}:
            pairs.append((variant, placeholder))
    # Longest first, so a folder inside another one keeps its own name.
    return sorted(pairs, key=lambda pair: len(pair[0]), reverse=True)


def _today() -> set[str]:
    """Today's date, local and UTC: log file names carry it (a fixed date such as a protocol version does not)."""
    now = datetime.now(timezone.utc)
    return {now.strftime("%Y-%m-%d"), now.astimezone().strftime("%Y-%m-%d")}


def _normalise_text(text: str, replacements: list[tuple[str, str]]) -> str:
    for path, placeholder in replacements:
        text = text.replace(path, placeholder)
    for pattern in _TIME_PATTERNS:
        text = pattern.sub("<TIME>", text)
    for day in _today():
        text = text.replace(day, "<TODAY>")
    for pattern in _ID_PATTERNS:
        text = pattern.sub("<ID>", text)
    return text


class GoldenBook:
    """The goldens of one test module."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.update = os.environ.get(UPDATE_ENV) == "1"
        self._cases: dict[str, Any] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )

    def check(self, case: str, status: int, body: Any) -> None:
        observed = {"status": status, "body": body}
        if self.update:
            self._cases[case] = observed
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps(dict(sorted(self._cases.items())), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8", newline="\n",
            )
            return
        if case not in self._cases:
            raise AssertionError(
                f"No golden {case!r} in {self.path.name}. Record it on development first: "
                f"{UPDATE_ENV}=1 python -m pytest tests/characterization -p no:cacheprovider"
            )
        expected = self._cases[case]
        assert observed == expected, (
            f"Golden {case!r} changed ({self.path.name}). If the change is intended, "
            f"it is a behaviour change: do not ship it in a move PR."
        )
