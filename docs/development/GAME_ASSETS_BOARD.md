# Tablero: Recursos para videojuegos

Base: `origin/development` (`b7d9962d`, incluye `415e4602`). Un bloque, un PR contra `development`. No se mezcla desde aquí.

| Bloque | Rama | PR | Estado | Archivos (exclusivos) |
|---|---|---|---|---|
| J0 Prueba H3 | `docs/game-assets-trial` | — | en curso | `docs/development/GAME_ASSETS_TRIAL_2026-10-06.md` |
| J1 Biblioteca | `feat/game-assets-1-library` | #862 | en curso (borrador) | `app/services/game_library.py`, `app/services/game_inputs.py`, `app/routers/game_library.py`, `app/shared/game_actions.json`, `app/shared/game_style_presets.json`, `tests/test_game_library.py`, `tests/test_game_inputs.py`, `tests/test_game_library_router.py`, este tablero |
| J2 Pixel e imagen | `feat/game-assets-2-pixel` | — | en curso | `app/services/game_pixel.py`, `app/services/game_image_ops.py`, `app/services/game_tiles.py`, `tests/test_game_pixel.py`, `tests/test_game_image_ops.py`, `tests/test_game_tiles.py` |
| J3 Fotogramas | `feat/game-assets-3-frames` | — | pendiente | `app/services/game_frames.py`, `app/services/game_sheet.py` |
| J4 Audio | `feat/game-assets-4-audio` | — | pendiente | `app/services/game_audio.py`, `app/services/game_sfxr.py` |
| J5 Imagen estática | `feat/game-assets-5-static` | — | pendiente | `app/services/game_tools.py`, `app/services/game_prompts.py`, `app/services/game_generators/` (still, tiles, background) |
| J6 Animación | `feat/game-assets-6-animation` | — | pendiente | `app/services/game_generators/animation.py`, `app/services/game_generators/vfx.py` |
| J7 Audio gen | `feat/game-assets-7-audio-gen` | — | pendiente | `app/services/game_generators/audio.py` |
| J8 Modelos 3D | `feat/game-assets-8-3d` | — | pendiente | `app/services/game_generators/three_d.py`, `triangle_count` en el inspector GLB |
| J9 Lista y lote | `feat/game-assets-9-produce` | — | pendiente | `app/services/game_list.py`, `app/services/game_produce.py`, `app/services/game_jobs.py`, `app/services/game_estimate.py`, `app/routers/game_produce.py` |
| J10 Exportación | `feat/game-assets-10-export` | — | pendiente | `app/services/game_export.py` |
| J11 MCP | `feat/game-assets-11-mcp` | — | pendiente | `app/services/game_commands.py`, `app/services/game_guide.py`, `app/shared/game_agent_guide.md`, perfil `game` |
| J12 UI juego | `feat/game-assets-12-ui-setup` | — | pendiente | `ui/src/features/game-assets/` (juego, estilo, reparto) |
| J13 UI lista | `feat/game-assets-13-ui-list` | — | pendiente | `GameListPanel`, `GameProducePanel` |
| J14 UI revisión | `feat/game-assets-14-ui-review` | — | pendiente | `GameReviewPanel`, `SpriteSheetPlayer`, `AudioLoopPlayer` |
| J15 UI prueba | `feat/game-assets-15-ui-playtest` | — | pendiente | `GamePlaytest`, `GameExportPanel` |
| J16 Control de estilo | `feat/game-assets-16-qa` | — | pendiente | `app/services/game_qa.py` |
| J17 Aceptación | `docs/game-assets-acceptance` | — | pendiente | `docs/development/GAME_ASSETS.md`, informe de aceptación |

Orden: J0 y J1 en paralelo; después J2, J3 y J4 en paralelo; luego J5 → J9 → J6 → J7 → J8 → J10 → J11 → J12 → J13 → J14 → J15 → J16 → J17. La UI (J12) puede empezar cuando J1 tenga la API.
