"""Files that travel with a gallery output: its metadata and its 3D card preview.

``<stem>.meta.json`` and ``<stem>.preview.png`` sit next to ``<stem>.<ext>`` in the workspace, and the gallery's move
(``output_ops.move_output``) carries them along with the media. The game-asset archive does the same, from this list.
"""
from __future__ import annotations

import os

SIDECAR_SUFFIXES = (".meta.json", ".preview.png")


def sidecar_names(name: str) -> list[str]:
    """The sidecar file names of ``name`` (``hero.png`` -> ``hero.meta.json``, ``hero.preview.png``)."""
    stem = os.path.splitext(name)[0]
    return [stem + suffix for suffix in SIDECAR_SUFFIXES]
