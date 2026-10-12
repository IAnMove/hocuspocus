"""Remote LLM calls survive a transient 429/5xx, say when a reply was cut, and treat DeepSeek as the remote API it is."""
import pytest

from services import llm_service
from services.llm_service import LLMTruncatedResponse, _post_with_backoff, _warn_if_truncated


class Response:
    def __init__(self, status=200, body=None, finish="stop", headers=None):
        self.status_code, self.headers, self.closed = status, headers or {}, False
        self._body = body if body is not None else {
            "choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}, "base_resp": {"status_code": 0},
        }

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise llm_service.requests.exceptions.HTTPError(response=self)

    def close(self):
        self.closed = True


def test_a_rate_limit_and_a_server_error_are_tried_again_with_backoff(monkeypatch):
    answers = [Response(429, headers={"Retry-After": "2"}), Response(503), Response(200)]
    calls, naps = [], []
    monkeypatch.setattr(llm_service.requests, "post", lambda url, **kw: calls.append(url) or answers.pop(0))
    monkeypatch.setattr(llm_service, "_sleep_unless_cancelled", lambda seconds, token, provider: naps.append(seconds))
    response = _post_with_backoff("https://api.example/v1/chat", provider="Example", json={})
    assert response.status_code == 200 and len(calls) == 3
    assert round(sum(naps), 2) == 4.0, "Retry-After 2 s, then the 2 s step"


def test_the_last_failure_is_returned_for_the_caller_to_report(monkeypatch):
    answers = [Response(500), Response(500), Response(500), Response(200)]
    monkeypatch.setattr(llm_service.requests, "post", lambda url, **kw: answers.pop(0))
    monkeypatch.setattr(llm_service, "_sleep_unless_cancelled", lambda *_args: None)
    response = _post_with_backoff("https://api.example/v1/chat", provider="Example", json={})
    assert response.status_code == 500 and len(answers) == 1, "three attempts, then the caller sees the error"
    with pytest.raises(llm_service.requests.exceptions.HTTPError):
        response.raise_for_status()


def test_a_dropped_connection_is_tried_again_and_a_client_error_is_not(monkeypatch):
    answers = [llm_service.requests.exceptions.ConnectionError("reset"), Response(200)]
    monkeypatch.setattr(llm_service.requests, "post", lambda url, **kw: (_ for _ in ()).throw(answers[0]) if isinstance(answers[0], Exception) and not answers.pop(0) else answers.pop(0))
    monkeypatch.setattr(llm_service, "_sleep_unless_cancelled", lambda *_args: None)
    assert _post_with_backoff("https://api.example/v1/chat", provider="Example", json={}).status_code == 200
    calls = []
    monkeypatch.setattr(llm_service.requests, "post", lambda url, **kw: calls.append(1) or Response(400))
    assert _post_with_backoff("https://api.example/v1/chat", provider="Example", json={}).status_code == 400 and calls == [1]


def test_a_reply_cut_at_max_tokens_is_an_error_when_json_was_asked_for():
    _warn_if_truncated("stop", "X", "fine", json_expected=True)
    _warn_if_truncated("length", "X", '{"half', json_expected=False)
    with pytest.raises(LLMTruncatedResponse) as raised:
        _warn_if_truncated("max_tokens", "Anthropic", '{"half', json_expected=True)
    assert raised.value.partial == '{"half' and "max_tokens" in str(raised.value)


def test_a_truncated_json_reply_from_a_remote_provider_raises_instead_of_returning_half(monkeypatch):
    monkeypatch.setattr(llm_service.requests, "post", lambda url, **kw: Response(200, finish="length"))
    with pytest.raises(LLMTruncatedResponse):
        llm_service.generate_openai_compatible(prompt="Return JSON", model_id="deepseek-v4-flash", base_url="https://api.deepseek.com",
                                               api_key="k", json_schema={"type": "object"})
    assert llm_service.generate_openai_compatible(prompt="Say hi", model_id="deepseek-v4-flash", base_url="https://api.deepseek.com",
                                                  api_key="k") == '{"ok": true}', "free text: a warning, not an error"


def test_deepseek_is_a_remote_provider_and_calls_its_api(monkeypatch):
    posted = []
    monkeypatch.setattr(llm_service.requests, "post", lambda url, **kw: posted.append((url, kw)) or Response(200))
    llm_service.load_model(model_id="deepseek-v4-flash", device="cpu", provider="deepseek", remote_url="", api_key="ds-key")
    try:
        status = llm_service.get_status()
        assert status["provider"] == "deepseek" and "deepseek.com" in (status.get("remote_url") or "")
        assert llm_service._api_headers().get("Authorization") == "Bearer ds-key"
        assert llm_service.generate("Hola", json_schema={"type": "object"}) == '{"ok": true}'
        assert posted and posted[0][0].startswith("https://api.deepseek.com"), "no local GGUF download, the remote API"
    finally:
        llm_service.unload_model()


def test_waiting_between_attempts_stops_when_the_request_is_cancelled(monkeypatch):
    class Token:
        def is_cancelled(self):
            return True

    monkeypatch.setattr(llm_service.time, "sleep", lambda _s: None)
    with pytest.raises(llm_service.LLMRequestCancelled):
        llm_service._sleep_unless_cancelled(5.0, Token(), "Example")
    naps = []
    monkeypatch.setattr(llm_service.time, "sleep", lambda seconds: naps.append(seconds))
    llm_service._sleep_unless_cancelled(0.0, None, "Example")
    assert naps == [], "nothing to wait for"
