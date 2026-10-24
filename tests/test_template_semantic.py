"""The optional semantic layer: scoring, ties, cache, and the lexical path when it is off."""
from __future__ import annotations

from pathlib import Path

import pytest

from services import install_catalog, template_semantic
from services import runtime_profiles as profiles
from services.install_status import Footprint, _component_row
from services.template_semantic import (
    FILL_LIMIT, MODEL_FILES, MODEL_ID, PASSAGE_PREFIX, QUERY_PREFIX, Row, cosine, hybrid_score, rank_rows,
)
from services.video2d_catalogs import query_catalog
from services.world3d_template_catalog import _cards, _fitting, _lexical_ranked, search_report

ROOT = Path(__file__).resolve().parents[1]


class Stub:
    def __init__(self, table: dict[str, list[float]], model_id: str = "stub") -> None:
        self.table = table
        self.model_id = model_id
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def embed(self, texts: list[str], *, prefix: str) -> list[list[float]]:
        self.calls.append((prefix, tuple(texts)))
        return [self.table[text] for text in texts]


@pytest.fixture(autouse=True)
def _lexical_default(tmp_path, monkeypatch):
    template_semantic.clear_embedder_override()
    monkeypatch.delenv("HOCUSPOCUS_TEMPLATE_SEMANTIC_DIR", raising=False)
    monkeypatch.setenv("HOCUSPOCUS_TEMPLATE_SEMANTIC_CACHE", str(tmp_path / "cache"))
    yield
    template_semantic.clear_embedder_override()


def test_hybrid_weight_breaks_a_tie_and_loses_to_a_title():
    # 24 points at cosine 1. A title-phrase bonus of 80 stays ahead of a perfect weak card.
    assert hybrid_score(80, 0.4) == 90
    assert hybrid_score(8, 0.99) == 32
    assert hybrid_score(80, 0.4) > hybrid_score(8, 0.99)
    assert hybrid_score(2, 0.95) > hybrid_score(8, 0.2)
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0


def test_equal_lexical_scores_follow_the_cosine(tmp_path):
    stub = Stub({"ask": [1.0, 0.0], "near": [1.0, 0.0], "far": [0.0, 1.0]})
    template_semantic.force_embedder(stub)
    rows = [Row(10, "far", 0, "far"), Row(10, "near", 1, "near")]
    ranked, used = rank_rows("ask", rows, cache_dir=tmp_path)
    assert used is True
    assert ranked == [(1, hybrid_score(10, 1.0)), (0, hybrid_score(10, 0.0))]


def test_unknown_query_fills_from_the_pool_and_drops_a_far_card(tmp_path):
    stub = Stub({"ask": [1.0, 0.0], "close": [1.0, 0.0], "far": [0.0, 1.0]})
    template_semantic.force_embedder(stub)
    pool = [Row(0, "far", 0, "far"), Row(0, "close", 1, "close")]
    ranked, used = rank_rows("ask", [], pool=pool, cache_dir=tmp_path)
    assert used is True
    assert ranked == [(1, hybrid_score(0, 1.0))]
    assert len(ranked) <= FILL_LIMIT


def test_passage_cache_misses_when_the_catalogue_changes(tmp_path):
    stub = Stub({"ask": [1.0, 0.0], "alpha": [1.0, 0.0], "beta": [0.0, 1.0], "gamma": [0.0, 1.0]})
    template_semantic.force_embedder(stub)
    first = [Row(10, "alpha", 0, "a"), Row(10, "beta", 1, "b")]
    rank_rows("ask", first, cache_dir=tmp_path)
    rank_rows("ask", first, cache_dir=tmp_path)
    passages = [call for call in stub.calls if call[0] == PASSAGE_PREFIX]
    queries = [call for call in stub.calls if call[0] == QUERY_PREFIX]
    assert len(passages) == 1 and len(queries) == 2
    rank_rows("ask", [Row(10, "alpha", 0, "a"), Row(10, "gamma", 1, "b")], cache_dir=tmp_path)
    passages = [call for call in stub.calls if call[0] == PASSAGE_PREFIX]
    assert len(passages) == 2


def test_absent_model_matches_the_lexical_ranker_and_does_not_embed():
    template_semantic.force_embedder(None)
    query = "dos personajes hablando en una cocina"
    report = search_report(query, limit=3)
    library = _cards(None, None)
    lexical, unknown = _lexical_ranked(query, library, _fitting(library, None, None, {}), None)
    assert report["semantic"] is False
    assert report["unknown_words"] == unknown
    assert [(card["id"], card["score"], card["match"]) for card in report["templates"]] == [
        (card["id"], score, match) for score, match, _index, card in lexical[:3]]
    empty = search_report("xyzzy xyzzy plugh")
    assert empty == {"templates": [], "unknown_words": ["xyzzy", "plugh"], "partial": False, "semantic": False}
    summary = query_catalog({})["result"]
    assert set(summary) == {"kinds"}
    plain = query_catalog({"kind": "motion"})["result"]
    assert "score" not in plain["entries"][0] and "unknown_words" not in plain and "semantic" not in plain
    nothing = query_catalog({"q": "zzyzx quux"})["result"]
    assert nothing["matches"] == [] and nothing["semantic"] is False


def test_a_flat_neighbourhood_does_not_invent_cards(tmp_path):
    """e5-small bunches short cards together. A flat top must not become a result."""
    table = {"ask": [1.0, 0.0]}
    pool = []
    for index in range(FILL_LIMIT + 1):
        table[f"card-{index}"] = [1.0, 0.0]
        pool.append(Row(0, f"card-{index}", index, f"card-{index}"))
    template_semantic.force_embedder(Stub(table, model_id="flat-top"))
    ranked, used = rank_rows("ask", [], pool=pool, cache_dir=tmp_path)
    assert used is True and ranked == []

    class Flat:
        model_id = "flat-catalog"

        def embed(self, texts, *, prefix):
            return [[1.0, 0.0] for _text in texts]

    template_semantic.force_embedder(Flat())
    report = search_report("xyzzy xyzzy plugh", limit=3)
    assert report["semantic"] is True
    assert report["templates"] == []
    assert report["unknown_words"] == ["xyzzy", "plugh"]


def test_mean_pool_ignores_padding_and_normalises():
    torch = pytest.importorskip("torch")
    hidden = torch.tensor([[[1.0, 0.0], [3.0, 0.0], [100.0, 0.0]]])
    mask = torch.tensor([[1, 1, 0]])
    assert template_semantic.mean_pool(hidden, mask)[0] == pytest.approx([1.0, 0.0])


def test_the_component_is_mit_cpu_and_weights_only():
    component = install_catalog.get("template_semantic")
    assert component.license == "MIT"
    assert component.ready_file == "app/services/template_semantic_model/READY"
    assert component.estimated_bytes == int(0.5 * 1024 ** 3)
    engine = profiles.catalog()["engines"]["template_semantic"]
    assert "cuda" not in engine and engine["defaultInstall"] is False
    assert engine["platforms"] == ["darwin", "linux", "win32"]
    script = (ROOT / "template_semantic_install.js").read_text(encoding="utf-8")
    assert "installEngines(" not in script and "script.return" in script
    assert "pytorch_model.bin" not in MODEL_FILES and "onnx" not in " ".join(MODEL_FILES)
    assert MODEL_ID == "intfloat/multilingual-e5-small"
    assert QUERY_PREFIX == "query: " and PASSAGE_PREFIX == "passage: "


def test_a_ready_file_counts_as_installed_without_a_venv_receipt(tmp_path):
    component = install_catalog.get("template_semantic")
    engine = {"supported": True, "installed": False}

    class Meter:
        def get(self, path):
            return Footprint(1, 1)

    missing = _component_row(component, engine, tmp_path, Meter(), None)
    assert missing["state"] == "not_installed"
    ready = tmp_path / component.ready_file
    ready.parent.mkdir(parents=True)
    ready.write_text("license=MIT\n", encoding="utf-8")
    present = _component_row(component, engine, tmp_path, Meter(), None)
    assert present["state"] == "installed"


def test_the_battery_covers_the_known_failures():
    text = (ROOT / "scripts" / "dev" / "template_query_battery.py").read_text(encoding="utf-8")
    for phrase in (
        "dos personajes hablando en una cocina", "el robot camina", "primer plano llorando",
        "plano subjetivo", "cámara en mano nerviosa", "presentador hablando a cámara",
        "paisaje al amanecer", "music video dance", "bosque con niebla", "narrador en off",
        "drone shot over the sea", "interior de una nave espacial", "boda", "beso", "abrazo",
        "flashback", "sueño", "público aplaudiendo", "tres amigos hablando", "sentado en un sofá",
        "hablando por teléfono", "cowboy en el desierto", "persecución en coche",
        "miedo en un pasillo", "hospital", "iglesia", "dormitorio",
    ):
        assert phrase in text, phrase
