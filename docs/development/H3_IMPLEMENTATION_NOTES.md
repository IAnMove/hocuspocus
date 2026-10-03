# H3 adoption implementation log

Branch: `feat/h3-maestro-adoption`. Worktree: `/tmp/hocuspocus-h3-adoption`.
Base: `43f75b907f3cf1134747ac09dc5ce5e6ba266900`.
Reference: Maestro `a5dddd4faa53e8fa8d76ef528c1074935eded8c0`.

## Authorization and preflight

User explicitly requests all investigated H3 features on an isolated temporary branch, with real media acceptance later. No changes or merge into the active checkout. Re-read AGENTS; applicable sections: Non-Negotiable Execution Workflow, Development Workflow, Troubleshooting with Logs, Best practices (preserve existing functionality, cross-platform, documentation, verification). Logs checked before diagnosis. PINOKIO_HOME=/home/ina/pinokio from config. Existing launcher destination=/home/ina/pinokio/api/Maestro-next.git; user explicitly authorizes development of this existing project in /tmp. Example lock: prototype/system/examples/mochi/install.js (requires + shell.run + venv), start.js (daemon + local.set); user-required capture index 1 prevails over old example index 0. App code remains app/, UI follows existing ui/ layout. Do not change working launchers unless dependencies require it.

## Work packages

- [x] Runtime: versioned Turbo variants, PDD, Fused, SLA/Sol, reference continuation.
- [x] Prompt modes: Faithful/Creative, owned dialogue, single/multiple windows, audio policy.
- [x] Integration: narrow router/runtime adapters, UI and persisted settings.
- [ ] Tests: CPU contracts, routing/UI, full safe validation.
- [ ] Handoff: exact commits, upstream attribution, refactor conflict map, user media checklist.

On 2026-09-06 the user additionally authorized real Seinfeld video benchmarks, LAN deployment, and optional Semantic Bridge evaluation. Those run separately from model-free validation.

## Compatibility and merge boundary

Runtime model files and kernels come from Maestro a5dddd4, with upstream notices preserved. Hocuspocus keeps its compact default weights, legacy sidecar guard, 24 GB window-memory tables and activation chunk threshold. Request/prompt policy lives in `h3_runtime_policy`, `h3_prompt_policy`, `h3_story_contract`; only narrow adapters touch `_launch_runtime.py`, `wgp.py`, `llm.py`, and Director. The generation store and Sidebar have small UI/persistence additions. Apply those adapters manually if Grok moves the corresponding functions. No main checkout edits or merge.

Benchmark launcher reference: existing project start.js lines 12–47; mochi/start.js shell.run, daemon and local.set shape. Temporary launcher destination resolved from config: /home/ina/pinokio/api/Hocuspocus-h3-benchmark. User authorized LAN binding; URL still captured with parenthesized HTTP regex and local.set input.event[1]. Existing app and dependencies remain unchanged.

Core implementation commit: cffe855. Runtime follow-up restores `single_block_prompt` for H3 so Context-IR sound fields are never split into separate generations. Local LLM responses that preserve literal words but omit speaker IDs are repaired from the canonical script before validation; the original generated scene is retained. The diagnostics contain real raw LLM responses and the initial fallback attempts.

Validation through core implementation: 1,849 Python tests passed in the second full run; subsequent policy extraction was covered by 94 targeted tests and 26 repeated planner/policy checks. 652 UI tests, lint, build, bundle budget and PR-base complexity ratchet passed. Initial concurrent run had four Quick Video timeout failures, all passed separately (16 tests). Final whole-branch validation remains due after optional changes.

## Driving audio

Finding, not a new control: driving audio syncs better from the full mix than from an isolated vocal (pilot r 0.41 vs 0.16).
