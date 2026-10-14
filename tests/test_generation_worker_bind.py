"""The generation worker modules get everything they use from the full server through one bind call.

``app/services/generation_worker/*.py`` hold the bodies of ``_run_generation`` and its phases. A name such as
``update_job`` or ``_workspace_dir`` that a body reads is either imported by the module (standard library, torch,
``services``, ``shared``) or injected by ``bind`` from the keyword arguments of ``bind_generation_worker`` in
``app/_launch_runtime.py``. These checks read the source (nothing is imported), like
``test_a_server_never_reads_a_name_it_does_not_define`` does for the launch module, and fail when a name a worker
module reads would resolve to nothing: a name the module neither defines nor declares, a declared name ``bind`` does
not assign, or a bound name the full server does not pass.
"""
from __future__ import annotations

import ast
import builtins
import symtable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "app" / "services" / "generation_worker"
LAUNCH = ROOT / "app" / "_launch_runtime.py"


def worker_files() -> list[Path]:
    return sorted(path for path in PACKAGE.glob("*.py") if path.name != "__init__.py")


def module_scope_names(table: symtable.SymbolTable) -> set[str]:
    return {s.get_name() for s in table.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}


def read_globals(table: symtable.SymbolTable) -> dict[str, str]:
    """Names that functions of the module read and that resolve to module globals, with a function that reads each."""
    found: dict[str, str] = {}

    def walk(scope: symtable.SymbolTable) -> None:
        for child in scope.get_children():
            if child.get_type() == "function":
                for symbol in child.get_symbols():
                    if symbol.is_global() and symbol.is_referenced():
                        found.setdefault(symbol.get_name(), child.get_name())
            walk(child)

    walk(table)
    return found


def injected_names(tree: ast.Module) -> set[str]:
    """Module-level ``name = None`` declarations: the names ``bind`` fills in."""
    return {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value is None
        for target in node.targets if isinstance(target, ast.Name)
    }


def bind_function(tree: ast.Module) -> ast.FunctionDef:
    return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "bind")


def bound_keys(tree: ast.Module) -> set[str]:
    return {
        node.slice.value for node in ast.walk(bind_function(tree))
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "names"
    }


def declared_global(tree: ast.Module) -> set[str]:
    return {name for node in ast.walk(bind_function(tree)) if isinstance(node, ast.Global) for name in node.names}


def test_there_are_worker_modules_to_check() -> None:
    assert [path.name for path in worker_files()], "app/services/generation_worker has no modules"


def test_every_global_a_worker_function_reads_is_defined_imported_or_injected() -> None:
    for path in worker_files():
        source = path.read_text(encoding="utf-8")
        table = symtable.symtable(source, str(path), "exec")
        known = module_scope_names(table) | set(dir(builtins))
        missing = {name: reader for name, reader in read_globals(table).items() if name not in known}
        assert not missing, (
            f"{path.name} reads names nothing defines (add them to the module's injected names and to "
            f"bind_generation_worker in app/_launch_runtime.py): {missing}"
        )


def test_bind_assigns_exactly_the_injected_names_and_declares_them_global() -> None:
    for path in worker_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        injected = injected_names(tree)
        assert bound_keys(tree) == injected, (
            f"{path.name}: names declared None but not bound, or bound but not declared: "
            f"{sorted(injected ^ bound_keys(tree))}"
        )
        assert injected <= declared_global(tree), (
            f"{path.name}: bind assigns without `global` (a local would be set instead): "
            f"{sorted(injected - declared_global(tree))}"
        )


def test_the_full_server_passes_every_name_the_worker_modules_inject() -> None:
    wanted = set()
    for path in worker_files():
        wanted |= bound_keys(ast.parse(path.read_text(encoding="utf-8")))
    launch = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(launch)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "bind_generation_worker"
    ]
    assert len(calls) == 1, "app/_launch_runtime.py must call bind_generation_worker exactly once"
    passed = {keyword.arg for keyword in calls[0].keywords}
    assert wanted <= passed, f"bind_generation_worker is not given: {sorted(wanted - passed)}"


def test_the_package_binds_every_worker_module() -> None:
    tree = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    entry = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "bind_generation_worker")
    bound = {
        node.func.value.id for node in ast.walk(entry)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "bind"
        and isinstance(node.func.value, ast.Name)
    }
    assert bound == {path.stem for path in worker_files()}


# Services this slice binds once from launch. The names are read from each module, not listed here.
BOUND_SERVICES = (
    (ROOT / "app" / "services" / "generation_jobs.py", "bind_generation_jobs"),
    (ROOT / "app" / "services" / "generation_recovery.py", "bind_generation_recovery"),
    (ROOT / "app" / "services" / "generation_preparation.py", "bind_generation_preparation"),
)


def _service_tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_every_global_a_bound_service_reads_is_defined_imported_or_injected() -> None:
    for path, _bind_name in BOUND_SERVICES:
        source = path.read_text(encoding="utf-8")
        table = symtable.symtable(source, str(path), "exec")
        known = module_scope_names(table) | set(dir(builtins))
        missing = {name: reader for name, reader in read_globals(table).items() if name not in known}
        assert not missing, f"{path.name} reads names nothing defines: {missing}"


def test_each_bound_service_assigns_exactly_its_injected_names() -> None:
    for path, _bind_name in BOUND_SERVICES:
        tree = _service_tree(path)
        injected = injected_names(tree)
        assert injected, path.name
        assert bound_keys(tree) == injected, (
            f"{path.name}: names declared None but not bound, or bound but not declared: "
            f"{sorted(injected ^ bound_keys(tree))}"
        )
        assert injected <= declared_global(tree), (
            f"{path.name}: bind assigns without `global`: {sorted(injected - declared_global(tree))}"
        )


def test_the_full_server_passes_every_name_a_bound_service_injects() -> None:
    launch = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    for path, bind_name in BOUND_SERVICES:
        wanted = bound_keys(_service_tree(path))
        calls = [
            node for node in ast.walk(launch)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == bind_name
        ]
        assert len(calls) == 1, f"app/_launch_runtime.py must call {bind_name} exactly once"
        passed = {keyword.arg for keyword in calls[0].keywords}
        assert wanted <= passed, f"{bind_name} is not given: {sorted(wanted - passed)}"
        defined_after: set[str] = set()
        call = calls[0]
        for node in launch.body:
            if node.lineno <= call.lineno:
                continue
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                defined_after.add(node.name)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                defined_after |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
            elif isinstance(node, ast.Assign):
                defined_after |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        for keyword in call.keywords:
            if keyword.arg in defined_after:
                assert isinstance(keyword.value, ast.Lambda), (
                    f"{keyword.arg} is defined after {bind_name}; pass a forwarder"
                )


def test_a_name_defined_after_the_bind_call_is_passed_as_a_forwarder() -> None:
    """A direct value would be captured before the name exists; the module would fail to import."""
    launch = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    call = next(
        node for node in ast.walk(launch)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "bind_generation_worker"
    )
    defined_after: set[str] = set()
    for node in launch.body:
        if node.lineno <= call.lineno:
            continue
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined_after.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            defined_after |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
        elif isinstance(node, ast.Assign):
            defined_after |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    for keyword in call.keywords:
        if keyword.arg in defined_after:
            assert isinstance(keyword.value, ast.Lambda), f"{keyword.arg} is defined after the bind call; pass a forwarder"
