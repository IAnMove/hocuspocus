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

from tests.support.origin_cases import ORIGIN_CASES, REFUSED, refused_by_origin

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
LAN_TOKEN = "lan-token-" + "x" * 30


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
    assert refused_by_origin(client) == list(ORIGIN_CASES)


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


def _trace_records(trace_dir: Path) -> list[dict]:
    import json

    records = []
    for file in sorted(trace_dir.glob("*.jsonl")):
        records.extend(json.loads(line) for line in file.read_text(encoding="utf-8").splitlines())
    return records


def _enable_trace(full_server, monkeypatch, trace_dir: Path) -> None:
    from services import debug_trace

    monkeypatch.setattr(debug_trace, "_log_dir", lambda: str(trace_dir))
    monkeypatch.setitem(full_server.wgp.server_config, "services", {
        **full_server.wgp.server_config.get("services", {}), "debug_trace_enabled": True,
    })


def test_the_trace_records_each_mutation_with_its_body_and_outcome(full_server, monkeypatch, tmp_path) -> None:
    """Every mutating method is traced (request, then response or error); reads and the UI-action route are not."""
    from fastapi.testclient import TestClient

    trace_dir = tmp_path / "trace"
    _enable_trace(full_server, monkeypatch, trace_dir)
    client = TestClient(full_server.api, raise_server_exceptions=False)
    probe = "/api/v1/__guard_probe__"
    assert client.put(f"{probe}/put?token=abc&x=1", json={"api_key": "secret", "prompt": "hi"}).status_code == 404
    assert client.patch(f"{probe}/patch", content=b"hello", headers={"content-type": "text/plain"}).status_code == 404
    assert client.delete(f"{probe}/delete").status_code == 404
    assert client.get(f"{probe}/get").status_code == 404
    assert client.options(f"{probe}/options").status_code == 404
    assert client.post("/api/v1/debug/user-action", json={"control": "probe"}).json() == {"status": "ok"}
    # The reclaim route reads its JSON body without a guard: a broken body is an unhandled error (a 500).
    broken = client.post("/api/v1/storage/duplicates/reclaim", content=b"{broken",
                         headers={"content-type": "application/json"})
    assert (broken.status_code, broken.text) == (500, "Internal Server Error")

    rows = []
    for record in _trace_records(trace_dir):
        if record.get("action") == "ui_control":
            rows.append(("ui_control", record["control"]))
        elif record.get("action") == "api_request":
            detail = {"request": lambda r: (r["query"], r["body"]), "response": lambda r: r["status_code"],
                      "error": lambda r: r["error"]["type"]}[record["phase"]](record)
            rows.append((record["phase"], record["method"], record["path"], detail))
    assert rows == [
        ("request", "PUT", f"{probe}/put", ({"token": "<redacted>", "x": "1"},
                                            {"api_key": "<redacted>", "prompt": "hi"})),
        ("response", "PUT", f"{probe}/put", 404),
        ("request", "PATCH", f"{probe}/patch", ({}, "<text/plain; body omitted>")),
        ("response", "PATCH", f"{probe}/patch", 404),
        ("request", "DELETE", f"{probe}/delete", ({}, None)),
        ("response", "DELETE", f"{probe}/delete", 404),
        ("ui_control", "probe"),
        ("request", "POST", "/api/v1/storage/duplicates/reclaim",
         ({}, {"parse_error": "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"})),
        ("error", "POST", "/api/v1/storage/duplicates/reclaim", "JSONDecodeError"),
    ]


def test_a_request_carries_its_trace_id_in_the_debug_context_only_while_tracing(
    full_server, monkeypatch, tmp_path,
) -> None:
    """Operation logs merge ``debug_trace.current_context()``: a request id appears there only when tracing is on."""
    from types import SimpleNamespace

    from fastapi.testclient import TestClient
    from services import debug_trace

    seen = []
    target = tmp_path / "probe.safetensors"
    target.write_bytes(b"x")

    def protected(_path):
        seen.append(debug_trace.current_context())
        return True

    monkeypatch.setattr(full_server.wgp, "fl", SimpleNamespace(is_protected_path=protected), raising=False)
    client = TestClient(full_server.api, raise_server_exceptions=False)
    route = "/api/v1/storage/duplicates/reclaim"
    assert client.post(route, json={"path": str(target)}).status_code == 403
    trace_dir = tmp_path / "trace"
    _enable_trace(full_server, monkeypatch, trace_dir)
    assert client.post(route, json={"path": str(target)}).status_code == 403
    [request_record, _response] = [r for r in _trace_records(trace_dir) if r.get("action") == "api_request"]
    off, on = ({key: context.get(key) for key in ("request_id", "http_method", "http_path")} for context in seen)
    assert off == {"request_id": None, "http_method": "POST", "http_path": route}
    assert on == {"request_id": request_record["event_id"], "http_method": "POST", "http_path": route}


def test_a_policy_refusal_reaching_the_server_is_a_409_with_its_message(full_server, monkeypatch) -> None:
    """Comic MiniMax generation lets ExecutionModeError through; the server's handler answers it."""
    from fastapi.testclient import TestClient
    from services import execution_mode

    def refuse(workspace, provider):
        raise execution_mode.ExecutionModeError(f"probe refusal for {workspace} via {provider}")

    monkeypatch.setattr(execution_mode, "validate_remote_provider", refuse)
    response = TestClient(full_server.api, raise_server_exceptions=False).post(
        "/api/v1/comics/generate/minimax", json={"workspace": "default", "prompt": "a panel"},
    )
    assert (response.status_code, response.json()) == (
        409, {"detail": "probe refusal for default via minimax-image"},
    )


def test_the_prompt_type_helpers_the_server_exports_strip_flags_without_their_input(full_server) -> None:
    launch = importlib.import_module("_launch_runtime")
    video = launch._normalize_video_prompt_type
    image = launch._normalize_image_prompt_type
    cases = [
        (video, {"video_prompt_type": "IV"}, "V"),
        (video, {"video_prompt_type": "IV", "image_refs": None}, "V"),
        (video, {"video_prompt_type": "IV", "image_refs": []}, "V"),
        (video, {"video_prompt_type": "IV", "image_refs": ()}, "V"),
        (video, {"video_prompt_type": "IV", "image_refs": ""}, "V"),
        (video, {"video_prompt_type": "IV", "image_refs": ["ref.png"]}, "IV"),
        (video, {"video_prompt_type": "V"}, "V"),
        (image, {"image_prompt_type": "SE"}, ""),
        (image, {"image_prompt_type": "SE", "image_start": "start.png"}, "S"),
        (image, {"image_prompt_type": "SE", "image_end": "end.png"}, "E"),
        (image, {"image_prompt_type": "SE", "image_start": [], "image_end": ()}, ""),
        (image, {"image_prompt_type": "SE", "image_start": ["a"], "image_end": "b"}, "SE"),
        (image, {"image_prompt_type": "T"}, "T"),
    ]
    for normalize, body, expected in cases:
        key = "video_prompt_type" if normalize is video else "image_prompt_type"
        changed = dict(body)
        normalize(changed)
        assert changed[key] == expected, (body, changed)
        assert {k: v for k, v in changed.items() if k != key} == {k: v for k, v in body.items() if k != key}
    for untouched in ({}, {"video_prompt_type": ""}, {"video_prompt_type": 5}, {"image_prompt_type": None}):
        body = dict(untouched)
        video(body)
        image(body)
        assert body == untouched


_HF = "https://huggingface.co/acme/probe/resolve/main/"
_PROBE_MODELS = {
    "probe_img": {
        "name": "Probe Image", "image_outputs": True,
        "URLs": [_HF + "probe_bf16.safetensors", {"url": _HF + "probe_fp8.safetensors"}],
        "modules": [[_HF + "te_bf16.safetensors", _HF + "te_int8.safetensors"], {"URLs": [_HF + "vae.safetensors"]},
                    {"URLs": []}, "named_module"],
        "required_model_assets": ["probe/tokenizer.json", "probe/tokenizer.json"],
        "vision_encoder_filename": "probe/vision.safetensors",
        "loras": [_HF + "accel.safetensors"],
    },
    "probe_img_ft": {"name": "Probe Finetune", "image_outputs": True, "URLs": "probe_img"},
}


def _probe_catalog(full_server, monkeypatch) -> None:
    from types import SimpleNamespace

    def recursive(model_type, prop="URLs", sub_prop_name=None, return_list=True, stack=()):
        value = _PROBE_MODELS[model_type].get(prop)
        if isinstance(value, str) and value in _PROBE_MODELS:
            return recursive(value, prop)
        return [] if value is None else value

    present = {"te_int8.safetensors"}
    fake = full_server.wgp
    monkeypatch.setattr(fake, "get_model_def", lambda model_type: _PROBE_MODELS.get(model_type))
    monkeypatch.setattr(fake, "get_model_recursive_prop", recursive, raising=False)
    monkeypatch.setattr(fake, "fl", SimpleNamespace(
        locate_file=lambda name, error_if_none=True: f"/probe/{name}" if name in present else None,
    ), raising=False)
    monkeypatch.setattr(fake, "resolve_lora_path", lambda model_type, name: f"/nowhere/{name}", raising=False)


def test_an_image_command_names_the_missing_model_files(full_server, monkeypatch) -> None:
    """The image command runtime reads ``_missing_image_model_files`` from the server's globals by name."""
    from fastapi.testclient import TestClient

    _probe_catalog(full_server, monkeypatch)
    client = TestClient(full_server.api, raise_server_exceptions=False)

    def submit(model_type: str) -> tuple:
        response = client.post("/api/v1/generation/commands", json={
            "version": 1, "operation": "generation.image", "intent_id": f"probe-readiness-{model_type}",
            "input": {"workspace": "default", "model_type": model_type, "prompt": "p", "resolution": "512x512",
                      "num_inference_steps": 1, "seed": -1, "guidance_scale": 1.0},
        })
        detail = response.json()["detail"]
        return response.status_code, detail.get("code"), detail.get("missing_files")

    # One variant of a group is enough (te_int8 is present); dict entries, dict modules, required assets
    # (once), the vision encoder and the model's LoRAs all count.
    assert submit("probe_img") == (409, "model_unavailable", [
        "probe_bf16.safetensors or probe_fp8.safetensors", "vae.safetensors", "probe/tokenizer.json",
        "probe/vision.safetensors", "accel.safetensors",
    ])
    # A finetune that points at its base needs the base's weights.
    assert submit("probe_img_ft") == (409, "model_unavailable", ["probe_bf16.safetensors or probe_fp8.safetensors"])
    launch = importlib.import_module("_launch_runtime")
    assert launch._model_weight_groups("probe_img_ft", owned_only=True) == []
    assert launch._model_weight_groups("probe_img_ft") == [_PROBE_MODELS["probe_img"]["URLs"]]


def test_the_mcp_model_list_answers_summaries_details_or_one_model(full_server, monkeypatch) -> None:
    from services.model_downloads import list_models
    from services.model_options import get_model_options
    from tests.support.fake_wgp import catalog_attributes

    for name, value in catalog_attributes().items():
        monkeypatch.setattr(full_server.wgp, name, value, raising=False)
    launch = importlib.import_module("_launch_runtime")
    summaries, details = list_models(detail=False), list_models(detail=True)
    assert summaries != details
    assert launch.mcp_model_list({}) == summaries
    assert launch.mcp_model_list("not a dict") == summaries
    assert launch.mcp_model_list({"detail": "yes", "model_type": "  "}) == summaries
    assert launch.mcp_model_list({"detail": True}) == details
    assert launch.mcp_model_list({"model_type": "fake_i2v", "detail": True}) == get_model_options("fake_i2v")


def test_the_h3_and_seed_helpers_the_server_exports(full_server, monkeypatch) -> None:
    """The MiniMax H3, character-sheet and output-seed helpers other clusters call through the server's names."""
    import sys
    from types import ModuleType, SimpleNamespace

    from services import minimax_h3_service

    launch = importlib.import_module("_launch_runtime")
    definitions = {"h3_by_arch": {"architecture": "MiniMax_H3_v2"}, "other": {"architecture": "wan"}}
    monkeypatch.setattr(full_server.wgp, "get_model_def", lambda model_type: definitions.get(model_type))
    is_h3 = launch._is_minimax_h3_model
    assert [is_h3(name) for name in ("minimax_h3", "MiniMax_H3_turbo", " minimax_h3_x ", "h3_by_arch",
                                     "other", "", None, "my_minimax_h3")] == [
        True, True, True, True, False, False, False, False]
    legacy = minimax_h3_service.MODEL_ID
    assert [launch._is_legacy_h3_model(name) for name in (legacy, f" {legacy} ", legacy + "_x", None)] == [
        True, True, False, False]
    engine = minimax_h3_service.CHARACTER_SHEET_ENGINE
    sheet = launch._is_character_sheet_engine
    assert [sheet({"character_sheet_engine": f" {engine} "}), sheet({"character_sheet_engine": "other"}),
            sheet({}), sheet(None), sheet([engine])] == [True, False, False, False, False]

    seed = launch._extract_output_seed
    assert [seed(name) for name in ("clip_seed42_x.mp4", "seed7.png", "a_seed9", "clip_seed42x.mp4",
                                    "clipseed42_x.mp4", "clip_seed.mp4", "clip_seed12_seed34.mp4")] == [
        42, 7, 9, None, None, None, 12]

    # Encoder recommendation: the hardware-aware choice when the model offers it, else the model's default
    # when offered, else the first variant.
    monkeypatch.setattr(launch, "_get_cached_hardware", lambda: {"gpu_vram_gb": 12})
    chosen = []

    def handler_for(answer):
        def recommend(hardware, model_def):
            chosen.append(hardware)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return SimpleNamespace(recommend_text_encoder=recommend)

    monkeypatch.setattr(full_server.wgp, "get_base_model_type", lambda model_type: model_type, raising=False)
    encoder = launch._recommended_minimax_h3_encoder
    variants = {"nvfp4_awq": {}, "int8": {}}
    for answer, model_def, expected in (
        ("int8", {"minimax_h3_text_encoder_variants": variants}, "int8"),
        ("fp4", {"minimax_h3_text_encoder_variants": variants}, "nvfp4_awq"),
        (RuntimeError("no kernel"), {"minimax_h3_text_encoder_variants": variants}, "nvfp4_awq"),
        ("fp4", {"minimax_h3_text_encoder_variants": {"int8": {}, "bf16": {}}}, "int8"),
        ("fp4", {"minimax_h3_text_encoder_variants": variants, "minimax_h3_text_encoder_default": "int8"}, "int8"),
        ("int8", {}, "nvfp4_awq"),
        ("int8", {"minimax_h3_text_encoder_default": "bf16"}, "bf16"),
    ):
        monkeypatch.setattr(full_server.wgp, "get_model_handler", lambda base, _a=answer: handler_for(_a), raising=False)
        assert encoder("h3_by_arch", model_def) == expected, (answer, model_def)
    assert chosen and all(hardware == {"gpu_vram_gb": 12} for hardware in chosen)

    # Runtime advisory: only for an H3 architecture; a preflight failure is no advisory.
    preflight = ModuleType("models.minimax_h3.minimax_h3_handler")
    preflight.h3_runtime_preflight = lambda model_def, hardware: {"warn": model_def["architecture"], **hardware}
    monkeypatch.setitem(sys.modules, "models.minimax_h3.minimax_h3_handler", preflight)
    advisory = launch._minimax_h3_runtime_advisory
    assert advisory({"architecture": "minimax_h3_full"}) == {"warn": "minimax_h3_full", "gpu_vram_gb": 12}
    assert [advisory({"architecture": "wan"}), advisory({}), advisory(None)] == [None, None, None]
    preflight.h3_runtime_preflight = lambda model_def, hardware: 1 / 0
    assert advisory({"architecture": "minimax_h3_full"}) is None
