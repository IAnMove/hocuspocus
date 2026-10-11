# Escenarios 3D: tablero

Base inicial: `origin/development` `0270dbda`. Worktree aislado `astra-sets`.
Fase 1: tests nuevos simulados por bloque. CI completa y GPU: fase 2.

| Bloque | Rama | PR | Estado | Archivos (exclusivos) |
|---|---|---|---|---|
| A4 | feat/set-molds-format | #969 | Z1 local OK: 6677 Python + 55 cancelación; UI; ratchet; docs | set_molds.py, set_commands.py, roomSet.ts, roomSetRuntime.ts, set_defaults.json |
| A1 | feat/mcp-remove-background | #970 | Z1 local OK: 6682 Python + 55 cancelación; UI; ratchet; docs | image_remove_background.py |
| A2 | feat/prop-library | #971 | Z1 local OK: 6685 Python + 55 cancelación; UI; ratchet; docs | prop_library.py |
| A3 | feat/scene3d-add-items | #972 | Z1 local OK: 6691 Python + 12 escala/GLB/editor; UI; ratchet; docs | scene3d_items.py |
| A5 | feat/set-skins | #973 | Z1 local OK: 6697 Python; UI; ratchet; docs | set_skins.py |
| A6 | feat/set-molds-v1 | #974 | Z1 local OK: 6713 Python; UI; ratchet; docs | set_molds/*.json |
| A7 | feat/sets-room-integration | #975 | Z1 local OK: 6720 Python + 20 contrato/catálogo; UI; ratchet; docs | production_rooms.py, series_sets.py |
| A8 | docs/sets-agent-guide | #976 | Z1 local OK: 6721 Python + 27 catálogo/Qwen; UI; ratchet; docs | guías de agentes |
| Z1 | ramas anteriores | #969–#976 | Local completo; CI de las correcciones finales en curso | comprobaciones completas |
| Z2 | docs/sets-trial | #977 | Completado: 70 imágenes, croma190, seam_error1.1807, caché sin GPU | defaults medidos e informe |
| Z3 | ramas anteriores | #969–#977 | Completado; correcciones y evidencias reales | evidencias por bloque |
| Z4 | docs/sets-acceptance | pendiente | pendiente | aceptación completa |

Los pequeños ganchos, el registro de tests y este tablero son compartidos secuencialmente por la pila.
Coste fase 1: 0 tokens LLM externos; 0 generaciones; tokens Codex N/A.
