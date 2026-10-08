# Tablero de mejoras de producción (2026-10-08)

Un bloque, un PR en borrador contra `development`. No se mezcla nada desde este tablero.
La columna «Puede empezar» no existe: «Estado» dice si el bloque está abierto.
Antes de empezar un bloque: `git fetch`, `gh pr list` y `git grep` de sus palabras clave.

| Bloque | Rama | PR | Estado | Archivos (exclusivos) |
|---|---|---|---|---|
| M1 Contrato de generation | `fix/mcp-generation-contract` | [#911](https://github.com/IAnMove/hocuspocus/pull/911) | borrador abierto | `app/services/jobs_cancel.py`, `app/services/output_names.py`, `app/routers/image_generation_commands.py`, `tests/test_generation_contract.py`, `tests/test_jobs_cancel.py`, `tests/test_output_names.py` |
| M2 Mensajes de error | `fix/mcp-error-messages` | — | pendiente | `app/services/series_script_problems.py`, control de campos en `series_commands.py` y `job_leftovers.py`, paginación de `world3d.templates.list` |
| M3 Informe de produce | `fix/series-produce-reporting` | — | pendiente | avance de `series.episode.produce`, `approvalReset` de `series.shot.update`, número de episodio |
| F1 Guía de agentes | `docs/agent-guide-lessons` | — | pendiente | `app/shared/series_agent_guide.md`, documentos de desarrollo desfasados |
| V1 Voz en español | `feat/speech-qa-spanish` | — | pendiente | `app/services/speech_text_es.py`, diccionario de pronunciación |
| V2 Tono y acento | `feat/voice-pitch-accent` | — | pendiente | `voiceProfile.pitchRange`, `app/services/qa_accent.py` |
| S1 Avisos del guion | `feat/series-script-warnings` | — | pendiente | avisos de `from_script`, `instanceKey` si el kit se repite |
| S2 Huella y cuadro | `fix/series-render-fingerprint-frame` | — | pendiente | huella de planos mudos, cuadro 3D, `estimate` |
| S3 Boca del rig | `feat/rig-mouth-report-precheck` | — | pendiente | `app/services/flat_rig_metrics.py`, `characters.rig.check` |
| S4 Fondos | `feat/series-plate-checks` | — | pendiente | aviso `people_in_plate`, `scene3d.backdrop` |
| D1 Candado de GPU | `feat/gpu-machine-lock` | — | pendiente | `app/services/gpu_machine_lock.py`, `scripts/hocus_instances.py` |
| Q1 Conjunto dorado | `feat/golden-shots` | — | pendiente | `scripts/golden_shots.py`, `docs/development/GOLDEN_SHOTS.md` |
| E1 Videojuegos, defectos | `fix/game-assets-followups` | — | pendiente | identidad por color, avisos `game_*`, T-pose, nine-slice, órbita |
| E2 Videojuegos, prueba real | `docs/game-assets-acceptance-run` | — | pendiente | informe de aceptación y entrega fuera del repo |
| G1 Transiciones | `feat/series-transitions` | — | pendiente | `shot.transitionIn` |
| G2 Cartela de documento | `feat/series-document-cards` | — | pendiente | `card.kind: document` |
| G3 Oído | `feat/series-hearing` | — | pendiente | `shot.hearing` |
| G4 Grabado y stop-motion | `feat/looks-etching-stopmotion` | — | pendiente | efecto `etching`, `motionStep` |
| G5 Planos de vídeo | `feat/series-video-shots` | — | pendiente | `app/services/series_video_shots.py` |
| G6 Versiones de kit | `feat/kit-revisions-pinning` | — | pendiente | `kit.revision`, `episode.kitPins` |
| H1 Recuperabilidad | `feat/recoverability-rest` | — | pendiente, solo si sobra tiempo | puntos abiertos de `docs/development/MCP_RECOVERABILITY.md` |
