"""Bare library names in a generate request become the files they stand for."""
from pathlib import Path

import pytest

from services.library_media_paths import is_bare_name, resolve_library_names


@pytest.fixture
def roots(tmp_path):
    uploads, workspace = tmp_path / "uploads", tmp_path / "outputs" / "demo"
    uploads.mkdir()
    workspace.mkdir(parents=True)
    return {"uploads_dir": str(uploads), "workspace_dir": str(workspace)}


def _touch(folder: str, name: str) -> str:
    path = Path(folder) / name
    path.write_bytes(b"x")
    return str(path)


def _resolve(body, roots):
    resolve_library_names(body, "demo", **roots)
    return body


@pytest.mark.parametrize("value, expected", [
    ("library pick.png", True), ("a, b. c.wav", True),
    ("uploads/x.png", False), ("/abs/x.png", False), ("C:\\x.png", False),
    ("/api/v1/uploads/x.png", False), ("https://host/x.png", False), ("", False), (None, False), (3, False),
])
def test_only_a_name_with_no_folder_is_bare(value, expected):
    assert is_bare_name(value) is expected


def test_single_and_list_fields_resolve_to_their_workspace_files(roots):
    guide = _touch(roots["workspace_dir"], "guide clip.mp4")
    voice = _touch(roots["workspace_dir"], "voice take.wav")
    start = _touch(roots["workspace_dir"], "first frame.png")
    refs = [_touch(roots["workspace_dir"], "ref a.png"), _touch(roots["uploads_dir"], "ref b.png")]
    body = {"video_guide": "guide clip.mp4", "audio_guide": "voice take.wav", "image_start": ["first frame.png"],
            "image_refs": ["ref a.png", "ref b.png"], "prompt": "keep me"}

    _resolve(body, roots)

    assert body["video_guide"] == guide and body["audio_guide"] == voice
    assert body["image_start"] == [start] and body["image_refs"] == refs
    assert body["prompt"] == "keep me"


def test_per_clip_keyframes_resolve_inside_each_clip(roots):
    one = _touch(roots["workspace_dir"], "key one.png")
    two = _touch(roots["uploads_dir"], "key two.png")
    body = {"per_clip_keyframes": [["key one.png"], [], ["key two.png", "gone.png"]]}

    _resolve(body, roots)

    assert body["per_clip_keyframes"] == [[one], [], [two, "gone.png"]]


def test_what_worked_before_is_left_alone(roots, tmp_path):
    outside = _touch(str(tmp_path), "elsewhere.mp4")
    body = {"video_guide": outside, "audio_guide": "uploads/old.wav", "image_start": "", "image_end": None,
            "image_refs": ["/api/v1/uploads/x.png", "https://host/y.png", "gone.png"], "video_mask": 5}
    before = {key: list(value) if isinstance(value, list) else value for key, value in body.items()}

    assert _resolve(body, roots) == before


def test_a_name_in_both_places_is_not_guessed(roots):
    _touch(roots["workspace_dir"], "twin.png")
    _touch(roots["uploads_dir"], "twin.png")
    body = {"image_start": "twin.png"}

    assert _resolve(body, roots) == {"image_start": "twin.png"}


def test_fields_that_are_absent_are_not_added(roots):
    assert _resolve({"prompt": "x"}, roots) == {"prompt": "x"}
