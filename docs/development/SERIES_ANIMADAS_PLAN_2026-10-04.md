# Plan: series de animación fáciles en HocusPocus (3 fases)

Fecha: 2026-10-04. Parte de la producción de «Uncanny Valley / Valle Inquietante» y de
`docs/development/SERIE_ANIMADA_MCP_PROBLEMAS_2026-10-04.md` (los números «P#» remiten a ese documento).

## Objetivo

Cualquiera debe poder hacer en Series Lab, sin escribir código, una serie de animación de recortes (al estilo de una sátira de televisión) con personajes que hablan en varios idiomas. Un agente debe poder hacer lo mismo por MCP con los mismos pasos.

Hoy la producción necesitó scripts externos para cinco cosas:

- dibujar y colocar las bocas;
- diseñar y comprobar las voces;
- colocar cada personaje según el encuadre;
- compilar el lip-sync;
- ensamblar.

El plan mete cada una de esas piezas en la app.

## Principios

1. **Un solo camino.** UI, Wizard y MCP llaman al mismo servicio de servidor. La pestaña del navegador nunca es la que trabaja.
2. **Todo queda editable.** Lo que se genera automáticamente acaba como Character Kits, escenas Video 2D/3D y tomas normales.
3. **Voces por rasgos, no clones.** Las voces se diseñan a partir de una descripción. Clonar una voz exige una grabación propia con consentimiento.
4. **Calidad medible.** Cada paso automático devuelve métricas (transcripción, tono, cobertura del lip-sync) y avisa, sin bloquear.

## Fase 1 — Personajes en un clic y arreglos de base

### 1A. Arreglos de los problemas detectados

| Arreglo | Problema | Estado |
|---|---|---|
| Cola con anti-inanición: un trabajo que lleva más de N s esperando no puede ser adelantado. `priority` documentado en `generation.*` | P8 | Hecho (`HOCUS_QUEUE_MAX_WAIT_SECONDS`, 300 s) |
| El render 3D no espera indefinidamente a que se vacíe la cola de la GPU | P14.2 | Hecho (`HOCUS_GPU_WAITER_MAX_WAIT_SECONDS`, 120 s) |
| La memoria de los modelos liberados vuelve al sistema | P9 | Hecho (`malloc_trim`; causa medida: arenas de glibc) |
| Presupuesto de RAM por familia de modelos antes de cargar | P9 | Pendiente: la causa medida ya está corregida |
| Una exportación 3D interrumpida aparece en `jobs.leftovers` y se reanuda | P9 | Hecho (`jobs.resume` / `jobs.discard`) |
| Los efectos de pantalla sin `color` usan el color del catálogo (servidor y pintor) | P12 | Hecho, con las fuentes del renderer |
| `jobs.wait` al agotar el tiempo devuelve el trabajo vivo con `timed_out: true`, sin error | P13 | Hecho |
| `jobs.*` aceptan `input`, como el resto de comandos | P13 | Hecho |
| `studio.key` acepta `intent_id` y un color de croma (verde, azul o magenta) | P13, P14.4 | Hecho |
| `generation.sfx` respeta `output_name`; los errores de versión dicen la versión válida | P13 | Hecho |
| El puerto efectivo del servidor se publica en `settings/server-endpoint.json` | P13 | Hecho |
| `characters.save` informa de los campos ignorados | P3 | Hecho (`ignoredFields`) |
| La concurrencia de exportación 2D se ajusta al número de núcleos | P14.7 | Hecho (sin medir la ganancia) |
| El ensamblado normaliza la sonoridad (−16 LUFS) y escribe subtítulos SRT/VTT por idioma | P14.8, P14.9 | Hecho, probado con los dos capítulos |
| Un test exige `mutation` explícito en todos los catálogos MCP | P1 | Hecho (faltaban 19 en `production.*`) |

### 1B. Personajes en un clic

1. **Presets de estilo** (`app/shared/character_styles.json`), compartidos por UI y MCP:
   - fragmentos de prompt para personaje, pose, fondo y prop;
   - color de croma automático: magenta si la descripción contiene verde;
   - un primer estilo, «Recorte de cartulina» (cabeza redonda, ojos ovalados blancos, colores planos, textura de papel).
2. **Crear desde descripción**, en el Creador de personajes:
   - genera 3 candidatas sobre croma;
   - recorta el fondo automáticamente;
   - la elegida pasa a ser la pose base aprobada.
3. **Pose nueva**: misma identidad, usando la pose base como referencia, con recorte y rig automáticos.
4. **Rig plano automático** (servicio `flat_rig`):
   - detecta ojos y boca;
   - borra la boca pintada con inpainting;
   - dibuja 9 bocas vectoriales parametrizadas (ancho, curva, sonrisa ladeada, paleta «pantalla»);
   - crea el parpadeo con la forma exacta de los ojos;
   - calcula los anclajes de cada pose.

   El resultado es un Character Kit listo para hablar.
5. **Diseñar voz** por idioma:
   - descripción e idioma;
   - 3 candidatas con VoiceDesign;
   - métricas de `qa.speech` (transcripción, WER con números normalizados, tono medio, palabras por segundo);
   - la elegida se guarda como voz de referencia (`qwen3_tts_base`) del idioma;
   - si falta el modelo, se ofrece descargarlo.
6. **MCP**: `characters.rig.flat`, `qa.speech` y el catálogo de estilos.

**Aceptación:** de una descripción a un personaje que habla dos idiomas en menos de 5 clics, revisable y editable en el Creador.

## Fase 2 — «Generar todo» en el servidor

1. **`series.episode.render_native`**, en el servidor y reanudable:
   - voz de cada línea en el idioma de la serie;
   - escena Video 2D;
   - lip-sync fonético;
   - exportación;
   - toma importada.

   Sustituye al lote que hoy vive en la pestaña (P2).
2. **Maquetación por encuadre:**
   - general, a dos, medio y primer plano, con línea de ojos y escala por personaje;
   - posiciones de continuidad por localización;
   - anclajes de props en el fondo (pedestal, escritorio).
3. **Animación limitada:** botes al hablar, entradas a saltitos, temblor de pánico, parpadeo aleatorio, cámara fija o acercamiento lento en los remates.
4. **Operaciones de escena** en `scenes.video2d.edit` (P6), con el compilador de bocas en el servidor:
   - `mount_character`;
   - `add_line`, que añade audio, señales de boca y `dialogueBeat`;
   - `animate_talk`.
5. **Sonido y cartelas:**
   - cortinillas entre escenas, ambiente por localización y música de moraleja;
   - cartelas de aviso, título y fin con textos por idioma.
6. **Planificador:** el LLM existente propone planos con encuadre, reparto y cámara a partir del guion.

**Aceptación:** un capítulo de 3 a 5 minutos desde el guion con un botón, y cada plano editable.

## Fase 3 — Doblaje, 3D y acabado

1. **Versiones de idioma de un capítulo** (`episode.languageVersions`, P7):
   - mismos planos e ids de línea;
   - texto, audio, tomas y ensamblado por idioma;
   - selector de idioma en Planos y Resultados;
   - rótulos y cartelas localizados.
2. **Recortes que hablan en Video 3D** (P11): las bocas y el parpadeo del Character Kit se pintan sobre el recorte.
3. **Fondos 3D automáticos:** el set Atmos se renderiza como fondo en bucle y los planos 2D lo usan.
4. **Acabado:** fundidos de audio en los cortes, subtítulos incrustados opcionales, miniaturas y publicación.
5. **Series plantilla:** «empezar una serie como Uncanny Valley», con estilo, cabecera y cortinillas ya hechos.

## Orden y dependencias

- La fase 1A no depende de nada y desbloquea trabajos largos fiables. Va en su propio PR, encima del #795.
- La fase 1B depende del #795 (`voicesByLanguage`, `characters.*`).
- La fase 2 depende de 1B: usa el rig y las voces.
- La fase 3 depende de la 2: el doblaje reutiliza el render en servidor.
