"""A MiniMax H3 manifest names its media the way the picker that chose it did."""
from pathlib import Path

import pytest

from models.minimax_h3.reference_manifest import validate_reference_manifest
from services.h3_reference_paths import resolve_h3_reference_paths


@pytest.fixture
def roots(tmp_path):
    uploads, workspace = tmp_path / "uploads", tmp_path / "outputs" / "demo"
    uploads.mkdir()
    workspace.mkdir(parents=True)
    return {"uploads_dir": str(uploads), "workspace_dir": str(workspace)}


def _resolve(manifest, roots, workspace="demo"):
    return resolve_h3_reference_paths(manifest, workspace, **roots)


def test_library_pick_is_opened_in_its_workspace(roots):
    name = "2026-01-02-03h04m05s_seed1_Picture 1 is a person, same face.png"
    (Path(roots["workspace_dir"]) / name).write_bytes(b"png")
    manifest = [{"type": "image", "path": name, "filename": name}]

    resolved = _resolve(manifest, roots)

    assert resolved[0]["path"] == str(Path(roots["workspace_dir"]) / name)
    assert resolved[0]["filename"] == name
    assert manifest[0]["path"] == name, "the request body is not rewritten in place"
    validated = validate_reference_manifest(resolved, require_files=True)
    assert validated[0]["path"] == resolved[0]["path"]


def test_the_bare_name_alone_is_what_used_to_fail(roots):
    name = "library pick.png"
    (Path(roots["workspace_dir"]) / name).write_bytes(b"png")
    with pytest.raises(ValueError, match="file was not found"):
        validate_reference_manifest([{"type": "image", "path": name}], require_files=True)


def test_upload_url_and_upload_name_are_resolved(roots):
    (Path(roots["uploads_dir"]) / "kept.png").write_bytes(b"png")
    manifest = [
        {"type": "image", "path": "/api/v1/uploads/kept.png"},
        {"type": "image", "path": "kept.png"},
    ]

    resolved = _resolve(manifest, roots)

    expected = str(Path(roots["uploads_dir"]) / "kept.png")
    assert [item["path"] for item in resolved] == [expected, expected]


def test_a_video_soundtrack_from_the_library_is_resolved_too(roots):
    for name in ("clip.mp4", "voice.wav"):
        (Path(roots["workspace_dir"]) / name).write_bytes(b"x")
    manifest = [{"type": "video", "path": "clip.mp4", "audio_path": "voice.wav"}]

    resolved = _resolve(manifest, roots)

    assert resolved[0]["path"].endswith("clip.mp4") and Path(resolved[0]["path"]).is_absolute()
    assert resolved[0]["audio_path"].endswith("voice.wav") and Path(resolved[0]["audio_path"]).is_absolute()


def test_paths_that_already_work_are_left_alone(roots, tmp_path):
    elsewhere = tmp_path / "elsewhere.png"
    elsewhere.write_bytes(b"png")
    manifest = [{"type": "image", "path": str(elsewhere)}, {"type": "image", "path": "uploads/old.png"}]

    assert _resolve(manifest, roots) == manifest


def test_a_missing_name_stays_so_the_check_names_it(roots):
    manifest = [{"type": "image", "path": "gone.png"}]

    resolved = _resolve(manifest, roots)

    assert resolved == manifest
    with pytest.raises(ValueError, match="Reference 1 file was not found: gone.png"):
        validate_reference_manifest(resolved, require_files=True)


def test_another_workspace_is_not_substituted(roots, tmp_path):
    other = tmp_path / "outputs" / "other"
    other.mkdir(parents=True)
    (other / "theirs.png").write_bytes(b"png")
    (Path(roots["workspace_dir"]) / "theirs.png").write_bytes(b"mine")
    manifest = [{"type": "image", "path": "/api/v1/file/theirs.png?workspace=other"}]

    assert _resolve(manifest, roots) == manifest


@pytest.mark.parametrize("value", [None, "text", {"type": "image"}, []])
def test_anything_that_is_not_a_manifest_list_passes_through(roots, value):
    assert _resolve(value, roots) == value


def test_entries_that_are_not_objects_are_kept_for_the_check_to_reject(roots):
    assert _resolve(["x", {"type": "image", "path": ""}], roots) == ["x", {"type": "image", "path": ""}]
