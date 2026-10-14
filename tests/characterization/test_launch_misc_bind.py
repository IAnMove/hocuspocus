"""After the full server has imported, every name a C9c module reads is the server's own object.

The list of names comes from each module's source (``name = None`` slots, and the functions it defines). A module
this slice has not created yet is skipped. A lambda the server passed is a forwarder: patching the server's name
changes what the next call returns.

The request guards C9c moved stay registered by the full server; the last tests drive them through the served app
(order of the middleware stack, the cross-origin check, the mutation trace and LAN authentication). They do not
depend on where the guard functions live, so they ran unchanged on the server before the move.
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


# The middleware the full server registers, outermost first (Starlette runs the last one registered first).
GUARD_ORDER = (
    "LanAuthMiddleware",
    "ActorHeaderMiddleware",
    "trace_user_mutations",
    "protect_cross_origin_mutations",
    "CORSMiddleware",
    "guard_host",
)
REFUSED = (403, {"detail": "Cross-origin API mutations are not allowed"})
LAN_TOKEN = "lan-token-" + "x" * 30
# (method, Origin header, Host header, refused by the cross-origin check)
ORIGIN_CASES = (
    *[(method, "http://evil.example", "testserver", True) for method in ("POST", "PUT", "PATCH", "DELETE")],
    *[(method, "http://evil.example", "testserver", False) for method in ("GET", "HEAD", "OPTIONS")],
    ("POST", None, "testserver", False),
    ("POST", "http://testserver", "testserver", False),
    ("DELETE", "http://TestServer", "testserver", False),
    ("POST", "http://testserver:8080", "testserver", True),
    ("POST", "http://localhost:5173", "127.0.0.1:42003", False),
    ("PATCH", "http://[::1]:5173", "localhost:42003", False),
    ("POST", "http://127.0.0.1:5173", "192.168.1.5:42003", True),
    ("POST", "http://192.168.1.5:5173", "127.0.0.1:42003", True),
    ("POST", "http://0.0.0.0:5173", "127.0.0.1:42003", True),
    ("PUT", "https://42003.localhost", "192.168.1.5:42003", False),
    ("POST", "http://42003.localhost:8080", "testserver", False),
    ("POST", "http://x42003.localhost", "testserver", True),
    ("POST", "http://42003.localhost.evil.example", "testserver", True),
    ("POST", "http://192.168.1.5:42003", "192.168.1.5:42003", False),
    ("DELETE", "http://192.168.1.5:5173", "192.168.1.5:42003", True),
    ("POST", "http://[bad", "testserver", True),
    ("POST", "null", "testserver", True),
)


def _answer(response) -> tuple:
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, response.text


def _traced(trace_dir: Path) -> list[tuple]:
    import json

    rows = []
    for file in sorted(trace_dir.glob("*.jsonl")):
        for line in file.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("action") == "api_request":
                rows.append((record["phase"], record["method"], record["path"], record.get("status_code")))
    return rows


def test_the_full_server_registers_the_request_guards_in_their_order(full_server) -> None:
    names = [getattr(item.kwargs.get("dispatch"), "__name__", item.cls.__name__)
             for item in full_server.api.user_middleware]
    assert [name for name in names if name in GUARD_ORDER] == list(GUARD_ORDER)
    from services import execution_mode

    handler = full_server.api.exception_handlers[execution_mode.ExecutionModeError]
    assert handler.__name__ == "execution_mode_error_handler"


def test_the_cross_origin_check_refuses_only_mutations_from_another_origin(full_server) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(full_server.api, raise_server_exceptions=False)
    seen = []
    for method, origin, host, refused in ORIGIN_CASES:
        headers = {"host": host} if origin is None else {"host": host, "origin": origin}
        answer = _answer(client.request(method, "/api/v1/__guard_probe__", headers=headers))
        seen.append((method, origin, host, answer == REFUSED))
    assert seen == [(method, origin, host, refused) for method, origin, host, refused in ORIGIN_CASES]


def test_lan_auth_runs_before_the_trace_and_the_trace_before_the_origin_check(
    full_server, monkeypatch, tmp_path,
) -> None:
    """A refused cross-origin mutation is traced; an unauthenticated LAN request never reaches the trace."""
    from fastapi.testclient import TestClient
    from services import debug_trace

    trace_dir = tmp_path / "trace"
    monkeypatch.setattr(debug_trace, "_log_dir", lambda: str(trace_dir))
    monkeypatch.setitem(full_server.wgp.server_config, "services", {
        **full_server.wgp.server_config.get("services", {}), "debug_trace_enabled": True,
    })
    local = TestClient(full_server.api, raise_server_exceptions=False)
    assert _answer(local.post("/api/v1/__guard_probe__/refused", headers={"origin": "http://evil.example"},
                              json={"api_key": "secret"})) == REFUSED
    assert local.post("/api/v1/__guard_probe__/same", json={}).status_code == 404
    assert local.get("/api/v1/__guard_probe__/read").status_code == 404

    for name, value in (("PINOKIO_SHARE_LOCAL", "1"), ("LOREFRAME_LAN_AUTH", "1"), ("LOREFRAME_LAN_TOKEN", LAN_TOKEN)):
        monkeypatch.setenv(name, value)
    remote = TestClient(full_server.api, raise_server_exceptions=False, client=("192.168.1.50", 50000))
    lan = {"host": "192.168.1.5:42003", "origin": "http://evil.example"}
    assert _answer(remote.post("/api/v1/__guard_probe__/lan-no-token", headers=lan, json={})) == (
        401, {"detail": "LAN authentication required"},
    )
    assert _answer(remote.post("/api/v1/__guard_probe__/lan-token", json={},
                               headers={**lan, "authorization": f"Bearer {LAN_TOKEN}"})) == REFUSED

    assert _traced(trace_dir) == [
        ("request", "POST", "/api/v1/__guard_probe__/refused", None),
        ("response", "POST", "/api/v1/__guard_probe__/refused", 403),
        ("request", "POST", "/api/v1/__guard_probe__/same", None),
        ("response", "POST", "/api/v1/__guard_probe__/same", 404),
        ("request", "POST", "/api/v1/__guard_probe__/lan-token", None),
        ("response", "POST", "/api/v1/__guard_probe__/lan-token", 403),
    ]
