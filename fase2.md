# Fase 2 — Idiomas y texto literal sin reparación destructiva

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `fix/lyrics-language-contract` → `main`.
- Dependencias: Fase 1 mezclada. Revisar y continuar #139 si cubre este trabajo; #137 puede estar ya mezclado.
- Archivos/módulos propios: app/services/lyrics_language.py, ui/src/lib/lyricsLanguageGuard.ts, sus tests y docs/development/LYRICS_LANGUAGE.md.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Medio.

## Tareas de implementación

- [x] F2.1 — Corpus + tests: `empty-vocal`, `english-requested-as-french`, `missing-protected-literal`, `cjk-only-repair-must-not-ok-empty`, `estonian-is-not-spanish` en `tests/fixtures/lyrics_language_corpus.json`.
- [x] F2.2 — `verdict`: valid | invalid | unevaluable. `ok` sólo si valid. `fr`/`et` no scored → unevaluable.
- [x] F2.3 — Alias exactos + BCP-47 + tokens >2; sin startsWith. Cubierto por #139 y reafirmado aquí (Estonian≠es).
- [x] F2.4 — Fragmentos protegidos por inclusión exacta, incluido newline. Falta → invalid.
- [x] F2.5 — `repair` escribe `proposal`/`proposal_diffs`; `lyrics` es el original. `assert_lyrics_language(..., repair=False)` por defecto. Proposal vacío no es vocal válida.
- [x] F2.6 — Corpus JSON compartido ejecutado por `tests/test_lyrics_language.py` y `ui/tests/lyricsLanguageGuard.test.ts`.
- [x] F2.7 — `docs/development/LYRICS_LANGUAGE.md`. Sin launch ni StoryLabPanel.

## Pruebas y criterio de aceptación

Tests Python/TS del corpus, compatibilidad con songLanguage, validación segura del repositorio.

Aceptación: Ningún caso desconocido o vacío da un falso éxito; ninguna reparación borra silenciosamente texto del usuario.

## Punto de parada

Un PR de librería corregida no significa protección activa de Generate. El cableado pertenece a fase 6.

## Protocolo obligatorio para cada fase

- [x] Fase 1 mezclada (`af51ecef` / main `d4263ce6`). #139 cubría F2.3; el resto va en este PR nuevo, no se reabre #139.
- [x] Worktree `/tmp/hocus-fase2` desde `origin/main`. Stashes intactos.
- [x] PRs abiertos: ninguno. Sin tocar launch/store/agentActions/StoryLabPanel.
- [x] Base `d4263ce6`. Propios: lyrics_language.py, lyricsLanguageGuard.ts, tests, corpus, LYRICS_LANGUAGE.md, fase2.md.
- [ ] Marcar [x] sólo tras cumplir la tarea y añadir evidencia breve: archivo, comando/resultado o URL/SHA. Un plan o test escrito sin ejecutar no acredita validación.
- [x] pytest lyrics 20 passed; TS corpus 15 passed; `validate_local.sh` OK; ratchet vs `d4263ce6`.
- [x] Add explícito de librería/tests/docs. Sin outputs.
- [x] PR nuevo `fix/lyrics-language-contract` (no se reabre #139).
- [ ] Esperar CI del último head; resolver fallos atribuibles al cambio. Leer comentarios de Cursor, contrastarlos y corregir con tests. Repetir checks tras fixes; revisión de un commit anterior no acredita el actual.
- [ ] Entregar URL, head/base SHA y estado separado de implementación, CI, Cursor, merge y smoke. No hacer merge ni activar auto-merge.
- [ ] Continuar otra fase sólo si sus dependencias están mezcladas y no comparte hotspot/contrato en cambio. Si no queda trabajo independiente elegible, parar y pedir que se mezclen los PRs concretos.

## Registro de entrega

- Base SHA: `origin/main` `d4263ce6`
- Rama / PR: `fix/lyrics-language-contract` (abrir)
- Commit implementado: (este commit)
- Tests ejecutados y resultado: 20 pytest + 15 TS + validate_local OK
- CI del head: pendiente del push
- Revisión Cursor (SHA, hallazgos pendientes): pendiente
- Merge en main (lo completa quien lo verifique): no
- Generación real: NO EJECUTADA salvo evidencia manual explícita.
- Bloqueos / siguiente fase elegible: fase 6 tras merge de 2 y 4. Fase 3 en paralelo.

Los checkboxes describen trabajo; los estados de entrega son independientes. No marcar una fase globalmente terminada sólo por abrir su PR. Tests reales requieren autorización manual separada. No son un requisito para abrir el PR y nunca se ejecutan en CI.

