"""assets.upload returns a canonical URL without POST /api/v1/upload."""

from __future__ import annotations

import asyncio
import base64
import struct
import zlib
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.asset_catalog import find_asset
from services.assets_upload import MAX_ASSETS_UPLOAD_BYTES, command_catalog, command_handlers
from services.studio_image_resources import StudioImageResources
from services.studio_image_spec import _validate_reference
from services.studio_speech_resources import StudioSpeechResources


def tiny_png() -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b"")


def _layout(tmp_path: Path):
    workspace = tmp_path / "outputs" / "clip"
    uploads = tmp_path / "uploads"
    workspace.mkdir(parents=True)
    uploads.mkdir()

    def workspace_dir(name: str) -> str:
        if name != "clip":
            raise ValueError("invalid workspace")
        return str(workspace)

    def uploads_dir() -> str:
        return str(uploads)

    return command_handlers(workspace_dir, uploads_dir), workspace, uploads


def _request(intent_id: str, payload: dict) -> dict:
    return {"version": 1, "intent_id": intent_id, "input": payload}


def _call(handlers, intent_id: str, payload: dict) -> dict:
    return asyncio.run(handlers["assets.upload"](_request(intent_id, payload)))


def _resources(workspace: Path, uploads: Path):
    def workspace_dir(name: str) -> str:
        if name != "clip":
            raise ValueError(name)
        return str(workspace)

    def list_workspaces():
        return [{"name": "clip"}]

    common = dict(
        workspace_dir=workspace_dir,
        uploads_dir=lambda: str(uploads),
        list_workspaces=list_workspaces,
        lora_search_dirs=lambda _model: [],
        lora_compatible=lambda *_args, **_kwargs: True,
    )
    return StudioImageResources(**common), StudioSpeechResources(**common)


def test_round_trip_tiny_png_url_is_accepted_by_image_and_audio_fields(tmp_path):
    handlers, workspace, uploads = _layout(tmp_path)
    png = tiny_png()
    encoded = base64.b64encode(png).decode("ascii")
    first = _call(handlers, "intent-png", {"workspace": "clip", "filename": "dot.png", "data_base64": encoded})
    again = _call(handlers, "intent-png", {"workspace": "clip", "filename": "dot.png", "data_base64": encoded})

    assert first["status"] == "completed"
    assert first["operation"] == "assets.upload"
    assert again["result"] == first["result"]
    result = first["result"]
    assert set(result) == {"asset_id", "url"}
    assert result["url"].startswith("/api/v1/file/")
    assert "workspace=clip" in result["url"]
    assert _validate_reference(result["url"]) == result["url"]
    assert _validate_reference(result["asset_id"]) == result["asset_id"]
    assert list(workspace.glob("*.png")) and len(list(workspace.glob("*.png"))) == 1

    images, speech = _resources(workspace, uploads)
    prepared, _resources_found = images.prepare_media({
        "image_refs": [result["url"]],
        "image_start": result["url"],
        "image_end": result["url"],
    })
    assert Path(prepared["image_refs"][0]).read_bytes() == png
    assert Path(prepared["image_start"]).read_bytes() == png
    assert Path(prepared["image_end"]).read_bytes() == png
    # audio_guide uses the same canonical-URL gate and resolver as the image fields.
    audio_path, _origin = speech._media(result["url"])
    assert Path(audio_path).read_bytes() == png

    catalog = find_asset(
        [
            {"workspace_id": "clip", "path": str(workspace)},
            {"workspace_id": "__uploads__", "path": str(uploads)},
        ],
        result["asset_id"],
    )
    assert catalog is not None
    assert catalog["filename"] == Path(prepared["image_start"]).name
    assert list(uploads.iterdir()) == []


def test_existing_workspace_file_round_trips_without_a_copy(tmp_path):
    handlers, workspace, uploads = _layout(tmp_path)
    png = tiny_png()
    source = workspace / "already.png"
    source.write_bytes(png)
    result = _call(handlers, "intent-source", {"workspace": "clip", "source": str(source)})["result"]

    assert _validate_reference(result["url"]) == result["url"]
    images, speech = _resources(workspace, uploads)
    prepared, _found = images.prepare_media({
        "image_refs": [result["url"]],
        "image_start": result["url"],
        "image_end": result["url"],
    })
    assert Path(prepared["image_start"]).read_bytes() == png
    assert Path(speech._media(result["url"])[0]).read_bytes() == png
    assert sorted(path.name for path in workspace.glob("*.png")) == ["already.png"]


def test_glb_bytes_import_into_workspace_with_exact_model3d_ref_and_replay(tmp_path):
    from services.procedural_3d.compose import compose_glb
    from services.procedural_3d.glb_inspector import inspect_glb
    from services.world3d_export import _ref_from_url
    from services.media_paths import MediaPathNotAllowed, resolve_permitted_media_path

    handlers, workspace, uploads = _layout(tmp_path)
    glb = compose_glb([{"type": "box", "color": "#F08030"}], "Imported model")
    payload = {"workspace": "clip", "filename": "model.glb", "data_base64": base64.b64encode(glb).decode()}
    result = _call(handlers, "intent-model", payload)["result"]
    assert _call(handlers, "intent-model", payload)["result"] == result
    files = list(workspace.glob("*.glb"))
    assert len(files) == 1 and files[0].read_bytes() == glb
    assert inspect_glb(files[0]).status == "valid"
    ref = _ref_from_url({"id": "hero", "media": "model3d"}, result["url"], "clip")
    assert ref['filename'] == files[0].name and ref['workspace'] == 'clip'
    with pytest.raises(MediaPathNotAllowed):
        resolve_permitted_media_path(result['url'], uploads_root=str(uploads), workspace_root=str(workspace),
                                    workspace_name='clip', kinds=('image',))


def test_explicit_source_copy_preserves_upload_and_replays_one_workspace_import(tmp_path):
    handlers, workspace, uploads = _layout(tmp_path)
    source = uploads / 'accepted.wav'
    source.write_bytes(b'accepted original song bytes')
    payload = {"workspace": "clip", "source": str(source), "copy_to_workspace": True}
    result = _call(handlers, "copy-song", payload)['result']
    assert _call(handlers, "copy-song", payload)['result'] == result
    assert result['url'].startswith('/api/v1/file/') and result['url'].endswith('?workspace=clip')
    copies = list(workspace.glob('*.wav'))
    assert len(copies) == 1 and copies[0].read_bytes() == source.read_bytes()
    assert source.is_file()
    original = _call(handlers, "reference-song", {"workspace": "clip", "source": str(source)})['result']
    assert original['url'].startswith('/api/v1/uploads/')


def test_source_copy_rejects_escaped_path_and_oversized_file(tmp_path, monkeypatch):
    import services.assets_upload as module

    handlers, workspace, uploads = _layout(tmp_path)
    outside = tmp_path / 'outside.wav'; outside.write_bytes(b'original')
    with pytest.raises(HTTPException) as caught:
        _call(handlers, 'escape-copy', {"workspace": "clip", "source": str(outside), "copy_to_workspace": True})
    assert caught.value.detail['code'] == 'path_not_allowed'
    source = uploads / 'large.wav'; source.write_bytes(b'larger than the test limit')
    monkeypatch.setattr(module, 'MAX_UPLOAD_BYTES', 3)
    with pytest.raises(HTTPException) as caught:
        _call(handlers, 'large-copy', {"workspace": "clip", "source": str(source), "copy_to_workspace": True})
    assert caught.value.status_code == 413 and source.is_file()
    assert not list(workspace.glob('*.wav')) and not list(workspace.glob('*.tmp'))


def test_oversized_payload_is_rejected_with_a_stable_code(tmp_path):
    handlers, workspace, _uploads = _layout(tmp_path)
    payload = base64.b64encode(b"\x00" * (MAX_ASSETS_UPLOAD_BYTES + 1)).decode("ascii")
    with pytest.raises(HTTPException) as caught:
        _call(handlers, "intent-large", {"workspace": "clip", "filename": "big.png", "data_base64": payload})
    assert caught.value.status_code == 413
    assert caught.value.detail["code"] == "payload_too_large"
    assert list(workspace.glob("*.png")) == []


def test_path_that_escapes_the_workspace_is_rejected(tmp_path):
    handlers, workspace, _uploads = _layout(tmp_path)
    outside = tmp_path / "secret.png"
    outside.write_bytes(tiny_png())
    escaped = workspace / ".." / ".." / outside.name
    with pytest.raises(HTTPException) as caught:
        _call(handlers, "intent-escape", {"workspace": "clip", "source": str(escaped)})
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "path_not_allowed"
    assert list(workspace.glob("*.png")) == []


def test_catalog_publishes_versioned_upload_schema():
    operation = command_catalog()[0]
    assert operation["name"] == "assets.upload"
    assert operation["version"] == 1
    assert operation["mutation"] is True
    schema = operation["inputSchema"]
    assert schema["properties"]["version"]["const"] == 1
    assert schema["required"] == ["version", "intent_id", "input"]
    branches = schema["properties"]["input"]["oneOf"]
    assert {"workspace", "filename", "data_base64"} in {frozenset(branch["required"]) for branch in branches}
    assert {"workspace", "source"} in {frozenset(branch["required"]) for branch in branches}


def test_named_copy_keeps_quality_bytes_metadata_and_idempotent_receipt(tmp_path):
    import hashlib
    import json

    handlers, workspace, _ = _layout(tmp_path)
    source = workspace / 'song(2).wav'; source.write_bytes(b'quality stereo source')
    source.with_suffix('.meta.json').write_text(json.dumps({'asset': {'filename': source.name}, 'seed': 7}))
    target = workspace / 'song.wav'; target.write_bytes(b'old take')
    payload = {'workspace': 'clip', 'source': str(source), 'copy_to_workspace': True,
               'destination_filename': target.name,
               'expected_destination_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    result = _call(handlers, 'publish-quality', payload)['result']
    assert _call(handlers, 'publish-quality', payload)['result'] == result
    assert target.read_bytes() == source.read_bytes() == b'quality stereo source'
    assert result['url'] == '/api/v1/file/song.wav?workspace=clip'
    metadata = json.loads(target.with_suffix('.meta.json').read_text())
    assert metadata['seed'] == 7 and metadata['copied_from'] == source.name
    assert metadata['asset']['filename'] == target.name
    with pytest.raises(HTTPException) as caught:
        _call(handlers, 'stale-replace', payload)
    assert caught.value.status_code == 409
    assert target.read_bytes() == b'quality stereo source'


@pytest.mark.parametrize('destination,expected,code', [
    ('../escape.wav', None, 'invalid_filename'),
    ('wrong.png', None, 'invalid_filename'),
    ('song.wav', None, 'destination_conflict'),
    ('song.wav', 'invalid', 'invalid_command'),
    ('song.wav', '0' * 64, 'destination_conflict'),
])
def test_named_copy_rejects_unsafe_or_unreviewed_replacements(tmp_path, destination, expected, code):
    handlers, workspace, _ = _layout(tmp_path)
    source = workspace / 'new.wav'; source.write_bytes(b'new')
    target = workspace / 'song.wav'; target.write_bytes(b'old')
    payload = {'workspace': 'clip', 'source': str(source), 'copy_to_workspace': True,
               'destination_filename': destination}
    if expected is not None:
        payload['expected_destination_sha256'] = expected
    with pytest.raises(HTTPException) as caught:
        _call(handlers, 'invalid-copy', payload)
    assert caught.value.detail['code'] == code and target.read_bytes() == b'old'


def test_named_copy_rejects_bad_sidecar_before_publishing(tmp_path):
    handlers, workspace, _ = _layout(tmp_path)
    source = workspace / 'new.wav'; source.write_bytes(b'new')
    source.with_suffix('.meta.json').write_text('not JSON')
    with pytest.raises(HTTPException) as caught:
        _call(handlers, 'bad-sidecar', {'workspace': 'clip', 'source': str(source),
              'copy_to_workspace': True, 'destination_filename': 'song.wav'})
    assert caught.value.detail['code'] == 'invalid_sidecar'
    assert not (workspace / 'song.wav').exists()


@pytest.mark.parametrize('failure_point', ['sidecar', 'journal', 'sidecar_after', 'journal_after'])
@pytest.mark.parametrize('replace_existing', [False, True])
def test_named_copy_failure_restores_media_metadata_and_intent(tmp_path, monkeypatch, failure_point, replace_existing):
    import hashlib
    from services import assets_upload

    handlers, workspace, _ = _layout(tmp_path)
    source = workspace / 'new.wav'
    source.write_bytes(b'new song')
    source.with_suffix('.meta.json').write_text('{"asset":{"filename":"new.wav"},"seed":7}')
    target = workspace / 'song.wav'
    target_meta = target.with_suffix('.meta.json')
    if replace_existing:
        target.write_bytes(b'old song')
        target_meta.write_text('{"asset":{"filename":"song.wav"},"seed":1}')
        (workspace / assets_upload._JOURNAL_NAME).write_text('{}')
    before = {p.name: p.read_bytes() for p in workspace.iterdir() if p.is_file()}
    payload = {'workspace': 'clip', 'source': str(source), 'copy_to_workspace': True,
               'destination_filename': target.name}
    if replace_existing:
        payload['expected_destination_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    function = '_publish_sidecar' if failure_point.startswith('sidecar') else '_remember'
    original = getattr(assets_upload, function)

    def fail(*args, **kwargs):
        if failure_point.endswith('_after'):
            original(*args, **kwargs)
        raise OSError('publication failed')

    monkeypatch.setattr(assets_upload, function, fail)
    with pytest.raises(OSError, match='publication failed'):
        _call(handlers, 'publish-retry', payload)
    assert {p.name: p.read_bytes() for p in workspace.iterdir() if p.is_file() and not p.name.endswith('.lock')} == before
    monkeypatch.setattr(assets_upload, function, original)
    result = _call(handlers, 'publish-retry', payload)
    assert target.read_bytes() == b'new song'
    assert _call(handlers, 'publish-retry', payload) == result


def test_named_copy_creates_exact_name_and_requires_copy_flag(tmp_path):
    handlers, workspace, _ = _layout(tmp_path)
    source = workspace / 'new.wav'; source.write_bytes(b'new')
    payload = {'workspace': 'clip', 'source': str(source), 'destination_filename': 'song.wav'}
    with pytest.raises(HTTPException) as caught:
        _call(handlers, 'missing-copy-flag', payload)
    assert caught.value.detail['code'] == 'invalid_command'
    payload['copy_to_workspace'] = True
    _call(handlers, 'new-name', payload)
    assert (workspace / 'song.wav').read_bytes() == b'new'


def _sidecar(path: Path, owner: str | None, **fields) -> None:
    import json

    path.write_text(json.dumps({**({'asset': {'filename': owner}} if owner else {}), **fields}))


@pytest.mark.parametrize('source_sidecar', [False, True])
@pytest.mark.parametrize('recorded_owner', ['song.png', None])
def test_named_copy_never_overwrites_or_deletes_the_metadata_of_another_output_with_the_same_stem(
        tmp_path, source_sidecar, recorded_owner):
    # Sidecars are keyed by stem: song.wav would share song.meta.json with the cover song.png.
    handlers, workspace, _ = _layout(tmp_path)
    (workspace / 'song.png').write_bytes(tiny_png())
    cover_meta = workspace / 'song.meta.json'
    _sidecar(cover_meta, recorded_owner, seed=1)
    before = cover_meta.read_bytes()
    source = workspace / 'take.wav'; source.write_bytes(b'take')
    if source_sidecar:
        _sidecar(workspace / 'take.meta.json', 'take.wav', seed=7)
    with pytest.raises(HTTPException) as caught:
        _call(handlers, f'shared-stem-{source_sidecar}-{recorded_owner}', {
            'workspace': 'clip', 'source': str(source), 'copy_to_workspace': True, 'destination_filename': 'song.wav'})
    assert caught.value.status_code == 409 and caught.value.detail['code'] == 'sidecar_conflict'
    assert 'song.png' in caught.value.detail['message']
    assert cover_meta.read_bytes() == before and not (workspace / 'song.wav').exists()


def test_named_copy_does_not_adopt_a_sidecar_written_for_another_output(tmp_path):
    import json

    handlers, workspace, _ = _layout(tmp_path)
    (workspace / 'clip.mp4').write_bytes(b'video')
    video_meta = workspace / 'clip.meta.json'
    _sidecar(video_meta, 'clip.mp4', seed=3, prompt='a video')
    before = video_meta.read_bytes()
    source = workspace / 'clip.wav'; source.write_bytes(b'extracted audio')
    _call(handlers, 'foreign-sidecar', {'workspace': 'clip', 'source': str(source), 'copy_to_workspace': True,
                                        'destination_filename': 'voice.wav'})
    assert (workspace / 'voice.wav').read_bytes() == b'extracted audio'
    assert not (workspace / 'voice.meta.json').exists(), "the video's prompt and seed are not the audio's"
    assert video_meta.read_bytes() == before
    # A sidecar that names its own output is still carried over.
    _sidecar(video_meta, 'clip.wav', seed=4)
    (workspace / 'clip.mp4').unlink()
    _call(handlers, 'own-sidecar', {'workspace': 'clip', 'source': str(source), 'copy_to_workspace': True,
                                    'destination_filename': 'voice2.wav'})
    assert json.loads((workspace / 'voice2.meta.json').read_text())['seed'] == 4


def test_named_copy_replaces_a_sidecar_whose_output_is_gone(tmp_path):
    import json

    handlers, workspace, _ = _layout(tmp_path)
    _sidecar(workspace / 'song.meta.json', 'song.png', seed=1)  # song.png was deleted; its sidecar stayed
    source = workspace / 'take.wav'; source.write_bytes(b'take')
    _sidecar(workspace / 'take.meta.json', 'take.wav', seed=7)
    _call(handlers, 'orphan', {'workspace': 'clip', 'source': str(source), 'copy_to_workspace': True,
                               'destination_filename': 'song.wav'})
    metadata = json.loads((workspace / 'song.meta.json').read_text())
    assert metadata['seed'] == 7 and metadata['asset']['filename'] == 'song.wav'


def test_named_copy_does_not_create_a_sidecar_another_output_would_read_as_its_own(tmp_path):
    import hashlib

    handlers, workspace, _ = _layout(tmp_path)
    (workspace / 'song.png').write_bytes(tiny_png())  # a cover without metadata
    source = workspace / 'take.wav'; source.write_bytes(b'take')
    payload = {'workspace': 'clip', 'source': str(source), 'copy_to_workspace': True, 'destination_filename': 'song.wav'}
    _call(handlers, 'no-provenance', payload)
    assert (workspace / 'song.wav').read_bytes() == b'take' and not (workspace / 'song.meta.json').exists()
    # With provenance to write, song.meta.json would describe song.wav and be read as song.png's too.
    _sidecar(workspace / 'take.meta.json', 'take.wav', seed=7)
    payload['expected_destination_sha256'] = hashlib.sha256(b'take').hexdigest()
    with pytest.raises(HTTPException) as caught:
        _call(handlers, 'with-provenance', payload)
    assert caught.value.detail['code'] == 'sidecar_conflict' and 'song.png' in caught.value.detail['message']
    assert not (workspace / 'song.meta.json').exists()
