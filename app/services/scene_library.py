"""Immutable native Video3D revisions in the existing workspace gallery."""
from __future__ import annotations

import base64
import json
import re
import uuid
from pathlib import Path
from urllib.parse import quote

from services.document_origin import write_document_origin
from services.scene_commands import DocumentInput


def preview_png(preview):
    if not isinstance(preview, str) or not preview.startswith('data:image/png;base64,'):
        raise ValueError('A PNG preview is required')
    try:
        png = base64.b64decode(preview.split(',', 1)[1], validate=True)
    except ValueError as exc:
        raise ValueError('Invalid PNG preview') from exc
    if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 8 * 1024 * 1024:
        raise ValueError('Use a PNG preview under 8 MB')
    return png


def save_world3d(body, workspace_dir, *, capability='scenes.world3d.save'):
    workspace = body.get('workspace')
    if not isinstance(workspace, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,119}', workspace):
        raise ValueError('Choose an explicit workspace')
    document = DocumentInput(document=body.get('document')).document
    if 'slots' not in document:
        raise ValueError('Choose a Video3D scene')
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2)
    if re.search(r'"(?:blob:|file:)', encoded):
        raise ValueError('Upload local scene resources before saving')
    name = str(body.get('name') or document.get('templateId') or 'Scene')[:120]
    png = preview_png(body.get('preview', ''))
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-._')[:80] or 'Scene'
    stem += '-' + uuid.uuid4().hex + '.world3d.scene'
    folder = Path(workspace_dir(workspace))
    folder.mkdir(parents=True, exist_ok=True)
    source, thumbnail = folder / (stem + '.json'), folder / (stem + '.preview.png')
    temporary = folder / (stem + '.json.tmp')
    # Publish the preview first; a listed JSON always has its matching preview.
    written = []
    try:
        for path, data in ((thumbnail, png), (temporary, encoded.encode())):
            with path.open('xb') as handle:
                written.append(path)
                handle.write(data)
        temporary.replace(source)
    except OSError:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    # An export of this document will name this file and may give it a real preview (scene_links).
    from services.scene_links import remember_saved
    remember_saved(folder, document, source.name)
    write_document_origin(source, capability)
    suffix = '?workspace=' + quote(workspace, safe='')
    return {'name': source.name, 'type': 'scene', 'workspace_id': workspace,
            'url': '/api/v1/file/' + quote(source.name) + suffix,
            'thumbnail_url': '/api/v1/file/' + quote(thumbnail.name) + suffix}
