# Fase 2 — Idiomas y texto literal sin reparación destructiva

Plan de ejecución basado en la auditoría del 5 de septiembre de 2026. Verificar el código vigente antes de aplicar hallazgos históricos.

- PR propuesto: `fix/lyrics-language-contract` → `main`.
- Dependencias: Fase 1 mezclada. Revisar y continuar #139 si cubre este trabajo; #137 puede estar ya mezclado.
- Archivos/módulos propios: app/services/lyrics_language.py, ui/src/lib/lyricsLanguageGuard.ts, sus tests y docs/development/LYRICS_LANGUAGE.md.
- Prohibido: cualquier otro hotspot sin coordinación, launchers, pesos y outputs.
- Riesgo: Medio.

## Tareas de implementación

- [ ] F2.1 — Reproducir con tests puros los defectos que sigan presentes: letra vocal vacía; inglés solicitado como francés; literal obligatorio ausente; reparación de texto chino a vacío; Estonian reconocido como español.
- [ ] F2.2 — Separar resultado válido, inválido y no evaluable. Un idioma sin soporte no puede presentarse como validado.
- [ ] F2.3 — Normalizar etiquetas/alias con reglas explícitas; no usar prefijos libres como startsWith('es'). Conservar variantes regionales y acento cuando sean relevantes.
- [ ] F2.4 — Validar presencia exacta de todos los fragmentos protegidos, incluidos multilineales, sin normalizar espacios, puntuación o Unicode del texto original.
- [ ] F2.5 — Eliminar reparación destructiva por defecto. Devolver propuesta y diferencias; preservar siempre original. No permitir que eliminar contenido produzca una letra vocal válida vacía.
- [ ] F2.6 — Crear un corpus compartido ejecutado por Python y TypeScript: idiomas mixtos autorizados, nombres propios, etiquetas [Verse], letra instrumental, citas solapadas y caracteres no latinos.
- [ ] F2.7 — Documentar que la heurística valida texto, no lo cantado. Mantener separados UI, conversación, contenido, voz y prompt técnico. No cablear todavía a launch ni tocar StoryLabPanel.

## Pruebas y criterio de aceptación

Tests Python/TS del corpus, compatibilidad con songLanguage, validación segura del repositorio.

Aceptación: Ningún caso desconocido o vacío da un falso éxito; ninguna reparación borra silenciosamente texto del usuario.

## Punto de parada

Un PR de librería corregida no significa protección activa de Generate. El cableado pertenece a fase 6.

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

