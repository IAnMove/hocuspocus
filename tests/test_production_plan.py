"""production.plan turns three briefs into specs that pass dry_run unedited."""
from __future__ import annotations

import pytest

import asyncio

from services.music_production import command_handlers, validate_spec
from services.production_dry_run import dry_run
from services.production_plan import PlanError, plan_brief


def _brief(**extra):
    brief = {
        "tema": "HocusPocus",
        "publico": "makers, one minute musical",
        "duracion": "48 seconds",
        "musica": "bright pop 120 BPM",
        "estilo": "anime product musical",
        "protagonista": "a friendly inventor at a desk",
        "cta": "Try the studio",
        "limites": "no real people",
        "lyrics": "[Verse]\nA small inventor wakes up\nThe desk is full of light\nA spark begins to hum\nThe night is turning bright\n[Chorus]\nTry the studio now\nMake it move, make it glow\nTry the studio now\nLet the whole world know\n",
    }
    brief.update(extra)
    return brief


def _passes(brief):
    spec = plan_brief(brief)
    validate_spec(spec)
    report = dry_run(spec)
    assert report["running"] is False
    assert report["lines_without_shot"] == []
    assert report["long_titles"] == []
    assert report["long_captions"] == []
    return spec


def test_three_briefs_pass_dry_run_unedited():
    musical = _passes(_brief())
    zine = _passes(_brief(tema="Love Machine", estilo="riso caricature zine", protagonista="a caricature of a programmer", cta="Read the zine"))
    desktop = _passes(_brief(tema="City Windows", estilo="Omarchy desktop", musica="pulse 100 BPM", protagonista="a person at a tiling desktop", cta="Switch workspace"))
    noir = _passes(_brief(tema="Night City", estilo="neo-noir night", musica="drone 90 BPM", protagonista="a figure in the rain", cta="Find the desk"))
    assert musical["style"]["image"].startswith("Cinematic anime")
    assert zine["style"]["lyric_template"] == "dymo"
    assert desktop["style"]["theme"] == "tokyo-night"
    assert noir["style"]["image_model"] == "flux2_klein_9b"


def test_caller_lyrics_are_kept():
    lyrics = "[Verse]\nhello there\nstay a while\n[Chorus]\nsing it back\nonce again\n"
    spec = plan_brief(_brief(lyrics=lyrics))
    assert spec["song"]["lyrics"] == lyrics.strip()


def test_a_missing_field_is_rejected():
    brief = _brief()
    del brief["cta"]
    try:
        plan_brief(brief)
    except PlanError as error:
        assert error.code == "invalid_brief"
    else:
        raise AssertionError("expected PlanError")


def test_handler_returns_the_spec_without_a_thread():
    handlers = command_handlers(lambda _ws: "/tmp", lambda: "/tmp", lambda: "", lambda: "")
    result = asyncio.run(handlers["production.plan"]({"version": 1, "input": {"brief": _brief()}}))
    assert result["operation"] == "production.plan"
    assert result["result"]["spec"]["shots"]
    assert result["result"]["spec"]["song"]["bpm"] == 120


def test_no_lyrics_is_an_error_not_a_placeholder_song():
    brief = _brief()
    del brief["lyrics"]
    with pytest.raises(PlanError) as error:
        plan_brief(brief)
    assert error.value.code == "invalid_brief" and "lyrics" in str(error.value)
    assert plan_brief(brief, lyricist=lambda fields: "[Verse]\nwritten by a caller\n")["song"]["lyrics"].startswith("[Verse]")


def test_an_explicit_look_word_beats_a_subject_word():
    assert plan_brief(_brief(estilo="zine riso sobre Omarchy"))["style"]["lyric_template"] == "dymo"
    assert plan_brief(_brief(estilo="escritorio Omarchy"))["style"]["theme"] == "tokyo-night"
    assert plan_brief(_brief(estilo="Omarchy en anime"))["style"]["image"].startswith("Cinematic anime")


def test_tempo_and_length_are_read_the_way_a_person_writes_them():
    assert plan_brief(_brief(musica="pop de los 2000s, 120 BPM"))["song"]["bpm"] == 120
    assert plan_brief(_brief(musica="pop de los 2000s"))["song"]["bpm"] == 120
    assert plan_brief(_brief(musica="synth-pop 110-125 BPM"))["song"]["bpm"] == 118
    assert plan_brief(_brief(duracion="1:30 minutos"))["song"]["duration"] == 90
    assert plan_brief(_brief(duracion="2 minutos"))["song"]["duration"] == 120
    assert plan_brief(_brief(duracion="75 segundos"))["song"]["duration"] == 75


def test_accents_survive_in_the_title():
    assert plan_brief(_brief(tema="Educación para niños"))["title"] == "Educación"


def test_the_brief_footer_and_cta_reach_the_spec():
    spec = plan_brief(_brief(footer="Fan-made, not affiliated with anyone", cta="Prueba el estudio"))
    assert spec["style"]["footer"] == "Fan-made, not affiliated with anyone"
    outro = next(shot for shot in spec["shots"] if shot["key"] == "outro")
    assert outro["title"]["fields"]["cta"] == "Prueba el estudio"
