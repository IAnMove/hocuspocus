# Fase 3 — GenerationRecord: autoridad y proyecciones coherentes

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `fix/generation-record-authority` → `main`.
- Dependencias: Fase 1 mezclada; revisar el código integrado de #138 y sus correcciones posteriores.
- Archivos/módulos propios: app/services/generation_record.py, ui/src/lib/generationRecord.ts, schema, tests y documentación de dominio.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Medio-alto.

## Tareas de implementación

- [ ] F3.1 — Definir relación entre command, workflow, run, generation attempt, task y asset. Un intento puede producir cero o varios assets; no duplicar Run sin justificar su relación.
- [ ] F3.2 — Compatibilizar Workspace como colección opcional con output_folder físico y recursos reutilizables. No fabricar pertenencia a una colección para satisfacer el schema.
- [ ] F3.3 — Elegir y documentar una autoridad de escritura. Preferir proyección de stores existentes; si un registro adicional resulta necesario, especificar propietario, revisión y reconciliación.
- [ ] F3.4 — Corregir equivalencia Python/TS en cancelación, estados desconocidos, retry, fechas y duración. Distinguir solicitud de cancelación de confirmación del worker.
- [ ] F3.5 — Preservar prompt original y efectivo, idiomas, entradas, transformaciones y tiempos de cola/inferencia/total al proyectar y actualizar manifests.
- [ ] F3.6 — Evitar que un patch con listas vacías o campos ausentes borre lineage existente. Definir semántica de merge y demostrar round-trip sin pérdida.
- [ ] F3.7 — Definir recuperación: volver a leer running no acredita worker activo. Representar interrupción o necesidad de reconciliación sin inventar éxito.
- [ ] F3.8 — Si se mantiene store escribible, probar rechazo de actualización obsoleta mediante revisión/CAS en el punto de escritura; un RLock por instancia y rename atómico no bastan.
- [ ] F3.9 — No conectar productores ni migrar físicamente archivos en este PR.

## Pruebas y criterio de aceptación

Corpus Python/TS de transiciones y proyecciones; dos escritores; datos legacy y corruptos; cero efectos sobre archivos existentes al leer.

Aceptación: Contrato compatible, autoridad única definida y actualizaciones sin pérdida de metadata ni sobrescritura obsoleta.

## Punto de parada

Mezclar antes de fase 4. No dar por resuelta la recuperación real: todavía falta ejecutar el protocolo.

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

