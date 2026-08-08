"""Regression tests for scoped comic-writing OpenAI-compatible requests."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from services import llm_service  # noqa: E402


class _Response:
    def __init__(self, content: str, status_code: int = 200, *, reasoning_tokens: int = 0):
        self.status_code = status_code
        self.text = ""
        self._content = content
        self._reasoning_tokens = reasoning_tokens

    def json(self):
        return {
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": self._content},
            }],
            "usage": {
                "completion_tokens": self._reasoning_tokens,
                "completion_tokens_details": {
                    "reasoning_tokens": self._reasoning_tokens,
                },
            },
            "base_resp": {"status_code": 0, "status_msg": ""},
        }

    def raise_for_status(self):
        if self.status_code >= 400:
            raise llm_service.requests.exceptions.HTTPError(response=self)


class TestComicCompatibleLlm(unittest.TestCase):
    def test_multimodal_request_preserves_image_order_before_text(self):
        with patch(
            "services.llm_service._image_to_data_url",
            side_effect=["data:image/jpeg;base64,one", "data:image/jpeg;base64,two"],
        ), patch(
            "services.llm_service.requests.post",
            return_value=_Response('{"assets": []}'),
        ) as post:
            llm_service.generate_openai_compatible(
                prompt="Classify these images",
                model_id="MiniMax-M3",
                base_url="https://api.minimax.io/v1",
                api_key="secret",
                image_paths=["first.jpg", "second.jpg"],
            )
        content = post.call_args.kwargs["json"]["messages"][-1]["content"]
        self.assertEqual([part["type"] for part in content], ["image_url", "image_url", "text"])
        self.assertEqual(content[-1]["text"], "Classify these images")

    def test_deepseek_empty_json_is_retried_once(self):
        with patch(
            "services.llm_service.requests.post",
            side_effect=[_Response(""), _Response('{"ok": true}')],
        ) as post:
            result = llm_service.generate_openai_compatible(
                prompt="Return JSON",
                model_id="deepseek-v4-flash",
                base_url="https://api.deepseek.com",
                api_key="deepseek-secret",
                json_schema={"type": "object"},
            )
        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(post.call_count, 2)

    def test_custom_local_server_can_omit_authentication(self):
        with patch(
            "services.llm_service.requests.post",
            return_value=_Response('{"ok": true}'),
        ) as post:
            llm_service.generate_openai_compatible(
                prompt="Return JSON",
                model_id="local-model",
                base_url="http://127.0.0.1:1234",
                api_key="",
                json_schema={"type": "object"},
            )
        self.assertNotIn("Authorization", post.call_args.kwargs["headers"])

    def test_minimax_uses_its_openai_compatible_endpoint(self):
        with patch(
            "services.llm_service.requests.post",
            return_value=_Response('<think>Plan the structure.</think>{"ok": true}'),
        ) as post:
            result = llm_service.generate_openai_compatible(
                prompt="Return a comic plan as JSON",
                model_id="MiniMax-M3",
                base_url="https://api.minimax.io/v1",
                api_key="minimax-shared-secret",
                json_schema={"type": "object"},
            )
        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(
            post.call_args.args[0],
            "https://api.minimax.io/v1/chat/completions",
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer minimax-shared-secret",
        )
        self.assertEqual(post.call_args.kwargs["json"]["model"], "MiniMax-M3")
        self.assertNotIn("response_format", post.call_args.kwargs["json"])
        self.assertEqual(
            post.call_args.kwargs["json"]["thinking"],
            {"type": "disabled"},
        )
        self.assertGreaterEqual(
            post.call_args.kwargs["json"]["max_completion_tokens"],
            4096,
        )
        self.assertNotIn("max_tokens", post.call_args.kwargs["json"])

    def test_minimax_empty_reasoning_response_retries_with_more_headroom(self):
        with patch(
            "services.llm_service.requests.post",
            side_effect=[
                _Response("", reasoning_tokens=4096),
                _Response('{"ok": true}'),
            ],
        ) as post:
            result = llm_service.generate_openai_compatible(
                prompt="Return a comic plan as JSON",
                model_id="MiniMax-M2.7",
                base_url="https://api.minimax.io/v1",
                api_key="minimax-shared-secret",
                max_new_tokens=1400,
                json_schema={"type": "object"},
            )
        self.assertEqual(result, '{"ok": true}')
        self.assertEqual(post.call_count, 2)
        first = post.call_args_list[0].kwargs["json"]
        second = post.call_args_list[1].kwargs["json"]
        self.assertEqual(first["max_completion_tokens"], 4096)
        self.assertEqual(second["max_completion_tokens"], 8192)
        self.assertNotIn("thinking", first)

    def test_minimax_plain_text_request_retries_after_empty_reasoning(self):
        with patch(
            "services.llm_service.requests.post",
            side_effect=[_Response("", reasoning_tokens=4096), _Response("[Verse]\nTranslated line")],
        ) as post:
            result = llm_service.generate_openai_compatible(
                prompt="Translate lyrics",
                model_id="MiniMax-M2.7",
                base_url="https://api.minimax.io/v1",
                api_key="minimax-shared-secret",
                max_new_tokens=600,
            )
        self.assertEqual(result, "[Verse]\nTranslated line")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["max_completion_tokens"], 4096)
        self.assertEqual(post.call_args_list[1].kwargs["json"]["max_completion_tokens"], 8192)

    def test_unsupported_structured_output_retries_without_envelope(self):
        with patch(
            "services.llm_service.requests.post",
            side_effect=[_Response("", 400), _Response('{"ok": true}')],
        ) as post:
            result = llm_service.generate_openai_compatible(
                prompt="Return JSON",
                model_id="custom-model",
                base_url="https://compatible.example/v1",
                api_key="custom-secret",
                json_schema={"type": "object"},
            )
        self.assertEqual(result, '{"ok": true}')
        self.assertIn("response_format", post.call_args_list[0].kwargs["json"])
        self.assertNotIn("response_format", post.call_args_list[1].kwargs["json"])


if __name__ == "__main__":
    unittest.main()
