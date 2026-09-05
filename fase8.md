# Fase 8 — Concurrencia y límites del workflow Wizard

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `fix/wizard-workflow-concurrency` → `main`.
- Dependencias: Fase 4 mezclada; puede adelantarse sólo sin conflicto de backend. No otro PR abierto en runtime Wizard.
- Archivos/módulos propios: wizardWorkflowRuntime.ts, wizard_workflows.py, contratos y tests; API mínima si procede.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Alto.

## Tareas de implementación

- [ ] F8.1 — Caracterizar dos clientes avanzando/respondiendo/cancelando el mismo workflow y eventos duplicados o fuera de orden.
- [ ] F8.2 — Sustituir resolución del mismo workflow por reloj updatedAt con precondiciones de revisión/paso y conflicto explícito o merge semántico acotado.
- [ ] F8.3 — Asegurar que la exclusión no dependa sólo de una Promise local al navegador; adquisición/validación de paso debe estar en la autoridad definida.
- [ ] F8.4 — Crear y validar comando antes del efecto cuando se migre un paso; preservar execution key y resultado durable.
- [ ] F8.5 — Versionar definiciones/checkpoints y describir qué ocurre con versiones antiguas o incompatibles.
- [ ] F8.6 — Definir claramente pasos server-side y pasos de presencia/UI. No migrar todo el motor a servidor en este PR.
- [ ] F8.7 — Probar workspace fuente durante conflictos, awaiting_input repetido, cancelar/completar y reapertura con eventos retenidos/resync.

## Pruebas y criterio de aceptación

Dos instancias de runtime, store temporal, CAS, fixtures de checkpoints antiguos y eventos canónicos.

Aceptación: Dos clientes no pierden cambios ni ejecutan dos veces un paso costoso; límites de ejecución sin navegador documentados.

## Punto de parada

Si requiere rediseñar todo el motor, parar con propuesta concreta; no ampliar silenciosamente este PR.

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

