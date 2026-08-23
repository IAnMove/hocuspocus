"""Contract tests for the Director pipeline stop endpoint."""

from __future__ import annotations

import ast
import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from services import director_pipeline


_ROOT = Path(__file__).resolve().parents[1]


class _HTTPException(Exception):
    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _load_stop_endpoint():
    source_path = _ROOT / "app" / "_launch_runtime.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    node = next(
        copy.deepcopy(candidate)
        for candidate in tree.body
        if isinstance(candidate, ast.FunctionDef)
        and candidate.name == "director_pipeline_stop"
    )
    node.decorator_list = []
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    namespace = {"HTTPException": _HTTPException}
    exec(compile(module, source_path, "exec"), namespace)
    return namespace["director_pipeline_stop"]


def test_stop_response_reports_safe_boundary_cancellation_as_active():
    endpoint = _load_stop_endpoint()
    current = {
        "status": "running",
        "phase": "cancelling",
        "_cancel_requested": True,
        "_state_persisted": True,
    }

    with patch.object(
        director_pipeline, "stop_pipeline", return_value=True,
    ), patch.object(
        director_pipeline, "get_pipeline", return_value=current,
    ):
        response = endpoint("pipeline-active")

    assert response == {
        "accepted": True,
        "status": "running",
        "phase": "cancelling",
        "cancel_requested": True,
        "cancelled": False,
        "persisted": True,
    }


def test_stop_response_only_reports_cancelled_after_terminal_acknowledgement():
    endpoint = _load_stop_endpoint()
    current = {
        "status": "cancelled",
        "phase": "cancelled",
        "_cancel_requested": True,
        "_state_persisted": True,
    }

    with patch.object(
        director_pipeline, "stop_pipeline", return_value=True,
    ), patch.object(
        director_pipeline, "get_pipeline", return_value=current,
    ):
        response = endpoint("pipeline-settled")

    assert response["accepted"] is True
    assert response["status"] == "cancelled"
    assert response["phase"] == "cancelled"
    assert response["cancel_requested"] is True
    assert response["cancelled"] is True


def test_stop_response_preserves_existing_terminal_state_and_missing_is_404():
    endpoint = _load_stop_endpoint()

    with patch.object(
        director_pipeline, "stop_pipeline", return_value=False,
    ), patch.object(
        director_pipeline,
        "get_pipeline",
        return_value={"status": "completed", "phase": "completed"},
    ):
        response = endpoint("pipeline-completed")

    assert response["accepted"] is False
    assert response["status"] == "completed"
    assert response["cancel_requested"] is False
    assert response["cancelled"] is False

    with patch.object(
        director_pipeline, "stop_pipeline", return_value=False,
    ), patch.object(
        director_pipeline, "get_pipeline", return_value=None,
    ), pytest.raises(_HTTPException) as error:
        endpoint("pipeline-missing")

    assert error.value.status_code == 404
    assert error.value.detail == "Pipeline not found"
