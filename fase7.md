# Fase 7 — Cliente asíncrono y selección recuperable

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `fix/story-music-rehydration` → `main`.
- Dependencias: Fases 5 y 6 mezcladas. Reservar StoryLabPanel y API UI.
- Archivos/módulos propios: ui/src/api/director.ts y stories.ts, StoryLabPanel/controlador musical, candidatos y tests UI/E2E.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Alto.

## Tareas de implementación

- [ ] F7.1 — Enviar spec e IDs; consumir aceptación inmediata y seguir task/attempt exacto. No crear candidato sólo al recibir una respuesta final.
- [ ] F7.2 — Rehidratar candidatos del servidor al abrir proyecto, reconectar y recargar. Conservar task_id, asset_id y duración medida.
- [ ] F7.3 — Capturar proyecto/carpeta/revisión al iniciar; una respuesta tardía no debe escribir en el contexto ahora seleccionado.
- [ ] F7.4 — Mostrar valores persistidos y estado real: preparado, aceptado, esperando recurso, ejecutando, cancelación solicitada y terminal.
- [ ] F7.5 — Impedir duplicados con el protocolo servidor; disabled/busy del botón es sólo una ayuda visual.
- [ ] F7.6 — Conservar edición y selección del usuario durante esperas; abrir el resultado por ID y no por título/filename.
- [ ] F7.7 — Probar formulario visible, doble pestaña, respuesta perdida, cambio de proyecto, recarga y audio elegido para Director.

## Pruebas y criterio de aceptación

Adapters sin React, tests de componentes y navegador con API/worker simulado. No cargar medios generados reales.

Aceptación: La UI refleja estado durable y las generaciones sobreviven a desconexión sin duplicación o selección equivocada.

## Punto de parada

Parada de aceptación de la base musical: merge y proponer smoke manual local antes de funcionalidades nuevas.

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

