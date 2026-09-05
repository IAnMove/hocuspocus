"""Provider-free lyric language contract. No GPU, no model weights."""

from __future__ import annotations

import pytest

from services.lyrics_language import (
    assert_lyrics_language,
    repair_lyrics_language,
    validate_lyrics_language,
)


SPANISH_OK = """[Verse]
En la red despierta el sysadmin.
[Chorus]
La noche y el código cantan.
"""

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

ARABIC = """[Verse]
En la red despierta el sysadmin.
[Chorus]
الليل يغني في الشبكة
"""


def test_spanish_structured_lyric_is_ok():
    report = validate_lyrics_language(SPANISH_OK, "Español")
    assert report["ok"] is True
    assert report["language_mismatch"] is False
    regional = validate_lyrics_language(SPANISH_OK, "Español de España")
    assert regional["ok"] is True
    assert regional["language_mismatch"] is False


def test_section_tags_are_not_english_contamination():
    report = validate_lyrics_language(
        "[Verse]\nLa noche canta en la red.\n[Chorus]\nEl código sangra.\n[Outro]\nReinicia.",
        "español",
    )
    assert report["ok"] is True


def test_accidental_english_chorus_fails():
    report = validate_lyrics_language(ENGLISH_CHORUS, "Español")
    assert report["ok"] is False
    assert report["language_mismatch"] is True
    assert any("English" in reason for reason in report["reasons"])


def test_chinese_and_arabic_fail_spanish_lyrics():
    chinese = validate_lyrics_language(CJK, "castellano")
    arabic = validate_lyrics_language(ARABIC, "es")
    assert chinese["ok"] is False
    assert arabic["ok"] is False
    assert any("han" in reason for reason in chinese["reasons"])
    assert any("arabic" in reason for reason in arabic["reasons"])


def test_quoted_english_is_ok_when_protected():
    lyrics = '[Chorus]\nHello, world\nLa noche nos verá.'
    report = validate_lyrics_language(
        lyrics,
        "Español",
        protected_segments=[{"kind": "lyrics", "text": "Hello, world", "language": "en"}],
    )
    assert report["ok"] is True


def test_technical_caption_is_not_mixed_into_lyric_validation():
    report = validate_lyrics_language(SPANISH_OK, "Español")
    assert "Heavy metal" not in report["lyrics"]
    assert report["ok"] is True


def test_repair_strips_cjk_and_keeps_spanish_lines():
    report = repair_lyrics_language(CJK, "Español")
    assert "En la red despierta el sysadmin." in report["lyrics"]
    assert "夜晚" not in report["lyrics"]
    assert "夜は" not in report["lyrics"]
    assert report["repaired"] is True
    assert report["stripped_spans"]
    assert report["ok"] is True


def test_repair_does_not_translate_an_english_chorus():
    report = repair_lyrics_language(ENGLISH_CHORUS, "Español")
    assert report["ok"] is False
    assert "The server fights through the night" in report["lyrics"]
    assert not any("El servidor" in report["lyrics"] for _ in (0,))


def test_assert_raises_on_unrepaired_mismatch():
    with pytest.raises(ValueError, match="idioma"):
        assert_lyrics_language(ENGLISH_CHORUS, "Español")
