# Prueba J0 — Recursos para videojuegos (2026-10-06)

Histórico. Medidas reales en la instancia `game-lab` (`127.0.0.1:42021`) con una RTX 4090 de 24564 MiB.
Ningún otro proceso pasó de 2 GB de VRAM. Un trabajo de GPU a la vez. Los fotogramas intermedios de T1–T4 y T10
se borraron después de la hoja de contactos y las métricas. Los números salen de
`/home/ina/grok-data/game-assets/trial/*/record.json` y `metrics.json`.

## Base

Personaje: «caballero bajito con armadura de bronce y capa roja», estilo pixel-16, fondo magenta `#FF00FF`.

Tres candidatos Qwen (`qwen_image_21`, 768×1024). Se eligió la semilla 22.

| Semilla | Tiempo | Fichero | Nota |
|---|---:|---|---|
| 11 | 22,4 s | `trial/candidates/knight-1.png` | Mira a la izquierda. |
| 22 | 17,1 s | `trial/candidates/knight-2.png` | Elegido. Mira a la derecha. |
| 33 | 17,0 s | `trial/candidates/knight-3.png` | Más alto y con más degradado. |

Hoja: `/home/ina/grok-data/game-assets/trial/candidates/contact-candidates.jpg`.

Lienzo H3 de T1–T4 y T10: 544×960, magenta puro. Alto opaco 0,619 del lienzo. Pies a 0,834 del alto. Centro horizontal 0,521.
PNG: `/home/ina/grok-data/game-assets/trial/base/knight-h3.png`.

## Resultados

`minimax_h3` (calidad) corrió a 30 pasos: lo dice el log del servidor (`H3 Perf`), no el JSON del trabajo.
El turbo fundido corrió a 4 pasos. Se pidieron 124 fotogramas; ffmpeg dejó 121 o 122, salvo T4 (124).

La deriva de identidad compara el color del personaje entre el primer fotograma y el central. Incluye el cambio de pose,
así que un andar usable puede marcar ~13 %. No separa un clip bueno de uno malo. El cierre del bucle y el halo sí separan.

| Prueba | Qué | Tiempo | VRAM máx. | Intentos | Medida | Juicio |
|---|---|---:|---:|---:|---|---|
| T1 | Andar, FL2VA turbo | 142,6 s | 19812 MiB | 1 | 122 fotogramas. Identidad 11,47 %. Cierre 14,3 % (lienzo 6,5 %). Pies 206 px (37,9 % del ancho). Halo central 4,5 %. | No sirve. El magenta se llena de destellos, el cuerpo se desplaza y el último fotograma no vuelve. |
| T2 | Andar, calidad | 306,1 s | 20036 MiB | 1 | 122 fotogramas. Identidad 12,84 %. Cierre 2,11 % (lienzo 0,73 %). Pies 48 px (8,8 %). Halo central 0,95 %. | Sirve como bucle de vídeo. El magenta se sostiene y el caballero anda en el sitio. |
| T3 | Tres acciones, turbo | 83,4 s | 19834 MiB | 1 | 121 fotogramas. Identidad 7,08 %. Cierre 15,62 %. Pies 68 px. Halo central 3,4 %. | No sirve para agrupar. Manchas verdes. El ataque no vuelve. El daño no se distingue. |
| T3b | Tres acciones, calidad | 305,7 s | 19856 MiB | 1 extra | 121 fotogramas. Identidad 15,38 %. Cierre 1,69 %. Pies 52 px. Halo central 1,46 %. | El magenta se sostiene y el ataque vuelve. El daño repite la espada. No agrupar por defecto. |
| T4 | Ref2VA turbo | 78,1 s | 19694 MiB | 1 | 124 fotogramas. Identidad 12,67 %. Cierre 43 %. Pies 99 px. | No sirve para un sprite. Inventa un bosque y un camino. El halo no mide nada porque el fondo ya no es magenta. |
| T5 | Tira Qwen 1536×512 | 76,7 s | 15640 MiB | 1 | Seis fotogramas en fila, mismo caballero, magenta plano. | Mejor hoja de sprite que el clip de H3, y mucho más barata. El usuario decide el método por defecto del andar. |
| T6 | Órbita de 4 vistas | 576,2 s | 23233 MiB | 4 | El último intento muestreó 25/25 y el sidecar murió al pedir el historial. Sin vídeo. | Falló. No hay concepto multivista. Tres intentos previos: ruta relativa, runtime sin enlazar y un peso que Hugging Face ya no sirve. |
| T7 | Tile de hierba | 290,5 s | 18557 MiB | 2 pasadas | Costura 2,043 y luego 1,916. | La hierba se reconoce. La costura se ve. Aviso `seam_visible`. No bloquea. |
| T8 | Fondo en 3 capas | 282,2 s | 14794 MiB | 1 | Costura 7,592 / 14,514 / 24,513. Parallax 0,1 / 0,3 / 1,0. Método `separate`. | Capas usables. Línea vertical fina en las siluetas. El número sube porque el interior es casi plano. `qwen_image_layered_20B` no está instalado. |
| T9 | Música 75 s, 120 bpm | 49,0 s | no medido | 1 | Detectados 117,5 bpm y 34 downbeats. Bucle 19,551–51,572 s (32,021 s, 15,68 compases). Puntuación 0,939. Salto de muestra 0,00146. RMS −0,319 dB. | La costura mide limpia. No lo escuché. El pico de VRAM no quedó escrito: el script falló al leer el análisis, con el wav ya en disco. |
| T10 | Explosión, turbo, negro | 148,7 s | 21198 MiB | 1 | 121 fotogramas, 71 con luz. Energía inicial 0, pico medio 48,72, final 3,54. | Sirve. Chispas y fogonazo central. Hay un plano de suelo tenue en el pico. |
| T11 | SFX y 3D | ver abajo | 11464 MiB (imagen y SFX); 14595 MiB (mallas) | 2 en el 3D | Tres WAV. Cofre y caballero a 200000 triángulos. Rig fallido. | Los sonidos y las mallas salieron. El rig no. |

T11, al detalle:

| Parte | Tiempo | Resultado |
|---|---:|---|
| MMAudio «short jump sound», semilla 7 | 16,7 s | `trial/t11/jump-7.wav` |
| Semilla 11 | 15,1 s | `trial/t11/jump-11.wav` |
| Semilla 22 | 15,2 s | `trial/t11/jump-22.wav` |
| Qwen del cofre, 1024×1024 | 63,9 s | `trial/t11/chest.png`. Se reconoce. El magenta no es plano: tiene halo. |
| Hunyuan3D 2 Turbo del cofre | 80,6 s | `trial/t11/chest.glb`. 200000 triángulos. |
| Hunyuan3D 2 Turbo del caballero | 96,4 s | `trial/t11/knight.glb`. 200000 triángulos. |
| Rig humanoide `idle`+`walk` | 5,1 s | Falló: `not_humanoid`, los brazos tocan el cuerpo. La vista de lado no es una pose en T. |

`model3d.generate` sin `model_id` usa el preset `balanced`, que es `hunyuan3d-2-turbo`, con textura y sin
`reduce_face`. El primer intento no arrancó: el worktree no tenía el runtime. Se enlazó el entorno del árbol vivo y
el segundo intento es el medido. No lo repetí.

Los tres WAV no los escuché.

## Hojas de contactos

Rutas absolutas. No están en el repositorio.

- Candidatos: `/home/ina/grok-data/game-assets/trial/candidates/contact-candidates.jpg`
- T1: `/home/ina/grok-data/game-assets/trial/t1/contact.jpg`
- T2: `/home/ina/grok-data/game-assets/trial/t2/contact.jpg`
- T3: `/home/ina/grok-data/game-assets/trial/t3/contact.jpg`
- T3b: `/home/ina/grok-data/game-assets/trial/t3b/contact.jpg`
- T4: `/home/ina/grok-data/game-assets/trial/t4/contact.jpg`
- T5: `/home/ina/grok-data/game-assets/trial/t5/contact.jpg` y `trial/t5/t5-walk-strip.png`
- T6: no hay hoja. No hubo vídeo.
- T7: `/home/ina/grok-data/game-assets/trial/t7/contact.jpg` y `trial/t7/tiled.jpg`
- T8: `/home/ina/grok-data/game-assets/trial/t8/contact.jpg` y `trial/t8/tiled.jpg`
- T9: `trial/t9/loop.wav` y `trial/t9/t9-forest.wav`
- T10: `/home/ina/grok-data/game-assets/trial/t10/contact.jpg`
- T11: `/home/ina/grok-data/game-assets/trial/t11/chest.png`, los tres wav y los dos glb

## Valores por defecto para J6

| Campo | Valor |
|---|---|
| Modelo de vídeo | `minimax_h3` (calidad, 30 pasos, los que usó el servidor) |
| Resolución | `544x960` |
| Fotogramas pedidos | 124 |
| Agrupar acciones en un clip | No |
| Croma | Magenta `#FF00FF`, el mismo en la imagen y en el prompt |
| Lienzo | Alto del personaje ~0,62, pies ~0,85, centrado, `image_start` = `image_end` |
| Plantilla | `[STYLE]` / `[STAGING]` / `[ACTION]` / `[AUDIO] Silence.` del encargo, sección 3.4 |

Método por acción. `h3` es un clip de calidad. `strip` es una tira Qwen de una fila.

| Acción | Método | Motivo |
|---|---|---|
| walk | `strip` | T5 gana como hoja (76,7 s, magenta plano, seis fotogramas) frente a T2 (306 s). T2 sigue siendo el mejor bucle de vídeo. El usuario decide el valor que quedará en el producto. |
| run | `strip` | No se midió. Misma familia que walk. |
| idle, jump, fall, attack, shoot, hurt, death, crouch, climb, victory | `h3` | Un clip por acción. La calidad cierra el bucle (T2, T3b). El turbo no sostiene el magenta. |
| spin, bob | `strip` | Ciclos de objeto en una fila. No se midieron en vídeo. |

Avisos, sin bloquear la exportación:

| Aviso | Umbral | Por qué |
|---|---|---|
| `loop_not_closed` | Cierre del personaje > 5 % | T2 usable está en 2,11 %. T1, que no sirve, está en 14,3 %. |
| `identity_drift` | > 20 % | El andar usable marca 12,8 % porque la pose cambia. Por debajo de 20 % no avisa. No bloquea. |
| Deriva de pies | > 20 % del ancho | T2 usable está en 8,8 % (la zancada). T1, que se desplaza, está en 37,9 %. |
| `halo` | > 2 % en el fotograma central | T2 está en 0,95 %. T1 está en 4,5 %. Si el fondo ya no es el croma, el número no vale. |

## Notas para los bloques siguientes

- J5. El tile avisa `seam_visible` por encima de 1,5 y no bloquea. T7 se quedó en 1,92. El fondo por capas usa el método separado. El modelo de capas no está instalado.
- J7. Pedir 120 bpm puede medir 117,5. El corte de 16 compases de T9 queda en 15,68 compases, con salto 0,00146 y RMS 0,3 dB. Falta el oído.
- J8. Sin `model_id`, Hunyuan es `hunyuan3d-2-turbo`: unos 80–100 s, pico 14,6 GB y 200000 triángulos. Hay que pasar `reduce_face` para bajar de 3000. La órbita de cuatro vistas no produjo fotogramas: no bloquea el bloque. Un rig humanoide necesita una pose en T o en A; la vista de lado falla con `not_humanoid`.
- T10. El alfa de un efecto sobre negro puede ser el canal máximo. El plano de suelo tenue es un defecto a tener en cuenta.
