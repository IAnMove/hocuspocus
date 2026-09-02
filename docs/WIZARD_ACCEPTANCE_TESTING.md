# Wizard acceptance testing

This suite exercises the same visible workflow as a user: browser, Wizard chat,
live LLM, capability registry, application adapters, product UI state, API,
canonical tasks, persistence, scheduler and SSE/poll recovery. Only expensive
media inference can be replaced.

It is designed for local overnight runs. The ordinary Playwright boot smoke
test remains cheap and deterministic in CI.

## Execution profiles

The backend reads `HOCUSPOCUS_EXECUTION_MODE` once at boot. It cannot be changed
through HTTP, UI actions or an LLM tool call.

| Profile | Real layers | Media inference |
| --- | --- | --- |
| `plan` | UI, live LLM, parsing, capabilities and visible form filling | Submission is refused before the queue |
| `simulate` | Everything above plus API, persistence, canonical queue, resource scheduling, progress and downstream consumers | Tiny valid PNG/WAV/MP4/GLB files |
| `real` | Complete production path | Installed local models and explicitly configured providers |

Non-real profiles are confined to one workspace (`e2e_wizard` by default), and
the UI shows a persistent banner. A simulated job is tagged in its sidecar and
in Activity. The application refuses to use another workspace. Paid/remote
providers are blocked unless `HOCUSPOCUS_E2E_ALLOW_PAID=1` was present before
boot.

The Wizard's configured LLM deliberately remains live in every profile: these
are acceptance tests of real language-to-action behavior, so they can consume
LLM tokens. `HOCUSPOCUS_E2E_ALLOW_PAID` governs media provider execution, not
the LLM selected in Settings. Director frames configured for MiniMax are
replaced at the provider boundary in `simulate`, without making the HTTP call.

For a fast LLM-only mixed-language contract check (no navigation, queue or
media inference), run:

```bash
cd ui
HOCUSPOCUS_BASE_URL=http://127.0.0.1:<port> npm run test:wizard-language-live
```

It is restricted to loopback URLs, spends one configured LLM request, respects
“do not generate”, and checks French conversation, English content/technical
direction and exact Spanish dialogue independently of a synthetic German UI
locale.

Simulation deliberately happens after the real job owns its scheduler lane.
It does not add a Wizard shortcut and does not bypass capability validation,
entity correlation, API submission, queue state or task publication.

## Start the backend

Set the variables in the app's per-app `ENVIRONMENT` file, then stop and start
HocusPocus with the normal Pinokio **Start** action. The existing launcher
activates its `env` virtual environment and runs `python launch.py` from
`app/`; do not bypass that lifecycle with `_launch_runtime.py`:

```dotenv
HOCUSPOCUS_EXECUTION_MODE=simulate
HOCUSPOCUS_E2E_WORKSPACE=e2e_wizard
HOCUSPOCUS_SIMULATION_STEP_DELAY=0.05
```

The variables are read only at backend boot, so changing profiles requires a
Pinokio stop/start. Never use a normal workspace for acceptance runs.

The optional failure injector accepts `image`, `audio`, `video`, `model3d` or
`any`. It fails once by default, so the same visible workflow can submit a new
retry and prove recovery. Set `HOCUSPOCUS_SIMULATION_FAIL_COUNT=-1` to fail
every matching attempt:

```dotenv
HOCUSPOCUS_EXECUTION_MODE=simulate
HOCUSPOCUS_SIMULATION_FAIL_KIND=audio
```

## Run from another terminal

```bash
python3 scripts/run_wizard_acceptance.py \
  --base-url http://127.0.0.1:42001 \
  --profile simulate \
  --scenario smoke
```

Replace `42001` with the port shown by Pinokio. The launcher chooses a free
port, so `--base-url` is required unless
`HOCUSPOCUS_BASE_URL` already contains the exact URL shown by Pinokio.

Available scenarios are `smoke`, `full`, `studio`, `language`, `music-video`, `comic`,
`series`, `failure`, `cancel` and `workspace`. `language` verifies a live mixed-language
turn (conversation, content, speech, exact quote and technical provider prompt).
`full` runs the principal successful flows serially.
Use `--headed` to watch the Wizard navigate and fill the application. Use
`--resume` to ask Playwright to run only failures from its previous run.

Real GPU acceptance is intentionally hard to trigger:

```bash
python3 scripts/run_wizard_acceptance.py \
  --profile real --scenario studio --confirm-real
```

The runner refuses a mismatch between the requested profile and the backend's
boot mode. This prevents a command intended for simulation from silently
spending GPU time or provider credit.

## Evidence and assertions

The HTML report is written to `ui/playwright-report/wizard-live`; raw results,
traces, screenshots and retained failure videos go to
`ui/test-results/wizard-live`. Both paths are ignored by Git.

Every live scenario records:

- the visible Wizard transcript;
- the raw LLM turn and its capability/command/result trace (ephemeral and
  bounded in the browser; attached to the report, never persisted by the app);
- the canonical task snapshot, including task/root IDs and status;
- the persisted Story library where applicable;
- screenshots and a complete Playwright trace;
- output identity supplied by real task/result records.

Assertions target state rather than exact prose. The suite verifies the
selected project type, editable lyrics, stable selected candidate ID, terminal
task state and visible UI destinations. A prepared Director pipeline is not
accepted as a generated videoclip; completion must be observable through its
canonical task.

## Nightly order

1. Run the ordinary Python/UI checks without models.
2. Boot `plan` and run `smoke` to catch LLM/schema/form regressions cheaply.
3. Boot `simulate` and run `full` for chained workflows.
4. Boot `simulate` with one injected failure and run `failure`.
5. Boot `simulate` with `HOCUSPOCUS_SIMULATION_STEP_DELAY=1` and run `cancel`
   to exercise the visible Activity cancellation path.
6. Run `workspace` to prove that the Wizard refreshes its exact UI/server
   context after a switch (the temporary secondary workspace is deleted).
7. Only for release candidates, boot `real` and run a small explicitly chosen
   GPU scenario.

The simulated artifacts are intentionally tiny, deterministic and structurally
valid so audio analysis, FFmpeg assembly, gallery discovery and Director
handoffs can consume them. They test orchestration and contracts, not model
quality. Model quality, timing and VRAM behavior still require the explicit
real profile.

## Extending coverage

Add a user-level prompt to `ui/e2e/live-specs/wizard-generation.spec.ts` and
assert durable IDs/state returned by the application. Do not call a capability
executor directly from the test and do not mock a Wizard action. New expensive
engines should call the shared `services.execution_mode` boundary at the point
where they would begin inference, after their normal validation and scheduler
acquisition.
