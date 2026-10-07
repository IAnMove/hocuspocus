# Tablero: Recursos para videojuegos

Base: `origin/development` (`b7d9962d`, incluye `415e4602`). Un bloque, un PR contra `development`. No se mezcla desde aquí.

El 2026-10-07, J0–J5 y J9 (#862–#868) se agruparon en #887 sobre `development` actual; los PR originales quedan sustituidos. J6–J8, J10 y J11 (#888–#893) y la UI J12–J14 (#895–#897) se agruparon después en #894. J15–J17 (#898–#900) se agruparon en #901.

| Bloque | Rama | PR | Estado | Archivos (exclusivos) |
|---|---|---|---|---|
| J0 Prueba H3 | `feat/game-assets-combined` | #887 | mezclado | `docs/development/GAME_ASSETS_TRIAL_2026-10-06.md` |
| J1 Biblioteca | `feat/game-assets-combined` | #887 | mezclado | `app/services/game_library.py`, `app/services/game_inputs.py`, `app/routers/game_library.py`, `app/shared/game_actions.json`, `app/shared/game_style_presets.json`, `tests/test_game_library.py`, `tests/test_game_inputs.py`, `tests/test_game_library_router.py`, este tablero |
| J2 Pixel e imagen | `feat/game-assets-combined` | #887 | mezclado | `app/services/game_pixel.py`, `app/services/game_image_ops.py`, `app/services/game_tiles.py`, `tests/test_game_pixel.py`, `tests/test_game_image_ops.py`, `tests/test_game_tiles.py` |
| J3 Fotogramas | `feat/game-assets-combined` | #887 | mezclado | `app/services/game_frames.py`, `app/services/game_sheet.py`, `tests/test_game_frames.py`, `tests/test_game_sheet.py` |
| J4 Audio | `feat/game-assets-combined` | #887 | mezclado | `app/services/game_audio.py`, `app/services/game_sfxr.py`, `tests/test_game_audio.py`, `tests/test_game_sfxr.py` |
| J5 Imagen estática | `feat/game-assets-combined` | #887 | mezclado | `app/services/game_tools.py`, `app/services/game_prompts.py`, `app/services/game_generators/` (`still`, `tiles`, `background`), `tests/test_game_tools.py`, `tests/test_game_prompts.py`, `tests/test_game_gen_still.py`, `tests/test_game_gen_tiles.py` |
| J6 Animación | `feat/game-assets-6-11` | #894 | mezclado | `app/services/game_generators/animation.py`, `app/services/game_generators/vfx.py`, `tests/test_game_gen_animation.py`, `tests/test_game_gen_vfx.py` |
| J7 Audio gen | `feat/game-assets-6-11` | #894 | mezclado | `app/services/game_generators/audio.py`, `tests/test_game_gen_audio.py` |
| J8 Modelos 3D | `feat/game-assets-6-11` | #894 | mezclado | `app/services/game_generators/three_d.py`, `triangle_count` en el inspector GLB, `tests/test_game_gen_3d.py` |
| J9 Lista y lote | `feat/game-assets-combined` | #887 | mezclado | `app/services/game_list.py`, `app/services/game_produce.py`, `app/services/game_jobs.py`, `app/services/game_estimate.py`, `app/routers/game_produce.py` |
| J10 Exportación | `feat/game-assets-6-11` | #894 | mezclado | `app/services/game_export.py`, `POST /api/v1/games/{id}/export`, `tests/test_game_export.py` |
| J11 MCP | `feat/game-assets-6-11` | #894 | mezclado | `app/services/game_commands.py`, `app/services/game_guide.py`, `app/shared/game_agent_guide.md`, perfil `game`, `docs/agents/GAME_ASSETS_MCP.md` |
| J12 UI juego | `feat/game-assets-6-11` | #894 | mezclado | `ui/src/features/game-assets/` (juego, estilo, reparto) |
| J13 UI lista | `feat/game-assets-6-11` | #894 | mezclado | `GameListPanel`, `GameProducePanel` |
| J14 UI revisión | `feat/game-assets-6-11` | #894 | mezclado | `GameReviewPanel`, `SpriteSheetPlayer`, `AudioLoopPlayer` |
| J15 UI prueba | `feat/game-assets-15-17` | #901 | en revisión (agrupado) | `GamePlaytest`, `GameExportPanel` |
| J16 Control de estilo | `feat/game-assets-15-17` | #901 | en revisión (agrupado) | `app/services/game_qa.py` |
| J17 Aceptación | `feat/game-assets-15-17` | #901 | en revisión (agrupado) | `docs/development/GAME_ASSETS.md`, informe de aceptación |

Orden: J0 y J1 en paralelo; después J2, J3 y J4 en paralelo; luego J5 → J9 → J6 → J7 → J8 → J10 → J11 → J12 → J13 → J14 → J15 → J16 → J17. La UI (J12) puede empezar cuando J1 tenga la API.
