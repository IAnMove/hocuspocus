"""Regression coverage for the word alignment exposed to cutout dialogue."""

from app.services import audio_analysis


class _Word:
    def __init__(self, start, end, word):
        self.start = start
        self.end = end
        self.word = word


class _Segment:
    start = 1.0
    end = 2.0
    text = " Hello there "
    words = [_Word(1.0, 1.3, " Hello"), _Word(1.31, 1.7, " there"), _Word(None, 1.8, "bad")]


class _Model:
    def __init__(self):
        self.kwargs = None

    def transcribe(self, _path, **kwargs):
        self.kwargs = kwargs
        return iter([_Segment()]), object()


def test_transcription_exposes_clean_word_alignment(monkeypatch):
    model = _Model()
    monkeypatch.setattr(audio_analysis, "_get_whisper_model", lambda: model)

    lyrics = audio_analysis._transcribe("example.wav")

    assert model.kwargs["word_timestamps"] is True
    assert lyrics[0].text == "Hello there"
    assert [(word.start, word.end, word.text) for word in lyrics[0].words] == [
        (1.0, 1.3, "Hello"),
        (1.31, 1.7, "there"),
    ]


def test_known_lyrics_disable_vad_so_a_quiet_intro_is_not_dropped(monkeypatch):
    model = _Model()
    monkeypatch.setattr(audio_analysis, "_get_whisper_model", lambda: model)

    audio_analysis._transcribe("song.wav", "[Intro]\nThe wizard enters the chat")

    assert model.kwargs["vad_filter"] is False
    assert model.kwargs["condition_on_previous_text"] is False
    assert model.kwargs["max_initial_timestamp"] == 30.0


def test_literal_lyrics_align_to_audio_and_create_action_anchor():
    transcript = [audio_analysis.LyricSegment(
        start=18.3,
        end=20.42,
        text="Gandalf ha entrado al chat",
        words=[
            audio_analysis.LyricWord(18.3, 18.9, "Gandalf"),
            audio_analysis.LyricWord(18.91, 19.1, "ha"),
            audio_analysis.LyricWord(19.16, 19.7, "entrado"),
            audio_analysis.LyricWord(19.71, 19.9, "al"),
            audio_analysis.LyricWord(19.91, 20.42, "chat"),
        ],
    )]

    timeline, timing = audio_analysis.align_authoritative_lyrics(
        "[Intro hablado]\nGandalf ha entrado al chat.", transcript, 30.0,
    )
    events = audio_analysis.build_visual_events(timeline)

    assert timeline[0].text == "Gandalf ha entrado al chat."
    assert (timeline[0].start, timeline[0].end) == (18.3, 20.42)
    assert timing["coverage"] == 1.0
    assert events[0]["kind"] == "entrance"
    assert events[0]["time"] == 19.16
    assert "00:00:18,300 --> 00:00:20,420" in audio_analysis.lyrics_to_srt(timeline)


def test_aligned_section_structure_uses_audio_times():
    timeline = [
        {"start": 3.2, "section": "Intro hablado", "text": "Welcome"},
        {"start": 18.3, "section": "Verso 1", "text": "First verse"},
        {"start": 42.75, "section": "Estribillo", "text": "Chorus"},
    ]

    structure = audio_analysis.structure_from_aligned_lyrics(timeline)

    assert [item["start"] for item in structure] == [3.2, 18.3, 42.75]
    assert [item["display_label"] for item in structure] == [
        "Intro hablado", "Verso 1", "Estribillo",
    ]
    assert [item["label"] for item in structure] == ["intro", "verse", "chorus"]


def test_missing_asr_keeps_all_written_lines_as_approximate_editable_cues():
    timeline, timing = audio_analysis.align_authoritative_lyrics(
        "[Verse]\nFirst line\nSecond line", [], 20.0,
    )

    assert [cue.text for cue in timeline] == ["First line", "Second line"]
    assert [(cue.start, cue.end) for cue in timeline] == [(0.0, 10.0), (10.0, 20.0)]
    assert all(cue.source == "interpolated" for cue in timeline)
    assert timing["coverage"] == 0.0
