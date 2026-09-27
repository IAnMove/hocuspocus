"""Ollama models Maestro used are released from GPU memory at handoff."""

import requests

from app.services import llm_service


class _Response:
    def raise_for_status(self):
        return None


def test_release_unloads_each_used_model_once(monkeypatch):
    calls = []
    monkeypatch.setattr(
        llm_service.requests, "post",
        lambda url, json, timeout: calls.append((url, json)) or _Response(),
    )
    llm_service._ollama_models_in_use.clear()
    llm_service._remember_ollama_model("http://127.0.0.1:11434/v1", "gemma4:12b")
    llm_service._remember_ollama_model("http://127.0.0.1:11434", "gemma4:12b")

    assert llm_service.release_ollama_models() == ["gemma4:12b"]
    assert calls == [(
        "http://127.0.0.1:11434/api/generate",
        {"model": "gemma4:12b", "keep_alive": 0},
    )]
    assert llm_service.release_ollama_models() == []


def test_unreachable_ollama_does_not_raise(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(llm_service.requests, "post", refuse)
    llm_service._ollama_models_in_use.clear()
    llm_service._remember_ollama_model("http://127.0.0.1:11434", "gemma4:12b")

    assert llm_service.release_ollama_models() == []


class _Stream:
    def __init__(self, lines):
        self.lines = lines
        self.encoding = None

    def iter_lines(self, decode_unicode=True):
        return iter(self.lines)


def test_streamed_reply_is_assembled_like_a_single_response():
    import json
    lines = [
        json.dumps({"message": {"content": '{"a":'}, "done": False}),
        "",
        json.dumps({"message": {"content": " 1}", "thinking": ""}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True, "done_reason": "stop",
                    "prompt_eval_count": 12, "eval_count": 5}),
    ]
    data = llm_service._read_ollama_native_stream(_Stream(lines))
    assert data["choices"][0]["message"]["content"] == '{"a": 1}'
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"]["completion_tokens"] == 5


def test_stream_errors_and_early_end_are_reported():
    import json
    import pytest
    with pytest.raises(RuntimeError, match="Ollama error: out of memory"):
        llm_service._read_ollama_native_stream(_Stream([json.dumps({"error": "out of memory"})]))
    with pytest.raises(RuntimeError, match="before the answer finished"):
        llm_service._read_ollama_native_stream(_Stream([json.dumps({"message": {"content": "half"}, "done": False})]))
