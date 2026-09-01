"""Regression tests for music-video pacing and structured Story lyrics."""

from app.services.audio_analysis import plan_clip_structure
from app.services.llm_service import structure_from_tagged_lyrics


def _analysis(duration: float = 92.0, section_count: int = 5) -> dict:
    beat_seconds = 0.5
    section_duration = duration / section_count
    return {
        "duration": duration,
        "bpm": 120.0,
        "beats": [
            {"time": round(index * beat_seconds, 3), "strength": 0.5}
            for index in range(int(duration / beat_seconds) + 1)
        ],
        "sections": [
            {
                "start": index * section_duration,
                "end": (index + 1) * section_duration,
                "label": ["intro", "verse", "chorus", "bridge", "outro"][index % 5],
                "energy": 0.3 + index * 0.1,
            }
            for index in range(section_count)
        ],
        "lyrics": [],
    }


def test_pacing_profiles_create_distinct_useful_clip_counts():
    analysis = _analysis()
    cinematic = plan_clip_structure(analysis, pacing_profile="cinematic")
    balanced = plan_clip_structure(analysis, pacing_profile="balanced")
    rhythmic = plan_clip_structure(analysis, pacing_profile="rhythmic")

    assert 6 <= len(cinematic) <= 9
    assert 12 <= len(balanced) <= 16
    assert 18 <= len(rhythmic) <= 26
    assert len(cinematic) < len(balanced) < len(rhythmic)
    assert {clip["section_label"] for clip in balanced}.issuperset({"verse", "chorus", "bridge"})


def test_profile_clips_cover_the_complete_song():
    clips = plan_clip_structure(_analysis(), pacing_profile="balanced")
    assert clips[0]["start"] == 0.0
    assert clips[-1]["end"] == 92.0
    assert all(left["end"] == right["start"] for left, right in zip(clips, clips[1:]))


def test_missing_beats_and_zero_bpm_use_a_safe_fallback():
    analysis = _analysis(duration=75.0)
    analysis.update({"bpm": 0.0, "beats": []})

    clips = plan_clip_structure(analysis, pacing_profile="balanced")

    assert clips
    assert clips[0]["start"] == 0.0
    assert clips[-1]["end"] == 75.0
    assert all(left["end"] == right["start"] for left, right in zip(clips, clips[1:]))


def test_zero_duration_uses_a_safe_non_empty_fallback_timeline():
    analysis = _analysis(duration=75.0)
    analysis.update({"duration": 0.0, "bpm": 0.0, "beats": []})

    clips = plan_clip_structure(analysis, pacing_profile="balanced")

    assert clips
    assert clips[0]["start"] == 0.0
    assert clips[-1]["end"] == 180.0


def test_structured_story_lyrics_are_authoritative():
    structure = structure_from_tagged_lyrics(
        "[Intro]\n(instrumental)\n[Verse 1]\nA seed crosses the empty sky\n"
        "[Pre-Chorus]\nThe metal guardian wakes\n[Chorus]\nHope grows blue tonight\n"
        "[Outro]\nHope remains",
        92.0,
    )

    assert [section["label"] for section in structure] == [
        "intro", "verse", "pre-chorus", "chorus", "outro",
    ]
    assert structure[0]["start"] == 0.0
    assert all(left["start"] < right["start"] for left, right in zip(structure, structure[1:]))
