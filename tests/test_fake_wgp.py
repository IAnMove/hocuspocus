"""The fake WanGP (tests/support/fake_wgp.py) may not drift from the real app/wgp.py.

Importing wgp needs the GPU stack, so these tests read its source instead:

- every attribute the fake gives is a module-level name of ``app/wgp.py``
  (``fl`` is the files locator module, so its functions are read from there);
- a fake function stands for a real function, takes its parameters in the same
  order (a leading ``_`` marks one the fake ignores), needs no more arguments,
  and has the same plain default values. A fake with ``*args, **kwargs``
  accepts any call.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
from types import SimpleNamespace

from tests.support.fake_wgp import APP_DIR, catalog_attributes, make_fake_wgp

WGP = APP_DIR / "wgp.py"
# Attributes the fake keeps as a namespace, and the real module they stand for.
NAMESPACES = {"fl": APP_DIR / "shared" / "utils" / "files_locator.py"}
_PLAIN = (type(None), bool, int, float, str)


def _module_names(path: Path) -> dict[str, ast.AST]:
    """Module-level names (in module-level if/try/with blocks too, and ``global`` ones) and their nodes."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: dict[str, ast.AST] = {}

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.setdefault(node.name, node)
            elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for item in ast.walk(target):
                        if isinstance(item, ast.Name):
                            names.setdefault(item.id, node)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.setdefault(alias.asname or alias.name.split(".")[0], node)
            elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for block in ("body", "orelse", "finalbody"):
                    visit(getattr(node, block, []))
                for handler in getattr(node, "handlers", []):
                    visit(handler.body)

    visit(tree.body)
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            for name in node.names:
                names.setdefault(name, node)
    return names


def _signature_problems(name: str, fake, real: ast.FunctionDef) -> list[str]:
    real_args = real.args
    real_names = [arg.arg for arg in (*real_args.posonlyargs, *real_args.args)]
    real_defaults = dict(zip(real_names[len(real_names) - len(real_args.defaults):], real_args.defaults))
    parameters = list(inspect.signature(fake).parameters.values())
    named = [item for item in parameters if item.kind in (item.POSITIONAL_ONLY, item.POSITIONAL_OR_KEYWORD)]
    takes_anything = {item.kind for item in parameters} >= {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
    problems = []
    for position, parameter in enumerate(named):
        if position >= len(real_names):
            if parameter.default is parameter.empty:
                problems.append(f"{name}: needs {parameter.name!r}, which wgp's {name} does not take")
            continue
        if parameter.name.lstrip("_") != real_names[position]:
            problems.append(f"{name}: parameter {position} is {parameter.name!r}, wgp names it {real_names[position]!r}")
        real_default = real_defaults.get(real_names[position])
        if real_default is None:
            if parameter.default is not parameter.empty:
                problems.append(f"{name}: {parameter.name!r} has a default; in wgp it is required")
            continue
        if parameter.default is parameter.empty:
            problems.append(f"{name}: {parameter.name!r} is required; in wgp it has a default")
            continue
        try:
            value = ast.literal_eval(real_default)
        except ValueError:
            continue
        if isinstance(value, _PLAIN) and parameter.default != value:
            problems.append(f"{name}: {parameter.name!r} defaults to {parameter.default!r}; wgp's default is {value!r}")
    if len(named) < len(real_names) and not takes_anything:
        problems.append(f"{name}: takes {len(named)} of wgp's parameters {real_names}; add the rest")
    return problems


def _fake_attributes(tmp_path: Path) -> dict[str, object]:
    fake = make_fake_wgp(tmp_path)
    attributes = {name: value for name, value in vars(fake).items() if not name.startswith("__")}
    attributes.update(catalog_attributes())
    return attributes


def _drift(name: str, value: object, real_names: dict[str, ast.AST], where: str) -> list[str]:
    if name not in real_names:
        return [f"{name} is not a module-level name of {where}"]
    real = real_names[name]
    if isinstance(value, SimpleNamespace) and name in NAMESPACES:
        inner = _module_names(NAMESPACES[name])
        source = NAMESPACES[name].relative_to(APP_DIR).as_posix()
        return [problem for key, item in vars(value).items() for problem in _drift(key, item, inner, source)]
    if inspect.isfunction(value):
        if not isinstance(real, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return [f"{name} is a function in the fake but not in {where}"]
        return _signature_problems(name, value, real)
    if isinstance(real, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [f"{name} is a function in {where} but {type(value).__name__} in the fake"]
    return []


def test_the_fake_names_and_signatures_match_wgp(tmp_path) -> None:
    real_names = _module_names(WGP)
    problems = [
        problem
        for name, value in sorted(_fake_attributes(tmp_path).items())
        for problem in _drift(name, value, real_names, "app/wgp.py")
    ]
    assert problems == [], "tests/support/fake_wgp.py drifted from WanGP:\n" + "\n".join(problems)


def test_the_drift_check_sees_a_renamed_or_reshaped_function() -> None:
    real = ast.parse(
        "def get_model_recursive_prop(model_type, prop='URLs', sub_prop_name=None, return_list=True, stack=[]):\n"
        "    pass\n"
    ).body[0]
    names = {"get_model_recursive_prop": real}

    def short(model_type, prop, return_list=False):
        return None

    def same(model_type, prop="URLs", sub_prop_name=None, return_list=True, stack=()):
        return None

    problems = _drift("get_model_recursive_prop", short, names, "wgp")
    assert any("'prop' is required" in item for item in problems)
    assert any("parameter 2 is 'return_list', wgp names it 'sub_prop_name'" in item for item in problems)
    assert any("add the rest" in item for item in problems)
    assert _drift("get_model_recursive_prop", same, names, "wgp") == []
    assert _drift("get_model_recursive_prop", lambda *args, **kwargs: None, names, "wgp") == []
    assert _drift("renamed_in_wgp", same, names, "wgp") == ["renamed_in_wgp is not a module-level name of wgp"]
