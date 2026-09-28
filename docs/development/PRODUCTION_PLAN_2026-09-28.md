# Plan de producción 2026-09-28

Cola de generación durable y operaciones MCP. No es una segunda cola: los leftovers siguen en `.maestro_generation_queue.json` y en la recuperación que ya usa la UI.

| Bloque | Qué | Estado | PR |
| --- | --- | --- | --- |
| A1 | `status` y `generation.receipt` reconocen leftovers; `jobs.leftovers`, `jobs.resume` y `jobs.discard`; un submit con la misma huella devuelve `duplicate_leftover` y el id existente | en revisión | [#553](https://github.com/IAnMove/hocuspocus/pull/553) |
