import ast
from pathlib import Path

import pytest

from services.media_paths import (
    MediaPathNotAllowed,
    resolve_permitted_media_path,
    resolve_story_cover_audio,
    resolve_voice_ref_paths,
)


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


def test_permitted_media_path_resolves_audio_upload_subdir(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "workspace"
    audio = uploads / "audio"
    audio.mkdir(parents=True)
    workspace.mkdir()
    sample = audio / "9f2.wav"
    sample.write_bytes(b"RIFF")

    assert resolve_permitted_media_path(
        "audio/9f2.wav",
        uploads_root=str(uploads),
        workspace_root=str(workspace),
        kinds=("audio",),
    ) == str(sample.resolve())
    with pytest.raises(FileNotFoundError):
        resolve_permitted_media_path(
            "9f2.wav",
            uploads_root=str(uploads),
            workspace_root=str(workspace),
            kinds=("audio",),
        )


def test_story_cover_prefers_audio_upload_then_workspace_basename(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "workspace"
    audio = uploads / "audio"
    audio.mkdir(parents=True)
    workspace.mkdir()
    uploaded = audio / "ref.wav"
    catalog = workspace / "theme.mp3"
    uploaded.write_bytes(b"RIFF")
    catalog.write_bytes(b"ID3")

    assert resolve_story_cover_audio(
        "ref.wav",
        uploads_audio_root=str(audio),
        uploads_root=str(uploads),
        workspace_root=str(workspace),
    ) == str(uploaded.resolve())
    assert resolve_story_cover_audio(
        "theme.mp3",
        uploads_audio_root=str(audio),
        uploads_root=str(uploads),
        workspace_root=str(workspace),
    ) == str(catalog.resolve())
    with pytest.raises(FileNotFoundError):
        resolve_story_cover_audio(
            "missing.mp3",
            uploads_audio_root=str(audio),
            uploads_root=str(uploads),
            workspace_root=str(workspace),
        )


def test_resolve_voice_ref_paths_keeps_audio_subdir_and_workspace_names(tmp_path):
    uploads = tmp_path / "uploads"
    workspace = tmp_path / "workspace"
    audio = uploads / "audio"
    audio.mkdir(parents=True)
    workspace.mkdir()
    uploaded = audio / "9f2.wav"
    clip = workspace / "hero.wav"
    uploaded.write_bytes(b"RIFF")
    clip.write_bytes(b"RIFF")

    assert resolve_voice_ref_paths(
        ["audio/9f2.wav", "hero.wav", "missing.wav", "9f2.wav"],
        uploads_root=str(uploads),
        workspace_root=str(workspace),
    ) == [str(uploaded.resolve()), str(clip.resolve())]


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
        "adopt_audio",
    ):
        calls = [
            node.func.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "_resolve_request_media_path" in calls, name


def test_story_cover_jobs_use_the_shared_cover_resolver():
    story_music = ROOT / "app" / "routers" / "story_music.py"
    tree = ast.parse(story_music.read_text(encoding="utf-8"), filename=str(story_music))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in (
        "start_story_music_candidates_job",
        "generate_story_music_candidates",
    ):
        calls = [
            node.func.id
            for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "_story_cover_reference_path" in calls, name


def test_generation_resolves_voice_clone_refs_before_seedvc():
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    run = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_run_generation"
    )
    calls = [
        node.func.id
        for node in ast.walk(run)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "resolve_voice_ref_paths" in calls


def test_adopting_audio_is_confined_to_audio_the_uploader_would_not_transcode():
    """Adoption takes a file in place, so it may only accept what the rest of
    the pipeline can already open. The uploader transcodes mp3/m4a/aac to PCM
    WAV because the clip slicer reads with soundfile; nothing does that for an
    adopted file, so the endpoint asks the resolver for audio only."""
    tree = ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))
    adopt = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "adopt_audio"
    )
    resolver = next(
        node for node in ast.walk(adopt)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_resolve_request_media_path"
    )
    kinds = next(kw.value for kw in resolver.keywords if kw.arg == "kinds")
    assert [element.value for element in kinds.elts] == ["audio"]
