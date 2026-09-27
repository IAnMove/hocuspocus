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
