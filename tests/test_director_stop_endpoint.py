"""Contract tests for the Director pipeline stop endpoint."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from routers import director as director_routes
from services import director_pipeline


def test_stop_response_reports_safe_boundary_cancellation_as_active():
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
        response = director_routes.director_pipeline_stop("pipeline-active")

    assert response == {
        "accepted": True,
        "status": "running",
        "phase": "cancelling",
        "cancel_requested": True,
        "cancelled": False,
        "persisted": True,
    }


def test_stop_response_only_reports_cancelled_after_terminal_acknowledgement():
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
        response = director_routes.director_pipeline_stop("pipeline-settled")

    assert response["accepted"] is True
    assert response["status"] == "cancelled"
    assert response["phase"] == "cancelled"
    assert response["cancel_requested"] is True
    assert response["cancelled"] is True


def test_stop_response_preserves_existing_terminal_state_and_missing_is_404():
    with patch.object(
        director_pipeline, "stop_pipeline", return_value=False,
    ), patch.object(
        director_pipeline,
        "get_pipeline",
        return_value={"status": "completed", "phase": "completed"},
    ):
        response = director_routes.director_pipeline_stop("pipeline-completed")

    assert response["accepted"] is False
    assert response["status"] == "completed"
    assert response["cancel_requested"] is False
    assert response["cancelled"] is False

    with patch.object(
        director_pipeline, "stop_pipeline", return_value=False,
    ), patch.object(
        director_pipeline, "get_pipeline", return_value=None,
    ), pytest.raises(HTTPException) as error:
        director_routes.director_pipeline_stop("pipeline-missing")

    assert error.value.status_code == 404
    assert error.value.detail == "Pipeline not found"
