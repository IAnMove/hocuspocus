# Architecture foundation contracts

This is the executable foundation for Steps 0 and 1.0 of the canonical
architecture plan in `comunicaciones/plan_arquitectura_hocuspocus.md`.
It changes no product behavior and never imports `_launch_runtime`, FastAPI or
WanGP.

## Static route order

`scripts/architecture_contracts.py` parses `_launch_runtime.py`, expands each
mounted `app/routers/*` factory at its `api.include_router(...)` position
(routers a factory includes itself are expanded too), and records method,
path, ordinal, endpoint, status, response model and source in
`tests/fixtures/route_table.json`.

A route path must be one string literal. A path built from an f-string, a
constant or any other expression fails the contract, unless its route is
listed in `NON_LITERAL_ROUTE_PATHS` with the reason.

The fixture is deliberately reviewed data. A router extraction must preserve
the relevant rows and ordinals; refreshing the fixture is not evidence that a
route move is safe.

## Served route table

`tests/fixtures/route_table_runtime.json` is the table the running app
serves, in match order: it is the authoritative one. `tests/support/full_server.py`
imports the full server with a fake WanGP and flattens its routes, nested
routers included, with resolved paths. Each row also has the handler's
source file, status code, response model and OpenAPI id.

- `tests/characterization/test_route_table_runtime.py` checks the served table
  against the fixture and that no route or OpenAPI id is served twice.
- `tests/test_architecture_contracts.py` checks, without importing anything,
  that the static table lists the same app routes in the same order.

## Cross-language wire inventory

`tests/fixtures/architecture_wire_inventory.json` enumerates:

- Python tests coupled to `_launch_runtime.py`;
- Python tests that inspect `ui/src/stores/useStore.ts`;
- UI tests that import the public `useStore` facade.

Every entry is classified as behavior, an importable-symbol candidate, an
intentional architecture rule, or fragile source inspection. New readers fail
the fixture gate until classified and reviewed.

The current inventory (`tests/fixtures/architecture_wire_inventory.json` on
`origin/main` at #137) contains **46** readers of `_launch_runtime.py` and
**36** readers of `useStore.ts`. These are measured values, not permanent
targets. The historical snapshot after #100 was 45 / 13 Python plus 16 UI
facade imports; do not treat that older split as the live count.

## WanGP boundary

`tests/test_architecture_contracts.py` parses first-party Python with AST and
names every currently tolerated `wgp` import by file, enclosing symbol and
statement. Upstream/vendor trees are excluded explicitly.

The WanGP wall lives in `app/services/generation/`. Launch imports `wgp` once
after the argv patch and calls `bind_wgp(wgp)`. Consumers read that live
instance through `get_wgp()`, `ModelCatalog`, or `RuntimeConfig`. The wall
does not import WanGP for consumers. The documented standalone Python API is
the single exception: `generation/bootstrap.py` may import once when a process
starts through `shared.api.init()` instead of launch, then binds that exact
`sys.modules["wgp"]` instance. Video concat stays in `services.mix_concat` and
only uses `get_wgp()` to reach the already-bound helper.

The remaining first-party allowlist contains exactly the launch bootstrap and
the standalone API bootstrap. New static or dynamic `wgp` imports outside
`app/models/**` and other vendor trees fail the gate.

Run the contracts with the app's Python (the served table imports the full
server in a child process; `--static-only` skips it):

```bash
app/env/bin/python scripts/architecture_contracts.py
python -m pytest -q tests/test_architecture_contracts.py
python -m pytest tests/characterization -p no:cacheprovider
```

After an intentional, reviewed architecture move:

```bash
app/env/bin/python scripts/architecture_contracts.py --write
git diff -- tests/fixtures/route_table.json tests/fixtures/route_table_runtime.json \
  tests/fixtures/architecture_wire_inventory.json
```

## Refactor safety net: what every move PR does

The refactor of `_launch_runtime.py` and `useStore.ts` into feature slices
moves code without changing behaviour. Each move PR (Step 0 consolidations,
the kernel, each slice) proves that with these four steps:

1. **Goldens first.** Before moving anything, add characterization tests for
   every route the PR moves (`tests/characterization`, see its README). Record
   them with `HOCUS_UPDATE_GOLDENS=1` and check they pass against unchanged
   `development` code. Then move the code: the goldens must pass unchanged.
2. **Route tables: only `source` changes.** Run
   `app/env/bin/python scripts/architecture_contracts.py --write`. In
   `route_table.json` and `route_table_runtime.json`, the moved routes may
   change their `source` and nothing else: method, path, endpoint, status
   code, response model, OpenAPI id and order stay the same.
3. **Boot smoke before merge.** On the GPU host, boot the PR's worktree:

   ```bash
   bash scripts/boot_smoke.sh /mnt/outputs/hocuspocus-worktrees/<name> [--list scripts/boot_smoke/<slice>.txt]
   bash scripts/boot_smoke.sh /mnt/outputs/hocuspocus-worktrees/<name> --core   # when the PR touches core
   ```

   It starts the server on a free port (42080-42099) with its own outputs,
   uploads, settings and caches, links only `app/env` and `ui/dist` from the
   live install, loads no model, calls `scripts/boot_smoke/default.txt` (or
   `core.txt`) plus the slice's list, compares the OpenAPI routes with
   `route_table_runtime.json`, and stops the server by its PID. It needs at
   least 3 GB of free VRAM unless `--cpu`. Put the result (port, route count,
   PASS) in the PR's E2E/smoke line. A PR that removes a core duplicate
   deletes its line in `scripts/boot_smoke/core.known-duplicates.txt`.
4. **Lower the ceiling.** `scripts/size_ceilings.json` holds the most lines
   `_launch_runtime.py`, `core_runtime.py` and `useStore.ts` may have.
   Ceilings only go down: `tests/test_size_ceilings.py` fails when a file is
   over its ceiling or more than 100 lines under it, and
   `scripts/check_code_health_pr_base.sh` fails when a ceiling rises against
   the PR base. After shrinking a file, run
   `python scripts/size_ceilings.py --lower` and commit the result. The merge
   train recomputes the ceilings at merge time.
