# 5/6 · Sonido ligado a la animación

> Hoja de ruta de calidad local (2026-10-03). Serie: [1 Render máster](01-render-master.md) ·
> [2 Iluminación HDRI y LUT](02-iluminacion-hdri-lut.md) · [3 Biblioteca CC0](03-biblioteca-cc0.md) ·
> [4 Personajes 3D](04-personajes-3d.md) · **5 Sonido** · [6 Control de calidad](06-control-calidad.md)
>
> Base comprobada: `origin/development` `ce070bee`. Estado: aprobado por el usuario el 2026-10-03, sin código (ver «Decisiones del usuario»).

## Objetivo

Que los vídeos deterministas suenen terminados:

- pasos que caen justo cuando el pie toca el suelo;
- un ambiente propio de cada escenario;
- música que baja sola cuando alguien habla;
- un volumen final correcto para cada plataforma.

Todo determinista: el mismo documento da el mismo audio.

## Qué hay hoy (comprobado en el código)

- **Video 3D mezcla en el navegador** (`ui/src/features/scene3d/speech/audio.ts:85-102`).
  - Usa un `OfflineAudioContext` a 48 kHz con efectos procedurales (`sfx`, `worldSfx`) y pistas de voz.
  - Cada pista tiene una ganancia constante. No hay ducking, compresión ni normalización. El límite son 180 s.
  - Existe la pista `soundtrack[]` (`ui/src/features/scene3d/types.ts:238`), pero la UI solo da una ganancia de 0 a 1
    (`ui/src/features/scene3d/speech/Scene3DSoundtrackControls.tsx:16`).
- **Efectos procedurales:** 15 sonidos sintetizados con semilla (`ui/src/features/sceneFx/audio.ts:51-75`). **No hay pasos.**
- **Montajes del editor** (`app/services/video_editor_layers.py`):
  - Las `audio_cues` tienen inicio, volumen y recorte (`:91-115`).
  - El ducking es un único valor global con `sidechaincompress` (`:118-120`, `:248-251`), más un limitador.
  - No hay fundidos por cue. La ruta de `core_editor.py` no tiene capas ni ducking.
- **Publicar** (`app/services/publish_presets.py:86-106`): `loudnorm` en dos pasadas, **fijo en −14 LUFS para todos los
  presets**. No hay objetivo por plataforma.
- **Patrón reutilizable:** `production_trailer_audio.py:80-89` baja la banda sonora en ventanas con una expresión `volume`
  por fotograma. Es la única envolvente de ganancia del código.
- **Sin datos de animación:** ningún clip guarda cuándo apoya cada pie, y ningún set de atmósfera
  (`atmos/definition.ts:19-35`) declara sonido.
- **Análisis disponible:** pulsos, compases y onsets en `app/services/audio_analysis.py:134-169`.

## Diseño

1. **Ducking determinista sin sidechain.** Los intervalos de diálogo se conocen de antemano (`slot.speech.clips`, las voces y
   las `audio_cues` de voz). La música recibe una envolvente: −10 dB, ataque de 120 ms y relajación de 400 ms, con un margen
   de 80 ms antes de cada frase. El mismo cálculo existe en TypeScript para Video 3D y como expresión `volume` de ffmpeg para
   el editor.
2. **Contactos de pie en cada clip.**
   - Al hornear, el worker ya sabe cuándo apoya cada pie (los apoyos de `app/services/humanoid_rig/motion.py`, que llega con el PR #765).
   - En los clips importados, los apoyos se detectan por altura y velocidad del tobillo y la punta.
   - Se guardan en el GLB como `extras.hocuspocus_contacts` del clip: `[{t, foot, strength}]`.
   - Video 3D convierte el tiempo del clip en tiempo de escena con `clipPlayback` (velocidad, inicio y bucle) o con el
     recorrido de [4 Personajes 3D](04-personajes-3d.md).
3. **Pasos.**
   - Un sonido `step` sintetizado con semilla, en 6 superficies: hierba, madera, piedra, nieve, arena y metal.
   - Si están instalados, se prefieren las muestras CC0 de la [3 Biblioteca CC0](03-biblioteca-cc0.md).
   - La superficie sale del set o de `floorStyle`; el volumen y el panorama, de la distancia y la posición del personaje en
     pantalla.
4. **Ambientes por set.** Un campo `ambience` en `AtmosSetDefinition` (viento, lluvia, insectos de noche, ciudad, cueva u
   océano), en bucle y con semilla, con ganancia propia. En los cortes del editor se funde con el plano siguiente.
5. **Volumen por plataforma.** Los presets llevan su objetivo y su pico real:

   | Preset | Objetivo | Pico real |
   |---|---|---|
   | YouTube y Shorts | −14 LUFS | −1 dBTP |
   | Apple | −16 LUFS | −1 dBTP |
   | Emisión (EBU R128) | −23 LUFS | −1 dBTP |
   | Archivo | sin normalizar | — |

   El recibo de exportación guarda el valor medido.

## Fases (un PR por fase)

### Fase 1 · Ducking y fundidos en Video 3D
- **Qué:** la envolvente de la banda sonora calculada a partir de los intervalos de voz, más fundidos de entrada y salida, en
  `speech/audio.ts`.
- **Pruebas:** el RMS de la música durante el diálogo queda al menos 8 dB por debajo; fuera de él no cambia (±0,5 dB); el
  resultado es idéntico entre dos exportaciones.
- **Quién:** delegable.

### Fase 2 · Volumen por plataforma y medida en el recibo
- **Qué:** objetivos por preset en `publish_presets.py`, la UI en `PublishPresetBar.tsx` y el LUFS medido en el recibo.
- **Pruebas:** cada preset queda a ± 1 LU de su objetivo y con un pico real de −1 dBTP o menos. Se amplía
  `tests/test_publish_presets.py`.
- **Quién:** delegable.

### Fase 3 · Contactos de pie
- **Qué:**
  - Extraer los contactos al hornear y al importar, y guardarlos en el GLB.
  - Una función en Video 3D que los convierte a tiempo de escena (velocidad, inicio, bucle y recorrido).
- **Pruebas:** los contactos del paseo horneado coinciden con los apoyos de `motion.py` (± 1 fotograma); un clip en bucle a
  velocidad 2 dobla la frecuencia; un clip importado de la biblioteca da contactos alternos izquierda y derecha.
- **Quién: Claude.** Une el rig del PR #765 con el reloj de la escena.

### Fase 4 · Pasos
- **Qué:**
  - El sonido `step` por superficie en `sceneFx/audio.ts` y la elección de superficie por set.
  - Atenuación por distancia y panorama.
  - Usar muestras de la biblioteca si están instaladas.
- **Pruebas:** el ataque de cada paso cae a ± 1 fotograma de su contacto; la misma semilla da la misma forma de onda.
- **Quién:** delegable.

### Fase 5 · Ambientes por set
- **Qué:** el campo `ambience` en los 20 sets, los fundidos en los cortes y su control en la UI.
- **Quién:** delegable. El usuario aprueba el carácter de cada ambiente.

### Fase 6 · Igualar el editor
- **Qué:** que la ruta de `core_editor.py` tenga las capas y el ducking por tramos, y fundidos por cue en
  `video_editor_layers.py`.
- **Quién:** delegable.

### Fase 7 · Reverb por set (opcional)
- **Qué:** un `ConvolverNode` con una respuesta al impulso sintética según el tamaño del espacio.
- **Quién:** delegable.

## Decisiones del usuario

- Cuánto baja la música bajo el diálogo: −10 dB por defecto.
- Qué objetivos de volumen ofrecer y cuál es el preset por defecto.
- Si los pasos y ambientes se activan solos en los documentos nuevos o hay que pedirlos.

## Riesgos

- **Pasos repetitivos.** Se varían la semilla, el tono y el volumen de cada paso; el pie izquierdo y el derecho llevan
  muestras distintas.
- **Límite de 180 s en la mezcla del navegador.** Para escenas largas, mezclar en el servidor con el render de
  [1 Render máster](01-render-master.md).
- **Clips importados con contactos dudosos.** Se pide una confianza mínima y, por debajo, no se generan pasos y se avisa.

## Fuera de alcance

Generar música o efectos con IA (ya existe con MMAudio), audio espacial binaural y Dolby Atmos.
