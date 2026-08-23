import ast
from pathlib import Path

import pytest

from services.media_paths import MediaPathNotAllowed, resolve_permitted_media_path


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"


def test_permitted_media_path_accepts_upload_and_current_workspace(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "workspace"
    uploads.mkdir()
    workspace.mkdir()
    upload = uploads / "voice.wav"
    output = workspace / "mix.mp3"
    upload.write_bytes(b"RIFF")
    output.write_bytes(b"ID3")

    assert resolve_permitted_media_path(
        str(upload),
        uploads_root=str(uploads),
        workspace_root=str(workspace),
        kinds=("audio",),
    ) == str(upload.resolve())
    assert resolve_permitted_media_path(
        str(output),
        uploads_root=str(uploads),
        workspace_root=str(workspace),
        kinds=("audio",),
    ) == str(output.resolve())


def test_permitted_media_path_rejects_external_and_other_workspace_files(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "workspace"
    other = tmp_path / "other"
    uploads.mkdir()
    workspace.mkdir()
    other.mkdir()
    external = tmp_path / "external.wav"
    foreign = other / "foreign.wav"
    external.write_bytes(b"RIFF")
    foreign.write_bytes(b"RIFF")

    for candidate in (external, foreign):
        with pytest.raises(MediaPathNotAllowed):
            resolve_permitted_media_path(
                str(candidate),
                uploads_root=str(uploads),
                workspace_root=str(workspace),
                kinds=("audio",),
            )


def test_permitted_media_path_rejects_a_symlink_escape(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "workspace"
    uploads.mkdir()
    workspace.mkdir()
    external = tmp_path / "external.wav"
    external.write_bytes(b"RIFF")
    link = uploads / "escape.wav"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("file symlinks are unavailable on this platform")

    with pytest.raises(MediaPathNotAllowed):
        resolve_permitted_media_path(
            str(link),
            uploads_root=str(uploads),
            workspace_root=str(workspace),
            kinds=("audio",),
        )


def test_permitted_media_path_distinguishes_missing_from_forbidden(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "workspace"
    uploads.mkdir()
    workspace.mkdir()

    with pytest.raises(FileNotFoundError):
        resolve_permitted_media_path(
            str(uploads / "missing.wav"),
            uploads_root=str(uploads),
            workspace_root=str(workspace),
            kinds=("audio",),
        )


def test_audio_trim_and_analysis_endpoints_use_the_shared_resolver():
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in (
        "trim_uploaded_audio",
        "analyze_audio",
        "start_audio_analysis_job",
    ):
        calls = [
            node.func.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "_resolve_request_media_path" in calls, name

