"""Model-free contract tests for asynchronous H3 window preplanning.

The production server imports WanGP and may initialize heavyweight model
dependencies, so these regressions extract only the relevant functions from
``launch.py`` and execute them with small fakes.  No model or GPU runtime is
loaded by this module.
"""
from __future__ import annotations

import ast
import asyncio
import copy
from contextlib import contextmanager
import os
import sys
import time
import traceback
import types
import uuid
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"


class _HTTPException(Exception):
    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _ExecutionModeError(ValueError):
    pass


class _Request:
    def __init__(self, body: dict):
        self._body = copy.deepcopy(body)

    async def json(self) -> dict:
        return copy.deepcopy(self._body)


class _DeferredThread:
    instances: list["_DeferredThread"] = []

    def __init__(self, *, target, args=(), kwargs=None, **_ignored):
        self.target = target
        self.args = tuple(args)
        self.kwargs = dict(kwargs or {})
        self.started = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.started = True

    def run_now(self) -> None:
        self.target(*self.args, **self.kwargs)


def _tree() -> ast.Module:
    return ast.parse(LAUNCH.read_text(encoding="utf-8"), filename=str(LAUNCH))


def _function(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in _tree().body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            selected = copy.deepcopy(node)
            selected.decorator_list = []
            return selected
    raise AssertionError(f"Function {name!r} not found in app/_launch_runtime.py")


def _load(*names: str, namespace: dict) -> dict:
    module = ast.Module(body=[_function(name) for name in names], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(LAUNCH), "exec"), namespace)
    return namespace


def _module(name: str, **attrs) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module


def _install_h3_fakes(monkeypatch, planner) -> None:
    turbo = _module(
        "models.minimax_h3.turbo",
        normalize_minimax_h3_turbo_request=lambda _body, **_kwargs: False,
    )
    handler = _module(
        "models.minimax_h3.minimax_h3_handler",
        apply_h3_window_memory_policy=lambda *_args, **_kwargs: None,
        h3_runtime_preflight=lambda *_args, **_kwargs: None,
    )
    minimax_h3_package = _module(
        "models.minimax_h3",
        turbo=turbo,
        minimax_h3_handler=handler,
    )
    minimax_h3_package.__path__ = []
    models_package = _module("models", minimax_h3=minimax_h3_package)
    models_package.__path__ = []
    monkeypatch.setitem(sys.modules, "models", models_package)
    monkeypatch.setitem(sys.modules, "models.minimax_h3", minimax_h3_package)
    monkeypatch.setitem(
        sys.modules,
        "models.minimax_h3.turbo",
        turbo,
    )
    monkeypatch.setitem(
        sys.modules,
        "models.minimax_h3.minimax_h3_handler",
        handler,
    )
    planner_module = _module(
        "services.h3_window_planner",
        compute_h3_window_boundaries=lambda *_args, **_kwargs: [
            {"index": 0}, {"index": 1},
        ],
        h3_window_plan_signature=lambda *_args, **_kwargs: "window-signature",
        plan_h3_sliding_windows=planner,
    )
    llm_module = _module(
        "services.llm_service",
        is_loaded=lambda: False,
        get_status=lambda: {"provider": "minimax"},
        unload_model=lambda: None,
    )
    duration_module = _module(
        "services.minimax_h3_duration",
        apply_h3_dialogue_duration=lambda _body, _model_def: None,
        apply_h3_vocal_timeline=lambda _body, _model_def: None,
        h3_dialogue_split_error=lambda _contract: "dialogue split required",
    )

    @contextmanager
    def task_context_scope(**_context):
        yield

    task_module = _module(
        "services.task_manager",
        task_context_scope=task_context_scope,
    )
    services_package = _module(
        "services",
        h3_window_planner=planner_module,
        llm_service=llm_module,
        minimax_h3_duration=duration_module,
        task_manager=task_module,
    )
    services_package.__path__ = []
    monkeypatch.setitem(sys.modules, "services", services_package)
    monkeypatch.setitem(
        sys.modules,
        "services.h3_window_planner",
        planner_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "services.llm_service",
        llm_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "services.minimax_h3_duration",
        duration_module,
    )
    monkeypatch.setitem(sys.modules, "services.task_manager", task_module)


def _base_body() -> dict:
    return {
        "model_type": "minimax_h3_test",
        "prompt": "A camera follows a cyclist through a rainy city.",
        "resolution": "960x544",
        "video_length": 209,
        "sliding_window_size": 107,
        "sliding_window_overlap": 0,
        "sliding_window_discard_last_frames": 0,
        "multi_prompts_gen_type": 0,
        "workspace": "default",
    }


def _harness(monkeypatch, tmp_path: Path, planner) -> tuple[dict, dict, float]:
    _DeferredThread.instances = []
    _install_h3_fakes(monkeypatch, planner)
    events: list[tuple[str, str]] = []
    gpu_calls: list[str] = []
    fifo_tickets: list[str] = []
    jobs: dict[str, dict] = {}

    model_def = {
        "architecture": "minimax_h3_test",
        "fps": 24,
        "minimax_h3_text_encoder_variants": {"qwen-test": {}},
    }

    def publish(job: dict) -> dict:
        task_id = f"task-generation-{job['id']}"
        events.append(("publish", job["id"]))
        return {"id": task_id, "root_id": task_id}

    def persist(job: dict) -> None:
        events.append(("persist", job["id"]))

    def try_start(job: dict, **updates) -> bool:
        if job.get("cancel_requested") or job.get("status") != "queued":
            return False
        job.update(updates)
        job["status"] = "running"
        job["started_at"] = job.get("started_at") or time.time()
        return True

    def try_requeue(job: dict, **updates) -> bool:
        if job.get("cancel_requested"):
            job["status"] = "cancelled"
            return False
        if job.get("status") != "running":
            return False
        job.update(updates)
        job["status"] = "queued"
        return True

    def update_job(job: dict, **updates) -> bool:
        if job.get("cancel_requested") or job.get("status") != "running":
            return False
        job.update(updates)
        return True

    def finish_job(job: dict, status: str, **updates) -> bool:
        job.update(updates)
        job["status"] = "cancelled" if job.get("cancel_requested") else status
        job["finished_at"] = time.time()
        return job["status"] == status

    def acknowledge_cancel(job: dict, **updates) -> bool:
        if not job.get("cancel_requested") or job.get("status") == "cancelled":
            return False
        job.update(updates)
        job["status"] = "cancelled"
        job["finished_at"] = time.time()
        return True

    namespace = {
        "Request": object,
        "HTTPException": _HTTPException,
        "execution_mode": SimpleNamespace(
            ExecutionModeError=_ExecutionModeError,
            validate_generation=lambda _workspace: None,
            policy=lambda: SimpleNamespace(mode="real"),
        ),
        "asyncio": asyncio,
        "copy": copy,
        "os": os,
        "threading": SimpleNamespace(Thread=_DeferredThread),
        "time": time,
        "traceback": traceback,
        "uuid": uuid,
        "wgp": SimpleNamespace(
            server_config={"services": {"nsfw_mode": False}},
            get_model_def=lambda model_type: model_def if model_type == "minimax_h3_test" else None,
            get_base_model_type=lambda _model_type: "minimax_h3_test",
            get_model_min_frames_and_step=lambda _model_type: (5, 209, 17),
        ),
        "minimax_h3_service": SimpleNamespace(
            cancel_idle_shutdown=lambda: None,
        ),
        "_jobs": jobs,
        "_gen_lock": object(),
        "_PUBLIC_LLM_PROVIDERS": frozenset({"openai", "anthropic"}),
        "_is_legacy_h3_model": lambda _model_type: False,
        "_is_minimax_h3_model": lambda model_type: model_type == "minimax_h3_test",
        "_recommended_minimax_h3_encoder": lambda *_args: "qwen-test",
        "_get_cached_hardware": lambda: {"cuda_available": True},
        "_effective_llm_routing": lambda _services: ("minimax", "MiniMax-M3", ""),
        "_ensure_llm_loaded": lambda: None,
        "_normalize_video_prompt_type": lambda _body: None,
        "_normalize_image_prompt_type": lambda _body: None,
        "_get_active_workspace": lambda: "default",
        "normalize_submission_provenance": lambda value: value or {
            "actor": "unknown", "tool": "studio", "command": {},
        },
        "_workspace_dir": lambda _workspace=None: str(tmp_path),
        "_publish_generation_task": publish,
        "_persist_generation_job": persist,
        "_remove_persisted_generation_job": lambda job: events.append(("remove", job["id"])),
        "_cancel_h3_idle_release": lambda: None,
        "register_generation_job": lambda _lock, job: fifo_tickets.append(job["id"]),
        "is_cancel_requested": lambda job: bool(
            job.get("cancel_requested") or job.get("status") == "cancelled"
        ),
        "try_start": try_start,
        "try_requeue": try_requeue,
        "update_job": update_job,
        "finish_job": finish_job,
        "acknowledge_cancel": acknowledge_cancel,
        "snapshot_job": lambda job: dict(job),
        "_run_generation": lambda job_id, **_kwargs: gpu_calls.append(job_id),
    }
    _load(
        "_new_generation_job",
        "_run_generation_with_preparation",
        "generate",
        namespace=namespace,
    )

    before = time.monotonic()
    result = asyncio.run(namespace["generate"](_Request(_base_body())))
    elapsed = time.monotonic() - before
    namespace.update({
        "_events": events,
        "_gpu_calls": gpu_calls,
        "_fifo_tickets": fifo_tickets,
    })
    return namespace, result, elapsed


def test_uncached_h3_submission_is_visible_and_returns_ids_within_250ms(
    tmp_path, monkeypatch,
):
    planner_calls: list[str] = []

    def slow_planner(*_args, **_kwargs):
        planner_calls.append("planner")
        time.sleep(0.35)
        return {"window_prompts": ["first", "second"]}

    namespace, result, elapsed = _harness(monkeypatch, tmp_path, slow_planner)

    assert elapsed < 0.25
    assert result["status"] == "queued"
    assert result["task_id"] == result["root_task_id"]
    assert result["job_id"] in namespace["_jobs"]
    assert planner_calls == []
    assert namespace["_fifo_tickets"] == []
    assert ("publish", result["job_id"]) in namespace["_events"]
    assert ("persist", result["job_id"]) in namespace["_events"]
    assert len(_DeferredThread.instances) == 1
    assert _DeferredThread.instances[0].started is True
    assert _DeferredThread.instances[0].target.__name__ == "_run_generation_with_preparation"


def test_cancel_before_preplanning_never_enters_or_reserves_gpu(
    tmp_path, monkeypatch,
):
    planner_calls: list[str] = []

    def planner(*_args, **_kwargs):
        planner_calls.append("planner")
        return {"window_prompts": ["first", "second"]}

    namespace, result, _elapsed = _harness(monkeypatch, tmp_path, planner)
    job = namespace["_jobs"][result["job_id"]]
    job["cancel_requested"] = True
    job["status"] = "cancelled"

    _DeferredThread.instances[0].run_now()

    assert planner_calls == []
    assert namespace["_gpu_calls"] == []
    assert namespace["_fifo_tickets"] == []


def test_preplanner_exception_fails_without_leaking_a_fifo_ticket(
    tmp_path, monkeypatch,
):
    def broken_planner(*_args, **_kwargs):
        raise RuntimeError("planner exploded")

    namespace, result, _elapsed = _harness(monkeypatch, tmp_path, broken_planner)
    failed_job = namespace["_jobs"][result["job_id"]]

    _DeferredThread.instances[0].run_now()

    assert failed_job["status"] == "failed"
    assert "planner exploded" in str(failed_job.get("error") or failed_job.get("message"))
    assert namespace["_gpu_calls"] == []
    assert namespace["_fifo_tickets"] == []

    next_job = namespace["_new_generation_job"](
        {"model_type": "other", "prompt": "next"},
        "default",
        reserve_generation=True,
    )
    assert namespace["_fifo_tickets"] == [next_job["id"]]


def test_recovery_routes_persisted_preplans_through_the_preparation_worker():
    resume = _function("resume_generation_queue")
    targets = [
        keyword.value.id
        for call in ast.walk(resume)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "Thread"
        for keyword in call.keywords
        if keyword.arg == "target" and isinstance(keyword.value, ast.Name)
    ]

    assert targets
    assert set(targets) == {"_run_generation_with_preparation"}

    calls = {
        node.func.id: node.lineno
        for node in ast.walk(resume)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {
            "_reset_canonical_task_for_resume", "_new_generation_job",
        }
    }
    assert "_reset_canonical_task_for_resume" in calls
    assert calls["_reset_canonical_task_for_resume"] < calls["_new_generation_job"]
