# Conjunto dorado

`scripts/golden_shots.py` compara planos ya renderizados con unas referencias que viven **fuera del repositorio**. No entra en la CI. Sirve después de cada tanda de fusiones, antes de actualizar la instancia de `:42003`.

El directorio por defecto es `/mnt/outputs/golden` (`HOCUS_GOLDEN_DIR` lo cambia). Ahí están el manifiesto, las copias de los planos y las referencias. No se mueven los originales.

## Qué mide

Por cada plano, en tres fotogramas (al 10 %, al 50 % y al 90 %):

- SSIM local: se calcula en cada ventana de 8×8 píxeles y cuenta la peor. Umbral por plano `ssim_threshold` (por defecto 0,9). Tamaños distintos puntúan 0.
- Sonoridad integrada, ±1 LU. Un plano sin audio no se compara por sonoridad.
- Duración, ±1 fotograma.

El SSIM global (una sola ventana, la de antes) no veía un cambio pequeño: tapar 80×40 píxeles, el tamaño de una boca, en un fotograma 1080p dejaba 0,98–0,9999. Con ventanas, ese cambio baja a 0,03 o menos. Medido en los fotogramas del conjunto: un plano 2D renderizado otra vez con las mismas entradas sale idéntico (1,0); el mismo plano recodificado (x264, crf 23) baja a 0,38–0,86. Un umbral de 0,98 en el manifiesto sigue valiendo: exige que el plano salga igual.

El informe HTML (`report/index.html`) muestra antes | ahora | diferencia.

Una fila `kind: rig` no lee un vídeo: vuelve a dibujar una boca warp sobre una cara sintética con el código actual. Si cambia una constante del rig, esa fila pasa a rojo.

## Cómo ejecutarlo

Desde la raíz del checkout, con el Python del entorno de la app:

```bash
python scripts/golden_shots.py selftest
python scripts/golden_shots.py record
python scripts/golden_shots.py check
```

`record` guarda las referencias a partir del medio que indica el manifiesto. Si ya hay referencias, no las cambia: `record --force` las sustituye. `check` las compara con ese mismo medio mientras no haya un render (ver abajo). `selftest` no toca el conjunto real: con un vídeo 1080p corto comprueba que un plano idéntico sale verde, que una zona de 80×40 tapada en una referencia sale roja, que `record` no sobrescribe, que `render` rechaza los puertos en vivo y que, tras un render, `check` no da verde sin la toma nueva.

Para volver a renderizar en una instancia de prueba (no en la que ya está produciendo):

```bash
python scripts/golden_shots.py render --base-url http://127.0.0.1:42021 --token-file /ruta/al/token
python scripts/golden_shots.py fetch --base-url http://127.0.0.1:42021 --token-file /ruta/al/token
python scripts/golden_shots.py check
```

`--base-url` es obligatorio y se rechazan los puertos 42003 (la instancia en vivo) y 42042 (la producción en curso): un render allí añade tomas a la biblioteca que esa instancia está escribiendo.

`render` llama a `series.episode.render_native` con los `shot_ids` del manifiesto, agrupados por serie y episodio. No aprueba tomas. Guarda los trabajos en `renders.json` y borra `current/`. `fetch` lee el estado de esos trabajos y copia cada toma terminada a `current/<id>`; si un plano aún se renderiza, lo dice y hay que repetir `fetch`. Desde el render, `check` compara cada fila renderizable con su toma de `current/`, y una fila sin toma nueva sale roja. Para volver a comparar las copias del manifiesto, quita `renders.json`. El token no se imprime.

## El primer conjunto

Doce planos de Plus Ultra, copiados desde el workspace de producción, y tres de Moncloa. Los de Moncloa no están en el repo: solo el manifiesto, fuera de git, guarda sus ids.

| Id | Papel |
|---|---|
| e2s05, e2s07 | rig warp (toma aprobada; el kit vigente es warp) |
| e2s60 | tinta: el kit tuvo `mouthStyle: ink` y la última entrada guardada es warp; la referencia es la toma aprobada |
| e2s225, e1s111 | 3D con clips |
| e2s164 | objeto en la mano |
| e2s54, e2s73 | `code_rain` |
| e1s28 | clip H3 de 5 s (`minimax_h3_fused_turbo`) |
| e1s43, e1s44 | sala de voz |
| e2s159 | foley |

La fila `rig-warp` es la que vuelve a ejecutar el rig. La primera pasada de `check`, hecha sobre estas copias y sobre esa fila, tiene que salir verde. Cambiar a propósito una constante del rig (por ejemplo `FEATHER` en `app/services/flat_rig_warp.py`) y repetir `check` pone en rojo solo esa fila. Hay que dejar la constante como estaba: el conjunto dorado no cambia el rig.
