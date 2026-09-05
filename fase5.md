# Fase 5 — Finalización musical y recuperación sin navegador

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `fix/music-server-finalization` → `main`.
- Dependencias: Fase 4 mezclada; reservar launch y servicios de persistencia Story.
- Archivos/módulos propios: Servicio musical, persistencia Story/cues/candidatos, workers existentes y cableado mínimo en _launch_runtime.py.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Alto.

## Tareas de implementación

- [ ] F5.1 — Finalizar en servidor por IDs reservados: intento → task → bytes → manifest → candidato del cue correcto.
- [ ] F5.2 — Separar producción de bytes de publicación completa. Si falla metadata, conservar el medio y registrar reparación pendiente.
- [ ] F5.3 — Hacer finalización repetible sin duplicar candidato ni asset; persistir progreso de publicación para reconciliar fallos.
- [ ] F5.4 — Medir duración del archivo y guardarla separada de la solicitada. Mantener versión visible independiente del ID.
- [ ] F5.5 — No cambiar automáticamente una selección que el usuario modificó mientras esperaba. Aplicar revisión/precondición o política explícita de selección.
- [ ] F5.6 — Implementar reconciliación de trabajo interrumpido sin regeneración automática costosa: archivo ya producido, metadata pendiente, candidato pendiente o worker ausente.
- [ ] F5.7 — Probar caída después de cada etapa, cancelación contra finalización y dos generaciones del mismo cue. Conservar cambios concurrentes de otros campos.
- [ ] F5.8 — Demostrar con API real y worker falso que terminar sin navegador crea el candidato correcto y que recargar sólo rehidrata.

## Pruebas y criterio de aceptación

Integración sin modelos, persistencia real temporal, inyección de fallos, repetición de finalización y cancelación concurrente.

Aceptación: Cerrar el navegador no pierde relaciones; recuperar no duplica ni adopta otro audio.

## Punto de parada

Merge obligatorio antes del cliente de fase 7 o de extraer rutas. Smoke GPU pendiente se registra, no se ejecuta automáticamente.

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

