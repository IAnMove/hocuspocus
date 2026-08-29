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
