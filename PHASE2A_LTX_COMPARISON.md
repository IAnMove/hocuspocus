# Fase 2A — Comparación LTX-2.3 en RTX 4090

Fecha de medición: 27 de julio de 2026. Repositorio:
`Maestro-next.git`, rama `experiment/linux-ltx-next`.

## Decisión

En el backend WanGP/LTX actual, **Quanto BF16 INT8 es la mejor variante
operativa para esta RTX 4090**. Frente a GGUF Q6_K:

- fue un 3,2 % más rápido en la mediana caliente del benchmark corto;
- fue un 22,1 % más rápido en la prueba representativa de 1280×704;
- mantuvo mejor o igual la identidad y el estilo de la referencia y produjo
  más movimiento útil;
- consumió aproximadamente 0,9–1,2 GiB más de VRAM, pero siguió por debajo de
  18,5 GiB de los 24 GiB disponibles.

No se ha cambiado el modelo predeterminado de la aplicación. GGUF queda
disponible como alternativa de menor VRAM y rollback. Dev FP8 no se ejecutó:
su pipeline no es equivalente al distilled y, en la configuración actual,
requiere una LoRA distilled de segunda etapa que no se puede localizar desde
la biblioteca `ckpts` compartida. Completarlo habría requerido descargar o
copiar 7.605.507.256 bytes, ambas acciones prohibidas para esta fase.

## Entorno verificado

| Componente | Valor |
|---|---|
| GPU | NVIDIA GeForce RTX 4090, compute capability 8.9, 24.564 MiB |
| Driver | 580.173.02 |
| Python | 3.10.20 |
| PyTorch | 2.7.0+cu128 |
| CUDA de PyTorch | 12.8 |
| NVCC | 12.8.93 |
| Flash Attention | 2.7.4+cu128torch2.7 |
| SageAttention | 2.1.1 |
| xFormers / Triton | 0.0.30 / 3.3.0 |
| GGUF / optimum-quanto | 0.17.1 / 0.2.7 |
| Attention de Maestro | `auto`; con este entorno selecciona SageAttention 2 |
| Perfil de offload | 3, safety coefficient 0,8 |
| `torch.compile` | desactivado |
| Salida | H.264 8-bit |

El proceso de Next recibió efectivamente:

```text
MAESTRO_READ_ONLY_CHECKPOINTS=/home/ina/pinokio/api/Maestro.git/app/ckpts
```

`app/ckpts` no existe en Next. No se hizo ninguna descarga, copia ni enlace.
Los tamaños, inodos y fechas de modificación de los tres checkpoints estables
se comprobaron antes y después y no cambiaron.

## IDs del catálogo y resolución de archivos

La auditoría reproducible se ejecuta con
`scripts/audit_ltx_phase2a_models.py`. `files_locator.py` encontró los tres
modelos principales en la raíz compartida, los marcó como solo lectura,
rechazó una operación de mutación simulada y dirigió una descarga simulada a
`Maestro-next.git/app/ckpts`.

| ID exacto de Maestro | Nombre del catálogo | Checkpoint resuelto | Tamaño | Apertura¹ |
|---|---|---|---:|---:|
| `ltx2_22B_distilled_gguf_q6_k` | LTX-2.3 Distilled GGUF Q6_K Light 22B | `/home/ina/pinokio/api/Maestro.git/app/ckpts/ltx-2.3-22b-distilled-Q6_K_light.gguf` | 16.116.771.872 B | 0,000277 s |
| `ltx2_22B_distilled_1_1` | LTX-2.3 Distilled 1.1 22B; se selecciona su alternativa Quanto BF16 INT8 porque el BF16 completo no está | `/home/ina/pinokio/api/Maestro.git/app/ckpts/ltx-2.3-22b-distilled-1.1_diffusion_model_quanto_bf16_int8.safetensors` | 19.447.662.615 B | 0,005639 s |
| `ltx2_22B_fp8` | LTX-2.3 Dev FP8 22B | `/home/ina/pinokio/api/Maestro.git/app/ckpts/ltx-2.3-22b-dev-fp8.safetensors` | 29.943.017.118 B | 0,010546 s |

¹ Tiempo para localizar, abrir y leer 1 MiB con la caché de páginas activa; no
es el tiempo de carga del modelo. Los tiempos de localización fueron,
respectivamente, 0,000043, 0,000031 y 0,000033 s.

VAE, codificadores de audio, vocoder, proyección, connector, upscaler y Gemma
INT8 también se resolvieron desde `ckpts` compartido como solo lectura.

### Por qué FP8 no es una tercera medición equivalente

Los modelos distilled se ejecutan en Maestro con 8 pasos de primera etapa,
guidance 1, y 3 pasos de refinado. Dev FP8 usa 30 pasos con CFG 3 en primera
etapa y 3 pasos distilled en segunda etapa. La propia definición del modelo
solicita:

```text
ltx-2.3-22b-distilled-lora-384.safetensors
```

El archivo existe únicamente bajo
`/home/ina/pinokio/api/Maestro.git/app/loras/ltx2/` y no pertenece a la raíz
compartida `app/ckpts`. Next no lo tiene en `app/loras`. WanGP intentaría
descargarlo en Next. No se activaron LoRAs en ninguna prueba y no se falseó un
Dev incompleto como si fuera comparable.

Esto coincide con el pipeline oficial: Distilled prioriza velocidad, mientras
que el pipeline Dev de dos etapas aplica una LoRA distilled para el refinado.
La documentación oficial actual usa 8 + 4 pasos para Distilled; la adaptación
de Maestro usa 8 + 3. Referencias:
[LTX-2 README oficial](https://github.com/Lightricks/LTX-2/blob/main/README.md)
y
[ltx-pipelines](https://github.com/Lightricks/LTX-2/blob/main/packages/ltx-pipelines/README.md).

## Metodología

Los scripts añadidos generan la referencia sin texto, adaptan la imagen
determinísticamente, envían un único trabajo por invocación, sondean GPU/RAM y
respuesta HTTP, guardan las transiciones de fase y verifican el vídeo con
`ffprobe`.

- Semilla fija: 424242.
- Sin LoRAs activas.
- Benchmark A: 512×512, 17 frames, 25 FPS, una ejecución fría y dos calientes.
- Benchmark B: misma imagen, prompt de movimiento y estrategia `contain`;
  768×512 y 512×768, 49 frames solicitados, 25 FPS.
- Benchmark C: los dos candidatos medibles, calientes, 1280×720 y 121 frames
  solicitados, 25 FPS.
- El servidor conservó un modelo residente entre trabajos del mismo modelo.
  Cambiar de modelo descarga el anterior y carga el nuevo.
- “Text/prep” incluye encoding del prompt y preparación posterior. Reutilizar
  exactamente el prompt aprovecha la caché; un prompt nuevo puede volver a
  tardar unos 90 s aunque el transformer siga residente.

El backend ajusta dimensiones y frames a sus restricciones internas. Por eso
Benchmark B entregó 47/48 frames, y Benchmark C entregó 1280×704, 117 frames y
4,68 s. Se informan siempre los valores efectivos, no los solicitados.

## Benchmark A — comparación corta

Todos los vídeos efectivos son 512×512, 17 frames, 25 FPS y 0,68 s.

| Modelo / ejecución | Total | Abrir checkpoint | Carga | Text/prep | Etapa 1 | Etapa 2 | VAE + encode² | VRAM pico | RSS pico | GPU media / pico | Fallos de sondeo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Q6 fría | 181,105 s | 0,000277 s | 55,959 s | 100,125 s | 11,112 s | 3,490 s³ | 9,877 s³ | 17.182 MiB | 32,20 GiB | 6,09 / 99 % | 0 |
| Q6 caliente 1 | 12,103 s | caché | residente | caché | 6,258 s | 2,711 s | 2,585 s | 17.184 MiB | 13,15 GiB | 61,64 / 100 % | 0 |
| Q6 caliente 2 | 12,241 s | caché | residente | caché | 6,617 s | 2,720 s | 2,362 s | 17.184 MiB | 13,12 GiB | 61,83 / 100 % | 0 |
| **Q6 mediana caliente** | **12,172 s** | — | — | — | **6,438 s** | **2,716 s** | **2,474 s** | **17.184 MiB** | **13,14 GiB** | **61,73 / 100 %** | **0** |
| INT8 fría | 233,997 s | 0,005639 s | 116,152 s | 96,069 s | 11,145 s | 2,710 s | 7,362 s | 18.082 MiB | 28,98 GiB | 2,95 / 98 % | 1 |
| INT8 caliente 1 | 11,697 s | caché | residente | caché | 6,010 s | 2,870 s | 2,273 s | 18.084 MiB | 18,20 GiB | 61,86 / 98 % | 0 |
| INT8 caliente 2 | 11,878 s | caché | residente | caché | 6,644 s | 2,179 s | 2,513 s | 18.084 MiB | 18,20 GiB | 53,41 / 98 % | 0 |
| **INT8 mediana caliente** | **11,788 s** | — | — | — | **6,327 s** | **2,525 s** | **2,393 s** | **18.084 MiB** | **18,20 GiB** | **57,64 / 98 %** | **0** |
| FP8 Dev | no ejecutado | 0,010546 s | — | — | — | — | — | — | — | — | — |

² En las ejecuciones iniciales la señal del API agrupa la decodificación VAE
con la creación del vídeo temporal. La visibilidad final del archivo tardó
0,04–0,08 s adicionales, pero eso no representa todo el encode.

³ El callback frío de Q6 emitió un “VAE Decoding” transitorio al terminar la
primera etapa. Los valores corregidos de etapa 2 y VAE proceden de las marcas
del log; no del parser anterior.

Una calibración posterior, con detección del archivo mientras aún se escribía,
midió 7,028 s desde VAE hasta la aparición del archivo y 0,712 s de escritura
restante. El códec es común a los modelos. Instrumentar el núcleo sería
necesario para separar con exactitud GPU VAE y encode para cada ejecución; no
se inventan cifras más precisas.

Durante la carga el servidor respondió a los sondeos. Hubo un único timeout
durante el encoding frío de INT8, no durante su carga. El transformer
distilled caliente tardó una mediana de 8,189 s en Q6 y 7,861 s en INT8.

## Benchmark B — image-to-video controlado

La primera prueba diagnóstica reveló que enviar directamente la imagen
cuadrada hacía que WanGP ignorase la orientación pedida. El harness genera
ahora un lienzo exacto con `contain`, usando el color de la esquina como fondo.
La prueba diagnóstica se excluyó de la tabla.

| Modelo / orientación | Estado | Total | Carga | Text/prep | Etapa 1 | Etapa 2 | VAE + encode | VRAM | RSS | GPU media | Salida efectiva |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Q6 landscape caliente | residente | 16,670 s | — | caché | 7,209 s | 5,468 s | 3,439 s | 17.282 MiB | 31,01 GiB | 68,97 % | 768×512, 47 f, 1,88 s |
| Q6 portrait caliente | residente | 16,612 s | — | caché | 7,180 s | 5,464 s | 3,423 s | 17.282 MiB | 31,05 GiB | 69,00 % | 512×768, 48 f, 1,92 s |
| INT8 landscape fría | cambio de modelo | 230,119 s | 115,800 s | 83,822 s | 15,548 s | 4,494 s | 8,621 s | 18.194 MiB | 30,91 GiB | 5,01 % | 768×512, 48 f, 1,92 s |
| INT8 portrait caliente | residente | 15,799 s | — | caché | 7,428 s | 3,810 s | 3,988 s | 18.198 MiB | 23,12 GiB | 55,75 % | 512×768, 48 f, 1,92 s |
| FP8 Dev | bloqueado | — | — | — | — | — | — | — | — | — | requiere LoRA no resoluble |

La fila landscape fría de INT8 sirve para calidad visual, no para comparar
latencia caliente. A igual número de píxeles y con modelo residente, INT8
portrait fue aproximadamente un 5 % más rápido que la media caliente de Q6.

### Métricas visuales reproducibles

Las métricas no sustituyen la inspección visual. MAE respecto a la fuente
también aumenta cuando hay movimiento intencionado.

| Variante | PSNR primer frame | MAE primer frame | MAE fuente, todos | Movimiento entre frames, media / p95 |
|---|---:|---:|---:|---:|
| Q6 landscape | 36,9810 dB | 2,0524 | 9,8999 | 1,2768 / 2,2070 |
| INT8 landscape | 36,8889 dB | 2,0923 | 7,3556 | 0,9999 / 1,9609 |
| Q6 portrait | 36,8298 dB | 2,0135 | 8,9678 | 1,8058 / 10,5650 |
| INT8 portrait | 36,6531 dB | 2,1199 | 9,7867 | 2,1821 / 8,6576 |

### Inspección visual

Ambos modelos conservaron el robot, los ojos asimétricos, antena, paleta,
composición y estilo low-poly. Ambos produjeron un saludo real y movimiento de
hojas; ninguno añadió texto o pseudo-texto ni mostró costuras en los bordes de
`contain`. La extensión del brazo se deforma moderadamente a mitad del saludo,
sin colapso de identidad.

Q6 introdujo más destellos blancos/estrellas no solicitados. En portrait tuvo
un zoom final más brusco, reflejado en el p95. INT8 mantuvo menos deriva en
landscape y produjo en portrait un acercamiento y un saludo algo más fuertes
pero graduales. Visualmente INT8 es el resultado más útil y estable.

## Benchmark C — prueba representativa

No se estimó riesgo de OOM: B dejó margen suficiente. No se cambió el perfil de
offload. Los dos modelos estaban calientes. La petición fue 1280×720, 121
frames, 25 FPS; ambos vídeos efectivos son 1280×704, 117 frames, 25 FPS y
4,68 s.

| Modelo | Total | Text/prep | Etapa 1 | Etapa 2 | VAE + encode | VRAM | RSS | GPU media / pico | Potencia media / pico |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Q6 | 43,108 s | 0,722 s | 15,382 s | 15,357 s | 11,054 s | 17.650 MiB | 28,12 GiB | 80,81 / 100 % | 324,25 / 442,82 W |
| **INT8** | **33,565 s** | caché | **11,100 s** | **13,104 s** | **8,188 s** | **18.866 MiB** | **21,54 GiB** | **85,20 / 100 %** | **296,42 / 425,48 W** |

INT8 redujo el total un 22,1 %; expresado en sentido inverso, Q6 tardó un
28,4 % más. Costó 1.216 MiB adicionales de VRAM.

| Modelo | PSNR primer frame | MAE primer frame | MAE fuente, todos | Movimiento media / p95 |
|---|---:|---:|---:|---:|
| Q6 | 37,9249 dB | 1,9639 | 11,4898 | 0,4034 / 0,9330 |
| INT8 | 38,2055 dB | 1,7285 | 13,5179 | 0,5760 / 1,2170 |

INT8 preservó mejor el primer frame y generó más movimiento intencionado,
manteniendo identidad y estilo. Q6 fue más estático y volvió a estirar el
brazo horizontalmente durante parte del saludo. No hubo OOM, timeouts ni
caídas del servidor.

## Rutas de resultados

Todos los artefactos pesados están ignorados por Git dentro de:

```text
/home/ina/pinokio/api/Maestro-next.git/app/outputs/phase2a
/home/ina/pinokio/api/Maestro-next.git/app/outputs/benchmarks/phase2a
```

Los nombres distinguen las ejecuciones por hora:

| Prueba | Q6 | INT8 |
|---|---|---|
| A fría | `2026-07-27-04h39m25s_…mp4` | `2026-07-27-04h44m58s_…mp4` |
| A caliente 1 | `2026-07-27-04h40m03s_…mp4` | `2026-07-27-04h45m17s_…mp4` |
| A caliente 2 | `2026-07-27-04h40m15s_…mp4` | `2026-07-27-04h45m29s_…mp4` |
| B landscape | `2026-07-27-04h51m36s_…mp4` | `2026-07-27-04h55m53s_…mp4` |
| B portrait | `2026-07-27-04h51m53s_…mp4` | `2026-07-27-04h56m11s_…mp4` |
| C 720p | `2026-07-27-05h03m07s_…mp4` | `2026-07-27-04h59m10s_…mp4` |

Los JSON completos conservan payload, fases, muestras de recursos,
responsividad y ruta absoluta. `contact-sheets/` contiene seis hojas de
contacto.

## Aviso GGUF: `[GGUF][llama.cpp CUDA] kernels unavailable, using fallback`

### Qué intenta cargar y por qué falta

`app/shared/qtypes/gguf.py` intenta exactamente:

```python
import llamacpp_gguf_cuda
```

El módulo no está instalado. `app/scripts/install_gguf_kernels.py` es anterior
a los binarios Linux actuales: en Linux termina sin instalar y todavía afirma
que no hay wheel. Además, el wheel precompilado publicado que corresponde a
Python 3.10/CUDA 12.8 fue construido para PyTorch 2.7.1, mientras este entorno
usa 2.7.0; una extensión CUDA no debe darse por compatible a través de esa
frontera ABI.

Sí existe una opción Linux publicada:
`llamacpp_gguf_cuda-1.0.2+torch271cu128py310-cp310-cp310-linux_x86_64.whl`.
Fuentes primarias:
[release GGUF Kernels](https://github.com/deepbeepmeep/kernels/releases/tag/GGUF_Kernels),
[código llama.cpp de los kernels](https://github.com/deepbeepmeep/kernels/tree/main/llama.cpp)
y
[instalación actual de WanGP](https://github.com/deepbeepmeep/Wan2GP/blob/main/docs/INSTALLATION.md).

### Qué sigue en CUDA y qué usa fallback

El aviso no significa que toda la generación caiga a CPU. Para Q6_K, Maestro:

1. mueve los bloques GGUF al dispositivo CUDA de la entrada;
2. ejecuta `_dequantize_blocks_Q6_K` mediante operaciones PyTorch en CUDA;
3. aplica `torch.nn.functional.linear` en CUDA.

Attention usa SageAttention 2; VAE, upscaler y denoising también usan CUDA.
El text encoder Quanto INT8 usa Triton, confirmado por el log. MMGP mantiene el
offload CPU/GPU.

La ruta fallback es la desquantización PyTorch y el `linear` separado para
cada capa, en vez del `linear`/MMQ/CUBLAS y embedding fusionados expuestos por
`llamacpp_gguf_cuda`. Algunos qtypes no implementados sí pueden caer a
`gguf.quants.dequantize(raw.cpu().numpy())`; Q6_K tiene implementación PyTorch
específica y no tomó esa ruta NumPy/CPU.

### Beneficio probable y riesgos

WanGP estima en su documentación alrededor de un 15 % sobre la porción de
difusión de vídeo; no se midió aquí porque no se instaló el kernel. Aplicado
de forma optimista a los 29,251 s de transformer de Q6 en C, ahorraría unos
4,4 s: total aproximado 38,7 s, todavía por encima de los 33,565 s medidos de
INT8. También debería reducir materializaciones y asignaciones transitorias,
pero la ganancia real depende de formas, offload y cobertura del kernel.

Riesgos:

- importar un wheel con ABI de Torch 2.7.1 en Torch 2.7.0 puede fallar o ser
  inestable;
- actualizar Torch puede obligar a reinstalar o romper Flash Attention,
  SageAttention y xFormers;
- compilar contra 2.7.0 exige NVCC/toolchain, tiempo y validación de todos los
  qtypes usados;
- un instalador global o sin `--no-deps` podría reemplazar dependencias
  importantes.

**Recomendación:** no instalarlo ahora. Si se autoriza una prueba posterior,
hacerla primero en un clon del entorno Next o entorno aislado, sin dependencias
automáticas. La opción conservadora es compilar el código contra Torch 2.7.0
con `TORCH_CUDA_ARCH_LIST=8.9`; la otra es validar el wheel exacto después de
alinear todo el stack a Torch 2.7.1. Ninguna debe tocar Maestro estable.

## Recomendaciones por perfil

Sin cambiar aún los defaults:

| Perfil | Recomendación |
|---|---|
| Preview rápido | Quanto BF16 INT8 distilled, 8+3 pasos, 17–49 frames y resolución reducida |
| Equilibrado | Quanto BF16 INT8 distilled con el perfil de offload actual |
| Calidad | Quanto BF16 INT8 para producción actual a 720p; Dev FP8 queda como candidato futuro, no como recomendación medida |

GGUF Q6_K sigue siendo útil cuando interesa ahorrar aproximadamente 1 GiB de
VRAM o como rollback. Con 24 GiB, esa ventaja no compensó su menor rendimiento
en C. Dev FP8 puede tener un techo de calidad mayor por su pipeline de 30 pasos
y CFG, pero no existe evidencia medida local que permita recomendarlo todavía.

## Estimaciones para 720p

Son **extrapolaciones**, no mediciones. Se ajustó una aproximación lineal usando
B y C, se mantuvo el modelo caliente y se asumió el mismo movimiento, códec,
offload y número de pasos. El backend producirá probablemente 1280×704.

| Duración pedida | Q6 estimado | INT8 estimado |
|---|---:|---:|
| 5 s | ~45 s | ~35 s |
| 10 s | ~80 s | ~58 s |

Margen razonable: ±20–30 %, especialmente a 10 s. La medición más cercana,
claramente separada de la extrapolación, fue C: 4,68 s efectivos en 43,108 s
con Q6 y 33,565 s con INT8.

## Conclusión de Fase 2A

La adopción de GGUF no fue la mejor elección de rendimiento para esta RTX
4090: ahorra memoria, pero INT8 es más rápido y al menos igual de sólido
visualmente. La decisión recomendada es **migrar en una fase posterior los
presets de Next a INT8, conservando GGUF como alternativa**, sin hacerlo en
este commit.

No hace falta alterar el stack CUDA para justificar esa decisión. Una futura
evaluación del backend oficial solo se justifica para probar correctamente Dev
FP8/calidad, resolver de forma explícita su LoRA de refinado y comparar la
semántica oficial de frames/resolución; no para perseguir velocidad inmediata.
No se inicia esa integración ni se descarga ningún modelo en esta fase.
