# Developer architecture map

The developer area contains a read-only, build-time map of one bounded flow:
**Story Lab → Director audio hand-off**. It complements tests and documentation;
it is not a full architecture inventory, runtime trace, or correctness certificate.

## Open and regenerate

Enable Developer mode in Settings → System, open the developer audit area and
select Architecture. The existing media audit remains a separate view. The viewer
loads only when selected and requests a fixed static JSON asset, not a backend
filesystem endpoint.

```sh
cd ui
npm ci
npm run architecture:generate
npm run dev
```

`npm run dev` and `npm run build` regenerate the snapshot automatically before
starting Vite. Requirements: Python 3.10+, Node and the locked UI dependencies.
No Python third-party package, model, GPU, network service or running API is needed.
If Python is not on PATH, set `HOCUSPOCUS_GRAPH_PYTHON` to its executable path.
Direct `vite` commands bypass the npm pre-step: regenerate explicitly in that case.

Equivalent root command:

```sh
python scripts/graphs/story_director_audio_flow.py --output ui/public/dev/architecture/story-director-audio.json
```

This is a snapshot, not a live file watcher. After editing a scoped source during
dev, regenerate and reopen/reload the Architecture view. The production bundle
contains its build-time snapshot. The source JSON is gitignored, not committed;
build artifacts carry it. No generated media or model weights are included.

## Extraction and evidence

- Python uses standard-library AST, scoped to configured route handlers/helpers.
- TypeScript and TSX use the existing locked TypeScript Compiler API. Calls in
  comments/string literals are not code; arrow functions and object functions are
  traversed syntactically. No new graph/parser dependency is introduced.
- Each detected relationship includes relative file/line/column evidence.
- `×N` means static call sites in the configured scope, not execution frequency.
  Read/write/reference relations may have weight zero: zero means uncounted, not
  evidence that the relation never occurs.
- Nodes/edges/evidence are sorted; schema version, source commit, scoped dirty flag,
  source hash, warnings and limitations accompany the result.
- Clean-source evidence links use the recorded commit, never the moving main branch.
  Dirty/unversioned snapshots do not pretend their line numbers match GitHub.

The source hash identifies the configured input files, not every file in the app
and not a signature of trust. The dirty flag describes scoped source files, not
unrelated working-tree changes. Imported external implementations are not analysed.

## Limits and failure behavior

The scope, service grouping and route mappings remain explicit configuration. AST
syntax avoids regex parsing errors but is not full type/module resolution. Aliases,
dynamic dispatch, computed names and similarly named symbols can need additional
resolution. The map must not claim all edges are runtime-proven. Required sources,
functions and invalid syntax must cause extraction to fail, not produce a silent
partial success. The UI shows missing/invalid assets as an error with retry.

For broader import/cycle rules, evaluate dependency-cruiser separately; it solves
module dependency analysis, not all cross-language call resolution. Do not add it
merely to render this bounded map, and do not promote map heuristics to a required
architectural gate without a demonstrated test corpus.

## Safety and contribution

The mode toggle is presentation, not authorization. No arbitrary paths, shell
commands or new privileged endpoints are exposed. The static graph has source
identifiers only: no source snippets, prompts, credentials, logs, workspaces or
absolute local paths. Treat graph JSON as untrusted data; validate schema, sizes,
paths and references, render text normally and restrict source links to this repo.
Do not serve repository configuration/secrets because the project is open source.

To extend the map: change the explicit scope, add parser fixtures and expected
evidence, then regenerate against the real source. Preserve stable IDs or version
the contract. Do not edit generated JSON or hardcode annotations claiming a PR was
validated. Keep extractor and viewer tests model-free.

## Verification

```sh
python -m pytest -q tests/test_architecture_graph.py
cd ui
node --test tests/architectureExtractor.test.mjs
npm run test
npm run i18n:check
npm run lint -- --max-warnings=0
npm run build
npm run budget
npm run test:e2e -- architecture
```

Browser E2E uses the simulated API and proves navigation/rendering, not real media
generation. Unit fixtures cover parsing/multiplicity, bad inputs and safe evidence.
CI already runs Python and UI suites plus build/budget/E2E; npm's prebuild step
generates the real scoped map so a missing required source fails the UI build.

Sources: [TypeScript Compiler API](https://github.com/microsoft/TypeScript/wiki/Using-the-Compiler-API),
[dependency-cruiser](https://github.com/sverweij/dependency-cruiser).
