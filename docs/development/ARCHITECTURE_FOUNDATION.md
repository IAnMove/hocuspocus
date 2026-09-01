# Architecture foundation contracts

This is the executable foundation for Steps 0 and 1.0 of the canonical
architecture plan in `comunicaciones/plan_arquitectura_hocuspocus.md`.
It changes no product behavior and never imports `_launch_runtime`, FastAPI or
WanGP.

## Static route order

`scripts/architecture_contracts.py` parses `_launch_runtime.py`, expands each
mounted `app/routers/*` factory at its `api.include_router(...)` position, and
records method, path, ordinal, endpoint, status, response model and source in
`tests/fixtures/route_table.json`.

The fixture is deliberately reviewed data. A router extraction must preserve
the relevant rows and ordinals; refreshing the fixture is not evidence that a
route move is safe.

## Cross-language wire inventory

`tests/fixtures/architecture_wire_inventory.json` enumerates:

- Python tests coupled to `_launch_runtime.py`;
- Python tests that inspect `ui/src/stores/useStore.ts`;
- UI tests that import the public `useStore` facade.

Every entry is classified as behavior, an importable-symbol candidate, an
intentional architecture rule, or fragile source inspection. New readers fail
the fixture gate until classified and reviewed.

The initial inventory contains 45 Python readers of `_launch_runtime.py`, 13
Python readers of `useStore.ts`, and 16 UI tests importing the public store
facade. These are measured values, not permanent targets.

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

Run the contracts with:

```bash
python scripts/architecture_contracts.py
python -m pytest -q tests/test_architecture_contracts.py
```

After an intentional, reviewed architecture move:

```bash
python scripts/architecture_contracts.py --write
git diff -- tests/fixtures/route_table.json tests/fixtures/architecture_wire_inventory.json
```
