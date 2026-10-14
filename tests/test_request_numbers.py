"""The one place a Studio edit route reads a number from its JSON body (validation edit-01/02/03, N5)."""
import pytest
from fastapi import HTTPException

from services.request_numbers import NOT_A_NUMBER_STATUS, number_field, optional_number


def test_a_missing_field_takes_the_default_and_text_that_holds_a_number_still_parses():
    assert number_field({}, "overlap_sec", 3) == 3.0
    assert isinstance(number_field({}, "overlap_sec", 3), float)
    assert number_field({"guidance_scale": "4"}, "guidance_scale", 1.0) == 4.0
    assert number_field({"num_inference_steps": "7"}, "num_inference_steps", 8, int) == 7
    assert number_field({"num_inference_steps": 7.9}, "num_inference_steps", 8, int) == 7
    assert number_field({"start_time": 0}, "start_time", 5) == 0.0  # a stated zero is not "missing"


@pytest.mark.parametrize("value", ["abc", "", None, [], {}, [1], "nan", "inf", "-inf", float("inf"), float("nan")])
def test_a_value_that_is_not_a_finite_number_answers_400_naming_the_field(value):
    with pytest.raises(HTTPException) as refused:
        number_field({"overlap_sec": value}, "overlap_sec", 3)
    assert refused.value.status_code == NOT_A_NUMBER_STATUS == 400
    assert refused.value.detail == "overlap_sec must be a number"


@pytest.mark.parametrize("value", ["x", "1.5", None, float("inf"), float("nan"), {}])
def test_a_whole_number_field_names_what_it_wants(value):
    with pytest.raises(HTTPException) as refused:
        number_field({"anchor_frames": value}, "anchor_frames", 0, int)
    assert (refused.value.status_code, refused.value.detail) == (400, "anchor_frames must be a whole number")


def test_a_default_is_read_through_the_same_check():
    # A junk value inherited from base_params is refused under the field's name, as the route reads it.
    with pytest.raises(HTTPException, match="guidance_scale must be a number"):
        number_field({}, "guidance_scale", "high")


def test_an_optional_number_is_none_when_absent_or_null_and_otherwise_a_number():
    assert optional_number({}, "start_time") is None
    assert optional_number({"start_time": None}, "start_time") is None
    assert optional_number({"start_time": 0}, "start_time") == 0.0
    assert optional_number({"start_time": "1.5"}, "start_time") == 1.5
    with pytest.raises(HTTPException, match="start_time must be a number"):
        optional_number({"start_time": "soon"}, "start_time")
