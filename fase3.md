# Fase 3 — GenerationRecord: autoridad y proyecciones coherentes

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `fix/generation-record-authority` → `main`.
- Dependencias: Fase 1 mezclada; revisar el código integrado de #138 y sus correcciones posteriores.
- Archivos/módulos propios: app/services/generation_record.py, ui/src/lib/generationRecord.ts, schema, tests y documentación de dominio.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Medio-alto.

## Tareas de implementación

- [x] F3.1 — Grafo en `docs/development/GENERATION_RECORD.md`: command → workflow? → run? → generation attempt → task? → asset*. Un intento puede publicar 0..n assets. `run_id` es correlación, no un segundo store.
- [x] F3.2 — `workspace_id` es `string | null`. `output_folder` es el físico. Sin colección no se copia el folder al schema (`test_rejects_host_paths_and_missing_workspace`, `test_unscoped_store_is_not_a_workspace_collection`).
- [x] F3.3 — `AUTHORITY = "projection"`. El JSON es proyección durable con CAS; bytes y provenance siguen en asset-manifest v1.
- [x] F3.4 — Cubierto por #138 y tests vigentes: `test_cancellation_before_and_during_running`, `test_manifest_partial_maps_to_result_kind`, `test_retry_mints_new_generation_id_and_lineage`. `request_cancel` vs `apply_cancel`.
- [x] F3.5 — `prompt_original` / `prompt_effective`, `queue_ms` / `inference_ms` / `duration_ms`→`timing.total_ms`, `lineage.transformations`. `test_original_and_effective_prompts_round_trip`.
- [x] F3.6 — `merge_generation_record` no borra lineage con listas vacías; el patch omite arrays vacíos. `test_merge_empty_lists_do_not_wipe_lineage`.
- [x] F3.7 — `resume(..., worker_alive=False)` marca `reconciliation.needed` + `interrupted`; el status durable no pasa a completed. `test_resume_after_simulated_restart_keeps_running`.
- [x] F3.8 — `revision` CAS en `persist_generation_record`. Dos escritores: `test_cas_rejects_stale_revision`. Load no muta el archivo.
- [x] F3.9 — Sin `_launch_runtime.py`, productores ni movimiento de archivos.

## Pruebas y criterio de aceptación

Corpus Python/TS de transiciones y proyecciones; dos escritores; datos legacy y corruptos; cero efectos sobre archivos existentes al leer.

Aceptación: Contrato compatible, autoridad única definida y actualizaciones sin pérdida de metadata ni sobrescritura obsoleta.

## Punto de parada

Mezclar antes de fase 4. No dar por resuelta la recuperación real: todavía falta ejecutar el protocolo.

## Protocolo obligatorio para cada fase

- [x] Fase 1 mezclada (`af51ecef` / main `d4263ce6`). #138 ya cubría F3.4; el resto va en este PR, no se reabre.
- [x] Worktree `/tmp/hocus-fase3` desde `origin/main`. Stashes intactos.
- [x] PRs abiertos: #141 (lyrics). Sin tocar launch/store/agentActions/StoryLabPanel.
- [x] Base `d4263ce6`. Propios: generation_record.py, generation_record_io.py, generationRecord.ts, schema, tests, GENERATION_RECORD.md, fase3.md.
- [x] Tareas F3.1–F3.9 marcadas con evidencia (tests + docs).
- [x] pytest `tests/test_generation_record.py` 18 passed; arquitectura 5 passed; TS generationRecord 10 passed; `validate_local.sh` OK (E2E 7/7); ratchet vs `d4263ce6` +38 líneas (presupuesto 75), score 49.8 +0.0.
- [x] Add explícito de contrato/IO/tests/docs. Sin outputs.
- [ ] PR `fix/generation-record-authority` hacia main (este commit).
- [ ] Esperar CI del último head; resolver fallos atribuibles al cambio. Leer comentarios de Cursor, contrastarlos y corregir con tests.
- [ ] Entregar URL, head/base SHA y estado separado. No merge.
- [x] No continuar a fase 4: depende de que esta fase esté mezclada.

## Registro de entrega

- Base SHA: `origin/main` `d4263ce6`
- Rama / PR: `fix/generation-record-authority` (abrir)
- Commit implementado: (este commit)
- Tests ejecutados y resultado: 18 pytest generation-record + arquitectura; 10 TS; validate_local OK; ratchet passed (+38 / 75)
- CI del head: pendiente
- Revisión Cursor (SHA, hallazgos pendientes): pendiente
- Merge en main (lo completa quien lo verifique): no
- Generación real: NO EJECUTADA
- Bloqueos / siguiente fase elegible: esperar merge de #141 y de este PR. Fase 4 no es elegible hasta mezclar fase 3.

Los checkboxes describen trabajo; los estados de entrega son independientes. No marcar una fase globalmente terminada sólo por abrir su PR. Tests reales requieren autorización manual separada. No son un requisito para abrir el PR y nunca se ejecutan en CI.

