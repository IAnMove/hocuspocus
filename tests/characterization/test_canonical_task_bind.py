"""After the full server has imported, every name the canonical task modules read is the server's own object."""
from __future__ import annotations

import ast
import builtins
import importlib
import symtable
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[2] / "app" / "services"


def _modules():
    """Modules that define ``bind``. ``canonical_task_helpers`` is an older helper and is not one of them."""
    for path in sorted(SERVICES.glob("canonical_task_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(node, ast.FunctionDef) and node.name == "bind" for node in tree.body):
            yield path, importlib.import_module(f"services.{path.stem}")


def _injected(tree: ast.Module) -> list[str]:
    return [
        target.id for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value is None
        for target in node.targets if isinstance(target, ast.Name)
    ]


def _exported(tree: ast.Module) -> list[str]:
    """Functions the move took out of launch. ``bind`` is the module's own entry point."""
    return [
        node.name for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name != "bind"
    ]


def _read_globals(source: str) -> set[str]:
    """Names that the module's functions read as module globals."""
    found: set[str] = set()

    def walk(scope: symtable.SymbolTable) -> None:
        for child in scope.get_children():
            if child.get_type() == "function":
                found.update(s.get_name() for s in child.get_symbols() if s.is_global() and s.is_referenced())
            walk(child)

    walk(symtable.symtable(source, "canonical", "exec"))
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
    for path, module in _modules():
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        injected = _injected(tree)
        assert injected, path.name
        for name in injected:
            value = getattr(module, name)
            assert value is not None, f"{path.stem}.{name} was never bound"
            assert hasattr(launch, name), f"{path.stem}.{name}: the full server has no {name}"
            checked += 1
            if _is_forwarder(value, launch):
                # A name the server defines after the bind call: the forwarder must reach the server's name when it
                # runs, not an object captured earlier.
                assert name in value.__code__.co_names, f"{path.stem}.{name} forwards to {value.__code__.co_names}"
                calls = []
                monkeypatch.setattr(launch, name, lambda *args, **kwargs: calls.append((args, kwargs)) or "forwarded")
                assert value("probe", flag=True) == "forwarded" and calls == [(("probe",), {"flag": True})]
                monkeypatch.undo()
                continue
            # Every other value (functions included) is the very object the rest of the server uses.
            assert value is getattr(launch, name), f"{path.stem}.{name} is not the server's object"
        # Names a module imports itself (math, os, time, datetime, ...) are the server's too:
        # the module must not call a same-named object the server does not use.
        for name in sorted(_read_globals(source) - set(injected)):
            if hasattr(builtins, name) or not hasattr(launch, name) or not hasattr(module, name):
                continue
            assert getattr(module, name) is getattr(launch, name), (
                f"{path.stem}.{name} is not the object the full server binds to {name}"
            )
            checked += 1
        for name in _exported(tree):
            assert getattr(launch, name) is getattr(module, name), (
                f"launch.{name} is not {path.stem}.{name}: the server must re-export the moved function"
            )
            checked += 1
    assert checked > 0
