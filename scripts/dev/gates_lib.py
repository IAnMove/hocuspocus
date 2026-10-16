"""Pure formatting for scripts/dev/gates.py. No subprocess, no git."""

from __future__ import annotations

import re


MAX_LINES = 30
_FAILED = re.compile(r"^FAILED\s+(\S+)")


def failure_details(log: str, limit: int = 5) -> list[str]:
    """First pytest node ids, or the first useful error line."""
    found: list[str] = []
    for raw in log.splitlines():
        match = _FAILED.match(raw.strip())
        if not match:
            continue
        node = match.group(1).split(" - ", 1)[0].rstrip(":")
        if "::" not in node:
            continue
        found.append(node)
        if len(found) >= limit:
            return found
    if found:
        return found
    for raw in log.splitlines():
        stripped = raw.strip()
        if not stripped or stripped[0] in "=-_":
            continue
        return [stripped[:180]]
    return ["failed"]


def gate_exit_code(results: list[dict]) -> int:
    """1 when any gate failed. Skips do not fail the run."""
    return 1 if any(item.get("status") == "FAIL" for item in results) else 0


def _header(item: dict) -> str:
    seconds = float(item.get("seconds") or 0)
    return f"{item['status']} {item['name']} ({seconds:.1f}s)"


def _failure_block(item: dict) -> list[str]:
    details = [str(line) for line in (item.get("details") or []) if str(line).strip()]
    details = details[:5] or ["failed"]
    log = str(item.get("log") or f".dev-gates/{item['name']}.log")
    lines = [f"{item['name']}: {detail}" for detail in details]
    lines.append(f"log: {log}")
    return lines


def format_summary(results: list[dict]) -> str:
    """At most 30 lines: one status line per gate, then failure details and logs."""
    headers = [_header(item) for item in results]
    blocks = [_failure_block(item) for item in results if item.get("status") == "FAIL"]
    lines = list(headers)
    extra: list[str] = []
    for block in blocks:
        extra.extend(block)
    if len(lines) + len(extra) <= MAX_LINES:
        lines.extend(extra)
        return "\n".join(lines[:MAX_LINES]) + "\n"
    # Keep the first detail and the log path. Drop the rest before dropping logs.
    reduced: list[str] = []
    for block in blocks:
        reduced.append(block[0])
        reduced.append(block[-1])
    if len(lines) + len(reduced) <= MAX_LINES:
        lines.extend(reduced)
        return "\n".join(lines[:MAX_LINES]) + "\n"
    for block in blocks:
        lines.append(block[-1])
        if len(lines) >= MAX_LINES:
            break
    return "\n".join(lines[:MAX_LINES]) + "\n"
