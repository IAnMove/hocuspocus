# Recursos para videojuegos: aceptación del 2026-10-07

Fecha: 2026-10-07. Rama: `docs/game-assets-acceptance`. Este documento es la nota de aceptación de J17. La prueba completa por MCP **no se ha ejecutado**.

## Qué se hizo

Se construyó el laboratorio de recursos, de J0 a J16, cada bloque en su borrador. J17 deja el contrato en `GAME_ASSETS.md` y completa la guía `docs/agents/GAME_ASSETS_MCP.md`.

No se creó el juego «Bosque encantado». No se produjo la lista de héroe, slime, animaciones, objetos, iconos, UI, tiles, fondo, efectos, sfx, temas, jingles, cofre 3D ni héroe 3D. No se rechazó, regeneró, exportó ni jugó esa lista. No hay GIF. No hay ZIP de esta prueba en `/home/ina/grok-data/game-assets/final/`. No hay tiempos de GPU de esa lista, ni capturas de esta noche.

La decisión es la que ya estaba tomada: terminar el código con tests simulados y dejar la prueba de GPU, de oído y de juego para cuando la 4090 esté libre. Plus Ultra (`:42042`) no se ha tocado.

## Lo único medido antes (J9, 2026-10-06)

No es esta aceptación. Es el lote pequeño que sí se generó, copiado de la nota de esa noche, sin cifras nuevas:

- Lista de ejemplo: 18 recursos, 0 problemas, fuente trial, 57,0 min.
- Lote `prado`, trabajo `game-produce-846ad8d9`: guardia, gema, estrella, losa y marco, todos en `review`.
- `guardia` no se regeneró. Intento `1d5778a9`.
- Seis imágenes `qwen_image_21`. 711,572 s en la procedencia. La ventana final duró 708 s.
- A ojo: guardia, gema y estrella se leen. La losa es piedra de 16×16 con el borde derecho más oscuro (`seamError` 0,116). El marco se ve, pero el 9-slice (35, 35, 2, 26) no sirve para estirarlo.

T9, el bucle de música de J4, no se ha escuchado. El control de estilo de J16 tiene tests con un analizador falso. No se han puntuado 10 candidatos reales.

## Borradores

Ninguno está fusionado. Este PR depende de #899. No fusionar antes de #899. El diff contra `development` arrastra también #898, #897, #896, #895, #893, #892, #891, #890, #888, #866, #868, #865, #867, #864 y #862. J0 es #863 y va en su propia rama.

| Bloque | PR |
|---|---|
| J0 Prueba H3 | #863 |
| J1 Biblioteca | #862 |
| J2 Pixel | #864 |
| J3 Fotogramas | #865 |
| J4 Audio | #866 |
| J5 Imagen estática | #867 |
| J6 Animación | #888 |
| J7 Audio gen | #890 |
| J8 Modelos 3D | #891 |
| J9 Lista y lote | #868 |
| J10 Exportación | #892 |
| J11 MCP | #893 |
| J12 UI juego | #895 |
| J13 UI lista | #896 |
| J14 UI revisión | #897 |
| J15 UI prueba | #898 |
| J16 Control de estilo | #899 |
| J17 Aceptación | este PR |

## Problemas

| # | Problema | Impacto | Estado |
|---|---|---|---|
| 1 | La prueba MCP de «Bosque encantado» no se ha hecho | No hay tiempos, intentos, GIF ni ZIP de aceptación | **[PENDIENTE]** GPU libre y una persona delante |
| 2 | T9 no se ha escuchado | El bucle de música de J4 no tiene juicio de oído | **[PENDIENTE]** |
| 3 | Andar y correr | El código sigue la tabla de J0 y usa tira. El valor de producto lo decide quien usa el lab | **[DECIDIR]** |
| 4 | `loop_not_closed` avisa por encima del 5 % (0,05) | El brief decía 0,5. Manda la tabla de J0 | **[HECHO]** a propósito |
| 5 | El modelo de fondo por capas no está instalado | Los fondos van por el método `separate` | **[HECHO]** límite conocido |
| 6 | El ojo de J16 (10 candidatos, uno a propósito fuera de estilo) no se ha hecho | `style_check` está cableado y cubierto con analizador falso | **[PENDIENTE]** |
| 7 | `identity_drift` incluye el cambio de pose | No separa por sí solo un ciclo bueno de uno malo | **[CONOCIDO]** |
| 8 | El aviso de costura del tile es un objeto `{code, message}` | El resto de avisos son cadenas. Quien lea `warnings` tiene que aceptar las dos formas | **[CONOCIDO]** |
| 9 | Un rig de perfil lateral cae en `not_humanoid` | El rig pide un humanoide de frente. Medido en J8, no repetido hoy | **[CONOCIDO]** |
| 10 | El 9-slice del marco de `prado` no estira | El marco se ve; los márgenes (35, 35, 2, 26) no valen | **[CONOCIDO]** en J9 |

No se inventan tiempos, rutas de captura ni hashes de un ZIP que no existe.

## Qué falta para cerrar

1. Con la GPU libre, medir **un** recurso y después el lote de «Bosque encantado», solo por el perfil `game`, en `game-lab`.
2. Ahí sí se puede aprobar por MCP, y hay que dejarlo escrito en una nota nueva. Hoy no se ha aprobado nada por esta vía.
3. Rechazar al menos tres con nota, regenerar, exportar y grabar el GIF de la pestaña Prueba.
4. Dejar el ZIP y el GIF en `/home/ina/grok-data/game-assets/final/`.
5. Escuchar T9.
6. Decidir si andar y correr se quedan en tira.
7. Arrancar el servidor desde la punta de esta pila. El proceso de J9 en el puerto 42021 sigue con código anterior al arreglo de reanudación (`0cf506be`).

## Qué mejoraría

Unificar los avisos a cadenas. Reiniciar el servidor de pruebas desde la rama apilada antes de medir. Añadir la línea de «What’s new» solo cuando estos borradores estén fusionados: la lista de la app es un renglón por PR ya fusionado, y el README no tiene esa sección.
