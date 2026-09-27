"""Bounded, local media links for the user's Activity reference previews."""

from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit


def _reference_url(value, workspace, uploads_dir, workspace_dir):
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    root = None
    if parsed.scheme or parsed.netloc:
        return None
    if parsed.path.startswith('/api/v1/uploads/'):
        root = Path(uploads_dir).resolve()
        path = root / unquote(parsed.path[len('/api/v1/uploads/'):])
    elif parsed.path.startswith('/api/v1/file/'):
        if parse_qs(parsed.query).get('workspace', [workspace])[0] != workspace:
            return None
        root = Path(workspace_dir).resolve()
        path = root / unquote(parsed.path[len('/api/v1/file/'):])
    elif Path(value).is_absolute():
        path = Path(value)
    else:
        # Legacy relative references need the same unambiguous lookup as a
        # submission. No image bytes are decoded or copied for this summary.
        from services.wangp_submission import resolve_wangp_media
        path = Path(resolve_wangp_media(value, workspace, uploads_dir=uploads_dir, workspace_dir=workspace_dir))
    if root is not None and not path.resolve().is_relative_to(root):
        return None
    if path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'}:
        return None
    from services.wangp_submission import wangp_media_url
    url = wangp_media_url(path, workspace, uploads_dir=uploads_dir, workspace_dir=workspace_dir)
    parsed = urlsplit(url)
    uploads = parsed.path.startswith('/api/v1/uploads/')
    filename = unquote(parsed.path.split('/api/v1/uploads/' if uploads else '/api/v1/file/', 1)[1])
    thumb_workspace = '__uploads__' if uploads else workspace
    thumbnail = f'/api/v1/outputs/thumbnail/{quote(filename, safe="")}?workspace={quote(thumb_workspace, safe="")}'
    return {'url': url, 'thumbnail_url': thumbnail, 'name': path.name}


def activity_reference_images(params, workspace, *, uploads_dir, workspace_dir):
    """Keep accepted reference order and identity; never publish disk paths."""
    references = []
    seen = set()
    for field in ('image_guide', 'image_start', 'image_refs', 'image_end'):
        values = params.get(field)
        for value in (values if isinstance(values, (list, tuple)) else [values])[:10]:
            try:
                item = _reference_url(value, workspace, uploads_dir, workspace_dir)
            except (ValueError, OSError):
                continue
            if item and item['url'] not in seen:
                references.append(item)
                seen.add(item['url'])
            if len(references) == 10:
                return references
    return references
