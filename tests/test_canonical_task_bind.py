"""The canonical task modules get everything they use from the full server through one bind call.

``app/services/canonical_task_*.py`` hold the field helpers, the publishers and the sync and
control functions that moved out of ``app/_launch_runtime.py``. A name a body reads is either
imported by the module (standard library, ``services``) or injected by ``bind`` from the
keyword arguments of that module's one ``bind(...)`` call in ``app/_launch_runtime.py``.
These checks read the source (nothing is imported), like
``test_a_server_never_reads_a_name_it_does_not_define`` does for the launch module, and fail
when a name a module reads would resolve to nothing: a name the module neither defines nor
declares, a declared name ``bind`` does not assign, or a bound name the full server does not
pass. The lists come from the source. Nothing here is a hand-written roster of names.
"""
from __future__ import annotations

import ast
import builtins
import symtable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "app" / "services"
LAUNCH = ROOT / "app" / "_launch_runtime.py"


def module_files() -> list[Path]:
    """Canonical-task modules that take a ``bind`` call.

    ``canonical_task_helpers.py`` is an older shared helper. It has no ``bind`` and
    is not part of this move. Publishers and sync appear here once they exist.
    """
    found = []
    for path in sorted(SERVICES.glob("canonical_task_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.FunctionDef) and node.name == "bind" for node in tree.body):
            found.append(path)
    return found


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
        and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)
    }


def declared_global(tree: ast.Module) -> set[str]:
    return {name for node in ast.walk(bind_function(tree)) if isinstance(node, ast.Global) for name in node.names}


def bind_calls(launch: ast.Module, module_name: str) -> list[ast.Call]:
    """Module-level ``<module>.bind(...)`` calls. A call nested in a function does not count."""
    found: list[ast.Call] = []
    for node in launch.body:
        call = node.value if isinstance(node, ast.Expr) else None
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr != "bind" or not isinstance(call.func.value, ast.Name):
            continue
        if call.func.value.id == module_name:
            found.append(call)
    return found


def defined_after(launch: ast.Module, line: int) -> set[str]:
    """Names the launch module assigns after ``line`` (a direct value would not exist at the call)."""
    names: set[str] = set()
    for node in launch.body:
        if node.lineno <= line:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
        elif isinstance(node, ast.Assign):
            names |= {target.id for target in node.targets if isinstance(target, ast.Name)}
    return names


def test_there_are_canonical_task_modules_to_check() -> None:
    assert [path.name for path in module_files()], "app/services has no canonical_task_*.py modules"


def test_every_global_a_function_reads_is_defined_imported_or_injected() -> None:
    for path in module_files():
        source = path.read_text(encoding="utf-8")
        table = symtable.symtable(source, str(path), "exec")
        known = module_scope_names(table) | set(dir(builtins))
        missing = {name: reader for name, reader in read_globals(table).items() if name not in known}
        assert not missing, (
            f"{path.name} reads names nothing defines (add them to the module's injected names and to "
            f"its bind(...) call in app/_launch_runtime.py): {missing}"
        )


def test_bind_assigns_exactly_the_injected_names_and_declares_them_global() -> None:
    for path in module_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        injected = injected_names(tree)
        assert injected, f"{path.name} declares no injected names"
        assert bound_keys(tree) == injected, (
            f"{path.name}: names declared None but not bound, or bound but not declared: "
            f"{sorted(injected ^ bound_keys(tree))}"
        )
        assert injected <= declared_global(tree), (
            f"{path.name}: bind assigns without `global` (a local would be set instead): "
            f"{sorted(injected - declared_global(tree))}"
        )


def test_the_full_server_calls_each_module_bind_once_with_exactly_those_names() -> None:
    launch = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    for path in module_files():
        injected = injected_names(ast.parse(path.read_text(encoding="utf-8")))
        calls = bind_calls(launch, path.stem)
        assert len(calls) == 1, f"app/_launch_runtime.py must call {path.stem}.bind exactly once"
        call = calls[0]
        assert not call.args, f"{path.stem}.bind takes keyword arguments only"
        passed = {keyword.arg for keyword in call.keywords}
        assert passed == injected, (
            f"{path.stem}.bind keywords are not the module's injected names: "
            f"{sorted(passed ^ injected)}"
        )
        later = defined_after(launch, call.lineno)
        for keyword in call.keywords:
            if keyword.arg in later:
                assert isinstance(keyword.value, ast.Lambda), (
                    f"{keyword.arg} is defined after {path.stem}.bind; pass a forwarder"
                )
                loaded = {
                    node.id for node in ast.walk(keyword.value)
                    if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
                }
                assert keyword.arg in loaded, f"{path.stem}.bind forwarder for {keyword.arg} does not read that name"
            else:
                assert isinstance(keyword.value, ast.Name) and keyword.value.id == keyword.arg, (
                    f"{path.stem}.bind must receive the server's {keyword.arg} object, not a wrapper"
                )


def test_a_name_defined_after_the_bind_call_is_passed_as_a_forwarder() -> None:
    """A direct value would be captured before the name exists; the module would fail to import."""
    launch = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    for path in module_files():
        call = bind_calls(launch, path.stem)[0]
        later = defined_after(launch, call.lineno)
        for keyword in call.keywords:
            if keyword.arg in later:
                assert isinstance(keyword.value, ast.Lambda), (
                    f"{keyword.arg} is defined after {path.stem}.bind; pass a forwarder"
                )
