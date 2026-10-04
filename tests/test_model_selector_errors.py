"""Selector rejection names the allowed values and does not run a model."""

import json

import pytest

from services.model_selectors import (
    InvalidSelector,
    selector_catalog,
    validate_submitted_selectors,
)
from services.studio_image_conditioning import validate_image_selectors


_FIVE_OR_TEN = {
    "name": "Clip",
    "duration_slider": {
        "label": "Duration",
        "choices": [("5 seconds", 5), ("10 seconds", 10)],
    },
}


def test_rejected_duration_lists_the_allowed_values():
    with pytest.raises(InvalidSelector) as caught:
        validate_submitted_selectors({"model_type": "clip", "duration": 7}, _FIVE_OR_TEN)
    detail = caught.value.detail
    body = json.dumps(detail)
    assert detail["code"] == "invalid_selector"
    assert detail["field"] == "duration"
    assert detail["allowed"] == [5, 10]
    assert "5" in body and "10" in body


def test_allowed_duration_passes_without_enqueue():
    assert validate_submitted_selectors({"duration": 5, "prompt": "a street"}, _FIVE_OR_TEN) is None
    assert validate_submitted_selectors({"duration": 10}, _FIVE_OR_TEN) is None
    assert validate_submitted_selectors({"duration_seconds": 5.0}, _FIVE_OR_TEN) is None


def test_open_duration_slider_is_not_a_closed_selector():
    slider = {"duration_slider": {"min": 5, "max": 10, "increment": 1, "default": 5}}
    assert validate_submitted_selectors({"duration": 7}, slider) is None


def test_model_detail_includes_allowed_duration():
    catalog = selector_catalog(_FIVE_OR_TEN)
    assert catalog["duration"]["allowed"] == [5, 10]
    assert "duration" in catalog["duration"]["fields"]
    assert "duration_seconds" in catalog["duration"]["fields"]


def test_conditioning_error_names_the_selector_values():
    definition = {
        "image_ref_choices": {
            "choices": [("None", ""), ("References", "I"), ("Subject", "KI")],
        },
    }
    with pytest.raises(ValueError, match="selector must be enabled") as caught:
        validate_image_selectors({"image_refs": ["/api/v1/uploads/ref.png"]}, definition)
    message = str(caught.value)
    assert "video_prompt_type" in message
    assert "I" in message and "KI" in message
