# Fase 4 — Envío musical idempotente antes de ejecutar

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `feat/music-submission-contract` → `main`.
- Dependencias: Fase 3 mezclada. Ningún PR abierto puede poseer _launch_runtime.py.
- Archivos/módulos propios: Nuevo servicio musical estrecho en app/services, API musical existente, tests de contrato. Cableado mínimo en app/_launch_runtime.py; no extraer router aún.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Alto.

## Tareas de implementación

- [x] F4.1 — Inventario en `docs/development/MUSIC_SUBMISSION.md`: local ACE/Music3 (`generateMusic`), remoto 202 jobs, sync legado. Endpoints intactos.
- [x] F4.2 — `spec_snapshot` + `idempotency_key` / `command_id` / `output_folder` / `workspace_id` / `library_revision`.
- [x] F4.3 — `submit_music_generation` reserva `generation_id`, `task_id`, `job_id`, `candidate_id` y crea la fila TaskRegistry. Destino Story por ID.
- [x] F4.4 — Misma clave+spec → replay; misma clave+spec distinto → `MusicSubmissionConflict` 409.
- [x] F4.5 — `intent=retry|new_version` mint nuevo intento; retry guarda `parent_generation_id`.
- [x] F4.6 — Jobs POST sigue en 202. Sync legado documentado. Poll GET existente.
- [x] F4.7 — `TaskRegistry.create` (idempotente). Tests sin GPU/modelos.
- [x] F4.8 — `tests/test_music_submission.py`: after_persist falla, 8 hilos, título ≠ id, revisión stale.

## Pruebas y criterio de aceptación

FastAPI/servicio real con worker falso y almacén temporal; una sola ejecución por clave; ruta y schemas compatibles.

Aceptación: Toda aceptación queda durable y se puede consultar aunque se pierda la respuesta HTTP.

## Punto de parada

Parar para merge antes de fase 5. No abrir simultáneamente otra modificación de launch.

## Protocolo obligatorio para cada fase

- [x] Fases 2 y 3 mezcladas (`58b7a08a`, `8b010a68`). Ningún PR abierto.
- [x] Worktree `/tmp/hocus-fase4` desde `origin/main`. Stashes intactos.
- [x] Un solo PR sobre `_launch_runtime.py`. Sin useStore/agentActions/StoryLabPanel.
- [x] Base `8b010a68`. Propios: music_submission.py, tests, MUSIC_SUBMISSION.md, cableado mínimo launch. Prohibido: launchers, pesos, outputs.
- [x] F4.1–F4.8 con evidencia en tests/docs.
- [x] validate_local OK (E2E 7/7) + ratchet vs `8b010a68`.
- [x] Add explícito. Sin outputs.
- [ ] PR `feat/music-submission-contract`.
- [ ] CI y Cursor del head. Sin merge.
- [x] No abrir fase 5 ni otro PR de launch hasta mezclar este.

## Registro de entrega

- Base SHA: `origin/main` `8b010a68`
- Rama / PR: `feat/music-submission-contract` (abrir)
- Commit implementado: (este commit)
- Tests ejecutados y resultado: pytest music_submission + minimax_music_jobs 14 passed
- CI del head: pendiente
- Revisión Cursor: pendiente (`cursor review` al abrir)
- Merge en main: no
- Generación real: NO EJECUTADA
- Bloqueos / siguiente fase elegible: fase 5 y 8 tras merge de este PR. Fase 6 tras este PR (fase 2 ya mezclada).

Los checkboxes describen trabajo; los estados de entrega son independientes. No marcar una fase globalmente terminada sólo por abrir su PR. Tests reales requieren autorización manual separada. No son un requisito para abrir el PR y nunca se ejecutan en CI.

