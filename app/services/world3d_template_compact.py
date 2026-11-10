"""The short card: what a model needs to choose a Video 3D shot, in a few hundred bytes.

A full card is about 1.2 KB of copy, roles, dependencies and URLs that a planner never reads. ``compact: true`` on
``world3d.templates.suggest`` and ``.catalog``, and every entry of ``world3d.templates.plan``, carry only the id, one
title, the shot size, the camera moves, the format and one line that says why: ``id title shot moves format why``.
"""
from __future__ import annotations

COMPACT_KEYS = ("id", "title", "shot", "moves", "format", "why")
MAX_WHY = 140
_COUNTS = {0: "no subject", 1: "one subject", 2: "two subjects"}


def _motion(card: dict, shown: list[str]) -> str:
    if shown:
        return "moves: " + ", ".join(shown)
    if [part for part in card.get("moving") or [] if part != "camera"]:
        return "moves on its own"
    return "still" if card.get("still") else "fixed camera"


def short_why(card: dict, *, shot: str | None = None, moves: list[str] | None = None) -> str:
    """«two subjects, wide, moves: push, uses: dialogue, talk; place: cocina», from the card's own traits. ``shot`` and
    ``moves`` replace the card's when a stage camera is chosen."""
    count = int(card.get("subjects") or 0)
    shown = (card.get("moves") or []) if moves is None else moves
    parts = [_COUNTS.get(count, f"{count} subjects"), shot or card.get("shot") or "unmeasured", _motion(card, shown)]
    if card.get("uses"):
        parts.append("uses: " + ", ".join(card["uses"][:2]))
    text = ", ".join(parts) + (f"; place: {card['place']}" if card.get("place") else "")
    return text if len(text) <= MAX_WHY else text[:MAX_WHY - 1].rsplit(" ", 1)[0] + "…"


def title_of(card: dict, language: str = "en") -> str:
    es, en = card.get("titleEs"), card.get("titleEn")
    first, second = (es, en) if language == "es" else (en, es)
    return str(first or second or card.get("id") or "")


def compact_card(card: dict, *, language: str = "en", shot: str | None = None, moves: list[str] | None = None,
                 why: str | None = None) -> dict:
    """The six fields of a card. ``card`` may be a shipped card or a public one from a search reply."""
    shown = (card.get("moves") or []) if moves is None else moves
    return {"id": card.get("id"), "title": title_of(card, language), "shot": shot or card.get("shot"), "moves": list(shown),
            "format": card.get("format"), "why": why or short_why(card, shot=shot, moves=moves)}


def compact_report(report: dict, language: str | None = None) -> dict:
    """A ``suggest`` or ``catalog`` reply with every card shortened; the rest of the reply stays as it is."""
    return {**report, "templates": [compact_card(card, language=language or "en") for card in report.get("templates") or []]}
