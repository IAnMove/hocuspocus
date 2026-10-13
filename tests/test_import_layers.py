"""Import layers of the backend: who may import whom (refactor design rules R1, R2 and R4).

Static checks over the source, in the style of
``tests/test_architecture_contracts.py``: nothing here imports the runtime.

- R1: a module under ``app/services`` must not import ``routers``. The set of
  current violations is frozen below. It may only shrink: a new violation
  fails, and so does a baseline entry whose import is gone (delete it).
- R2: nothing but the composition roots imports ``launch``, ``_launch_runtime``
  or ``core_runtime``. Same frozen baseline.
- R4: the kernel (``app/services/kernel``) imports, from this code base, only
  itself, ``services.resource_scheduler``, ``services.job_lifecycle`` and
  ``services.generation``, plus the few named leaf services below. A leaf is
  allowed only while nothing it reaches is a router, a composition root or
  ``wgp``. Anything else the kernel needs arrives as an argument.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
SERVICES = APP / "services"
KERNEL = SERVICES / "kernel"

# R1. Services that import a router today. Only ever delete entries.
SERVICES_IMPORTING_ROUTERS = {
    ("app/services/core_generation_commands.py", "routers.system_capabilities"),
    ("app/services/core_production.py", "routers.system_capabilities"),
    ("app/services/core_remote_3d.py", "routers.system_capabilities"),
    ("app/services/model3d_commands.py", "routers.wangp_mcp"),
    ("app/services/series_kit_pins.py", "routers.series_library"),
    ("app/services/series_video_shots.py", "routers.series_library"),
}

# R2. Code that imports a composition root today (the roots themselves are exempt).
COMPOSITION_ROOTS = {"launch", "_launch_runtime", "core_runtime"}
IMPORTING_A_COMPOSITION_ROOT = {
    ("app/services/director_pipeline.py", "launch"),
}

# R4. What the kernel may import besides the standard library and third-party packages.
KERNEL_PACKAGES = ("services.kernel", "services.generation")
KERNEL_MODULES = {"services.resource_scheduler", "services.job_lifecycle"}
# Leaf services the moved code already used. Each one reaches no router, no
# composition root and no wgp (test_kernel_leaf_services_reach_no_slice).
KERNEL_LEAF_SERVICES = {
    "services.durable_generation_queue": "the file-backed queue the generation queue owns",
    "services.execution_mode": "the execution-mode check made when a job is built",
    "services.media_paths": "the request media path policy that PathPolicy wraps",
    "services.task_manager": "the canonical task store that TaskRegistry opens",
    "services.upload_stream": "the upload streaming and transcoding that PathPolicy wraps",
}
# R4 violations that cannot be injected without rewriting a moved body. Only ever delete entries.
KERNEL_IMPORTING_A_SLICE = {
    # GenerationQueue.new_job applies the MiniMax H3 dialogue duration contract inline;
    # it goes with the engine port.
    ("app/services/kernel/jobs.py", "services.minimax_h3_duration"),
}


def _first_party_roots() -> set[str]:
    roots = {path.stem for path in APP.glob("*.py")}
    for path in APP.iterdir():
        if path.is_dir() and path.name != "env" and any(path.rglob("*.py")):
            roots.add(path.name)
    return roots


def _module_file(module: str) -> Path | None:
    base = APP.joinpath(*module.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def imported_modules(tree: ast.AST, package: str = "") -> set[str]:
    """The modules a source imports, in any scope.

    ``from services import resource_scheduler`` names ``services.resource_scheduler``
    (a submodule) and ``from services.kernel.paths import safe_join`` names
    ``services.kernel.paths`` (``safe_join`` is a member). A relative import is
    resolved against ``package``. ``import_module("a.b")`` and ``__import__("a.b")``
    with a literal name count too.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".") if package else []
                base = base[: len(base) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            submodules = {
                f"{module}.{alias.name}" if module else alias.name
                for alias in node.names
                if alias.name != "*" and _module_file(f"{module}.{alias.name}" if module else alias.name)
            }
            found.update(submodules)
            if module and len(submodules) < len(node.names):
                found.add(module)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            argument = node.args[0]
            if name in {"import_module", "__import__"} and isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                found.add(argument.value)
    return found


def _under(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _scan(folder: Path) -> list[tuple[str, set[str]]]:
    rows = []
    for path in sorted(folder.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        package = ".".join(path.relative_to(APP).with_suffix("").parts[:-1])
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        rows.append((relative, imported_modules(tree, package)))
    return rows


def test_services_do_not_import_routers_beyond_the_frozen_baseline() -> None:
    found = {
        (relative, module)
        for relative, modules in _scan(SERVICES)
        for module in modules
        if _under(module, "routers")
    }
    assert found - SERVICES_IMPORTING_ROUTERS == set(), (
        "A service must not import a router (R1). Move the shared code into services/, "
        f"or pass it in. New: {sorted(found - SERVICES_IMPORTING_ROUTERS)!r}"
    )
    assert SERVICES_IMPORTING_ROUTERS - found == set(), (
        "These baseline entries are fixed; delete them from SERVICES_IMPORTING_ROUTERS: "
        f"{sorted(SERVICES_IMPORTING_ROUTERS - found)!r}"
    )


def test_only_the_composition_roots_import_a_composition_root() -> None:
    found = {
        (relative, module)
        for folder in ("services", "routers", "shared")
        for relative, modules in _scan(APP / folder)
        for module in modules
        if module in COMPOSITION_ROOTS
    }
    assert found - IMPORTING_A_COMPOSITION_ROOT == set(), (
        "Only the composition roots may import launch, _launch_runtime or core_runtime (R2). "
        f"New: {sorted(found - IMPORTING_A_COMPOSITION_ROOT)!r}"
    )
    assert IMPORTING_A_COMPOSITION_ROOT - found == set(), (
        "These baseline entries are fixed; delete them from IMPORTING_A_COMPOSITION_ROOT: "
        f"{sorted(IMPORTING_A_COMPOSITION_ROOT - found)!r}"
    )


def _kernel_allows(module: str) -> bool:
    return (
        any(_under(module, package) for package in KERNEL_PACKAGES)
        or module in KERNEL_MODULES
        or module in KERNEL_LEAF_SERVICES
    )


def _kernel_first_party_imports() -> set[tuple[str, str]]:
    roots = _first_party_roots()
    return {
        (relative, module)
        for relative, modules in _scan(KERNEL)
        for module in modules
        if module.split(".")[0] in roots and not _kernel_allows(module)
    }


def test_kernel_imports_only_what_the_layer_allows() -> None:
    found = _kernel_first_party_imports()
    assert found - KERNEL_IMPORTING_A_SLICE == set(), (
        "services/kernel may import only services.kernel.*, services.resource_scheduler, services.job_lifecycle, "
        "services.generation and the named leaf services (R4). Pass anything else in as an argument. "
        f"New: {sorted(found - KERNEL_IMPORTING_A_SLICE)!r}"
    )
    assert KERNEL_IMPORTING_A_SLICE - found == set(), (
        "These baseline entries are fixed; delete them from KERNEL_IMPORTING_A_SLICE: "
        f"{sorted(KERNEL_IMPORTING_A_SLICE - found)!r}"
    )


def _first_party_closure(modules: set[str]) -> set[str]:
    roots = _first_party_roots()
    seen: set[str] = set()
    todo = sorted(modules)
    while todo:
        module = todo.pop()
        if module in seen or module.split(".")[0] not in roots:
            continue
        seen.add(module)
        path = _module_file(module)
        if path is None:
            continue
        package = ".".join(path.relative_to(APP).with_suffix("").parts[:-1])
        todo.extend(imported_modules(ast.parse(path.read_text(encoding="utf-8")), package))
    return seen


def test_kernel_leaf_services_reach_no_slice() -> None:
    reached = _first_party_closure(
        set(KERNEL_LEAF_SERVICES) | KERNEL_MODULES | {"services.generation"} | {
            f"services.kernel.{path.stem}" for path in KERNEL.glob("*.py") if path.stem != "__init__"
        }
    )
    forbidden = {
        module for module in reached
        if module.split(".")[0] in {"routers", "wgp"} or module.split(".")[0] in COMPOSITION_ROOTS
    }
    assert forbidden == set(), f"The kernel reaches a router, wgp or a composition root: {sorted(forbidden)!r}"
    assert set(KERNEL_LEAF_SERVICES) <= reached


def test_import_scan_names_every_form() -> None:
    tree = ast.parse(
        "\n".join([
            "import routers.uploads",
            "from routers import lan_auth",
            "from routers.system_capabilities import require_capability_http",
            "from services import resource_scheduler, job_lifecycle",
            "from . import paths",
            "from .config import ConfigStore",
            "def late():",
            "    from launch import _get_cached_hardware",
            "    importlib.import_module('routers.series_library')",
            "    __import__('routers.wangp_mcp')",
            "    importlib.import_module(name)",
        ])
    )
    assert imported_modules(tree, "services.kernel") == {
        "routers.uploads",
        "routers.lan_auth",
        "routers.system_capabilities",
        "services.resource_scheduler",
        "services.job_lifecycle",
        "services.kernel.paths",
        "services.kernel.config",
        "launch",
        "routers.series_library",
        "routers.wangp_mcp",
    }


def test_the_baselines_name_files_that_exist() -> None:
    for relative, _module in SERVICES_IMPORTING_ROUTERS | KERNEL_IMPORTING_A_SLICE | IMPORTING_A_COMPOSITION_ROOT:
        assert (ROOT / relative).is_file(), relative
    for module in KERNEL_LEAF_SERVICES:
        assert _module_file(module) is not None, module
