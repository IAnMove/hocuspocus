# Plan: «plano a plano» — ver de qué planos sale un clip, rehacer planos y volver a montarlo

Fecha: 27 de septiembre de 2026. Estado: **S1–S3 implementados** (contrato, `shots.get`/`shot.regenerate`/`shot.select`, panel en el Editor de vídeo); pendientes S4 (Story Lab y Director), la marca de export desactualizado y `shot.rerender` para escenas.
Depende de: PR #494 (montajes editables, documentos de escena y export Video 2D en servidor).

## 1. Qué se busca

Un sitio único donde, para un videoclip terminado, se vea:

- qué planos lo forman, en qué momento de la canción cae cada uno (y qué verso);
- de dónde sale cada plano (generación con su prompt, semilla y referencias,
  escena Video 2D/3D, subida o render);
- y desde ahí **rehacer uno o varios planos** (regenerar, editar la escena y
  volver a renderizar, o elegir otra toma) y **volver a exportar el clip** sin tocar el resto.

## 2. Qué existe hoy

| Pieza | Dónde | Qué hace | Por qué no basta |
|---|---|---|---|
| Mesa de revisión de producción | Director → producción (`ui/src/features/production-review/`) | Planos con tomas, aprobar/rechazar, regenerar un subconjunto, exportar la selección aprobada. | Solo existe para producciones creadas por el pipeline del Director. Los videoclips hechos por MCP (ciudades, X, Musktopía) no son producciones del Director. |
| Montaje del Story Lab | Story Lab → pestaña de montaje (`StoryAssemblyTab.tsx`) | Lista producciones de la historia con su línea de tiempo; reabrir y restaurar fuente. | Igual: depende de producciones del Director; no edita ni regenera planos. |
| Montajes editables | Editor de vídeo → Montajes (PR #494) | Línea de tiempo guardada (`*.montage.json`) con clips, canción, captions y voces como capas; se reabre, se retoca y se reexporta. | Guarda la procedencia (`origin`) solo como nota; no enlaza la generación ni permite regenerar o elegir tomas. **Aún no está desplegado** (`/api/v1/montages/commands` da 404 en el servidor actual). |
| Sidecar de generación | `<clip>.meta.json` junto a cada MP4 generado | `params`, `task_id`, `job_id`, `lineage`, `generation`… | Tiene todo lo necesario para regenerar, pero nada lo conecta con el montaje. |

Resumen: **hoy no se puede** hacer el ciclo completo desde un sitio. Con el
PR #494 desplegado se podrá abrir el montaje, cambiar un clip por otro fichero,
mover captions y reexportar, pero regenerar el plano sigue siendo manual.

## 3. Decisión: dónde vive

No hace falta una sección nueva. La unidad es el **montaje** y la vista es un
componente compartido, **Plano a plano** (`ShotBoard`), que se abre desde:

1. **Editor de vídeo → Montajes**, conmutador «Línea de tiempo / Plano a plano».
2. **Story Lab → Montaje**: cada producción `music_video` enlaza (o crea) su
   montaje y muestra el mismo `ShotBoard`.
3. **Director → Revisión de producción**: «Exportar selección aprobada» crea o
   actualiza un montaje con `origin.kind = 'production'`, así las dos vías
   (Director y MCP/agente) acaban en el mismo sitio.

## 4. Contrato (montaje versión 1, campos opcionales nuevos)

```jsonc
"clips": [{
  "id": "shot-02", "source": "take-b.mp4", "trimStart": 0, "trimEnd": 4.4,
  "origin": {                                   // ampliado; sigue siendo opcional
    "kind": "generation" | "scene2d" | "scene3d" | "production" | "upload" | "render",
    "meta": "take-b.meta.json",                 // generation: sidecar (se deduce del stem si falta)
    "scene": "Intro-3f2a.scene.json",           // scene2d/scene3d
    "productionId": "…", "shotId": "…", "takeId": "…",   // production
    "derivedFrom": "take-b.mp4", "note": "slowed 1.20x"  // render (p. ej. copia ralentizada)
  },
  "takes": [                                    // ≤ 20; la toma activa es la de `source`
    {"id": "t1", "source": "take-a.mp4", "origin": {…}, "createdAt": "…", "note": "seed 8801"},
    {"id": "t2", "source": "take-b.mp4", "origin": {…}, "createdAt": "…"},
    {"id": "t3", "pending": {"taskId": "task-…", "intentId": "…"}}   // en cola
  ],
  "lyric": "The young men type and laugh…"      // texto de la canción en ese hueco (solo informativo)
}]
```

- Si `origin.kind == 'generation'` y falta `meta`, se usa `<stem>.meta.json`, así
  los montajes ya guardados (X, Musktopía, ciudades) funcionan sin migración.
- Las copias ralentizadas (`*_retimed*.mp4`) se describen como `render` con
  `derivedFrom`; al regenerar se regenera el original y se vuelve a derivar.
- El sidecar del export (`<salida>.meta.json`) guarda la `revision` del
  montaje. El montaje queda marcado como **desactualizado** si cambia la toma
  activa de algún clip después del último export.

## 5. Operaciones (HTTP + MCP)

| Operación | Efecto |
|---|---|
| `montages.shots.get` | Devuelve por clip: hueco en la canción, verso, miniatura, procedencia resuelta (prompt, semilla, referencias, modelo del sidecar o escena) y tomas. |
| `montages.shot.regenerate` `{file, clipId, overrides?, intent_id}` | Lee los `params` del sidecar, aplica cambios (prompt, semilla, referencias, duración) y encola la generación con la API existente. Añade una toma `pending`. **Usa la cola de GPU normal**; nada de saltarse la cola. |
| `montages.shot.rerender` `{file, clipId, intent_id}` | Para `scene2d`/`scene3d`: `scenes.video2d.export` / `scenes.world3d.export` de la última revisión de la escena → toma nueva. |
| `montages.shot.select` `{file, clipId, takeId, expected_revision}` | Cambia la toma activa (ajusta `trimEnd` o deriva una copia ralentizada si la toma es más corta que el hueco). Guarda una revisión. |
| `montages.export` | Sin cambios (PR #494). |

Las tomas `pending` se resuelven al leer (`shots.get`) consultando el registro
de tareas del workspace; no hace falta un proceso aparte.

## 6. UI de «Plano a plano»

- Rejilla ordenada por tiempo: miniatura/vídeo en bucle, `mm:ss–mm:ss`, verso,
  icono de procedencia, estado (ok / en cola / fallo / desactualizado).
- Panel del plano: prompt editable, semilla, referencias (miniaturas), tomas
  en carrusel para comparar, y botones **Regenerar**, **Abrir en Video 2D/3D**,
  **Renderizar escena**, **Reemplazar con archivo**.
- Selección múltiple → «Regenerar seleccionados».
- Barra superior: «Exportar de nuevo» y aviso de montaje desactualizado.
- Móvil: lista vertical; el panel del plano como hoja inferior.

## 7. Bloques

| Bloque | Contenido |
|---|---|
| S1 | Backend: `origin`/`takes` en `montage_documents.py`, deducción del sidecar, `shots.get`, `shot.select`, marca de desactualizado. Tests. |
| S2 | Backend: `shot.regenerate` (desde `params` del sidecar, con `intent_id`) y `shot.rerender`. Tests con registro de tareas simulado. |
| S3 | UI `ShotBoard` en el Editor de vídeo (componentes propios, i18n es/en). |
| S4 | Enlaces desde Story Lab → Montaje y desde Revisión de producción (exportar selección → montaje). |
| S5 | Documentación (`docs/video-editor/MONTAGES.md`) y prueba real con el montaje de «The Bird Is Freed»: regenerar un plano, elegir la toma y reexportar. |

## 8. Fuera de alcance

- Cambiar el pipeline del Director o su mesa de revisión más allá del enlace de S4.
- Componer verticales con fondo difuminado en el Editor de vídeo (plan aparte).
- Las mejoras de texto y efectos de Video 2D ([GROK_VIDEO2D_BOOST_PLAN_2026-09-27](GROK_VIDEO2D_BOOST_PLAN_2026-09-27.md)).
