# Producción de videoclips: tablero de trabajo (2026-09-30)

Repartir lo que falta del plan `GROK_PRODUCTION_NEXT_2026-09-29.md` (el detalle por bloque, en `GROK_PRODUCTION_BLOCKS_2026-09-30.md`) (los números son los de ese documento) para que dos
agentes no abran lo mismo. GitHub tiene los issues desactivados: **este archivo es el tablero**. Cada PR que cierre o
avance un bloque actualiza aquí su estado en el mismo PR. Estado comprobado el 2026-09-30 contra `origin/development` 40df83ec
(archivos y ramas, no solo títulos de PR).

## Reglas
1. Un bloque = un dueño = archivos exclusivos (columna "Archivos"). Si necesitas tocar un archivo de otro bloque, abre
   una nota en la tabla de solapes (abajo) y espera o pide el cambio al dueño.
2. `app/services/music_production.py` (1154 líneas, ya hotspot de complejidad) es zona restringida hasta que aterrice el
   bloque 0: en ese archivo solo se permiten ganchos de ≤ 5 líneas que llamen a un módulo nuevo. Después, lo mismo.
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

## Bloques pendientes
| Bloque | Puntos | Dueño propuesto | Rama | Archivos (exclusivos) | Aceptación |
|---|---|---|---|---|---|
| **0. Refactor de `music_production.py`** | 17, 18, 19, 20 | Grok, PR borrador en `fix/music-spec-complexity` | `fix/music-spec-complexity` | `music_production.py`; `production_state.py` (guardado con debounce), `production_song.py`, `production_images.py`, `production_clips.py`, `production_scene_ops.py`, `production_montage.py` | `music_production.py` pasa de 1189 a 669 líneas y la complejidad máxima de 24 a 23. El log se escribe como mucho cada 2 s; un save de estado sigue escribiendo al momento. El runbook documenta `appearance_changed` frente a `face_consistent` y cómo copiar un preset. Los tests actuales no se editan. Sin mezclar. |
| **A. Dirección** (PR #668 abierto, 2026-09-30) | 21 tratamiento y variación; 23 modo `trailer` | Claude | `feat/production-treatment` | nuevos `production_treatment.py`, `production_structure.py`, `production_trailer_audio.py`; `production_shot_plan.py`, `production_plan.py` | `spec.treatment` validado; avisos `chorus_repeats_identical` y `moment_without_shot` en el dry-run (gancho de ≤ 5 líneas en `production_dry_run.py`); `structure: "trailer"` compila silencios, impactos y entrada tardía de la canción; el modo `clip` no cambia (tests de regresión sobre los specs actuales). |
| **B. Calidad medida** | 25 resolución y `enhance`; 26 fluidez; 27 veredictos por niveles; 30 fases de H3 | Grok (detalle en `GROK_PRODUCTION_BLOCKS_2026-09-30.md`) | `feat/production-quality-levels` | `production_review.py`, `production_review_checks.py`, `production_timing.py`; nuevos `production_smoothness.py`, `production_enhance.py`, `production_levels.py` | 26: clips sintéticos con fotogramas duplicados y cambios de cadencia detectados, y atribución clip→escena→final. 27: `review {execution, technical, artistic}` y `artistic` nunca `ok` automático (devuelve evidencias y "pendiente de criterio"); intención por plano `shot.allow`. 25: coste extra de GPU y mejora medibles en 3 clips del Gremlins v2. 30: fases (carga, compilación, pasos, s/paso) en `timing.shots`. El enganche de 25 en el runner espera al bloque 0. |
| **C. Operativa** | 12 exportar escenas en paralelo; 13 progreso y ETA; 14 sondeo largo (`MAX_WAIT_S` y `until`); 15 medir y, si hace falta, ajustar la descarga de Qwen antes de H3 (ya existe en `generation_memory.py`); 16 estimación con datos propios; 29 contabilidad `gpu_seconds`/`reused_seconds` | Grok (tras el bloque 0) | `feat/production-operations` | `production_wait.py`, `production_scene_retry.py`, `production_usage.py`; nuevos `production_progress.py`, `production_gpu.py`, `production_estimate.py` | 14 y 16 se pueden hacer ya (no tocan `music_production.py`); 12, 13, 15 esperan al bloque 0. 12: tiempo de 21 escenas antes/después con `HOCUS_SCENE_EXPORT_CONCURRENCY`. 15: s/paso de H3 tras Qwen con y sin la descarga. 29: sin conversión de bytes a tokens. |
| **D. Revisión plano a plano** (prioridad del usuario) | Nuevo: cambios por plano pedidos a un LLM/asistente o a mano; rehacer un plano desde el fotograma con prompts nuevos; estado aprobado/pide cambios; bloqueo de ediciones manuales; historial y deshacer; modo Revisar en la UI; `publish` exige revisión | Grok | `feat/production-shot-review` | nuevos `production_shot_review.py`, `production_shot_redo.py`, `production_shot_request.py`, `ReviewMode.tsx`; `production_commands.py`, `routers/music_productions.py`, `production_publication.py`, `production_shot_edit.py` | Ver `GROK_PRODUCTION_BLOCKS_2026-09-30.md`, bloque D: redo de un solo plano con el resto intacto, plan del LLM validado contra un esquema cerrado (con test de inyección), modo Revisar con teclado, prueba real sobre `voices-v2`. **Empieza ya: no toca `music_production.py` salvo ganchos de ≤ 5 líneas tras el bloque 0.** |
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
