# Plan de producción Video 2D — 2026-09-28

Registro de avance. Un PR por bloque contra `development`. Este archivo no copia
el encargo privado; solo el estado.

| Bloque | PR | Estado | Evidencia |
| --- | --- | --- | --- |
| 0 | draft [#550](https://github.com/IAnMove/hocuspocus/pull/550) (`fix/video2d-production-block0`) | en revisión | Cherry-pick de `/examples/` en compile. Validate avisa `text_overlap`, `text_outside_frame`, `lyrics_overlap`, `empty_timespan`, `reserved_zone` y `text_low_contrast` (píxeles reales; si el pintor no arranca no hay ratio). `add_title` se compara con el puente TypeScript. Cámaras y finish salen de `app/shared`. El smoke usa `scenes.video2d.edit`. La guía sigue catalog → inspect → compile → text/lyrics → edit → validate → preview → save → export → montages.save. |
| A | — | pendiente | Cola tras reinicio, presión de memoria y prioridad. Requiere GPU en una instancia que no sea el servidor en vivo. |
| B | — | pendiente | Contrato MCP de generación, subida, nombres de salida, selectores y respuestas compactas. |
| C | — | pendiente | Análisis de audio, QA de labios y personas, croma y QA de música. |
| D | — | pendiente | Acabado Video 2D (prensa, trapping, estilos, capa a sangre, preview de montaje, sync y gráficos acotados), apagado por defecto. |
| E | — | pendiente | Plan declarativo, workflow de videoclip, rúbrica y runbook. La aceptación final usa GPU. |

El bloque 0 no hace A–E. No genera medios en GPU y no fusiona el PR.
