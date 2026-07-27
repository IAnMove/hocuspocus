# Fase 2B — LTX-2.3 en cola de cómic y caché de texto

Fecha de medición: 27 de julio de 2026

GPU: NVIDIA GeForce RTX 4090, 24 GiB

Rama: `experiment/linux-ltx-next`

Punto de partida: `9c1e71d`

## Decisión

**LTX-2.3 Distilled Quanto BF16 INT8 sigue siendo la variante recomendada
para una RTX 4090.**

- `ltx2_22B_distilled_1_1` queda identificado como **Recommended — RTX
  4090**. Ya era el ID predeterminado de vídeo, Director y el flujo de cómic;
  se conserva ese ID para Preview y Balanced.
- `ltx2_22B_distilled_gguf_q6_k` sigue disponible como **Low VRAM /
  Compatibility**.
- `ltx2_22B_fp8` queda como **Quality Experimental**, no como preset
  predeterminado. Su pipeline Dev de 30 pasos con CFG no es comparable en
  velocidad con Distilled. En la prueba realizada fue mucho más lento,
  necesitó un perfil de memoria conservador y no produjo una mejora visual
  suficientemente estable.

No se instaló el kernel GGUF, no se descargó el checkpoint oficial de
46,1 GB y no se inició la integración del backend oficial.

## Alcance y aislamiento

Los tres checkpoints se localizaron en la biblioteca compartida de solo
lectura:

| ID de catálogo | Archivo resuelto |
|---|---|
| `ltx2_22B_distilled_1_1` | `/home/ina/pinokio/api/Maestro.git/app/ckpts/ltx-2.3-22b-distilled-1.1_diffusion_model_quanto_bf16_int8.safetensors` |
| `ltx2_22B_distilled_gguf_q6_k` | `/home/ina/pinokio/api/Maestro.git/app/ckpts/ltx-2.3-22b-distilled-Q6_K_light.gguf` |
| `ltx2_22B_fp8` | `/home/ina/pinokio/api/Maestro.git/app/ckpts/ltx-2.3-22b-dev-fp8.safetensors` |

La LoRA requerida por Dev FP8 se resolvió, sin copia ni enlace simbólico,
desde:

`/home/ina/pinokio/api/Maestro.git/app/loras/ltx2/ltx-2.3-22b-distilled-lora-384.safetensors`

Tamaño comprobado: 7.605.507.256 bytes. El proceso efectivo de Maestro Next
recibió:

```text
MAESTRO_READ_ONLY_CHECKPOINTS=/home/ina/pinokio/api/Maestro.git/app/ckpts
MAESTRO_READ_ONLY_LORAS=/home/ina/pinokio/api/Maestro.git/app/loras
```

`files_locator.py` aplica precedencia local, consulta después la biblioteca
estable y dirige cualquier descarga nueva a `Maestro-next.git/app/loras`.
Una raíz declarada en `MAESTRO_READ_ONLY_LORAS` no puede reclasificarse como
escribible mediante configuración. Las pruebas cubren descarga simulada,
mutación, reset, precedencia y ausencia de symlinks.

No se realizó ninguna descarga durante esta fase.

## Dos semillas adicionales de Benchmark C

Petición común: 1280×720, 121 frames, 25 FPS, modelo caliente, misma imagen y
prompt. La salida efectiva de todas las ejecuciones fue 1280×704, 117 frames,
25 FPS y 4,68 s.

| Modelo | Seed | Total medido | Etapa 1 | Etapa 2 | VAE + escritura observada | VRAM pico | RSS pico | GPU media / pico |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Q6 | 171717 | 43,014 s | 16,002 s | 14,726 s | 11,736 s | 17.650 MiB | 18,48 GiB | 79,99 / 100 % |
| Q6 | 787878 | 40,909 s | 15,948 s | 14,779 s | 9,637 s | 17.650 MiB | 18,10 GiB | 83,40 / 100 % |
| INT8 | 171717 | 44,132 s | 11,630 s | 13,181 s | 18,109 s | 18.866 MiB | 19,35 GiB | 62,50 / 100 % |
| INT8 | 787878 | 44,571 s | 10,899 s | 13,128 s | 19,989 s | 18.866 MiB | 18,86 GiB | 60,50 / 100 % |
| **Mediana Q6** | — | **41,962 s** | **15,975 s** | **14,753 s** | **10,687 s** | **17.650 MiB** | — | — |
| **Mediana INT8** | — | **44,352 s** | **11,264 s** | **13,154 s** | **19,049 s** | **18.866 MiB** | — | — |

### Interpretación

Estas dos ejecuciones adicionales confirman la ventaja de INT8 en el núcleo
de difusión: 24,418 s de mediana frente a 30,728 s de Q6, una reducción del
20,5 %. No confirman una ventaja del total de pared por sí solas: el tramo
VAE/escritura de INT8 sufrió una variación anómala de 10–13 s después de
aparecer el vídeo temporal, y su mediana total quedó un 5,7 % por detrás.
Ese tramo usa el mismo VAE/códec y no es una diferencia del transformer.

La medición anterior de Fase 2A, sin esa anomalía de salida, fue 33,565 s para
INT8 y 43,108 s para Q6, un 22,1 % a favor de INT8. La recomendación se apoya
en ambas fases: difusión repetidamente más rápida, mejor fidelidad en las
semillas nuevas y la medición completa limpia de Fase 2A. No se presenta el
ruido de escritura como una victoria inexistente.

### Calidad de las semillas nuevas

| Modelo | Seed | PSNR primer frame | MAE primer frame | MAE fuente, todos | Movimiento entre frames, media / p95 |
|---|---:|---:|---:|---:|---:|
| Q6 | 171717 | 37,8911 dB | 1,9874 | 10,3354 | 0,5307 / 0,8726 |
| INT8 | 171717 | 38,3636 dB | 1,6336 | 6,9050 | 0,4298 / 0,8557 |
| Q6 | 787878 | 37,4464 dB | 2,0418 | 15,5008 | 0,8762 / 1,4776 |
| INT8 | 787878 | 38,2725 dB | 1,6609 | 10,6698 | 0,3345 / 0,8242 |

INT8 conservó mejor el primer frame en las dos semillas. Con `171717`, ambas
variantes mantuvieron personaje y estilo; INT8 completó un saludo y volvió a
la pose inicial con menos deriva. Con `787878`, Q6 alejó más la composición y
añadió hojas/partículas no solicitadas; INT8 mantuvo mejor los elementos
originales. No hubo pseudo-texto. Un MAE menor entre frames también puede
indicar menos movimiento, por lo que estas cifras se interpretaron junto con
los contact sheets.

## Cola realista de cuatro viñetas

La cola usa cuatro imágenes deterministas sin texto y cuatro prompts
distintos:

1. Heroína anime en una azotea.
2. Robot low-poly en un bosque.
3. Gato de cómic en una cocina.
4. Piloto enmascarado en un desierto de ciencia ficción.

Cada petición fue 768×512, 49 frames, 25 FPS, seed `626262`, 8 pasos
Distilled y sin LoRAs. Cada clip efectivo fue 768×512, 45 frames, 25 FPS y
1,80 s; el vídeo concatenado fue de 191 frames y 7,64 s.

El transformer INT8 ya estaba residente. Los cuatro prompts eran nuevos, de
modo que la prueba no obtuvo una ventaja artificial de textos repetidos.

| Viñeta | Imagen/preparación | Text encoding | Difusión | VAE | Escritura | Total percibido |
|---|---:|---:|---:|---:|---:|---:|
| 1 — azotea | 0,290 s | 94,990 s¹ | 20,551 s | 7,958 s | 1,684 s | 125,476 s |
| 2 — bosque | 0,321 s | 0,197 s | 11,537 s | 2,455 s | 0,761 s | 15,353 s |
| 3 — cocina | 0,253 s | 0,242 s | 11,521 s | 2,754 s | 1,436 s | 16,253 s |
| 4 — desierto | 0,206 s | 0,198 s | 10,941 s | 2,365 s | 1,923 s | 15,673 s |

¹ La primera viñeta carga el coste compartido de precalcular los cuatro
prompts en un único batch Gemma. Los clips 2–4 son hits exactos de caché; el
log interno midió 0,002 s por lookup. Repartido contablemente entre cuatro
viñetas, el coste de texto es 23,70 s por prompt, pero esa cifra no es la
latencia percibida de la primera viñeta.

Resultados agregados medidos:

- Cola caliente total: **173,840 s**.
- Carga de modelo durante la cola: **0 s; ya residente**.
- Batch de cuatro prompts: **94,760 s**.
- VRAM máxima: **19.320 MiB**.
- RSS máximo del árbol de proceso: **19,50 GiB**.
- GPU media / pico: **24,37 / 100 %**.
- Cinco sondeos de estado agotaron el timeout durante el batch Gemma; el
  proceso siguió trabajando y completó la cola.

Una ejecución fría diagnóstica tardó 311,843 s. La señal antigua agrupó carga
e imagen antes del inicio del batch, por lo que no se inventa una separación
más precisa para esa ejecución. La carga fría de INT8 medida de forma
independiente fue 100,404 s, y la localización/apertura caliente del checkpoint
medida en Fase 2A fue 0,005639 s.

### Inspección visual de la cola

- **Azotea:** conserva paleta y estilo, pero el push-in termina demasiado
  cerrado y modifica ropa/composición. La identidad simplificada se reconoce,
  aunque no es un resultado de producción.
- **Bosque:** hay movimiento real, pasos, lámpara y hojas; el robot conserva
  su geometría básica. La deriva lateral es visible pero coherente.
- **Cocina:** color, encuadre y cara del gato son estables; al acercarse al
  bol, la extremidad se transforma en una forma tubular.
- **Desierto:** es el clip más estable; mantiene piloto/vehículo, introduce
  polvo útil y no genera texto.

No aparecieron artefactos de `contain`/crop porque las referencias ya tenían
el lienzo objetivo exacto. No hubo pseudo-texto. La prueba muestra que la
optimización de cola funciona, pero también que prompts de cámara como
`push-in` deben limitarse más en presets de conservación estricta.

## Por qué un prompt nuevo tarda unos 90 segundos

El checkpoint de Gemma no se recarga para cada viñeta. El objeto de text
encoder permanece dentro del pipeline residente, pero MMGP mueve sus bloques
entre CPU y GPU cuando se invoca. El tokenizer LTX rellena cada prompt hasta
1.024 tokens y Gemma 3 12B debe ejecutar una pasada completa. Antes de esta
fase, `encode_text()` además recorría una lista de prompts de forma serial,
aunque la llamada superior indicase `parallel=True`.

Mediciones:

- Prompt nuevo Q6, ejecución fría controlada: 89,494 s.
- Prompt nuevo INT8, ejecución fría controlada: 96,697 s.
- Cuatro prompts nuevos en un único batch: 94,760 s.
- Prompt recuperado de caché: 0,002 s en el log del pipeline.

Por tanto, el cuello no era una nueva carga de checkpoint, sino el forward de
Gemma más las transferencias MMGP. Mantener Gemma permanentemente en GPU
mientras también reside el transformer INT8 de ~19 GiB no es seguro en una
RTX 4090 de 24 GiB.

## Optimización implementada

1. `encode_text()` procesa varios prompts en un único forward Gemma y divide
   los hidden states resultantes. Si el batch provoca CUDA OOM, retrocede a
   encoding serial sin perder el trabajo.
2. El primer trabajo de una cola LTX homogénea precalcula los prompts distintos
   siguientes. Colas con modelos mezclados no activan esta optimización.
3. Los embeddings quedan en una LRU del pipeline residente y se reutilizan en
   trabajos posteriores.
4. La clave es SHA-256 sobre prompt y configuración canónica: versión de
   esquema, pipeline Distilled/Dev, ID de modelo, familia, ruta real de Gemma y
   dtype. Distilled y Dev no pueden compartir embeddings por accidente.
5. Reiniciar o cambiar de modelo descarta deliberadamente la caché en memoria.
   No existe caché persistente en disco que pueda quedar obsoleta.
6. El API expone tiempos estructurados por viñeta y separa preparación,
   encoding, difusión, VAE y escritura.

No se solapó Gemma de forma asíncrona con la difusión de la viñeta actual:
ambos competirían por la misma GPU y aumentarían el riesgo de OOM. El
lookahead se ejecuta como batch justo antes de la primera difusión. El vídeo
se genera secuencialmente porque las cuatro imágenes son distintas y un batch
de vídeo excedería el margen razonable de una 4090; el batching se limita a
embeddings, donde fue compatible y medido.

## Dev FP8 con pipeline y LoRA correctos

Configuración medida:

- ID: `ltx2_22B_fp8`.
- 768×512 solicitados y efectivos.
- 49 frames solicitados; 45 efectivos.
- 25 FPS; 1,80 s.
- 30 pasos, CFG `3.0`, dos fases.
- Seed `626262`.
- LoRA distilled/refiner cargada desde la biblioteca estable de solo lectura.
- Perfil de memoria por trabajo: `3.5` VeryLowRAM/HighVRAM.

| Fase FP8 | Tiempo medido |
|---|---:|
| Carga del modelo | 5,759 s² |
| Preparación/aplicación de LoRA | 41,281 s |
| Text encoding, prompt + negativo en batch | 41,146 s |
| Primera etapa | 131,115 s |
| Segunda etapa | 10,393 s |
| VAE final | 5,083 s |
| Escritura | 1,205 s |
| **Total percibido** | **236,441 s** |

² El sistema conservaba page cache de la tentativa anterior; no representa
una carga fría desde almacenamiento.

Recursos medidos: 16.182 MiB de VRAM del servidor, 100 % de GPU pico,
32,69 % de GPU media y 53,41 GB de suma RSS del árbol. Esta suma incluye
mapeos compartidos y no equivale a RAM física exclusiva. No hubo timeouts ni
OOM con el perfil 3.5.

### Incidente y recuperación

El primer intento usó el perfil de vídeo 3. MMGP fijó en memoria reservada el
transformer (~20.791 MB) y la LoRA (~7.253 MB), además de Gemma y el resto del
pipeline. A las 13:12:02 el kernel registró un OOM global y mató un proceso
auxiliar `pinokio-bin` y Caddy. Maestro Next quedó fuera de servicio.

Pinokio se recuperó mediante su launcher y Next volvió a iniciarse aislado. La
repetición con perfil 3.5 desactivó la reserva pinned del transformer y
completó. No se modificó ninguna dependencia ni el perfil global de la
aplicación; el override se aplicó únicamente al benchmark FP8.

### Resultado visual FP8

FP8 preservó el primer frame casi igual que INT8:

| Variante | PSNR primer frame | MAE primer frame | MAE fuente, todos | Movimiento media / p95 |
|---|---:|---:|---:|---:|
| INT8, azotea | 37,2533 dB | 2,4318 | 47,1239 | 3,8499 / 5,8985 |
| FP8 Dev | 37,2488 dB | 2,4091 | 35,2096 | 5,1720 / 13,9432 |

FP8 produjo más movimiento, pero no una mejora de calidad utilizable: el zoom
fue excesivo, brazos/manos se deformaron y la ropa cambió. INT8 también cerró
demasiado el encuadre, pero mantuvo una geometría más estable. Ninguno añadió
pseudo-texto. Esta única prueba Dev se reporta como perfil de calidad, no como
una comparación de velocidad equivalente con Distilled.

## Presets definitivos para Next

| Preset | Modelo | Configuración recomendada |
|---|---|---|
| Preview rápido | INT8 Distilled | 512–768 px, 17–49 frames, 8+3 pasos |
| Balanced | INT8 Distilled | 768×512 o 512×768, 49 frames; subir a 720p cuando la composición esté aprobada |
| Calidad actual | INT8 Distilled | 1280×720 solicitado, 121 frames; el backend entrega 1280×704 / 117 frames |
| Low VRAM / Compatibility | GGUF Q6_K | Rollback visible; menor VRAM y mayor deriva en estas semillas |
| Quality Experimental | Dev FP8 | Solo prueba manual, perfil 3.5, 30 pasos + CFG + LoRA; no predeterminado |

Los defaults funcionales de vídeo, Director y cómic ya apuntaban al ID INT8
exacto `ltx2_22B_distilled_1_1`; no se introdujo un cambio de ID innecesario.
El catálogo ahora hace explícitas las etiquetas Recommended, Low VRAM y
Quality Experimental. No se eliminó compatibilidad anterior.

## Artefactos fuera de Git

JSON principales:

- `app/outputs/benchmarks/phase2b/queue-int8-hot.json`
- `app/outputs/benchmarks/phase2b/C-q6-seed171717.json`
- `app/outputs/benchmarks/phase2b/C-q6-seed787878.json`
- `app/outputs/benchmarks/phase2b/C-int8-seed171717.json`
- `app/outputs/benchmarks/phase2b/C-int8-seed787878.json`
- `app/outputs/benchmarks/phase2b/FP8-dev-quality-profile3_5.json`
- `app/outputs/benchmarks/phase2b/lora-audit-before.json`
- `app/outputs/benchmarks/phase2b/lora-audit-final.json`
- `app/outputs/benchmarks/phase2b/visual-analysis/`

Vídeos:

- `app/outputs/phase2b/2026-07-27-13h01m26s_seed626262_Preserve the exact anime heroine, rooftop composition, violet-orange palette, and cel-shaded style..mp4`
- `app/outputs/phase2b/2026-07-27-13h01m43s_seed626262_Preserve the exact small low-poly robot, mossy forest composition, teal-green colors, and faceted st.mp4`
- `app/outputs/phase2b/2026-07-27-13h01m59s_seed626262_Preserve the exact orange comic-book cat, kitchen composition, cream-red palette, and inked illustra.mp4`
- `app/outputs/phase2b/2026-07-27-13h02m14s_seed626262_Preserve the exact masked rider, science-fiction desert composition, cobalt-gold palette, and graphi.mp4`
- `app/outputs/phase2b/2026-07-27-13h02m14s_seed626262_multiclip.mp4`
- `app/outputs/phase2b/2026-07-27-14h30m18s_seed626262_Preserve the exact anime heroine, rooftop composition, violet-orange palette, and cel-shaded style..mp4`

Los vídeos de las semillas C se enumeran dentro de sus JSON respectivos. Todo
este árbol está ignorado por Git.

## Medido frente a extrapolado

Son mediciones:

- Los cuatro tiempos de cola y su total de 173,840 s.
- Las dos semillas adicionales por modelo.
- FP8 a 768×512, 45 frames efectivos y 236,441 s.
- VRAM, RSS, GPU, resoluciones, frames y FPS de las tablas.

Son extrapolaciones, no nuevas mediciones:

- Cuatro prompts seriales habrían costado aproximadamente 4 × 90–97 s; el
  batch real costó 94,760 s.
- Las estimaciones 720p de Fase 2A siguen siendo ~35 s para 5 s y ~58 s para
  10 s con INT8 caliente, con margen ±20–30 %. La variación de escritura de
  esta fase aconseja conservar ese margen.

## Validación

- 168 tests completos superados después del endurecimiento final de la raíz
  LoRA.
- `pip check` limpio, `git diff --check` limpio y sintaxis Python/Node limpia.
- El escaneo de secretos se registra en el cierre de la fase.
- La UI no se modificó; su build no es aplicable.
- Los launchers conservan el patrón obligatorio de captura de URL y
  `local.set`.
- La biblioteca estable se verifica por inodo, tamaño, mtime y estado Git
  antes del commit.

## Siguiente decisión

La Fase 2B no justifica sustituir WanGP/LTX por el backend oficial todavía.
INT8 resuelve bien la cola cuando se agrupa el text encoding y mantiene la
mejor combinación actual de velocidad, fidelidad y estabilidad.

Una evaluación posterior del backend oficial solo se justificaría si se busca
mejorar específicamente la estabilidad I2V/Dev o reducir la presión de RAM de
FP8. Debe seguir siendo un backend seleccionable y requerir autorización
antes de descargar el checkpoint de 46,1 GB.
