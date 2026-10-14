# Characterization tests

These tests record what the full server answers today, so that a refactor PR
can prove it changed nothing. They import `app/_launch_runtime.py` in-process
with a fake WanGP (`tests/support/fake_wgp.py`). No GPU, model or network is
needed, and the import takes about 4 seconds.

## Run them alone

```bash
python -m pytest tests/characterization -p no:cacheprovider
```

The import changes process-wide state (it binds `wgp` once, patches `requests`
and `tqdm`, and sets a scheduler hook). The harness also moves the temp folder,
the Numba cache and the style and template libraries into its state folder
before the import: the import sweeps old `hocuspocus-*` folders out of the temp
folder, and the others default to the live install's folders (with
`PINOKIO_HOME` set, in a checkout under `<pinokio>/api`, or through a linked
`app/env`). So in a run that also collects other
tests, such as `pytest` at the repo root or a CI shard, these tests skip and
the skip reason gives the command above. CI runs them in their own step of the
`Python tests A` job. `bash scripts/validate_local.sh --full` runs them too.

## What is here

- `conftest.py`: `full_server` imports the server once per session. `server`
  gives each test empty outputs and uploads folders and a `TestClient`.
  `golden` is the test module's golden file.
- `test_route_table_runtime.py`: the served route table (nested routers and
  resolved paths included) must equal `tests/fixtures/route_table_runtime.json`.
  No route or OpenAPI id may be served twice.
- The other `test_*.py` files call read-only and low-risk routes and compare
  status and body with `goldens/<module>.json`. Bodies are normalised first:
  state folders become `<OUTPUTS>`, `<STATE>` or `<REPO>`, date-time text
  `<TIME>`, today's date `<TODAY>`, generated ids `<ID>`
  (`tests/support/golden.py`). A number under a clock key (`created_at`,
  `mtime` ...) becomes `<TIME>` only when it reads "now"; a fixed stamp the
  test set (`media.BASE_MTIME`) stays in the golden, so a route that starts
  reporting another time fails. A measured duration under such a key
  (`elapsed_time`) is not masked: name it in `mask`.

- `test_run_generation.py`: the generation worker (`_run_generation`) runs for real, with a scripted
  fake engine instead of the GPU. `POST /api/v1/generate` starts the worker thread; `FakeEngine`
  (`tests/support/fake_wgp.py`) plays `wgp.generate_video`: it sends progress commands, writes a media file into
  `wgp.save_path` and lists it in the generation state, or raises, or blocks (`call.hold`) while the test cancels.
  Each test records one observation of the finished job (every lifecycle write, the status and canonical task,
  the files and sidecars, what the engine received, what the worker left behind). The fake `generate_video`
  declares WanGP's real parameters (read from `app/wgp.py`), so the worker's own signature filter decides which
  params reach it; `engine_calls[].kwargs` is what WanGP would receive. Branches that HTTP cannot reach
  call `_run_generation` directly (`Rig.call_worker`, in a daemon thread with a deadline) on a job the server's
  own factory built. Tests named `test_oddity_*` pin
  behaviour that looks unintended: a refactor keeps it, and a fix re-records the golden in its own PR. The stubs go
  through `Rig.patch`, which patches the name on every module in `worker_modules()` that holds it: the full server
  module and the modules of `app/services/generation_worker/`, where the worker lives since slice 21 (they get the
  server's objects through `bind_generation_worker`). `test_generation_worker_bind.py` checks that every injected name is bound.
  A worker that never finishes fails its test; if its thread is still alive when the session ends, `conftest.py`
  ends the process with exit code 1 instead of letting Python wait for it.

## The rule for move PRs: goldens first

A PR that moves code (a slice out of `_launch_runtime.py` or `useStore.ts`)
must not change a golden.

1. **Before the move, on `development`:** add goldens for every route the
   slice moves. Write the test, record it with
   `HOCUS_UPDATE_GOLDENS=1 python -m pytest tests/characterization -p no:cacheprovider`,
   and check that it passes on unchanged `development` code. Commit the test
   and the golden first in the PR.
2. **Then move the code.** The same goldens must pass with no update.
3. `python scripts/architecture_contracts.py --write`: in both route tables
   only the `source` of the moved routes may change.

A golden that changes in a move PR is a behaviour change. Undo it, or take it
out into its own PR that says so.

A feature or bug-fix PR that changes a route's answer on purpose re-records
that route's golden with `HOCUS_UPDATE_GOLDENS=1` and says so in its
description.

## Adding a golden

- Use the `server` fixture. It points the server at empty folders, so the
  answer does not depend on other tests or their order.
- Make the files a route needs inside the test (`tests/characterization/media.py`
  makes tiny images, clips and sounds the same way on every machine).
- Do not golden routes whose answers depend on the machine: hardware, free
  disk, installed model weights, network services or the React build. When
  a field depends on a tool version (an encoded file size), mask it:
  `server.check(..., mask=("size",))`, and when the same value sits inside
  a string, replace it there too: `replace=((pattern, replacement),)`
  (`test_outputs.py` does both).
- A job's generation goes through `FakeEngine` (see above); script it with `rig.engine.script` or `rig.engine.scripts`.
  Names the generation worker needs from WanGP live in `generation_attributes` (drift-checked like the rest).
- When a route reads WanGP state the fake lacks, the call fails with the
  attribute's name. Give the fake that attribute in the test
  (`monkeypatch.setattr(server.wgp, name, value, raising=False)`); see the
  `catalog` fixture in `test_models_and_config.py`. A name you add to
  `tests/support/fake_wgp.py` must exist in `app/wgp.py` with the same
  parameters: `tests/test_fake_wgp.py` reads the real source and fails on drift.

## Known differences from a real boot

- The fake's `create_ui` raises inside the server's own try/except, so the
  import prints a warning and a traceback, and there is no `/classic` mount.
- The video editor router keeps `<repo>/cache/media-thumbnails` (it takes the
  folder when it is included, before the harness repoints the cache). A test
  that makes video editor thumbnails writes them there; git ignores `cache/`.
- `/` is the repair page: the import runs as if the React build were missing,
  so the served table is the same with or without `ui/dist`.
