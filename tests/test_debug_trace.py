"""Tests for opt-in structured debug tracing and secret redaction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import debug_trace


@pytest.fixture(autouse=True)
def reset_debug_trace():
    yield
    debug_trace.configure(enabled=lambda: False, log_dir=lambda: "logs/debug")


def test_trace_disabled_by_default_does_not_write(tmp_path: Path):
    debug_trace.configure(enabled=lambda: False, log_dir=lambda: str(tmp_path))
    assert debug_trace.trace_event("test", "disabled", value="x") is None
    assert list(tmp_path.iterdir()) == []


def test_llm_trace_pairs_request_and_response_and_redacts_secrets(tmp_path: Path):
    debug_trace.configure(enabled=lambda: True, log_dir=lambda: str(tmp_path))

    @debug_trace.trace_llm_call("test_generate", context=lambda: {"provider": "test", "model_id": "model"})
    def generate(prompt: str, api_key: str = "") -> str:
        return f"answer for {prompt}"

    assert generate("full prompt", api_key="do-not-log") == "answer for full prompt"
    records = [json.loads(line) for line in Path(debug_trace.current_log_path()).read_text(encoding="utf-8").splitlines()]
    assert [record["phase"] for record in records] == ["request", "response"]
    assert records[0]["event_id"] == records[1]["event_id"]
    assert records[0]["request"]["prompt"] == "full prompt"
    assert records[0]["request"]["api_key"] == "<redacted>"
    assert records[0]["context"] == {"provider": "test", "model_id": "model"}
    assert records[1]["response"] == "answer for full prompt"
    assert records[1]["duration_ms"] >= 0


def test_sanitizer_omits_binary_and_base64_payloads():
    value = debug_trace.sanitize_for_trace({
        "image": b"abc",
        "preview": "data:image/png;base64,abcdef",
        "Authorization": "Bearer secret",
        "max_new_tokens": 4096,
    })
    assert value == {
        "image": "<binary:3 bytes>",
        "preview": "<base64-data:28 chars>",
        "Authorization": "<redacted>",
        "max_new_tokens": 4096,
    }
