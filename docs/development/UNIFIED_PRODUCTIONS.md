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
`{id}.production.json` cuando el fichero se crea o aún no lo tiene. Un
`production.run` posterior hace `state.update` y conserva esa clave.

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
| `production.run` | no tenía Story | `{id}.production.json` | `{id}.shots.json`, `takes`, review | se enlaza antes de generar; el run conserva `project` | el run no llama a resolve; el cliente debe hacerlo |
| Director | `provenance.project_id` opcional | `_director_pipeline_*.json` | `clips[]`, `video_attempts` | el catálogo indexa el snapshot | el arranque del pipeline no llama a resolve |
| Story Lab | la biblioteca | `projects[].productions[]` | el pipeline o el batch que dispare | Story mínima y fila `productions[]` | Resultados aún no abre la vista común |
| Series | el episodio | `productionIds[]` no se reescribe | `shots[]`, `attempts[]` | un episodio explícito se reutiliza y no crea Story | no se añade el id al episodio |
| Montaje | no | `{nombre}.montage.json` | clips y tomas del editor | aún no indexado | vista y enlace, en los PR siguientes |
| MCP `generation.video` | no | un job de Studio | no es una obra | no se convierte en proyecto | sigue en la galería hasta que alguien lo vincule |
| Wizard | la Story que la acción envíe | handoff a Director o Series | los del destino | el mismo resolve HTTP | el registro de capacidades lo ocupa el PR de plantillas World3D |

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

`music_production.py` sigue restringido a ganchos de pocas líneas. Este flujo
no necesita un gancho: el fichero de producción se prepara antes y el run
conserva las claves que no sustituye.

## Límites conocidos en este corte

- Quien llama a `production.run` o al arranque del Director tiene que pedir
  resolve antes. El servidor aún no intercepta esos comandos.
- El estado del enlace se alinea con el fichero al listar o al `POST` de estado.
  No hay gancho dentro del hilo de `production.run`.
- Los montajes y los jobs sueltos de `generation.video` no son proyectos.
- Los tokens de LLM de este cambio no están disponibles: el cliente no los midió.
  No se estiman a partir de bytes.

## Pruebas

`tests/test_production_project_link.py` cubre reintento, proyecto inválido,
episodio, escritura parcial, guardado viejo de la biblioteca, ejecución nueva,
concurrencia, catálogo sin duplicar y el HTTP. Está en el grupo `python-a`.
