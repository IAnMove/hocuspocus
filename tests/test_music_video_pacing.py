"""Regression tests for music-video pacing and structured Story lyrics."""

from app.services.audio_analysis import plan_clip_structure
from app.services.director.planners.music_video import MusicVideoPlanner
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


def test_source_audio_events_are_assigned_to_clip_with_exact_offset():
    analysis = _analysis(duration=30.0, section_count=3)
    analysis["lyric_timeline"] = [{
        "start": 18.3, "end": 20.42, "text": "Gandalf ha entrado al chat.",
        "source": "aligned_lyrics", "confidence": 1.0,
    }]
    analysis["visual_events"] = [{
        "time": 19.16, "end": 19.7, "kind": "entrance", "cue_index": 0,
        "lyric": "Gandalf ha entrado al chat.", "trigger": "entrado",
        "rule": "The visual action starts here; do not reveal its result earlier.",
    }]

    clips = plan_clip_structure(analysis, pacing_profile="balanced")
    event_clip = next(clip for clip in clips if clip["visual_events"])
    event = event_clip["visual_events"][0]

    assert event["time"] == 19.16
    assert event["offset"] == round(19.16 - event_clip["start"], 3)
    assert event_clip["start"] <= 19.16 < event_clip["end"]


def test_music_planner_receives_mandatory_in_clip_action_time():
    clip = {
        "start": 16.0, "end": 22.0, "label": "verse", "beat_count": 12,
        "lyric_cues": [{"offset": 2.3, "text": "Gandalf ha entrado al chat."}],
        "visual_events": [{"offset": 3.16, "kind": "entrance", "trigger": "entrado"}],
    }

    contexts = MusicVideoPlanner._build_clip_contexts(
        MusicVideoPlanner.__new__(MusicVideoPlanner),
        [clip], [], {}, {}, {}, [{}],
    )

    assert '+2.300s "Gandalf ha entrado al chat."' in contexts[0]
    assert '+3.160s entrance on "entrado"' in contexts[0]
    assert "must not be visible earlier" in contexts[0]


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
