"""Tests for model-scoped, configuration-safe text embedding reuse."""

from __future__ import annotations

import unittest

import torch

from app.shared.utils.text_encoder_cache import TextEncoderCache


class TestTextEncoderCache(unittest.TestCase):
    def test_namespace_changes_hash_for_same_prompt(self):
        first = TextEncoderCache.make_key("same", {"model": "int8"})
        second = TextEncoderCache.make_key("same", {"model": "q6"})

        self.assertNotEqual(first, second)

    def test_parallel_cache_only_encodes_missing_prompts(self):
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

    def test_cached_tensors_are_detached_and_kept_on_cpu(self):
        source = torch.tensor([4.0], requires_grad=True)
        cache = TextEncoderCache(namespace={"model": "int8"})

        cache.encode(lambda _prompts: [source], ["scene"], parallel=True)
        cached = next(iter(cache._entries.values())).value

        self.assertEqual(cached.device.type, "cpu")
        self.assertFalse(cached.requires_grad)

    def test_parallel_encoding_uses_microbatches_of_at_most_four(self):
        calls = []

        def encode(prompts):
            calls.append(list(prompts))
            return [torch.tensor([index]) for index, _ in enumerate(prompts)]

        cache = TextEncoderCache(max_batch_size=4)
        cache.encode(
            encode,
            [f"panel-{index}" for index in range(9)],
            parallel=True,
        )

        self.assertEqual([len(batch) for batch in calls], [4, 4, 1])
        self.assertEqual(cache.last_report["batch_sizes"], [4, 4, 1])


if __name__ == "__main__":
    unittest.main()
