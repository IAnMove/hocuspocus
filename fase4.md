# Fase 4 — Envío musical idempotente antes de ejecutar

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `feat/music-submission-contract` → `main`.
- Dependencias: Fase 3 mezclada. Ningún PR abierto puede poseer _launch_runtime.py.
- Archivos/módulos propios: Nuevo servicio musical estrecho en app/services, API musical existente, tests de contrato. Cableado mínimo en app/_launch_runtime.py; no extraer router aún.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Alto.

## Tareas de implementación

- [ ] F4.1 — Inventariar caminos local/ACE/Music3 y remoto; conservar endpoints y clientes existentes mediante compatibilidad explícita.
- [ ] F4.2 — Definir solicitud con command/idempotency key, proyecto/cue, carpeta, colección opcional, revisión y snapshot inmutable del spec.
- [ ] F4.3 — Reservar y persistir IDs de intento, tarea y candidato antes de aceptar ejecución. Verificar existencia y pertenencia del destino en servidor.
- [ ] F4.4 — Persistir deduplicación atómica: misma clave y payload devuelve el mismo resultado; clave reutilizada con payload distinto devuelve conflicto.
- [ ] F4.5 — Distinguir retransmisión de transporte de nueva versión creativa y retry explícito. Estos últimos generan nuevos intentos con lineage.
- [ ] F4.6 — Responder 202 con referencias y estado consultable sin esperar a inferencia; mantener una vía de compatibilidad documentada.
- [ ] F4.7 — Usar TaskRegistry y scheduler existentes. No introducir infraestructura distribuida, GPU ni descarga de modelos para probarlo.
- [ ] F4.8 — Probar fallo entre reserva y arranque, doble petición concurrente, respuesta perdida y referencia a proyecto inexistente. Nunca resolver por título si ya existe ID.

## Pruebas y criterio de aceptación

FastAPI/servicio real con worker falso y almacén temporal; una sola ejecución por clave; ruta y schemas compatibles.

Aceptación: Toda aceptación queda durable y se puede consultar aunque se pierda la respuesta HTTP.

## Punto de parada

Parar para merge antes de fase 5. No abrir simultáneamente otra modificación de launch.

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

