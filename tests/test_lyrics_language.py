"""Provider-free lyric language contract. No GPU, no model weights."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.lyrics_language import (
    assert_lyrics_language,
    canonical_lyrics_language,
    repair_lyrics_language,
    validate_lyrics_language,
)


CORPUS = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "lyrics_language_corpus.json").read_text(
        encoding="utf-8",
    )
)

SPANISH_OK = CORPUS["cases"][0]["lyrics"]
ENGLISH_CHORUS = """[Verse]
En la red despierta el sysadmin y la noche canta.
[Chorus]
The server fights through the night and we sing for our network.
"""
CJK = """[Verse]
En la red despierta el sysadmin.
[Chorus]
夜晚在服务器里唱歌 夜は歌う
"""


def _run_case(case: dict) -> dict:
    kwargs = {
        "protected_segments": case.get("protected"),
        "instrumental": bool(case.get("instrumental")),
    }
    if case.get("repair"):
        return repair_lyrics_language(case["lyrics"], case["language"], **kwargs)
    return validate_lyrics_language(case["lyrics"], case["language"], **kwargs)


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["id"])
def test_shared_corpus(case: dict):
    report = _run_case(case)
    assert report["verdict"] == case["verdict"]
    assert report["ok"] is (case["verdict"] == "valid")
    if case.get("preserve_original"):
        assert report["lyrics"] == case["lyrics"]
        assert report.get("proposal") is not None


def test_empty_vocal_is_invalid_not_ok():
    report = validate_lyrics_language("", "Español")
    assert report["verdict"] == "invalid"
    assert report["ok"] is False


def test_estonian_is_not_scored_as_spanish():
    assert canonical_lyrics_language("Estonian") == "et"
    report = validate_lyrics_language(SPANISH_OK, "Estonian")
    assert report["verdict"] == "unevaluable"
    assert report["ok"] is False


def test_english_as_french_is_unevaluable():
    report = validate_lyrics_language(
        "[Verse]\nThe night sings through the server farm.",
        "français",
    )
    assert canonical_lyrics_language("français") == "fr"
    assert report["verdict"] == "unevaluable"
    assert report["ok"] is False


def test_missing_protected_span_is_invalid():
    report = validate_lyrics_language(
        "[Chorus]\nLa noche nos verá.\n",
        "Español",
        protected_segments=[{"kind": "lyrics", "text": "Hello, world", "language": "en"}],
    )
    assert report["verdict"] == "invalid"
    assert any("verbatim" in reason for reason in report["reasons"])


def test_multiline_protected_span_is_exact():
    block = "Keep this\nexact block"
    report = validate_lyrics_language(
        f"[Verse]\n{block}\nLa noche canta.\n",
        "Español",
        protected_segments=[{"kind": "lyrics", "text": block, "language": "en"}],
    )
    assert report["verdict"] == "valid"


def test_repair_keeps_original_and_does_not_ok_empty_proposal():
    original = "[Chorus]\n夜晚在服务器里唱歌\n"
    report = repair_lyrics_language(original, "Español")
    assert report["lyrics"] == original
    assert report["verdict"] == "invalid"
    assert report["ok"] is False
    assert "夜晚" in report["lyrics"]
    assert report["proposal"] is not None
    assert "夜晚" not in (report["proposal"] or "")


def test_repair_strips_cjk_into_proposal_not_lyrics():
    report = repair_lyrics_language(CJK, "Español")
    assert "En la red despierta el sysadmin." in report["lyrics"]
    assert "夜晚" in report["lyrics"]
    assert report["proposal"] is not None
    assert "夜晚" not in report["proposal"]
    assert "夜は" not in report["proposal"]
    assert report["repaired"] is True


def test_assert_does_not_repair_by_default():
    with pytest.raises(ValueError, match="idioma"):
        assert_lyrics_language(ENGLISH_CHORUS, "Español")


def test_accidental_english_chorus_fails():
    report = validate_lyrics_language(ENGLISH_CHORUS, "Español")
    assert report["ok"] is False
    assert report["language_mismatch"] is True
