# Production plan progress — 2026-09-28

| Block | Status | Notes |
| --- | --- | --- |
| B3 | implemented on `feat/generation-output-name` | Optional `output_name` on generate/submit. Omitting it keeps the truncated-prompt file name. `invalid_output_name` rejects a path separator or a name that escapes the workspace. `status` and `generation.receipt` return `asset_id`, `canonical_url`, and the workspace-relative `path` of the produced file. |
