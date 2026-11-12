"""Read `_run_generation` as the group of functions it is split into.

`_run_generation` keeps the slot, try, except and finally frame and chains through `_run_generation_*` phase
functions. They live in `app/_launch_runtime.py` while they are being moved and in the modules of
`app/services/generation_worker/` once moved. A wiring test that asserts what the worker does reads the whole group, in
chain order, so it does not depend on which file or function holds a statement.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
# The earliest phases are in the launch module until they move, and in prepare.py after that.
FILES = (
    "_launch_runtime.py",
    "services/generation_worker/prepare.py",
    "services/generation_worker/tasks.py",
    "services/generation_worker/finalize.py",
)
# A different worker that merely shares the prefix.
_NOT_A_PHASE = {"_run_generation_with_preparation"}


def _parsed():
    for relative in FILES:
        path = APP / relative
        if path.exists():
            source = path.read_text(encoding="utf-8")
            yield source, ast.parse(source, filename=str(path))


def _is_phase(node: ast.AST) -> bool:
    return isinstance(node, ast.FunctionDef) and (
        node.name == "_run_generation"
        or (node.name.startswith("_run_generation_") and node.name not in _NOT_A_PHASE)
    )


def generation_group() -> list[ast.FunctionDef]:
    """`_run_generation` and its phase functions, in chain order."""
    return [node for _, tree in _parsed() for node in tree.body if _is_phase(node)]


def generation_module() -> ast.Module:
    """The group as one module, for `ast.walk` and for exec of selected statements."""
    return ast.Module(body=generation_group(), type_ignores=[])


def generation_source() -> str:
    """The text of the group, in chain order (order assertions keep their meaning)."""
    return "\n\n".join(
        ast.get_source_segment(source, node)
        for source, tree in _parsed() for node in tree.body if _is_phase(node)
    )


def launch_and_worker_source(launch_source: str) -> str:
    """What the launch module's text was before the worker moved out of it: its source plus the worker's functions."""
    return launch_source + "\n\n" + generation_source()
