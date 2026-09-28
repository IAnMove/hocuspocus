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
| C3 | en este PR | `qa.people` cuenta personas en CPU y responde `ok`, `retake` o `unreliable`. |
| C4 | en este PR | `studio.key` quita el fondo verde en CPU. El mate temporal queda fijo en 0.15/0.7/0.15. `isnet-anime` solo si el modelo ya está instalado. |
| C6 | en este PR | `clip.align` devuelve el recorte contra el compás. Sin `qa.lipsync` el veredicto es `unreliable`. |
| D2 | en este PR | El texto de color reserva la plancha negra con `finish.riso` o `trap: true`. |
| D3 | en este PR | Plantillas `ransom`, `dymo` y `card`. La misma geometría sale de TypeScript y de Python. |
| D5 | en este PR | `montages.preview` pinta hasta 8 instantes del montaje completo, guarda el PNG y devuelve URL y sha256. |
| D7 | en este PR | `scenes.catalog` con `kind: graphics` lista seis dibujos parametrizados. |
