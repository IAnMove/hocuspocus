# 6/6 · Control de calidad antes y después de exportar

> Hoja de ruta de calidad local (2026-10-03). Serie: [1 Render máster](01-render-master.md) ·
> [2 Iluminación HDRI y LUT](02-iluminacion-hdri-lut.md) · [3 Biblioteca CC0](03-biblioteca-cc0.md) ·
> [4 Personajes 3D](04-personajes-3d.md) · [5 Sonido](05-sonido.md) · **6 Control de calidad**
>
> Base comprobada: `origin/development` `ce070bee`. Estado: aprobado por el usuario el 2026-10-03, sin código (ver «Decisiones del usuario»).

## Objetivo

Avisar **antes** de gastar el render y comprobar **después** el archivo, en los tres caminos deterministas: Video 3D,
Video 2D y el editor. Antes del render se detectan:

- personajes que atraviesan el suelo o flotan;
- cámaras dentro de la geometría;
- personajes fuera de plano.

Sobre el archivo exportado se detectan:

- fotogramas negros o congelados;
- saltos de cámara;
- audio saturado, demasiado bajo o con silencios.

## Qué hay hoy (comprobado en el código)

- **El control de calidad solo existe en las producciones musicales.** Video 3D, Video 2D y el editor no tienen ninguno.
  Sus recibos (`app/services/export_receipts.py`) solo copian el estado.
- **Comprobaciones de producción que se pueden reutilizar:**

  | Módulo | Qué mide |
  |---|---|
  | `production_review_checks.py` | `frozen_shot` con 4 muestras y bandas negras en los bordes; no detecta fotogramas negros enteros |
  | `production_clip_qa.py` | Estático, parpadeo, deriva de color y salto de identidad |
  | `production_smoothness.py` | Fotogramas repetidos y tirones, con ffprobe |
  | `lipsync_qa.py` y `qa_people.py` | Sincronía de labios y número de personas |

  Los veredictos son `ok`, `watch`, `fail` y `unreliable` (`production_review_layers.py`).
- **Validación estática:**
  - **2D** (`app/services/scene2d_validate.py` y `scene2d_text_boxes.py`): ya es buena (zona segura, solapes de texto,
    contraste medido, medios que faltan y tramos vacíos).
  - **3D** (`ui/src/features/scene3d/documentValidation.ts:37-45`): solo comprueba la forma del documento, sin geometría.
  - **Editor** (`ui/src/features/video-editor/actions.ts:161`): solo rechaza una línea de tiempo vacía.
- **No se usa ningún filtro de análisis de ffmpeg:** ni `blackdetect`, ni `freezedetect`, ni `silencedetect`, ni `astats`, ni
  `scdet`. `ebur128` solo se usa para normalizar al publicar (`publish_presets.py:86-117`).
- **Se pueden reutilizar:**
  - las hojas de contacto: `montage_preview.py` y el pintor de `video2d_preview.py`;
  - los muestreadores de fotogramas que ya existen;
  - `imageFootprint` (`imageGrounding.ts`), para recortes que flotan.

## Diseño

1. **Un solo formato de resultado**, el de las producciones: veredicto `ok`, `watch`, `fail` o `unreliable`, más una lista de
   avisos `{code, t, slot?, detail, evidence}`. Se guarda en el recibo de exportación y se expone por MCP como
   `qa.export`.
2. **Después del render, con sondas de ffmpeg sobre el archivo:**
   - `blackdetect` y `freezedetect`, respetando las pausas intencionadas: una lista `allow` por plano, como en producción;
   - `scdet` para saltos de cámara dentro de un plano;
   - `silencedetect`;
   - `astats` para el pico y las muestras recortadas;
   - `ebur128` comparado con el objetivo del preset ([5 Sonido](05-sonido.md));
   - la deriva de duración y fps que ya calcula `scene_recording.py`.
3. **Antes del render, la geometría en 3D.**
   - Se evalúa la escena cada 0,25 s sin pintar, con la misma `prepareFrame(t)`.
   - Para cada personaje: el contacto más bajo frente al suelo (atraviesa o flota), su caja frente a las de los props y los
     sets marcados como sólidos, y si está dentro del encuadre.
   - Para la cámara: si está dentro de la geometría.
   - Usa los contactos de pie de [4 Personajes 3D](04-personajes-3d.md) y [5 Sonido](05-sonido.md).
4. **Antes del render en 2D y en el editor:**
   - 2D: añadir el audio que falta o satura y los recortes flotando (`imageFootprint`).
   - Editor: huecos, fuentes con fps o resolución distintos y una estimación de saturación de la mezcla.
5. **Revisar antes de exportar.** Un panel con los avisos ordenados por gravedad. Cada aviso salta a su instante y la hoja de
   contacto marca los fotogramas señalados. **Nada se bloquea:** ni siquiera un `fail` impide exportar ni pide confirmación.
   Solo avisa.

## Fases (un PR por fase)

### Fase 1 · Sondas sobre el archivo exportado
- **Qué:**
  - El módulo `app/services/export_qa.py` con las sondas del punto 2.
  - Los avisos en el recibo y el comando MCP `qa.export`.
- **Pruebas con medios sintéticos:**
  - 1 s de negro se detecta con ± 1 fotograma.
  - 2 s congelados se detectan, salvo que estén permitidos.
  - Un seno a 0 dBFS da `clipping`.
  - −30 LUFS frente a −14 da `too_quiet`.
  - Un corte duro dentro de un plano da `camera_jump`.
  - Tres exportaciones limpias de referencia dan cero avisos.
- **Quién:** delegable, con la especificación de este documento. Claude revisa los umbrales.

### Fase 2 · Geometría en 3D antes del render
- **Qué:**
  - Evaluación sin pintar a lo largo de la línea de tiempo.
  - Comprobar suelo, colisiones con cajas, encuadre y cámara dentro de geometría.
  - Marcar como sólidos los props y sets necesarios.
- **Pruebas:**
  - Un personaje 10 cm bajo el suelo da `below_floor` en el instante correcto.
  - Uno 15 cm por encima, sin animación de salto, da `floating`; un salto de la biblioteca no da aviso.
  - Una cámara dentro de una pared da `camera_inside`.
  - Las escenas de plantilla incluidas dan cero avisos.
- **Quién: Claude.** Necesita el núcleo de evaluación compartido (previsto como PR 04 en
  `docs/development/VIDEO3D_PRODUCTION_PLAN.md:162-177`) y los contactos del rig.

### Fase 3 · Avisos previos en 2D y en el editor
- **Qué:** ampliar `scene2d_validate.py` (audio y recortes flotando) y añadir validación al editor (huecos, fps y
  resolución mezclados, saturación estimada).
- **Quién:** delegable.

### Fase 4 · Panel "Revisar antes de exportar"
- **Qué:** la lista de avisos con salto a su instante, la hoja de contacto con marcas y los textos en español e inglés.
  No hay confirmación ni bloqueo.
- **Quién:** delegable.

### Fase 5 · Ajuste de umbrales con material real
- **Qué:**
  - Pasar las sondas por 20 exportaciones reales (Gremlins v2, voices-v2 y escenas de plantilla).
  - Ajustar los umbrales y documentar los falsos positivos.
- **Quién:** delegable la ejecución. El usuario decide qué se considera aceptable.

## Decisiones del usuario

Decidido el 2026-10-03:

- **Los fallos de calidad solo avisan;** nunca bloquean nada.
- **El juicio artístico es humano**, como en producción.

Pendiente:

- Qué avisos se activan por defecto en exportaciones rápidas (`borrador`) y cuáles solo en `final` y `master`.
- Las tolerancias, en cm, para suelo y flotación.

## Riesgos

- **Falsos positivos que hacen ignorar los avisos.** La fase 5 es obligatoria antes de activarlos por defecto, y siempre se
  pueden permitir pausas o cortes intencionados.
- **Coste de evaluar sin pintar en escenas largas.** Se muestrea cada 0,25 s y en paralelo con el carril de CPU existente
  (`scene_export_lane.py`).
- **Sets sin colisiones declaradas.** Solo se comprueba lo que esté marcado; el resto se informa como `unreliable`.

## Fuera de alcance

El juicio artístico (sigue siendo humano, como en producción), la evaluación de vídeo generado por IA (ya existe en
producción) y VMAF.
