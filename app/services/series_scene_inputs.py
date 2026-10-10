"""Content identity of mutable 3D scene sources used by a Series shot."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable


def audio_content(root: str | None, filenames: Iterable[str]) -> dict[str, str]:
    """Identify the bytes behind recording aliases, which a voice retake replaces in place."""
    from services.audio_mix import track_source
    from services.series_shot_foley import file_digest

    if root is None:
        return {}
    content = {}
    for filename in sorted(set(filenames)):
        path = track_source(root, filename)
        try:
            content[filename] = file_digest(str(path)) if path else "unavailable"
        except OSError:
            content[filename] = "unavailable"
    return content


def document_digest(document: dict) -> str:
    """JSON formatting and key order do not change the source a shot renders."""
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def scene_source_digest(config: dict, root: str | None) -> str | None:
    """Fingerprint a saved scene or personal template; built-ins retain their existing identity.

    Missing or unreadable sources invalidate an earlier usable take. The render's normal validation explains the
    source error; checking which shots changed must not silently reuse that earlier take or crash an episode listing.
    """
    if root is None:
        return None
    from services.scene_documents import get_document
    from services.world3d_template_catalog import user_template_document

    try:
        if config.get("scene"):
            document = get_document("default", config["scene"], workspace_dir=lambda _: root)["document"]
        elif str(config.get("template") or "").startswith("user-"):
            document = user_template_document(config["template"], lambda _: root, "default")
        else:
            return None
        return document_digest(document)
    except (OSError, ValueError):
        return "unavailable"
