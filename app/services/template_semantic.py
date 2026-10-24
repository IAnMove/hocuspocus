"""Optional CPU embeddings for template search.

The model is ``intfloat/multilingual-e5-small`` (MIT). It is not a dependency of
the studio: the Installation catalog downloads the weights, and search stays
lexical until they are present. ``transformers`` (already in the studio env)
loads them. There is no ``sentence-transformers`` package.

Hybrid score, used only when the weights load::

    hybrid = lexical + round(SEMANTIC_WEIGHT * clamp(cosine, 0, 1))

``SEMANTIC_WEIGHT`` is 24. A perfect cosine adds 24 points. That breaks an equal
lexical score and can outrank a weak token (a line hit is 2, a short id hit is
about 4). It does not beat a title-phrase bonus of 80 or an exact-id bonus of
40. When the model is installed, two cards that used to tie can therefore get
different scores, and ``apply_query`` may instantiate the winner. With the model
absent, scores and order are the lexical ones.

When no card matches lexically, the same model may fill from the pool. A card
is kept when its cosine is at least ``MIN_SIMILARITY`` (0.75) and within
``FILL_MARGIN`` (0.04) of the best. If more than ``FILL_LIMIT`` (8) cards sit
in that band, the neighbourhood is flat and the fill is refused: on these
short cards e5-small's cosines bunch up, and a flat top is not a match.
Callers mark a real fill ``partial``, so nothing is applied automatically.
``unknown_words`` stays the lexical list.

Card text is the title, the one-line description and the trait, use and place
words. Queries use the e5 prefix ``query: `` and cards use ``passage: ``.
Vectors are mean-pooled and L2-normalised, on CPU. The passage cache is one
JSON file named by the SHA-256 of the model id plus every card id and passage.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

MODEL_ID = "intfloat/multilingual-e5-small"
LICENSE = "MIT"
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
SEMANTIC_WEIGHT = 24
MIN_SIMILARITY = 0.75
FILL_MARGIN = 0.04
FILL_LIMIT = 8
MAX_LENGTH = 256
ENV_DIR = "HOCUSPOCUS_TEMPLATE_SEMANTIC_DIR"
ENV_CACHE = "HOCUSPOCUS_TEMPLATE_SEMANTIC_CACHE"
# Transformers files only. The rest of the Hub repo (ONNX, OpenVINO, a second
# PyTorch pickle) is another copy of the same weights and is not downloaded.
MODEL_FILES = (
    "config.json",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
)

_UNSET = object()
_override: object = _UNSET
_failed = False
_embedder: E5Embedder | None = None


@dataclass(frozen=True)
class Row:
    """One candidate. ``key`` must be unique inside a single ``rank_rows`` call."""

    lexical: int
    passage: str
    order: int
    key: str


def hybrid_score(lexical: int, similarity: float) -> int:
    """Lexical points plus the bounded cosine term. The result is an int, as today."""
    if similarity < 0:
        similarity = 0.0
    elif similarity > 1:
        similarity = 1.0
    return int(lexical) + int(round(SEMANTIC_WEIGHT * similarity))


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine of two vectors. A zero or a mismatched vector is 0, not an error."""
    if len(left) != len(right) or not left:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def passage(title: str, description: str = "", tags: list | None = None) -> str:
    """Title, line and trait words, which is the text a card is embedded as."""
    extra = " ".join(str(tag) for tag in tags or [])
    return " ".join(part for part in (title, description, extra) if part)


def world3d_passage(card: dict) -> str:
    """The Video 3D card: both titles, both lines, and the trait, use and place words."""
    parts = [
        _text(card.get("titleEs")), _text(card.get("titleEn")),
        _text(card.get("lineEs")), _text(card.get("lineEn")),
        _kept(card.get("place")), _kept(card.get("shot")), _kept(card.get("dressing")),
        _kept(card.get("uses")), _kept(card.get("moves")), _kept(card.get("tags")),
        _subjects(card.get("subjects")),
    ]
    return " ".join(part for part in parts if part)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _kept(value: object) -> str:
    """Skip the two defaults that every ordinary card would otherwise repeat."""
    if isinstance(value, str):
        return "" if value in ("studio", "cinema") else value
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value if item)
    return ""


def _subjects(value: object) -> str:
    if value == 1:
        return "one subject"
    if value == 2:
        return "two subjects"
    return ""


def force_embedder(embedder: object) -> None:
    """Tests and the battery install a stub, or ``None`` to force the lexical path."""
    global _override
    _override = embedder


def clear_embedder_override() -> None:
    global _override
    _override = _UNSET


def active():
    """The embedder, or None when the weights are absent or a load already failed."""
    if _override is not _UNSET:
        return _override
    if _failed:
        return None
    return _real()


def _real() -> E5Embedder | None:
    global _embedder
    if _embedder is not None:
        return _embedder
    folder = weights_dir()
    if folder is None:
        return None
    _embedder = E5Embedder(folder)
    return _embedder


def _note_failure() -> None:
    global _failed, _embedder
    if _override is _UNSET:
        _failed = True
        _embedder = None


def weights_dir() -> Path | None:
    """The downloaded folder, from the env override or the catalog's remove path."""
    raw = os.environ.get(ENV_DIR)
    path = Path(raw) if raw else Path(__file__).resolve().parent / "template_semantic_model"
    if _weights_present(path):
        return path
    return None


def _weights_present(path: Path) -> bool:
    config = (path / "config.json").is_file()
    weights = (path / "model.safetensors").is_file() or (path / "pytorch_model.bin").is_file()
    return config and weights


def rank_rows(query: str, rows: list[Row], *, pool: list[Row] | None = None,
              cache_dir: Path | None = None) -> tuple[list[tuple[int, int]], bool]:
    """``[(order, score)]`` best first, and whether an embedding was used.

    With no embedder, or an empty query, the rows come back in the order given
    and with their lexical scores. A failed load does the same and remembers
    the failure, so the next search does not try again.
    """
    embedder = active()
    if embedder is None or not str(query or "").strip():
        return [(row.order, row.lexical) for row in rows], False
    try:
        return _scored(embedder, query, rows, pool or [], _cache_dir(cache_dir)), True
    except (OSError, RuntimeError, ImportError, ValueError):
        _note_failure()
        return [(row.order, row.lexical) for row in rows], False


def _scored(embedder, query: str, rows: list[Row], pool: list[Row], cache_dir: Path) -> list[tuple[int, int]]:
    if rows:
        return _rescore(embedder, query, rows, cache_dir)
    return _fill(embedder, query, pool, cache_dir)


def _rescore(embedder, query: str, rows: list[Row], cache_dir: Path) -> list[tuple[int, int]]:
    vectors = passage_vectors(embedder, rows, cache_dir)
    query_vector = embedder.embed([query], prefix=QUERY_PREFIX)[0]
    scored = [_hybrid_row(row, vector, query_vector) for row, vector in zip(rows, vectors)]
    scored.sort(key=_score_key)
    return [(order, score) for order, score, _similarity in scored]


def _hybrid_row(row: Row, vector: list[float], query_vector: list[float]) -> tuple[int, int, float]:
    similarity = cosine(query_vector, vector)
    return row.order, hybrid_score(row.lexical, similarity), similarity


def _score_key(item: tuple[int, int, float]) -> tuple:
    order, score, similarity = item
    return (-score, -similarity, order)


def _fill(embedder, query: str, pool: list[Row], cache_dir: Path) -> list[tuple[int, int]]:
    if not pool:
        return []
    vectors = passage_vectors(embedder, pool, cache_dir)
    query_vector = embedder.embed([query], prefix=QUERY_PREFIX)[0]
    scored = [(row.order, cosine(query_vector, vector)) for row, vector in zip(pool, vectors)]
    return _keep_close(scored)


def _keep_close(scored: list[tuple[int, float]]) -> list[tuple[int, int]]:
    if not scored:
        return []
    best = max(similarity for _order, similarity in scored)
    if best < MIN_SIMILARITY:
        return []
    floor = best - FILL_MARGIN
    kept = [item for item in scored if item[1] >= floor and item[1] >= MIN_SIMILARITY]
    # A flat top is the anisotropy of a short-card embedding, not a match.
    if len(kept) > FILL_LIMIT:
        return []
    kept.sort(key=lambda item: (-item[1], item[0]))
    return [(order, hybrid_score(0, similarity)) for order, similarity in kept]


def fingerprint(model_id: str, items: list[tuple[str, str]]) -> str:
    """SHA-256 of the model id and every card id plus passage, order-independent."""
    lines = [model_id]
    lines.extend(f"{key}\t{text}" for key, text in sorted(items))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def passage_vectors(embedder, rows: list[Row], cache_dir: Path) -> list[list[float]]:
    """Cached passage vectors. A changed card or model id is a different file."""
    items = [(row.key, row.passage) for row in rows]
    if not items:
        return []
    path = cache_dir / f"{fingerprint(embedder.model_id, items)}.json"
    cached = _read_vectors(path, embedder.model_id, [key for key, _text in items])
    if cached is not None:
        return cached
    vectors = embedder.embed([text for _key, text in items], prefix=PASSAGE_PREFIX)
    mapping = {key: vector for (key, _text), vector in zip(items, vectors)}
    _write_vectors(path, embedder.model_id, mapping)
    return list(vectors)


def _read_vectors(path: Path, model_id: str, keys: list[str]) -> list[list[float]] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    vectors = data.get("vectors") if isinstance(data, dict) and data.get("model") == model_id else None
    if not isinstance(vectors, dict) or any(key not in vectors for key in keys):
        return None
    return [vectors[key] for key in keys]


def _write_vectors(path: Path, model_id: str, mapping: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps({"model": model_id, "vectors": mapping}), encoding="utf-8")
    os.replace(temporary, path)


def _cache_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    raw = os.environ.get(ENV_CACHE)
    if raw:
        return Path(raw)
    folder = weights_dir()
    if folder is not None:
        return folder / "cache"
    return Path(tempfile.gettempdir()) / "hocuspocus-template-semantic-cache"


class E5Embedder:
    """Lazy CPU loader. Importing this module does not import torch."""

    model_id = MODEL_ID

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._model = None
        self._tokenizer = None

    def embed(self, texts: list[str], *, prefix: str) -> list[list[float]]:
        model, tokenizer = self._loaded()
        return _encode(model, tokenizer, [prefix + text for text in texts])

    def _loaded(self):
        if self._model is None:
            self._model, self._tokenizer = _load_e5(self._folder)
        return self._model, self._tokenizer


def _load_e5(folder: Path):
    import torch
    from transformers import AutoModel, AutoTokenizer

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    tokenizer = AutoTokenizer.from_pretrained(folder, local_files_only=True)
    model = AutoModel.from_pretrained(folder, local_files_only=True)
    model.eval()
    model.to("cpu")
    return model, tokenizer


def _encode(model, tokenizer, texts: list[str]) -> list[list[float]]:
    import torch

    batch = tokenizer(texts, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="pt")
    with torch.no_grad():
        hidden = model(**batch).last_hidden_state
    return mean_pool(hidden, batch["attention_mask"])


def mean_pool(hidden, mask) -> list[list[float]]:
    """Mean of the unmasked tokens, then L2 norm. Padding does not move the vector."""
    import torch

    weights = mask.unsqueeze(-1).to(dtype=hidden.dtype)
    summed = (hidden * weights).sum(dim=1)
    counts = weights.sum(dim=1).clamp(min=1e-9)
    pooled = torch.nn.functional.normalize(summed / counts, p=2, dim=1)
    return pooled.tolist()
