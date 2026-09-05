# Fase 12 — Trazabilidad visible y cierre de la base

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `feat/generation-traceability-views` → `main`.
- Dependencias: Fases 3 y 7 mezcladas; contratos de fase 8 integrados si la UI consume sus cambios.
- Archivos/módulos propios: ProjectsPanel, AssetsPanel, vistas existentes Productions/Runs, ActivityFooter y previews. Elegir una vertical musical; no rediseñar toda la navegación.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Medio.

## Tareas de implementación

- [ ] F12.1 — Mostrar para una generación musical sus relaciones proyecto/cue/candidato/attempt/task/asset y abrir cada entidad por ID exacto.
- [ ] F12.2 — Consumir estados canónicos: Activity no debe poseer otro ciclo de vida. Conservar orden por evento real y resync.
- [ ] F12.3 — Mostrar prompt original/efectivo, modelo/proveedor, idiomas y tiempos separados; datos legacy ausentes se señalan sin inventarlos.
- [ ] F12.4 — Distinguir temporales internos y assets finales sin perder lineage; no mover ni borrar archivos al listar.
- [ ] F12.5 — Probar previews/selección estable tras recarga y que el input enviado corresponde al asset seleccionado, incluidas respuestas tardías.
- [ ] F12.6 — Verificar formulario Wizard visible, edición manual y reduced motion; no expandir partículas ni coreografía.
- [ ] F12.7 — Preparar checklist manual con SHA para ACE, Music3, cierre de navegador, cancelación, canción→videoclip, imagen/referencia y Tools afectados. No ejecutarlo automáticamente.
- [ ] F12.8 — Registrar pendientes de producto fuera de esta ola: templates, portadas, RhythmMap persistente, primer lifecycle PipelineRuntime, parser/reconciliador y adopciones selectivas de Maestro. Cada uno requiere un nuevo paquete y no queda autorizado por este cierre.

## Pruebas y criterio de aceptación

Fixtures de lineage/legacy/temporales, UI/E2E simulado, orden Activity y selección por ID.

Aceptación: Usuario puede explicar de dónde salió el resultado y recuperar su trabajo; toda validación real pendiente queda explícita.

## Punto de parada

Fin de esta ola. Entregar PRs, matriz de evidencia y propuesta de smoke local; esperar merges/validación antes de templates, portadas o refactors adicionales.

## Protocolo obligatorio para cada fase

- [ ] Leer fase1.md y esta fase; comprobar dependencias mezcladas en main remoto. Si el trabajo ya existe, verificarlo y registrar evidencia en lugar de duplicarlo.
- [ ] Inspeccionar cambios locales y logs relevantes al diagnosticar. Trabajar en rama/worktree aislado desde el main actualizado; preservar WIP, stashes y archivos del usuario.
- [ ] Revisar PRs abiertos y sus archivos: máximo un PR por hotspot (_launch_runtime.py, useStore.ts, agentActions.ts, StoryLabPanel o runtime Director/Wizard). No usar ramas apiladas en esta ola.
- [ ] Registrar base SHA, archivos propios/prohibidos y pruebas antes de editar. Aplicar AGENTS.md; no tocar launchers ni código vendor/WanGP salvo paquete posterior explícito.
- [ ] Marcar [x] sólo tras cumplir la tarea y añadir evidencia breve: archivo, comando/resultado o URL/SHA. Un plan o test escrito sin ejecutar no acredita validación.
- [ ] Ejecutar tests focalizados y validación segura pertinente, lint/tipos/build si cambia UI, arquitectura si corresponde y ratchet contra base exacta. No refrescar baseline para ocultar regresiones.
- [ ] Revisar diff y archivos a añadir explícitamente. Nunca incorporar pesos, outputs, secretos, caches, entornos ni comunicaciones. No usar git add indiscriminado.
- [ ] Crear commit y PR hacia main, o actualizar el PR existente correspondiente. Descripción: problema, comportamiento final, alcance, pruebas, riesgos y limitaciones.
- [ ] Esperar CI del último head; resolver fallos atribuibles al cambio. Leer comentarios de Cursor, contrastarlos y corregir con tests. Repetir checks tras fixes; revisión de un commit anterior no acredita el actual.
- [ ] Entregar URL, head/base SHA y estado separado de implementación, CI, Cursor, merge y smoke. No hacer merge ni activar auto-merge.
- [ ] Continuar otra fase sólo si sus dependencias están mezcladas y no comparte hotspot/contrato en cambio. Si no queda trabajo independiente elegible, parar y pedir que se mezclen los PRs concretos.

## Registro de entrega

- Base SHA:
- Rama / PR:
- Commit implementado:
- Tests ejecutados y resultado:
- CI del head:
- Revisión Cursor (SHA, hallazgos pendientes):
- Merge en main (lo completa quien lo verifique):
- Generación real: NO EJECUTADA salvo evidencia manual explícita.
- Bloqueos / siguiente fase elegible:

Los checkboxes describen trabajo; los estados de entrega son independientes. No marcar una fase globalmente terminada sólo por abrir su PR. Tests reales requieren autorización manual separada. No son un requisito para abrir el PR y nunca se ejecutan en CI.

