# Grok: empieza aquí (producción de videoclips, 2026-09-30)

Instrucción completa para Grok. Léela entera y haz el trabajo de principio a fin. Claude ya hizo el bloque A (tratamiento y
modo trailer, PR #668, mezclado) y revisará cada PR tuyo.

## Lee primero (están en origin/development; si no los ves, `git fetch`)

1. `AGENTS.md`: cumple su revisión antes de editar y antes de terminar.
2. `docs/development/PRODUCTION_WORK_BOARD.md`: el tablero con bloques, dueños, ramas y archivos exclusivos. Manda sobre todo lo demás.
3. `docs/development/GROK_PRODUCTION_BLOCKS_2026-09-30.md`: el detalle de tus bloques (0, D, C, B), con defecto, diseño, archivos, pruebas y
   medidas de aceptación.
4. `docs/agents/VIDEO_PRODUCTION_RUNBOOK.md`, `docs/development/PRODUCTION_QUALITY_ANALYSIS_2026-09-29.md` y
   `docs/development/GROK_PRODUCTION_NEXT_2026-09-29.md`: contexto y numeración de los puntos.

## Tu trabajo, en este orden

- **Bloque 0**: refactor de `music_production.py` (puntos 17-20). Solo movimiento de código, sin cambiar comportamiento. Aterriza primero.
- **Bloque D** (prioridad del usuario): revisar el vídeo plano a plano y poder pedir cambios a un LLM, al asistente de la app o a mano,
  solo en ese plano. Incluye rehacer un plano desde el fotograma con prompts nuevos, estado aprobado/pide cambios, bloqueo de ediciones
  manuales, historial y deshacer, modo "Revisar" en la UI, y que `production.publish` exija revisión. Puedes empezar ya por los
  comandos y la UI (no tocan `music_production.py` salvo ganchos de ≤ 5 líneas tras el bloque 0).
- **Bloque C**: operativa (12 exportar escenas en paralelo, 13 progreso y ETA, 14 sondeo largo con `until`, 15 medir la memoria de GPU
  antes de construir nada, 16 estimación con datos propios, 29 contabilidad honesta). 14 y 16 pueden ir ya; el resto tras el bloque 0.
- **Bloque B**: calidad medida (25 resolución y FlashVSR, 26 fluidez de los tirones, 27 veredictos por niveles, 30 fases de H3).

## Reglas

- Antes de cada bloque: `git fetch`, `gh pr list` y `git grep` de las palabras clave del punto; otros agentes (Cursor, Sol, Claude) también
  abren PR. No dupliques trabajo que ya tenga dueño. Si dos bloques chocan en un archivo, sigue la tabla de solapes del tablero.
- Worktree propio desde `origin/development`. No trabajes en el checkout compartido `/mnt/extras/pinokio/api/hocuspocus-development`
  (está atrasado y tiene archivos sin seguimiento). No toques launchers ni 42003. Usa tu instancia 42021; no uses 42017 (es de Claude).
- Un PR por bloque (o por punto si el bloque es grande), abierto como borrador el primer día con la rama del tablero: esa es tu
  reclamación. Actualiza la fila de tu bloque en el tablero dentro del mismo PR.
- `music_production.py` es zona restringida: solo ganchos de ≤ 5 líneas hasta que aterrice el bloque 0.
- Cada PR: tests dirigidos (registrados en `scripts/ci_test_groups.json`), `cd ui && npm run check` si tocas UI,
  `BASE_REF=origin/development scripts/check_code_health_pr_base.sh` (el ratchet no puede empeorar),
  `python3 scripts/check_documentation_links.py`, y una sección en el runbook. Comprueba la CI del HEAD del PR y arregla lo que falle.
  Si un test E2E de Windows falla por algo ajeno a tu cambio, dilo y vuelve a lanzarlo empujando un commit vacío.
- No mezcles tus PR: los revisa Claude contra tu fila del tablero.
- GPU: `nvidia-smi` antes de cada prueba; si otro proceso usa más de 2 GB, espera. Solo generas lo que pide la prueba de aceptación real
  de cada bloque, y solo en tu instancia. Datos pesados en `/home/ina/grok-data` o `/mnt/outputs`; `/mnt/extras` está justo de espacio.
- Para las producciones del usuario se prefiere Qwen Image 2.1 en todas las imágenes. Un "ok" técnico no es aprobación artística.
- Tokens y tiempos: solo cifras medidas. Los tokens del LLM los mide el cliente; los bytes de respuestas MCP NO son tokens y no se convierten.
- No cambies el formato de `production.json` ni de `shots.json` salvo añadir campos. No borres tomas.
- Material real de prueba: workspace `gremlins-devday-v2-20260929`, producción `voices-v2`
  (en `/mnt/outputs/hocuspocus-worktrees/claude-pop/app/outputs/`). Cópiala a tu workspace; no edites la original.

## Entrega de cada PR

Enlace, defecto concreto que resuelve, archivos tocados, pruebas con sus números, medidas reales donde el bloque las pide, conflictos
evitados, y qué sigue pendiente de tu bloque. Cuando termines un bloque pasa al siguiente sin esperar; si algo te bloquea (un archivo
ocupado, una decisión que es del usuario, falta de GPU), cambia a otro punto independiente y déjalo anotado. Al acabar los cuatro
bloques, da un resumen final con lo hecho, lo medido y lo que quede.
