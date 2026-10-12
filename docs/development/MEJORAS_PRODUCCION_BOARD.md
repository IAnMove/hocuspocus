# Tablero de mejoras de producción (2026-10-08)

Un bloque, un PR en borrador contra `development`. No se mezcla nada desde este tablero.
La columna «Puede empezar» no existe: «Estado» dice si el bloque está abierto.
Antes de empezar un bloque: `git fetch`, `gh pr list` y `git grep` de sus palabras clave.

| Bloque | Rama | PR | Estado | Archivos (exclusivos) |
|---|---|---|---|---|
| M1 Contrato de generation | `fix/mcp-generation-contract` | [#911](https://github.com/IAnMove/hocuspocus/pull/911) | borrador abierto | `app/services/jobs_cancel.py`, `app/services/output_names.py`, `app/routers/image_generation_commands.py`, `tests/test_generation_contract.py`, `tests/test_jobs_cancel.py`, `tests/test_output_names.py` |
| M2 Mensajes de error | `fix/mcp-error-messages` | [#912](https://github.com/IAnMove/hocuspocus/pull/912) | borrador abierto | `app/services/series_script_problems.py`, control de campos en `series_commands.py` y `job_leftovers.py`, paginación de `world3d.templates.list` |
| M3 Informe de produce | `fix/series-produce-reporting` | [#913](https://github.com/IAnMove/hocuspocus/pull/913) | borrador abierto | avance de `series.episode.produce`, `approvalReset` de `series.shot.update`, número de episodio |
| F1 Guía de agentes | `docs/agent-guide-lessons` | [#914](https://github.com/IAnMove/hocuspocus/pull/914) | borrador abierto | `app/shared/series_agent_guide.md`, documentos de desarrollo desfasados |
| V1 Voz en español | `feat/speech-qa-spanish` | [#915](https://github.com/IAnMove/hocuspocus/pull/915) | borrador abierto | `app/services/speech_text_es.py`, diccionario de pronunciación |
| V2 Tono y acento | `feat/voice-pitch-accent` | [#916](https://github.com/IAnMove/hocuspocus/pull/916) | borrador abierto | `voiceProfile.pitchRange`, `app/services/qa_accent.py` |
| S1 Avisos del guion | `feat/series-script-warnings` | [#917](https://github.com/IAnMove/hocuspocus/pull/917) | borrador abierto | avisos de `from_script`, `instanceKey` si el kit se repite |
| S2 Huella y cuadro | `fix/series-render-fingerprint-frame` | [#918](https://github.com/IAnMove/hocuspocus/pull/918) | borrador abierto | huella de planos mudos, cuadro 3D, `estimate` |
| S3 Boca del rig | `feat/rig-mouth-report-precheck` | [#919](https://github.com/IAnMove/hocuspocus/pull/919) | borrador abierto | `app/services/flat_rig_metrics.py`, `characters.rig.check` |
| S4 Fondos | `feat/series-plate-checks` | [#920](https://github.com/IAnMove/hocuspocus/pull/920) | borrador abierto | aviso `people_in_plate`, `scene3d.backdrop` |
| D1 Candado de GPU | `feat/gpu-machine-lock` | [#921](https://github.com/IAnMove/hocuspocus/pull/921) | borrador abierto | `app/services/gpu_machine_lock.py`, `scripts/hocus_instances.py` |
| Q1 Conjunto dorado | `feat/golden-shots` | [#922](https://github.com/IAnMove/hocuspocus/pull/922) | borrador abierto | `scripts/golden_shots.py`, `docs/development/GOLDEN_SHOTS.md` |
| E1 Videojuegos, defectos | `fix/game-assets-followups` | [#923](https://github.com/IAnMove/hocuspocus/pull/923) | borrador abierto | identidad por color, avisos `game_*`, T-pose, nine-slice, órbita |
| E2 Videojuegos, prueba real | `docs/game-assets-acceptance-run` | — | pendiente | informe de aceptación y entrega fuera del repo |
| G1 Transiciones | `feat/series-transitions` | [#924](https://github.com/IAnMove/hocuspocus/pull/924) | borrador abierto | `shot.transitionIn` |
| G2 Cartela de documento | `feat/series-document-cards` | [#925](https://github.com/IAnMove/hocuspocus/pull/925) | borrador abierto: la página cabe o avisa, y no bloquea | `card.kind: document` |
| G3 Oído | `feat/series-hearing` | [#926](https://github.com/IAnMove/hocuspocus/pull/926) | borrador abierto: el oído normal no toca el archivo; el sordo hay que volver a renderizarlo | `shot.hearing` |
| G4 Grabado y stop-motion | `feat/looks-etching-stopmotion` | [#927](https://github.com/IAnMove/hocuspocus/pull/927) | borrador abierto: el grabado es estable y el stop-motion no toca el audio | efecto `etching`, `motionStep` |
| G5 Planos de vídeo | `feat/series-video-shots` | [#928](https://github.com/IAnMove/hocuspocus/pull/928) | borrador abierto: el paso de vídeo va antes del render; las dos tomas reales esperan GPU libre | `video` en el plano |
| G6 Versiones de kit | `feat/kit-revisions-pinning` | [#929](https://github.com/IAnMove/hocuspocus/pull/929) | borrador abierto: sin pins el episodio usa la última revisión; las capturas esperan GPU libre | `kit.revision`, `episode.kitPins` |
| H1 Recuperabilidad | `feat/recoverability-rest` | — | pendiente, solo si sobra tiempo | puntos abiertos de `docs/development/MCP_RECOVERABILITY.md` |
