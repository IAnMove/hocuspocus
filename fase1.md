# Fase 1 — Estado canónico y reglas de ejecución

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `docs/architecture-execution-baseline` → `main`.
- Dependencias: Ninguna. Revisar primero el PR documental #136; actualizarlo si corresponde en lugar de duplicarlo.
- Archivos/módulos propios: fase*.md, docs/development/SLICE_QUEUE.md y documentos canónicos de arquitectura; no código de producción.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Bajo.

## Tareas de implementación

- [x] F1.1 — Leídos AGENTS.md, planmejora.md, SLICE_QUEUE, CODE_HEALTH, LOCAL_VALIDATION, WIZARD_ACTION_RUNNER, WIZARD_WORKFLOW_RUNTIME, DOMAIN_MODEL_AND_ASSET_PROVENANCE, INTERNATIONALIZATION, GENERATION_RECORD. `comunicaciones/` sólo como evidencia histórica.
- [x] F1.2 — `git fetch origin --prune`. `origin/main` = `9ac4cacb` (merge #137). Stashes `{0}` `{1}` intactos. Workspace en `feat/local-minimax-music3` con `fase*.md` y `outputs/` sin commit. PRs abiertos: #136 `b2bdad47`, #139 `a6b7b0ff`, #140 `dc63eb5b`. Rama Cursor sin PR: `cursor/music-recovery-persistence-6c38` `ae76c653`.
- [x] F1.3 — Matriz en `docs/development/EXECUTION_BASELINE.md`. Columnas independientes; no se infiere merge desde CI.
- [x] F1.4 — #135/#138/#137 mezclados. #139 cubre F2.3 prefijos, no el corpus F2 restante. #140 cubre pending cliente, no finalización servidor. Hallazgos Cursor de SHAs antiguos no se reaplican al head que ya los corrige.
- [x] F1.5 — Cola unificada aquí y en SLICE_QUEUE. Ratchet wrapper y catálogos reutilizados (`scripts/validate_local.sh`, `check_code_health_pr_base.sh`). Fases versionadas en este PR. Sin outputs ni comunicaciones.
- [x] F1.6 — Grafo documentado en EXECUTION_BASELINE.md: merge obligatorio en cada flecha.
- [x] F1.7 — TaskRegistry = tareas/eventos; Story library = cues/candidatos; asset-manifest = bytes publicados; GenerationRecord = proyección, no segundo scheduler.

## Pruebas y criterio de aceptación

Comprobar links y diff; verificar estados con GitHub. No ejecutar generaciones para un PR documental.

Aceptación: Una sola cola vigente, SHA y estados explícitos, fases entregables sin duplicar PRs.

## Punto de parada

Puede prepararse 2 y 3 tras integrar esta base. Si #136 ya cubre la fase, documentar evidencia y no abrir otro PR equivalente.

## Protocolo obligatorio para cada fase

- [x] Leer fase1.md y esta fase; dependencias: ninguna. #136 ya era el PR documental; se actualiza en lugar de duplicar (`docs/slice-queue-post-134`).
- [x] Inspeccionar cambios locales. Worktree `/tmp/hocus-docs-sync` desde `origin/main` `9ac4cacb`. Stashes `{0}` `{1}` no aplicados. `outputs/` y `comunicaciones/` fuera del PR.
- [x] PRs abiertos: #136 docs, #139 lyrics (no launch), #140 Story pending (no launch). Ningún segundo PR de `_launch_runtime.py` / `useStore.ts` / `agentActions.ts`. Sin ramas apiladas.
- [x] Base SHA `9ac4cacb`. Archivos propios: `fase*.md`, `docs/development/EXECUTION_BASELINE.md`, SLICE_QUEUE, DOMAIN_MODEL, GENERATION_RECORD, WIZARD_AUTOMATION_ROADMAP. Prohibido: launchers, pesos, outputs, WanGP.
- [x] Checkboxes de F1.1–F1.7 marcados con evidencia en EXECUTION_BASELINE.md y este archivo.
- [x] `PYTHON=app/env/bin/python bash scripts/validate_local.sh` OK (contratos 13, UI, lint, build, E2E 7/7). `check_code_health_pr_base.sh` ratchet passed, +0 LOC. `check_documentation_links.py` PASS.
- [x] Add explícito: `fase1.md`–`fase12.md`, `docs/development/EXECUTION_BASELINE.md`, SLICE_QUEUE, DOMAIN_MODEL, GENERATION_RECORD, WIZARD_AUTOMATION_ROADMAP. Sin outputs, comunicaciones, stashes, env.
- [x] Actualiza PR existente #136 (no se abre un segundo PR documental).
- [ ] Esperar CI del último head; resolver fallos atribuibles al cambio. Leer comentarios de Cursor, contrastarlos y corregir con tests. Repetir checks tras fixes; revisión de un commit anterior no acredita el actual.
- [ ] Entregar URL, head/base SHA y estado separado de implementación, CI, Cursor, merge y smoke. No hacer merge ni activar auto-merge.
- [x] No continuar fase 2 ni 3 hasta que esta base esté mezclada. #139/#140 no se duplican.

## Registro de entrega

- Base SHA: `origin/main` `9ac4cacb`
- Rama / PR: `docs/slice-queue-post-134` / https://github.com/IAnMove/hocuspocus/pull/136
- Commit implementado: (este commit de fase 1 sobre #136)
- Tests ejecutados y resultado: documental; `validate_local.sh` + ratchet vs base exacta (sin GPU)
- CI del head: pendiente del push de este commit
- Revisión Cursor (SHA, hallazgos pendientes): pendiente del head nuevo
- Merge en main (lo completa quien lo verifique): no
- Generación real: NO EJECUTADA salvo evidencia manual explícita.
- Bloqueos / siguiente fase elegible: fases 2 y 3 **tras merge** de esta base. #139 y #140 ya abiertos; no duplicar. No continuar 2/3 hasta el merge de fase 1.

Los checkboxes describen trabajo; los estados de entrega son independientes. No marcar una fase globalmente terminada sólo por abrir su PR. Tests reales requieren autorización manual separada. No son un requisito para abrir el PR y nunca se ejecutan en CI.

