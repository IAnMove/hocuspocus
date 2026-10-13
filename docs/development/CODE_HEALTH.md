# Code-health ratchet

`scripts/code_health.py` measures only first-party production code. It includes
the HocusPocus Python runtime, services and routers plus `ui/src` TypeScript
and JavaScript. Markdown, JSON catalogs, tests and vendored models are
excluded. Test LOC is reported separately because adding tests is not a
production-code regression.

CI prints a table in the job summary and a separate write-only job upserts
the same table as a PR comment (`<!-- code-health-report -->`) so every
pull request shows the current hotspots, the 0–100 quality score and the
delta versus the PR base. The job that runs the ratchet does not get
comment permissions.

After UI dependencies install successfully, CI still runs UI tests, lint and
the build when the ratchet fails. Their individual results remain visible;
any failed validation, including the ratchet, still fails `CI required`.
Cancelling the run or failing dependency installation skips those later checks.

The PR table starts with a transparent quality score from 0 to 100 and its
change against the PR's exact base commit. Higher is better. The score combines
cyclomatic health (45%), concentration in the largest files (25%), oversized
file debt (20%) and modularity (10%). Component scores and their individual
deltas are shown so the total is explainable.

Each signal is linearly mapped between a healthy bound (100) and a severe
bound (0), then clamped. The current bounds are deliberately broad:

| Component | Signals (100 → 0) |
|---|---|
| Cyclomatic health | functions at complexity 15+: 2% → 12%; maximum complexity: 25 → 700 |
| File concentration | largest-file share: 5% → 25%; top-five share: 20% → 55% |
| Oversized-file debt | lines above 1,000 per hotspot: 5% → 50% of production; files at 5,000+ lines: 0.5% → 5% |
| Modularity | average file size: 250 → 800 lines; 1,000-line hotspot share: 2% → 15% of files |

Inside the components, cyclomatic ratio has 75% of its component weight and
maximum complexity 25%; the oversized-line debt has 75% and giant-file ratio
25%. The other paired signals are weighted equally.

Quick report after installing the normal UI dependencies:

```bash
python scripts/code_health.py
python scripts/code_health.py --markdown
```

`--markdown` without `--check` prints **Ratchet not evaluated.** CI uses `--check --markdown` so the PR comment shows passed or failed against the committed baseline.

The report lists physical/non-blank lines, files over 1,000 lines, and the most
complex Python and TypeScript/JavaScript functions. Python uses a classic
AST-based McCabe count. UI complexity uses ESLint's built-in `complexity` rule.
If `ui/node_modules` is absent, the normal report still works but warns that UI
complexity is unavailable.

CI compares a pull request with the exact code-health report generated from
its base commit. The release integration rule below only changes the unit for
the two cumulative growth budgets. The committed baseline remains the repository trend
dashboard and is used when running the check outside a pull request:

```bash
python scripts/code_health.py --check
```

For a feature branch, do not use the historical-baseline command above as the
pre-PR gate. It intentionally reports accumulated trend debt and may fail even
when a change is safe relative to its pull-request base. Use:

```bash
bash scripts/check_code_health_pr_base.sh
```

The helper checks the exact `origin/main` ref by default. Set `BASE_SHA` to the
base SHA reported by GitHub (or `BASE_REF` to another fetched base ref) to
reproduce a specific pull-request comparison. `scripts/validate_local.sh`
invokes the same helper automatically. The committed baseline remains useful
for the long-term dashboard and must not be refreshed merely to make a PR
green.

The check prints deltas for production LOC, test LOC, complex functions and
every changed large-file hotspot, so a refactor's improvement is visible in
the same run. Small increases print warnings. CI fails only for a material
regression:

- production LOC grows beyond the greater of 3% or 2,000 lines;
- functions at complexity 15+ increase by more than five (split pieces can be
  credited, see below);
- maximum function complexity rises by more than three;
- a file's maximum complexity rises by more than five, or a new file exceeds 25
  (unless every function over the limit is a verified move, see below);
- an existing 1,000-line hotspot exceeds its small growth allowance;
- a new first-party file exceeds 1,200 lines (never waivable, moves included);
- a tracked `app/**/*.py` file is outside the measured scope and is neither
  vendored engine code nor in the unmeasured baseline; or
- a file in the unmeasured baseline grows beyond the hotspot growth allowance
  or gains a function at complexity 15+ (above its base maximum).

A deliberate architectural change can refresh the snapshot, but the diff must
be reviewed like any other budget change:

```bash
python scripts/code_health.py --write-baseline
git diff -- scripts/code_health_baseline.json
```

The baseline is a ratchet, not a quality certificate. Decreasing a giant file
or a complex function is progress; moving the same code under a different name
should be reviewed rather than used to reset the baseline casually.

The aggregate score is also not a quality certificate and never replaces the
ratchet. It deliberately excludes test volume and coverage, which need their
own evidence and are too easy to game as a maintainability score.

`--check` fails closed when a required measurement is missing (including UI
complexity), when the baseline summary is incomplete, when product files are
silently excluded while they still exist, or when the policy dict changes
without review. A higher quality score cannot hide those local failures.
Reports record `policy_version`, HEAD and base SHAs, and whether UI metrics
were complete. Exceptions live in `scripts/code_health_exceptions.json` and
must include path, rule, reason, owner, issue and expiry; there is no global
hotspot waiver. `expires` must be a `YYYY-MM-DD` date. A waiver covers only
its own rule's failure about exactly its `path`: `hotspot <path> grew …` for
`hotspot_growth`, `new complexity hotspot <path> is …` or `complexity hotspot
<path> increased …` for `complexity_hotspot`. A folder prefix or a fragment
such as `LOC` matches nothing. There is no per-function cap: the complexity
rules are per file. Function fingerprints only let the ratchet recognize moves
and splits.

## Moves, splits and unmeasured code

The architecture refactor moves functions out of `app/_launch_runtime.py` and
`ui/src/stores/useStore.ts` into feature modules. Without the rules in this
section, a verbatim move of a complex function fails as a "new complexity
hotspot", and code moved to a folder outside the scope stops being measured.
The rules change only the logic in `compare()` and `collect()`. The `POLICY`
dict is unchanged.

### What a report records

`collect()` writes `fingerprints`: one record per function at complexity 15+.
It also writes the weaker functions that split accounting needs: those that
share a name with a complex function, or whose name makes them a split parent
of one. Each record has the path, the name, the line, the complexity and a
hash:

- **Python:** the qualified name and a hash of the normalized AST. The hash
  covers the node type (sync or async), the arguments (default values
  included), the return annotation and the body. Docstrings (of the function
  and of every def and class inside it), comments and positions are ignored.
  Nothing is renamed. The function's own name and its **decorators** are left
  out: a route moved from `@app.post(...)` in launch to `@router.post(...)` in
  a router changes only its decorator, which does not count towards
  complexity.
- **UI:** the identifier from ESLint's label (`startGeneration` from
  "Async method 'startGeneration'") and the complexity. There is no hash.
  ESLint reports the function's head, not its body, so a hash would need a
  second parse of `ui/src`. Anonymous functions (an unnamed arrow function,
  a constructor) have no name and never get move or split credit.

### Moves

A function is a **verified move** when it has left its base file for another
file and the base report has a function with:

- the same name; and
- the same hash (Python), or the same or higher complexity (UI, which has no
  hash).

The base function must be gone from its old path. If it is still there, the
new one is a copy, and a copy is new code. Matching counts instances, so two
copies of one base function give at most one move.

- A **new complexity hotspot** over 25 does not fail when every function over
  25 in that file is a verified move.
- An **existing file** whose maximum complexity rises by more than five (a
  move into an existing router, for example) does not fail when every function
  over the old maximum + 5 is a verified move.
- The moved function's base complexity is its **ceiling**. Any change to a
  Python body changes the hash. So does any rise in complexity. Either loses
  the credit, and the normal rule applies. A UI function above its base
  complexity loses the credit the same way.
- The failure says why a function did not count as a move: "has the name of
  base … but different code, so it counts as new", "rose above its base
  ceiling", "is a copy", "has no name to match", or "is not in the base".
- The check lists every verified move as `moved: X (complexity N) from A to B`
  under **Moves and splits** in the PR table, or as a `NOTE:` line in the
  terminal.

The hash proves that the function's own code did not change. It does not
cover what that code refers to: the decorators, the module's constants and
globals, and the helpers it calls, which in the new file can be different
objects with the same names. None of that changes the function's complexity,
and a helper under 15 is invisible to every rule anyway. Reviewers of a move
PR should check those by hand: compare the decorator lines, and diff the new
module's constants and helpers against the ones in the old file.

A UI move is weaker, because it has no hash. Any function with the same name
whose complexity did not rise passes, even if its body was rewritten. The
complexity cannot go up and the original must be gone, so the ratchet's
numbers stay honest, but nothing proves the code is the same. Reviewers of a
UI move PR should read the moved functions with `git diff --color-moved`
(moved lines show in their own colour; anything else is a change) and ask for
behaviour changes in a separate PR.

Keep moves verbatim and make logic changes in a separate PR. If one PR must
both move and change a complex function, the dated `complexity_hotspot`
waiver is still available. A waiver applies only to the file a failure is
about, the path before the first `;`. A waiver for the base file does not
cover the file the function moved to. After the move merges, the new file is an
ordinary hotspot in the next PR's base: it may rise by up to five, like any
other file.

The 1,200-line rule for new files has no move exception and cannot be waived.
A function longer than that, such as `_run_generation`, must be split before
it moves.

### Splits

At most five new functions at complexity 15+ are allowed per PR. A piece
carved out of a function that existed in the base does not count against
that budget when both of these are true:

- **Name rule (the parent is found by name prefix; there is no `split_from`
  annotation).** The piece is a def nested in the parent
  (`_run_generation.prepare`), or its last name part, without leading
  underscores, is the parent's last name part plus a suffix that starts with
  `_`, an upper-case letter or a digit:
  - `_run_generation` → `_run_generation_prepare`, `Runner._run_generation_finalize`;
  - `startGeneration` → `startGenerationAudio`, but not `startGenerations`.

  The parent must be at complexity 15+ in the base. The piece's name must not
  be in the base records. The longest matching parent wins.
- **Complexity rule.** The parent's complexity, summed over every function of
  that name, must drop by at least the sum of the pieces' **decisions**, which
  is their complexity minus one each. Extracting a block with *d* decisions
  lowers the parent by *d* and creates a piece of complexity *d* + 1, so a
  pure extraction passes exactly. A parent that kept or gained complexity does
  not get credit.
- **No new logic.** The change as a whole must not add decisions: the report's
  `summary.decisions` (complexity minus one, summed over every measured
  function) may not rise versus the base. Moving and splitting code keeps that
  total; new logic raises it. Without this rule a parent could shed its logic
  into helpers under 15, which no rule counts, while the "pieces" named after
  it hold new code. A PR that splits functions and also adds logic gets no
  split credit, so split in one PR and change behaviour in another.

Credit is all or nothing per parent. The PR table lists `split: … carved out
of P (before -> after)`, or `split not credited: …` with the numbers. Pieces
over 25 that move to a new file still need the move rule or a waiver.

### Unmeasured product code

The ratchet measures `app/_launch_runtime.py`, `app/launch.py`, `app/wgp.py`,
`app/services/**` and `app/routers/**` among the Python files. Any other
tracked `app/**/*.py` file fails as **unmeasured product code**, except:

- vendored engine code: `UNMEASURED_VENDOR_PREFIXES` (`app/models/`,
  `app/plugins/`, `app/postprocessing/`, `app/preprocessing/`, `app/shared/`);
- the files that were already outside the scope on 2026-10-13:
  `UNMEASURED_BASELINE` (`app/app_identity.py`, `app/core_runtime.py`,
  `app/setup.py` and the eight `app/scripts/*.py` tools).

New feature code goes under `app/services/` or `app/routers/`. Developer tools
go in the repository's `scripts/` folder. Both lists are copied into the
report, and a list that grows versus the PR base fails ("needs owner review").
A baseline file that is deleted and later created again fails as new versus
the base. A baseline entry whose file no longer exists prints a warning:
remove it from the list. `tests/test_code_health_moves.py` requires the list
to match today's tree exactly, so a PR that deletes or moves one of those
files also removes it from `UNMEASURED_BASELINE`.

The baseline files stay where they are, but they cannot absorb code moved out
of the measured scope. `app/core_runtime.py`, for example, is a 790-line
server that imports every router. The report records each baseline file's
lines and highest function complexity under `unmeasured.files`. A baseline
file fails when it grows by more than the hotspot growth allowance (75 lines
for files this size) or when it gets a function above its base maximum or 14,
whichever is higher. Shrinking or deleting them is always free. These
failures cannot be waived.

Vendored folders are not measured, and model integrations add first-party
files there routinely (VoxCPM2 added twenty), so a new file there cannot fail.
Instead the report lists every tracked `.py` file under those prefixes
(`unmeasured.vendor_files`), and the PR table warns about each new one:
"N new Python file(s) under vendored folders are not measured". Reviewers must
confirm that such a file is engine code and not product code moved out of the
ratchet. Code added to an existing vendored file gets no warning, so reviewers
read every diff into those folders.

### Compatibility

- The PR base is measured by the base's own analyzer. A base from before this
  change has no `fingerprints`, `summary.decisions` or `unmeasured` data.
  Against it there is no move or split credit, and the scope lists and
  baseline files cannot be compared, so the old strict rules apply.
- The release integration verifier (below) treats any change to
  `scripts/code_health.py` in the release chain as a measurement change and
  fails closed. The first development → main release after an analyzer change
  needs that separate review.
- The verifier re-checks the complex-function budget at every first-parent
  merge with reports it builds from history. Those checkpoint reports carry
  the same `fingerprints` and `summary.decisions` as a PR report, so a split
  credited on its PR is credited again at its release step, and a split that
  was not credited fails there too.

## Release integration: development → main

Ordinary feature PRs and pushes keep the existing single-change ratchet.
For a release PR whose actual source is `development` and base is `main`,
`check_code_health_pr_base.sh` invokes `code_health_integration.py`.
Both PR repositories must also match GitHub's current repository identity;
a fork branch named `development` keeps the ordinary ratchet.

- Production LOC and the number of functions at complexity 15+ must stay within
  the unchanged budget at **every first-parent integration**. Splitting a release
  into many commits does not permit any individual step to exceed its budget;
  a later reduction cannot erase an earlier aggregate-budget failure.
- Maximum complexity, per-file complexity, large-file growth, new-file limits,
  policy, scope and complete measurements remain mandatory between the **exact
  main base and final candidate**. An intermediate local hotspot can be repaired
  before release; its historical finding stays in the report and the final
  tree must satisfy the original base limits. There is no local-rule waiver.
- The report retains the full cumulative LOC/function deltas and quality score
  against main. The baseline and exception file are never rewritten.

The verifier requires full Git history, exact source/base SHAs, contiguous
first-parent ancestry and a checked-out candidate tree equal to the source
tree. The main base must have the same tree as the integration merge-base
(publication-only merge history is allowed). It rejects dirty product files,
missing blobs, omitted measurements, and changes to the analyzer, policy or
ESLint configuration anywhere in the chain. UI dependencies are compared by
their measurement fingerprint: ESLint's executable, the configuration's static
package imports, and their dependencies, optional dependencies and peers.
The fingerprint preserves complete lock records (including version, resolved
URL, integrity and executable mappings), dependency ranges and resolved paths;
an absent optional dependency is recorded explicitly. All packages declaring
install scripts or native builds and their dependencies are also protected,
even outside ESLint's graph. Because npm can execute implicit native build hooks
without a lockfile flag, the remaining package records and root dependency
ranges may only be removed: additions or mutations require separate review.
Removing an unrelated package such as `@types/dompurify` therefore does not
invalidate an otherwise identical measurement toolchain; adding or updating an
unrelated package still fails closed.

Root manifest metadata, overrides and install hooks remain protected. Ordinary
npm scripts may change because measurement invokes ESLint directly; when a root
install hook exists, all scripts and installed packages remain protected because
that hook could use them. Missing required packages or identities, linked
packages, lockfiles other than npm v3, and local or dynamic configuration imports
fail closed. Analyzer and ESLint configuration files still require identical
blobs; there is no exception for changes to the measurement tools themselves.
Historical blob metrics must reproduce the gate's base and candidate
measurements exactly. Unsupported history or measurement changes fail closed and require
separate review; branch labels alone are insufficient to pass.

Unique source blobs are analyzed once with the existing Python AST counter and
ESLint complexity rule, then reconstructed into each exact commit's product
paths. This avoids rerunning full UI analysis for unchanged code at every merge.
The `code-health-report` artifact includes `code-health-integration.json` with
every checkpoint SHA, tree, aggregate metrics, historical findings and verdict.
CI fetches complete history when necessary. Local reproduction uses exact SHAs:

```bash
BASE_BRANCH=main SOURCE_BRANCH=development \
GITHUB_REPOSITORY=IAnMove/hocuspocus \
BASE_REPOSITORY=IAnMove/hocuspocus SOURCE_REPOSITORY=IAnMove/hocuspocus \
BASE_SHA=<main-base-sha> SOURCE_HEAD_SHA=<candidate-sha> \
bash scripts/check_code_health_pr_base.sh
```

The integration that introduced the explosion effects had two historical
hotspot regressions. Separating material/particle animation and replacing
effect-default branches with a defaults table repairs those current functions;
the release rule still checks their final complexity against main.

The same rule applies to the ensuing canonical `push` to `main` only when its
`before` SHA equals the first parent of a two-parent merge, the published tree
equals its second parent's tree, and that second parent belongs to a freshly
fetched `origin/development` history. Thus publishing the verified development
tree keeps the same gate. Fast-forward/squash commits, changed merge trees,
unrelated second parents and ambiguous metadata keep the ordinary ratchet;
missing history or a failed fetch cannot produce a pass.
