"""Invented speech is muted only in H3 clips planned as silent."""

from types import SimpleNamespace

from app.services import director_pipeline
# Patch the module under the name the pipeline imports it by.
from services import h3_speech_guard

_SILENT = {"_director_audio_plan": {"mode": "ambient_only"}, "_director_dialogue_beats": []}
_SPOKEN = {
    "_director_audio_plan": {"mode": "dialogue_driven"},
    "_director_dialogue_beats": [{"spoken_text": "I am the storm."}],
}


def _run_guard(monkeypatch, tmp_path, *, video_model, plans, speech):
    names = [f"clip{index}.mp4" for index in range(len(plans))] + ["x_multiclip.mp4"]
    for name in names:
        (tmp_path / name).write_bytes(b"video")
    checked, joined = [], []
    monkeypatch.setattr(
        h3_speech_guard, "mute_invented_speech",
        lambda path: checked.append(path) or speech.get(path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1], []),
    )
    monkeypatch.setattr(director_pipeline, "_wgp", SimpleNamespace(
        concatenate_multi_clip_videos=lambda clips, out, audio: joined.append((clips, audio))
        or open(out, "wb").close() or True,
    ))
    director_pipeline._guard_h3_invented_speech(
        "guard", {"video_model": video_model}, plans, names, str(tmp_path),
    )
    return [path.replace("\\", "/").rsplit("/", 1)[-1] for path in checked], joined


def test_only_silent_clips_are_checked_and_join_is_rebuilt(monkeypatch, tmp_path):
    checked, joined = _run_guard(
        monkeypatch, tmp_path,
        video_model="minimax_h3_fused_turbo",
        plans=[_SILENT, _SPOKEN, _SILENT],
        speech={"clip2.mp4": [(1.0, 2.0, "Das?")]},
    )
    assert checked == ["clip0.mp4", "clip2.mp4"]
    assert len(joined) == 1 and len(joined[0][0]) == 3 and joined[0][1] is None


def test_join_is_left_alone_when_no_speech_is_found(monkeypatch, tmp_path):
    _checked, joined = _run_guard(
        monkeypatch, tmp_path,
        video_model="minimax_h3_fused_turbo", plans=[_SILENT, _SILENT], speech={},
    )
    assert joined == []


def test_non_h3_models_are_not_checked(monkeypatch, tmp_path):
    checked, _joined = _run_guard(
        monkeypatch, tmp_path, video_model="ltx2", plans=[_SILENT], speech={},
    )
    assert checked == []


def test_a_failing_check_never_breaks_the_run(monkeypatch, tmp_path):
    def broken(_path):
        raise FileNotFoundError("ffmpeg")

    (tmp_path / "clip0.mp4").write_bytes(b"video")
    monkeypatch.setattr(h3_speech_guard, "mute_invented_speech", broken)
    director_pipeline._guard_h3_invented_speech(
        "guard", {"video_model": "minimax_h3"}, [_SILENT], ["clip0.mp4"], str(tmp_path),
    )


def test_padded_spans_merge_when_they_overlap():
    assert h3_speech_guard.merge_spans([(3.0, 4.0), (0.0, 1.0), (0.9, 2.0)]) == [
        (0.0, 2.0), (3.0, 4.0),
    ]
