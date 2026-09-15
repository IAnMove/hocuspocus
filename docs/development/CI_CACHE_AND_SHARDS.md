# CI caches and Python test shards

Faster CI without dropping jobs. `CI required` stays a fail-closed
aggregator: cancelled, skipped, missing or failed dependencies are not
success. Windows speech E2E and UI E2E stay in that set.

## Launch and keep working

Push one cohesive commit, then continue a *different* reserved package. Do
not sit on `gh pr checks --watch`. Extra pushes to the same PR cancel the
in-flight run (`cancel-in-progress` is PR-only). Do not use skip-ci.

```bash
git push -u origin HEAD
# next reserved hotspot, not another amend of this PR
python3 .grok-coordinacion/coordinar.py check <agent> <task>
```

Local fast path, from the repo root:

```bash
python scripts/select_local_tests.py path/you/changed.py
python -m pytest -q $(python scripts/select_local_tests.py path/you/changed.py)
# or
python scripts/select_local_tests.py --run path/you/changed.py
```

Unknown or empty paths print a stderr warning and run the **full** automated
suite. They never print an empty list. A mapped test file runs that file.
`scripts/ci_required.py` maps to `tests/test_ci_required.py`.

`--full` local validation (`bash scripts/validate_local.sh --full`) is still
the CI-equivalent wrapper: it runs every safe test, not a shard.

## Caches

| Surface | Mechanism | Key material |
|---|---|---|
| Python pip (Linux shards) | `actions/setup-python` `cache: pip` | OS + Python 3.10 + hash of `scripts/ci-python-requirements.txt`, `scripts/ci-python-torch-cpu.txt`, `app/requirements.txt`, `app/runtime/locks/*.txt` |
| Python pip (Windows speech) | same | OS + Python 3.10 + hash of `scripts/ci-python-windows-requirements.txt`, `app/requirements.txt`, `app/runtime/locks/*.txt` |
| apt ffmpeg | `actions/cache` pinned SHA, `~/.cache/hocus-apt-archives` | OS + arch + `ubuntu-24.04-ffmpeg` |
| Node | existing `setup-node` `cache: npm` | `ui/package-lock.json` |

A lockfile or CI requirements change invalidates pip. A cache miss still
`pip install -r` / `apt-get install` from the network; jobs do not assume a
warm cache. Caches hold public wheels and debs only. No tokens, no workspace
outputs, no pytest result cache.

JUnit XML per shard is uploaded as `pytest-shard-a` / `pytest-shard-b`.

## Shards

`scripts/ci_test_groups.json` partitions every `tests/test_*.py` file into
`python-a` and `python-b` (job names `Python tests A` / `Python tests B`).
Weights are pytest `--collect-only` nodeid counts (parametrized tests
included), packed greedily. That is a duration **proxy**. CI #320 did not
publish per-test timings.

The compile/docs job (`Clean-repo guard + Python checks`) no longer runs
pytest. `CI required` needs:

- `Clean-repo guard + Python checks`
- `Python tests A`
- `Python tests B`
- `UI tests + lint + type-check + build`
- `UI E2E boot (Chromium + simulated API)`
- `Speech E2E Windows (real H.264 + AAC)`

Failure or cancellation of **any** of those keeps `CI required` red.
`scripts/ci_required.py` treats a missing pair as `missing`, not success.

Adding a `tests/test_*.py` file without listing it in the manifest makes
`--group` (CI shards) fail closed. Put the file in the lighter group and
keep the two path lists disjoint.

```bash
python scripts/select_local_tests.py --check-partition
python -m pytest tests/test_ci_shards.py tests/test_select_local_tests.py tests/test_ci_required.py -q
```

`tests/manual_grammar_live_test.py` is a manual script (`*_test.py` with no
pytest cases). It is not in the automated partition.

## Timing (honest)

Measured here, worktree at `origin/development` `780d3915`, existing local
interpreter, **not** a GitHub-hosted runner:

- pytest `--collect-only -q`: **3107 tests in 14.06s**
- Selector/shard unit tests: see the PR test log (seconds, not minutes)

From evidence **E16** (CI #320, previous monolithic guard job):

- Guard wall ~**7m18s**
- Light pip install **101s**, Torch CPU **15s**, collect **22s**, pytest **266s**
- 50-minute queues were **not** measured there or here

Not measured in this change (needs GitHub Actions after push):

- Cold vs hot pip/apt cache on `ubuntu-24.04` / `windows-2025`
- Wall clock of `CI required` with two parallel pytest jobs

Expected shape, not a promise: on a **hot** pip cache the ~116s install
should shrink; pytest wall clock for `CI required` should approach the
slower shard (about half of 266s if the count proxy matches runtime) plus
remaining install/ffmpeg. A **cold** run still pays network installs. This
is not a 2-minute CI. UI E2E, Windows speech export, and npm remain on the
critical path.

Do not treat a green aggregator on an old SHA as coverage of a new HEAD.
