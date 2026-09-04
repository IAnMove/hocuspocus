"""Contract tests for the optional local MiniMax-Music3 backend.

These tests deliberately inspect definitions and prompt helpers only. They do
not download weights or allocate GPU memory; real generation belongs to the
opt-in local media smoke suite.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import types


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
HANDLER = APP / "models" / "TTS" / "minimax_music3_handler.py"
PIPELINE = APP / "models" / "TTS" / "minimax_music3" / "pipeline.py"
DEFAULT = APP / "defaults" / "minimax_music3.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _handler_namespace():
    tree = ast.parse(_read(HANDLER), filename=str(HANDLER))
    nodes = [
        node for node in tree.body
        if isinstance(node, (ast.Assign, ast.FunctionDef))
        or isinstance(node, ast.ClassDef) and node.name == "family_handler"
    ]
    namespace = {
        "os": os,
        "torch": types.SimpleNamespace(bfloat16="bf16"),
        "fl": types.SimpleNamespace(),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(HANDLER), "exec"), namespace)
    return namespace


def _pipeline_helpers():
    tree = ast.parse(_read(PIPELINE), filename=str(PIPELINE))
    wanted = {
        "clean_music_caption",
        "normalize_music3_lyrics",
        "build_music3_prompt",
        "music3_chunk_starts",
    }
    def private_assignment(node):
        if not isinstance(node, ast.Assign):
            return False
        names = []
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                names.extend(item.id for item in target.elts if isinstance(item, ast.Name))
        return any(name.startswith("_") for name in names)

    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
        or private_assignment(node)
    ]
    namespace = {"re": re}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(PIPELINE), "exec"), namespace)
    return namespace


def test_model_definition_is_local_and_license_aware():
    model = json.loads(_read(DEFAULT))["model"]
    assert model["architecture"] == "minimax_music3"
    assert model["source_repo"].endswith("MiniMax-Music3")
    assert model["license_name"] == "MiniMax-Music3 Community License"
    assert model["model_size_gb"] >= 28
    assert len(model["required_model_assets"]) >= 7


def test_handler_registers_model_and_validates_audio_contract():
    handler = _handler_namespace()["family_handler"]
    assert handler.query_supported_types() == ["minimax_music3"]
    model = handler.query_model_def("minimax_music3", {})
    assert model["audio_only"] is True
    assert model["music3_structured_caption"] is True
    assert model["duration_slider"] == {
        "label": "Song duration (seconds)", "min": 5, "max": 300,
        "increment": 1, "default": 120,
    }
    valid = {"alt_prompt": "### Global Metadata\nMetal", "duration_seconds": 30, "num_inference_steps": 30}
    assert handler.validate_generative_prompt("minimax_music3", model, valid, "[Verse]\nHola") is None
    assert handler.validate_generative_settings("minimax_music3", model, valid) is None
    assert "Music Caption" in handler.validate_generative_prompt("minimax_music3", model, {**valid, "alt_prompt": ""}, "lyrics")
    assert "between 5 and 300" in handler.validate_generative_settings("minimax_music3", model, {**valid, "duration_seconds": 301})


def test_prompt_helpers_keep_provider_structure_and_chunk_geometry():
    helpers = _pipeline_helpers()
    prompt = helpers["build_music3_prompt"](
        "### Global Metadata\nHeavy metal\n### Arrangement\nWide chorus",
        "[Verse - ronco] palabras descartadas\nLínea uno\n[Chorus]\nLínea dos",
    )
    assert prompt.startswith("<|im_start|><|caption_start|>")
    assert prompt.endswith("<|im_end|><|audio_start|>")
    assert "###" not in prompt
    lyrics = helpers["normalize_music3_lyrics"]("[Verse] palabras en etiqueta\nLínea real\n[CHORUS]\nEstribillo")
    assert lyrics.splitlines()[:2] == ["[start]", "[verse]"]
    assert "palabras en etiqueta" not in lyrics
    assert helpers["music3_chunk_starts"](200) == [0]
    assert helpers["music3_chunk_starts"](201) == [0, 100]


def test_runtime_registers_local_handler():
    assert '"models.TTS.minimax_music3_handler"' in _read(APP / "wgp.py")
    assert "MiniMaxMusic3Pipeline" in _read(PIPELINE)
