# Recursos para videojuegos: aceptación del 2026-10-07

Fecha: 2026-10-07. Rama: `feat/game-assets-15-17`, que junta J15, J16 y J17. Este documento es la nota de aceptación de J17. La prueba completa por MCP **no se ha ejecutado**.

## Estado del código

J0–J5 y J9 están en `development` por #887. J6–J8 y J10–J14 están por #894. Los PR sueltos que sustituyen quedaron cerrados.

J15, J16 y J17 (#898, #899 y #900) se agruparon en #901, revisados contra el código actual. J17 deja el contrato en `GAME_ASSETS.md` y la guía `docs/agents/GAME_ASSETS_MCP.md`. Los dos se revisaron contra el código de esta rama, con #887 y #894 dentro.

## Qué se verificó

- La CI de #887 y #894 pasó: tests de Python A y B, tests, lint, tipos y build de la UI, y arranque E2E de la UI con API simulada.
- En esta rama, los 25 archivos `tests/test_game_*.py` dieron 255 tests en verde en una pasada local del 2026-10-07. J16 seguía cambiando, así que la cifra no cubre su versión final.
- Esos tests usan herramientas falsas. Ningún test llama a la GPU. El control de estilo usa un `analyze` falso.
- #901 se fusionó en `development` el 2026-10-07. La prueba completa por MCP y GPU sigue sin hacerse.
- Cada dato de `GAME_ASSETS.md` y de la guía MCP se comparó con el código. No con una ejecución real.

## Qué no se verificó

No se creó el juego «Bosque encantado». No se produjo la lista de héroe, slime, animaciones, objetos, iconos, UI, tiles, fondo, efectos, sfx, temas, jingles, cofre 3D ni héroe 3D. No se rechazó, regeneró, exportó ni jugó esa lista. No hay GIF. No existe la carpeta `/home/ina/grok-data/game-assets/final/`, así que tampoco hay ZIP de esta prueba. No hay tiempos de GPU de esa lista ni capturas.

Ninguna generación usó la GPU para J17. El control de estilo no se ha probado con `analyze` real. Hoy no se ha aprobado nada por MCP.

La decisión es la que ya estaba tomada: terminar el código con tests simulados y dejar la prueba de GPU, de oído y de juego para cuando la 4090 esté libre.

## Lo único medido antes (J9, 2026-10-06)

No es esta aceptación. Es el lote pequeño que sí se generó. Las cifras salen de `/home/ina/grok-data/game-assets/j9/report.json`, sin cifras nuevas:

- Lista de ejemplo: 18 recursos, 0 problemas, fuente trial, 57,0 min.
- Lote `prado`, trabajo `game-produce-846ad8d9`: guardia, gema, estrella, losa y marco, todos en `review`.
- `guardia` no se regeneró. Intento `1d5778a9`.
- Seis imágenes `qwen_image_21`. 711,572 s en la procedencia. La ventana final duró 708 s.
- A ojo, según la nota de esa noche: guardia, gema y estrella se leen. La losa es piedra de 16×16 con el borde derecho más oscuro (`seamError` 0,116). El marco se ve, pero el 9-slice (35, 35, 2, 26) no sirve para estirarlo.

Ese lote corrió con el borrador de J9, antes de #887 y #894. T9, el bucle de música de J4, no se ha escuchado. No se han puntuado 10 candidatos reales con el control de estilo de J16.

## Bloques y PR

| Bloque | PR original | Dónde está |
|---|---|---|
| J0 Prueba H3 | #863 | #887, fusionado |
| J1 Biblioteca | #862 | #887, fusionado |
| J2 Pixel | #864 | #887, fusionado |
| J3 Fotogramas | #865 | #887, fusionado |
| J4 Audio | #866 | #887, fusionado |
| J5 Imagen estática | #867 | #887, fusionado |
| J9 Lista y lote | #868 | #887, fusionado |
| J6 Animación | #888 | #894, fusionado |
| J7 Audio gen | #890 | #894, fusionado |
| J8 Modelos 3D | #891 | #894, fusionado |
| J10 Exportación | #892 | #894, fusionado |
| J11 MCP | #893 | #894, fusionado |
| J12 UI juego | #895 | #894, fusionado |
| J13 UI lista | #896 | #894, fusionado |
| J14 UI revisión | #897 | #894, fusionado |
| J15 UI prueba | #901 | fusionado (2026-10-07) |
| J16 Control de estilo | #901 | fusionado (2026-10-07) |
| J17 Aceptación | #901 | fusionado (2026-10-07) |

J15, J16 y J17 se fusionaron juntos en #901. J17 describe `game_qa.py`.

## Problemas

| # | Problema | Impacto | Estado |
|---|---|---|---|
| 1 | La prueba MCP de «Bosque encantado» no se ha hecho | No hay tiempos, intentos, GIF ni ZIP de aceptación | **[PENDIENTE]** GPU libre y una persona delante |
| 2 | T9 no se ha escuchado | El bucle de música no tiene juicio de oído | **[PENDIENTE]** |
| 3 | Andar, correr, girar y flotar van en tira | El código sigue la tabla de J0. El valor de producto lo decide quien usa el lab | **[DECIDIR]** |
| 4 | `loop_not_closed` avisa por encima del 5 % (0,05) | El brief decía 0,5. Manda la tabla de J0 | **[HECHO]** a propósito |
| 5 | El modelo de fondo por capas no está instalado | `layered` sin el modelo falla con `model_not_installed`. Con el modelo también usa `separate` | **[CONOCIDO]** |
| 6 | El ojo de J16 (10 candidatos, uno a propósito fuera de estilo) no se ha hecho | `note_style` solo tiene tests con analizador falso | **[PENDIENTE]** |
| 7 | El control de estilo sigue cambiando | La versión de hoy, sin commit, solo puntúa imágenes fijas y manda URL `/api/v1/file` a `analyze`. Nadie la ha probado con `analyze` real | **[PENDIENTE]** J16 |
| 8 | `identity_drift` incluye el cambio de pose | No separa por sí solo un ciclo bueno de uno malo | **[CONOCIDO]** |
| 9 | `seam_visible` y `style_check_failed` son objetos `{code, message}` | El resto de avisos son cadenas. Un Ogg que no se codifica añade texto libre | **[CONOCIDO]** |
| 10 | Un rig de perfil lateral cae en `not_humanoid` | El rig pide un humanoide de frente. Medido en J8, no repetido hoy | **[CONOCIDO]** |
| 11 | El 9-slice del marco de `prado` no estira | El marco se ve; los márgenes (35, 35, 2, 26) no valen | **[CONOCIDO]** en J9 |
| 12 | `nothing_to_export` sale por MCP con `retryable: true` | Reintentar sin aprobar nada falla igual | **[CONOCIDO]** |

No se inventan tiempos, rutas de captura ni hashes de un ZIP que no existe.

## Qué falta para cerrar

1. Con la GPU libre, medir **un** recurso y después el lote de «Bosque encantado», solo por el perfil `game`, en `game-lab`.
2. Ahí sí se puede aprobar por MCP, y hay que dejarlo escrito en una nota nueva.
3. Rechazar al menos tres con nota, regenerar, exportar y grabar el GIF de la pestaña Prueba.
4. Dejar el ZIP y el GIF en `/home/ina/grok-data/game-assets/final/`.
5. Escuchar T9.
6. Puntuar candidatos reales con `analyze` y comprobar que recibe las imágenes.
7. Decidir si andar, correr, girar y flotar se quedan en tira.
8. Arrancar un servidor nuevo desde `development` más esta rama. El servidor de J9 en el puerto 42021 ya no está en marcha.

## Qué mejoraría

Unificar los avisos a cadenas. Corregir `app/shared/game_agent_guide.md`: dice que solo andar y correr van en tira, y también van girar y flotar. Añadir la línea de «What’s new» cuando J15–J17 se fusionen. La lista de la app es un renglón por PR fusionado; #887 y #894 entraron sin línea. El README no tiene esa sección.
