#!/usr/bin/env python3
"""Turn a code-health report into a transparent 0–100 trend score.

The score is deliberately a dashboard, not a gate.  The code-health ratchet
continues to own pass/fail decisions so one improving component cannot hide a
material regression in another.
"""

from __future__ import annotations

from typing import Any, Mapping


COMPONENT_WEIGHTS = {
    "cyclomatic": 0.45,
    "concentration": 0.25,
    "oversized_files": 0.20,
    "modularity": 0.10,
}


def _bounded(value: float, good: float, bad: float) -> float:
    """Return 100 at/below ``good`` and 0 at/above ``bad``."""
    if bad <= good:
        raise ValueError("bad threshold must be greater than good threshold")
    return max(0.0, min(100.0, 100.0 * (bad - value) / (bad - good)))


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def quality_score(report: Mapping[str, Any]) -> dict[str, Any]:
    """Calculate a stable score from fields present in report schema v1."""
    summary = report.get("summary") or {}
    production_lines = float(summary.get("production_lines") or 0)
    production_files = float(summary.get("production_files") or 0)
    functions = float(summary.get("functions_measured") or 0)
    complex_functions = float(summary.get("complex_functions") or 0)
    maximum_complexity = float(summary.get("max_complexity") or 0)
    hotspot_lines = sorted(
        (float(value) for value in (report.get("hotspots") or {}).values()),
        reverse=True,
    )

    complex_ratio = _ratio(complex_functions, functions)
    complexity_component = (
        0.75 * _bounded(complex_ratio, 0.02, 0.12)
        + 0.25 * _bounded(maximum_complexity, 25.0, 700.0)
    )

    largest_share = _ratio(hotspot_lines[0] if hotspot_lines else 0.0, production_lines)
    top_five_share = _ratio(sum(hotspot_lines[:5]), production_lines)
    concentration_component = (
        0.5 * _bounded(largest_share, 0.05, 0.25)
        + 0.5 * _bounded(top_five_share, 0.20, 0.55)
    )

    oversized_debt = _ratio(
        sum(max(0.0, lines - 1_000.0) for lines in hotspot_lines),
        production_lines,
    )
    giant_file_ratio = _ratio(
        sum(lines >= 5_000 for lines in hotspot_lines),
        production_files,
    )
    oversized_component = (
        0.75 * _bounded(oversized_debt, 0.05, 0.50)
        + 0.25 * _bounded(giant_file_ratio, 0.005, 0.05)
    )

    average_file_lines = _ratio(production_lines, production_files)
    hotspot_file_ratio = _ratio(len(hotspot_lines), production_files)
    modularity_component = (
        0.6 * _bounded(average_file_lines, 250.0, 800.0)
        + 0.4 * _bounded(hotspot_file_ratio, 0.02, 0.15)
    )

    components = {
        "cyclomatic": complexity_component,
        "concentration": concentration_component,
        "oversized_files": oversized_component,
        "modularity": modularity_component,
    }
    total = sum(components[name] * weight for name, weight in COMPONENT_WEIGHTS.items())
    return {
        "score": round(total, 1),
        "components": {name: round(value, 1) for name, value in components.items()},
        "signals": {
            "complex_function_ratio": round(complex_ratio, 6),
            "largest_file_share": round(largest_share, 6),
            "top_five_file_share": round(top_five_share, 6),
            "oversized_line_debt_ratio": round(oversized_debt, 6),
            "average_file_lines": round(average_file_lines, 1),
        },
    }


def score_delta(current: Mapping[str, Any], baseline: Mapping[str, Any]) -> float:
    return round(float(current["score"]) - float(baseline["score"]), 1)
