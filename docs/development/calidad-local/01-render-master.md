# 1/6 · Render final de calidad máster

> Hoja de ruta de calidad local (2026-10-03). Serie: **1 Render máster** ·
> [2 Iluminación HDRI y LUT](02-iluminacion-hdri-lut.md) · [3 Biblioteca CC0](03-biblioteca-cc0.md) ·
> [4 Personajes 3D](04-personajes-3d.md) · [5 Sonido](05-sonido.md) · [6 Control de calidad](06-control-calidad.md)
>
> Base comprobada: `origin/development` `ce070bee`. Estado: aprobado por el usuario el 2026-10-03, sin código (ver «Decisiones del usuario»).

## Objetivo

Que cualquier vídeo determinista (Video 3D, Video 2D y el Scene Animator) pueda salir con bordes limpios, motion blur real,
hasta 4K y un máster sin pérdidas intermedias. Todo con los recursos locales de cada usuario: GPU si hay, CPU (SwiftShader)
si no. El resultado es el mismo en los dos casos; con CPU solo tarda más.

## Qué hay hoy (comprobado en el código)

| Camino | Cómo pinta | Límite | Códec |
|---|---|---|---|
| Video 3D en el navegador | Reloj determinista `t = i/fps` (`ui/src/features/scene3d/clock.ts:1-15`), `prepareFrame` + `paint` y dos `requestAnimationFrame` por fotograma (`exportFlow.ts:55-60`, `exportMp4.ts:44-46`) | 1920×1080 (`exportMp4.ts:17-25`) | WebCodecs H.264 de 4 a 24 Mbps (`exportMp4.ts:27-35`) |
| Video 3D en el servidor | Playwright abre `ui/world3d-render.html` y guarda un PNG por fotograma (`app/services/world3d_export.py`, `ownedRenderer.tsx:51`). Usa Vulkan, o SwiftShader con `HOCUS_SCENE_RENDER_DEVICE=cpu` (`world3d_export.py:116-148`) | 1080p (`:72-77`). Las escenas con voz se rechazan (`:773-775`) | x264 `fast`, crf 18 y `-threads 1` (`:239-267`) |
| Scene Animator | Fotograma a fotograma con WebCodecs (`SceneAnimatorPanel.tsx:1632-1708`). `MediaRecorder` solo es el respaldo si no hay WebCodecs (`:1431-1520`) | Hasta 4K (`:185-188`), pero con nivel H.264 4.0 | De 8 a 80 Mbps |
| Video 2D | El mismo servicio del servidor con `scene2d-render.html` y Canvas2D (`app/services/scene2d_export.py:217-300`) | 1080p heredado, aunque la UI ofrece 4K | x264 crf 18 |
| Editor de vídeo | Cadena de ffmpeg | Hasta 3840 (`app/services/video_editor.py:352-355`) | Cuatro o cinco recodificaciones con pérdida en crf 16-18 (normalizar, transiciones, capas, concatenar y publicar) |

Además:

- **El servidor recodifica todas las grabaciones subidas** (`app/services/core_scene_recording.py:104-112` →
  `scene_recording.py:90-150`, crf 18 `fast`). Un MP4 ya determinista pierde una generación sin necesidad.
- **No hay antialiasing en el composer.** No hay SMAA, FXAA, TAA ni `samples` MSAA en los render targets. Cuando una escena
  usa atmósfera o efectos, el `antialias: true` del renderer (`gpu.ts:566-573`) probablemente deja de aplicarse. Hay que
  medirlo antes de arreglarlo (fase 0).
- **No hay motion blur.** La propia ficha de técnicas lo dice: «The renderer does not add motion blur»
  (`cinematicTechniques.json`). También están pendientes F44 (motion blur) y F49 (TAA) en
  `docs/development/procedural-video/FILTERS.md:115-127`.
- No hay 10 bits, 4:4:4, HEVC, ProRes ni DNxHD en ninguna parte. El preset `archive` es el mejor que existe: crf 12 `slow`
  (`app/services/publish_presets.py:13-36`).

## Diseño

1. **Un solo renderizador de calidad: el del servidor.** Ya es determinista, no depende de la memoria del navegador y
   funciona con GPU o con CPU. Los niveles nuevos se añaden ahí. La exportación del navegador se queda como borrador rápido.
2. **Niveles de calidad** con nombre, guardados en el recibo de exportación:

   | Nivel | Supersampling | Subfotogramas (motion blur) | Tamaño máximo | Salida |
   |---|---|---|---|---|
   | `borrador` (el de hoy) | 1× | 1 | 1080p | H.264 crf 18 |
   | `final` | 1,5× | 4 (obturador de 180°) | 1080p por defecto, 4K opcional | H.264 High crf 14 `slow` |
   | `master` | 2× | 8 | 1080p por defecto, 4K opcional | H.264 de entrega y, solo si se pide, un máster ProRes 422 HQ `.mov` |

3. **Supersampling.** El composer pinta a k veces el tamaño y la reducción se hace con un filtro Lanczos, en la página o con
   `scale=flags=lanczos` en ffmpeg. Bloom, profundidad de campo y rayos de luz deben usar el tamaño escalado
   (`cinematicRuntime.ts:111-121` construye el bloom a 1280×720).
4. **Antialiasing del composer.** Un render target con `samples: 4` en WebGL2 y SMAA como respaldo. Hay que reutilizar
   `atmos/passes.ts`; no se crea un segundo composer (regla de `docs/development/ATMOS_SETS.md:376-389`).
5. **Motion blur por acumulación.** Cada fotograma promedia N subfotogramas en los instantes
   `t + (j + 0,5)/N · obturador/fps − obturador/(2·fps)`, en un target de media precisión. Para que funcione,
   `prepareFrame(t)` tiene que ser una función pura del tiempo. La fase 2 empieza auditando eso: `Math.random`, estado
   acumulado, partículas, el `AnimationMixer` y el ritmo. El grano de la etapa de color se aplica una sola vez por fotograma,
   después de promediar, para que no se convierta en ruido.
6. **4K.** Se suben los topes de 1080p del servidor (`world3d_export.py:72-77`) y del cliente (`exportMp4.ts:17-25`) solo para
   `final` y `master`. Se usa el nivel H.264 correcto: 5.1 para 4K a 30 fps y 5.2 para 60 fps.
7. **Un máster sin pérdidas intermedias.**
   - Los PNG del servidor se codifican una sola vez: una entrega H.264 y, si se pide, un máster ProRes.
   - El servidor solo remultiplexa (`-c copy`) una subida que ya es H.264 + AAC con los fps correctos; deja de recodificarla.
   - El editor usa un intermedio casi sin pérdidas (x264 crf 0 `ultrafast`, o FFV1) y hace una sola codificación final.
8. **Estimación previa.** Antes de lanzar el render se muestra el tiempo por fotograma medido en esa máquina (GPU o CPU),
   multiplicado por el supersampling y los subfotogramas.

## Fases (un PR por fase)

### Fase 0 · Medir antes de tocar
- **Qué:**
  - Tres escenas de referencia: una de atmósfera (clearing), una de acción y un personaje GLB caminando.
  - Una métrica de dientes de sierra (energía de alta frecuencia en bordes) y SSIM contra una referencia a 4×.
  - Tiempo por fotograma en GPU y en SwiftShader.
  - Confirmar o descartar que las escenas con atmósfera pierden el antialiasing.
- **Archivos:** `tests/test_world3d_render_quality.py` (opcional, con `RUN_WORLD3D_RENDER_SMOKE=1`) y un script en `scripts/`.
- **Aceptación:** una tabla en este documento con las medidas reales de las tres escenas.
- **Quién:** delegable. Claude revisa la métrica.

### Fase 1 · Niveles de calidad, supersampling y antialiasing en el servidor
- **Qué:**
  - Un campo `quality` en la petición de exportación y en el recibo (`app/services/export_receipts.py`).
  - Composer escalado con MSAA o SMAA, y reducción con Lanczos.
  - El bloom y las demás etapas siguen el tamaño escalado.
- **Archivos:** `app/services/world3d_export.py`, `app/routers/world3d_export.py`, `ui/src/features/scene3d/ownedRenderer.tsx`,
  `cinematicRuntime.ts` y `atmos/composerBind.ts`.
- **Aceptación:**
  - La métrica de bordes baja al menos un 50 % y el SSIM contra la referencia a 4× es ≥ 0,98 en las tres escenas.
  - `borrador` queda idéntico al de hoy: mismo hash de PNG.
- **Quién: Claude.** Fija el contrato de niveles que usan las fases 2 a 5.

### Fase 2 · Motion blur determinista
- **Qué:**
  - Auditar que `prepareFrame(t)` es función pura del tiempo, con tiempos fraccionarios.
  - Acumular en float y aplicar el grano después de promediar.
  - Exponer el obturador en grados (180° por defecto).
- **Pruebas:**
  - Una escena estática da el mismo resultado con y sin blur (diferencia ≤ 1 LSB).
  - Un cubo a velocidad conocida deja una estela de longitud `v · obturador/fps` ± 10 %.
  - Dos renders del mismo fotograma dan el mismo hash.
- **Quién: Claude.** Es el punto con más riesgo de romper el determinismo.

### Fase 3 · 4K y niveles H.264 correctos
- **Qué:** subir los topes de 1080p solo en `final` y `master`, elegir el nivel 5.1 o 5.2, y corregir el nivel 4.0 que hoy
  usa el Scene Animator a 4K (`SceneAnimatorPanel.tsx:1632-1708`).
- **Aceptación:** `ffprobe` da 3840×2160 con un nivel coherente y el vídeo se reproduce en Chromium y en VLC.
- **Quién:** delegable, con el contrato de la fase 1 ya fijado.

### Fase 4 · Máster y fin de las recodificaciones
- **Qué:**
  - Entrega H.264 crf 14 `slow` y máster ProRes 422 HQ opcional, los dos desde los mismos PNG.
  - Remultiplexar (sin recodificar) una subida que ya es válida en `scene_recording.py`.
  - En el editor, un intermedio sin pérdidas y una sola codificación final.
- **Archivos:** `app/services/scene_recording.py`, `core_scene_recording.py`, `video_editor*.py`, `mix_concat.py` y
  `publish_presets.py`.
- **Aceptación:**
  - El SSIM de la entrega contra el máster es ≥ 0,99.
  - Una subida válida conserva el mismo flujo de vídeo (mismo hash del bitstream).
  - El editor hace una sola codificación con pérdida; se comprueba contando las llamadas a ffmpeg en los tests.
- **Quién:** delegable.

### Fase 5 · Voz en el render del servidor, UI y estimación
- **Qué:**
  - Que el render del servidor acepte escenas con voz: la mezcla de audio del cliente se reutiliza en la página headless.
  - Un selector de nivel y obturador en Video 3D, Video 2D y el Scene Animator.
  - La estimación de tiempo y de disco antes de lanzar el render.
  - Textos en español e inglés.
- **Quién:** la voz en el servidor la hace **Claude**, porque toca el contrato de audio de `exportFlow.ts`. La UI, la
  estimación y los textos son delegables.

## Decisiones del usuario

Decidido el 2026-10-03:

- **Tamaño:** 1080p es lo normal y el valor por defecto. 4K es el máximo y siempre opcional.
- **ProRes:** es opcional y está desactivado por defecto, porque ocupa unos 5-6 GB por minuto en 4K. La entrega siempre es
  H.264.
- **Aprobación artística:** la da el usuario, como en producción. Un «ok» técnico no aprueba el aspecto.

Pendiente:

- Si `final` y `master` se ofrecen también en CPU, con un aviso de tiempo, o solo con GPU.
- El nivel por defecto al exportar desde la app y desde MCP.

## Riesgos

- **Coste.** `master` en CPU es unas 32 veces más caro que hoy (2² de supersampling × 8 subfotogramas). La estimación previa
  es obligatoria.
- **Memoria en 4K.** Los targets en float a 4K con supersampling 2× no caben en GPUs pequeñas. Si no hay WebGL2 o no hay
  memoria, se cae a SMAA.
- **Determinismo.** Cualquier estado que dependa del fotograma anterior rompe la acumulación. La auditoría de la fase 2
  va primero.
- **Disco.** `/mnt/extras` está casi lleno. Los PNG temporales van a la carpeta de trabajos y se borran tras codificar.

## Fuera de alcance

Path tracing, HDR10/Dolby Vision y el render distribuido entre máquinas.

## Dependencias

- La [2 Iluminación](02-iluminacion-hdri-lut.md) añade coste por fotograma; la estimación de la fase 5 debe contarlo.
- El [6 Control de calidad](06-control-calidad.md) lee los PNG y el recibo con el campo `quality`.
