# Fase 1 — Auditoría LTX y línea base

Fecha de auditoría: 2026-07-27
Ámbito exclusivo: `/home/ina/pinokio/api/Maestro-next.git`
Rama: `experiment/linux-ltx-next`
Punto de partida: `0e242188b7f9383e26fe2e980bf8830b54d50162`

## Estado instalado

- La instalación de Pinokio completó sus 20 pasos y la UI React compiló.
- GPU: NVIDIA RTX 4090, 24.564 MiB, compute capability 8.9.
- Driver: 580.173.02.
- Python: 3.10.20.
- PyTorch: 2.7.0+cu128; CUDA disponible 12.8; BF16 disponible; cuDNN 9.7.1.
- Atención instalada y soportada: SDPA, Flash Attention 2, xFormers,
  SageAttention y SageAttention 2. La selección `auto` efectiva es `sage2`.
- Triton 3.3.0, xFormers 0.0.30, SageAttention 2.1.1,
  Flash Attention 2.7.4+cu128torch2.7, optimum-quanto 0.2.7,
  MMGP 3.7.6 y gguf 0.17.1.
- `pip check` queda limpio tanto en `app/env` como en el entorno aislado de
  Hunyuan3D. Se fijó Pillow 11.3.0 para respetar `gradio==5.29.0` y Ninja
  1.13.0 para sustituir la rueda 1.11.1.1 que `pip check` rechazaba en Linux.

Avisos no bloqueantes observados:

- Faltan dos guías opcionales de prompt de Dramabox.
- La compilación npm informa de siete vulnerabilidades transitivas y chunks
  grandes; el build termina correctamente.
- `npm run lint` conserva una deuda previa de 56 incidencias (52 errores y
  cuatro avisos) repartidas por archivos UI no modificados en esta fase.
- El kernel CUDA opcional para GGUF de llama.cpp no está disponible:
  `[GGUF][llama.cpp CUDA] kernels unavailable, using fallback`.

## Aislamiento y privacidad

El proceso efectivo de Next se ejecuta desde `Maestro-next.git/app` con:

```text
MAESTRO_READ_ONLY_CHECKPOINTS=/home/ina/pinokio/api/Maestro.git/app/ckpts
VIRTUAL_ENV=/home/ina/pinokio/api/Maestro-next.git/app/env
HF_HOME=/home/ina/pinokio/api/Maestro-next.git/cache/HF_HOME
TORCH_HOME=/home/ina/pinokio/api/Maestro-next.git/cache/TORCH_HOME
GRADIO_TEMP_DIR=/home/ina/pinokio/api/Maestro-next.git/cache/GRADIO_TEMP_DIR
```

Al inicio de la auditoría se encontró un `HF_TOKEN` copiado en el archivo
ignorado `ENVIRONMENT` de Next. Se eliminó únicamente de Next y se reinició
la aplicación. El archivo de entorno de Next ya no contiene claves, tokens,
secretos ni contraseñas. Pinokio sigue inyectando en el proceso su
autenticación global, cuya ruta declarada es
`/home/ina/pinokio/cache/HF_AUTH/anonymous`; esa credencial no procede de un
archivo de configuración de Next y nunca se imprimió.

No hay symlinks desde Next hacia Maestro estable. La biblioteca estable no
se modificó: el GGUF usado conservó inode `106304439`, tamaño
`16116771872` bytes y mtime `1785030921` antes y después de las pruebas.

### Demostración de `files_locator.py`

Con el cwd real de la aplicación:

```text
localizado:
/home/ina/pinokio/api/Maestro.git/app/ckpts/ltx-2.3-22b-distilled-Q6_K_light.gguf

is_read_only_path:
true

descarga simulada:
/home/ina/pinokio/api/Maestro-next.git/app/ckpts/ltx2/phase1-simulated-new-model.safetensors
```

No se creó el archivo simulado. Se añadieron protecciones para:

- redirigir a `app/ckpts` de Next incluso una ruta absoluta de descarga que
  apunte por error dentro de la raíz estable;
- impedir borrados de modelos compartidos desde el endpoint REST;
- impedir borrados compartidos desde el gestor gráfico de modelos;
- hacer que el catálogo detecte como descargados los modelos localizados en
  una raíz de solo lectura.

Las migraciones de nombres y la limpieza de modelos obsoletos ya comprobaban
`is_read_only_path`. `reset.js` solo elimina rutas relativas bajo Next y no
borra `app/ckpts` completo; su única limpieza de checkpoints es
`app/ckpts/model3d`, también local. Las siete pruebas de regresión de raíces
compartidas pasan.

## Inventario de modelos

Next no contenía `app/ckpts` ni pesos LTX/Wan/LLM propios antes de la prueba.
Las pruebas tampoco descargaron pesos.

Biblioteca estable compartida: aproximadamente 193 GB.

| Familia | Archivo o conjunto principal | Bytes |
| --- | --- | ---: |
| LTX-2.3 | `ltx-2.3-22b-dev-fp8.safetensors` | 29.943.017.118 |
| LTX-2.3 | `ltx-2.3-22b-distilled-1.1_diffusion_model_quanto_bf16_int8.safetensors` | 19.447.662.615 |
| LTX-2.3 | `ltx-2.3-22b-distilled-Q6_K_light.gguf` | 16.116.771.872 |
| LTX-2.3 | IC-LoRA union control | 654.465.352 |
| LTX-2.3 | Video VAE | 1.452.263.226 |
| LTX-2.3 | Audio VAE | 106.538.084 |
| LTX-2.3 | Embeddings connector | 4.032.404.584 |
| LTX-2.3 | Text embedding projection | 2.312.151.888 |
| LTX-2.3 | Vocoder | 258.347.744 |
| LTX-2.3 | Spatial upscaler x2 1.1 | 995.743.560 |
| LTX-2.3 | Temporal upscaler x2 1.0 | 261.944.000 |
| Gemma 3 12B | Quanto BF16 INT8 | 13.210.647.730 |
| Qwen3 8B | Quanto BF16 INT8 | 9.438.678.396 |
| Qwen3 embedding | Safetensors | 1.191.586.416 |
| LLM local | Gemma 4 E4B Q4_K_M + mmproj | 6.325.658.272 |

No se encontraron pesos Wan descargados. El catálogo ofrece variantes Wan,
pero todas estaban sin descargar. No se realizó ninguna descarga grande.

## Backend LTX actual

Maestro no invoca el paquete oficial como backend externo. Usa una copia
integrada y modificada de `ltx-core`/`ltx-pipelines` dentro de
`app/models/ltx2`, conectada al ciclo WanGP y al gestor MMGP de perfiles,
cuantización y offload.

Configuración efectiva del modelo usado:

- Modelo: LTX-2.3 Distilled GGUF Q6_K Light 22B.
- Pipeline: distilled, con primera pasada de 8 pasos y segunda de 3 pasos.
- Cálculo del transformer: BF16; pesos principales GGUF Q6_K.
- Text encoder: Gemma 3 12B Quanto BF16 INT8.
- VAE efectiva: FP16 (`vae_precision` por defecto).
- Atención: `auto`, resuelta a SageAttention 2.
- `torch.compile`: desactivado.
- Perfil de vídeo MMGP: 3.
- Coeficiente VRAM base: 0,8; para la prueba se ajustó a 0,744, con límite
  calculado de 17,5 GB.
- Offload: el transformer completo se fija en RAM, 64 bloques y
  15.389,45 MB reservados, y MMGP los transfiere según el perfil.
- Valores por defecto del Q6: 1280x720, 241 frames, 25 fps, 8 pasos,
  sliding window 481/17.
- Límites: mínimo 17 frames, incremento de 8 frames.

El backend conserva el modelo entre trabajos. No se observó recarga en la
segunda generación. La API marcaba erróneamente toda la familia LTX como no
T2V/no I2V; el handler ahora declara ambas capacidades.

## Benchmark reproducible

Script: `scripts/benchmark_ltx_phase1.py`

Parámetros:

```text
modelo=ltx2_22B_distilled_gguf_q6_k
resolución=512x512
frames=17
fps=25
pasos=8+3
seed=424242
guidance=1.0
LoRAs=ninguna
```

Prompt:

```text
A matte red toy sphere rests on a neutral gray tabletop. The camera remains
locked. The sphere rolls slowly to the right. Soft studio light, simple
background, no text, no cuts.
```

Resultados:

| Medida | Arranque frío | Modelo caliente |
| --- | ---: | ---: |
| Tiempo total | 266,7 s | 14,50 s |
| Primer progreso de difusión | 244,3 s | 3,10 s |
| Primera pasada, 8 pasos | ~5 s | ~5 s |
| Segunda pasada, 3 pasos | ~2 s | ~2 s |
| VRAM máxima del PID Next | no retenida por el primer recolector | 17.184 MiB |
| RSS máxima del árbol Next | no retenida por el primer recolector | 10.883.502.080 bytes |
| RAM usada máxima del sistema | no retenida por el primer recolector | 48.049.041.408 bytes |
| Salida | 512x512, 17 frames, 25 fps | 512x512, 17 frames, 25 fps |
| Duración final | 0,68 s | 0,68 s |

Durante la carga/codificación fría, el API dejó de responder en intervalos de
más de 30 segundos. La primera versión del recolector perdió los picos al
agotar su timeout; el script ahora tolera esos periodos y permite reconectar
por `job_id`.

La salida mantiene el objeto y el fondo, pero introduce pseudo-texto en el
suelo pese a la instrucción `no text`. Debe incluirse como defecto de
referencia en las comparativas de Fase 3.

## Verificación de cierre

- Suite Python completa: 154 pruebas, todas correctas.
- Regresiones de bibliotecas de solo lectura: siete pruebas, todas correctas.
- `pip check`: correcto en el entorno principal y en Hunyuan3D.
- Build UI (`tsc -b && vite build`): correcto.
- `git diff --check`: correcto.
- Escaneo de secretos de los cambios: sin coincidencias.
- Lint UI: no queda limpio por las 56 incidencias preexistentes descritas
  arriba; esta fase no modifica código de `ui/src`.

## Comparación preliminar con el repositorio oficial

Fuentes primarias consultadas:

- [Lightricks/LTX-2](https://github.com/Lightricks/LTX-2)
- [LTX-2 pipelines](https://github.com/Lightricks/LTX-2/tree/main/packages/ltx-pipelines)
- [LTX-2 core](https://github.com/Lightricks/LTX-2/tree/main/packages/ltx-core)
- [Lightricks/LTX-2.3](https://huggingface.co/Lightricks/LTX-2.3)

El runtime oficial actual:

- recomienda `ltx-2.3-22b-distilled-1.1.safetensors` para la ruta rápida;
- expone `DistilledPipeline` con ocho sigmas y pipelines de una/dos etapas;
- documenta `fp8-cast` más offload a CPU o disco para poca VRAM;
- incorpora block streaming desde buffers CPU fijados o disco;
- usa el spatial upscaler x2 1.1 y Gemma 3.

La biblioteca compartida ya contiene los upscalers oficiales y los
componentes auxiliares necesarios para la integración WanGP. No contiene el
checkpoint oficial BF16 de 46,1 GB con su nombre/formato original. El Q6,
el INT8 Quanto dividido y el FP8 actual son formatos adaptados; no debe
asumirse que el CLI oficial los cargará directamente. La compatibilidad
exacta y la reutilización sin descargas quedan como primera prueba de Fase 2.

## Decisión recomendada

Mantener WanGP/LTX como rollback y añadir el runtime oficial como backend
seleccionable solo después de un prototipo aislado. Para una RTX 4090, la
primera comparación debe usar el INT8 Quanto ya disponible contra el Q6:
el Q6 es rápido una vez caliente, pero su arranque frío de 4,4 minutos, los
cortes de respuesta y la ausencia del kernel GGUF CUDA lo hacen una mala
opción predeterminada. No descargar el checkpoint oficial de 46,1 GB hasta
confirmar expresamente tamaño, ubicación y objetivo con el usuario.
