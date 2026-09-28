# Plan de producción 2026-09-28

| Bloque | Estado | Notas |
| --- | --- | --- |
| B5 | en borrador | `jobs.wait` v1 bloquea hasta `completed`, `failed`, `cancelled` o `discarded`, o devuelve `timeout`. Por defecto 30 s, máximo 120. Reutiliza el status de generación, incluye `progress` si ya está, y no arranca modelo ni GPU. `interrupted` no es terminal. |
