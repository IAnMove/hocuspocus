"""Provider-free coverage for the shared music model contract."""
from __future__ import annotations

import pytest

from app.services.music_model_contract import (
    ACE_DEFAULT,
    GUIDE_REVISION,
    MUSIC3_LOCAL,
    REMOTE_PROMPT_LIMIT,
    assert_enqueue_guard,
    compile_backend_request,
    freeze_music_spec,
    inspect_music_model,
    require_catalog_entry,
    MusicModelError,
)
from app.services.music_submission import MusicSubmissionError, spec_snapshot, submit_music_generation


LONG_CAPTION = (
    "### Global Metadata\n"
    "Warm acoustic folk in C major at 92 BPM with close Spanish vocals, "
    "fingerpicked guitar, brushed drums and a wide final chorus. " * 8
)


def test_catalog_distinguishes_known_installed_and_unavailable_states():
    remote = inspect_music_model("music-3.0", configured=False)
    assert remote["known"] is True
    assert remote["downloadable"] is False
    assert remote["configured"] is False
    assert remote["available"] is False
    assert "not configured" in " ".join(remote["unavailable_reasons"]).lower()

    ready_remote = inspect_music_model("music-3.0", configured=True)
    assert ready_remote["available"] is True

    local = inspect_music_model(MUSIC3_LOCAL, installed=False, enabled=True)
    assert local["known"] is True
    assert local["downloadable"] is True
    assert local["incomplete"] is True
    assert local["installed"] is False
    assert local["available"] is False

    installed = inspect_music_model(MUSIC3_LOCAL, installed=True)
    assert installed["available"] is True

    community = inspect_music_model("minimax_music3_gguf")
    assert community["known"] is True
    assert community["compatible"] is False
    assert community["available"] is False

    unknown = inspect_music_model("not-a-model")
    assert unknown["known"] is False
    assert unknown["available"] is False


def test_community_model_cannot_be_compiled():
    with pytest.raises(MusicModelError, match="validated adapter"):
        require_catalog_entry("minimax_music3_mlx")


def test_local_caption_is_not_truncated_to_remote_limit():
    assert len(LONG_CAPTION) > REMOTE_PROMPT_LIMIT
    spec = freeze_music_spec({
        "model": ACE_DEFAULT,
        "prompt": LONG_CAPTION,
        "lyrics": "[Verse]\nLa noche canta",
        "duration_seconds": 120,
    })
    assert spec["guide_revision"] == GUIDE_REVISION
    assert spec["prompt"] == LONG_CAPTION.strip()
    assert spec["compiled"]["prompt"] == LONG_CAPTION.strip()
    assert spec["compiled"]["truncated_prompt"] is False
    assert spec["compiled"]["backend"] == "generateMusic"
    assert spec["route"] == "local"


def test_remote_compile_applies_300_character_cap_without_rewriting_the_spec():
    spec = freeze_music_spec({
        "model": "music-3.0",
        "prompt": LONG_CAPTION,
        "lyrics": "[Verse]\nLa noche canta",
        "count": 1,
    })
    assert spec["prompt"] == LONG_CAPTION.strip()
    assert spec["compiled"]["prompt"] == LONG_CAPTION.strip()[:REMOTE_PROMPT_LIMIT]
    assert spec["compiled"]["truncated_prompt"] is True
    assert spec["compiled"]["backend"] == "minimax_api"


def test_invalid_lyrics_language_blocks_enqueue_and_keeps_the_original(tmp_path):
    request = {
        "prompt": "cinematic dream pop",
        "lyrics": "[Verse]\nThe night is singing through the server",
        "lyrics_language": "es",
        "model": "music-3.0",
        "count": 1,
        "output_folder": "night-shift",
        "idempotency_key": "cmd-guard",
    }
    with pytest.raises(MusicSubmissionError, match="idioma") as caught:
        submit_music_generation(workspace_dir=str(tmp_path), request=request)
    assert caught.value.details["lyrics"] == request["lyrics"]
    assert caught.value.details["language_guard"]["verdict"] == "invalid"
    assert "proposal" in caught.value.details


def test_unevaluable_language_is_recorded_and_is_not_ok():
    spec = freeze_music_spec({
        "model": ACE_DEFAULT,
        "prompt": "chanson folk",
        "lyrics": "[Verse]\nLa nuit chante",
        "lyrics_language": "fr",
    })
    assert spec["language_guard"]["verdict"] == "unevaluable"
    assert spec["language_guard"]["ok"] is False
    assert_enqueue_guard(spec)


def test_story_wizard_and_ui_ports_compile_equivalent_specs():
    shared = {
        "model": ACE_DEFAULT,
        "prompt": LONG_CAPTION,
        "lyrics": "[Verse]\nLa noche canta\n[Chorus]\nSigue el río",
        "instrumental": False,
        "duration_seconds": 96,
        "lyrics_language": "es",
        "count": 1,
    }
    story = freeze_music_spec({**shared, "source": "story"})
    wizard = freeze_music_spec({**shared, "source": "wizard"})
    ui = freeze_music_spec({**shared, "source": "ui"})
    for spec in (story, wizard, ui):
        spec.pop("source", None)
    assert story["compiled"] == wizard["compiled"] == ui["compiled"]
    assert story["prompt"] == wizard["prompt"] == ui["prompt"] == LONG_CAPTION.strip()
    assert story["guide_revision"] == wizard["guide_revision"] == ui["guide_revision"]


def test_spec_snapshot_keeps_local_caption_and_adds_folder():
    spec = spec_snapshot({
        "model": MUSIC3_LOCAL,
        "prompt": LONG_CAPTION,
        "lyrics": "[Verse]\nLa noche canta",
        "output_folder": "night-shift",
        "duration_seconds": 400,
    })
    assert spec["output_folder"] == "night-shift"
    assert spec["prompt"] == LONG_CAPTION.strip()
    assert spec["duration_seconds"] == 300
    assert spec["compiled"]["truncated_prompt"] is False


def test_omitted_duration_is_not_a_requested_duration():
    spec = freeze_music_spec({
        "model": ACE_DEFAULT,
        "prompt": "cinematic dream pop",
        "lyrics": "[Verse]\nLa noche canta",
    })
    assert spec["duration_seconds"] is None
    assert spec["compiled"]["duration_seconds"] == 90


def test_cover_without_lyrics_enqueues_when_reference_is_present(tmp_path):
    record = submit_music_generation(
        workspace_dir=str(tmp_path),
        request={
            "prompt": "cover this folk song",
            "lyrics": "",
            "model": "music-cover",
            "count": 1,
            "output_folder": "night-shift",
            "reference_audio_filename": "source.mp3",
            "idempotency_key": "cmd-cover",
        },
    )
    assert record["spec"]["mode"] == "cover"
    assert record["spec"]["language_guard"]["verdict"] == "valid"
    assert record["replay"] is False


def test_invalid_count_is_rejected_and_zero_uses_remote_default():
    with pytest.raises(MusicModelError, match="integer"):
        freeze_music_spec({
            "model": "music-3.0",
            "prompt": "cinematic dream pop",
            "lyrics": "[Verse]\nLa noche canta",
            "count": "many",
        })
    spec = freeze_music_spec({
        "model": "music-3.0",
        "prompt": "cinematic dream pop",
        "lyrics": "[Verse]\nLa noche canta",
        "count": 0,
    })
    assert spec["count"] == 2


def test_compile_backend_request_does_not_fallback_to_ace():
    entry = require_catalog_entry("music-3.0")
    compiled = compile_backend_request(
        entry, caption="style", lyrics="[Verse]\nHi", instrumental=False,
        duration_seconds=60, count=1,
    )
    assert compiled["model"] == "music-3.0"
    assert compiled["backend"] == "minimax_api"
