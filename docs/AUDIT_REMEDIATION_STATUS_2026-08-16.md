# Estado de remediación de la auditoría — 2026-08-16

Rama principal: `audit-full-remediation-2026-08-16`  
Base exacta: `68aa157` desde `agent/scheduler-observability`  
Contrato: un ticket por commit; cada ticket exige prueba o evidencia verificable.

La fuente autoritativa de criterios es
[`AUDITORIA_CODIGO_UI_2026-08-13.md`](AUDITORIA_CODIGO_UI_2026-08-13.md).
Este documento registra el estado vivo frente al código posterior a la auditoría.

Estados: `pendiente`, `delegado`, `completado`, `bloqueado`.

| Ticket | Estado | Evidencia principal |
| --- | --- | --- |
| SEC-01 | completado | Tests de move válido, traversal, absoluta y symlink de escape |
| SEC-02 | completado | Resolver común para trim/análisis; uploads/workspace válidos, externos y symlinks rechazados |
| SEC-03 | completado | Token bearer + cookie de sesión para LAN; loopback libre; UI, API y `/classic` cubiertos |
| TASK-01 | completado | Namespace `task-client-*` exacto en backend y UI; root externo eliminado/ignorado; tarea backend homónima conserva snapshot/eventos; 37 tests Python + 27 UI verdes |
| TASK-02 | completado | Comparación semántica normalizada antes de timestamp/evento: 10.000 syncs idénticas => 1 cambio, transiciones reales/terminales => 1 cada una, sin notify ni renovación de `completed_at`; 16 tests verdes. |
| TASK-03 | completado | Hash semántico sin `updatedAt`, dedupe y coalescing a 1,5 s; terminal/error inmediato; 100 polls iguales => 1 publicación; 30 tests UI verdes |
| TASK-04 | completado | Snapshot devuelve cursor bajo frontera atómica; Activity espera snapshot y abre SSE desde high-water mark; carrera concurrente + 10.000 eventos históricos cubiertos |
| TASK-05 | pendiente | — |
| TASK-06 | pendiente | — |
| TASK-07 | pendiente | — |
| DIR-01 | completado | Helper compartido mapea antes de filtrar, conserva índices originales/explicitos y prioriza `shotId`; huecos `[∅,b,∅,d] => [1,3]`, null y plan reordenado cubiertos; 49 tests UI + lint/build verdes. |
| DIR-02 | pendiente | — |
| PLAN-01 | pendiente | — |
| PLAN-02 | pendiente | — |
| PLAN-03 | pendiente | — |
| DIR-03 | pendiente | — |
| SER-01 | pendiente | — |
| SER-02 | pendiente | — |
| SER-UI-01 | pendiente | — |
| SER-UI-02 | pendiente | — |
| DUR-01 | pendiente | Revalidar contra `c2da86c` |
| SER-UI-03 | pendiente | — |
| SER-03 | pendiente | — |
| STORY-01 | pendiente | — |
| STORY-02 | pendiente | — |
| STORY-03 | pendiente | — |
| STORY-04 | pendiente | — |
| UI-WS-01 | completado | Epochs y AbortController aíslan outputs/metadata por workspace, invalidan listas y mutaciones tardías y pasan workspace explícito en todos los consumidores; 5 regresiones diferidas, 44 tests UI, lint y build verdes. |
| UI-SEARCH-01 | completado | Input controlado; debounce cancelado al cerrar/desmontar y store limpiado sin búsqueda/carga fantasma; 35 tests UI + lint/build verdes |
| UI-GEN-01 | completado | `deriveIsGenerating` es la única derivación del flag y sólo acepta queued/waiting/running/cancelling; todas las rutas migradas; historial terminal => false; 37 tests UI + lint/build verdes |
| EDITOR-01 | pendiente | Revalidar contra `b6c741a` y `68aa157` |
| EDITOR-02 | pendiente | — |
| EDITOR-03 | pendiente | — |
| PLAY-01 | completado | Cursor de reproducción por ID estable en Series y Stories: reordenar o reemplazar un intento conserva el clip activo y eliminarlo detiene Play all explícitamente; 39 tests UI, lint y build verdes. |
| POLL-01 | pendiente | — |
| TIMELINE-01 | completado | Poll serial de Story timeline se detiene en estados terminales; Refresh manual recupera/reanuda y un éxito limpia el error; 33 tests UI + lint/build verdes |
| ACT-01 | completado | Fallos cancel/resume/dismiss quedan por task ID en bloque `aria-live`, preservan la tarea y ofrecen Retry; éxito limpia el error; 34 tests UI + lint/build verdes |
| UPLOAD-01 | completado | Ingesta en chunks de 1 MiB con límite acumulado y 413; publicación atómica, cleanup en error/cancelación, concurrencia acotada y transcode cancel-safe; 4 tests verdes |
| CANCEL-01 | completado | Token por job/workspace cierra únicamente la respuesta HTTP activa en streaming local/OpenAI-compatible/Anthropic; fallback informa safe boundary, stages se preservan y tokens se limpian; 115 tests focalizados verdes. |
| RES-01 | completado | Ticket monotónico + Condition por lane; sólo la cabeza adquiere, cancelación elimina/despierta; FIFO A/B/C validado 100 veces y B cancelado deja A/C; 17 tests verdes |
| A11Y-01 | completado | `ModalShell` aporta nombre, `role=dialog`, `aria-modal`, foco inicial/restaurado, Escape y trap Tab/Shift+Tab; migrados Director Dashboard y picker del editor; tests RTL + lint/build verdes. |
| A11Y-02 | pendiente | — |
| RESP-01 | pendiente | — |
| RESP-02 | pendiente | — |
| RESP-03 | pendiente | — |
| MEM-01 | pendiente | — |
| STORAGE-01 | completado | Wrapper seguro para local/session storage con fallback en memoria sólo cuando persiste el fallo; Welcome/Preflight sobreviven SecurityError/cuota y una eliminación externa no resucita valores; tests UI + lint/build verdes. |
| I18N-01 | pendiente | — |
| TRAILER-01 | pendiente | — |
| STYLE-01 | pendiente | — |
| STYLE-02 | pendiente | — |
| TEST-01 | completado | 1.278 tests coleccionados desde raíz con `PYTHONPATH` eliminado |
| TEST-02 | completado | Harness actualizado para el contrato de duración H3 posterior a la auditoría; 4 tests verdes |
| CI-01 | completado | CI instala runtime CPU reproducible, colecciona 1.278 tests y ejecuta la suite completa: 1.270 pass + 8 skip en entorno limpio; 1.278 pass en el entorno de la app |
| CI-02 | completado | Node 20 fijado en CI; `npm ci`, 21 tests, lint con cero warnings, type-check y build verificados también con Node 20.20.2 |
| TEST-UI-01 | completado | RTL/jsdom cubre interacciones reales de recovery Director, Approve all, Play all y edición/aplicación de propuesta; 26 tests verdes en Node 20 |
| TEST-UI-02 | completado | Primer flujo migrado por commit: recuperación/identidad MiniMax prueba llamadas y estado runtime, sin leer ni partir TSX; 25 tests + lint verde |
| API-01 | pendiente | — |
| API-02 | pendiente | — |
| ARCH-01 | pendiente | — |
| ARCH-02 | pendiente | — |
| ARCH-03 | pendiente | — |
| OBS-01 | pendiente | — |
| PERF-01 | pendiente | — |
| DEPS-01 | pendiente | — |
| DEPS-02 | pendiente | — |
| DEPS-03 | pendiente | — |
| DOC-01 | pendiente | — |
| BRAND-01 | pendiente | Sustituir nombre visible Maestro por Loreframe Lab; conservar atribución del fork |
