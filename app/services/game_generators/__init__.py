"""Generators keyed by asset kind. 3D registers in a later block."""
from __future__ import annotations

from services.game_generators.animation import AnimationGenerator, ItemGenerator
from services.game_generators.audio import JingleGenerator, MusicGenerator, SfxGenerator, VoiceGenerator
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
REGISTRY["sfx"] = SfxGenerator()
REGISTRY["music"] = MusicGenerator()
REGISTRY["jingle"] = JingleGenerator()
REGISTRY["voice"] = VoiceGenerator()
