"""Raw prompts: the Director sends a prompt exactly as planned; a prompt the user types keeps its lettering."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services import director_pipeline

# A music video: the no-visible-text lock is for sung projects only
# (tests/test_director_narrow_locks.py covers stories).
STATE = {
    "pipeline_type": "music_video",
    "_params_snapshot": {"preserve_visual_style": True, "visual_style": "European comic art, ink lines"},
}
PROMPT = "A shop window with a sign reading 'OPEN'."


def _services(**services):
    return patch.object(director_pipeline, "_wgp", SimpleNamespace(server_config={"services": services}))


def test_music_video_rerun_prompts_get_the_locks_by_default():
    with _services():
        sent = director_pipeline._saved_prompt_contract(STATE, PROMPT, "image")
    assert sent.startswith("NO VISIBLE TEXT LOCK") and "VISUAL STYLE LOCK:" in sent


def test_raw_prompts_send_the_plan_as_written():
    with _services(raw_prompts=True):
        assert director_pipeline._saved_prompt_contract(STATE, PROMPT, "image") == PROMPT
        assert director_pipeline._raw_prompts() is True


def test_a_prompt_the_user_typed_keeps_the_text_it_asks_for():
    with _services():
        sent = director_pipeline._saved_prompt_contract(STATE, PROMPT, "image", typed=True)
    assert "OPEN" in sent and "NO VISIBLE TEXT LOCK" not in sent and "VISUAL STYLE LOCK:" in sent
