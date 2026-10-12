"""A saved export URL either serves its original bytes or reports the version unavailable."""
import hashlib

from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.win_safe_files import share_delete_file_response


def _client(path):
    api = FastAPI()

    @api.get('/clip.mp4')
    def download(sha256: str | None = None):
        return share_delete_file_response(str(path), expected_sha256=sha256)

    return TestClient(api)


def test_saved_export_url_rejects_replaced_alias_and_preserves_ranges(tmp_path):
    path = tmp_path / 'clip.mp4'
    path.write_bytes(b'original video')
    url = '/clip.mp4?sha256=' + hashlib.sha256(path.read_bytes()).hexdigest()
    client = _client(path)
    assert client.get(url).content == b'original video'
    ranged = client.get(url, headers={'Range': 'bytes=2-5'})
    assert ranged.status_code == 206 and ranged.content == b'igin'
    path.write_bytes(b'new version')
    stale = client.get(url)
    assert stale.status_code == 410 and b'new version' not in stale.content
    assert client.get('/clip.mp4').content == b'new version'


def test_replacement_after_verification_streams_the_verified_open_inode(tmp_path, monkeypatch):
    from services.win_safe_files import ShareDeleteFileResponse
    path = tmp_path / 'clip.mp4'
    path.write_bytes(b'original video')
    verify = ShareDeleteFileResponse._matches_content

    def replace_after_hash(self, handle):
        matched = verify(self, handle)
        replacement = path.with_suffix('.new')
        replacement.write_bytes(b'new version')
        replacement.replace(path)
        return matched

    monkeypatch.setattr(ShareDeleteFileResponse, '_matches_content', replace_after_hash)
    url = '/clip.mp4?sha256=' + hashlib.sha256(path.read_bytes()).hexdigest()
    assert _client(path).get(url).content == b'original video'
    assert path.read_bytes() == b'new version'


def test_core_file_endpoint_enforces_expected_export_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import core_runtime
    from pathlib import Path
    folder = Path(core_runtime.core.workspace_dir('show'))
    (folder / 'clip.mp4').write_bytes(b'original video')
    client = TestClient(core_runtime.api)
    good = hashlib.sha256(b'original video').hexdigest()
    assert client.get(f'/api/v1/file/clip.mp4?workspace=show&sha256={good}').content == b'original video'
    (folder / 'clip.mp4').write_bytes(b'new version')
    assert client.get(f'/api/v1/file/clip.mp4?workspace=show&sha256={good}').status_code == 410
