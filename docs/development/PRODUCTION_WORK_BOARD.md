# Producción de videoclips: tablero de trabajo (2026-09-30)

## Cierre 2026-09-30

Quedó en `development` antes de este cierre: fluidez #661, tratamiento y tráiler #668, revisión en tres capas #672, atmósfera crystal cave #673 (`4aedc6aa`). La rama `feat/production-phase-close` cierra lo que seguía abierto: espera hasta 1200 s con `until`, progreso y ETA, estimación con historial, segundos de uso, debounce del guardado, resolución y enhance planificado, fases H3 cuando el job las trae, revisión humana por plano, bloqueo, rehacer/deshacer, y la puerta de publicación. `music_production.py` queda en 688 líneas en `fix/music-production-under-700`: las etapas salen a módulos propios y se quedan la espera, la resolución, el bloqueo, el enhance planificado y el guardado cada 5 s. No hay medida de la tabla de 17 fotogramas Qwen→H3, ni del tiempo de 21 escenas, ni de SSIM, ni de los seis retratos, ni del antes/después de gremlins. `artistic` no pasa a ok por código.

Repartir lo que falta del plan `GROK_PRODUCTION_NEXT_2026-09-29.md` (el detalle por bloque, en `GROK_PRODUCTION_BLOCKS_2026-09-30.md`) (los números son los de ese documento) para que dos
agentes no abran lo mismo. GitHub tiene los issues desactivados: **este archivo es el tablero**. Cada PR que cierre o
avance un bloque actualiza aquí su estado en el mismo PR. Estado comprobado el 2026-09-30 contra `origin/development` 40df83ec
(archivos y ramas, no solo títulos de PR).

## Estado 2026-10-01 (comprobado contra `origin/development` 50a2a17c)

Los bloques 0, A, B, C y D están en `development`. Lo que sigue abierto son medidas con GPU, no código. El detalle original de
cada bloque (archivos y aceptación) queda más abajo, sin tocar.

| Bloque | Estado | PR | Pendiente |
|---|---|---|---|
| 0. Refactor de `music_production.py` | Hecho: 688 líneas, etapas en sus módulos | #716 | Nada |
| A. Dirección | Hecho | #668 (arreglos de tráiler: #669, #670) | Nada |
| B. Calidad medida | Hecho en código | #661 fluidez, #672 revisión en tres capas, #687 resolución y `enhance` planeado, #694 veredicto humano en `artistic` | Medir FlashVSR en 3 clips del Gremlins v2 (GPU). `enhance` solo corre con un upscaler inyectado y RIFE solo se recomienda |
| C. Operativa | Hecho en código | #687: espera hasta 1200 s con `until`, progreso y ETA, estimación con historial, `gpu_seconds`/`reused_seconds`, `HOCUS_SCENE_EXPORT_CONCURRENCY` | Medidas con GPU: 21 escenas antes y después (punto 12) y s/paso de H3 tras Qwen con y sin descarga (punto 15) |
| D. Revisión plano a plano | Hecho; el borrador #690 se cerró y su contenido entró por #694 | #694; #710 vistas previas; #726 y #728 lista de planos y acciones; #702, #708, #714, #715, #725 bloqueo y toma; #733 deshacer re-export (todo lo posterior a #694 entró por la integración #731) | Redo real de voices-v2 en GPU. `request` devuelve `applied: false` salvo `apply: true` |
| Producciones unificadas | Hecho | #721 identidad Story/episodio; catálogo y vista de planos en #731; #727 conflicto de revisión; #734 obras antiguas | Nada |

Mantenimiento del mismo día: #731 integró lo que seguía abierto (la búsqueda de plantillas por palabras de #720 incluida);
#722 hace que un perfil sin guardar use Qwen Image 2.1 local si está instalado (producciones ya preferían Qwen por GPU desde
#667 y `production_image_defaults.py`); #724 añade `media.options` para que un asistente vea qué hay y pregunte antes de crear.
Quedaron fuera de la integración, por no abrirse ese día: #589, #583, #575, #564 y #486.

## Reglas
1. Un bloque = un dueño = archivos exclusivos (columna "Archivos"). Si necesitas tocar un archivo de otro bloque, abre
   una nota en la tabla de solapes (abajo) y espera o pide el cambio al dueño.
2. `app/services/music_production.py` queda en 688 líneas tras `fix/music-production-under-700`. Una etapa nueva
   vive en su módulo. En este archivo solo entran ganchos cortos que llamen a ese módulo.
3. Antes de empezar: `git fetch && git grep` de las palabras clave del punto, `gh pr list`, y mira las ramas remotas recientes.
   Abre el PR como borrador el primer día con el nombre de rama de la tabla; eso es la reclamación.
4. Un PR por bloque (o por punto si el bloque es grande). Sin GPU mientras otro agente produce en 42017/42021: los
   bloques de abajo se prueban con clips sintéticos y MCP simulado; la medida real va en el PR con la instancia propia.
5. Cada PR: tests dirigidos registrados en `scripts/ci_test_groups.json`, `cd ui && npm run check` si toca UI,
   `BASE_REF=origin/development scripts/check_code_health_pr_base.sh`, y una línea en el runbook.
6. Tokens: solo los medidos por el cliente del LLM; nunca bytes de MCP convertidos (ver runbook, `usage`).

## Hecho y mezclado (no reabrir)
| Punto | PR |
|---|---|
| P0 1-5: panel de producciones, use_take, shot.update, song.use, cancel | #624 |
| 6: puerta visual de clips no cantados | #638 |
| 7: sujetos por plano frente a `cast.count` | #643 (dentro de #659) |
| 8: retrato limpio por personaje | #645 |
| 9, 10, 11, 22, 28: animatic barato, `caption_unreadable`, `hold_after_clip`, validación del dry-run | #637 |
| 24 (primera versión): `kind: scene3d` exportado con el worker de World3D | #620, #622, #626 |
| 31: `production.publish` | mezclado (`production_publication.py`) |
| Evaluación offline del paquete antes de publicar | #619 |
| Base: #608, #613, #614, #632, #660 | Claude |
| Bloques 0, A, B, C, D completos en código (medidas con GPU pendientes) | #716, #668, #661/#672/#687/#694, #687, #694/#731 |
| Escenarios Video 3D Silicon Dreams (rejilla, circuito, mainframe) | #703, #709 |
| Perfil sin guardar con Qwen Image 2.1 si está instalado; `media.options` | #722, #724 |

## Bloques (detalle original; el estado vigente está arriba)
| Bloque | Puntos | Dueño propuesto | Rama | Archivos (exclusivos) | Aceptación |
|---|---|---|---|---|---|
| **0. Refactor de `music_production.py`** | 17, 18, 19, 20 | Grok | `fix/music-production-under-700` | `music_production.py`; `production_windows.py`, `production_stage_frames.py`, `production_stage_clips.py`, `production_stage_scenes.py`, `production_stage_run.py` | El corte antiguo de 669 líneas no se reutiliza: quitaría espera, resolución, bloqueo y enhance. Este corte deja el archivo en 688 líneas y conserva esos comportamientos. El guardado sigue cada 5 s (claves volátiles `log` y `usage`). |
| **A. Dirección** (#668 mezclado) | 21 tratamiento y variación; 23 modo `trailer` | Claude | `feat/production-treatment` | nuevos `production_treatment.py`, `production_structure.py`, `production_trailer_audio.py`; `production_shot_plan.py`, `production_plan.py` | `spec.treatment` validado; avisos `chorus_repeats_identical` y `moment_without_shot` en el dry-run (gancho de ≤ 5 líneas en `production_dry_run.py`); `structure: "trailer"` compila silencios, impactos y entrada tardía de la canción; el modo `clip` no cambia (tests de regresión sobre los specs actuales). |
| **B. Calidad medida** | 25 resolución y `enhance`; 26 fluidez; 27 veredictos por niveles; 30 fases de H3 | Grok (detalle en `GROK_PRODUCTION_BLOCKS_2026-09-30.md`) | `feat/production-quality-levels` | `production_review.py`, `production_review_checks.py`, `production_timing.py`; nuevos `production_smoothness.py`, `production_enhance.py`, `production_levels.py` | 26: clips sintéticos con fotogramas duplicados y cambios de cadencia detectados, y atribución clip→escena→final. 27: `review {execution, technical, artistic}` y `artistic` nunca `ok` automático (devuelve evidencias y "pendiente de criterio"); intención por plano `shot.allow`. 25: coste extra de GPU y mejora medibles en 3 clips del Gremlins v2. 30: fases (carga, compilación, pasos, s/paso) en `timing.shots`. El enganche de 25 en el runner espera al bloque 0. Estado 2026-09-30 en `feat/production-quality-levels`: 26 y la base de 27 ya están en development; este PR valida `spec.resolution` y `spec.enhance`, añade el coste no medido en dry_run, `enhance_clip` con upscaler inyectado (sin GPU) y `crop_report`; publica `s_per_step`, `degraded` y `model` en `timing.shots`; `artistic` `pending` significa pending judgement hasta `review.json` o `review_shots`. La medida FlashVSR de 3 clips sigue pendiente de GPU. |
| **C. Operativa** | 12 exportar escenas en paralelo; 13 progreso y ETA; 14 sondeo largo (`MAX_WAIT_S` y `until`); 15 medir y, si hace falta, ajustar la descarga de Qwen antes de H3 (ya existe en `generation_memory.py`); 16 estimación con datos propios; 29 contabilidad `gpu_seconds`/`reused_seconds` | Grok (tras el bloque 0) | `feat/production-operations` | `production_wait.py`, `production_scene_retry.py`, `production_usage.py`; nuevos `production_progress.py`, `production_gpu.py`, `production_estimate.py` | 14 y 16 se pueden hacer ya (no tocan `music_production.py`); 12, 13, 15 esperan al bloque 0. 12: tiempo de 21 escenas antes/después con `HOCUS_SCENE_EXPORT_CONCURRENCY`. 15: s/paso de H3 tras Qwen con y sin la descarga. 29: sin conversión de bytes a tokens. |
| **D. Revisión plano a plano** (#690 cerrado; entró en #694 y #731) | Nuevo: cambios por plano pedidos a un LLM/asistente o a mano; rehacer un plano desde el fotograma con prompts nuevos; estado aprobado/pide cambios; bloqueo de ediciones manuales; historial y deshacer; modo Revisar en la UI; `publish` exige revisión | Grok | `feat/production-shot-review` | nuevos `production_shot_review.py`, `production_shot_redo.py`, `production_shot_request.py`, `ReviewMode.tsx`; `production_commands.py`, `routers/music_productions.py`, `production_publication.py`, `production_shot_edit.py` | Borrador abierto: https://github.com/IAnMove/hocuspocus/pull/690 (`feat/production-shot-review`). Aterrizó: `production.shot.review/lock/redo/request/undo`, `<id>.review.json`, campo `review` en el manifiesto, modo Revisar, `publish` rechaza planos no aprobados si `shots.json` los lista (salvo `accept_unreviewed`). `music_production.py` solo omite planos `locked`. Pendiente: el redo real de voices-v2 en GPU. |
| **Revisión** | todos | Claude | — | — | Claude revisa cada PR contra su fila (archivos fuera de la fila = comentario). |

## Orden y dependencias
1. Ya, en paralelo (no tocan `music_production.py`): bloque 0 (Grok), bloque A (Claude), bloque D (Grok: empieza por los comandos y la UI), bloque B menos el enganche de 25 (Grok), bloque C: 14 y 16 (Grok).
2. Cuando aterrice el bloque 0: los ganchos de D (omitir planos `locked` en `frames()`/`clips()`/`scenes()`), C 12, 13, 15, 29 y el enganche de B 25 y de B 30.
3. El motor por plano con una sola paleta (resto del punto 24) depende de los escenarios 3D (`GROK_ATMOSPHERE_SETS`, en marcha con luna, marte y nieve): no se reparte todavía.

## Solapes conocidos (se actualiza en los PR)
| Archivo | Quién lo toca | Regla |
|---|---|---|
| `production_dry_run.py` | A (avisos), C-16 (estimación) | Cada uno añade una función propia y una línea de enganche; nadie reordena el resto. |
| `production_timing.py` | B-30 (fases), C-29 (lee `clip_seconds`), C-14 (una línea: `state["stage"]` en `StageWatch.start`) | C solo lee salvo esa línea; B escribe. |
| `production_publication.py`, `production_shot_edit.py` | D | Nadie más; B-27 lee el estado de revisión de D, no edita esos archivos. |
| `production_review*.py` | B | Nadie más. Los chequeos nuevos de otros bloques entran como adaptadores que B registra. |
| `docs/agents/VIDEO_PRODUCTION_RUNBOOK.md` | todos | Cada bloque añade su sección al final de la suya; sin reescribir lo ajeno. |
| `scripts/ci_test_groups.json` | todos | Añadir el test propio en su grupo; los conflictos se resuelven conservando ambas líneas. |

## Producciones unificadas (2026-10-01)

### Cierre de integración automática — Codex

Reclamado en `feat/production-project-generation`: registro antes de iniciar
`production.run`, Director y Series; regeneración desde la revisión compartida;
recorrido Chromium sin GPU. Módulos nuevos de integración y ganchos pequeños en
los puntos de arranque, sin cambios de renderers ni launchers. La fila «Hecho»
anterior describe las capacidades del catálogo; no implica que los productores
ya llamen automáticamente al registro. No se tocan los fixes de undo (#737),
slot de escritura (#739), song switch (#742) ni audio del Director (#741/#743).

Reclamado por Grok en `feat/unified-productions-identity`. Índice y enlace
Story/episodio antes de generar. No rehace motores ni plantillas World3D.
Detalle y matriz: `docs/development/UNIFIED_PRODUCTIONS.md`.

| Archivo | Quién más | Regla |
|---|---|---|
| `app/_launch_runtime.py` | PR #717 `feat/world3d-templates-mcp` | Solo el `include_router` de `production_projects` junto a `/api/v1/productions`. No tocar el bloque de plantillas World3D. |
| `applicationAdapters.ts`, `capabilityRegistry.ts`, `wangp_mcp.py` | #717 | No se editan en el PR de identidad. El enganche Wizard/MCP espera o usa el HTTP de resolve. |
| `music_production.py` | PR #716 `fix/music-production-under-700` | No se edita. El enlace vive en `.production-project-links-v1.json`. |
| Bloque D (`production_shot_review.py`, `routers/music_productions.py`, `ReviewMode.tsx`) | revisión de planos | Consumir las operaciones. No duplicarlas. |
| `scripts/ci_test_groups.json`, `tests/fixtures/route_table.json`, este tablero, el runbook | #716 y #717 | Cambios aditivos. Al rebasar se conservan ambas aportaciones. |
| `app/services/production_shot_view.py`, `ui/src/features/production-shots/` | vista de planos, rama `feat/unified-productions-shots` | Solo lectura. No edita `ReviewMode`, el bloque D ni `music_production.py`. |
| `app/services/production_shot_actions.py` | acciones, rama `feat/unified-productions-actions` | Elige toma, revisión, bloqueo, deshacer y export desactualizado sobre el manifiesto, el Director o el montaje. No edita `music_production.py`, `production_shot_redo.py` ni `ReviewMode.tsx` (#723). |
| `app/services/production_work_commands.py`, `ui/src/features/production-catalog/`, una línea en `capabilityRegistry.ts`, un método `productionWorks.command` | catálogo, rama `feat/unified-productions-catalog` | Lista, abre y resuelve. El método del adaptador es aditivo. No reescribe plantillas World3D, `music_production.py` ni `wangp_mcp.py`. |
| `link_existing_production`, `production.works.link` | obras antiguas, rama `feat/unified-productions-legacy` | Vincula por id un registro reconocible. No mueve medios ni crea una Story. |

## Cómic a película, adenda 2026-10-01

Rama `fix/comic-film-pass-addendum`. Un cómic con motor H3 conserva cada viñeta
en el PRE: un plano corto se alarga al mínimo del modelo y no se fusiona con el
siguiente. LTX-2 entra en el selector cuando el catálogo lo marca compatible
con película de cómic. Un PRE guardado se reabre con su estado y su aprobación.
El error de ffmpeg muestra el final del registro y guarda el registro entero.
La resolución ofrecida, por ejemplo 1280×704, llega al PRE y al render.
Aceptar una prueba exige quién lo pidió, la vía y la nota de atestación.
