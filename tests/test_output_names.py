"""One output-name rule: keep the existing file and say when the next name was used."""
from __future__ import annotations

import base64
import os
import tempfile
from unittest.mock import Mock, patch

from services.generation_memory import include_performance
from services.generation_output_name import generation_receipt_view
from services.minimax_image_service import generate_image
from services.output_names import annotate_generation_view, reserve


class _MiniMaxResponse:
    text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "data": {"image_base64": [base64.b64encode(b"jpeg-bytes").decode("ascii")]},
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }


def test_the_first_collision_uses_the_existing_two_suffix_and_keeps_the_file():
    with tempfile.TemporaryDirectory() as directory:
        original = os.path.join(directory, "still.jpg")
        with open(original, "wb") as handle:
            handle.write(b"keep-me")
        final, taken = reserve(directory, "still.jpg")
        assert final == "still(2).jpg"
        assert taken is True
        with open(original, "rb") as handle:
            assert handle.read() == b"keep-me"
        with open(os.path.join(directory, final), "wb") as handle:
            handle.write(b"second")
        again, taken_again = reserve(directory, "still.jpg")
        assert again == "still(3).jpg"
        assert taken_again is True
        free, was_taken = reserve(directory, "other.jpg")
        assert free == "other.jpg"
        assert was_taken is False


def test_a_png_request_saved_as_jpg_is_not_reported_as_taken():
    view = annotate_generation_view(
        {"path": "still.jpg", "status": "completed"},
        {"output_name_requested": "still.png", "output_files": ["still.jpg"]},
    )
    assert "outputName" not in view
    assert view.get("warnings") in (None, [])


def test_a_real_rename_reports_output_name_taken():
    view = annotate_generation_view(
        {"path": "still(2).jpg", "status": "completed"},
        {
            "output_name_requested": "still.jpg",
            "output_files": ["outputs/still(2).jpg"],
            "token_usage": {"prompt": 0, "completion": 0, "total": 0, "calls": 0},
        },
    )
    assert view["outputName"] == {"requested": "still.jpg", "final": "still(2).jpg", "taken": True}
    assert view["warnings"][0]["code"] == "output_name_taken"
    assert "still.jpg" in view["warnings"][0]["message"]
    assert "still(2).jpg" in view["warnings"][0]["message"]


def test_zero_token_counters_are_not_a_measurement_and_a_real_call_is():
    silent = annotate_generation_view(
        {"status": "completed", "task": {"token_usage": {"prompt": 0, "completion": 0, "total": 0, "calls": 0}}},
        {"token_usage": {"prompt": 0, "completion": 0, "total": 0, "calls": 0}},
    )
    assert silent["token_usage"] is None
    assert silent["token_usage_source"] == "not_measured"
    assert silent["task"]["token_usage"] is None
    measured = annotate_generation_view(
        {"status": "completed"},
        {"metadata": {"token_usage": {"prompt": 3, "completion": 1, "total": 4, "calls": 1}}},
    )
    assert measured["token_usage"] == {"prompt": 3, "completion": 1, "total": 4, "calls": 1}
    assert measured["token_usage_source"] == "llm"


def test_the_stored_receipt_stays_equal_when_the_public_view_is_annotated():
    receipt = {"status": "queued"}
    task = {
        "status": "running",
        "token_usage": {"prompt": 0, "completion": 0, "total": 0, "calls": 0},
        "metadata": {"output_name_requested": "still.jpg"},
        "result_refs": ["still(2).jpg"],
    }
    assert include_performance(receipt, task) == {"status": "queued"}
    view = generation_receipt_view(receipt, task, workspace="lab", workspace_dir="")
    assert view["receipt"] == {"status": "queued"}
    assert task["token_usage"]["calls"] == 0
    assert view["token_usage"] is None
    assert view["token_usage_source"] == "not_measured"
    assert view["outputName"]["taken"] is True
    assert view["task"] is not task


def test_minimax_keeps_an_existing_file_and_marks_the_next_name_taken():
    post = Mock(return_value=_MiniMaxResponse())
    with tempfile.TemporaryDirectory() as output_dir, patch("services.minimax_image_service.requests.post", post):
        original = os.path.join(output_dir, "still.jpg")
        with open(original, "wb") as handle:
            handle.write(b"original-bytes")
        result = generate_image(
            api_key="test-secret-not-for-production",
            prompt="a red square",
            aspect_ratio="1:1",
            output_dir=output_dir,
            output_name="still.png",
        )
        with open(original, "rb") as handle:
            assert handle.read() == b"original-bytes"
        assert result["requested_name"] == "still.jpg"
        assert result["name"] == "still(2).jpg"
        assert result["output_name_taken"] is True
        assert os.path.isfile(result["path"])
        assert "test-secret-not-for-production" not in open(
            os.path.splitext(result["path"])[0] + ".meta.json", encoding="utf-8",
        ).read()
