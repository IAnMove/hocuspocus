# Fase 6 — Spec musical y catálogo compartido por modelo

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `refactor/music-model-contract` → `main`.
- Dependencias: Fases 2 y 4 mezcladas. Evitar PR concurrente de fase 5 si comparte launch, servicio o contrato; ejecutar después en ese caso.
- Archivos/módulos propios: Servicios/guías musicales, musicModel.ts, catálogo y adapters, router LLM si hace falta; evitar grandes paneles y useStore.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Medio.

## Tareas de implementación

- [ ] F6.1 — Crear MusicGenerationSpec/Result y guía declarativa reutilizando LanguageIntent y contratos existentes.
- [ ] F6.2 — Distinguir modelo conocido, descargable, incompleto, instalado, compatible, configurado y disponible. Revisar assets obligatorios sin descargar pesos.
- [ ] F6.3 — Declarar modos, duraciones, límites, formato de caption/letra y parámetros por ACE-Step, MiniMax remoto y Music3 local.
- [ ] F6.4 — Compilar spec a solicitud de cada backend; evitar que reglas remotas de 300 caracteres trunquen captions estructurados locales.
- [ ] F6.5 — Aplicar guard de fase 2 en la frontera servidor antes de encolar; mostrar errores estructurados y propuestas sin modificar el original.
- [ ] F6.6 — Conservar modelo pedido; si no está disponible explicar causa. Prohibir fallback silencioso a ACE y respetar enabled/selección explícita.
- [ ] F6.7 — Congelar prompt efectivo, configuración, revisión de guía/modelo e idiomas en la solicitud durable.
- [ ] F6.8 — Probar que UI, Story y Wizard producen specs equivalentes mediante puertos; no introducir templates o portadas.

## Pruebas y criterio de aceptación

Fixtures por proveedor, límites, instalación parcial, modelo deshabilitado, idiomas y captions multilínea; ningún proveedor real.

Aceptación: Un único contrato decide disponibilidad y compilación; validación lingüística activa antes de efectos.

## Punto de parada

Mezclar antes de fase 7; no ampliar el catálogo a variantes sin adapter probado.

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

