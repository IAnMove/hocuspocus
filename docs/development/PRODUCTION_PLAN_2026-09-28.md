# Plan de producción 2026-09-28

Registro corto. El encargo privado no está en git. B2 ya está en `development` (#552).

| Bloque | Estado | Evidencia |
|---|---|---|
| 0 | en este PR | Validate avisa solapes, caja real, contraste, tramo vacío y zona reservada. El recibo de export sigue a la tarea y lista el MP4. El ancla izquierda/derecha no se corta. |
| A1 | en este PR | `jobs.leftovers`, `jobs.resume` y `jobs.discard`. Un submit repetido devuelve `duplicate_leftover`. |
| B2 | mezclado | #552 `assets.upload`. |
| B3 | en este PR | `output_name` opcional. El recibo devuelve asset, URL y ruta. |
| D1 | en este PR | Prensa riso opcional (`risoPress`). Apagada por defecto. |
| A3 | en este PR | Un trabajo corto y prioritario sale antes que un vídeo largo. |
| B3 | en este PR | `output_name` opcional. El recibo devuelve asset, URL y ruta. |
| B4 | en este PR | Un selector inválido responde `invalid_selector` y los valores permitidos. |
| B5 | en este PR | `jobs.wait` espera el fin del trabajo o `timeout`. |
| B6 | en este PR | Catálogos y ediciones resumidos. La hoja de contactos es una URL. |
| C4 | en este PR | `studio.key` quita el fondo verde en CPU. El mate temporal queda fijo en 0.15/0.7/0.15. `isnet-anime` solo si el modelo ya está instalado. |
