"""Read `_run_generation` (app/_launch_runtime.py) as the group of functions it is split into.

`_run_generation` keeps the slot, try, except and finally frame and chains through `_run_generation_*` phase
functions. A wiring test that asserts what the worker does reads the whole group, in file order, so it does not
depend on which phase holds a statement.
"""
from __future__ import annotations

import ast

# A different worker that merely shares the prefix.
_NOT_A_PHASE = {"_run_generation_with_preparation"}


def generation_group(tree: ast.Module) -> list[ast.FunctionDef]:
    """`_run_generation` and its phase functions, in file order."""
    return [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and (node.name == "_run_generation"
             or (node.name.startswith("_run_generation_") and node.name not in _NOT_A_PHASE))
    ]


def generation_module(tree: ast.Module) -> ast.Module:
    """The group as one module, for `ast.walk` and for exec of selected statements."""
    return ast.Module(body=generation_group(tree), type_ignores=[])


def generation_source(source: str, tree: ast.Module) -> str:
    """The text of the group, in file order (order assertions keep their meaning)."""
    return "\n\n".join(ast.get_source_segment(source, node) for node in generation_group(tree))
