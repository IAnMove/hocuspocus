"""Generators keyed by asset kind. Audio and 3D register in later blocks."""
from __future__ import annotations

from services.game_generators.animation import AnimationGenerator, ItemGenerator
from services.game_generators.background import BackgroundGenerator
from services.game_generators.still import StillGenerator
from services.game_generators.tiles import TileGenerator, TilesetGenerator
from services.game_generators.vfx import VfxGenerator

_STILLS = ("character", "sprite", "icon", "ui")

REGISTRY = {kind: StillGenerator(kind) for kind in _STILLS}
REGISTRY["item"] = ItemGenerator()
REGISTRY["tile"] = TileGenerator()
REGISTRY["tileset"] = TilesetGenerator()
REGISTRY["background"] = BackgroundGenerator()
REGISTRY["animation"] = AnimationGenerator()
REGISTRY["vfx"] = VfxGenerator()
