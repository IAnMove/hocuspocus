# Grok: bloques 0, D, C y B de producción de videoclips (2026-09-30)

Documento de trabajo para Grok. Sustituye el reparto de `GROK_PRODUCTION_NEXT_2026-09-29.md` para lo que sigue sin hacer
(los números de punto son los de ese documento) y añade un bloque nuevo, **D**, que es la prioridad del usuario.
El bloque A (tratamiento y modo trailer, puntos 21 y 23) lo hace Claude; no lo toques. Claude revisa cada PR tuyo.
El tablero con dueños, ramas y archivos exclusivos es `PRODUCTION_WORK_BOARD.md`; manda sobre este documento si difieren.

## 0. Cómo trabajar (obligatorio)

- Worktree propio desde `origin/development` actualizado. No trabajes en el checkout compartido
  `/mnt/extras/pinokio/api/hocuspocus-development` (está muy atrasado y tiene archivos sin seguimiento).
- Instancia propia (42021) para pruebas con servidor. Nunca 42003 (usuario) ni 42017 (Claude). `nvidia-smi` antes de
  cualquier prueba con GPU; si otro proceso usa más de 2 GB, espera. Datos pesados en `/home/ina/grok-data` o
  `/mnt/outputs`; `/mnt/extras` está justo de espacio.
- Abre el PR como borrador el primer día con el nombre de rama del tablero: eso es la reclamación. Actualiza la fila
  de tu bloque en `PRODUCTION_WORK_BOARD.md` dentro del mismo PR.
- Un PR por bloque (o por punto si el bloque es grande). Nada de PR gigante con los 31 puntos.
- Cada PR: tests dirigidos registrados en `scripts/ci_test_groups.json` (hay un test que falla si falta alguno),
  `cd ui && npm run check` si tocas UI, `BASE_REF=origin/development scripts/check_code_health_pr_base.sh`
  (el ratchet no puede empeorar), `python3 scripts/check_documentation_links.py`, y una sección en
  `docs/agents/VIDEO_PRODUCTION_RUNBOOK.md` (añade al final de la sección que toques, sin reescribir lo ajeno).
- Tokens y tiempos: solo cifras medidas. Los tokens del LLM los mide el cliente (Claude Code guarda `usage` por mensaje);
  `usage.response_bytes` son bytes que leyó el ejecutor interno, NO tokens, y no se convierten. No escribas "≈ bytes/4".
- No generes vídeo, música ni imágenes salvo la prueba de aceptación real que pide cada bloque, y solo en tu instancia.
- Material de prueba real: workspace `gremlins-devday-v2-20260929`, producción `voices-v2` (17 planos H3 + 4 de relleno,
  manifiesto `voices-v2.shots.json`, documentos de escena, montaje, `takes` desde #614), y en
  `gremlins-devday-20260929` la de Sol. Están en `/mnt/outputs/hocuspocus-worktrees/claude-pop/app/outputs/`.
  Cópialas a tu workspace antes de tocar nada; no edites las originales.
- Orden: bloque 0 primero (es corto y desbloquea el resto). D, C-14, C-16 y B (sin enganches al runner) pueden empezar ya en
  paralelo porque no tocan `music_production.py`. Los puntos que sí necesitan un gancho en el runner esperan al bloque 0.
- Zona restringida: `app/services/music_production.py` (1154 líneas, hotspot de complejidad). Hasta que aterrice el
  bloque 0 solo se permiten ganchos de ≤ 5 líneas que llamen a un módulo nuevo.

---

## BLOQUE D. Revisar plano a plano y pedir cambios a un LLM, al asistente de la app o a mano (PRIORIDAD 1)

### Lo que pide el usuario (sus palabras)
"Que el LLM construya todo, pero que podamos ver todas las escenas una a una y luego pedirle al LLM, o al wizard de la
propia app, lo que queremos cambiar, o cambiarlo a mano solo en esa escena. Creo que eso sería el mejor control de
calidad." La tesis: el control de calidad más fiable no es un veredicto automático, es una persona (o un LLM con el
plano delante) que revisa cada plano y arregla solo ese plano sin rehacer el vídeo.

### Lo que ya existe (no lo reescribas; reutilízalo)
- Panel "Music productions" y parrilla de planos: `ui/src/features/music-productions/*` (#624). Lee
  `<id>.production.json` y `<id>.shots.json`.
- Comandos MCP y REST (`app/routers/music_productions.py`, `app/services/production_commands.py`):
  `production.shot.use_take` (cambia la toma, re-exporta solo esa escena y sustituye el clip del montaje con
  `expected_revision`), `production.shot.update` (guarda `lyric_style`/`title`/`camera` en
  `spec.shots[i].overrides` y re-exporta solo esa escena), `production.song.use`, `production.cancel`, y
  `production.run` con `retake: [clave]` (clip nuevo con otra semilla, misma imagen inicial y mismos prompts).
  Lógica en `production_shot_edit.py`, `production_song_switch.py`, `production_control.py`.
- Paquete editable (#613): `Production.package()` guarda un `*.scene.json` por plano, `origin` en los clips del montaje y
  el manifiesto `shots.json` (tiempos, letra, prompts, semilla, imagen inicial, tomas con `r`, escena, vídeo).
  Botón "Abrir escena" del tablero de planos del Video Editor (`ShotBoard.tsx`, `sceneOutput()`).
- Re-exportación selectiva: `scene_fingerprint(shot, style, stills, score, a, b)` hace que solo se re-exporte lo que cambió.

### Lo que falta (los huecos reales, con el motivo)
1. **Rehacer un plano con prompts nuevos.** `retake` solo cambia la semilla del clip: la imagen inicial y los prompts son los
   mismos. Casi todos los arreglos de calidad son de imagen ("el personaje salió duplicado", "el fondo no es el que quería",
   "esta acción no se entiende"). Hace falta rehacer desde el fotograma (Qwen) con `frame`/`action` modificados, luego
   el clip, luego la escena, solo para ese plano.
2. **Petición en lenguaje natural por plano.** Hoy un humano o un agente tiene que traducir "que no salgan gatos" a un
   `overrides` o a un nuevo prompt. Debe poder escribirse la instrucción y obtener un plan de cambios estructurado y
   validado, que se muestra (con diff) y solo se aplica al confirmar.
3. **Estado de revisión por plano.** No hay "visto / aprobado / pide cambios". Sin eso no hay control de calidad medible ni
   sitio donde el veredicto artístico (punto 27) pueda apoyarse.
4. **Edición manual que sobrevive.** Si alguien retoca la escena a mano (Video 2D) y exporta, un `production.run` de
   reanudación vuelve a construir esa escena desde el spec y pisa el retoque. Hace falta un bloqueo por plano.
5. **Historial y deshacer por plano.** Las tomas se conservan desde #614, pero no hay registro de qué prompt/toma/override
   tenía el plano antes de cada cambio ni forma de volver atrás en un paso.

### Diseño

**Estado.** Un archivo nuevo por producción, `<production_id>.review.json`, escrito de forma atómica
(tmp + replace, como `Production.save`) por un módulo nuevo `app/services/production_shot_review.py`. No lo mezcles con
`production.json` (se reescribe varias veces por minuto y lo lee `wait_for_status`). Estructura:

```json
{"version": 1, "production_id": "voices-v2", "shots": {
  "chorus_a": {"status": "changes_requested", "locked": false, "notes": [{"at": 1759240000, "by": "human", "text": "..."}],
    "history": [{"id": "h3", "at": 1759240100, "by": "llm", "kind": "redo",
                 "before": {"frame": "f.png", "clip": "c.mp4", "frame_prompt": "...", "action": "...", "overrides": {}},
                 "after":  {"frame": "f2.png", "clip": "c2.mp4", "frame_prompt": "...", "action": "...", "overrides": {}}}]}}}
```
`status` ∈ `pending | approved | changes_requested`. `locked: true` = edición manual o decisión humana: ni reanudar, ni
`retake` sin nombrar el plano explícitamente, ni re-exportación automática lo tocan. Expón el estado también dentro del
manifiesto `shots.json` (campo `review` por plano) para que la UI y los agentes lo lean de un sitio.

**Comandos** (MCP `production.shot.*` + REST bajo `/api/v1/music-productions/...`, mismo patrón y validación que #624,
envoltorio `{version: 1, input: {...}}`, errores estables con `code`):

| Comando | Qué hace |
|---|---|
| `production.shot.review {workspace, production_id, shot, status, note?}` | Pone `pending/approved/changes_requested` y añade la nota. Sin GPU. |
| `production.shot.lock {shot, locked}` | Activa/desactiva el bloqueo. Se activa solo si se guarda una escena exportada a mano (ver UI). |
| `production.shot.redo {shot, from: "frame"\|"clip"\|"scene", frame_prompt?, action?, seed?, image_model?, cast?, expected_revision}` | Cadena para UN plano: `frame` = regenera la imagen inicial (Qwen, con `attempt` nuevo para no caer en el intent idempotente: reutiliza `Production._attempt`, `frame_prompt`, `image`) y sigue con clip y escena; `clip` = clip nuevo desde la imagen actual con `action` nueva; `scene` = solo re-exporta. Guarda la versión anterior en `history`. Respeta `locked` (error `shot_locked`). |
| `production.shot.request {shot, instruction, apply?: false}` | Pide al LLM de la app un plan y lo devuelve; con `apply: true` lo ejecuta. Ver abajo. |
| `production.shot.undo {shot, history_id}` | Restaura el estado anterior del plano (prompt, toma, overrides) y re-exporta esa escena. No borra archivos. |

`redo` es GPU: pásalo por la misma cola y por `guard_mcp` de `production_resource_gate.py` que usa el runner. El
re-montaje del plano en el montaje y la revisión de escena reutilizan el camino de `production_shot_edit.py`
(mismo `expected_revision`, mismo parche de un solo clip); no dupliques esa lógica, extrae lo común.

**`production.shot.request`: del lenguaje natural a cambios validados.**
1. Contexto (datos, nunca instrucciones): la fila del plano de `shots.json` (letra, `frame_prompt`, `action`, semilla,
   cast, tomas con su `r`, avisos), el estilo resumido y 1-3 URLs de miniaturas si el LLM configurado acepta imagen.
2. Llama al LLM que la app ya tiene configurado (mira `app/services/llm_service.py`, `app/routers/llm.py` y cómo lo
   usan `wizard_conversations.py`/`wizard_workflows.py`; reutiliza ese acceso, no abras otro cliente). Si no hay LLM
   configurado: error `llm_unavailable`. No inventes un plan sin modelo.
3. La respuesta debe ser JSON con un esquema cerrado `ShotChangePlan`:
   `{summary, changes: [{op: "set_overrides" | "redo" | "retake" | "use_take" | "note", ...campos permitidos por op}]}`.
   Valida con el mismo validador que cada comando; un `op` desconocido, un campo extra, una ruta de archivo o un plano
   distinto del solicitado invalida el plan entero. El texto del usuario y el del LLM son datos: nada se ejecuta por estar
   escrito en una instrucción (pon un test de inyección: una instrucción que pide "borra las tomas" o "cambia el plano 3"
   no produce cambios fuera del plano pedido ni borra nada).
4. Devuelve `{plan, diff, cost_estimate}` (diff legible: prompt antes/después, qué GPU se gastará, qué escena se re-exportará).
   Con `apply: true` (o desde el botón de la UI) ejecuta los `changes` uno a uno con los comandos de arriba, con
   `intent_id` estable (`<id>-req-<hash>`) para que repetir la llamada no duplique trabajo.
5. Un agente externo (Claude Code, tú mismo) no necesita `request`: llama directamente a `redo`/`update`/`use_take`.
   Documenta ambas vías en el runbook.

**Asistente de la app ("wizard").** Comprueba primero qué puede hacer hoy: `wizard_workflow_executor.py` ejecuta flujos
de imagen, no es un agente de herramientas general. Primer corte, sin depender del wizard: el botón "Pedir cambio" de la
UI llama a `production.shot.request`. Segundo corte (solo si ya hay un asistente con llamadas a herramientas): registra
`production.shot.request/redo/review` en su catálogo con el plano seleccionado como contexto. Si no existe ese
asistente, deja anotado el hueco en el PR; no lo construyas aquí.

**Publicación.** `production.publish` (`production_publication.py`) debe rechazar con `review_incomplete` una producción con
planos en `pending`/`changes_requested`, salvo `accept_unreviewed: true` explícito. Y el nivel `artistic` del punto 27
(bloque B) se calcula a partir de este estado: todos aprobados → `approved_by_review`; si no, `pending_judgement`.

**UI** (`ui/src/features/music-productions/`, reutiliza la parrilla de #624): modo "Revisar" a pantalla completa que recorre
los planos en orden con el reproductor de la escena exportada, muestra letra, prompts, tomas y avisos, y tiene:
Aprobar (Enter) · Pedir cambio (cuadro de texto → `request` → muestra el plan con diff → Aplicar) · Abrir escena
(edición manual; al volver y guardar una escena exportada, ofrece Reemplazar clip + bloquear el plano) · Otra toma ·
Deshacer. Flechas/J/K para moverse; contador "12/21 aprobados"; filtro "solo pendientes". Responsive y accesible (mira
los tests de `musicProductions.test.tsx`). Textos en `en` y `es` (`npm run i18n:check`).

### Archivos (exclusivos de este bloque)
Nuevos: `app/services/production_shot_review.py`, `app/services/production_shot_redo.py`,
`app/services/production_shot_request.py`, `ui/src/features/music-productions/ReviewMode.tsx` (+ hooks/tests).
Editar: `production_commands.py` y `routers/music_productions.py` (registrar comandos/rutas), `production_publication.py`
(el rechazo), `production_shot_edit.py` (extraer lo común con `redo`), runbook. Ganchos en `music_production.py` (≤ 5
líneas, tras el bloque 0): que `frames()`, `clips()` y `scenes()` omitan los planos `locked`.

### Aceptación
- Tests con MCP y LLM simulados por comando: `redo` desde `frame` cambia solo ese plano (el resto de escenas conserva su
  fingerprint y no se re-exporta; el montaje termina con ese clip nuevo y el `origin` intacto); `shot_locked`; `undo`
  restaura exactamente `before`; `review` persiste y aparece en `shots.json`; `publish` rechaza lo incompleto.
- Test de contrato de `ShotChangePlan`: acepta un plan válido; rechaza `op` desconocido, campo extra, plano ajeno, ruta;
  test de inyección (ver arriba); `llm_unavailable` sin modelo.
- Test de UI del modo Revisar con API simulada: aprobar, pedir cambio con diff, deshacer, teclado, filtro.
- Prueba real en tu instancia con `voices-v2` copiada: pide por instrucción "que solo aparezca Hum, sin otros
  animales" sobre `chorus_a`; aplica; comprueba que solo cambian el fotograma, el clip y la escena de ese plano y su clip
  en el montaje; deshaz. Mide: segundos de extremo a extremo (LLM → escena nueva), segundos de GPU, y que
  ningún archivo fuera de ese plano, el montaje (nueva revisión), el manifiesto y `review.json` se modifica.
- Entrega: capturas del modo Revisar (escritorio y móvil) en `/home/ina/grok-data`, no en el repo.

### No hacer
No reconstruyas el Video Editor ni Video 2D; no cambies el formato de `production.json` ni de `shots.json` salvo añadir
campos; no borres tomas; no apliques cambios del LLM sin confirmación salvo `apply: true` explícito; no pongas claves ni
URLs de modelos en el repo.

---

## BLOQUE 0. Refactor de `music_production.py` (puntos 17, 18, 19, 20). Aterriza primero.

### Por qué
`app/services/music_production.py` tiene 1154 líneas y es el hotspot de complejidad del repo (el ratchet lo marca en cada
PR: 24 → 25). Cada bloque de abajo necesita un gancho ahí; sin este refactor se pisan entre ellos.

### Mapa de extracción (nombres y líneas de origin/development 40df83ec)
| Destino (nuevo módulo) | Qué se mueve |
|---|---|
| `production_scene_ops.py` | `scene_ops`, `_title_ops`, `_lyric_ops`, `_footer_ops`, `theme_colours`, `theme_lyric_style`, `title_span`, `lyric_span`, `title_cue_count`, `scene_fingerprint`, `DYMO_READABLE` |
| `production_song.py` | `song()`, `analyze()`, `score()`, `pick_song` |
| `production_images.py` | `image()`, `cast()`, `_attempt()`, `frame_prompt()`, `frames()`, `preview()`, `FRAME_ATTEMPTS`, `FRAME_RESOLUTIONS` |
| `production_clips.py` | `clip_job()`, `clips()`, `judge_take()` |
| `production_state.py` | `save()`, `log()`, `note_stop()`, el debounce de guardado (punto 18) |
| se queda en `music_production.py` | `ProductionError`, `SPEC_SCHEMA`, la cadena `validate_spec`, el esqueleto de `Production` (`__init__`, `wait`, `run`, `scenes`, `package`/`repackage`, `montage`, `animatic`), `status_summary`, catálogo y manejadores MCP |

Patrón: módulos con funciones que reciben la producción (`def clips(production, spec, windows, retake, pause)`), y métodos
delegadores de una línea en `Production` (`def clips(self, *a, **k): return production_clips.clips(self, *a, **k)`) para que
los tests que llaman `production.clips(...)` o reemplazan `production.wait`/`clip_job` con un stub sigan funcionando sin editar.
Todos los nombres públicos actuales deben seguir importables desde `services.music_production`.

### Punto 18 (guardado)
`Production.save()` reescribe el JSON entero (spec, log, takes, usage) varias veces por minuto. Separa lo volátil
(`log`, `usage`) de lo estable (`spec`) o escribe con debounce (p. ej. como mucho cada 2 s salvo en cambios de estado),
manteniendo el reemplazo atómico (`tmp` + `replace`): `wait_for_status` lee el archivo mientras se escribe. Test: 500 llamadas
a `log()` producen ≤ N escrituras y el archivo siempre es JSON válido.

### Puntos 19 y 20 (limpieza)
19: `production_review_checks.py` usa `appearance_changed` y `production_review.py` (modelo) `face_consistent` con
significado opuesto; deja un solo vocabulario documentado en el runbook y, si `production.review` sigue sin backend de
visión, decide y anota si se retira. 20: `tests/test_production_style_presets.py` ya prohíbe nombres propios en
`app/shared/style_presets.json`; añade una guía corta en el runbook de cómo crear un preset nuevo desde una producción
que salió bien.

### Aceptación
- Los tests actuales pasan **sin tocarlos** (solo se permiten imports nuevos en tests nuevos).
- `BASE_REF=origin/development scripts/check_code_health_pr_base.sh`: `music_production.py` baja de complejidad y de líneas
  (objetivo < 700 líneas), ningún módulo nuevo con función ≥ 15 de complejidad.
- Ningún cambio de comportamiento: compara `production.status` y `shots.json` de una corrida simulada antes/después.
- PR solo de movimiento (revisable con `git diff --color-moved`). Nada de mejoras mezcladas.

---

## BLOQUE C. Operativa (puntos 12, 13, 14, 15, 16, 29)

Archivos: `production_wait.py`, `production_scene_retry.py`, `production_usage.py`, `resource_scheduler.py` (solo el
parámetro de capacidad), `scene2d_export.py` (solo la capacidad del carril), nuevos `production_progress.py`,
`production_gpu.py`, `production_estimate.py`. 14 y 16 pueden empezar ya; 12, 13, 15 y 29 esperan al bloque 0 por su gancho.

### 12. Exportar escenas en paralelo
Hoy las 21 escenas de `voices-v2` se exportaron una tras otra (~1,2 min cada una, ~30 min). El runner ya encola todas
(`Production.scenes` envía `scenes.video2d.export` para cada plano y luego `finish_scene_exports` espera); el cuello está en
el carril: `scene2d_export.resource_lane()` devuelve `resource_scheduler.cpu_lane("scene2d-render")` y `ResourceLane`
tiene `capacity=1` fijo (dataclass congelada; `cpu_lane` no acepta capacidad).
- Añade `capacity` a `cpu_lane(name, capacity=1)` y en `scene2d_export` léela de `HOCUS_SCENE_EXPORT_CONCURRENCY`
  (por defecto 2, límite 1-4; valor inválido → 1).
- Antes de subir el valor comprueba que el pintor es seguro en paralelo: puertos/orígenes (`video2d_preview._serve_and_paint`,
  `_paint_on_lane`), directorios temporales, memoria de Chromium. Si hay colisión, arréglala o deja el valor en 1 y explícalo.
- Test: dos exportaciones simultáneas del mismo documento terminan bien y distintas; con el valor 1 el comportamiento no cambia.
- Medida: tiempo de las 21 escenas de `voices-v2` (documentos guardados en `*.scene.json`) con 1 y con 2-3, CPU y RAM pico.

### 13. Progreso y ETA en `production.status`
Nuevo `production_progress.py`: `progress_summary(state) -> {stage, clips: {landed, total, eta_s}, scenes: {done, total, eta_s}}`,
sin ganchos en el runner: `total` de clips = planos H3 del spec (`state["spec"]`), `landed` = `len(state["clips"])`; escenas:
`len(state["segments"])` y las de `state["scenes"]` con `file`. ETA con la mediana de `clip_seconds`/tiempos de escena de esta
producción (o de la historia del punto 16 si aún no hay datos). Una línea en `status_summary` para incluirlo. `stage` sale del
punto 14. Test con estados de ejemplo, incluido el caso sin datos (`eta_s: null`, nunca un número inventado).

### 14. Sondeo largo (`wait_s`/`until`)
Un agente que espera 2 h sondeando cada 5 min hace ~24 turnos y cada uno relee su contexto entero: en una sesión real de
333 turnos se midieron 126,6 M de tokens de lectura de caché (~33 $ a tarifa de Sonnet 5.5), con ~70 turnos solo de espera.
- `production_wait.py`: `MAX_WAIT_S = 300` → 1200. Nuevo parámetro `until`: `"change"` (hoy: vuelve cuando cambia `status`),
  `"stage"` (también cuando cambia la etapa) o `"done"` (hasta `completed/failed/cancelled`).
- La etapa actual debe estar en el estado: hoy `StageWatch` (`production_timing.py`, archivo del bloque B) solo la tiene en
  memoria. Añade **una línea** en `StageWatch.start`: `production.state["stage"] = name` (permitido cruzar de bloque;
  anótalo en los solapes del tablero).
- Cuidado con los límites de los clientes: Claude Code/otros MCP tienen sus propios tiempos de espera por llamada;
  documenta el valor seguro y, si hace falta, devuelve un latido (`status` sin cambios + `waited_s`) antes del límite.
- Test de `wait_for_status` con reloj y `sleep` falsos para `change`, `stage`, `done`; valor fuera de rango → 422 estable.

### 15. Memoria de GPU entre Qwen y H3: verifica antes de construir
La gestión de memoria de la cola ya existe (`services/generation_memory.py`, #581): `prepare_queued_model` descarga la
familia inactiva cuando va a cargarse un modelo de vídeo grande y la RAM disponible está por debajo de
`HOCUSPOCUS_QUEUE_RAM_MIN_BYTES` (por defecto 24 GiB), y `note_inference_step`/`record_pace` miden s/paso y marcan
`degraded` si supera 1,6× la línea base. Se llama desde `_launch_runtime.py` (`prepare_queued_params`, `note_inference_step`).
1. Mide primero, sin cambiar código: 17 frames de Qwen seguidos de la primera ronda de H3 en tu instancia; anota
   `performance.s_per_step` y `degraded` de cada clip y la RAM disponible antes y después de los frames.
2. Si no hay degradación: no construyas nada; documenta la medida y el umbral en el runbook.
3. Si la hay: (a) ¿la descarga no se dispara porque hay RAM "suficiente" pero el swap/VRAM está lleno? Ajusta el criterio en
   `generation_memory` (con test) en vez de añadir otro mecanismo; (b) expón una función pública
   `release_inactive_models()` (hoy es privada, `_release_inactive`) y nuevo `production_gpu.py` la llama tras la etapa
   `frames` cuando la RAM está por debajo del umbral, registrando la decisión en el log; (c) si tras eso sigue `degraded`
   en > 2 clips, `production.status` añade `advice: "restart_recommended"`.
Aceptación: tabla s/paso con y sin la descarga, con la RAM medida.

### 16. Estimación con datos propios
`dry_run` usa constantes (`_MINUTES_PER_SEED = 2`, `_MINUTES_PER_H3 = 5`). Nuevo `production_estimate.py`: al completar una
producción añade a `<workspace>/.production-timings.json` las medianas reales (segundos por clip según nº de fotogramas,
por escena, por imagen de Qwen/Flux según resolución y pasos, por semilla de canción). `estimate(spec)` = medianas × conteos,
con `estimate_source: "history(n)"` o `"defaults"` si no hay datos. Gancho de ≤ 5 líneas en `production_dry_run.py`. Test
con historias de ejemplo y el caso vacío.

### 29. Contabilidad honesta
`production_usage.py`: además de `mcp_calls`/`response_bytes`/`h3_takes`, `usage` gana `gpu_seconds` (canción + frames +
clips medidos en `timing`), `cpu_seconds` (escenas, montaje, paquete), `retry_seconds` (segundos de tomas más allá de la
primera, jobs perdidos y frames fallidos) y `reused_seconds` (lo que una reanudación no tuvo que rehacer: planos cuyo
fingerprint no cambió). Para esto cada `run()` debe dejar un registro `{started, finished, retake, timing}` en
`state["runs"]` (gancho de ≤ 5 líneas en `run`, tras el bloque 0). Nada de tokens de LLM: dilo en el runbook. Test con estados
de una primera pasada y una reanudación.

---

## BLOQUE B. Calidad medida (puntos 25, 26, 27, 30)

Archivos: `production_review.py`, `production_review_checks.py`, `production_timing.py`; nuevos `production_smoothness.py`,
`production_enhance.py`, `production_levels.py`. Lo que engancha con el runner (25 y la captura de 30) espera al bloque 0.
26 y 27 empiezan ya.

### 26. Análisis de fluidez ("tirones")
Problema: en City of Windows hubo tirones y la hoja de contactos no permitía verlos; el análisis actual (`production_clip_qa`)
mide movimiento, parpadeo, deriva de color y salto de identidad, no la cadencia. Un tirón puede venir del clip original,
de un cambio de velocidad/retime, de la conversión de imagen por segundo al exportar o del montaje.
- `production_smoothness.py`: para un MP4, (a) marcas de tiempo de paquetes/fotogramas con `ffprobe` (o OpenCV
  `CAP_PROP_POS_MSEC`): desviación respecto a 1/fps y deltas irregulares; (b) rachas de fotogramas casi idénticos (diferencia
  absoluta media entre consecutivos bajo un umbral) y su periodo dominante (un patrón 3:2 indica conversión 24 → 30);
  (c) saltos de velocidad (la serie de diferencias por fotograma con picos periódicos o escalones); (d) una puntuación y una
  etiqueta: `ok | judder | duplicates | speed_steps`.
- Atribución: aplícalo al clip original, a la escena exportada de ese plano y al vídeo final, y devuelve la primera etapa
  donde aparece el problema (`clip → scene → final`). Así se sabe si hay que rehacer el clip (GPU), la escena (CPU) o el montaje.
- Integración: lo llama `production_review_checks.py` (archivo del bloque) para los planos de `state`, como un chequeo más
  con su pregunta en `review.failures` (p. ej. `judder`) y `retake_keys` solo si el origen es el clip.
- Pruebas (sin GPU, con `ffmpeg -f lavfi`): `testsrc2` suave → ok; `fps=12,fps=24` → duplicates; 24 → 30 con `fps=30` →
  patrón 3:2; `setpts` con cambios de velocidad → speed_steps; umbrales fijados con los 17 clips de `voices-v2` (nada debe
  marcarse en los que se ven bien).

### 27. Veredictos por niveles
Hoy `review` es `{verdict, failures, unknown}` + `retake_keys` (cuatro chequeos de código) y los clips no cantados pasaban con
`ok`. Un `ok` técnico no es aprobación artística.
- `production_levels.py`: `review.levels = {execution, technical, artistic}` **además** de las claves actuales (no rompas a los
  agentes ni los tests que las leen). `execution`: el archivo existe y se reproduce (`ffprobe`). `technical`: definición,
  movimiento, texto, sincronía, continuidad, fluidez (26), sujetos por plano (#643), con los umbrales y números que usó cada
  uno. `artistic`: **nunca `ok` automático**. Devuelve `{verdict: "pending_judgement", evidence: {contact_sheet, animatic,
  frames_sheet, frames: [fotograma real de cada momento fuerte]}}`; cuando existe el estado de revisión del bloque D, `artistic`
  = `approved_by_review` si todos los planos están aprobados, `changes_requested` si alguno lo pide, `pending_judgement` si no.
- Intención por plano: `shot.allow: ["still", "dark", "secondary", "frozen"]` en el spec suprime el chequeo
  correspondiente para ese plano (un plano quieto, oscuro o con personajes secundarios a propósito no es un fallo). Valídalo
  en `validate_spec` (mismo patrón que los otros campos de plano; ≤ 5 líneas) y documéntalo.
- Test: un plano `still` con `allow: ["still"]` no da `frozen_shot`; `artistic` jamás `ok` sin revisión; las claves
  antiguas siguen idénticas.

### 25. Resolución de extremo a extremo
El runner fija los fotogramas iniciales y H3 a 1280×704 (`FRAME_RESOLUTIONS[0]`, `clip_job`) y exporta a 1920×1080; escalar no
recupera detalle, y `fit: fill` recorta (1280×704 es 1,818:1, el vídeo 1,778:1). El valor por defecto del modelo H3 en
`app/defaults/minimax_h3_fused_turbo.json` es 1152×640. Existen FlashVSR y RIFE en `app/postprocessing/` y el parámetro
`spatial_upsampling` (p. ej. `"flashvsr*2"`) que valida `services/wangp_submission.py` (`validate_selection`).
1. `spec.resolution = {frames, clips}` (por defecto lo actual). Valida contra lo que el modelo admite (lee los defaults del
   modelo; no llames a `models`, son decenas de miles de tokens).
2. Paso opcional `enhance` (`spec.enhance: {"method": "flashvsr", "scale": 2}`): pasa cada clip por el postprocesado antes
   de montar. Comprueba primero si `generate` admite `spatial_upsampling` para H3 o si hay que usar el servicio de
   `tools_upscale.py`; elige la vía que se integre en la cola sin inventar otra. Con estimación de coste en `dry_run`
   (gancho de ≤ 5 líneas) y `timing` propio.
3. Informa por plano la resolución de origen y el recorte aplicado.
4. RIFE opcional cuando el análisis de fluidez (26) lo recomiende.
Aceptación: sobre 3 clips de `voices-v2`, GPU-minutos extra y mejora medible (nitidez/SSIM frente a escalado bicúbico), con las
imágenes en `/home/ina/grok-data`. El enganche en el runner espera al bloque 0.

### 30. Por qué H3 va a 20-38 s/paso unas veces y otras no
Registra por clip las fases (carga de modelo, compilación, pasos con s/paso, exportación) en `timing.shots`. La medición de
s/paso ya existe en `generation_memory.note_inference_step` (campo `performance` del job); comprueba qué devuelve la respuesta
de `status` de un job y captura `performance` dentro de `Production.wait`/`land` (gancho ≤ 5 líneas, tras el bloque 0) y
escríbela en `state["clip_perf"][key]`; `production_timing.py` la publica en `timing.shots[i]` (`s_per_step`, `degraded`,
`model`). Sin adivinar: si un dato no está en la respuesta del job, deja `null` y anota qué campo falta.

---

## Entrega de cada PR
- Enlace, defecto concreto que resuelve, archivos tocados, pruebas (con los números), y qué sigue pendiente de su bloque.
- Medidas reales donde el bloque las pide (segundos, GPU-minutos, RAM) con fecha y qué datos usaste.
- Conflictos evitados con otros bloques (tabla de solapes del tablero).
- Tokens solo si están medidos por el cliente del LLM; si no, di que no se midieron.
- CI del HEAD del PR comprobada. No mezcles tú el PR: lo revisa Claude.
