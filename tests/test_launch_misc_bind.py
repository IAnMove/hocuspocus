"""The modules moved out of the full server by the C9c slice get their launch objects through one bind call.

``app/services/storage_tools.py``, ``managed_loras.py``, ``model_file_groups.py``,
``generation_option_helpers.py`` and ``request_guards.py`` hold bodies that used to live in
``app/_launch_runtime.py``. A name a body reads is either imported by the module or injected by ``bind`` from the
keyword arguments of the one ``bind_<module>(...)`` call in the full server. These checks read the source (nothing
is imported). A module that this slice has not created yet is skipped, so the same test covers each commit. A
module with no injected names (it imports everything it uses) has no bind call.
"""
from __future__ import annotations

import ast
import builtins
import symtable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "app" / "services"
LAUNCH = ROOT / "app" / "_launch_runtime.py"

# Fixed list. A file that does not exist yet is skipped; deleting the last one fails the test below.
SLICE_MODULES = (
    "storage_tools",
    "managed_loras",
    "model_file_groups",
    "generation_option_helpers",
    "request_guards",
)


def slice_files() -> list[Path]:
    return [SERVICES / f"{name}.py" for name in SLICE_MODULES if (SERVICES / f"{name}.py").is_file()]


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


def bind_function(tree: ast.Module) -> ast.FunctionDef | None:
    found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "bind"]
    assert len(found) <= 1, "a slice module has more than one bind()"
    return found[0] if found else None


def bound_keys(tree: ast.Module) -> set[str]:
    function = bind_function(tree)
    assert function is not None
    return {
        node.slice.value for node in ast.walk(function)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "names"
        and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)
    }


def declared_global(tree: ast.Module) -> set[str]:
    function = bind_function(tree)
    assert function is not None
    return {name for node in ast.walk(function) if isinstance(node, ast.Global) for name in node.names}


def bind_calls(launch: ast.Module, stem: str) -> list[ast.Call]:
    return [
        node for node in ast.walk(launch)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == f"bind_{stem}"
    ]


def defined_after(launch: ast.Module, line: int) -> set[str]:
    """Names whose definition in the full server is below ``line``."""
    found: set[str] = set()
    for node in launch.body:
        if node.lineno <= line:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            found |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
        elif isinstance(node, ast.Assign):
            found |= {target.id for target in node.targets if isinstance(target, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
    return found


def test_the_slice_has_a_module_to_check() -> None:
    assert slice_files(), "none of the C9c modules exist yet"


def test_every_global_a_slice_function_reads_is_defined_imported_or_injected() -> None:
    for path in slice_files():
        source = path.read_text(encoding="utf-8")
        table = symtable.symtable(source, str(path), "exec")
        known = module_scope_names(table) | set(dir(builtins))
        missing = {name: reader for name, reader in read_globals(table).items() if name not in known}
        assert not missing, (
            f"{path.name} reads names nothing defines (add them to the module's injected names and to "
            f"bind_{path.stem} in app/_launch_runtime.py): {missing}"
        )


def test_bind_assigns_exactly_the_injected_names_and_declares_them_global() -> None:
    for path in slice_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        injected = injected_names(tree)
        if not injected:
            assert bind_function(tree) is None, f"{path.name} defines bind() but injects no names"
            continue
        assert bound_keys(tree) == injected, (
            f"{path.name}: names declared None but not bound, or bound but not declared: "
            f"{sorted(injected ^ bound_keys(tree))}"
        )
        assert injected <= declared_global(tree), (
            f"{path.name}: bind assigns without `global` (a local would be set instead): "
            f"{sorted(injected - declared_global(tree))}"
        )


def test_the_full_server_passes_every_injected_name_once_by_keyword() -> None:
    launch = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    for path in slice_files():
        injected = injected_names(ast.parse(path.read_text(encoding="utf-8")))
        calls = bind_calls(launch, path.stem)
        if not injected:
            assert calls == [], f"{path.name} injects nothing, but bind_{path.stem} is called"
            continue
        assert len(calls) == 1, f"app/_launch_runtime.py must call bind_{path.stem} exactly once"
        call = calls[0]
        assert call.args == [], f"bind_{path.stem} takes keyword arguments only"
        assert all(keyword.arg for keyword in call.keywords), f"bind_{path.stem} must not take **keywords"
        passed = {keyword.arg for keyword in call.keywords}
        assert passed == injected, (
            f"bind_{path.stem} keywords {sorted(passed)} are not the injected names {sorted(injected)}"
        )


def test_a_name_defined_after_the_bind_call_is_passed_as_a_forwarder() -> None:
    """A direct value would be captured before the name exists, or before a later rebinding."""
    launch = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    for path in slice_files():
        calls = bind_calls(launch, path.stem)
        if not calls:
            continue
        call = calls[0]
        later = defined_after(launch, call.lineno)
        for keyword in call.keywords:
            if keyword.arg in later:
                assert isinstance(keyword.value, ast.Lambda), (
                    f"{keyword.arg} is defined after bind_{path.stem}; pass a forwarder"
                )
