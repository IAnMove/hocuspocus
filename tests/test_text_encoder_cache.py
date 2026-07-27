"""Tests for model-scoped, configuration-safe text embedding reuse."""

from __future__ import annotations

import unittest

import torch

from app.shared.utils.text_encoder_cache import TextEncoderCache


class TestTextEncoderCache(unittest.TestCase):
    def test_namespace_changes_hash_for_same_prompt(self):
        first = TextEncoderCache.make_key("same", {"model": "int8"})
        second = TextEncoderCache.make_key("same", {"model": "fp8"})
        self.assertNotEqual(first, second)

    def test_parallel_prefetch_only_encodes_missing_prompts(self):
        calls = []

        def encode(prompts):
            calls.append(list(prompts))
            return [torch.tensor([len(prompt)]) for prompt in prompts]

        cache = TextEncoderCache(namespace={"pipeline": "distilled"})
        first = cache.encode(encode, ["one", "two", "three"], parallel=True)
        second = cache.encode(encode, ["two", "three"], parallel=True)

        self.assertEqual(calls, [["one", "two", "three"]])
        self.assertEqual([int(value.item()) for value in first], [3, 3, 5])
        self.assertEqual([int(value.item()) for value in second], [3, 5])
        self.assertEqual(cache.last_report["hits"], 2)
        self.assertEqual(cache.last_report["misses"], 0)

    def test_explicit_configuration_keys_do_not_cross_reuse(self):
        calls = []

        def encode(prompts):
            calls.append(list(prompts))
            return [torch.tensor([len(calls)]) for _ in prompts]

        cache = TextEncoderCache()
        key_a = cache.make_key("prompt", {"connector": "a"})
        key_b = cache.make_key("prompt", {"connector": "b"})
        result_a = cache.encode(encode, "prompt", cache_keys=key_a)
        result_b = cache.encode(encode, "prompt", cache_keys=key_b)

        self.assertEqual(len(calls), 2)
        self.assertEqual(int(result_a[0].item()), 1)
        self.assertEqual(int(result_b[0].item()), 2)


if __name__ == "__main__":
    unittest.main()
