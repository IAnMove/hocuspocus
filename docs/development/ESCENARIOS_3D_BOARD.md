# Escenarios 3D: tablero

Base inicial: `origin/development` `0270dbda`. Worktree aislado `astra-sets`.
Fase 1: tests nuevos simulados por bloque. CI completa y GPU: fase 2.

| Bloque | Rama | PR | Estado | Archivos (exclusivos) |
|---|---|---|---|---|
| A4 | feat/set-molds-format | #969 | Z1 local OK: 6677 Python + 55 cancelación; UI; ratchet; docs | set_molds.py, set_commands.py, roomSet.ts, roomSetRuntime.ts, set_defaults.json |
| A1 | feat/mcp-remove-background | pendiente | pendiente | image_remove_background.py |
| A2 | feat/prop-library | pendiente | pendiente | prop_library.py |
| A3 | feat/scene3d-add-items | pendiente | pendiente | scene3d_items.py |
| A5 | feat/set-skins | pendiente | pendiente | set_skins.py |
| A6 | feat/set-molds-v1 | pendiente | pendiente | set_molds/*.json |
| A7 | feat/sets-room-integration | pendiente | pendiente | production_rooms.py, series_sets.py |
| A8 | docs/sets-agent-guide | pendiente | pendiente | guías de agentes |
| Z1 | ramas anteriores | pendiente | pendiente | comprobaciones completas |
| Z2 | docs/sets-trial | pendiente | pendiente | defaults medidos e informe |
| Z3 | ramas anteriores | pendiente | pendiente | evidencias por bloque |
| Z4 | docs/sets-acceptance | pendiente | pendiente | aceptación completa |

Los pequeños ganchos, el registro de tests y este tablero son compartidos secuencialmente por la pila.
Coste fase 1: 0 tokens LLM externos; 0 generaciones; tokens Codex N/A.
