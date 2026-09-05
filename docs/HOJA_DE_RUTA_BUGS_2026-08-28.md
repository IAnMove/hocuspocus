# Hoja de ruta — bugs y mejoras — 2026-08-28

Fuente: revisión de lectura sobre el código commitado de `feat/3d-compositor-recipe`.
No se ha modificado código de producto para esta hoja. Un Grok Build sigue
trabajando el compositor 3D y las recipes; esos archivos quedan **fuera de
alcance** hasta que esa rama aterrice.

Contrato de ejecución, igual que la auditoría de agosto:

- Un ticket por commit, salvo que el propio ticket autorice un par.
- Cada ticket exige prueba automática o evidencia verificable.
- No reabrir tickets ya cerrados en
  [`AUDITORIA_CODIGO_UI_2026-08-13.md`](AUDITORIA_CODIGO_UI_2026-08-13.md) /
  [`AUDIT_REMEDIATION_STATUS_2026-08-16.md`](AUDIT_REMEDIATION_STATUS_2026-08-16.md).
  Esta hoja empieza donde aquella terminó.
- No tocar vendor, pesos, ni el monolito de `_launch_runtime.py` salvo que un
  ticket lo nombre de forma explícita.

Estados: `pendiente`, `bloqueado`, `en_curso`, `completado`.

## Archivos que no se tocan mientras el Grok Build de recipes esté vivo

```
app/_launch_runtime.py
app/services/director_pipeline.py
tests/test_director_pipeline_recovery.py
ui/src/App.tsx
ui/src/api/client.ts
ui/src/components/DownloadStatusBanner.tsx
ui/src/components/Sidebar/HardwareStatusBar.tsx
ui/src/components/Sidebar/SceneAnimatorPanel.tsx
ui/src/features/workspaces/WorkspacesPanel.tsx
ui/src/lib/cutoutDialogue.ts
ui/src/lib/sceneRecipe.ts
ui/src/stores/useStore.ts
ui/src/types/index.ts
ui/tests/cutoutDialogue.test.mjs
ui/tests/directorPipelineLoadError.test.tsx
ui/tests/sceneRecipe.test.mjs
ui/tests/workspacesPanel.test.tsx
```

Los tickets marcados **bloqueado · Grok Build** esperan a que esa lista vuelva
a estar limpia. El resto se puede ejecutar en paralelo sin pisarla.

## Tablero

| Orden | Ticket | Pri | Tamaño | Estado | Bloque |
| --- | --- | --- | --- | --- | --- |
| 1 | CHAR-01 | P1 | S | completado | Character Creator |
| 2 | CHAR-02 | P1 | S | completado | Character Creator |
| 3 | VID-01 | P1 | S | completado | Video Editor |
| 4 | SER-UI-05 | P1 | S | completado | Series Review |
| 5 | SER-UI-06 | P1 | S | completado | Series Review |
| 6 | ACT-02 | P1 | S | completado | Activity |
| 7 | COMIC-01 | P1 | S | completado | Comics |
| 8 | SER-UI-04 | P1 | S | completado | Series Review |
| 9 | CHAR-03 | P2 | S | completado | Character Creator |
| 10 | POLL-02 | P2 | S | completado | Polling |
| 11 | POLL-03 | P2 | S | completado | Polling |
| 12 | POLL-04 | P2 | S | completado | Polling |
| 13 | POLL-05 | P2 | S | completado | Polling |
| 14 | LLM-01 | P1 | M | completado | Backend |
| 15 | SER-04 | P1 | S | completado | Backend |
| 16 | TASK-08 | P2 | S | completado | Backend |
| 17 | API-03 | P2 | S | completado | Backend |
| 18 | COMIC-02 | P2 | S | completado | Comics |
| 19 | SCENE-01 | P2 | S | completado | 3D Video |
| 20 | VID-02 | P1 | S | completado | Galería |
| 21 | EDIT-01 | P2 | S | completado | Studio Edits |
| 22 | SCENE-02 | P1 | S | completado | 3D Video / recipes |
| 23 | SCENE-03 | P2 | L | bloqueado · Grok Build | 3D Video / recipes |
| 24 | ARCH-04 | P3 | L | pendiente | Deuda |

## Orden recomendado

No ejecutar todo a la vez. El orden seguro es:

1. **Fase A — identidad de workspace/episodio** (`CHAR-01`, `CHAR-02`, `VID-01`, `SER-UI-05`, `SER-UI-06`, `ACT-02`, `COMIC-01`). Bugs de datos cruzados. Ninguno toca la lista sucia.
2. **Fase B — polling** (`SER-UI-04`, `CHAR-03`, `POLL-02`…`POLL-05`). Reutilizar `useSerializedPoll`. Un panel por commit.
3. **Fase C — backend** (`LLM-01`, `SER-04`, `TASK-08`, `API-03`). Cancelación y sidecars. Independiente de la UI de recipes.
4. **Fase D — después del Grok Build** (`VID-02`, `EDIT-01`, `SCENE-01`, `SCENE-02`). Tocan `useStore.ts` o el contrato de recipes.
5. **Fase E — evolución** (`SCENE-03`, `ARCH-04`). No empiezan hasta que A–D estén verdes. `SCENE-03` es el hueco documentado en [`scene-recipe-gap.md`](scene-recipe-gap.md); el Grok Build actual ya está en esa zona.

Cada ID es un commit separado salvo que el ticket diga lo contrario.

Prioridades:

- **P1:** dato incorrecto, job fantasma, cancelación que no corta, o lista vacía con contenido real.
- **P2:** carrera, fuga o 500 evitable que no rompe el camino feliz.
- **P3:** deuda. No bloquear producto.

---

## Fase A — Identidad de workspace y episodio

### CHAR-01 — Pasar el workspace activo a captura y URLs del Character Creator

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** `ui/src/features/characters/CharacterCreatorPanel.tsx:202` llama `captureVideoEditorFrame` sin `workspace`. `:212`, `:241` y `:543` llaman `getFileUrl(filename)` sin el segundo argumento. `getFileUrl` (`ui/src/api/client.ts:839`) sólo añade `?workspace=` cuando se pasa. Series Review sí lo hace (`SeriesReviewPanel.tsx:17`).
- **Riesgo:** en un workspace que no es el default, la órbita, las fotos y el GLB se resuelven contra el workspace por defecto. El usuario ve 404 o el asset de otro proyecto.
- **Archivos permitidos:** `ui/src/features/characters/CharacterCreatorPanel.tsx` y un test UI nuevo. No editar `client.ts` (el parámetro ya existe y el archivo está sucio).
- **Pasos:**
  1. Pasar `activeWorkspace` a `captureVideoEditorFrame`.
  2. Pasar `activeWorkspace` a todos los `getFileUrl(...)` del panel, incluido `model-viewer src`.
  3. Cubrir con un test que el payload de captura y las URLs de preview lleven el workspace.
- **Aceptación automática:** con workspace `otro`, el POST de screenshot incluye `workspace: "otro"` y las URLs contienen `?workspace=otro`.
- **Validación del usuario:** crear un character sheet en un workspace no default; las cuatro vistas y el GLB deben verse ahí, no en Default.
- **No hacer:** no restaurar sheets, no cambiar el motor PoopMan333, no tocar Hunyuan3DPanel.

### CHAR-02 — No restaurar un sheet si hay una sesión en curso

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Dependencia:** ninguna. Mejor después de `CHAR-01` para reutilizar el mismo test.
- **Evidencia:** `CharacterCreatorPanel.tsx:252-274` recorre hasta 50 vídeos al montar y llama `takePhotos` del último `character_sheet_engine === 'poopman333_6_panel'`. No mira `busy` ni `jobId`. `takePhotos` pone `busy=true` y pisa `views`.
- **Riesgo:** el usuario sube refs y pulsa generar mientras el restore aún lee metadatos; al terminar, el panel muestra el sheet viejo y puede abortar la sensación de progreso.
- **Archivos permitidos:** `CharacterCreatorPanel.tsx` y el test de `CHAR-01` o uno hermano.
- **Pasos:**
  1. No iniciar restore si `busy`, `jobId` o `hunyuanJobId` están activos.
  2. Antes de `setVideoName` / `takePhotos`, volver a comprobar que no hay generación en curso.
  3. Si el usuario ya eligió refs o pulsó generar, abandonar el restore.
- **Aceptación automática:** con un sheet viejo en outputs, montar el panel, pulsar generar antes de que acabe el restore; `views` y `jobId` de la sesión nueva se conservan.
- **Validación del usuario:** abrir Character Creator en un workspace con sheets antiguos, generar uno nuevo de inmediato; no debe volver el anterior.
- **No hacer:** no borrar la restauración útil cuando el panel está idle.

### VID-01 — Namespaced del draft del Video Editor por workspace

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** el export ya usa `maestro-video-editor-export-v1:${workspace}` (`VideoEditorPanel.tsx:130-146`, test `ui/tests/videoEditorExportPersistence.test.tsx`). El draft usa una sola clave `maestro-video-editor-draft-v1` (`:115`, `:688-719`) y se carga una vez al montar (`:728`). Series Review escribe `maestro-video-editor-pending-sequence` con URLs del workspace.
- **Riesgo:** al cambiar de workspace el montaje del anterior sigue en el timeline; al recargar, se mezcla.
- **Archivos permitidos:** `ui/src/features/video-editor/VideoEditorPanel.tsx` y el test de persistencia (o uno nuevo de draft).
- **Pasos:**
  1. Clave de draft `maestro-video-editor-draft-v1:${encodeURIComponent(workspace || 'default')}`.
  2. Recargar el draft al cambiar `activeWorkspace`.
  3. Ignorar clips cuya fuente no pertenezca al workspace actual.
  4. Migrar una sola vez el draft legacy sin workspace hacia el workspace activo, no hacia todos.
- **Aceptación automática:** workspace A guarda clips A; al cambiar a B el timeline no muestra A; al volver a A reaparecen. El export namespaced no cambia.
- **Validación del usuario:** dos workspaces, un corte en cada uno; el selector de workspace cambia el montaje, no lo mezcla.
- **No hacer:** no reabrir `EDITOR-01`/`EDITOR-02`/`EDITOR-03`.

### SER-UI-05 — Cancel/Resume de Review no reenganchan el episodio anterior

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** `SeriesReviewPanel.tsx:304` hace `api.cancelSeriesRenderJob(job.jobId).then(setJob)` y lo mismo en Resume. Assembly usa `.then(setAssemblyJob)` (`:383`). El cambio de episodio limpia estado (`:64-84`), pero una promesa tardía de E1 reescribe E2. `SeriesEpisodePanel.tsx:108-118` ya guarda por `episode.id`.
- **Riesgo:** el usuario cambia de episodio y ve la cola, el error o el botón Resume del anterior.
- **Archivos permitidos:** `ui/src/features/series/SeriesReviewPanel.tsx` y un test RTL hermano del de planning (`SER-UI-01`).
- **Pasos:**
  1. Capturar `episode.id` y `job.jobId` antes del await.
  2. Sólo `setJob` / `setAssemblyJob` si siguen coincidiendo con el episodio visible.
  3. Cubrir E1 cancel diferido → rerender E2: E2 no muestra el job de E1.
- **Aceptación automática:** la prueba E1→E2 de planning, replicada para Review render y assembly.
- **Validación del usuario:** lanzar generate missing en un episodio, saltar a otro, pulsar Cancel en el primero si aún está a mano; el segundo permanece vacío o con su propia cola.
- **No hacer:** no cambiar el contrato HTTP de render/assembly.

### SER-UI-06 — Recalcular duración sólo después de una preview correcta

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** `SeriesShotDurationControl.tsx:50-51` asigna `lastCalculatedSignature.current = signature` **antes** de `previewSeriesShotDuration`. Si la petición falla o el abort por cambio de `workspace`/`series.id` corta un request con el mismo diálogo, el efecto vuelve a salir en `:50` y no recalcula. Lo usan Shots (`SeriesShotsPanel.tsx:132`) y Review (`SeriesReviewPanel.tsx:361`).
- **Riesgo:** un shot con diálogo muestra una duración vieja o silenciosa y el render sale corto.
- **Archivos permitidos:** `SeriesShotDurationControl.tsx` y su test (o uno nuevo).
- **Pasos:**
  1. Escribir la firma sólo tras un `previewSeriesShotDuration` resuelto y no abortado.
  2. En abort, restaurar la firma anterior (o clavearla por `workspace:seriesId:shotId:signature`).
  3. Dejar el error visible y permitir un recálculo al reintentar.
- **Aceptación automática:** preview 500 no congela la firma; un abort por cambio de series con el mismo texto relanza la preview; un éxito no entra en bucle.
- **Validación del usuario:** shot con diálogo, cambiar de series y volver; el control debe recalcular voz/clip.
- **No hacer:** no reabrir `DUR-01`. El estimador de sílabas se queda.

### ACT-02 — Cancel/Resume/Dismiss del footer no pisan el workspace nuevo

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** `ActivityFooter.tsx:342-355` dispara `cancelCanonicalTask(task.id, activeWorkspace)` y en el `then` hace `setTasks` desde `tasksRef`. El footer ya trata el workspace como dueño del poll (`:205`, `:283-291`). Los controles no comprueban que el workspace siga siendo el de la pulsación.
- **Riesgo:** un Cancel lento de WS1 escribe la lista de WS1 encima del snapshot de WS2.
- **Archivos permitidos:** `ui/src/components/ActivityFooter.tsx` y el test de `ACT-01` o uno hermano.
- **Pasos:**
  1. Cerrar `workspace` y `task.id` en el click.
  2. Ignorar el resultado si el workspace activo ya no coincide.
  3. Aplicar por `task.id` sobre el snapshot actual, no sustituir la lista entera desde un `tasksRef` stale.
- **Aceptación automática:** Cancel de WS1 que resuelve después de cambiar a WS2 no muta las tareas de WS2. Retry de `ACT-01` sigue verde.
- **Validación del usuario:** dos workspaces con Activity, cancelar en uno y cambiar al otro antes de que vuelva; el segundo no hereda la lista.
- **No hacer:** no cambiar el contrato de `/api/v1/tasks`.

### COMIC-01 — Tratar `interrupted`/`crashed` como terminal en Comic PRE

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** `ComicWorkflowPanels.tsx:1449-1478` hace `for (;;)` y sólo sale con `preview_ready`, `failed` o `cancelled`. `interrupted` y `crashed` son terminales en Story (`StoryProductionTimeline.tsx:15-22`) y en colas (`workspaces/queue.ts:102`). No hay `AbortSignal` ni flag de unmount, así que `setPreflightStatus` sigue tras salir del panel. El poll de animatic (`:1067`) tiene el mismo agujero.
- **Riesgo:** un Director que se interrumpe deja el PRE en spinner eterno y escribe estado en un panel desmontado.
- **Archivos permitidos:** `ui/src/features/comics/ComicWorkflowPanels.tsx` y un test del flujo PRE/animatic.
- **Pasos:**
  1. Salir del bucle también con `interrupted` y `crashed`, como fallo.
  2. Pasar `AbortSignal` o un flag de unmount; no llamar `setPreflightStatus` después.
  3. Aplicar lo mismo al poll de export animatic.
- **Aceptación automática:** status `interrupted` lanza error visible y no vuelve a poll; unmount aborta el siguiente tick.
- **Validación del usuario:** lanzar Comic → PRE, parar el backend o Cancel a mitad; el panel muestra error y el botón vuelve a estar usable.
- **No hacer:** no cambiar el pipeline Director ni los contratos de `comic_movie`.

---

## Fase B — Un poll en vuelo

Patrón obligatorio: `useSerializedPoll` (`ui/src/hooks/useSerializedPoll.ts`) + `AbortSignal` en el cliente. Referencia ya verde: `SeriesEpisodePanel.tsx:37` y `ui/tests/useSerializedPoll.test.tsx`. Un panel por commit.

### SER-UI-04 — Poll serial de render/assembly en Series Review

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** `SeriesReviewPanel.tsx:85-97` usa `setInterval` con `activeJobCurrent` en deps. Un poll lento se solapa; un `current` menor puede pisar un snapshot más nuevo y disparar `reload()`. Assembly (`:98`) solapa igual, sin abort.
- **Archivos permitidos:** `SeriesReviewPanel.tsx`, el cliente de fetch de series si hay que hilar `signal` (no `client.ts` sucio: si el método ya acepta `signal`, usarlo; si no, añadir el arg en un helper local o esperar Fase D).
- **Pasos:**
  1. `useSerializedPoll({ ownerKey: jobId, intervalMs: 1000 })`.
  2. Quitar `activeJobCurrent` de las deps.
  3. `reload()` sólo en transición a terminal o cuando `value.current` sube respecto a un ref.
- **Aceptación automática:** dos respuestas fuera de orden; gana la más nueva. Unmount no aplica la tardía.
- **Validación del usuario:** generate missing de varios shots; la barra no salta atrás.
- **No hacer:** no mezclar este commit con `SER-UI-05`.

### CHAR-03 — Poll de órbita/Hunyuan con timer abortable y reintentos

- **Tipo:** mejora · **P2** · tamaño S.
- **Evidencia:** `CharacterCreatorPanel.tsx:276-309` y `:342-375` programan `setTimeout` sin guardar el id. El cleanup sólo pone `cancelled=true`; el timer dispara un GET extra. Un único error hace `setJobId(null)` y tira un job vivo. Hunyuan3DPanel ya reintenta 4 veces y trata 404 (`Hunyuan3DPanel.tsx:271-291`).
- **Archivos permitidos:** `CharacterCreatorPanel.tsx` y test de CHAR.
- **Pasos:**
  1. Guardar el timer, `clearTimeout` en cleanup, abortar el fetch.
  2. Reintentar un puñado de fallos transitorios; 404 o 4 fallos → error local, Generate otra vez usable.
- **Aceptación automática:** unmount no deja timer; un 500 aislado no borra el `jobId`; 404 sí.
- **Validación del usuario:** generar órbita, recargar el tab Character Creator; el job se reengancha o muestra error claro, no un spinner muerto.

### POLL-02 — Hunyuan3DPanel

- **Tipo:** mejora · **P2** · tamaño S.
- **Evidencia:** `Hunyuan3DPanel.tsx:271-300` `setInterval(poll, 1500)` sin serializar. Si el GET tarda más de 1,5 s, un status viejo puede pisar uno nuevo.
- **Archivos permitidos:** `Hunyuan3DPanel.tsx` y un test de poll.
- **Pasos:** `useSerializedPoll({ ownerKey: activeJobId })`. Conservar el conteo de 404/4 fallos.
- **Aceptación automática:** owner change aborta; un 404 marca `failed` local.
- **Validación del usuario:** generar un GLB; Cancel y Generate siguen respondiendo.

### POLL-03 — RigAnimatePanel

- **Tipo:** mejora · **P2** · tamaño S.
- **Evidencia:** `RigAnimatePanel.tsx:152-178`, el mismo patrón que POLL-02.
- **Archivos permitidos:** `RigAnimatePanel.tsx` y test.
- **Pasos / aceptación / validación:** iguales a `POLL-02`, con el mensaje de job perdido de rig.

### POLL-04 — StyleSheetPanel import

- **Tipo:** mejora · **P2** · tamaño S.
- **Evidencia:** `StyleSheetPanel.tsx:280-291` mete el objeto `importJob` entero en deps. Cada `setImportJob(next)` reinicia el interval. No hay flag `active`; un GET lento aplica un job viejo.
- **Archivos permitidos:** `StyleSheetPanel.tsx` y test de import.
- **Pasos:** poll por `importJob.jobId`; no depender del objeto entero; ignorar respuestas de otro `jobId`.
- **Aceptación automática:** dos status fuera de orden; gana el `jobId` actual. Unmount no llama `setImportJob`.
- **Validación del usuario:** importar estilos MiniMax, Cancelar; la UI no oscila entre queued/running viejos.

### POLL-05 — Quick Video Batch no pisa un cancel in-flight

- **Tipo:** mejora · **P2** · tamaño S.
- **Evidencia:** `QuickVideoBatchPanel.tsx:81-96` y `:150`. `refresh()` sustituye `jobs` entero cada 2,5 s. Un cancel/resume in-flight puede reaparecer como `running`.
- **Archivos permitidos:** `QuickVideoBatchPanel.tsx` y test de batches.
- **Pasos:**
  1. `useSerializedPoll` mientras haya jobs activos.
  2. Fusionar por `jobId` en vez de sustituir la lista.
  3. Un cancel local marca `cancelling` hasta que el servidor confirme.
- **Aceptación automática:** refresh que llega durante cancel no resucita `running`.
- **Validación del usuario:** lote de 3 ideas, Cancel del lote; no vuelve a “running” al siguiente tick.

---

## Fase C — Backend: cancelación y sidecars

### LLM-01 — `generate()` no-streaming debe abortar con el token de cancelación

- **Tipo:** bug confirmado · **P1** · tamaño M.
- **Evidencia:** `app/services/llm_service.py:2210-2218` hace `requests.post(..., timeout=(10, 600))` sin `_watch_response_for_cancellation`. `_scheduled_llm_request` sólo mira el token mientras espera el lane. `h3_window_planner.py:620` llama `llm_service.generate(..., json_schema=schema)`. Streaming (`generate_streaming`, OpenAI-compatible) sí está cubierto por `tests/test_llm_request_cancellation.py`.
- **Riesgo:** Cancel de Director/H3 durante el planner de ventanas deja el llama-server ocupado hasta 10 minutos. El GPU/CPU no se libera; el siguiente plan espera.
- **Archivos permitidos:** `app/services/llm_service.py`, `app/services/h3_window_planner.py` si hay que pasar el token, `tests/test_llm_request_cancellation.py` (ampliar, no duplicar).
- **Pasos:**
  1. Dar a `generate()` el mismo `cancellation_token` + watcher + `stream=True` (o `stream=bool(token)`) que `generate_streaming`.
  2. Cubrir Anthropic en el mismo camino.
  3. El planner H3 debe pasar el token de la tarea Director.
  4. Un test: token cancelado cierra el socket antes de los 600 s; el job pasa a cancelled.
- **Aceptación automática:** el harness de `test_llm_request_cancellation` también cubre `generate()` local y OpenAI-compatible. Un cancel a 100 ms no espera el timeout de lectura.
- **Validación del usuario:** Director Short Film H3, Cancel en “planning windows”; Activity pasa a cancelled en pocos segundos y se puede lanzar otra generación.
- **No hacer:** no reescribir el planner de ventanas ni tocar `director_pipeline.py` (sucio). Si el planner se llama desde ahí, pasar el token por el argumento ya existente.

### SER-04 — Borrar el sidecar si assembly se cancela tras FFmpeg

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** `app/routers/series_assembly.py:344-368` escribe `{output}.meta.json` y, si llega un cancel, borra el `.mp4` y no el sidecar. El `except` de `:423-438` igual. `test_cancelled_assembly_removes_output_created_during_cancellation` sólo afirma que no queda `*_series_assembly.mp4`.
- **Riesgo:** galería con un `.meta.json` huérfano; o un asset de biblioteca cuyo `uri` apunta a un MP4 que el except acaba de borrar (si el fallo es posterior a `write_library`).
- **Archivos permitidos:** `app/routers/series_assembly.py`, `app/services/series_assembly.py` si el unlink vive ahí, y `tests/test_series_assembly.py` / `test_series_assembly_router.py`.
- **Pasos:**
  1. Recordar `meta_path` junto a `output_path`; en cancel/fail borrar los dos.
  2. Tras un `write_library` correcto: el job está publicado. Un cancel tardío no borra media; se persiste `completed`.
  3. Test del hueco post-meta y del hueco post-library.
- **Aceptación automática:** cancel entre meta y publish → ni mp4 ni meta; cancel tras `write_library` → mp4 + meta + asset intactos y job `completed`.
- **Validación del usuario:** unir un episodio, Cancel en el último segundo; la galería no muestra un capítulo fantasma.
- **No hacer:** no reabrir `SER-03`. El abort cooperativo de FFmpeg se queda.

### TASK-08 — Soltar tokens de cancelación en cualquier terminal

- **Tipo:** mejora · **P2** · tamaño S.
- **Evidencia:** `app/services/task_manager.py:124` (`_update_cancellation_token`) sólo hace pop en `completed`/`failed`. `cancelled`, `interrupted` y `delete()` dejan entradas en `_cancellation_tokens` toda la vida del proceso. Un id reutilizado que no pase por `queued`+reset puede nacer ya cancelado.
- **Archivos permitidos:** `task_manager.py` y tests de task manager / assembly.
- **Pasos:** pop en cualquier status terminal y en `task.deleted`. `reset()` sólo en resume/reopen explícito.
- **Aceptación automática:** cancel → token ausente; delete de activa → token ausente; resume vuelve a crear token limpio.
- **Validación del usuario:** ninguna visible si A–C van bien. Es higiene de proceso largo.

### API-03 — Upsert de tarea cliente: 422 en vez de 500

- **Tipo:** mejora · **P2** · tamaño S.
- **Evidencia:** `app/routers/canonical_tasks.py:106` hace `int(...)` / `float(...)` sobre `current` / `total` / `startedAt` de un `dict` crudo. Un no-número es 500. Series assembly ya tiene contrato Pydantic y test 422 (`API-01`).
- **Archivos permitidos:** `canonical_tasks.py` y `tests/test_canonical_tasks_router.py`.
- **Pasos:** try/except con default 0/now, o modelo Pydantic `extra=forbid`. No cambiar el namespace `task-client-*`.
- **Aceptación automática:** body con `"current": "x"` → 422 estructurado, no 500.
- **Validación del usuario:** ninguna. Activity normal sigue igual.
- **No hacer:** no reabrir `TASK-01`…`TASK-07`.

---

## Fase D — Después del Grok Build de recipes

Ejecutar sólo cuando `git status` ya no liste los archivos sucios del compositor. Hasta entonces, estado `bloqueado`.

### VID-02 — La pestaña Edits pide la lista al servidor

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Bloqueo:** `ui/src/stores/useStore.ts` (loadOutputs) y posiblemente `ui/src/types/index.ts`.
- **Evidencia:** `galleryListQuery.ts` incluye `avatars` pero no pone `useServerList`. `loadOutputs` (`useStore.ts:9426`) pide las primeras 100 piezas mixtas. `computeFilteredOutputs` (`:2232-2239`) filtra en cliente por `edit_sub_mode` o `mode === 'avatar'`. Un edit antiguo no entra en esas 100.
- **Riesgo:** la pestaña Edits parece vacía con recasts/inpaints reales en disco.
- **Archivos permitidos:** `ui/src/lib/galleryListQuery.ts`, `useStore.ts` (sólo `loadOutputs` / query), test de galería. Backend de `/api/v1/outputs` si hace falta un query `edit_sub_mode`.
- **Pasos:**
  1. `avatars` debe activar lista de servidor (flag o `mediaType`/query dedicado).
  2. El servidor filtra por `edit_sub_mode` o `mode=avatar`, no devolver 100 mixtos.
  3. `jobFitsGalleryFilter` debe aceptar jobs de edit en esa pestaña.
- **Aceptación automática:** 120 outputs recientes no-edit + 1 recast viejo → Edits muestra el recast. `images`/`videos` no cambian.
- **Validación del usuario:** generar un retake, producir 100 imágenes, abrir Edits; el retake sigue ahí.
- **No hacer:** no volver a filtrar por `mode === 'avatar'` sólo; el comentario de `:2233-2238` explica por qué eso vació la lista.

### EDIT-01 — Revocar object URLs al sustituir el vídeo de edit

- **Tipo:** mejora · **P2** · tamaño S.
- **Bloqueo:** `ui/src/stores/useStore.ts`.
- **Evidencia:** `setEditVideo` (`:2687-2691`) y `clearEditVideo` (`:2692-2696`) pisan `editVideoUrl` sin `URL.revokeObjectURL`. Inpaint (`InpaintControls.tsx:72`) y Repaint (`RestyleControls.tsx:77`, `:97`) crean un blob por subida. `useObjectUrl` ya existe para el resto (`MEM-01`).
- **Riesgo:** varios vídeos grandes de edit en una sesión hinchan la pestaña hasta OOM del renderer.
- **Archivos permitidos:** `useStore.ts` (sólo set/clear de edit video/frame) o un helper usado por Inpaint/Restyle. Preferir `useObjectUrl` si no hay que tocar más el store.
- **Pasos:** revocar la URL anterior en set y en clear, tanto del vídeo como del frame de Repaint. No revocar URLs persistidas del servidor.
- **Aceptación automática:** dos subidas seguidas; la primera URL queda revocada (spy de `revokeObjectURL`). Clear también.
- **Validación del usuario:** subir tres vídeos a Inpaint; la pestaña no crece sin límite en el task manager del browser.
- **No hacer:** no reabrir `MEM-01` en Director.

### SCENE-01 — Validar el JSON de escena en el parser, no sólo en el panel

- **Tipo:** mejora · **P2** · tamaño S.
- **Evidencia:** `ui/src/lib/sceneFile.ts:21-28` comprueba `version === 1` y `layers` array, y hace cast a `Scene`. `importScene` en `SceneAnimatorPanel.tsx:1490+` normaliza ids, tipos, rangos. `sceneFromLibraryPayload` (`sceneLibrary.ts:25`) parsea y luego el panel vuelve a pasar por `importScene` (`:2584`). Un caller nuevo se salta las guardas.
- **Archivos permitidos:** `ui/src/lib/sceneFile.ts`, `ui/src/lib/sceneLibrary.ts`, test nuevo. No hace falta tocar el panel sucio si `importScene` sigue pudiendo ser más estricto encima.
- **Pasos:**
  1. Rechazar capas sin `id`/`type`, tipos desconocidos, `width`/`height` no finitos.
  2. Dejar defaults documentados (fps 30, duration > 0).
  3. `sceneFromLibraryPayload` reutiliza el parser; no duplicar reglas.
- **Aceptación automática:** JSON `{version:1, layers:[{}]}` lanza; una escena exportada por `serializeSceneFile` round-trip sin pérdida de ids.
- **Validación del usuario:** Abrir escena desde la librería y desde fichero; el compositor no se cae con un JSON a medias.

### SCENE-02 — El audio genérico de 3D Video tiene que sobrevivir la recipe

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Bloqueo:** `ui/src/lib/sceneRecipe.ts` y `SceneAnimatorPanel.tsx` están sucios. `sceneToRecipe.ts` está limpio, pero el contrato de `SceneRecipeAudio` vive en el archivo sucio.
- **Evidencia:** `attachSceneAudio` (`SceneAnimatorPanel.tsx:2118`, `:2453`) usa `kind: 'audio'` por defecto al adjuntar un output. `sceneToRecipe.ts:93` descarta `kind === 'audio'`. El speech generado sí se guarda (`kind: 'speech'`, `:2140`). El tipo de recipe sólo admite `'speech' | 'music' | 'sfx'`.
- **Riesgo:** el usuario pega un wav a la escena, exporta, reabre la recipe: el audio no está. El sidecar promete reproducción y miente.
- **Archivos permitidos:** `sceneToRecipe.ts`, `sceneRecipe.ts`, `SceneAnimatorPanel.tsx` (sólo el kind por defecto o el mapeo), tests `sceneRecipe.test.mjs` / uno de `sceneToRecipe`.
- **Pasos:**
  1. Decidir un mapeo: o la recipe acepta `audio`, o el adjunto de galería se etiqueta `sfx`/`music`.
  2. Round-trip: escena con un track `audio` → recipe → escena; el filename y el volumen siguen.
  3. No tirar `model` ni `prompt` si el Grok Build ya los serializa.
- **Aceptación automática:** attach de un wav de galería + `sceneToRecipe` + `compileSceneRecipe` conserva el track. Speech/music/sfx no se duplican.
- **Validación del usuario:** 3D Video, “Choose audio…”, exportar, reabrir recipe; el audio suena.
- **No hacer:** no reimplementar el hueco de keyframes (`SCENE-03`). Coordinar con el Grok Build si aún no ha aterrizado.

---

## Fase E — Evolución, no hotfix

### SCENE-03 — Cerrar el hueco Scene → Recipe que ya está documentado

- **Tipo:** deuda de contrato · **P2** · tamaño L.
- **Bloqueo:** es el trabajo del Grok Build actual y de [`scene-recipe-gap.md`](scene-recipe-gap.md).
- **Evidencia:** 122 campos auditados; 65 no viajan. El bloqueo de fase 4 del compositor es `animation.keyframes`. También `strip`/`seamOccluder`, `visible`/`locked`, `relationship`, timing, `effects.blur`.
- **Pasos:** no empezar un segundo diseño. Cuando el Grok Build aterrice, re-leer `scene-recipe-gap.md`, marcar qué lista A quedó hecha, y abrir tickets de un campo (o un cluster) por commit.
- **Aceptación automática:** la que ya exija ese build (round-trip de template + keyframes).
- **No hacer:** no escribir un serializer paralelo. `sceneToRecipe.ts` es el único sitio.

### ARCH-04 — Seguir partiendo el monolito, no reescribirlo

- **Tipo:** deuda · **P3** · tamaño L.
- **Evidencia:** `_launch_runtime.py`, `director_pipeline.py` y `useStore.ts` siguen siendo los tres archivos más grandes. `ARCH-01`…`ARCH-03` ya sacaron launch factory, router de tasks y job reducers.
- **Pasos:** un dominio vertical por PR (el siguiente candidato natural: outputs/upload, o el resto de canonical tasks). Misma regla que `ARCH-02`: URLs, status codes y side effects idénticos + snapshot OpenAPI.
- **Aceptación automática:** tests de caracterización del dominio extraído en verde; el bundle/entry budget no sube.
- **No hacer:** no “limpiar” `_launch_runtime.py` de golpe. No mezclar con Fase A–D.

---

## Fuera de alcance a propósito

- Vendor Hunyuan/SAM/UniRig, kernels, FlashVSR, Sage Attention `FIXME`.
- Relajar o endurecer LAN auth (`SEC-03` ya es opt-in).
- Compactar la DB de Activity (`TASK-06` ya existe).
- Cambiar el motor PoopMan333 ni los prompts de órbita.
- Cualquier ticket nuevo sobre cutout dialogue / visemes mientras el Grok Build esté vivo.

## Cómo ejecutar un ticket

1. Copiar el ID al mensaje del commit: `fix: CHAR-01 pass workspace into character creator urls`.
2. No ampliar el “archivos permitidos”.
3. Correr la aceptación automática del ticket + la suite corta del área (`ui` tests del panel, o pytest del servicio).
4. No marcar `completado` en el tablero de arriba sin la evidencia (test o comando) en el cuerpo del commit.
5. Si un ticket de Fase D se desbloquea a mitad, no adelantarlo por delante de A–C: la identidad de workspace/episodio sigue siendo más barata y más visible.

## Definición de hecho de esta hoja

La hoja está hecha cuando:

- Fase A y C están `completado` con tests.
- Fase B no deja `setInterval` de jobs en Character Creator, Hunyuan3D, Rig, Style import, Quick Video Batch ni Series Review.
- Fase D se ha re-evaluado contra el diff final del Grok Build (algún ítem puede haber quedado resuelto ahí; entonces se marca `completado` con la evidencia de ese commit, no se reimplementa).
- `SCENE-03` y `ARCH-04` pueden seguir `pendiente` sin bloquear un corte de producto.
