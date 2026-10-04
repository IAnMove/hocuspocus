"""templates.list matches words, not the exact phrase: case, accents, plurals, order and filler words are forgiven."""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "app"))

from services.template_search import fold, query_stems, same_word, score, stem  # noqa: E402

PS1 = {"title": "Escena estilo PS1", "tags": ["ps1", "backplate"],
       "description": "PS1-style scene: fondos prerenderizados de Qwen Image 2.1 y personajes 3D animados, cámara fija."}


def test_accents_case_and_plurals_are_forgiven():
    assert fold("Gráficos ÁÉÍ") == "graficos aei"
    assert stem("escenas") == stem("escena") == "escena"
    assert same_word(stem("scenes"), stem("scene"))
    assert not same_word("pre", "prerenderizado")        # too short to be a prefix of anything
    assert score("ESCENAS estilo", **PS1) > 0
    assert score("graficos prerenderizados", **PS1) > 0


def test_a_sentence_is_a_query_and_filler_words_are_ignored():
    assert query_stems("haz un videoclip con escenas de la PS1") == ["haz", "videoclip", "escena", "ps1"]
    assert score("la de con", **PS1) == 1                # only filler: no filter, same as an empty query
    assert score("", **PS1) == 1


def test_unrelated_words_score_zero():
    assert score("cocina italiana", **PS1) == 0


def test_title_beats_tags_beats_description():
    title_hit = score("escena", **PS1)
    tag_hit = score("backplate", **PS1)
    description_hit = score("camara", **PS1)
    assert title_hit > tag_hit > description_hit > 0


def test_more_matching_words_rank_higher():
    assert score("escena estilo ps1", **PS1) > score("escena", **PS1)
