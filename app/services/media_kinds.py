"""Kinds and extensions of the asset library, declared once.

The asset library (``services.asset_library``) installs files of these kinds,
and the asset manifest records them. Older modules still keep their own sets,
and those sets differ on purpose or by history; this module does not change
what any of them accepts:

- ``core_workspace``: audio ``.wav .mp3``; models ``.glb .gltf .obj .ply .stl .usdz .zip``.
- ``media_paths``: ten audio extensions; models ``.glb`` only.
- ``asset_catalog.MEDIA_EXTENSIONS``: the workspace listing (no ``.hdr``, ``.exr``, ``.cube`` or ``.bvh``).
"""
from __future__ import annotations

from pathlib import PurePosixPath

LIBRARY_KIND_EXTENSIONS: dict[str, frozenset[str]] = {
    "hdri": frozenset({".hdr", ".exr"}),
    "material": frozenset({".png", ".jpg", ".jpeg", ".webp", ".exr", ".json"}),
    "lut": frozenset({".cube"}),
    "animation": frozenset({".glb", ".bvh"}),
    "sfx": frozenset({".wav", ".ogg", ".flac", ".mp3"}),
    "model3d": frozenset({".glb", ".gltf"}),
}
LIBRARY_KINDS = frozenset(LIBRARY_KIND_EXTENSIONS)

# Kinds added to the asset manifest for library files; the rest keep their old kind.
MANIFEST_KINDS = frozenset({"hdri", "material", "lut"})
MANIFEST_KIND_BY_EXTENSION = {".hdr": "hdri", ".exr": "hdri", ".cube": "lut"}

MEDIA_TYPES = {
    ".hdr": "image/vnd.radiance",
    ".exr": "image/x-exr",
    ".cube": "text/plain; charset=utf-8",
    ".bvh": "text/plain; charset=utf-8",
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
}


def library_kind_accepts(kind: str, name: str) -> bool:
    """Whether a library file named ``name`` may be of ``kind``."""
    return PurePosixPath(name).suffix.casefold() in LIBRARY_KIND_EXTENSIONS.get(kind, frozenset())


__all__ = [
    "LIBRARY_KINDS", "LIBRARY_KIND_EXTENSIONS", "MANIFEST_KINDS", "MANIFEST_KIND_BY_EXTENSION", "MEDIA_TYPES",
    "library_kind_accepts",
]
