"""Call-time names from the launch module.

A service that left ``_launch_runtime`` still reads names that live there.
Those names are bound once, as proxies. Each proxy looks the name up in the
launch namespace when the service uses it, so a name defined later in launch,
or patched on ``_launch_runtime`` by a test, is the object the service sees.
"""

import builtins
import symtable
from pathlib import Path


class LaunchName:
    """One launch global, resolved when the service uses it."""

    def __init__(self, namespace: dict, name: str) -> None:
        object.__setattr__(self, "_namespace", namespace)
        object.__setattr__(self, "_name", name)

    def value(self):
        """The object launch holds for this name right now."""
        namespace = object.__getattribute__(self, "_namespace")
        name = object.__getattribute__(self, "_name")
        return namespace[name]

    def __repr__(self) -> str:
        name = object.__getattribute__(self, "_name")
        return f"<launch {name}>"

    def __call__(self, *args, **kwargs):
        return self.value()(*args, **kwargs)

    def __getattr__(self, item: str):
        return getattr(self.value(), item)

    def __setattr__(self, item: str, assigned) -> None:
        setattr(self.value(), item, assigned)

    def __getitem__(self, key):
        return self.value()[key]

    def __setitem__(self, key, assigned) -> None:
        self.value()[key] = assigned

    def __delitem__(self, key) -> None:
        del self.value()[key]

    def __contains__(self, item) -> bool:
        return item in self.value()

    def __iter__(self):
        return iter(self.value())

    def __len__(self) -> int:
        return len(self.value())

    def __bool__(self) -> bool:
        return bool(self.value())

    def __eq__(self, other) -> bool:
        return self.value() == other

    def __ne__(self, other) -> bool:
        return self.value() != other


def _assigned_global(item: symtable.Symbol) -> bool:
    return item.is_declared_global() and item.is_assigned()


def _collect_global_assigns(table: symtable.SymbolTable, bound: set[str]) -> None:
    for item in table.get_symbols():
        if _assigned_global(item):
            bound.add(item.get_name())
    for child in table.get_children():
        _collect_global_assigns(child, bound)


def _bound_names(table: symtable.SymbolTable) -> set[str]:
    bound = {
        item.get_name()
        for item in table.get_symbols()
        if item.is_assigned() or item.is_imported() or item.is_namespace()
    }
    _collect_global_assigns(table, bound)
    return bound


def _is_free_global(table: symtable.SymbolTable, item: symtable.Symbol, bound: set[str]) -> bool:
    name = item.get_name()
    if table.get_type() == "module":
        return False
    if not item.is_global() or not item.is_referenced():
        return False
    if name in bound or name.startswith("__"):
        return False
    return not hasattr(builtins, name)


def _walk_free(table: symtable.SymbolTable, bound: set[str], found: set[str]) -> None:
    for item in table.get_symbols():
        if _is_free_global(table, item, bound):
            found.add(item.get_name())
    for child in table.get_children():
        _walk_free(child, bound, found)


def free_launch_names(source: str) -> tuple[str, ...]:
    """Names a module reads that it does not define, in sorted order."""
    table = symtable.symtable(source, "<module>", "exec")
    found: set[str] = set()
    _walk_free(table, _bound_names(table), found)
    return tuple(sorted(found))


def bind(module, namespace: dict) -> tuple[str, ...]:
    """Point each free name of ``module`` at ``namespace``. One call per module."""
    if hasattr(module, "LAUNCH_NAMES"):
        raise RuntimeError(f"{module.__name__} is already bound")
    source = Path(module.__file__).read_text(encoding="utf-8")
    names = free_launch_names(source)
    module.LAUNCH_NAMES = names
    for name in names:
        setattr(module, name, LaunchName(namespace, name))
    return names
