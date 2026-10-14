"""After the full server has imported, every name the generation worker modules inject is bound."""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "services" / "generation_worker"


def test_every_injected_name_is_bound_to_the_servers_object(full_server) -> None:
    launch = importlib.import_module("_launch_runtime")
    checked = 0
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = importlib.import_module(f"services.generation_worker.{path.stem}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        injected = [
            target.id for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value is None
            for target in node.targets if isinstance(target, ast.Name)
        ]
        assert injected, path.name
        for name in injected:
            assert getattr(module, name) is not None, f"{path.stem}.{name} was never bound"
            checked += 1
            # Values the server defines are the server's own objects; forwarders and library objects are callables.
            if hasattr(launch, name) and not getattr(module, name).__class__.__name__ == "function":
                assert getattr(module, name) is getattr(launch, name), f"{path.stem}.{name} is not the server's object"
    assert checked > 0
