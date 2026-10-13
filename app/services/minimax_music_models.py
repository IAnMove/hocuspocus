"""MiniMax API music model ids. Every one of them is a paid provider call.

No third-party imports: the music contract, ``production.*`` and ``media.options``
read these ids without loading the HTTP client in ``minimax_music_service``.
"""
from __future__ import annotations

ORIGINAL_MODELS = frozenset({"music-3.0", "music-2.6", "music-3.0-free", "music-2.6-free"})
COVER_MODELS = frozenset({"music-cover", "music-cover-free"})
ALLOWED_MODELS = ORIGINAL_MODELS | COVER_MODELS
