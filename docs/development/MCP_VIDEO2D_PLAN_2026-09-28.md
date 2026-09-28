# Video 2D por MCP — plan 2026-09-28

Un LLM externo tiene que poder crear, previsualizar, editar y exportar una escena
Video 2D con todos los recursos (plantillas de escena, rótulos, letra, fuentes,
acabado, atmósferas, secuencias, movimientos y efectos) solo por MCP, sin leer el
código. Hoy las plantillas, el acabado, las fuentes y los presets de movimiento
viven en TypeScript de la UI. `scenes.document.save` y `scenes.video2d.export`
reciben `document` como objeto opaco. No hay fotograma de vista previa: hace
falta exportar el MP4. El modelo a imitar es `scenes.effects.catalog` /
`scenes.effects.apply` / `scenes.effects.showcase`, con el catálogo en
`app/shared/scene_effects.json`.

## Paridad

Una capacidad no está terminada hasta que el MCP permite descubrirla, validarla,
verla, editarla y guardarla o exportarla. Cada operación va versionada
(`{version: 1, input}`), con límites y un `code` de error estable. Las mutaciones
llevan `intent_id`.

## Reglas de entrega

Cada bloque es un PR en borrador contra `development`, ramificado desde
`origin/development`. No se apilan PRs. Si un bloque depende de otro que aún no
está fusionado, se espera. Sin GPU ni generación de medios. Las escenas ya
guardadas se pintan igual. El avance de esta tabla se actualiza en el PR del
bloque que cambie el estado.

## Matriz

| Capacidad | Dónde vive | Operación MCP | Estado |
|---|---|---|---|
| Efectos de pantalla y de mundo | `app/shared/scene_effects.json`, `ui/src/features/sceneFx` | `scenes.effects.catalog`, `.apply`, `.showcase` | Expuesto |
| Bases del showcase | `app/shared/scene_bases.json` | Las carga `scenes.effects.showcase`; no es un catálogo de ids | No es catálogo |
| Plantillas de escena | `ui/src/features/sceneTemplates/catalog.ts`, `video2dCandidates.ts` | Ninguna | Hueco (M1, M2, M4) |
| Plantillas de rótulo | `ui/src/lib/kineticText/templates.ts` | Ninguna | Hueco (M1, M2, M4) |
| Acabado | `ui/src/lib/scene2d/finish.ts` | Ninguna | Hueco (M1, M2, M6) |
| Fuentes | `ui/public/fonts` | Ninguna | Hueco (M1, M2) |
| Atmósferas y emisores | UI de escena / receta | Ninguna de catálogo | Hueco (M1, M2) |
| Movimientos y cámaras | `ui/src/lib/sceneRecipe.ts` | Ninguna de catálogo | Hueco (M1, M2, M8) |
| Textos v2 | `ui/src/lib/kineticText` | El export los nombra en la descripción, sin esquema | Hueco de esquema (M3) |
| Letra / karaoke | `ui/src/lib/kineticText/lyrics.ts` | Ninguna | Hueco (M3, M4, M6) |
| Ritmo, secuencias, pistas de audio | Documento de escena (`Scene` en `ui/src/types/index.ts`) | `audioTracks` se nombra en la descripción del export; el resto no | Hueco de esquema (M3) |
| Guardar / leer | `app/services/scene_documents.py` | `scenes.document.save`, `scenes.document.get` | `document` opaco |
| Exportar MP4 | `app/services/scene2d_export.py` | `scenes.video2d.export`, recibo y cancelación | `document` opaco; sin vista previa |
| Validar sin guardar | No existe | `scenes.video2d.validate` | Hueco (M3) |
| Compilar plantilla, rótulo o letra | TypeScript de la UI | `scenes.template.compile`, `scenes.text.template`, `scenes.lyrics.import` | Hueco (M4) |
| Vista previa de fotogramas | No existe | `scenes.video2d.preview` | Hueco (M5) |
| Edición por operaciones | Copiloto de la UI | `scenes.video2d.edit` | Hueco (M6) |
| Inventario de recursos con rol | Herramienta `assets` | `scenes.assets` o extensión de `assets` | Hueco (M7) |
| Guía para agentes y planificador | `buildRecipeSystemPrompt` no ve textos ni acabado | Documentación, sin operación nueva | Hueco (M8) |
| Extremo a extremo solo por MCP | No existe | Script de humo | Hueco (M9) |

`tests/test_mcp_coverage.py` falla si aparece un JSON de catálogo en
`app/shared/*.json` (lista de objetos con `id`) que ningún `*.catalog` lee, o si
`export interface Scene` gana una clave de primer nivel que ni el esquema
publicado ni la lista de huecos conocidos nombran. Hoy el esquema del documento
sigue siendo `{"type": "object"}`, así que las claves de `Scene` están en el
hueco a propósito. M3 las publica y las quita de esa lista.

## Bloques

1. M0 — este plan y el test de cobertura.
2. M1 — catálogos JSON compartidos. La UI y el servidor leen los mismos datos.
3. M2 — `scenes.catalog` y `GET /api/v1/scenes/catalog`.
4. M3 — esquema real y `scenes.video2d.validate`.
5. M4 — compilar plantilla, rótulo y letra en el puente de render, sin guardar.
6. M5 — `scenes.video2d.preview` (hoja de contactos). Video 3D solo si es barato.
7. M6 — `scenes.video2d.edit` por operaciones pequeñas.
8. M7 — metadatos de recursos cacheados en el sidecar.
9. M8 — guía de agentes y el mismo catálogo dentro del planificador.
10. M9 — humo de 20 s solo por MCP, sin GPU.

M2 y M3 pueden ir en paralelo después de fusionar M1. M5 espera a M4.

## Avance

| Bloque | Estado | PR |
|---|---|---|
| M0 | En borrador | https://github.com/IAnMove/hocuspocus/pull/530 |
| M1 | En borrador | https://github.com/IAnMove/hocuspocus/pull/535 |
| M2 | Pendiente | |
| M3 | Pendiente | |
| M4 | Pendiente | |
| M5 | Pendiente | |
| M6 | Pendiente | |
| M7 | Pendiente | |
| M8 | En borrador | https://github.com/IAnMove/hocuspocus/pull/538 |
| M9 | Pendiente | |
