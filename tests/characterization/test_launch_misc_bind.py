"""After the full server has imported, every name a C9c module reads is the server's own object.

The list of names comes from each module's source (``name = None`` slots, and the functions it defines). A module
this slice has not created yet is skipped. A lambda the server passed is a forwarder: patching the server's name
changes what the next call returns.
"""
from __future__ import annotations

import ast
import builtins
import importlib
import symtable
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[2] / "app" / "services"
SLICE_MODULES = (
    "storage_tools",
    "managed_loras",
    "model_file_groups",
    "generation_option_helpers",
    "request_guards",
)


def _existing():
    for name in SLICE_MODULES:
        path = SERVICES / f"{name}.py"
        if path.is_file():
            yield path, importlib.import_module(f"services.{name}")


def _injected(tree: ast.Module) -> list[str]:
    return [
        target.id for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value is None
        for target in node.targets if isinstance(target, ast.Name)
    ]


def _functions(tree: ast.Module) -> list[str]:
    return [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != "bind"
    ]


def _read_globals(source: str) -> set[str]:
    found: set[str] = set()

    def walk(scope: symtable.SymbolTable) -> None:
        for child in scope.get_children():
            if child.get_type() == "function":
                found.update(s.get_name() for s in child.get_symbols() if s.is_global() and s.is_referenced())
            walk(child)

    walk(symtable.symtable(source, "slice", "exec"))
    return found


def _is_forwarder(value, launch) -> bool:
    """A lambda written in the launch module: it looks the launch name up each time it is called."""
    code = getattr(value, "__code__", None)
    return (
        code is not None and value.__name__ == "<lambda>"
        and getattr(value, "__globals__", None) is vars(launch)
    )


def test_every_injected_name_is_bound_to_the_servers_object(full_server, monkeypatch) -> None:
    launch = importlib.import_module("_launch_runtime")
    checked = 0
    modules = list(_existing())
    assert modules, "none of the C9c modules exist yet"
    for path, module in modules:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        injected = _injected(tree)
        for name in injected:
            value = getattr(module, name)
            assert value is not None, f"{path.stem}.{name} was never bound"
            assert hasattr(launch, name), f"{path.stem}.{name}: the full server has no {name}"
            checked += 1
            if _is_forwarder(value, launch):
                assert name in value.__code__.co_names, f"{path.stem}.{name} forwards to {value.__code__.co_names}"
                calls = []
                monkeypatch.setattr(launch, name, lambda *args, **kwargs: calls.append((args, kwargs)) or "forwarded")
                assert value("probe", flag=True) == "forwarded" and calls == [(("probe",), {"flag": True})]
                monkeypatch.undo()
                continue
            assert value is getattr(launch, name), f"{path.stem}.{name} is not the server's object"
        for name in sorted(_read_globals(source) - set(injected)):
            if hasattr(builtins, name) or not hasattr(launch, name) or not hasattr(module, name):
                continue
            value = getattr(module, name)
            if name == "__file__":
                # managed_loras points __file__ at the full server so a relative loras_root
                # still resolves under app/. The path is the server's file; the string is new.
                assert Path(value).resolve() == Path(getattr(launch, name)).resolve(), (
                    f"{path.stem}.__file__ is {value}, not the full server's file"
                )
                checked += 1
                continue
            assert getattr(module, name) is getattr(launch, name), (
                f"{path.stem}.{name} is not the object the full server binds to {name}"
            )
            checked += 1
        for name in _functions(tree):
            if not hasattr(launch, name):
                continue
            assert getattr(module, name) is getattr(launch, name), (
                f"{path.stem}.{name} is not the function the full server exports"
            )
            checked += 1
    assert checked > 0
