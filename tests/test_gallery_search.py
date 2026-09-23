"""Gallery search finds outputs by prompt, model and mode, as typed."""

from __future__ import annotations

import json

import pytest

from services import search_index
from tests.test_output_completion_time import list_test_outputs


@pytest.fixture(autouse=True)
def fresh_index(monkeypatch):
    monkeypatch.setattr(search_index, "_search_index", search_index.SearchIndex())


@pytest.fixture
def library(tmp_path):
    def add(name, prompt, model="", mode="image"):
        (tmp_path / name).write_bytes(b"media")
        stem = name.rsplit(".", 1)[0]
        (tmp_path / f"{stem}.meta.json").write_text(
            json.dumps({"generation_mode": mode, "params": {"prompt": prompt, "model_type": model}}), encoding="utf-8")
    add("dragon.png", "Un dragón rojo sobre el mar", "qwen_image_21")
    add("castle.mp4", "A castle at dawn, drone shot", "ltx2_22B_distilled_1_1", "video")
    add("forest.png", "Bosque en niebla", "flux2_klein")
    return tmp_path


def names(tmp_path, query):
    return sorted(item["name"] for item in list_test_outputs(tmp_path, search=query))


def test_prompts_are_searchable_not_just_file_names(library):
    assert names(library, "castle") == ["castle.mp4"]
    assert names(library, "dawn") == ["castle.mp4"]
    assert names(library, "bosque niebla") == ["forest.png"]


def test_words_match_while_still_being_typed(library):
    assert names(library, "dr") == ["castle.mp4", "dragon.png"]  # dragón, drone
    assert names(library, "drag") == ["dragon.png"]
    assert names(library, "cas daw") == ["castle.mp4"]


def test_accents_do_not_matter_either_way(library):
    assert names(library, "dragon") == ["dragon.png"]
    assert names(library, "DRAGÓN") == ["dragon.png"]
    assert names(library, "niébla") == ["forest.png"]


def test_models_and_modes_are_searchable(library):
    assert names(library, "qwen") == ["dragon.png"]
    assert names(library, "ltx") == ["castle.mp4"]
    assert names(library, "video") == ["castle.mp4"]
    assert names(library, "qwen video") == []
