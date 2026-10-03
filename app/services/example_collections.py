"""Explicit, cancellable installs of independently hosted example archives."""
import hashlib
from http.client import HTTPException as HTTPClientError
import json
import os
from pathlib import Path
import tempfile
from threading import Event, Lock, Thread
from uuid import uuid4
import zipfile

from services.example_assets import ExampleAssets, ExampleUnavailable
from services.secure_download import DownloadCancelled, DownloadRefused, copy_verified, opener_for

# Release archives live on GitHub, which redirects to its asset storage hosts.
ARCHIVE_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
urlopen = opener_for(ARCHIVE_HOSTS)
_ARCHIVE_ERRORS = {'too_large': 'Archive exceeds its declared size', 'integrity': 'Archive failed integrity verification'}

__all__ = ['ARCHIVE_HOSTS', 'CollectionDownloads', 'DownloadCancelled', 'install_collection']


def _download_archive(url: str, archive: Path, pack: dict, cancelled, progress, opener) -> None:
    try:
        with (opener or urlopen)(url, timeout=30) as response, archive.open('wb') as output:
            copy_verified(response, output, size=pack['archive']['size'], sha256=pack['archive']['sha256'],
                          cancelled=cancelled, progress=progress)
    except DownloadRefused as refused:
        if refused.code in _ARCHIVE_ERRORS:
            raise ExampleUnavailable(_ARCHIVE_ERRORS[refused.code]) from refused
        raise


def install_collection(assets: ExampleAssets, collection: str, cancelled, progress, opener=None):
    """``opener`` defaults to the module's ``urlopen`` (GitHub release hosts only)."""
    pack = assets.collections[collection]
    if assets.installed(collection):
        return
    assets.cache.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='.install-', dir=assets.cache) as directory:
            staging = Path(directory)
            archive = staging / 'download.zip'
            _download_archive(pack['archive']['url'], archive, pack, cancelled, progress, opener)
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
                if len(names) != len(set(names)) or set(names) != set(pack['files']):
                    raise ExampleUnavailable('Archive contains unexpected files')
                for name in names:
                    if cancelled():
                        raise DownloadCancelled()
                    entry = assets.entry(name)
                    if bundle.getinfo(name).file_size != entry['size']:
                        raise ExampleUnavailable('Example size does not match the catalog')
                    # Never extract archive paths. Publish only content-addressed files.
                    target = staging / assets._target(name).name
                    size, digest = 0, hashlib.sha256()
                    with bundle.open(name) as source, target.open('wb') as output:
                        while chunk := source.read(1024 * 1024):
                            if cancelled():
                                raise DownloadCancelled()
                            size += len(chunk)
                            if size > entry['size']:
                                raise ExampleUnavailable('Example exceeds its declared size')
                            digest.update(chunk)
                            output.write(chunk)
                    if size != entry['size'] or digest.hexdigest() != entry['sha256']:
                        raise ExampleUnavailable('Example failed integrity verification')
            if cancelled():
                raise DownloadCancelled()
            # All content is validated before publishing. Identical resources may be shared.
            for name in {assets._target(n).name for n in names}:
                os.replace(staging / name, assets.cache / name)
            receipt = staging / 'receipt.json'
            receipt.write_text(json.dumps({'sha256': pack['archive']['sha256']}))
            os.replace(receipt, assets.cache / (collection + '.installed.json'))
    except (OSError, ValueError, HTTPClientError, zipfile.BadZipFile, RuntimeError) as error:
        raise ExampleUnavailable('Collection download failed. Check your connection and retry.') from error


class CollectionDownloads:
    def __init__(self, assets: ExampleAssets, opener=None, busy_message: str = 'Another example download is already running'):
        self.assets = assets
        self.opener = opener
        self.busy_message = busy_message
        self.lock = Lock()
        self.cancelled = Event()
        self.job = None

    def catalog(self):
        installed = {name: self.assets.installed(name) for name in self.assets.collections}
        collections = []
        for name, pack in self.assets.collections.items():
            required = self.assets.closure([name])
            collections.append({'id': name, 'size': sum(self.assets.collections[n]['size'] for n in required),
                                'download_size': sum(self.assets.collections[n]['archive']['size'] for n in required if not installed[n]),
                                'installed': all(installed[n] for n in required), 'cached': installed[name],
                                'archive_size': pack['archive']['size'], 'gallery': name + '/index.html' in self.assets.files,
                                'dependencies': required})
        with self.lock:
            job = dict(self.job) if self.job else None
        return {'collections': collections, 'job': job}

    def start(self, collections: list[str]):
        required = self.assets.closure(collections)
        pending = [name for name in required if not self.assets.installed(name)]
        with self.lock:
            if self.job and self.job['status'] == 'running':
                raise RuntimeError(self.busy_message)
            self.cancelled = Event()
            self.job = {'id': uuid4().hex, 'collections': required, 'status': 'running', 'received': 0,
                        'total': sum(self.assets.collections[n]['archive']['size'] for n in pending), 'error': None}
            result = dict(self.job)
        Thread(target=self._run, args=(pending, self.cancelled), daemon=True).start()
        return result

    def cancel(self, job_id: str):
        with self.lock:
            if not self.job or self.job['id'] != job_id:
                raise KeyError(job_id)
            self.cancelled.set()

    def _run(self, pending, cancelled):
        def progress(count):
            with self.lock:
                self.job['received'] += count
        status, error = 'complete', None
        try:
            for name in pending:
                if cancelled.is_set():
                    raise DownloadCancelled()
                install_collection(self.assets, name, cancelled.is_set, progress, self.opener)
            if cancelled.is_set():
                raise DownloadCancelled()
        except DownloadCancelled:
            status = 'cancelled'
        except Exception as cause:
            status, error = 'failed', str(cause)
        with self.lock:
            self.job.update(status=status, error=error)
