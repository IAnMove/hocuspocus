import ast
import asyncio
import os
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi import HTTPException

from app.services.character_kit_library import patch_character_kit, read_character_kit_library
from app.services.character_speech_definition import normalize_character_voice
from app.services.media_paths import MediaPathNotAllowed, resolve_permitted_media_path


def voice():
    return {"provider": "local", "model": "qwen3_tts_base", "voiceId": "reference", "name": "Narradora",
            "referenceAudio": "/api/v1/uploads/audio/recording.wav", "transcript": "Esta es mi voz.", "language": "spanish"}


def test_reference_voice_survives_library_reload_and_links_from_another_workspace(tmp_path):
    custom = voice()
    custom["referenceAudio"] = "/api/v1/file/assets/voice.wav?workspace=original"
    kit = {"version": 1, "id": "narrator", "name": "Narrator", "style": "cutout", "poses": {},
           "mouth": {}, "eyes": {}, "anchors": {}, "provenance": [], "voice": custom}
    for workspace in ("original", "episode"):
        patch_character_kit(str(tmp_path / workspace), "narrator", kit, base_revision=0)
        assert read_character_kit_library(str(tmp_path / workspace))["kits"]["narrator"]["voice"] == custom
    assert normalize_character_voice({**custom, "name": "  Narradora  ", "transcript": "  Esta es mi voz.  "}) == custom
    preset = {"provider": "local", "model": "qwen3_tts_customvoice", "voiceId": "ryan", "instructions": "Warm"}
    assert normalize_character_voice(preset) == preset


@pytest.mark.parametrize("patch", [
    {"name": ""}, {"name": " "}, {"name": "a" * 121}, {"name": 12}, {"transcript": ""}, {"transcript": "\n"},
    {"transcript": "a" * 4001}, {"transcript": None}, {"referenceAudio": ""}, {"language": "martian"},
    {"language": []}, {"voiceId": "ryan"}, {"provider": "remote"}, {"apiKey": "not-a-secret"}, {"instructions": "unsupported"},
])
def test_incomplete_or_unsupported_reference_voice_is_rejected(patch):
    with pytest.raises(ValueError):
        normalize_character_voice({**voice(), **patch})


@pytest.mark.parametrize("key", list(voice()))
def test_every_reference_voice_field_is_required(key):
    incomplete = voice()
    del incomplete[key]
    with pytest.raises(ValueError):
        normalize_character_voice(incomplete)


@pytest.mark.parametrize("reference", [
    "https://example.com/voice.wav", "//example.com/voice.wav", "blob:voice", "data:audio/wav;base64,AAAA",
    "/home/private.wav", "/api/v1/uploads/../voice.wav", "/api/v1/uploads/%2e%2e/voice.wav",
    "/api/v1/uploads/%252e%252e/voice.wav", "/api/v1/uploads/audio%5cvoice.wav", "/api/v1/uploads/.private/voice.wav",
    "/api/v1/uploads/voice.wav?token=example", "/api/v1/uploads/voice.wav#fragment", "/api/v1/uploads/voice.wav?",
    "/api/v1/uploads/voice.webm",
    "/api/v1/uploads/voice%00.wav", "/api/v1/uploads/%ZZ.wav", "/api/v1/uploads/voice.json",
    "/api/v1/uploads/voice wav.wav", "/api/v1/uploads//voice.wav", "/api/v1/file/voice.wav",
    "/api/v1/file/voice.wav?workspace=", "/api/v1/file/voice.wav?workspace=..",
    "/api/v1/file/voice.wav?workspace=one&workspace=two", "/api/v1/file/voice.wav?workspace=one&key=example",
    "/api/v1/file/voice.wav?workspace=%ZZ", "/api/v1/file/voice.wav?workspace=%FF",
])
def test_remote_unsafe_or_ambiguous_reference_is_rejected(reference):
    with pytest.raises(ValueError):
        normalize_character_voice({**voice(), "referenceAudio": reference})


@pytest.fixture
def media_roots(tmp_path):
    uploads, workspace = tmp_path / "uploads", tmp_path / "episode"
    uploads.mkdir()
    workspace.mkdir()
    return uploads, workspace


def resolve(reference, roots, workspace_name="original"):
    return resolve_permitted_media_path(reference, uploads_root=str(roots[0]), workspace_root=str(roots[1]),
                                        workspace_name=workspace_name, kinds=("audio",))


def test_canonical_media_adoption_keeps_the_exact_root_even_with_colliding_names(media_roots):
    uploads, workspace = media_roots
    for root in media_roots:
        (root / "same.wav").write_bytes(b"reference")
    assert resolve("/api/v1/uploads/same.wav", media_roots) == str(uploads / "same.wav")
    assert resolve("/api/v1/file/same.wav?workspace=original", media_roots) == str(workspace / "same.wav")
    (workspace / "same.wav").unlink()
    with pytest.raises(FileNotFoundError):
        resolve("/api/v1/file/same.wav?workspace=original", media_roots)
    (workspace / "nested").mkdir()
    (workspace / "nested" / "mi voz.wav").write_bytes(b"reference")
    assert resolve("/api/v1/file/nested%2Fmi%20voz.wav?workspace=original", media_roots) == str(workspace / "nested" / "mi voz.wav")


@pytest.mark.parametrize("reference", [
    "/api/v1/file/same.wav?workspace=wrong", "/api/v1/file/same.wav",
    "/api/v1/file/same.wav?workspace=original&workspace=wrong", "/api/v1/file/same.wav?workspace=original&token=example",
    "/api/v1/uploads/same.wav?token=example", "/api/v1/uploads/../episode/same.wav",
    "/api/v1/uploads/%2e%2e/episode/same.wav", "/api/v1/file/%2e%2e/uploads/same.wav?workspace=original",
    "/api/v1/uploads/audio%5csame.wav", "/api/v1/uploads/same%00.wav", "/api/v1/uploads/%ZZ.wav",
    "/api/v1/uploads/same.wav#ignored", "/api/v1/uploads//same.wav",
])
def test_canonical_adoption_rejects_wrong_workspaces_and_traversal(media_roots, reference):
    for root in media_roots:
        (root / "same.wav").write_bytes(b"reference")
    with pytest.raises(MediaPathNotAllowed):
        resolve(reference, media_roots)


def test_canonical_adoption_does_not_follow_a_symlink_into_another_allowed_root(media_roots):
    uploads, workspace = media_roots
    (uploads / "same.wav").write_bytes(b"reference")
    try:
        (workspace / "same.wav").symlink_to(uploads / "same.wav")
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks unavailable")
    with pytest.raises(MediaPathNotAllowed):
        resolve("/api/v1/file/same.wav?workspace=original", media_roots)


def test_legacy_adoption_remains_available_for_existing_audio_studio_callers(media_roots):
    uploads, _ = media_roots
    (uploads / "same.wav").write_bytes(b"reference")
    assert resolve("same.wav", media_roots) == str(uploads / "same.wav")
    assert resolve(str(uploads / "same.wav"), media_roots) == str(uploads / "same.wav")


def test_audio_adopt_endpoint_uses_source_workspace_and_new_canonical_resolver(media_roots, monkeypatch):
    """Execute the actual lightweight route functions without importing GPU runtimes."""
    uploads, workspace = media_roots
    monkeypatch.chdir(uploads.parent)
    for root in media_roots:
        (root / "same.wav").write_bytes(b"reference")
    launch = Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py"
    parsed = ast.parse(launch.read_text(encoding="utf-8"))
    selected = [node for node in parsed.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in {"_resolve_request_media_path", "adopt_audio"}]
    for node in selected:
        node.decorator_list = []
    seen_workspaces = []

    def workspace_dir(name):
        seen_workspaces.append(name)
        return str(workspace)

    namespace = {"os": os, "quote": quote, "Request": object, "HTTPException": HTTPException,
                 "resolve_permitted_media_path": resolve_permitted_media_path, "MediaPathNotAllowed": MediaPathNotAllowed,
                 "_workspace_dir": workspace_dir, "_get_active_workspace": lambda: "destination",
                 "_probe_audio_duration": lambda _: 5}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(launch), "exec"), namespace)

    class Request:
        async def json(self):
            return {"audio_path": "/api/v1/file/same.wav?workspace=original", "workspace": "original"}

    result = asyncio.run(namespace["adopt_audio"](Request()))
    assert seen_workspaces == ["original"]
    assert result["path"] == str(workspace / "same.wav")
    assert result["duration_seconds"] == 5
    assert result["url"].endswith("?workspace=original")
