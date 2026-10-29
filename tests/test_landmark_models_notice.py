"""The DWPose model files are not always on a machine (a fresh worktree, a CI box): say so instead of degrading silently."""
import logging

from services import face_landmarks


def _nothing_found(monkeypatch):
    from shared.utils import files_locator
    monkeypatch.delenv("HOCUS_FACE_LANDMARKS", raising=False)
    monkeypatch.setattr(files_locator, "locate_file", lambda name, error_if_none=True: None)


def test_the_missing_files_are_named(monkeypatch):
    _nothing_found(monkeypatch)
    assert face_landmarks.models_missing() == list(face_landmarks.MODELS)


def test_a_switched_off_pass_is_not_a_missing_one(monkeypatch):
    _nothing_found(monkeypatch)
    monkeypatch.setenv("HOCUS_FACE_LANDMARKS", "0")
    assert face_landmarks.models_missing() == []


def test_the_first_use_without_the_files_is_logged_once(monkeypatch, caplog):
    _nothing_found(monkeypatch)
    monkeypatch.setattr(face_landmarks, "_model", None)
    with caplog.at_level(logging.WARNING, logger=face_landmarks.__name__):
        assert face_landmarks._wholebody() is None
        assert face_landmarks._wholebody() is None
    notes = [record.getMessage() for record in caplog.records if "DWPose" in record.getMessage()]
    assert len(notes) == 1 and "yolox_l.onnx" in notes[0]
