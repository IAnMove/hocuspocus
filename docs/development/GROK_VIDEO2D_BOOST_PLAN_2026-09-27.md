# Plan de mejora del creador Video 2D para Grok

Fecha: 27 de septiembre de 2026. Estado: **B0+B1 en [#497](https://github.com/IAnMove/hocuspocus/pull/497), B2 en [#502](https://github.com/IAnMove/hocuspocus/pull/502), B3 en [#509](https://github.com/IAnMove/hocuspocus/pull/509), B4–B6 en [#510](https://github.com/IAnMove/hocuspocus/pull/510), B7 en [#508](https://github.com/IAnMove/hocuspocus/pull/508), B8 en [#507](https://github.com/IAnMove/hocuspocus/pull/507).** B4, B5 y B6 comparten el pintor.
Autor del plan: Claude (revisará cada PR de Grok). Ejecutor: Grok.

## 1. Por qué

Los videoclips de ciudades, «The Bird Is Freed» y el tráiler «Musktopía» se
animaron con un motor de canvas escrito a mano fuera de HocusPocus, porque el
creador Video 2D (Scene Animator) no tenía lo necesario. El objetivo es que ese
tipo de pieza se pueda **componer, editar y exportar íntegramente como escena
Video 2D** (`*.scene.json` → `scenes.video2d.export`), sin perder calidad.

Referencia visual de lo que se hizo a mano (solo como inspiración, **no copiar
código**; ese motor es desechable):
`/mnt/extras/pinokio/cache/TMPDIR/claude-1000/-mnt-extras-pinokio-api-hocuspocus-development/5ca6d68f-96af-4a0e-8b0a-42e5379b9c63/scratchpad/papel/engine.js` y `fx2.js`
(rótulos con fecha, banners de estribillo sobre papel, contador de años, rayos
de luz, grano, gaviotas con aleteo, humo de cohete…). Si la ruta ya no existe,
seguir sin ella.

## 2. Estado actual (verificado en código el 27/9)

| Área | Dónde | Situación |
|---|---|---|
| Textos cinéticos | `ui/src/lib/kineticText.ts` (≈110 líneas) | 4 presets (`impact`, `rise`, `typewriter`, `wave`), 2 fuentes (`sans`, `mono`), un color, máx. 12 cues, contorno/sombra fijos en código. Sin caja de fondo, alineación, ancho máximo, espaciado, entrada/salida separadas. |
| UI de textos | `ui/src/components/common/KineticTextControls.tsx` | Formulario mínimo. |
| Esquema MCP de textos | `KINETIC_TEXT_SCHEMA` en `kineticText.ts`, usado por `ui/src/lib/sceneRecipe.ts` | `additionalProperties: false`: todo campo nuevo debe añadirse aquí. |
| Consumidores de `texts` | `lib/scene2d/normalize.ts`, `lib/scene2d/paint.ts`, `features/scene3d/document.ts`, `features/scene3d/ownedRenderer.tsx`, `sceneRecipe.ts`, `sceneToRecipe.ts`, `sceneNarrative.ts`, `sceneFile.ts` | **Los mismos textos pintan en 2D y en 3D.** Cualquier cambio debe mantener ambos. |
| Pintado 2D | `ui/src/lib/scene2d/{types,normalize,evaluate,layerStyle,paint}.ts` | Compartido por el editor, la exportación del navegador y el render sin interfaz (`ui/src/features/scene2d/ownedRenderer.ts`, `ui/scene2d-render.html`). Orden: capas → seam occluders → `paintSceneFx` → `paintKineticTexts`. |
| Atmósfera | `SceneLayer.atmosphere` (`ui/src/types/index.ts`, `SceneAtmosphereKind`) | 14 tipos (rain, snow, dust, embers, fog, smoke, ash, fireflies, confetti, bokeh, sparkles, bubbles, speedlines, leaves). **Siempre a pantalla completa**; no hay emisor en un punto ni pegado a una capa. |
| Efectos de pantalla | `ui/src/features/sceneFx/` + `app/shared/scene_effects.json` | **Bug**: `paint.ts` (fireworks) pasa `hsl(...)` a `glow()` de `energyBrush.ts`, que concatena `'00'` → color inválido → excepción al pintar. |
| Sonido de efectos | `app/services/scene2d_export.py` | El export sin interfaz rechaza `sfx[].sound = true` (`unsupported_capability`). |
| Ritmo | `ui/src/lib/sceneRhythm.ts` | «Hornea» keyframes a partir de un análisis de audio. No hay modulación en vivo guardada en la escena. |
| Plantillas | `ui/src/features/sceneTemplates/` (catálogo, builders, revisión) | Familias `cinema`, `music`, `space`. Ninguna de rótulos, documental, tráiler ni lyric video. |
| Letra alineada | `app/services/lyric_timeline.py` (`LyricSegment.words`, `align_authoritative_lyrics`, `build_timing_bundle`) | Ya existe el alineado palabra a palabra en el pipeline de videoclip; Video 2D no lo consume. |
| Fuentes | `ui/public/fonts/` | Solo la del logotipo. |
| Postproceso | — | No hay pase de acabado global (gradación, bloom, rayos, grano, viñeta, textura, bandas). |
| Secuencias de fotogramas | — | Una capa `image` no puede animar fotogramas ni sprite sheets. |
| Trayectorias | `animation.keyframes` | Solo interpolación entre puntos; no hay trayectoria curva con orientación. |

## 3. Reglas para Grok (obligatorias)

1. **Base.** Comprobar si el PR #494 (`feat/editable-montage-scenes`, que creó
   `ui/src/lib/scene2d/` y `scenes.video2d.export`) está mergeado en
   `development`. Si lo está, ramificar desde `origin/development`. Si no, ramificar
   desde `origin/feat/editable-montage-scenes` y decirlo en la descripción del PR.
   Trabajar en un **worktree aislado** (`git worktree add ../hocuspocus-worktrees/video2d-boost …`);
   no cambiar la rama del checkout compartido, no `reset`/`clean`/`stash` global.
2. **Leer antes de tocar**: `AGENTS.md`/`CLAUDE.md`, `docs/development/BRANCHING.md`,
   `CODE_HEALTH.md`, `LOCAL_VALIDATION.md`, `AGENT_QA_POLICY.md`,
   `SCENE_TEMPLATE_LIBRARY.md`, `SCENE_TEMPLATE_REVIEW.md`,
   `SCENE_EFFECTS_AND_MCP.md` y `docs/video-editor/MONTAGES.md`.
3. **Compatibilidad total**: toda escena guardada hoy debe pintarse **idéntica**
   (mismos píxeles) tras cada PR. Todos los campos nuevos son **opcionales** y su
   ausencia reproduce el comportamiento actual (incluidos el contorno `#07101e`,
   la sombra y la fuente `900 system-ui` actuales de los textos).
4. **Determinismo**: todo lo pintado es función pura de `(escena, segundo)`.
   Nada de `Math.random()` ni estado entre fotogramas; usar semillas
   (`fxRandom` de `features/sceneFx/types.ts`) e índice de fotograma.
   Retroceder en la línea de tiempo debe dar el mismo fotograma.
5. **Paridad**: editor, exportación en navegador y render sin interfaz usan el
   mismo código de `lib/scene2d/` y `lib/kineticText*`. No duplicar pintores.
   Si el editor previsualiza con DOM en vez de canvas, añadir un modo de vista
   previa «final» que use `paintScene2D`, en lugar de reimplementar efectos en CSS.
6. **Salud de código**: pasar `BASE_REF=origin/development bash scripts/check_code_health_pr_base.sh`.
   Funciones nuevas con complejidad ≤ 25. **No hacer crecer
   `ui/src/components/Sidebar/SceneAnimatorPanel.tsx`** (≈2.900 líneas): la UI
   nueva va en componentes propios y el panel solo los monta.
7. **Validación sin proveedores** en cada PR: `bash scripts/validate_local.sh`
   (o, como mínimo, `cd ui && npm run check` y `pytest` de los tests tocados).
   Registrar fallos previos de `development` por separado (hoy se conocen 3 en
   pytest: `director_cancellation` ×2 y `download_state` ×1).
8. **Sin GPU ni proveedores**. Nada de generar imágenes, música ni voz. Las
   demos usan medios ya existentes en `ui/public/examples/` o procedurales.
9. **Esquemas**: todo campo nuevo se refleja en `KINETIC_TEXT_SCHEMA` / los
   esquemas de `sceneRecipe.ts`, en los validadores Python de
   `scene2d_export.py` / `scene_documents.py` si recogen referencias de medios, y
   en i18n **es y en**.
10. **Límites**: todo array nuevo tiene un máximo explícito y se recorta al
    normalizar; nunca confiar en la entrada.
11. **Commits** con Conventional Commits; **un PR por bloque** (sección 5),
    abierto como *draft* contra `development`, con título `feat(video2d): …` o
    `fix(scene-fx): …`. Se pueden apilar PRs (base = rama del PR anterior),
    indicándolo en la descripción.
12. **Parar y preguntar** si un bloque exige cambiar un contrato existente de
    forma incompatible, tocar la cola de GPU o añadir dependencias npm/pip.

## 4. Entregables por PR (para la revisión de Claude)

La descripción de cada PR debe incluir:

- Qué contrato se añade (campos, límites, valores por defecto) y un ejemplo JSON.
- Evidencia de compatibilidad: una escena antigua exportada antes y después
  (hash o diff de fotogramas; ver bloque B0).
- **Demo**: una escena `*.scene.json` que use lo nuevo y su MP4 exportado con
  `scenes.video2d.export` (workspace `video2d-lab`), con la ruta en la descripción.
- Salida de los comandos de validación y lista de fallos previos.
- Tiempo por fotograma a 1920×1080 en el render sin interfaz, antes y después.
- Lo que **no** se ha hecho y por qué.

## 5. Bloques de trabajo

Orden recomendado. Cada bloque = un PR.

### B0 — Preparación y arnés de paridad (dentro del PR B1)

- [ ] Worktree, baseline de validación y medición del tiempo de render actual.
- [ ] Script `ui/scripts/scene2d-frame-hash.mjs` (Playwright + `scene2d-render.html`)
  que, dada una escena y una lista de segundos, pinta esos fotogramas y
  devuelve un hash por fotograma. Commitear 3 escenas de referencia en
  `ui/tests/fixtures/scene2d/` (una con textos v1 de los 4 presets, una con
  atmósferas y efectos de pantalla, y una con cámara, strips y relaciones) y sus
  hashes esperados. Si el hash varía entre ejecuciones en la misma máquina
  (antialiasing), comparar con tolerancia de diferencia de píxeles y documentarlo.
- [ ] Este arnés se usa en todos los PR posteriores como prueba de «no cambia
  nada de lo existente».

### B1 — `fix(scene-fx)`: colores con alfa y fireworks

- [ ] Helper `withAlpha(color, alpha)` en `features/sceneFx/` que acepte
  `#rgb`, `#rrggbb`, `rgb()/rgba()` y `hsl()/hsla()` (sintaxis con comas y con
  espacios) y devuelva un color CSS válido.
- [ ] Sustituir `color + '00'` en `glow()` y **auditar** con
  `grep -rn "+ '[0-9a-f]\{2\}'" ui/src/features/sceneFx ui/src/lib` cualquier otra
  concatenación de alfa sobre colores que puedan no ser hex.
- [ ] Test en `ui/tests/` que pinte `fireworks` (y cada efecto del catálogo)
  en un canvas simulado que lance error ante colores inválidos (o validar cada
  color con una expresión regular dentro de un contexto espía).
- Aceptación: exportar sin interfaz una escena con `fireworks` produce MP4.

### B2 — `feat(video2d)`: textos v2 (estilo, animación y fuentes)

Dividir `lib/kineticText.ts` en `lib/kineticText/{schema,parse,layout,state,paint,index}.ts`
y dejar `lib/kineticText.ts` como reexportación para no tocar consumidores.

Contrato (todos los campos nuevos son opcionales):

```ts
type KineticText = {
  // v1 — sin cambios
  id: string; text: string; start: number; end: number
  preset: 'impact' | 'rise' | 'typewriter' | 'wave'
  x: number; y: number; size: number; color: string; rotation: number
  font?: TextFont
  // v2
  enter?: { preset: TextEnter; duration: number }   // 0.05–3 s
  exit?: { preset: TextExit; duration: number }     // 0.05–3 s
  loop?: 'none' | 'wave' | 'pulse' | 'shake' | 'float' | 'flicker'
  weight?: 400 | 500 | 600 | 700 | 800 | 900
  align?: 'left' | 'center' | 'right'
  maxWidth?: number        // % del ancho del fotograma, 10–100; ajusta líneas por palabras
  lineHeight?: number      // 0.8–2
  letterSpacing?: number   // em, −0.1–0.5
  uppercase?: boolean
  italic?: boolean
  stroke?: { color: string; width: number }                  // width en em, 0–0.3
  shadow?: { color: string; blur: number; x: number; y: number } // em
  fill?: { kind: 'solid' } | { kind: 'gradient'; from: string; to: string; angle: number }
  box?: { kind: 'none' | 'solid' | 'paper' | 'pill' | 'bar' | 'underline' | 'plate';
          color: string; opacity: number; padding: number; radius?: number }
  counter?: { from: number; to: number; decimals: number; ease: 'linear' | 'ease' }
  template?: string        // procedencia (B3); no afecta al pintado
}
type TextFont = 'sans' | 'mono' | 'display' | 'condensed' | 'serif' | 'hand' | 'marker'
type TextEnter = 'none' | 'fade' | 'impact' | 'rise' | 'drop' | 'typewriter' | 'letters'
               | 'words' | 'blur' | 'wipe' | 'scale' | 'slide-left' | 'slide-right'
type TextExit  = 'none' | 'fade' | 'fall' | 'blur' | 'wipe' | 'scale' | 'slide-left' | 'slide-right'
```

- [ ] **Compatibilidad**: si faltan `enter`/`exit`/`loop`, se derivan de
  `preset` exactamente como hoy (`impact`/`rise`/`typewriter` = entrada, `wave` =
  bucle, salida = fundido de 0,3 s). `color` sigue siendo el relleno sólido.
- [ ] `counter`: el texto admite `{value}` (p. ej. `"{value}"` o `"Año {value}"`),
  sustituido en cada fotograma por el valor interpolado y formateado.
  `letters`/`words` animan por unidad con retardo escalonado.
- [ ] `box.kind = 'paper'`: textura procedural determinista (semilla del `id`),
  bordes irregulares y ligera rotación; sin imágenes externas. `plate` = placa de
  pantalla completa (para títulos sobre negro).
- [ ] Máximo de cues: de 12 a **48**. Longitud máxima del texto: 240 (sin cambios).
- [ ] **Fuentes**: autoalojar 5 familias con licencia OFL o Apache en
  `ui/public/fonts/` (woff2, subconjunto latin + latin-ext; total ≤ 600 KB):
  una display (tipo Anton o Bebas Neue), una condensada, una serif (tipo Playfair
  Display), una manuscrita (tipo Caveat) y una rotulador (tipo Permanent Marker).
  Añadir `ui/public/fonts/LICENSES.md` con origen y licencia de cada una.
  `@font-face` en `index.css`. **Sin CDN en tiempo de ejecución.**
- [ ] El render sin interfaz (`features/scene2d/ownedRenderer.ts`) y el de 3D
  (`features/scene3d/ownedRenderer.tsx`) deben esperar a
  `document.fonts.load(...)` de cada familia usada **antes** del primer fotograma.
  Añadir un helper compartido `ensureTextFonts(texts)`.
- [ ] UI: reescribir `KineticTextControls` en componentes pequeños
  (contenido, estilo, animación, caja), con secciones plegables y vista previa
  del preset. Mantener la API pública del componente.
- [ ] `KINETIC_TEXT_SCHEMA` y esquemas de receta/MCP actualizados; i18n es/en.
- Tests: parseo y límites; derivación v1→v2 (tabla de casos); `kineticTextState`
  por preset en instantes clave; salto de línea con `maxWidth`; `counter`;
  hashes de B0 sin cambios; demo con los 7 tipos de fuente y todas las entradas.

### B3 — `feat(video2d)`: plantillas de rótulo y letra karaoke

**Plantillas de texto** (`lib/kineticText/templates.ts`). Cada plantilla es
`{ id, labelKey, fields: [{ key, labelKey, default }], build(values, { start, duration, width, height }) => KineticText[] }`
y adapta posiciones y tamaños a 16:9 y 9:16 (zona segura vertical):

| id | Contenido |
|---|---|
| `lower-third-date` | Año/fecha grande + descripción debajo, barra de color, entrada deslizante. |
| `chorus-banner` | Frase sobre papel, fuente rotulador, entrada palabra a palabra, pulso. |
| `title-card` | Título display + subtítulo, entrada con desenfoque, opción de placa negra. |
| `end-card` | Título + llamada a la acción («Próximamente», @usuario). |
| `year-counter` | Contador `from → to` con rótulo opcional. |
| `quote` | Cita en serif cursiva con comillas, máquina de escribir, autor. |
| `trailer-slam` | N frases que golpean una tras otra sobre negro, repartidas en la duración. |
| `chapter` | Etiqueta pequeña en mayúsculas + título grande. |
| `social-caption` | Subtítulo vertical en la zona segura, caja tipo píldora. |

- [ ] UI: botón «Insertar plantilla» con los campos y una vista previa en miniatura.
- [ ] Las cues generadas llevan `template: id` y siguen siendo editables una a una.
- [ ] Exponer las plantillas en el catálogo de la receta/MCP (ids y campos).

**Letra sincronizada**: nuevo campo de escena (no son `texts`):

```ts
lyrics?: {
  mode: 'karaoke' | 'word-pop' | 'line-fade' | 'bounce'
  lines: Array<{ id: string; start: number; end: number;
                 words: Array<{ text: string; start: number; end: number }> }>  // ≤400 líneas, ≤4000 palabras
  style: { font: TextFont; size: number; color: string; activeColor: string; weight?: number
           x: number; y: number; maxWidth: number; align: 'left' | 'center' | 'right'
           uppercase?: boolean; stroke?; shadow?; box?; visibleLines: 1 | 2 }
  source?: { kind: 'timing-bundle' | 'srt' | 'lrc' | 'manual'; file?: string }
}
```

- [ ] Pintado en `lib/kineticText/lyrics.ts`, después de `texts`. En `karaoke`
  el relleno avanza dentro de cada palabra según su `start`/`end`; `word-pop`
  hace aparecer cada palabra; `line-fade` funde líneas; `bounce` salta la palabra activa.
- [ ] **Importadores** (UI, puros y testeados):
  1. Pegar LRC (con o sin marcas por palabra) o SRT; las palabras sin marca se
     reparten proporcionalmente a su longitud dentro de la línea.
  2. Desde un fichero de tiempos del pipeline de videoclip: localizar dónde
     `build_timing_bundle` / `lyrics_to_srt` guardan su salida en el workspace y
     leer esos `segments[].words`. No lanzar transcripción nueva en este bloque.
  3. Texto plano + duración: reparto uniforme (para editar luego).
- [ ] Desplazar todas las marcas con un `offset` al importar (la escena puede no
  empezar en el segundo 0 de la canción).
- [ ] Esquemas MCP, normalización (`normalize.ts`) e i18n.
- Tests: parsers LRC/SRT (casos con y sin palabras), reparto, límites, estado de
  karaoke en instantes concretos; demo de 20 s con la letra de «The Bird Is Freed»
  (o cualquier letra con tiempos existente en `app/outputs/x-song/`) en 16:9 y 9:16.

### B4 — `feat(video2d)`: pase de acabado («finish»)

Nuevo campo de escena, pintado en `lib/scene2d/finish.ts`:

```ts
finish?: {
  grade?: { exposure: number; contrast: number; saturation: number;
            temperature: number; tint: number; fade: number }        // −1..1 (fade 0..1)
  bloom?: { amount: number; threshold: number; radius: number }
  rays?: { amount: number; x: number; y: number; length: number; threshold: number }  // rayos de luz desde zonas brillantes hacia/desde (x, y)
  vignette?: { amount: number; softness: number }
  grain?: { amount: number; size: number }
  texture?: { kind: 'none' | 'paper' | 'film-dust' | 'scratches'; amount: number }
  letterbox?: { ratio: 1.85 | 2 | 2.39; color: string }
  applyToTexts?: boolean   // por defecto false: textos y letra quedan nítidos encima
}
```

- [ ] Orden: capas → efectos de pantalla → **finish** → textos → letra
  (con `applyToTexts` el finish va al final).
- [ ] Implementación en canvas 2D con lienzos auxiliares reutilizados (no crear
  canvas por fotograma): bloom = umbral + reducción + desenfoque + composición
  `lighter`; rayos = desenfoque radial por copias escaladas desde `(x, y)` sobre
  la máscara de brillo; grano/polvo/rayas = ruido con semilla = índice de
  fotograma; papel = patrón procedural cacheado por tamaño.
- [ ] Presupuesto: **≤ 25 ms por fotograma 1080p** con todo activado en el
  render sin interfaz. Si no se alcanza, documentar y bajar la resolución interna
  de bloom/rayos.
- [ ] UI: panel «Acabado» con 4 presets (Cine cálido, Documental antiguo,
  Neón nocturno, Papel/cómic) y controles finos.
- Tests: normalización y límites; funciones puras (curvas de gradación, semilla
  del grano); B0 sin cambios cuando `finish` falta; demo antes/después.

### B5 — `feat(video2d)`: emisores anclados, secuencias de fotogramas y trayectorias

**Emisores**: `atmosphere.emitter?`:

```ts
emitter?: { mode: 'frame' | 'point' | 'layer'; x?: number; y?: number
            targetLayerId?: string; offsetX?: number; offsetY?: number
            direction: number; spread: number     // grados
            rate: number; lifetime: number; speed: number; gravity: number }
```

- [ ] `frame` = comportamiento actual. `point`/`layer` emiten partículas
  cerradas en forma (nacimiento `i / rate`, posición = f(edad)), sin simulación.
  `layer` sigue el estado evaluado de la capa objetivo (humo tras el cohete).
  Rechazar dependencias circulares como ya hace `breakDependencyCycles`.
- [ ] Añadir tipos `sparks` y `exhaust` a `SceneAtmosphereKind` si hacen falta;
  reutilizar `smoke`, `bubbles` y `embers` con emisor.

**Secuencias de fotogramas** en capas `image`:

```ts
sequence?: { kind: 'frames'; sources: string[]; fps: number; loop: 'loop' | 'pingpong' | 'once' }   // ≤120 fuentes
         | { kind: 'sheet'; source: string; columns: number; rows: number; count: number; fps: number; loop: … }
```

- [ ] Precarga de todos los fotogramas en editor y render sin interfaz.
- [ ] **Backend**: `scene2d_export.py` (recogida de `refs`, `missing_ref`) y
  `scene_documents.py` (rechazo de `blob:`/remotas) deben recorrer también
  `sequence.sources` / `sequence.source`. Tests Python.

**Trayectorias**: `animation.path?`:

```ts
path?: { points: Array<{ x: number; y: number }>; orient: boolean; rotationOffset?: number }  // 2–32 puntos, Catmull-Rom
```

- [ ] Recorrido parametrizado por longitud de arco; el progreso usa la curva de
  la animación; `x`/`y` salen de la trayectoria y escala/opacidad siguen saliendo
  de keyframes. `orient` gira la capa según la tangente.
- [ ] UI: editar puntos arrastrando sobre la vista previa (componente propio).
- Tests: evaluador (posición y ángulo en t), límites, backend de refs; demo con
  un pájaro de 6 fotogramas volando en curva y un cohete con humo anclado.

### B6 — `feat(video2d)`: modulación con el ritmo

- [ ] Campo de escena `rhythm?: { bpm: number; beats: number[]; downbeats?: number[]; energy?: { fps: number; values: number[] } }`
  (≤ 2000 beats, energía ≤ 6000 valores), **guardado en la escena** para que el
  render sin interfaz sea determinista. Se rellena en la UI a partir del
  análisis de audio que ya usa `sceneRhythm.ts` (sin análisis nuevo en servidor).
- [ ] Consumidores: `KineticText.beatPulse?: number` (0–1), `lyrics.style.beatPulse`,
  `finish.bloom.beat?: number` y `finish.grade.beatFlash?: number`, y en capas
  `beatPulse?: { amount: number; on: 'beats' | 'downbeats' }` aplicado en el
  evaluador (escala), además de lo que ya hornea `applySceneRhythm`.
- [ ] Documentar la diferencia entre «hornear keyframes» (existente) y
  «modulación en vivo» (nueva).
- Tests: envolvente del pulso alrededor de un beat; sin `rhythm` = sin cambio.

### B7 — `feat(video2d)`: plantillas de escena completas

Añadir a `features/sceneTemplates/`, siguiendo `SCENE_TEMPLATE_LIBRARY.md` y el
flujo de revisión (`catalogReview.ts`, `reviewDecisions.ts`) como **candidatas
pendientes de revisión**, nunca aprobadas por el propio Grok:

| id | Composición |
|---|---|
| `documentary-history` | Foto con Ken Burns + paralaje, `lower-third-date`, `year-counter`, acabado «Documental antiguo», polvo. |
| `trailer-teaser` | Planos cortos + `trailer-slam` sobre negro, `title-card`, `end-card`, bandas 2.39, bloom. |
| `lyric-vertical` | 1080×1920, fondo con movimiento lento, `lyrics` en karaoke, `beatPulse`, acabado «Neón nocturno». |
| `city-postcard` | Plano de ciudad en strip, `chorus-banner` sobre papel, gaviotas en secuencia con trayectoria, rayos de sol. |

- [ ] Slots con medios de `ui/public/examples/`; nada generado.
- [ ] Las plantillas producen `layers` + `texts` + `lyrics` + `finish` y pasan
  por `scenes.video2d.export` sin error.
- Tests del compilador de plantillas; demo MP4 de cada una en `video2d-lab`.

### B8 — `feat(video2d)`: sonido de efectos de pantalla en la exportación sin interfaz

- [ ] En `scene2d-render.html`, sintetizar el audio de `sfx[].sound` con
  `OfflineAudioContext` reutilizando `features/sceneFx/audio.ts` y
  `sceneAudioWav` de `audioExport.ts`; devolverlo por el puente
  `__scene2dExport` como WAV.
- [ ] `scene2d_export.py`: dejar de rechazar `sound: true`; mezclar ese WAV con
  los `audioTracks` en `finish_media`. Actualizar el test parametrizado que hoy
  espera `unsupported_capability` y `MONTAGES.md` §4.
- Tests: Python con renderer inyectado que devuelve un WAV; UI del sintetizador
  offline si es testeable en node, si no, smoke con Playwright.

## 6. Fuera de alcance

- Generar medios con modelos (imágenes, música, voz) o usar la cola de GPU.
- Reescribir `SceneAnimatorPanel.tsx` más allá de montar componentes nuevos.
- Capas `model3d` en el export 2D.
- Composición vertical con fondo difuminado en el Editor de vídeo (otro plan).
- Rehacer los videoclips existentes: lo hará Claude cuando esto esté mergeado.

## 7. Revisión de Claude

Por cada PR, Claude comprobará:

1. Contrato: campos opcionales, límites, normalización, esquemas MCP, i18n.
2. Compatibilidad: hashes de B0 y escenas guardadas reales (`app/outputs/*/*.scene.json`).
3. Determinismo: fotograma en t tras saltar hacia atrás = fotograma en t en secuencia.
4. Paridad editor ↔ render sin interfaz (misma función de pintado).
5. Rendimiento: ms/fotograma frente a la línea base.
6. Salud de código (ratchet), tamaño de `SceneAnimatorPanel.tsx`, complejidad.
7. Calidad visual de las demos (tipografía, legibilidad, zona segura en vertical).

Los hallazgos se dejarán como comentarios en el PR; Grok los corrige en la misma
rama antes de pasar al siguiente bloque.

## 8. Registro de ejecución

| Bloque | Rama / PR | Estado | Notas |
|---|---|---|---|
| B0+B1 | [#497](https://github.com/IAnMove/hocuspocus/pull/497) `fix/scene-fx-alpha-20260927` | draft | Hashes de paridad iguales en los fotogramas que ya pintaban. Fireworks deja de lanzar `hsl(...)00`. Demo: `/mnt/extras/hocuspocus-worktrees/video2d-demo/fireworks-demo.mp4`. |
| B2 | [#502](https://github.com/IAnMove/hocuspocus/pull/502) `feat/video2d-texts-v2` | draft, apilado sobre #497 | Textos v2, cinco fuentes vendidas, hashes B1 iguales. |
| B3 | [#509](https://github.com/IAnMove/hocuspocus/pull/509) `feat/video2d-titles-lyrics` | draft, apilado sobre #502 | Plantillas en la receta, letra en `scene.lyrics`, demo `ui/tests/fixtures/scene2d/lyrics-demo/scene.json`. |
| B4–B6 | [#510](https://github.com/IAnMove/hocuspocus/pull/510) `feat/video2d-finish` | draft, apilado sobre #509 | Acabado, emisores, secuencias, trayectorias y ritmo guardado. Mismo pintor: un PR. Hashes B0 iguales. |
| B7 | [#508](https://github.com/IAnMove/hocuspocus/pull/508) `feat/video2d-scene-templates` | draft, apilado sobre #510 | Cuatro candidatas sin aprobar. Sin medios de ejemplo: capas de efecto. |
| B8 | [#507](https://github.com/IAnMove/hocuspocus/pull/507) `feat/video2d-fx-sound` | draft, apilado sobre #508 | `sound: true` se sintetiza y se mezcla. Secuencias remotas o `blob:` se rechazan. |
