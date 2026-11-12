"""Top-level generation priority and output_name match the published MCP schema."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from routers.image_generation_commands import _generation_arguments, image_command_catalog
from routers.wangp_mcp import tool_definitions
from services.generation_output_name import prepare_command_output_name
from services.image_generation_spec import freeze_image_generation_spec
from services.job_lifecycle import take_submission_priority


def _base_input() -> dict:
    return {
        "workspace": "workspace-a",
        "model_type": "pi_flux2",
        "prompt": "a red square",
        "resolution": "512x512",
        "num_inference_steps": 1,
        "seed": -1,
        "guidance_scale": 1.0,
    }


def _envelope(**extra) -> dict:
    command = {"version": 1, "intent_id": "intent-1", "input": _base_input()}
    command.update(extra)
    return command


def _detail(error: HTTPException) -> dict:
    assert isinstance(error.detail, dict)
    return error.detail


def test_top_level_priority_and_output_name_move_into_the_command_input():
    folded = _generation_arguments(_envelope(priority=7, output_name="still.png"))
    assert "priority" not in folded
    assert "output_name" not in folded
    assert folded["input"]["params"]["priority"] == 7
    assert folded["input"]["output_name"] == "still.png"


def test_equal_copies_are_not_a_conflict_and_leave_a_freezable_v1_command():
    folded = _generation_arguments(_envelope(
        priority=7,
        output_name="still.png",
        input={**_base_input(), "output_name": "still.png", "params": {"priority": 7}},
    ))
    submitted = {**folded, "operation": "generation.image"}
    prepared, name = prepare_command_output_name(submitted)
    assert name == "still.png"
    assert take_submission_priority(prepared) == 7
    assert "params" not in prepared["input"]
    assert "output_name" not in prepared["input"]
    freeze_image_generation_spec(prepared)


def test_a_bool_priority_is_rejected():
    with pytest.raises(HTTPException) as caught:
        _generation_arguments(_envelope(priority=True))
    assert caught.value.status_code == 422
    assert _detail(caught.value)["code"] == "invalid_command"


def test_different_priority_copies_are_a_conflict_with_both_values():
    with pytest.raises(HTTPException) as caught:
        _generation_arguments(_envelope(priority=1, input={**_base_input(), "params": {"priority": 9}}))
    error = _detail(caught.value)
    assert caught.value.status_code == 422
    assert error["code"] == "conflicting_field"
    assert error["field"] == "priority"
    assert error["values"] == [1, 9]
    assert error["retryable"] is False


def test_different_output_names_are_a_conflict():
    with pytest.raises(HTTPException) as caught:
        _generation_arguments(_envelope(
            output_name="one.png",
            input={**_base_input(), "output_name": "two.png"},
        ))
    error = _detail(caught.value)
    assert error["code"] == "conflicting_field"
    assert error["field"] == "output_name"
    assert error["values"] == ["one.png", "two.png"]


def test_an_unknown_top_level_field_is_still_rejected():
    with pytest.raises(HTTPException) as caught:
        _generation_arguments(_envelope(operation="generation.image"))
    assert _detail(caught.value)["code"] == "invalid_command"


def test_published_generation_schema_matches_the_validator():
    operations = image_command_catalog()
    source = operations[0]["inputSchema"]
    tools = {tool["name"]: tool for tool in tool_definitions({item["name"] for item in operations}, operations)}
    published = tools["generation.image"]["inputSchema"]["properties"]
    receipt = tools["generation.receipt"]["inputSchema"]["properties"]
    assert published["priority"]["type"] == "integer"
    assert published["output_name"]["type"] == "string"
    assert "priority" not in receipt
    assert "output_name" not in receipt
    assert "priority" not in source["properties"]
    assert "output_name" not in source["properties"]

    samples = {
        "version": 1,
        "intent_id": "intent-schema",
        "input": {"workspace": "lab"},
        "priority": 2,
        "output_name": "frame.png",
    }
    assert set(published) <= set(samples)
    for name in published:
        arguments = {"version": 1, "intent_id": "intent-schema", "input": {"workspace": "lab"}}
        arguments[name] = samples[name]
        folded = _generation_arguments(arguments)
        assert folded["version"] == 1
        assert isinstance(folded["input"], dict)

    combined = {"version": 1, "intent_id": "intent-schema", "input": {"workspace": "lab"}}
    for name in set(published) - {"version", "intent_id", "input"}:
        combined[name] = samples[name]
    folded = _generation_arguments(combined)
    assert set(folded) == {"version", "intent_id", "input"}
    assert folded["input"]["params"]["priority"] == samples["priority"]
    assert folded["input"]["output_name"] == samples["output_name"]
