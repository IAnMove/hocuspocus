"""production.plan turns three briefs into specs that pass dry_run unedited."""
from __future__ import annotations

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
