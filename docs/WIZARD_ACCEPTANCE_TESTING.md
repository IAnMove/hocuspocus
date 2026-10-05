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

Available scenarios are `smoke`, `full`, `studio`, `language`, `music-video`,
`music-video-new`, `comic`, `series`, `failure`, `cancel`, `workspace`,
`wizard-media`, `app-tour`, `app-generate` and `app`. `language`
verifies a live mixed-language turn (conversation, content, speech, exact quote and
technical provider prompt). `music-video-new` is the one-turn regression for a newly
authored song and videoclip: it proves that the Wizard creates a fresh Story project,
fills and generates its vocal ACE-Step song, carries the exact cue identity into
Director and never falls back to an unrelated selected song.
`full` runs the principal Wizard flows serially. `app-tour` captures every
primary destination, direct-generation submode, tool panel, Settings, Activity
and mobile navigation. `app-generate` uses visible native controls to generate
an image and instrumental music and to upscale the generated image; it checks
canonical completion, downloaded media and metadata. `app` combines these
native UI cases with the tour. `app-generate` and `app` require `real`; the
image case needs an enabled Flux 2 Klein 9B, and the music case needs the
configured ACE-Step model installed. Music waits for model defaults before
setting 30 seconds and checks the decoded duration. Upscale uses Lanczos ×2
and checks the decoded dimensions. These are family-level cases, not certification
of every model and parameter combination. `wizard-media` is the current live
Wizard acceptance pass for two independent native generations: a Flux 2 Klein 9B
image followed by a 20-second ACE-Step instrumental track. Both submissions start
in the visible Ask to the Wizard panel, resolve through the canonical queue, and
retain the literal prompts, Wizard command trace, task IDs, output bytes and browser
decode evidence. It requires the corresponding local models to be installed and
enabled and must be run with `--profile real --confirm-real`.
Use `--headed` to watch the Wizard navigate and fill the application. Use
`--resume --output-dir <previous-root>` to ask Playwright to rerun failures
from that root's previous completed attempt. It creates a new evidence folder;
it does not resume a backend generation or overwrite the earlier report.
Resume rejects a corrupt, empty or successful `.last-run.json` before launching
Playwright: without a valid list of failed IDs, `--last-failed` could otherwise
select the complete scenario again.

Real GPU acceptance is intentionally hard to trigger:

```bash
python3 scripts/run_wizard_acceptance.py \
  --base-url http://127.0.0.1:<port> \
  --profile real --scenario app --confirm-real \
  --output-dir outputs/acceptance-my-run \
  --workspace-prefix e2e_my_run
```

The runner refuses a mismatch between the requested profile and the backend's
boot mode. This prevents a command intended for simulation from silently
spending GPU time or provider credit.

For an occasional release-candidate check of the complete Ask to the Wizard path,
including the configured live LLM, local ACE-Step inference and the final Director
MP4, boot in `real` and opt in explicitly:

```bash
python3 scripts/run_wizard_acceptance.py \
  --base-url http://127.0.0.1:<port> \
  --profile real \
  --scenario music-video-new \
  --confirm-real \
  --headed
```

This scenario is deliberately absent from CI and from `full`: it can spend LLM
tokens and substantial local GPU time. Run the same scenario with `simulate` first
to validate the complete orchestration cheaply while still consulting the real LLM.

## Evidence and assertions

The runner defaults to a unique `outputs/acceptance-<UTC timestamp>` root.
`--output-dir` selects a reusable root. Each attempt gets its own
`attempt-<UTC timestamp>/report`, `raw` and `results.json`. `run.json` records
the invocation and exit status, and `index.html` links the evidence. An abrupt
OS kill can leave an attempt marked `running`; inspect its process and backend
task before starting another inference. Never treat that file alone as proof
of liveness or completion. Run one invocation per evidence root at a time.

Use `--browser-executable /path/to/chromium` when the normal Playwright browser
is unavailable. This selects an owned test browser, not the user's browser.
Direct Playwright calls still accept `HOCUSPOCUS_E2E_ARTIFACT_DIR` and require
the actual `HOCUSPOCUS_BASE_URL`. They do not get the runner's manifest.

To create one index over several scenario roots:

```bash
python3 scripts/acceptance_report.py outputs/my-audit
```

Real-mode cases create fresh `e2e_` folders. The browser harness virtualizes
active-folder selection and shared model/profile preferences so it does not
switch the user's global folder or overwrite their preferences. It restricts
the recovery listing to the current test folder and forbids global recovery
resume/discard. The interrupted queue and test outputs are preserved. This
means **server persistence of those global preferences and recovery actions
is not tested**. Generation, LLM calls, project saves, tasks and media remain
live, except legacy Comics save/history routes: those resolve the server's
global active folder even when a browser has another selected folder. The
harness blocks those writes. The comic case validates all 12 panel images
and browser JSON/PDF downloads; it does **not** certify server save/history.
Story and Series library writes remain live within the selected test folder.
Task controls, including legacy cancel/stop routes, must resolve to canonical
tasks in that folder. JSON and query destinations are checked independently;
native submissions require an explicit JSON workspace. Deletion is excluded.
Do not remove the isolation guard to get a failing case to pass.

See the archived [Wizard coverage audit](archive/2026-09-08/WIZARD_COVERAGE_AUDIT.md)
for the Wizard capability matrix of that audit (the current user guide is
[APP_USER_GUIDE.md](APP_USER_GUIDE.md)). The tour's `features.json` records screenshot coverage separately from
registry support. The native media cases also retain sampled RAM/VRAM data;
the preflight refuses to submit while host RAM usage is already at 80%.
This is a preflight check, not a prediction or prevention of model peak memory.

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
3. Run `app-tour` to capture the visible destinations, then boot `simulate`
   and run `full` for chained workflows.
4. Boot `simulate` with one injected failure and run `failure`.
5. Boot `simulate` with `HOCUSPOCUS_SIMULATION_STEP_DELAY=1` and run `cancel`
   to exercise the visible Activity cancellation path.
6. Run `workspace` to prove that the Wizard refreshes its folder context after
   a browser-local switch. Both test folders are preserved for review.
7. For real acceptance, boot `real` and run `app-generate --confirm-real`.
   Keep local inference serial. Add `comic`, `series` or `music-video-new`
   explicitly according to the available models and provider configuration.

For a single real audit index, use separate output roots under one parent
(`outputs/my-audit/tour`, `outputs/my-audit/native`, etc.), then run
`python3 scripts/acceptance_report.py outputs/my-audit`. This preserves every
scenario's resume state. Copy `docs/archive/2026-09-08/WIZARD_COVERAGE_AUDIT.md` into that parent if
you want the offline index to link the capability matrix. Only read requests retry brief
socket interruptions; a POST is never automatically replayed by the harness.

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
