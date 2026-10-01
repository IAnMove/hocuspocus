# Producciones unificadas

Una obra de vídeo (videoclip, tráiler, vídeo rápido, historia o episodio) queda
ligada a un proyecto antes de encolar trabajo costoso. Producciones no es otro
almacén: es un índice de los registros que ya existen.

## Unidades

| Unidad | Dónde vive | Identidad |
|---|---|---|
| Proyecto | `.story-library-v1.json` o episodio en `.series-library-v1.json` | `id` de Story o de episodio |
| Producción | `{id}.production.json` y la fila del enlace | `production_id` estable por intención y ejecución |
| Plano | `{id}.shots.json`, clips del Director, `shots[]` del episodio o clips del montaje | clave ya usada por ese productor |
| Toma | `takes`, `video_attempts` o `attempts` del productor | fichero o id de intento existente |
| Montaje | `montage_file` / `final` o `{nombre}.montage.json` | el fichero que ya escribe el productor |

El enlace está en `{workspace}/.production-project-links-v1.json`. No mueve
medios. El campo opcional `project` de `production-record-v1` se copia al
`{id}.production.json` cuando el fichero se crea o aún no lo tiene. Los arranques de música y Director guardan ese enlace y su identidad en el
estado antes del worker. Series guarda el id en `episode.productionIds`.

## Resolver antes de generar

`POST /api/v1/production-projects/resolve`

```json
{
  "workspace": "film",
  "origin": "mcp",
  "intent_id": "clip1",
  "format": "music_video",
  "title": "Night bus",
  "idea": "opcional",
  "project": {"kind": "story", "id": "story-open"},
  "new_execution": false
}
```

`origin` es `mcp`, `wizard` o `ui`. `format` es `music_video`, `trailer`,
`quick_video` o `full_story`, y es obligatorio solo si no hay proyecto.
`production_id` es opcional: permite conservar el id que ya usa un productor.
Un id explícito identifica una sola ejecución y no admite `new_execution`.
El resolve de un episodio no crea un fichero musical ficticio.

1. Un `project` o `episode_id` explícito se valida. Si no existe, la respuesta
   es `invalid_project` y no se crea ninguna Story.
2. Ni MCP ni Wizard leen `activeId`. El proyecto abierto solo entra si el
   cliente lo envía en `project`.
3. Sin proyecto, se crea una Story mínima de ese `format` con
   `patch_story_project` (revisión de la biblioteca, sin robar la Story activa).
   El id de esa Story sale de `workspace + intent_id`, así un reintento no crea otra.
4. El enlace se escribe antes del `{id}.production.json`. Si el fichero de
   producción no llega a escribirse, el mismo `intent_id` reconcilia sin otra Story.
5. El mismo `intent_id` devuelve la misma producción. `new_execution: true`
   añade otra producción al mismo proyecto.
6. `POST /api/v1/production-projects/status` actualiza el enlace. El catálogo
   también copia el `status` del `{id}.production.json` cuando el productor ya lo
   escribió. Cerrar el cliente no borra el enlace.

Un guardado de biblioteca con una revisión vieja puede quitar la Story. El
siguiente resolve de una Story creada por este flujo la restaura desde la
semilla guardada en el enlace y vuelve a añadir las producciones que falten.
No restaura un proyecto explícito que el usuario haya borrado.

## Catálogo

`GET /api/v1/production-projects?workspace=&format=&status=`

Una fila por `production_id` dentro del workspace. Se leen los
`*.production.json`, el enlace, `productions[]` de cada Story y los
`_director_pipeline_*.json` de esa carpeta. El mismo id en varios sitios es una
fila. Dos obras con el mismo título siguen siendo dos filas. Un JPG u otro
recurso suelto no entra. Un fichero antiguo sin `project` sale con
`"linked": false`.

La respuesta no incluye rutas del disco. `preview` solo existe cuando el
contacto ya es un nombre de fichero del workspace.

## Matriz de cobertura

| Productor | Proyecto | Producción | Planos / tomas | Qué reutiliza este cambio | Qué falta |
|---|---|---|---|---|---|
| `production.run` | Story mínima o proyecto explícito | `{id}.production.json` | manifiesto, tomas y review | registro y estado guardados antes del hilo, incluida llamada MCP directa | preview, package y dry-run no crean proyecto |
| Director | Story mínima, `project` o `provenance.project_id` | snapshot del pipeline con id canónico | clips e intentos | registro y snapshot antes de planificación; reintento usa su workspace | no migra obras antiguas automáticamente |
| Story Lab / Wizard | proyecto enviado en la acción | producción del motor de destino | planos del destino | reusa el proyecto, sin leer la Story activa | jobs sueltos de Studio no se convierten en obras |
| Series | episodio existente | enlace y `productionIds[]` | shots e intentos | registro antes del worker generado y antes del batch nativo 2D; estado de ejecución | el batch de Series no ofrece motor nativo 3D |
| Montaje | vínculo previo, si existe | montaje existente | clips y tomas | revisión y selección existentes | regenerar un clip importado exige un generador de origen |
| MCP `generation.video` | no | job de Studio | salida del job | conserva la galería | no crea una Story por cada recurso suelto |

## Coordinación

Reclamación: rama `feat/unified-productions-identity` y los PR que salen de ella.
No editan `music_production.py` (PR #716, `fix/music-production-under-700`).
No editan la búsqueda ni la aplicación de plantillas World3D (PR #717,
`feat/world3d-templates-mcp`): ese trabajo posee `applicationAdapters.ts`,
`capabilityRegistry.ts`, `wangp_mcp.py` y el bloque de plantillas en
`_launch_runtime.py`. Aquí solo se añade el `include_router` del catálogo junto
al router de producciones del Director, antes de ese bloque.

Archivos compartidos y regla:

| Archivo | Quién más | Regla |
|---|---|---|
| `app/_launch_runtime.py` | #717 | Una inclusión de router. No mover el bloque World3D. |
| `scripts/ci_test_groups.json` | #716 y #717 | Añadir el test propio. Conservar las otras líneas. |
| `tests/fixtures/route_table.json` | #717 | Regenerar con `scripts/architecture_contracts.py --write` y conservar las rutas ajenas al rebasar. |
| `docs/development/PRODUCTION_WORK_BOARD.md` | #716 | Sección aditiva al final. |
| `docs/agents/VIDEO_PRODUCTION_RUNBOOK.md` | #716 | Sección aditiva al final. |
| Bloque D (`production_shot_review.py`, `ReviewMode.tsx`, `music_productions.py`) | revisión musical | Consumir sus operaciones. No reimplementarlas. |

La continuación `feat/production-shared-review-completion` incorpora el registro
`bind_producer` del PR #746, conserva sus commits y lo usa desde los adaptadores
de arranque. Solo queda un registro por productor. Añade metadatos persistidos,
`productionIds` del episodio, regeneración y verificación Chromium. Los fixes
#737, #739, #742 y #743 se conservan al integrar `development`.
`music_production.py` mantiene el gancho breve y menos de 700 líneas.

## Vista de planos (solo lectura)

`GET /api/v1/production-projects/{production_id}/shots?workspace=`

La lista sale del primer origen que ya tiene planos: `{id}.shots.json`, si no
los `shots[]` del episodio, si no los `clips[]` del pipeline del Director, si
no los clips del montaje nombrado por la producción o cuyo `origin.productionId`
es esa producción. Los otros orígenes solo rellenan el mismo id (escena, toma,
`video_stale` / `export_stale`). No se añaden planos de más.

No se inventa letra, duración ni escena. Un nombre con `..` no se copia. La
vista devuelve como mucho 200 planos y 20 tomas por plano. `review` solo
aparece si `{id}.review.json` tiene esa clave, o si el intento aprobado de la
serie ya trae `reviewDecision`. La aprobación artística sigue siendo
`approved`, nunca `ok`. `video_stale: false` que ya escribe el Director se
conserva; si el campo no está, `montage` queda en null.

Si `selected_video_filename` está vacío, el `video_filename` del clip es la
toma activa: es el campo que el Director ya usa. La UI abre esta misma
respuesta con el evento `hocuspocus:production-shots-open` y el detalle
`{workspace, productionId}`. La misma revisión se abre desde Obras, Story Lab y Series.

## Acciones de un plano

`POST /api/v1/production-projects/{production_id}/shots/{shot_id}` con
`action`. `select` cambia solo esa toma, conserva las anteriores y marca
`video_stale` sin tocar el `source` del montaje. `reexport` copia la toma
elegida al clip de ese plano. `undo` restaura la instantánea de la revisión y
no borra ficheros. Un plano `locked` responde `shot_locked` (422) y no
escribe. `expected_revision` distinto del fichero responde `stale_revision`
(409). `review` solo acepta `pending`, `approved` o `changes_requested`.
`request` con `apply` distinto de `true` devuelve `applied: false` y no
escribe. `regenerate`, con `expected_revision`, devuelve `applied: false`
y un destino `regeneration`: ese POST prepara la operación, no genera medios.
La UI ejecuta el destino una sola vez y deja la revisión en `pending` solo
cuando el motor acepta o completa la operación. Los clientes API deben ejecutar
ese destino; un destino ausente no cuenta como reintento completado.
La revisión de Series sigue en el sidecar. Abrir la escena no muta (`applied: false`) y la
UI emite `hocuspocus:production-shot-scene`.

## Catálogo y accesos

`POST /api/v1/production-projects/commands` con `version: 1` y `input.workspace`.

| Operación | Qué hace |
|---|---|
| `production.works.list` | Filtra por `format` y `status` dentro de ese workspace. `applied` es false. |
| `production.works.open` | Una obra y su evento de revisión. No escribe el plano. |
| `production.works.resolve` | El mismo resolve de siempre. `applied` es true. `reused` es true si ese `intent_id` ya existía. |

Cada fila trae `review.event` = `hocuspocus:production-shots-open`, `workspace` y `production_id`. Un episodio añade `series_id` cuando la biblioteca de series ya tiene ese capítulo. No se crea una Story para el episodio.

La UI abre **Producciones** desde **Obras** (`hocuspocus:production-catalog-open`). El botón **Producciones** del Director no cambia. **Revisar planos** conserva el workspace. **Abrir proyecto** abre la Story o el episodio que ya existen; si no están en el workspace, no crea otro. Story Lab → Montaje y Series → Resultados usan el mismo evento. Crear una obra ofrece videoclip, tráiler o vídeo rápido, el formato ligero de Story Lab, y reutiliza el `intent_id` del formulario.

El asistente registra `production_works` con una línea en `capabilityRegistry.ts` y llama a `productionWorks.command`. Ese método es una adición en `applicationAdapters.ts`; no reescribe el registro de plantillas World3D ni `wangp_mcp.py`. No arranca un modelo. `applied: false` no se resume como obra nueva.

## Obras antiguas

`production.works.link` une un `production_id` que el catálogo ya reconoce con una Story o un episodio que ya existen. No crea una Story, no compara títulos y no reescribe el fichero de producción, las tomas ni la biblioteca de series. La segunda llamada con el mismo par responde `reused: true` y no añade otra fila. Si el id ya apunta a otro proyecto, responde `invalid_project`. Un fichero ilegible sigue en `warnings` y no se vincula. Sin el sidecar, la obra se lee igual y sale **Sin proyecto vinculado**.

La UI ofrece **Vincular a proyecto** solo en esa fila. El id lo escribe quien conoce el proyecto.

## Productores

`production.run` llama a `link_production_run` después de validar el spec y antes de arrancar el hilo. Sin `project` crea una Story mínima y el mismo `production_id` la reutiliza. Un `project` que no existe responde 422 y no arranca el hilo. `dry_run` no crea proyecto.

`start_pipeline` llama a `link_director_start` antes de registrar el pipeline y antes del worker. El id del pipeline es el id de la obra. Un segundo arranque del mismo id no crea otra Story. `provenance.project_id` no se interpreta como Story.

El render de un episodio llama a `link_series_render` cuando la petición ya es válida y antes de arrancar el worker. Un render rechazado no crea proyecto. El proyecto es ese episodio. No crea una Story y no reescribe `.series-library-v1.json` en el enlace.

## Regeneración compartida

- Música reutiliza el redo existente: H3 desde clip, imágenes desde frame y
  escenas 3D desde scene. La toma nueva actualiza solo su fila del manifiesto,
  conserva las anteriores y marca el export desactualizado; no cambia el montaje.
- Director usa el índice exacto del clip y el workspace guardado.
- Series generado usa `mode: selected` y un solo `shotIds`; Series nativo 2D
  vuelve al episodio y usa su batch existente. Un batch ocupado falla de forma
  explícita. No se añade un runner alternativo.
- El motor HTTP vuelve a validar bloqueo, revisión y correspondencia con el
  plano solicitado. No permite autorizar otro plano ni otro modo con ese token
  de revisión. No hay reintento automático tras un error.
- Medios importados y Series nativo 3D carecen de una operación de regeneración
  disponible en este batch; el botón explica el límite. Los montajes y jobs
  sueltos de Studio no se convierten en proyectos por esta integración.

## Verificación y coste

`tests/test_production_generation_link.py` comprueba el estado en disco antes
del worker musical, Director y render de Series, reintentos, ids inválidos,
colisiones y fallo de persistencia. `tests/test_production_shot_regeneration.py`
comprueba el destino exacto, bloqueo, revisión, aislamiento entre planos y
conservación del montaje. Ambos están registrados en el grupo `python-a`.

`cd ui && npm run test:e2e:production` arranca una UI y una API aisladas y usa
Chromium real. El recorrido genera mediante el handler real, recarga el cliente,
abre Obras y Revisar planos, regenera una toma, comprueba que la anterior y el
otro plano permanecen, aprueba y bloquea. El registro, el catálogo, la revisión,
el redo y los JSON son reales; solo la producción de medios se simula. Los MP4
son fixtures sintéticos: esta prueba no certifica calidad ni reproducción del
vídeo. CI ejecuta este recorrido además del E2E general.

El entorno Python mínimo está en `scripts/ci-production-browser-requirements.txt`.
`HOCUS_PRODUCTION_TEST_PYTHON` selecciona su intérprete; los puertos de prueba
se pueden configurar con `HOCUSPOCUS_E2E_PORT` y
`HOCUS_PRODUCTION_TEST_API_PORT`. No reutiliza los servidores del usuario.

Generaciones reales y consumo GPU: cero. Los tokens del agente no están
expuestos por el cliente y se registran como no disponibles, sin estimarlos
por bytes. El coste de validación procede de tests CPU y builds de la UI.
