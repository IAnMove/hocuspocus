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
| TASK-05 | completado | Retención configurable por edad/cantidad conserva activos y terminal más reciente, mantiene tombstones, persiste frontera de cursor y emite `resync_required`; dry-run, reinicio y continuación desde cursor reciente cubiertos. |
| TASK-06 | completado | Versión de esquema idempotente; CLI dry-run sobre copia temporal, backup/restore validados y compactación sólo con backend detenido. Dry-run real: 266.469.376 B, 557.376 eventos, retiraría 547.376/0 tareas y `source_unchanged=true`; 44 tests focalizados. |
| TASK-07 | completado | Stream LLM visible como tail normalizado de 400 caracteres sólo en snapshot; 500 actualizaciones no añaden eventos ni mueven `updated_at`, y terminal limpia preview conservando transición durable; contrato documentado. |
| DIR-01 | completado | Helper compartido mapea antes de filtrar, conserva índices originales/explicitos y prioriza `shotId`; huecos `[∅,b,∅,d] => [1,3]`, null y plan reordenado cubiertos; 49 tests UI + lint/build verdes. |
| DIR-02 | completado | `DirectorClipImage.file` es nullable; previews recuperadas resuelven filename backend sin `createObjectURL(null)` y los blobs locales se revocan al reemplazar/desmontar; tests UI + lint/build verdes. |
| PLAN-01 | completado | Planificación determinista en lotes máximos de 8; schema restringido a índices del lote, merge ordenado sin overwrite, reparación compacta sólo de huecos y fallback individual. Fake que trunca >8 produce 41/41 únicos en 6 llamadas; 31 tests focalizados verdes. |
| PLAN-02 | completado | Job JSON atómico por workspace persiste índices/planes tras cada lote, lote activo, llamadas y tokens; status/list/resume públicos y claim único. Reinicio simulado tras lote 3 recupera 1–24 y sólo llama 25–41; 84 tests backend + 68 UI/lint/build verdes. |
| PLAN-03 | completado | Fallo durable devuelve contrato estructurado sin prompts con job, lotes, completos/faltantes, llamadas/tokens y acción Resume; tarjeta recuperable reanuda sólo huecos y bloquea imágenes hasta respuesta completa. Fallo repetido + éxito cubiertos; 36 tests backend, 78 UI, lint/build verdes. |
| DIR-03 | completado | Fallo de lista/detalle conserva pipeline previa, muestra alerta accesible y destino de Retry; nueva carga limpia error stale y Retry exitoso selecciona el destino. Prueba RTL funcional + suite/lint/build verdes. |
| SER-01 | pendiente | — |
| SER-02 | pendiente | — |
| SER-UI-01 | pendiente | — |
| SER-UI-02 | completado | Cambio de `episode.id` pausa el último reproductor y reinicia error, decisiones, aprobación, cursor/Play all, foco, preview, edición, seed/busy, assembly y subvista; el efecto de playback ignora el render transitorio stale. Prueba E1→E2 funcional + 80 UI, lint/build verdes. |
| DUR-01 | pendiente | Revalidar contra `c2da86c` |
| SER-UI-03 | completado | Selección se poda contra `selectableShotIds`; aprobado queda desmarcado y con control deshabilitado/nombre explícito, contador y Render selected caen a cero, y desaprobar no resucita selección stale. Prueba RTL E1 seleccionada→aprobada→desaprobada + 81 UI/lint/build verdes. |
| SER-03 | pendiente | — |
| STORY-01 | pendiente | — |
| STORY-02 | completado | Resolver puro compartido conserva MiniMax, OpenAI, DeepSeek, OpenAI-compatible y Maestro con provider/model/base URL coherentes en UI, generación y reanudación; tabla de casos automatizada + lint/build verdes. |
| STORY-03 | completado | Merge por `updatedAt` conserva exclusivos y versión más nueva; empate divergente no autosalva y ofrece Keep local/Use remote con timestamp monotónico. Primer load remoto no mezcla fallback sintético. Casos puros + alerta/acciones DOM + suite/lint/build verdes. |
| STORY-04 | pendiente | — |
| UI-WS-01 | completado | Epochs y AbortController aíslan outputs/metadata por workspace, invalidan listas y mutaciones tardías y pasan workspace explícito en todos los consumidores; 5 regresiones diferidas, 44 tests UI, lint y build verdes. |
| UI-SEARCH-01 | completado | Input controlado; debounce cancelado al cerrar/desmontar y store limpiado sin búsqueda/carga fantasma; 35 tests UI + lint/build verdes |
| UI-GEN-01 | completado | `deriveIsGenerating` es la única derivación del flag y sólo acepta queued/waiting/running/cancelling; todas las rutas migradas; historial terminal => false; 37 tests UI + lint/build verdes |
| EDITOR-01 | pendiente | Revalidar contra `b6c741a` y `68aa157` |
| EDITOR-02 | pendiente | — |
| EDITOR-03 | completado | Normalizador único en carga y export exige fuente + duración finita, repara IDs únicos, metadata numérica, trims ordenados/acotados, volumen y enums, y descarta irreparables con aviso visible. Tabla NaN/strings/invertidos/ausentes/duplicados + 84 UI/lint/build verdes. |
| PLAY-01 | completado | Cursor de reproducción por ID estable en Series y Stories: reordenar o reemplazar un intento conserva el clip activo y eliminarlo detiene Play all explícitamente; 39 tests UI, lint y build verdes. |
| POLL-01 | pendiente | — |
| TIMELINE-01 | completado | Poll serial de Story timeline se detiene en estados terminales; Refresh manual recupera/reanuda y un éxito limpia el error; 33 tests UI + lint/build verdes |
| ACT-01 | completado | Fallos cancel/resume/dismiss quedan por task ID en bloque `aria-live`, preservan la tarea y ofrecen Retry; éxito limpia el error; 34 tests UI + lint/build verdes |
| UPLOAD-01 | completado | Ingesta en chunks de 1 MiB con límite acumulado y 413; publicación atómica, cleanup en error/cancelación, concurrencia acotada y transcode cancel-safe; 4 tests verdes |
| CANCEL-01 | completado | Token por job/workspace cierra únicamente la respuesta HTTP activa en streaming local/OpenAI-compatible/Anthropic; fallback informa safe boundary, stages se preservan y tokens se limpian; 115 tests focalizados verdes. |
| RES-01 | completado | Ticket monotónico + Condition por lane; sólo la cabeza adquiere, cancelación elimina/despierta; FIFO A/B/C validado 100 veces y B cancelado deja A/C; 17 tests verdes |
| A11Y-01 | completado | `ModalShell` aporta nombre, `role=dialog`, `aria-modal`, foco inicial/restaurado, Escape y trap Tab/Shift+Tab; migrados Director Dashboard y picker del editor; tests RTL + lint/build verdes. |
| A11Y-02 | pendiente | — |
| RESP-01 | completado | Series Lab usa selector horizontal y layout full-width bajo `md`, rail vertical en desktop, header con wrap y contenedor principal `min-h-0`; prueba RTL monta y consulta la estructura accesible; lint/build verdes. |
| RESP-02 | completado | Bajo `md`, Story Lab usa navegación horizontal desplazable con indicador visible y contenido a ancho completo; escritorio conserva rail vertical y notas. Prueba RTL real + 66 tests UI, lint/build verdes. |
| RESP-03 | completado | Video Editor elimina altura mínima rígida, toolbar hace wrap y el cuerpo móvil desplaza inspector/timeline sin alterar grid desktop; regiones accesibles exponen Import, Export y trim. Prueba RTL responsive + lint/build verdes. |
| MEM-01 | pendiente | — |
| STORAGE-01 | completado | Wrapper seguro para local/session storage con fallback en memoria sólo cuando persiste el fallo; Welcome/Preflight sobreviven SecurityError/cuota y una eliminación externa no resucita valores; tests UI + lint/build verdes. |
| I18N-01 | completado | Formatter central basado en locale de aplicación para timestamps de Media/Activity y glosario EN/ES de acciones; snapshots deterministas es-ES/en-US con UTC, lint y build verdes. |
| TRAILER-01 | completado | Reset por proyecto separado de la sincronización de defaults; tipo/duración siguen al proyecto hasta la primera edición manual y después se preservan; tests de ambos estados + lint/build verdes. |
| STYLE-01 | pendiente | — |
| STYLE-02 | pendiente | — |
| TEST-01 | completado | 1.278 tests coleccionados desde raíz con `PYTHONPATH` eliminado |
| TEST-02 | completado | Harness actualizado para el contrato de duración H3 posterior a la auditoría; 4 tests verdes |
| CI-01 | completado | CI instala runtime CPU reproducible, colecciona 1.278 tests y ejecuta la suite completa: 1.270 pass + 8 skip en entorno limpio; 1.278 pass en el entorno de la app |
| CI-02 | completado | Node 20 fijado en CI; `npm ci`, 21 tests, lint con cero warnings, type-check y build verificados también con Node 20.20.2 |
| TEST-UI-01 | completado | RTL/jsdom cubre interacciones reales de recovery Director, Approve all, Play all y edición/aplicación de propuesta; 26 tests verdes en Node 20 |
| TEST-UI-02 | completado | Primer flujo migrado por commit: recuperación/identidad MiniMax prueba llamadas y estado runtime, sin leer ni partir TSX; 25 tests + lint verde |
| API-01 | pendiente | — |
| API-02 | completado | Request/progress/response de Director V2 viven en un único módulo de contratos; guard runtime rechaza drift y reconoce el `comic_movie` canónico del backend además del selector UI. Test TypeScript de consumidores + suite/lint/build verdes. |
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
