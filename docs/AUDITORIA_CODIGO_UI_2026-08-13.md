# Auditoría de código, implementaciones y UI — 2026-08-13

## Objetivo y alcance

Este documento convierte la revisión del estado actual de Maestro/Loreframe Lab en un backlog de tareas pequeñas, independientes y verificables. Está escrito para que un agente con poca capacidad de contexto, como GPT-Luna, pueda ejecutar **una sola tarea por vez** sin tener que rediseñar el sistema.

La auditoría se hizo sobre el *working tree* actual, que contiene cambios todavía no confirmados y archivos nuevos. Por tanto, las referencias describen el código que estaba en disco el 13 de agosto de 2026, no únicamente el último commit.

Superficie revisada:

- Backend propio: `app/launch.py`, `app/services/`, `app/routers/`.
- UI propia: `ui/src/`, incluidos Series Lab, Story Lab, Director, Activity y Video Editor.
- Contratos y pruebas: `tests/`, `ui/tests/`, `pytest.ini`, CI.
- Lanzador Pinokio: `pinokio.js`, `start.js`, `install.js`, `update.js` y logs.
- Estado real: `logs/api/start.js/latest`, base SQLite de Activity, aplicación en ejecución y revisión visual de escritorio/móvil.

No se ha hecho una revisión línea por línea del código de terceros o *vendor* ni de los pesos/modelos. Tampoco es una auditoría de penetración formal. Los hallazgos se clasifican así:

- **Confirmado:** existe una reproducción, un fallo de test, evidencia de log/DB o un camino de código inequívoco.
- **Probable:** el riesgo está sustentado en código, pero la primera acción debe ser escribir una prueba que lo reproduzca.
- **Mejora:** no hay un fallo inmediato, pero reduce deuda, coste o riesgo.

Prioridades:

- **P0:** corregir antes de exponer o seguir usando la función afectada.
- **P1:** siguiente bloque de trabajo; puede causar pérdida, corrupción, caída o una función incorrecta.
- **P2:** fiabilidad, UX, accesibilidad o mantenibilidad importante.
- **P3:** limpieza y evolución gradual.

## Resultado de las comprobaciones

| Comprobación | Resultado |
|---|---|
| Compilación Python de módulos propios | Correcta |
| `PYTHONPATH=app ... pytest -q` | **3 fallos, 1.219 correctos**; los tres proceden del mismo harness incompleto |
| `unittest discover` | 796 correctos, pero omite muchas funciones pytest |
| Build UI | Correcto |
| Lint UI | 0 errores, 1 warning de dependencias de un efecto |
| Tests Node actuales | 6/6 correctos, pero no están integrados en `package.json` ni CI |
| Clean-repo guard | Correcto |
| `git diff --check` | Correcto |
| Preflight del backend durante la revisión | Correcto cuando el proceso respondió |
| Revisión visual | Escritorio razonable; problemas concretos de accesibilidad y layout móvil |

Mediciones relevantes:

- `app/launch.py`: 35.902 líneas.
- `app/services/director_pipeline.py`: 13.480 líneas.
- `ui/src/stores/useStore.ts`: 10.726 líneas.
- `ui/src/features/stories/StoryLabPanel.tsx`: 6.976 líneas.
- `ui/src/api/client.ts`: 4.456 líneas.
- Bundle principal: aproximadamente 1,13 MB sin comprimir; Vite avisa de varios chunks superiores a 500 KB.
- Base de Activity observada: 266.436.608 bytes, más de 541.000 eventos; más de 540.000 eran `adapter.synced`.
- Un plan real de videoclip de 41 clips se truncó, reparó sólo parcialmente y terminó en HTTP 500.

## Lo que ya existe y no debe reimplementarse

Series Review ya incluye:

- `Approve all`.
- `Play all` en orden.
- Unión de clips.
- Edición y regeneración en el mismo slot.
- Indicador del slot que será sustituido.

Referencias: `ui/src/features/series/SeriesReviewPanel.tsx:157-170` y `:278-316`. Las tareas de este documento corrigen fallos alrededor de ese flujo; no piden crear otra implementación paralela.

## Orden recomendado

No ejecutar todo a la vez. El orden seguro es:

1. `SEC-01`, `SEC-02`.
2. `TEST-01`, `TEST-02`, `CI-01`, `CI-02`.
3. `TASK-01` a `TASK-06`.
4. `DIR-01`, `DIR-02`, `PLAN-01` a `PLAN-03`.
5. `SER-01`, `SER-02`, `SER-UI-01`, `DUR-01`.
6. Carreras de Story/workspaces/editor.
7. Resto de P2 y P3.

Cada ID debe ser un commit separado salvo que el propio ticket diga lo contrario.

---

## Bloque A — Seguridad y confinamiento

### SEC-01 — Confinar “Move output” al workspace

- **Tipo:** bug confirmado · **P0** · tamaño S.
- **Evidencia:** `app/launch.py:34808-34836` concatena `name` con `os.path.join` y mueve el resultado sin `_safe_join`. La ruta acepta `{name:path}`.
- **Riesgo:** una ruta relativa con `..`, absoluta o un symlink puede mover un archivo fuera de `outputs` y romper la aplicación o perder datos.
- **Archivos permitidos:** `app/launch.py` y un test nuevo específico.
- **Pasos:**
  1. Crear un resolvedor común que haga `realpath` y compruebe `commonpath` para origen y destino.
  2. Aceptar sólo una ruta relativa de media dentro del workspace origen.
  3. Rechazar rutas absolutas, `..`, separadores alternativos y symlinks que escapen.
  4. Aplicar la misma validación al sidecar y preview asociados antes de moverlos.
- **Aceptación automática:** con directorios temporales, nombre simple mueve el fichero; traversal, absoluta y symlink devuelven 400 y dejan intactos todos los archivos.
- **Validación del usuario:** usar sólo un marcador desechable dentro de un workspace de prueba; comprobar que mover desde la UI funciona y que una petición de escape preparada por el test recibe 400.
- **No hacer:** no probar contra `launch.py` real ni contra archivos personales.

### SEC-02 — Aceptar audio sólo desde uploads/assets del workspace

- **Tipo:** bug confirmado · **P1** · tamaño M.
- **Evidencia:** `app/launch.py:9010-9048`, `:9164-9194` y `:9421-9429` aceptan cualquier `audio_path` que exista. `/audio/mix` ya tiene un patrón de confinamiento mejor.
- **Riesgo:** una ruta conocida del host puede analizarse o copiarse a un endpoint servido.
- **Archivos permitidos:** `app/launch.py`, un helper pequeño en `app/services/` y tests de rutas.
- **Pasos:**
  1. Crear `resolve_permitted_media_path(value, workspace, kinds)` con `realpath/commonpath`.
  2. Permitir únicamente `uploads` y el output del workspace indicado, preferiblemente mediante asset ID.
  3. Aplicarlo a trim, análisis síncrono y job asíncrono.
  4. No devolver la ruta absoluta rechazada en el error.
- **Aceptación automática:** fichero externo y symlink de escape => 400; upload y asset del workspace => correcto; asset de otro workspace => 400/404.
- **Validación del usuario:** subir un audio normal, recortarlo y analizarlo; el flujo visible debe ser idéntico.

### SEC-03 — Autenticación cuando se comparte por LAN

- **Tipo:** riesgo confirmado sólo en modo compartido · **P2** · tamaño M.
- **Evidencia:** `app/launch.py:35820-35826` permite `0.0.0.0`; el middleware de `:268-292` sólo valida `Origin` si la cabecera existe. Un cliente LAN sin `Origin` puede mutar la API.
- **Pasos:** generar/configurar un token de sesión para LAN; exigir cookie segura en la UI o bearer token en API; mantener el flujo loopback sin fricción.
- **Aceptación automática:** en modo share, POST sin token => 401; token válido => correcto; loopback conserva compatibilidad.
- **Validación del usuario:** probar desde otro dispositivo de la LAN con y sin token.

---

## Bloque B — Activity, tareas y SQLite

### TASK-01 — Reservar namespaces de IDs de tareas

- **Tipo:** corrupción confirmada · **P1** · tamaño S.
- **Evidencia:** `app/launch.py:35575-35600` conserva literalmente cualquier ID cliente que empiece por `task-`. Puede colisionar con `task-generation-*` o `task-director-*`. En la DB real se observaron campos terminales alternando entre dos productores.
- **Pasos:**
  1. Todo upsert frontend debe terminar en `task-client-<id-normalizado>` exactamente una vez.
  2. Rechazar o remapear namespaces reservados del backend.
  3. El cliente no puede elegir `root_id` canónico de otra tarea.
  4. Mantener compatibilidad sólo para IDs ya `task-client-*`.
- **Aceptación automática:** crear `task-generation-demo`, publicar desde frontend con el mismo texto y comprobar que nace `task-client-task-generation-demo`; el snapshot y la secuencia originales no cambian.
- **Validación del usuario:** una generación debe mostrar su tarea backend y, si procede, su actividad frontend sin cambiar fecha/estado entre refrescos.

### TASK-02 — No escribir eventos semánticamente vacíos

- **Tipo:** bug de rendimiento confirmado · **P1** · tamaño S.
- **Evidencia:** `app/services/task_manager.py:398-458` cambia `updated_at` y añade evento en cada `update`, aunque el contenido útil sea idéntico.
- **Dependencia:** `TASK-01`.
- **Pasos:** eliminar campos volátiles de la comparación; comparar el patch normalizado con el snapshot; devolver el snapshot existente sin evento ni notify cuando no cambie nada.
- **Aceptación automática:** 10.000 sincronizaciones idénticas añaden como máximo un evento; un cambio real y una transición terminal añaden exactamente uno cada uno.
- **Validación del usuario:** Activity abierta sin trabajo no debe aumentar continuamente el contador de eventos.

### TASK-03 — Dedupe y throttle del progreso frontend

- **Tipo:** bug de rendimiento confirmado · **P1** · tamaño S.
- **Evidencia:** `ui/src/stores/useStore.ts:8084-8117` consulta cada 800 ms y cada respuesta llama `activity.report`; `:7208-7228` publica un POST canónico.
- **Pasos:** guardar el último hash publicado; no enviar estados iguales; limitar progreso no terminal a una publicación cada 1–2 s; publicar inmediatamente errores y terminales.
- **Aceptación automática:** 100 polls iguales producen 1–2 publicaciones; `running → completed` no se retrasa.
- **Validación del usuario:** plan de dos minutos; Network no debe mostrar un POST `/tasks/upsert` por cada GET de progreso.

### TASK-04 — Iniciar SSE desde el high-water mark del snapshot

- **Tipo:** bug de escalabilidad confirmado · **P1** · tamaño M.
- **Evidencia:** `ui/src/lib/canonicalTaskEvents.ts:179-190` comienza con `lastEventId = 0`. El backend entrega 500 eventos por lote; con más de 541.000 eventos, una primera conexión reproduce más de mil lotes históricos.
- **Pasos:**
  1. Devolver `latest_event_id` junto al snapshot de `/api/v1/tasks`.
  2. Abrir SSE con ese cursor después de reconciliar el snapshot.
  3. Definir la frontera snapshot/cursor para no perder eventos concurrentes.
  4. Mantener `Last-Event-ID` en reconexiones.
- **Aceptación automática:** fixture con 10.000 eventos viejos + cambio concurrente; primera conexión no reproduce lo viejo y sí recibe el cambio sin duplicarlo.
- **Validación del usuario:** una sesión nueva debe abrir Activity rápidamente aunque la DB histórica sea grande.

### TASK-05 — Retención con `resync_required`

- **Tipo:** carencia confirmada · **P1** · tamaño M.
- **Evidencia:** `TaskRegistry.prune()` en `app/services/task_manager.py:611-620` no tiene caller y sólo borra snapshots; los eventos y tombstones quedan para siempre.
- **Dependencias:** `TASK-01` a `TASK-04`.
- **Pasos:** política configurable por edad/cantidad; conservar activos, último terminal y tombstone necesario; guardar cursor mínimo; si un cliente pide uno ya eliminado, emitir `resync_required` para que vuelva a pedir snapshot.
- **Aceptación automática:** prune conserva activos y estado final; un cursor antiguo recibe `resync_required`; cursor reciente continúa normalmente.
- **Validación del usuario:** dejar una copia de la DB, ejecutar dry-run y revisar qué se conservaría antes de borrar nada.

### TASK-06 — Mantenimiento y compactación segura de la DB existente

- **Tipo:** reparación operativa · **P1** · tamaño M.
- **Dependencia:** causa corregida en `TASK-01` a `TASK-05`.
- **Pasos:** añadir versión de esquema; comando con `--dry-run`; backup previo; borrar según retención; checkpoint WAL y compactar sólo con el backend detenido o mediante estrategia segura documentada.
- **Aceptación automática:** migrar dos veces una fixture legacy produce el mismo resultado; backup restaura todos los snapshots finales.
- **Validación del usuario:** ejecutar primero sólo dry-run sobre una copia de los 266 MB; comparar filas y tamaño, nunca compactar la única copia directamente.

### TASK-07 — No persistir el stream bruto del LLM en cada evento

- **Tipo:** mejora de rendimiento/privacidad · **P2** · tamaño S.
- **Evidencia:** el tail del stream se envía como detalle repetidamente y queda en el historial durable; una tarea observada acumuló cientos de eventos y cientos de KB de cambios.
- **Pasos:** mantener una preview corta en snapshot; no duplicarla si no cambió; no persistir texto bruto en cada evento; documentar qué metadatos son durables.
- **Aceptación automática:** un stream largo mantiene detalle visible, pero el tamaño total del historial queda acotado.

---

## Bloque C — Director y planificación de videoclips

### DIR-01 — Preservar el índice real al recuperar imágenes

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** `ui/src/stores/useStore.ts:3342-3349` filtra clips sin imagen y luego usa el índice del array filtrado. El patrón correcto aparece en `:10603-10620`.
- **Pasos:** mapear el `clipIndex` original antes de filtrar; usar identidad estable de shot si existe; compartir el helper entre carga y polling.
- **Aceptación automática:** `[sin imagen, b.png, sin imagen, d.png]` produce índices `[1, 3]`.
- **Validación del usuario:** reabrir una pipeline con hueco en el primer clip; la miniatura debe aparecer en el slot correcto.

### DIR-02 — Soportar preview recuperada sin objeto `File`

- **Tipo:** crash confirmado por camino de código · **P1** · tamaño S.
- **Evidencia:** `DirectorClipImage.file` exige `File` en `ui/src/types/index.ts:1274-1279`; recovery inyecta `null as File`; `DirectorPanel.tsx:679,723` llama `URL.createObjectURL(null)`. `DirectorChat` ya tiene fallback a filename.
- **Dependencia:** `DIR-01`.
- **Pasos:** hacer `file` nullable; resolver `File` o URL backend mediante un hook; revocar object URLs; reemplazar ambos usos inseguros.
- **Aceptación automática:** una imagen con sólo `filename` renderiza URL backend sin llamar `createObjectURL`; una con `File` crea y revoca una URL.
- **Validación del usuario:** reabrir una pipeline guardada y navegar por sus imágenes sin error de consola.

### PLAN-01 — Planificar videoclips por lotes acotados

- **Tipo:** fallo real confirmado · **P1** · tamaño M.
- **Evidencia:** `app/services/director/planners/music_video.py:1050-1109` solicita todos los clips en un único JSON; `:1122-1179` hace una sola reparación. El log real de 41 clips truncó respuesta y reparación y terminó en 500.
- **Pasos:** lotes deterministas de 6–8 índices; validar cada lote; reparar sólo faltantes del lote; fallback individual para el último faltante; combinar por `clip_index` y rechazar duplicados.
- **Aceptación automática:** fake LLM que trunca cualquier respuesta de más de 8 objetos debe terminar con exactamente 41 índices únicos y ordenados.
- **Validación del usuario:** repetir el plan real de 41 clips; no debe perder lotes ya correctos ni devolver 500 por truncamiento del final.

### PLAN-02 — Persistir lotes completos y reanudar

- **Tipo:** mejora de recuperación · **P1** · tamaño M.
- **Dependencia:** `PLAN-01`.
- **Pasos:** crear job durable; guardar cada lote validado y sus índices; al reanudar pedir sólo faltantes; marcar claramente lote activo, llamadas y tokens.
- **Aceptación automática:** interrumpir tras lote 3, recrear servicio y completar sin volver a llamar a los lotes 1–3.
- **Validación del usuario:** recargar la UI durante un plan largo y pulsar Resume; el progreso debe continuar.

### PLAN-03 — Error estructurado y propuesta parcial recuperable

- **Tipo:** mejora funcional · **P2** · tamaño S/M.
- **Dependencia:** `PLAN-02`.
- **Pasos:** no devolver sólo un 500 genérico; incluir job ID, índices completos/faltantes y acción de reanudar; UI con tarjeta “reanudar clips faltantes”. No encolar imágenes hasta que el plan esté completo.
- **Aceptación automática:** fallo final conserva lotes y la respuesta enumera índices faltantes; Resume completa la propuesta.
- **Validación del usuario:** simular un proveedor que falla en el último lote; la UI debe mostrar qué queda y no perder lo anterior.

### DIR-03 — Mostrar el fallo al cargar una pipeline

- **Tipo:** bug UX confirmado · **P2** · tamaño S.
- **Evidencia:** `ui/src/stores/useStore.ts:3011-3025` sólo hace `console.error`; el selector no informa al usuario.
- **Pasos:** estado `dashboardLoadError`; mantener selección anterior coherente; mensaje visible y Retry.
- **Aceptación automática:** fetch rechazado muestra error; Retry correcto lo limpia y carga la nueva pipeline.

---

## Bloque D — Series Lab y concurrencia de datos

### SER-01 — PUT de episodio con revisión y campos server-owned

- **Tipo:** riesgo de pérdida confirmado · **P1** · tamaño M.
- **Evidencia:** `app/launch.py:28503-28528` sustituye casi todo el episodio con el objeto del cliente, sin `baseRevision`, y puede borrar attempts, aprobaciones o assembly añadidos por un worker.
- **Pasos:** exigir `baseSeriesRevision` o `baseEpisodeUpdatedAt`; 409 si está stale; aceptar patch de campos editables; preservar/mezclar campos runtime propiedad del servidor.
- **Aceptación automática:** tras añadir un attempt en servidor, un PUT antiguo devuelve 409 y conserva el attempt; un PUT vigente cambia prompt sin tocar runtime.
- **Validación del usuario:** dos pestañas; renderizar en una y guardar una copia vieja en otra debe pedir refresh, no borrar el render.

### SER-02 — Impedir borrar series/episodios con trabajos activos

- **Tipo:** bug confirmado · **P1** · tamaño S/M.
- **Evidencia:** DELETE de serie en `app/launch.py:28244-28253` no revisa jobs; DELETE de episodio revisa plan/render pero no assembly.
- **Pasos:** consulta central de lifecycle por workspace/series/episodio; incluir planning, render y assembly; devolver 409 con IDs activos; permitir borrar sólo tras cancelar/terminar.
- **Aceptación automática:** cada tipo de job activo bloquea DELETE; después de terminal permite borrar y preserva outputs según contrato.
- **Validación del usuario:** iniciar render/join e intentar borrar desde la UI; debe explicar qué trabajo hay que cancelar.

### SER-UI-01 — No mostrar/aplicar una propuesta en otro episodio

- **Tipo:** bug UI confirmado · **P1** · tamaño S.
- **Evidencia:** `SeriesEpisodePanel.tsx:19-35` conserva el job local al cambiar `episode.id`; `:77-81` presenta la propuesta contra el episodio actual.
- **Pasos:** reset por `episode.id`; exigir `job.episodeId === episode.id` antes de mostrar/aplicar; identificar el episodio propietario si llega el resultado en segundo plano.
- **Aceptación automática:** empezar con E1, rerender E2 y resolver E1; E2 no muestra ni aplica esa propuesta.
- **Validación del usuario:** planificar E1, cambiar a E2 y esperar; E2 permanece limpio.

### SER-UI-02 — Limpiar estado de Review al cambiar episodio

- **Tipo:** bug UI confirmado · **P2** · tamaño S.
- **Evidencia:** `SeriesReviewPanel.tsx:41-55` guarda decisiones, reproducción, foco, edición y assembly sin limpieza por episodio.
- **Pasos:** pausar vídeo y resetear estado derivado cuando cambia `episode.id`.
- **Aceptación automática:** rerender E1→E2 deja foco, play, editor y decisiones en estado inicial.

### DUR-01 — Contrato único de duración calculada por diálogo

- **Tipo:** incumplimiento funcional confirmado · **P1** · tamaño M.
- **Evidencia:** la UI y schema Series fuerzan 5/10/15 (`SeriesEpisodeProposalReview.tsx:91`, `SeriesReviewPanel.tsx:315`, `SeriesShotsPanel.tsx:114`, `app/services/series_planning.py:134`). Esto puede redondear hacia abajo una estimación por sílabas.
- **Pasos:**
  1. Centralizar la estimación segundos/sílaba y las pausas en backend.
  2. Guardar la estimación exacta como metadato explicable.
  3. Consultar capacidades del modelo: si acepta duración continua, conservarla; si usa una lattice, elegir siempre el menor valor soportado **mayor o igual** a la voz, nunca uno menor.
  4. Crear un único `SeriesShotDurationControl` que muestre “voz estimada” y “clip solicitado”.
  5. Aplicar el mismo valor en propuesta, edición, regeneración y render futuro.
- **Aceptación automática:** diálogo estimado en 6,5 s nunca se convierte en 5 s; queda 6,5 s en modelo continuo o el siguiente valor soportado (por ejemplo 10 s) en modelo discreto. Persistir/reabrir no cambia el resultado.
- **Validación del usuario:** editar una frase, comprobar el recálculo y regenerar; ningún clip debe quedar más corto que su diálogo.
- **No hacer:** no permitir duraciones que el proveedor realmente no soporte; usar trim no destructivo para el sobrante final.

### SER-UI-03 — Selección coherente al aprobar un shot

- **Tipo:** bug UI confirmado · **P2** · tamaño S.
- **Evidencia:** `SeriesShotsPanel.tsx:26-36` excluye aprobados del contador, pero el checkbox puede seguir marcado en `:100-107`.
- **Pasos:** deshabilitar/ocultar selección para aprobados y podar selección contra `selectableShotIds`.
- **Aceptación automática:** seleccionar y aprobar un shot lo desmarca y actualiza contador/botón.

### SER-03 — Integrar Assembly en TaskRegistry y cancelación

- **Tipo:** carencia confirmada · **P2** · tamaño M.
- **Evidencia:** `app/routers/series_assembly.py:63-69` mantiene jobs privados; sólo hay start/status en `:241-318`; no se publica en `_sync_canonical_tasks`.
- **Pasos:** publicar tarea canónica; status confinado por workspace; cancel cooperativo del proceso FFmpeg; estados cancelled/interrupted/retry; normalizar checkpoints stale al arrancar.
- **Aceptación automática:** assembly queued/running aparece en Activity, se cancela, no cruza workspace y se recupera como interrupted tras reinicio.
- **Validación del usuario:** iniciar Join, verlo en Activity, cancelarlo y reintentarlo.

---

## Bloque E — Story Lab, workspaces y estado asíncrono

### STORY-01 — Aplicar resultados asíncronos a la Story propietaria

- **Tipo:** bug confirmado · **P1** · tamaño M.
- **Evidencia:** operaciones ocupadas se distribuyen por `StoryLabPanel.tsx:830-904`; navegación sólo bloquea `busy || imageBusy` en `:4418-4505`; conversiones/versiones mutan el proyecto actualmente abierto después de `await`.
- **Pasos:** crear `updateProjectById`; capturar `projectId` al iniciar cada operación; aplicar por ID al resolver; bloquear borrar/duplicar la entidad con trabajo activo; no reutilizar IDs internos al duplicar.
- **Aceptación automática:** iniciar promesa en A, abrir B y resolver; sólo A cambia. Duplicar A produce IDs internos únicos.
- **Validación del usuario:** iniciar conversión por lotes e intentar cambiar/duplicar/borrar; el resultado nunca debe aterrizar en otra Story.

### STORY-02 — Respetar DeepSeek y OpenAI-compatible

- **Tipo:** bug confirmado · **P1** · tamaño S.
- **Evidencia:** `StoryLabPanel.tsx:1030-1047` reconoce proveedores, pero `:1673-1683` convierte varios a Maestro al construir la petición.
- **Pasos:** helper puro `resolveStoryWritingProvider(profile, project)` usado tanto para mostrar como enviar; incluir provider, model y base URL.
- **Aceptación automática:** tabla de casos para MiniMax, OpenAI, DeepSeek, OpenAI-compatible y Maestro.
- **Validación del usuario:** seleccionar cada proveedor e inspeccionar la petición; lo enviado coincide con la UI.

### STORY-03 — Fusionar fallback local y remoto sin perder la versión nueva

- **Tipo:** riesgo de pérdida confirmado · **P1** · tamaño M.
- **Evidencia:** `ui/src/features/stories/store.ts:36-55` recupera local; `:147-179` lo reemplaza con cualquier biblioteca remota válida, aunque sea anterior.
- **Pasos:** comparar `updatedAt` por Story; fusionar proyectos exclusivos; conservar el más nuevo; ante empate divergente crear conflicto visible, no sobrescribir.
- **Aceptación automática:** remoto viejo/local nuevo, remoto nuevo/local viejo, exclusivos y empate divergente.
- **Validación del usuario:** editar con backend caído, restaurarlo y recargar; la edición local se conserva o aparece como conflicto.

### STORY-04 — Revisión monotónica también en la biblioteca backend

- **Tipo:** riesgo probable/arquitectónico · **P2** · tamaño M.
- **Evidencia:** `app/launch.py:30447-30463` reemplaza la biblioteca completa; `app/services/story_library.py` no tiene revisión/ETag.
- **Pasos:** añadir `revision`; exigir `baseRevision`; 409 al cliente stale; después crear endpoints patch por proyecto de forma incremental.
- **Aceptación automática:** dos PUT desde revisión N: el primero crea N+1 y el segundo recibe 409 sin borrar el primero.

### UI-WS-01 — Descartar respuestas de outputs de otro workspace

- **Tipo:** carrera confirmada · **P1** · tamaño S/M.
- **Evidencia:** `useStore.ts:9187-9200` lanza cargas sin epoch; `:9289-9324` aplica cualquier respuesta y no siempre manda workspace explícito.
- **Pasos:** capturar workspace + request epoch; pasarlo explícito a API; descartar respuesta si ya cambió; abortar fetch anterior cuando sea posible.
- **Aceptación automática:** A lento, B rápido, A resuelve al final; el estado contiene únicamente B.
- **Validación del usuario:** alternar workspaces con throttling de red; no deben mezclarse nombres/rutas.

### UI-SEARCH-01 — Cancelar debounce al cerrar búsqueda

- **Tipo:** bug UI confirmado · **P2** · tamaño S.
- **Evidencia:** `TabFilter.tsx:39-42` crea timer; `:93-96` cierra sin cancelarlo. La búsqueda oculta puede activarse 400 ms después.
- **Pasos:** input controlado; `cancelPendingSearch` al cerrar/desmontar; limpiar store siempre.
- **Aceptación automática:** escribir, cerrar, avanzar timers; query permanece vacía y no carga outputs.

### UI-GEN-01 — Derivar `isGenerating` sólo de jobs activos

- **Tipo:** bug confirmado · **P2** · tamaño S.
- **Evidencia:** `useStore.ts:5962-5976` usa `remaining.length > 0`; otras rutas usan correctamente `.some(_isGenerationJobActive)`.
- **Pasos:** helper único `deriveIsGenerating(jobs)` y reemplazo de todas las derivaciones.
- **Aceptación automática:** al completar el único activo y quedar sólo failed/cancelled, `isGenerating` es false.

---

## Bloque F — Video Editor y reproducción ordenada

### EDITOR-01 — Importar handoff de forma atómica

- **Tipo:** pérdida confirmada por camino de código · **P1** · tamaño M.
- **Evidencia:** `VideoEditorPanel.tsx:757-798` borra el handoff y vacía el montaje antes de verificar todas las fuentes.
- **Pasos:** probar fuentes en colección temporal; no tocar draft ni clave pendiente hasta éxito completo; reemplazo atómico; confirmación si ya existe montaje; Retry conservando handoff.
- **Aceptación automática:** falla la segunda de tres fuentes; draft anterior y handoff siguen intactos, sin autosave parcial.
- **Validación del usuario:** handoff de prueba con una URL inválida; debe conservar el montaje anterior y ofrecer Retry.

### EDITOR-02 — Reenganchar una exportación al volver al editor

- **Tipo:** carencia confirmada · **P2** · tamaño M.
- **Evidencia:** `VideoEditorPanel.tsx:672`, `:690-696` y `:1393-1441`: job/polling viven sólo en el componente montado.
- **Pasos:** persistir job ID por workspace; al montar consultar status; reanudar polling; impedir segundo POST mientras el job siga activo.
- **Aceptación automática:** iniciar, desmontar y remontar reengancha el mismo ID.
- **Validación del usuario:** comenzar export, cambiar de tab y regresar; debe mostrar progreso/cancel/download del mismo job.

### EDITOR-03 — Normalizar drafts y trims antes de usarlos

- **Tipo:** bug de robustez confirmado · **P2** · tamaño S/M.
- **Evidencia:** `VideoEditorPanel.tsx:557-624` deja pasar `NaN`, tiempos invertidos o campos corruptos; `:1412-1424` los envía.
- **Pasos:** `normalizeEditorClip`; sólo números finitos; `0 ≤ start < end ≤ duration`; volumen acotado; enums válidos; regenerar ID si falta; descartar con aviso lo irreparable.
- **Aceptación automática:** tabla con NaN, strings, trims invertidos y duración ausente se repara o rechaza de forma estable.

### PLAY-01 — Reconciliar cursor de Play all por identidad

- **Tipo:** bug confirmado · **P2** · tamaño S.
- **Evidencia:** `StoryProductionTimeline.tsx:27-38` y `SeriesReviewPanel.tsx:91-136` usan índice; regeneración/polling puede cambiar la lista debajo.
- **Pasos:** helper `reconcilePlaybackCursor(previousShotId, playable)`; conservar mismo shot/slot por ID; si desaparece, detener o avanzar explícitamente; nunca quedar `playingAll=true` sin clip.
- **Aceptación automática:** lista se reduce, reordena y reemplaza intento durante reproducción; cursor permanece coherente.
- **Validación del usuario:** regenerar el clip activo mientras Play all corre; debe continuar por slot o detenerse con mensaje claro.

### POLL-01 — Polling serializado y cancelable

- **Tipo:** bug de concurrencia confirmado · **P2** · tamaño M.
- **Evidencia:** `setInterval(async...)` sin exclusión en varios paneles Series y Story.
- **Pasos:** hook `useSerializedPoll` con `setTimeout` después de finalizar, `AbortController` y epoch; migrar **un panel por commit**.
- **Aceptación automática:** latencia superior al intervalo mantiene concurrencia máxima 1; una respuesta antigua no reemplaza la nueva; nada actualiza tras unmount.
- **Validación del usuario:** simular 2–3 s de latencia; Network no muestra polls solapados.

### TIMELINE-01 — Parar polling de timelines terminales

- **Tipo:** coste confirmado · **P2** · tamaño S.
- **Evidencia:** `StoryProductionTimeline.tsx:40-59` consulta cada 3 s indefinidamente mientras esté abierto y no limpia un error tras éxito.
- **Pasos:** detener en estados terminales; limpiar error al recibir éxito; botón Refresh manual.
- **Aceptación automática:** terminal no programa otro timer; un éxito posterior borra error.

### ACT-01 — Feedback visible en acciones de Activity

- **Tipo:** bug UX confirmado · **P2** · tamaño S.
- **Evidencia:** `ActivityFooter.tsx:239-259` sólo usa `console.error` en cancel/resume/dismiss.
- **Pasos:** error por task ID, bloque inline `aria-live`, Retry y limpieza tras éxito.
- **Aceptación automática:** API rechazada conserva tarea y muestra error; Retry exitoso lo limpia.

---

## Bloque G — Subidas, jobs y recursos

### UPLOAD-01 — Subidas en streaming, no 500 MB en RAM

- **Tipo:** riesgo de caída confirmado · **P1** · tamaño M.
- **Evidencia:** `app/launch.py:8911-8915` y `:34960-34981` hacen `await file.read()` completo; el límite real se valida después.
- **Pasos:** escribir chunks en `.partial`; contador acumulado y 413 inmediato; cleanup en error/cancel; `os.replace` atómico; límite de concurrencia de ingest/transcode.
- **Aceptación automática:** UploadFile falso que supera límite no reserva el tamaño total, devuelve 413 y no deja partial; upload válido conserva hash.
- **Validación del usuario:** subir un archivo grande permitido mientras se consulta preflight; memoria y UI permanecen estables.

### CANCEL-01 — Cancelación real de la llamada LLM

- **Tipo:** carencia confirmada · **P2** · tamaño M.
- **Evidencia:** Series/Story comprueban cancel antes/después de la llamada larga, no dentro del stream.
- **Pasos:** token por job propagado al cliente HTTP/local LLM; abortar sólo esa request; persistir último stage completo; mensaje explícito si un proveedor no permite abortar.
- **Aceptación automática:** fake stream bloqueante observa token y termina en tiempo acotado; otro job concurrente sigue vivo.

### RES-01 — FIFO real por resource lane

- **Tipo:** riesgo probable · **P2** · tamaño M.
- **Evidencia:** `app/services/resource_scheduler.py:252-276` registra waiters pero todos compiten por el semaphore; la lista no gobierna adquisición.
- **Pasos:** tickets + Condition por lane; sólo cabeza adquiere; cancelar elimina y despierta siguiente.
- **Aceptación automática:** A/B/C entran siempre en ese orden durante 100 repeticiones; cancelar B deja A/C.

---

## Bloque H — Accesibilidad, móvil y memoria del navegador

### A11Y-01 — `ModalShell` accesible

- **Tipo:** defecto confirmado · **P2** · tamaño M.
- **Evidencia:** overlays de Director y picker del editor carecen de `role=dialog`, `aria-modal`, Escape, trap y restauración de foco; algunos botones X no tienen nombre accesible.
- **Pasos:** componente mínimo con título, foco inicial, Escape, ciclo de Tab y restauración; migrar Director primero y un overlay por commit.
- **Aceptación automática:** RTL + axe: diálogo tiene nombre, Escape cierra, Tab no escapa y foco vuelve al disparador.
- **Validación del usuario:** navegar sólo con Tab/Shift+Tab/Escape y probar NVDA/VoiceOver cuando esté disponible.

### A11Y-02 — Etiquetar controles e iconos

- **Tipo:** defecto confirmado en inspección DOM · **P2** · tamaño M.
- **Evidencia:** varios inputs/ranges/selects no tienen asociación programática y botones de miniaturas/cierre dependen sólo del icono o de la imagen hija.
- **Pasos:** auditar por panel; `label htmlFor/id` o `aria-label`; estado con `aria-pressed`; miniaturas con nombre del asset/clip; un panel por commit.
- **Aceptación automática:** query por roles encuentra todos los controles por nombre; axe sin `button-name` ni `label` en el panel migrado.

### RESP-01 — Series Lab usable en 320–375 px

- **Tipo:** defecto confirmado por CSS · **P2** · tamaño M.
- **Evidencia:** `SeriesLabPanel.tsx:165-171` mantiene un rail `w-56` en el viewport mínimo.
- **Pasos:** bajo `md`, rail como selector horizontal/drawer; contenido a ancho completo; mantener rail en escritorio.
- **Aceptación automática:** Playwright 375×667 sin overflow horizontal y tabs/episodio accesibles.
- **Validación del usuario:** probar 320, 375 y 768 px.

### RESP-02 — Story Lab móvil

- **Tipo:** probable visual · **P2** · tamaño S/M.
- **Evidencia:** `StoryLabPanel.tsx:4514-4538` conserva rail `w-36` en móvil.
- **Pasos:** tabs horizontales o drawer bajo `md`; scroll visible; conservar estructura desktop.
- **Aceptación automática:** screenshots 320×568 y 375×667 sin controles cortados.

### RESP-03 — Video Editor móvil

- **Tipo:** probable visual · **P2** · tamaño M.
- **Evidencia:** `VideoEditorPanel.tsx:1488-1559` impone altura/overflow y toolbar sin wrap; el padre también oculta overflow.
- **Pasos:** toolbar con scroll/wrap; `min-h-0` móvil; timeline/inspector accesibles por panel; no cambiar layout desktop.
- **Aceptación automática:** Import, Export, trim e inspector alcanzables a 320×568 y 375×667.

### MEM-01 — Hook único para object URLs

- **Tipo:** fuga probable-alta · **P2** · tamaño M incremental.
- **Evidencia:** 41 `createObjectURL` frente a 16 `revokeObjectURL`; patrón correcto ya existe en `MultiClipEditor.tsx:6-15`.
- **Pasos:** `useObjectUrl(file, fallback)`; migrar primero Director, luego uploads/refs, un componente por commit.
- **Aceptación automática:** una revocación al sustituir y otra al desmontar; nunca crear dentro del render repetidamente.
- **Validación del usuario:** alternar muchas previews y observar que la memoria se estabiliza.

### STORAGE-01 — Wrapper seguro de `localStorage/sessionStorage`

- **Tipo:** robustez confirmada por código · **P2** · tamaño S.
- **Evidencia:** `WelcomeModal.tsx:16-22` y `PreflightBanner` acceden al storage sin capturar `SecurityError`/cuota.
- **Pasos:** helper `safeStorageGet/Set/Remove`; fallback en memoria; migrar primero bienvenida/preflight.
- **Aceptación automática:** storage que lanza no rompe el render ni el dismiss.

### I18N-01 — Fechas y etiquetas con locale coherente

- **Tipo:** mejora UX confirmada visualmente · **P3** · tamaño S.
- **Evidencia:** se observó una etiqueta española `Finalizado` junto a mes inglés `Aug` y mezcla amplia de etiquetas españolas/inglesas.
- **Pasos:** formatter central `Intl.DateTimeFormat` con locale de aplicación; empezar por timestamps de media/Activity; glosario pequeño para acciones principales.
- **Aceptación automática:** snapshot de `es-ES` y locale alternativo; zona horaria explícita cuando corresponda.

### TRAILER-01 — Defaults de trailer sin borrar edición manual

- **Tipo:** warning/estado stale confirmado · **P2** · tamaño S.
- **Evidencia:** `StoryLabPanel.tsx:1236-1248` usa tipo y duración pero el efecto depende sólo de `project.id`; ESLint lo avisa.
- **Pasos:** flag `trailerTouched`; sincronizar defaults mientras no haya edición manual; separar reset por proyecto de sync de duración.
- **Aceptación automática:** cambiar duración antes de editar actualiza; después de edición manual conserva el valor.

---

## Bloque I — Styles, persistencia y licencias

### STYLE-01 — Preflight de disco, cancelación y storage durable

- **Tipo:** carencia confirmada · **P2** · tamaño M.
- **Evidencia:** import esperado de ~1,43 GB, descarga/previews sin cancel y almacenamiento bajo el árbol fuente.
- **Pasos:** directorio configurable fuera del código; `disk_usage` con margen; cancel event comprobado en descarga/index/previews; resume parcial; status visible.
- **Aceptación automática:** disco insuficiente rechaza antes del thread; cancelar no deja estado corrupto y permite reanudar.
- **Validación del usuario:** iniciar, cancelar, reiniciar aplicación y reanudar la descarga.

### STYLE-02 — No convertir manifest corrupto en biblioteca vacía

- **Tipo:** riesgo confirmado · **P2** · tamaño S/M.
- **Evidencia:** `app/services/style_library.py:99-118` captura error y devuelve `styles=[]`, `deletedIds=[]`; un import posterior puede reintroducir borrados.
- **Pasos:** backups generacionales; quarantine; estado `degraded`; bloquear escritura automática hasta recuperar backup; preservar tombstones.
- **Aceptación automática:** manifest corrupto no se sobrescribe; status informa degraded; backup restaura deletedIds.

---

## Bloque J — Tests y CI

### TEST-01 — Pytest ejecutable desde la raíz

- **Tipo:** puerta de calidad rota · **P1** · tamaño S.
- **Evidencia:** `pytest.ini` sólo define `testpaths`; sin `PYTHONPATH=app` hay imports `services` que fallan.
- **Pasos:** añadir `pythonpath = app`; documentar un comando canónico; verificar colección desde raíz.
- **Aceptación automática:** `app/env/bin/python -m pytest --collect-only -q` desde raíz colecciona al menos 1.222 tests sin error de import.

### TEST-02 — Reparar harness de preplan H3

- **Tipo:** fallo de test confirmado · **P1** · tamaño S.
- **Evidencia:** los 3 fallos en `tests/test_h3_preplan_job_contract.py` son `NameError: _is_minimax_h3_model`; producción sí define el helper en `app/launch.py:708`, pero el namespace extraído por el test no lo inyecta.
- **Pasos:** incluir el helper real o un fake explícito en el harness; no cambiar producción para satisfacer un namespace artificial.
- **Aceptación automática:** ese archivo queda verde y sigue fallando si se elimina el preplan obligatorio real.

### CI-01 — Ejecutar toda la suite pytest en CI

- **Tipo:** cobertura omitida confirmada · **P1** · tamaño M.
- **Evidencia:** `.github/workflows/ci.yml:38` usa `unittest discover`; existen cientos de tests pytest top-level que no ejecuta.
- **Dependencias:** `TEST-01`, `TEST-02`.
- **Pasos:** instalar deps ligeras necesarias; sustituir unittest + runner especial por `python -m pytest`; si hay tests GPU/model, marcarlos y separarlos, no seleccionar archivos manualmente; job `--collect-only` obligatorio.
- **Aceptación automática:** un test pytest top-level fallido hace fallar CI; la suite normal queda verde.

### CI-02 — Puerta frontend estándar

- **Tipo:** carencia confirmada · **P1** · tamaño M.
- **Evidencia:** CI sólo hace build; `ui/package.json` no tiene `test`; los tests actuales no están integrados y se ejecutaron localmente con Node distinto al de CI.
- **Pasos:** elegir Vitest o `tsx --test`; fijar compatibilidad Node 20; scripts `test` y `check`; incluir lint con cero warnings, tests y build.
- **Aceptación automática:** `npm ci`, `npm test`, `npm run lint -- --max-warnings=0`, `npm run build` correctos en Node 20.

### TEST-UI-01 — Primer test DOM de los flujos críticos

- **Tipo:** mejora · **P2** · tamaño M.
- **Dependencia:** `CI-02`.
- **Pasos:** añadir RTL/jsdom; empezar por recovery Director, Approve all, Play all y propuesta de episodio; usar roles/labels, no buscar strings en source.
- **Aceptación automática:** el test interactúa con el componente y detecta una regresión real de estado.

### TEST-UI-02 — Migrar tests que parsean source

- **Tipo:** deuda confirmada · **P2/P3** · tamaño S repetible.
- **Evidencia:** decenas de tests Python leen/splitean TSX; son frágiles ante refactors y pueden pasar con runtime roto.
- **Pasos:** clasificar; conservar sólo contratos estáticos legítimos; migrar **un flujo por commit** a test conductual.
- **Aceptación automática:** cambiar una etiqueta inocua no rompe el test; romper el comportamiento sí.

---

## Bloque K — API, arquitectura y release

### API-01 — Contratos Pydantic/OpenAPI empezando por Series Assembly

- **Tipo:** mejora estructural · **P2** · tamaño M.
- **Evidencia:** muchos handlers aceptan `dict`/`Request` sin schema y casi no hay `response_model`; los tipos TS pueden divergir.
- **Pasos:** modelos request/response sólo para Assembly; `response_model`; fixture OpenAPI; generar tipos TS de ese dominio; detector de drift.
- **Aceptación automática:** payload inválido => 422 estructurado; fixture backend satisface tipo generado.
- **No hacer:** no migrar las 247 rutas en una sola tarea.

### API-02 — Eliminar tipo duplicado de Director V2

- **Tipo:** drift confirmado · **P2** · tamaño S.
- **Evidencia:** `ui/src/api/client.ts:1767-1771` usa `skill_type: string`; `ui/src/types/index.ts:1399-1403` usa `DirectorSkill`.
- **Pasos:** una sola fuente de tipo; import type desde client o módulo de contratos; test TypeScript de los consumidores.

### ARCH-01 — `create_app()` importable sin cargar GPU

- **Tipo:** mejora estructural · **P2** · tamaño L, dividir.
- **Evidencia:** importar `app/launch.py` modifica env, cwd y argv y carga Torch/WanGP en `:31-62`, `:107-110`.
- **Primera microtarea únicamente:** escribir characterization test de cwd/argv/import y extraer construcción FastAPI más pequeña sin cambiar rutas. No mover endpoints todavía.
- **Aceptación automática:** importar la factory no carga Torch/WanGP ni cambia cwd; start Pinokio sigue funcionando.

### ARCH-02 — Extraer routers verticalmente

- **Tipo:** mejora · **P2/P3** · programa de tareas S/M.
- **Regla:** un dominio por commit, empezando por canonical tasks o audio. Mantener URL, status, schema y side effects; inyectar dependencias explícitas como ya hace Series Assembly.
- **Aceptación automática:** snapshot de rutas/OpenAPI antes/después y tests de contrato del dominio.
- **No hacer:** no “limpiar `launch.py`” de forma global.

### ARCH-03 — Dividir Zustand por slices con fachada compatible

- **Tipo:** mejora · **P2/P3** · programa incremental.
- **Primera microtarea:** extraer sólo `deriveIsGenerating` y reducers puros de jobs; después slice Director, sin cambiar la API pública del store.
- **Aceptación automática:** characterization tests del estado antes de mover cada bloque.

### OBS-01 — Logging estructurado por operación

- **Tipo:** mejora confirmada · **P2** · tamaño M incremental.
- **Evidencia:** muchos `print`, excepciones amplias y polling ruidoso; falta correlación uniforme workspace/task/pipeline.
- **Pasos:** primero corregir frecuencia real; después filtrar sólo GET 2xx de progreso; adapter con IDs; migrar planner y TaskRegistry; sustituir `except: pass` críticos por log contextual.
- **Aceptación automática:** GET 200 de progreso puede ocultarse, GET 500 y POST no; error contiene activity/pipeline/workspace.

### PERF-01 — Presupuesto del bundle y lazy overlays

- **Tipo:** mejora medida · **P2** · tamaño S repetible.
- **Evidencia:** chunk principal ~1,13 MB; `App.tsx` importa overlays globales de forma eager. Los workspaces grandes ya usan lazy correctamente.
- **Pasos:** registrar gzip en CI; presupuesto inicial; lazy-load de DirectorDashboard primero; un overlay por commit.
- **Aceptación automática:** build budget y test de apertura lazy; medir antes/después.

### DEPS-01 — Limpiar y fijar dependencias directas

- **Tipo:** reproducibilidad · **P2** · tamaño S repetible.
- **Evidencia:** `app/requirements.txt` declara pins estrictos pero tiene dependencias sin versión y duplica el nombre normalizado `vector_quantize_pytorch`/`vector-quantize-pytorch`.
- **Pasos:** eliminar duplicado; fijar una dependencia directa por commit con smoke test; no actualizar todo el stack de IA junto.

### DEPS-02 — Igualar install y update

- **Tipo:** reproducibilidad · **P2** · tamaño S.
- **Evidencia:** install usa `--index-strategy unsafe-best-match`, update no; launcher usa `npm install`, CI `npm ci`.
- **Pasos:** mismo resolvedor Python; `npm ci` con lock válido; smoke de instalación seguida de update sin cambios de freeze.

### DEPS-03 — Fijar revisiones de vendors

- **Tipo:** reproducibilidad · **P2** · tamaño S por vendor.
- **Pasos:** Hunyuan3D-2, Hunyuan3D-2.1, SAM y UniRig en tickets/commits separados; commit/tag explícito; marker de versión; update sólo a revisión declarada.

### DOC-01 — Documentación sin drift

- **Tipo:** mejora · **P3** · tamaño S.
- **Evidencia:** `ui/README.md` sigue siendo la plantilla Vite y un issue template apunta al upstream antiguo.
- **Pasos:** comandos reales de UI; arquitectura mínima; corregir enlaces; comprobarlos con script.

---

## Extras — no certificables o no convenientes como tarea directa

Estos puntos no son imposibles en sentido absoluto, pero no pueden darse por “resueltos” sólo con una microtarea en esta máquina:

1. **Calidad real de audio/idioma de MiniMax.** No se puede garantizar de forma determinista que nunca balbucee, cante o cambie de idioma. Se puede crear un conjunto de evaluación, ASR, detector de idioma y revisión humana, pero el proveedor sigue siendo estocástico.
2. **Duración exacta arbitraria.** Si un modelo sólo admite duraciones discretas, no puede pedirse exactamente 6,5 s. La solución verificable es escoger la duración soportada inmediatamente superior y aplicar trim no destructivo en el montaje.
3. **E2E GPU en GitHub Actions estándar.** Requiere runner propio con NVIDIA/modelos. En CI normal deben usarse backend simulado y fixtures; dejar smoke GPU nocturno como extra.
4. **Windows, macOS, AMD y todos los codecs.** Esta revisión se ejecutó en Linux/NVIDIA. Hace falta una matriz real de máquinas/FFmpeg.
5. **Accesibilidad formal multi-lector/multi-browser.** Axe/RTL/Playwright reducen errores, pero la certificación requiere NVDA, VoiceOver y pruebas humanas.
6. **Licencia del dataset de estilos.** La fuente actual no publica una licencia clara. No inventar términos ni redistribuir automáticamente; mantener atribución/source, aviso y aceptación del usuario hasta aclaración del autor.
7. **Reanudar FFmpeg exactamente a mitad de una unión.** No compensa la complejidad: cancelar y reiniciar la unión conservando clips fuente es la opción segura.
8. **Reescritura total de `launch.py` o `useStore.ts`.** No debe asignarse a Luna como una tarea. Sólo extracciones verticales con fachada compatible y characterization tests.
9. **Pentest formal y auditoría completa de dependencias externas.** Requieren herramientas, red, tiempo y alcance específico separados.

## Plantilla para asignar una tarea a GPT-Luna

Copiar este texto y sustituir el ID:

> Implementa únicamente la tarea `[ID]` de `docs/AUDITORIA_CODIGO_UI_2026-08-13.md`. Lee completa esa tarea y sus dependencias. Antes de editar, reproduce el fallo con un test pequeño. Toca sólo los archivos indicados o explica por qué necesitas uno adicional. No arregles problemas vecinos. Ejecuta la aceptación automática exacta, `git diff --check` y las pruebas del módulo afectado. Haz un único commit con el ID al inicio del mensaje. Devuélveme: archivos cambiados, prueba que fallaba antes/pasa después, comando ejecutado, resultado y pasos exactos para mi validación manual. Si no puedes cumplir algún criterio, no improvises: marca la tarea como bloqueada y explica la evidencia.

## Checklist de validación para cada commit

- [ ] El commit contiene un solo ID.
- [ ] Hay prueba de regresión o una razón concreta por la que no puede existir aún.
- [ ] La prueba falla antes del cambio y pasa después.
- [ ] No se han añadido casts para ocultar un contrato roto (`as unknown as`, `any`) sin justificación.
- [ ] No se han cambiado archivos ajenos ni artefactos generados.
- [ ] `git diff --check` no informa de whitespace roto.
- [ ] Backend: tests focalizados y, cuando proceda, pytest completo.
- [ ] UI: lint, test focalizado y build.
- [ ] Se han ejecutado los pasos de validación manual del ticket.
- [ ] Si afecta rutas/archivos, hay pruebas de traversal, ruta absoluta y symlink.
- [ ] Si afecta jobs, hay casos queued/running/terminal/cancel/restart.
- [ ] Si afecta workspaces, hay un test explícito que impide mezclar A y B.

## Criterio para dar la auditoría por cerrada

La auditoría queda documentada con este backlog, pero el producto no debe considerarse “sin fallos” al completarlo. Se puede cerrar el bloque actual cuando:

1. Todos los P0/P1 estén corregidos o tengan una decisión explícita del usuario.
2. Pytest y la puerta UI estén integrados y verdes.
3. La DB de Activity deje de crecer estando inactiva y exista un dry-run de mantenimiento.
4. El plan real de 41 clips complete o se reanude sin perder lotes.
5. Las carreras Story/Series/workspace tengan tests diferidos.
6. La validación manual de Series Review confirme orden, sustitución de slot, duración de diálogo y unión final.
