import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from services.director.h3_dialogue import scrub_h3_silent_shot_vocals  # noqa: E402
from services.director.planners.short_film import (  # noqa: E402
    _h3_vocal_semantic_issues,
    _normalize_h3_audio_metadata,
)


def _silent_shot():
    return {
        "dialogue_beats": [],
        "action_beats": ["Whiskers freezes and gasps as the T-Rex rounds the corner"],
        "audio_plan": {"mode": "ambient", "lip_sync_critical": False,
                       "ambience": "distant traffic, a sharp gasp", "effects": ["tiny gasp", "thud"]},
        "video_prompt": "A mouse gasps. overall_soundscape: distant traffic, a sharp gasp non_diegetic_music: none",
    }


def test_silent_shot_vocal_cues_are_scrubbed_to_pass_preflight():
    shots = [_silent_shot()]
    _normalize_h3_audio_metadata(shots)
    assert _h3_vocal_semantic_issues(shots)
    assert scrub_h3_silent_shot_vocals(shots[0]) is True
    _normalize_h3_audio_metadata(shots)
    assert _h3_vocal_semantic_issues(shots) == []
    assert shots[0]["audio_plan"]["effects"] == ["thud"]


def test_dialogue_shots_are_left_alone():
    shot = _silent_shot()
    shot["dialogue_beats"] = [{"speaker_id": "whiskers", "spoken_text": "Run!"}]
    assert scrub_h3_silent_shot_vocals(shot) is False
    assert "gasps" in shot["video_prompt"]


def test_visible_cast_does_not_repeat_a_name_the_description_already_starts_with():
    from services.director.planners.short_film import _h3_rebuilt_visual_prompt
    prompt = _h3_rebuilt_visual_prompt({"subjects_on_screen": [
        {"speaker_name": "Tyranno", "visual_description": "Tyranno (D-01): Massive theropod with cracked skin"},
        {"speaker_name": "Whiskers", "visual_description": "Small white mouse"},
    ]})
    assert "Tyranno, Tyranno" not in prompt
    assert "Tyranno (D-01): Massive theropod with cracked skin" in prompt
    assert "Whiskers, Small white mouse" in prompt


def test_screenplay_cast_list_and_stage_directions_are_not_spoken():
    from services.director.planners.short_film import _extract_h3_screenplay_dialogue
    screenplay = """**Main Character:**
- **Tyranno** (D-01): A massive theropod with cracked skin.

**Key Supporting Character(s):**
- **Whiskers** (M-01): A sleek mouse.

**INT. HIGH STREET - DUSK**

**TYRANNO**
*(growling, low-frequency vibration)* **Ughhh...**

**WHISKERS**
*(squeaking)* **Not today, big guy!**

**TYRANNO**
*(roaring)* **WHERE—IS—**
"""
    rows = _extract_h3_screenplay_dialogue(screenplay)
    assert [row["speaker_name"] for row in rows] == ["TYRANNO", "WHISKERS", "TYRANNO"]
    assert [row["spoken_text"] for row in rows] == ["Ughhh...", "Not today, big guy!", "WHERE... IS..."]
