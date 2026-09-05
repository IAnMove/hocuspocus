# Fase 9 — Extracción mecánica del router Story Music

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `refactor/story-music-router` → `main`.
- Dependencias: Fase 5 mezclada y todo cableado musical de fase 6 que toque launch integrado.
- Archivos/módulos propios: app/_launch_runtime.py, nuevo router Story Music y servicio asociado; fixtures de arquitectura revisadas.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Medio.

## Tareas de implementación

- [ ] F9.1 — Inventariar las cuatro rutas stories/music-candidates y sus dependencias reales, además de la compatibilidad con el protocolo nuevo.
- [ ] F9.2 — Congelar tests de comportamiento, método/path/status/schema y orden de montaje.
- [ ] F9.3 — Extraer router y servicio con dependencias explícitas, sin importar launch desde el servicio.
- [ ] F9.4 — Conservar compatibilidad y ordinals; no incluir trim/mix/analyze, otro dominio ni cambios funcionales.
- [ ] F9.5 — Revisar cada cambio de fixture: regenerarla no demuestra corrección.
- [ ] F9.6 — Verificar muro WanGP, cancelación, consulta y errores con dependencias falsas.

## Pruebas y criterio de aceptación

Architecture contracts, route table y pruebas de dominio/API sin modelos.

Aceptación: Mismo comportamiento público; launch reduce responsabilidad y el dominio se importa aisladamente.

## Punto de parada

Merge antes de cualquier otro router en launch. Routers siguientes requieren paquete propio.

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

