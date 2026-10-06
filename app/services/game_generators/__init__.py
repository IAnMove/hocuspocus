"""Generators keyed by asset kind. Animation, audio and 3D register in later blocks."""
from __future__ import annotations

from services.game_generators.background import BackgroundGenerator
from services.game_generators.still import StillGenerator
from services.game_generators.tiles import TileGenerator, TilesetGenerator

_STILLS = ("character", "sprite", "item", "icon", "ui")

REGISTRY = {kind: StillGenerator(kind) for kind in _STILLS}
REGISTRY["tile"] = TileGenerator()
REGISTRY["tileset"] = TilesetGenerator()
REGISTRY["background"] = BackgroundGenerator()
