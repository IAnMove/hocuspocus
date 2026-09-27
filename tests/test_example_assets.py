import hashlib
import io
import json
from pathlib import Path
import time
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.example_assets import create_example_assets_router
from services import example_assets as module
from services import example_collections as downloads

CONTENT = b'optional video bytes'


def store(tmp_path, content=CONTENT, extra=None):
    data = {'demo/video.mp4': content}
    if extra:
        data.update(extra)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, value in data.items():
            bundle.writestr(name, value)
    payload = archive.getvalue()
    files = {name: {'size': len(value), 'sha256': hashlib.sha256(value).hexdigest(), 'collection': 'demo'} for name, value in data.items()}
    manifest = {'revision': 'a' * 40, 'files': files, 'collections': {
        'demo': {'files': list(files), 'dependencies': [], 'size': sum(len(v) for v in data.values()),
                 'archive': {'url': 'https://example.invalid/demo.zip', 'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}}}}
    return module.ExampleAssets(tmp_path / 'cache', manifest), payload


def client(assets):
    app = FastAPI()
    app.include_router(create_example_assets_router(assets))
    return TestClient(app)


def wait_job(http):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = http.get('/api/v1/examples').json()
        if result['job']['status'] != 'running':
            return result
        time.sleep(.01)
    pytest.fail('download did not settle')


def test_startup_catalog_head_and_get_never_download(tmp_path, monkeypatch):
    monkeypatch.setattr(downloads, 'urlopen', lambda *a, **k: pytest.fail('unexpected network'))
    assets, _ = store(tmp_path)
    with client(assets) as http:
        assert http.get('/api/v1/examples').json()['collections'][0]['installed'] is False
        assert http.head('/examples/demo/video.mp4').status_code == 200
        assert http.get('/examples/demo/video.mp4').status_code == 409
        for path in ['missing.mp4', '..%2fprivate.txt', 'https:%2f%2fexample.com/file', 'demo%5cvideo.mp4']:
            assert http.get('/examples/' + path).status_code == 404
        assert http.post('/api/v1/examples/install', json={'collections': ['demo']}).status_code == 403
        assert http.post('/api/v1/examples/install', json={'collections': ['unknown']}, headers={'X-Hocus-Action': 'install-examples'}).status_code == 422
    assert not assets.cache.exists()


def test_explicit_install_preserves_urls_offline_and_video_ranges(tmp_path, monkeypatch):
    assets, payload = store(tmp_path)
    calls = []
    def download(url, timeout):
        calls.append(url)
        return io.BytesIO(payload)
    monkeypatch.setattr(downloads, 'urlopen', download)
    with client(assets) as http:
        assert http.post('/api/v1/examples/install', json={'collections': ['demo']}, headers={'X-Hocus-Action': 'install-examples'}).status_code == 202
        result = wait_job(http)
        assert result['job']['status'] == 'complete'
        assert result['collections'][0]['installed'] is True
        assert result['collections'][0]['download_size'] == 0
        assert len(calls) == 1
        monkeypatch.setattr(downloads, 'urlopen', lambda *a, **k: pytest.fail('cache must work offline'))
        assert http.get('/examples/demo/video.mp4').content == CONTENT
        response = http.get('/examples/demo/video.mp4', headers={'Range': 'bytes=0-7'})
        assert response.status_code == 206 and response.content == CONTENT[:8]
    assert module.ExampleAssets(assets.cache, {'revision': assets.revision, 'files': assets.files}).resolve('demo/video.mp4').read_bytes() == CONTENT


@pytest.mark.parametrize('received', [b'short', b'x' * 200, b'extra' * 1000])
def test_invalid_archive_is_never_published_and_can_be_retried(tmp_path, monkeypatch, received):
    assets, payload = store(tmp_path)
    monkeypatch.setattr(downloads, 'urlopen', lambda *a, **k: io.BytesIO(received))
    with pytest.raises(module.ExampleUnavailable):
        downloads.install_collection(assets, 'demo', lambda: False, lambda n: None)
    assert not assets.installed('demo')
    assert list(assets.cache.iterdir()) == []
    monkeypatch.setattr(downloads, 'urlopen', lambda *a, **k: io.BytesIO(payload))
    downloads.install_collection(assets, 'demo', lambda: False, lambda n: None)
    assert assets.installed('demo')


def test_content_hash_and_archive_paths_are_verified_before_publish(tmp_path, monkeypatch):
    assets, payload = store(tmp_path, extra={'demo/index.html': b'gallery'})
    assets.files['demo/video.mp4']['sha256'] = 'b' * 64
    monkeypatch.setattr(downloads, 'urlopen', lambda *a, **k: io.BytesIO(payload))
    with pytest.raises(module.ExampleUnavailable):
        downloads.install_collection(assets, 'demo', lambda: False, lambda n: None)
    assert list(assets.cache.iterdir()) == []
    assets.collections['demo']['files'] = ['../private.txt']
    with pytest.raises(module.ExampleUnavailable):
        downloads.install_collection(assets, 'demo', lambda: False, lambda n: None)
    assert not (tmp_path / 'private.txt').exists()


def test_cancel_cleans_partial_downloads_and_retry_succeeds(tmp_path, monkeypatch):
    assets, payload = store(tmp_path)
    monkeypatch.setattr(downloads, 'urlopen', lambda *a, **k: io.BytesIO(payload))
    with pytest.raises(downloads.DownloadCancelled):
        downloads.install_collection(assets, 'demo', lambda: True, lambda n: None)
    assert not assets.installed('demo') and list(assets.cache.iterdir()) == []
    downloads.install_collection(assets, 'demo', lambda: False, lambda n: None)
    assert assets.installed('demo')


def test_corrupted_cached_file_is_not_served(tmp_path):
    assets, _ = store(tmp_path)
    target = assets._target('demo/video.mp4')
    target.parent.mkdir()
    target.write_bytes(CONTENT)
    assert assets.cached('demo/video.mp4') == target
    target.write_bytes(b'x' * len(CONTENT))
    with pytest.raises(module.ExampleUnavailable):
        assets.resolve('demo/video.mp4')


def test_dependency_closure_handles_cycles_and_shared_packs(tmp_path):
    assets, _ = store(tmp_path)
    assets.collections['demo']['dependencies'] = ['common']
    assets.collections['common'] = {**assets.collections['demo'], 'dependencies': ['demo']}
    assert assets.closure(['demo', 'common']) == ['common', 'demo']


def test_gallery_redirect_and_offline_serving(tmp_path, monkeypatch):
    assets, payload = store(tmp_path, extra={'demo/index.html': b'<html>gallery</html>'})
    monkeypatch.setattr(downloads, 'urlopen', lambda *a, **k: io.BytesIO(payload))
    downloads.install_collection(assets, 'demo', lambda: False, lambda n: None)
    with client(assets) as http:
        response = http.get('/examples/demo', follow_redirects=False)
        assert response.status_code == 307 and response.headers['location'] == '/examples/demo/'
        assert http.get('/examples/demo/').content == b'<html>gallery</html>'


def test_manifest_covers_each_file_once_and_media_is_not_bundled():
    assets = module.example_assets
    names = [n for pack in assets.collections.values() for n in pack['files']]
    assert len(names) == len(set(names)) and set(names) == set(assets.files)
    for name, pack in assets.collections.items():
        assert set(pack['dependencies']) <= set(assets.collections)
        assert pack['archive']['url'].startswith('https://github.com/IAnMove/hocuspocus/releases/download/example-assets-v1/')
        assert len(pack['archive']['sha256']) == 64
    assert not (module.APP_ROOT.parent / 'ui/public/examples').exists()


def test_corrupted_install_is_offered_again_and_repaired(tmp_path, monkeypatch):
    assets, payload = store(tmp_path)
    monkeypatch.setattr(downloads, 'urlopen', lambda *a, **k: io.BytesIO(payload))
    downloads.install_collection(assets, 'demo', lambda: False, lambda n: None)
    assert assets.installed('demo')
    assets._target('demo/video.mp4').write_bytes(b'x' * len(CONTENT))
    assert not assets.installed('demo')
    downloads.install_collection(assets, 'demo', lambda: False, lambda n: None)
    assert assets.installed('demo')


def test_api_cancel_conflict_and_offline_failure(tmp_path, monkeypatch):
    from threading import Event
    assets, payload = store(tmp_path)
    entered, release = Event(), Event()
    def download(*a, **k):
        entered.set()
        assert release.wait(5)
        return io.BytesIO(payload)
    monkeypatch.setattr(downloads, 'urlopen', download)
    headers = {'X-Hocus-Action': 'install-examples'}
    with client(assets) as http:
        job = http.post('/api/v1/examples/install', json={'collections': ['demo']}, headers=headers).json()
        try:
            assert entered.wait(5)
            assert http.post('/api/v1/examples/install', json={'collections': ['demo']}, headers=headers).status_code == 409
            assert http.delete('/api/v1/examples/install/' + job['id']).status_code == 403
            assert http.delete('/api/v1/examples/install/unknown', headers=headers).status_code == 404
            assert http.delete('/api/v1/examples/install/' + job['id'], headers=headers).status_code == 200
        finally:
            release.set()
        assert wait_job(http)['job']['status'] == 'cancelled'
        assert not assets.installed('demo')
        def offline(*a, **k):
            raise OSError('offline')
        monkeypatch.setattr(downloads, 'urlopen', offline)
        http.post('/api/v1/examples/install', json={'collections': ['demo']}, headers=headers)
        result = wait_job(http)
        assert result['job']['status'] == 'failed'
        assert result['job']['error']
        assert not assets.installed('demo')
