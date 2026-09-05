"""Aggregate required GitHub Actions job results.

Cancelled, skipped, missing or failed jobs are not success. This is the
truthful final CI status; it does not publish comments or tokens.
"""
from __future__ import annotations

import argparse
import sys

SUCCESS = "success"


def evaluate(results: dict[str, str]) -> tuple[bool, list[str]]:
    if not results:
        return False, ["no required jobs reported"]
    failed = [
        f"{name}={value or 'missing'}"
        for name, value in results.items()
        if value != SUCCESS
    ]
    return (not failed), failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pairs",
        nargs="+",
        help="NAME=RESULT from GitHub needs.<job>.result",
    )
    args = parser.parse_args(argv)
    results: dict[str, str] = {}
    for item in args.pairs:
        if "=" not in item:
            print(f"invalid result pair: {item}", file=sys.stderr)
            return 2
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            print(f"invalid result pair: {item}", file=sys.stderr)
            return 2
        results[name] = value.strip()
    ok, failed = evaluate(results)
    for name, value in results.items():
        print(f"{name}: {value}")
    if not ok:
        print("CI required failed: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
