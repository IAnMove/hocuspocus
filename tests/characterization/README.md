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
and `tqdm`, and sets a scheduler hook). So in a run that also collects other
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
  state folders become `<OUTPUTS>`, `<STATE>` or `<REPO>`, clocks `<TIME>`,
  today's date `<TODAY>`, generated ids `<ID>` (`tests/support/golden.py`).

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
  `server.check(..., mask=("size",))`.
- When a route reads WanGP state the fake lacks, the call fails with the
  attribute's name. Give the fake that attribute in the test
  (`monkeypatch.setattr(server.wgp, name, value, raising=False)`); see the
  `catalog` fixture in `test_models_and_config.py`.
