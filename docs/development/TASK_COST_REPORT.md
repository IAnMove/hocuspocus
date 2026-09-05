# Task cost report

This lightweight report makes the cost of delegated work and live application
checks visible without adding telemetry or a billing system to HocusPocus.

## When to write it

Add the report to every pull request and to the final human handoff for work
that does not create a PR. Start collecting the values before running live
provider calls or long-running checks so that retries are included.

## Template

Copy this block into the PR description or final handoff comment:

```md
## Coste de la tarea

- Tests simulados: 0 tokens externos
- Tests reales: N/A
- Llamadas LLM externas: 0
- Tokens de prompt: N/A
- Tokens de respuesta: N/A
- Tokens totales: N/A
- Generaciones de imágenes/audio/vídeo: 0
- Tiempo transcurrido: N/A
- Proveedores/modelos: N/A
```

Replace `N/A` with provider-reported values when a tool exposes them. Keep
separate counts for independent providers, and include retries in the totals.
For HocusPocus tasks, Activity/task metadata may already contain
`prompt_tokens`, `completion_tokens`, `total_tokens`, `calls`, provider/model,
`task_id`, `root_task_id` and duration; copy those values instead of estimating.

## Counting rules

- Unit tests, static checks, builds and simulated E2E tests use **0 external
  LLM tokens**, even if they exercise an LLM-shaped adapter.
- A live Wizard or LLM integration test counts the provider's reported usage.
- Image, audio and video generation is counted separately from text tokens.
- Codex, Luna, Cursor and Grok usage is reported only when their own tool
  exposes a reliable number. Otherwise write `N/A`.
- Never include API keys, prompts containing secrets, or private user content in
  the report.

This is intentionally a reporting convention, not telemetry: it has no network
calls, does not change runtime behavior, and does not block local-first use.
