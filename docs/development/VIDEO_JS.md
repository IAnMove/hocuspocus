# Vídeo JS (experimental): vídeo programático dirigido por LLM

Rama `feat/video-js`, creada el 2026-09-16 desde `origin/development` `475b1735`.
Estado: **experimental, sin PR ni merge**. Es una base para iterar, no un
contrato cerrado del vídeo procedural.

## Qué es

Tercer editor junto a Vídeo 2,5D y Vídeo 3D (Estudios → Vídeo JS). Un vídeo es
una lista ordenada de escenas; cada escena es **código JavaScript** que pinta un
fotograma en función del tiempo, con Canvas 2D o con three.js (3D + capa 2D
encima). Flujo:

1. **Crear**: el usuario describe el vídeo (presentación, promo, historia con
   datos, escaparate 3D…) y el LLM configurado devuelve todas las escenas.
2. **Revisar**: la previsualización pinta en directo; cada escena se puede
   seleccionar, reordenar, duplicar, borrar o editar a mano (`Ctrl+Enter`).
3. **Ajustar**: una petición para todo el vídeo o para una escena. Si una escena
   falla, «Corregir con LLM» envía el error con su línea. Todo se puede deshacer.
4. **Exportar**: MP4 H.264 determinista (30/60 fps, hasta 1080p) publicado en
   Vídeos mediante el endpoint existente `POST /api/v1/scenes/recordings`. El
   sidecar guarda el documento completo (`recipe.engine = "videojs"`).

No se añade backend ni dependencia nueva: reutiliza `/api/v1/llm/generate`, el
codificador WebCodecs de Vídeo 3D (`encodeWorld3DFrames`) y three.js ya instalado.

## Código

`ui/src/features/videojs/`

| Archivo | Responsabilidad |
|---|---|
| `types.ts`, `document.ts` | Documento `hocuspocus.videojs/v1`, normalización de entradas no confiables, línea de tiempo |
| `promptGuide.ts` | Prompt de sistema: formato de salida, API del kit y guía de diseño |
| `llm.ts` | Prompts crear/ajustar/corregir, parser tolerante y fusión por `id` |
| `runtime/videojsWorker.js` | Kit de escenas y render por fotograma (se ejecuta en el Worker del sandbox) |
| `runtime/videojsHost.js` | Script del iframe: vida del Worker, watchdog y reenvío de fotogramas |
| `sandbox.ts`, `sources.ts` | CSP, srcdoc, RPC serializado desde la app, carga perezosa de three.js |
| `exportVideo.ts` | Render de todos los fotogramas por el mismo sandbox y publicación MP4 |
| `useVideoJs*.ts`, `VideoJs*.tsx` | Estado con historial, sandbox, exportación y UI |

## Contrato de escena

El cuerpo de la escena es el cuerpo de una función que devuelve
`{ setup?, render, overlay? }`:

```js
return {
  setup({ kit, width, height, THREE, scene, camera }) { return state },
  render({ ctx, t, p, frame, width, height, kit, state, THREE, scene, camera }) { … },
  overlay({ ctx, t, … }) { … }, // opcional: 2D sobre la imagen 3D
}
```

- `t` segundos desde el inicio de la escena, `p = t / duration`.
- `render` es función pura del tiempo: preview y exportación piden el mismo
  fotograma y obtienen la misma imagen; se pueden pedir fuera de orden.
- `Math.random` se siembra por escena y fotograma; `Date.now`/`performance.now`
  devuelven el tiempo de escena; `setTimeout`, `setInterval`,
  `requestAnimationFrame` y `fetch` lanzan un error explicativo.
- Transiciones de entrada: `none | fade | slide-left | slide-up | zoom | wipe`.
- El kit (`kit.tween`, `kit.stagger`, `kit.keyframes`, `kit.draw.*`,
  `kit.text.*`, `kit.layout.*`, `kit.three.*`…) está documentado en
  `promptGuide.ts`; un test falla si la guía menciona algo que el runtime no tiene.

Formato de respuesta del LLM (etiquetas, no JSON, para que el código no dependa
de escapes): `<video title>`, `<theme …/>` y `<scene id title kind duration
transition>código</scene>`. Crear ignora ids; ajustar el vídeo conserva los ids
devueltos y rechaza respuestas sin `</video>` (truncadas) sin aplicar nada.

## Seguridad y aislamiento

`docs/development/PROCEDURAL_VIDEO_ROADMAP.md` fija que el Wizard no ejecuta JS
arbitrario en la app. Vídeo JS respeta esa intención con aislamiento explícito
en lugar de una DSL:

- iframe `sandbox="allow-scripts"` **sin** `allow-same-origin` (origen opaco):
  sin cookies, almacenamiento ni DOM de HocusPocus.
- CSP en el srcdoc: `default-src 'none'`, `connect-src 'none'`, sin frames,
  formularios ni `base`. El Worker creado desde `blob:` hereda la política.
- El código corre en un Worker con `OffscreenCanvas`; el iframe lo termina si un
  fotograma supera 20 s (bucle infinito) y la app sigue respondiendo.
- La app sólo recibe `ImageBitmap` y errores saneados; los textos del LLM nunca
  amplían permisos ni se evalúan en la app.
- three.js se envía como texto al sandbox (no hay red dentro).

E2E comprobado: XHR, EventSource, `fetch` vía prototipo, `importScripts` y
WebSocket contra la API y contra un servidor local quedan bloqueados (`csp`).

## Límites conocidos

- Sin audio, sin imágenes/fuentes propias y sin assets de Library en escenas.
- Borrador por navegador y workspace (`localStorage`) + importar/descargar JSON;
  el MP4 publicado es el registro durable. No hay reapertura desde la galería.
- No está conectado al Wizard/MCP ni a GenerationRecord más allá del sidecar.
- Exportación en el navegador del usuario (WebCodecs H.264). Sin render en servidor.
- Calidad visual dependiente del LLM: la guía ayuda, pero no hay evaluación automática.
- Chunk perezoso de three.js ~407 KB gzip, sólo al existir escenas 3D.

## Siguientes pasos sugeridos

1. Assets de Library (imágenes, logos, GLB) entregados al sandbox como bitmaps.
2. Pista de audio/música y marcas de tiempo por escena.
3. Reabrir un MP4 desde su sidecar y guardado durable del documento.
4. Acción Wizard/MCP «crear vídeo JS» con la misma política de permisos.
5. Revisión visual con modelo de visión sobre fotogramas clave antes de exportar.
6. Render en servidor reutilizando el Chromium propio de `world3d_export`.

## Verificación

```sh
cd ui
npx tsx --tsconfig tsconfig.app.json --import ./tests/setupI18n.ts --test tests/videojs*.test.ts
npm run i18n:check && npm run lint && npm run build && npm run budget
npm run test:e2e -- videojs
```

Evidencia local (2026-09-16, Chromium de Playwright, API simulada): 17 tests
unitarios; 4 E2E (render 2D/3D real, bloqueo de red, crear → error → corregir →
deshacer → MP4, watchdog de escena colgada). La demo de 22 s exportó un MP4
H.264 1920×1080, 30 fps, 660 fotogramas validado con `ffprobe`. No se ha probado
con un proveedor LLM real ni con el servidor HocusPocus en marcha.
