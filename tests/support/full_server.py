"""Import the full server in-process with a fake WanGP, and read its served routes.

``load_full_server`` imports ``app/_launch_runtime.py`` through the lazy factory
``launch.create_app()``, with :mod:`tests.support.fake_wgp` in
``sys.modules["wgp"]``. No GPU, no model and no network are needed. It takes
about 4 seconds, most of it the torch import.

The import changes process-wide state that cannot be undone: ``wgp`` is bound
once (``services.generation.bind_wgp``), ``services.safe_download`` patches
``requests`` and ``tqdm``, the resource scheduler gets a prepare hook, and the
temp folder (``TMPDIR`` and ``tempfile.tempdir``) and the Numba cache move into
the state folder, because the import sweeps old ``hocuspocus-*`` folders out of
the temp folder. So it runs
once per process, in a pytest run of ``tests/characterization`` alone
or in a script (``python -m tests.support.full_server``).

``served_route_table`` flattens the routes in the order the app matches them,
nested routers included, with their resolved paths.

Two known differences from a real boot:

- the fake's ``create_ui`` raises inside the server's own try/except, so the
  import prints a warning and a traceback, and the table has no Gradio
  ``/classic`` mount (``scripts/boot_smoke.py`` ignores mounts too);
- the server keeps media thumbnails in ``<repo>/cache/media-thumbnails``.
  :func:`_keep_media_cache_in` repoints the launch alias, ``output_ops`` and
  ``media_dimensions`` after the import, but the video editor router took the
  folder when it was included, so a test that makes video editor thumbnails
  writes them under the repo's ``cache/`` (ignored by git).
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import tempfile
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"
RUNTIME_ROUTE_FIXTURE = ROOT / "tests" / "fixtures" / "route_table_runtime.json"

# Fixed for every import, so the served table does not depend on the shell.
SERVER_ENV = {
    "HOCUS_TRUSTED_HOSTS": "testserver",
    "HOCUS_GPU_MACHINE_LOCK": "0",
    "CUDA_VISIBLE_DEVICES": "",
    "HF_HUB_OFFLINE": "1",
}


@dataclass(frozen=True)
class FullServer:
    api: Any
    wgp: Any
    state_root: Path


def load_full_server(state_root: Path) -> FullServer:
    """Import the full server once, with its outputs, LoRAs and config under ``state_root``."""
    if "_launch_runtime" in sys.modules:
        raise RuntimeError("The full server is already imported in this process; import it only once.")
    os.environ.update(SERVER_ENV)
    # With PINOKIO_HOME set, or in a checkout under <pinokio>/api, these
    # libraries default to the live install's shared cache.
    os.environ["MAESTRO_STYLE_LIBRARY_DIR"] = str(state_root / "style-library")
    os.environ["HOCUS_TEMPLATE_LIBRARY_DIR"] = str(state_root / "template-library")
    _keep_temp_files_in(state_root / "tmp")
    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))
    from tests.support.fake_wgp import make_fake_wgp

    fake = make_fake_wgp(state_root)
    sys.modules["wgp"] = fake
    # The React build may or may not exist (CI has none, a live checkout has
    # one). Import as if it were missing, so the served table is the same
    # everywhere: "/" is the repair page, not a static mount.
    from services import ui_distribution

    real_build_status = ui_distribution.build_status
    ui_distribution.build_status = lambda *args, **kwargs: {**real_build_status(*args, **kwargs), "ready": False}
    try:
        import launch

        api = launch.create_app()
    finally:
        ui_distribution.build_status = real_build_status
    _keep_media_cache_in(state_root / "cache" / "media-thumbnails")
    return FullServer(api=api, wgp=fake, state_root=state_root)


def _keep_temp_files_in(folder: Path) -> None:
    """The import starts a sweep of old hocuspocus-* folders in the temp folder, which the live install shares.

    pytest has already chosen its own base folder, so ``tmp_path`` is unaffected.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("TMPDIR", "TEMP", "TMP"):
        os.environ[name] = str(folder)
    tempfile.tempdir = str(folder)
    # Numba caches compiled functions next to their package, in app/env, which may link to the live install's.
    os.environ["NUMBA_CACHE_DIR"] = str(folder / "numba-cache")


def _keep_media_cache_in(folder: Path) -> None:
    """The server caches media facts and thumbnails in <repo>/cache; tests keep theirs in the state folder."""
    from services import media_dimensions
    from services import output_ops

    folder.mkdir(parents=True, exist_ok=True)
    path = str(folder)
    # The launch name is the alias the video editor already captured. Thumbnails
    # read the service global at request time, so both names move together.
    sys.modules["_launch_runtime"]._MEDIA_THUMBNAIL_CACHE_DIR = path
    output_ops._MEDIA_THUMBNAIL_CACHE_DIR = path
    media_dimensions.configure(path)


def _source_of(endpoint: Any) -> str | None:
    """The handler's file relative to the repo, or ``<module>`` for a library handler."""
    try:
        path = Path(inspect.getsourcefile(inspect.unwrap(endpoint)) or "").resolve()
    except (TypeError, OSError):
        path = None
    if path is not None:
        try:
            return path.relative_to(ROOT).as_posix()
        except ValueError:
            pass
    return f"<{getattr(endpoint, '__module__', '?')}>"


def _type_name(value: Any) -> str | None:
    """A response model by class name only, so moving its module is not a route change."""
    if value is None:
        return None
    origin = typing.get_origin(value)
    if origin is not None:
        args = ", ".join(_type_name(arg) or "None" for arg in typing.get_args(value))
        return f"{getattr(origin, '__qualname__', str(origin))}[{args}]"
    return getattr(value, "__qualname__", None) or repr(value)


def _route_contexts(api: Any) -> list[Any]:
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # FastAPI before lazy includes: the list is already flat.
        return list(api.routes)
    return list(iter_route_contexts(api.routes))


def _operation_ids(api: Any) -> dict[tuple[str, str], str]:
    ids: dict[tuple[str, str], str] = {}
    for path, operations in (api.openapi().get("paths") or {}).items():
        for method, operation in operations.items():
            if isinstance(operation, dict) and operation.get("operationId"):
                ids[(method.upper(), path)] = operation["operationId"]
    return ids


def served_route_table(api: Any) -> list[dict]:
    """Every served (method, path) in match order, with where its handler lives."""
    from starlette.routing import Mount

    operation_ids = _operation_ids(api)
    rows: list[dict] = []
    for route in _route_contexts(api):
        path = getattr(route, "path", None)
        if isinstance(getattr(route, "original_route", route), Mount) or isinstance(route, Mount):
            app = getattr(route, "app", None)
            rows.append({"method": "MOUNT", "path": path, "endpoint": type(app).__name__, "source": None,
                         "status_code": None, "response_model": None, "include_in_schema": False,
                         "operation_id": None})
            continue
        methods = set(getattr(route, "methods", None) or ())
        if "GET" in methods:
            methods.discard("HEAD")
        endpoint = getattr(route, "endpoint", None)
        for method in sorted(methods) or ["?"]:
            rows.append({
                "method": method,
                "path": path,
                "endpoint": getattr(endpoint, "__name__", None),
                "source": _source_of(endpoint) if endpoint is not None else None,
                "status_code": getattr(route, "status_code", None),
                "response_model": _type_name(getattr(route, "response_model", None)),
                "include_in_schema": bool(getattr(route, "include_in_schema", True)),
                "operation_id": operation_ids.get((method, getattr(route, "path_format", None) or path)),
            })
    for ordinal, row in enumerate(rows):
        row["ordinal"] = ordinal
    return rows


def runtime_route_payload(api: Any) -> dict:
    return {"version": 1, "routes": served_route_table(api)}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the full server with a fake WanGP and check its served routes.")
    parser.add_argument("--write", action="store_true", help=f"refresh {RUNTIME_ROUTE_FIXTURE.relative_to(ROOT)}")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="hocus-routes-") as state:
        previous = os.getcwd()
        os.chdir(state)
        try:
            payload = runtime_route_payload(load_full_server(Path(state)).api)
        finally:
            os.chdir(previous)
    if args.write:
        _write_json(RUNTIME_ROUTE_FIXTURE, payload)
        print(f"wrote {len(payload['routes'])} served routes to {RUNTIME_ROUTE_FIXTURE.relative_to(ROOT)}")
        return 0
    current = json.loads(RUNTIME_ROUTE_FIXTURE.read_text(encoding="utf-8")) if RUNTIME_ROUTE_FIXTURE.exists() else None
    if current != payload:
        print(f"{RUNTIME_ROUTE_FIXTURE.relative_to(ROOT)} is stale. Run scripts/architecture_contracts.py --write and review the diff.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
