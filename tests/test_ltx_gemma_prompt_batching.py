"""Tests for grouped Gemma prompt encoding in LTX-2."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from typing import NamedTuple

import torch


def _load_encode_text():
    source_path = (
        Path(__file__).parents[1]
        / "app/models/ltx2/ltx_core/text_encoders/gemma/encoders/base_encoder.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    selected = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "RawTextEmbeddings"
        )
        or (
            isinstance(node, ast.FunctionDef)
            and node.name == "encode_text"
        )
    ]
    namespace = {
        "torch": torch,
        "NamedTuple": NamedTuple,
        "GemmaTextEncoderModelBase": object,
    }
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(source_path), "exec"),
        namespace,
    )
    return namespace["encode_text"]


encode_text = _load_encode_text()


class _Tokenizer:
    def tokenize_with_weights(self, prompt: str):
        value = len(prompt)
        return {"gemma": [(value, 1), (0, 0), (0, 0)]}


class _Model:
    device = torch.device("cpu")

    def __init__(self):
        self.calls = []

    def __call__(self, *, input_ids, attention_mask, output_hidden_states):
        self.calls.append(
            {
                "input_ids": input_ids.clone(),
                "attention_mask": attention_mask.clone(),
                "output_hidden_states": output_hidden_states,
            }
        )
        hidden = input_ids.to(dtype=torch.float32).unsqueeze(-1)
        return SimpleNamespace(hidden_states=(hidden, hidden + 10))


class _TextEncoder:
    def __init__(self):
        self.tokenizer = _Tokenizer()
        self.model = _Model()
        self.single_calls = []

    def encode_raw(self, prompt):
        self.single_calls.append(prompt)
        raise AssertionError("Grouped prompts must use one batched model call")


class TestLTXGemmaPromptBatching(unittest.TestCase):
    def test_multiple_prompts_share_one_model_forward(self):
        encoder = _TextEncoder()

        results = encode_text(encoder, ["one", "longer", "third"])

        self.assertEqual(len(encoder.model.calls), 1)
        self.assertEqual(encoder.single_calls, [])
        self.assertEqual(encoder.model.calls[0]["input_ids"].shape, (3, 3))
        self.assertEqual(len(results), 3)
        self.assertTrue(
            torch.equal(results[1].hidden_states[0], torch.tensor([[[6.0], [0.0], [0.0]]]))
        )
        self.assertEqual(results[2].attention_mask.tolist(), [[1, 0, 0]])


if __name__ == "__main__":
    unittest.main()
