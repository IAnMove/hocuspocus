#!/usr/bin/env python3
"""Top-1 and top-3 for the template queries, lexical-only beside hybrid.

Lexical-only forces the embedder off. Hybrid uses ``template_semantic.active()``
(``HOCUSPOCUS_TEMPLATE_SEMANTIC_DIR``, or the installed weights folder). With
no weights the two columns match and ``semantic`` is false. CPU only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

from services import template_semantic  # noqa: E402
from services.world3d_template_catalog import search_report  # noqa: E402

QUERIES = (
    "dos personajes hablando en una cocina",
    "el robot camina",
    "primer plano llorando",
    "plano subjetivo",
    "cámara en mano nerviosa",
    "presentador hablando a cámara",
    "paisaje al amanecer",
    "music video dance",
    "bosque con niebla",
    "narrador en off",
    "drone shot over the sea",
    "interior de una nave espacial",
    "boda",
    "beso",
    "abrazo",
    "flashback",
    "sueño",
    "público aplaudiendo",
    "tres amigos hablando",
    "sentado en un sofá",
    "hablando por teléfono",
    "cowboy en el desierto",
    "persecución en coche",
    "miedo en un pasillo",
    "hospital",
    "iglesia",
    "dormitorio",
    "two people talking in a kitchen",
    "close-up crying",
    "handheld nervous camera",
    "wedding",
    "kiss",
)


def _line(report: dict) -> str:
    cards = report["templates"]
    if not cards:
        return f"(none) {report['unknown_words']}"
    top = cards[0]
    rest = ",".join(card["id"] for card in cards[1:3])
    return f"{top['id']} {top['score']}{(' > ' + rest) if rest else ''}"


def main() -> None:
    template_semantic.force_embedder(None)
    lexical = [(query, search_report(query, limit=3)) for query in QUERIES]
    template_semantic.clear_embedder_override()
    hybrid_on = template_semantic.active() is not None
    hybrid = [(query, search_report(query, limit=3)) for query in QUERIES]
    print(f"model {'on' if hybrid_on else 'off'}  weight {template_semantic.SEMANTIC_WEIGHT}")
    for (query, left), (_same, right) in zip(lexical, hybrid):
        flag = "S" if right.get("semantic") else "-"
        print(f"{flag} {query} | L {_line(left)} | H {_line(right)}")


if __name__ == "__main__":
    main()
