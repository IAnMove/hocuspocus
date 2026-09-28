# Plan de producción 2026-09-28

Registro corto. El encargo privado no está en git. Los bloques de esta tabla
están en `development` (`326f0f41`). El contrato operativo está en
[JOBS_AND_ASSETS](JOBS_AND_ASSETS.md) y [VIDEO_COMMANDS](VIDEO_COMMANDS.md).

| Bloque | Estado | Evidencia |
|---|---|---|
| 0 | mezclado | #548 / #561. Validate avisa solapes, caja real, contraste, tramo vacío y zona reservada. El recibo de export 2D/3D sigue a la tarea y lista el MP4 (`export_receipts.project_export_receipt`). El ancla izquierda/derecha no se corta. |
| A1 | mezclado | #561 `jobs.leftovers`, `jobs.resume` y `jobs.discard`. Un submit repetido devuelve `duplicate_leftover`. |
| B2 | mezclado | #552 `assets.upload`. |
| B3 | mezclado | #561 `output_name` opcional. El recibo proyecta asset, URL y ruta. |
| D1 | mezclado | #561 prensa riso opcional (`risoPress` en `finish_presets.json`). Apagada por defecto. |
| A3 | mezclado | #561 un trabajo corto y prioritario sale antes que un vídeo largo. Entero `priority`; no se adelanta al que ya corre. |
| B4 | mezclado | #561 un selector inválido responde `invalid_selector` y los valores permitidos. |
| B5 | mezclado | #561 `jobs.wait` espera el fin del trabajo o `timeout` (30 s por defecto, tope 120). |
| B6 | mezclado | #561 catálogos y ediciones resumidos. La hoja de contactos es una URL de workspace. |

No implica que el servidor local esté en esta revisión ni una publicación en
`main`. `validate: true` en `generation.video` v3 no encola.
