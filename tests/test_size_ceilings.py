"""The files the architecture refactor splits may only shrink (scripts/size_ceilings.json)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.size_ceilings import CEILINGS, ROOT, SLACK, load, lower, raised_errors, size_errors

TRACKED = {"app/_launch_runtime.py", "app/core_runtime.py", "ui/src/stores/useStore.ts"}


def test_the_refactor_targets_have_ceilings() -> None:
    assert TRACKED <= set(load())


def test_files_stay_at_or_under_their_ceilings() -> None:
    errors = size_errors(ROOT, load())
    assert errors == [], "\n".join(errors)


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def test_ceilings_never_rise_against_the_base() -> None:
    """BASE_SHA, else the merge base with BASE_REF (default origin/development).

    CI's Python shards check out one commit, so the base is often missing
    there; the code-health ratchet step (check_code_health_pr_base.sh) runs the
    same comparison with the base it fetches.
    """
    base = os.environ.get("BASE_SHA") or ""
    if not base:
        merge_base = _git("merge-base", "HEAD", os.environ.get("BASE_REF") or "origin/development")
        base = (merge_base or "").strip()
    if not base:
        pytest.skip("no PR base in this checkout; check_code_health_pr_base.sh compares the ceilings with it")
    text = _git("show", f"{base}:scripts/size_ceilings.json")
    if text is None:
        return  # The base predates the ceilings.
    base_ceilings = {name: int(limit) for name, limit in json.loads(text)["ceilings"].items()}
    errors = raised_errors(base_ceilings, load())
    assert errors == [], "\n".join(errors)


def _tree(tmp_path: Path, lines: int, ceiling: int) -> Path:
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "big.py").write_text("x = 1\n" * lines, encoding="utf-8")
    (tmp_path / "ceilings.json").write_text(
        json.dumps({"version": 1, "ceilings": {"app/big.py": ceiling}}), encoding="utf-8"
    )
    return tmp_path


def test_rules_on_a_synthetic_tree(tmp_path) -> None:
    root = _tree(tmp_path, lines=500, ceiling=500)
    assert size_errors(root, {"app/big.py": 500}) == []
    over = size_errors(root, {"app/big.py": 499})
    assert len(over) == 1 and "may only shrink" in over[0]
    assert size_errors(root, {"app/big.py": 500 + SLACK}) == []
    stale = size_errors(root, {"app/big.py": 501 + SLACK})
    assert len(stale) == 1 and "--lower" in stale[0] and "500" in stale[0]
    assert "does not exist" in size_errors(root, {"app/gone.py": 10})[0]

    assert raised_errors({"app/big.py": 600}, {"app/big.py": 500}, root) == []
    assert "rose from 500 to 600" in raised_errors({"app/big.py": 500}, {"app/big.py": 600}, root)[0]
    assert "left scripts/size_ceilings.json" in raised_errors({"app/big.py": 500}, {}, root)[0]
    assert raised_errors({"app/deleted.py": 500}, {}, root) == []


def test_lower_writes_the_current_sizes(tmp_path) -> None:
    root = _tree(tmp_path, lines=300, ceiling=900)
    path = root / "ceilings.json"
    assert lower(root, path) == ["app/big.py: 900 -> 300"]
    assert json.loads(path.read_text(encoding="utf-8"))["ceilings"] == {"app/big.py": 300}
    assert lower(root, path) == []


def test_the_ceilings_file_explains_itself() -> None:
    payload = json.loads(CEILINGS.read_text(encoding="utf-8"))
    assert "merge train" in payload["note"]
