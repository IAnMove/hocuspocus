# Cola vigente de refactor

Base verificada: `origin/development` `e44ee001`, 2026-09-21.
Lee primero [CURRENT_WORK](CURRENT_WORK.md): integrado, en curso y límites de QA.
No uses la ola F1–F12 como cola actual; es distinta de Labs L0–L12.

## Reservas y base

- Trabajo ordinario desde `origin/development`, PR hacia `development`.
  `main` es publicación: [BRANCHING](BRANCHING.md).
- Reconsultar PR y diff local antes de reservar. Máximo un PR pendiente por
  `_launch_runtime.py`, `useStore.ts`, `agentActions.ts`, StoryLabPanel o runtime
  Director/Wizard. No superponer cambios de otros agentes.
- Conservar prompts, IDs, provenance y fachadas. No mover código solo por reducir
  líneas. PR cohesivos con contratos y pruebas; no uno por propiedad.
- Revisión/merge según [AGENT_QA_POLICY](AGENT_QA_POLICY.md) y autorización vigente
  del usuario. Esta cola no concede permisos nuevos ni restablece excepciones de
  handoffs antiguos. No activar auto-merge ni protecciones por limpiar documentos.

## Pendientes elegibles: comprobar antes de reservar

| Paquete | Propiedad prevista | Dependencia / alcance |
|---|---|---|
| Cierre de QA Labs | Tests UI/Wizard, browser y pruebas reales acotadas | L0–L12 y attemptId (#201) integrados. Quedan móvil real, equivalencia amplia y GPU |
| Proyección visible de intentos | Activity / Library sobre GenerationRecord | Story Music ya proyecta (#432). Elegir **otro** productor concreto; no segundo scheduler |
| Director ciclo de vida | Dependencias tipadas / PipelineRuntime | Locks (#427) y reconcile (#431) extraídos. Un solo contrato por PR |
| H3 30 s real | Evidencia GPU del pase 719 | Contrato [H3_EXTENDED_DURATION](H3_EXTENDED_DURATION.md). No cambiar el catálogo 345 |

## No volver a poner en cola

Finalización musical del servidor, rehidratación, contrato de idioma/proyección,
I/O Director, refactor H3, Labs L0–L12, router Story Music (#426), sesión Story
(#428), slice musical Studio (#430), locks/reconcile Director (#427, #431),
Wizard concurrente (#429), GenerationRecord de canción (#432), policy H3 desde
Studio (#433) y routers de librería (#437, #438, #441) ya tienen entregas
integradas. Ver pruebas y límites en [CURRENT_WORK](CURRENT_WORK.md); integrado
no significa QA audiovisual exhaustiva. Wizard 409 y Series→Comics provenance
tampoco son tareas nuevas (#122, #124). No restaurar el viejo backlog post-#120.

## Documentación histórica

[Archivo de la ola anterior](../archive/2026-09-06/architecture-wave/SLICE_QUEUE.md).
Consultar solo para recuperar una decisión o requisito concreto, nunca para elegir
base, permisos, PR pendientes o la próxima tarea.
