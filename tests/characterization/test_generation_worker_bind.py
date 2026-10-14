"""After the full server has imported, every name the generation worker modules read is the server's own object."""
from __future__ import annotations

import ast
import builtins
import importlib
import symtable
from pathlib import Path
from types import SimpleNamespace

# Fixtures, used by name: the C0 rig and its decodable clip.
from tests.characterization.test_run_generation import clip, rig  # noqa: F401

PACKAGE = Path(__file__).resolve().parents[2] / "app" / "services" / "generation_worker"


def _worker_modules():
    for path in sorted(PACKAGE.glob("*.py")):
        if path.name != "__init__.py":
            yield path, importlib.import_module(f"services.generation_worker.{path.stem}")


def _injected(tree: ast.Module) -> list[str]:
    return [
        target.id for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value is None
        for target in node.targets if isinstance(target, ast.Name)
    ]


def _read_globals(source: str) -> set[str]:
    """Names that the module's functions read as module globals."""
    found: set[str] = set()

    def walk(scope: symtable.SymbolTable) -> None:
        for child in scope.get_children():
            if child.get_type() == "function":
                found.update(s.get_name() for s in child.get_symbols() if s.is_global() and s.is_referenced())
            walk(child)

    walk(symtable.symtable(source, "worker", "exec"))
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
    for path, module in _worker_modules():
        source = path.read_text(encoding="utf-8")
        injected = _injected(ast.parse(source))
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
        # Names a worker module imports itself (update_job, execution_mode, time, ...) are the server's too:
        # the worker must not call a same-named object the server does not use.
        for name in sorted(_read_globals(source) - set(injected)):
            if hasattr(builtins, name) or not hasattr(launch, name) or not hasattr(module, name):
                continue
            assert getattr(module, name) is getattr(launch, name), (
                f"{path.stem}.{name} is not the object the full server binds to {name}"
            )
            checked += 1
    assert checked > 0


def test_a_command_job_is_registered_and_started_on_the_servers_real_globals(rig, monkeypatch) -> None:
    """``create_image_generation_commands(globals())`` reads launch's own namespace. Its ``dispatch`` once read
    ``register_generation_job`` there, the kernel PR (#1059) stopped defining that name in launch, and every job a
    command admitted (image, speech, music, sfx, video) died with ``KeyError`` before its worker thread started.
    Every test of ``dispatch`` used a hand-made runtime dict, so nothing noticed. This one runs it on the real one."""
    from services import image_generation_runtime, job_lifecycle

    launch = rig.launch
    started = []

    class RecordingThread:
        """The worker thread, recorded and never run: no engine is scripted for this job."""

        def __init__(self, *, target, args, name, daemon):
            self.target, self.args, self.name, self.daemon, self.ident = target, args, name, daemon, None

        def start(self):
            self.ident = 1
            started.append(self)

    # Only this module's view of ``threading`` changes; patching ``threading.Thread`` would reach the whole process.
    monkeypatch.setattr(image_generation_runtime, "threading", SimpleNamespace(Thread=RecordingThread))
    job = launch._new_generation_job(
        {"model_type": "fake_t2v", "prompt": "a calm lake"}, "default", job_id="dispatch-real-globals",
        reserve_generation=False, publish_task=True,
    )
    assert "_generation_queue_token" not in job, "the job must start unregistered, as a command admission leaves it"

    launch._image_generation_commands.dispatch(job)

    assert launch._jobs["dispatch-real-globals"] is job
    # register_generation_job ran, against the server's own GPU lock.
    assert job["_generation_queue_lock_key"] == id(launch._gen_lock)
    queue = job_lifecycle._generation_queues[id(launch._gen_lock)]
    assert [entry[2] for entry in queue] == [job]
    # The worker thread was handed the job's id and started once.
    assert [(thread.target, thread.args, thread.name, thread.daemon) for thread in started] == [
        (launch._run_generation_with_preparation, ("dispatch-real-globals",),
         "command-generation-dispatch-real-globals", False),
    ]
    assert job["status"] == "queued"


def test_a_command_job_still_planning_its_h3_windows_stays_off_the_gpu_queue(rig, monkeypatch) -> None:
    """Studio generate and recovery leave a job whose H3 window prompts are still to be planned off the GPU FIFO:
    the planner is an LLM call that needs no GPU, and a registered job would sit at the queue head and hold every
    later Studio job back while the GPU is idle. A command admission reaches the same worker (``generate()`` sets
    ``_h3_window_plan_pending``), so ``dispatch`` must start it unregistered too. The job joins the queue by itself
    when its prompts are ready (``acquire_generation_slot``)."""
    from services import image_generation_runtime, job_lifecycle

    launch = rig.launch
    started = []

    class RecordingThread:
        def __init__(self, *, target, args, name, daemon):
            self.target, self.args, self.name, self.daemon, self.ident = target, args, name, daemon, None

        def start(self):
            self.ident = 1
            started.append(self)

    monkeypatch.setattr(image_generation_runtime, "threading", SimpleNamespace(Thread=RecordingThread))
    job = launch._new_generation_job(
        {"model_type": "fake_t2v", "prompt": "a calm lake",
         "_h3_window_plan_pending": {"expected_count": 2, "window_frames": 81}},
        "default", job_id="dispatch-h3-preplan", reserve_generation=False, publish_task=True,
    )

    launch._image_generation_commands.dispatch(job)

    assert launch._jobs["dispatch-h3-preplan"] is job
    assert "_generation_queue_token" not in job
    assert [entry[2] for entry in job_lifecycle._generation_queues.get(id(launch._gen_lock), ())] == []
    assert [thread.args for thread in started] == [("dispatch-h3-preplan",)]
    assert job["status"] == "queued"


def test_a_command_job_whose_h3_planning_fails_leaves_the_gpu_queue_free(rig, monkeypatch) -> None:
    """A failed plan finishes the job without ever entering ``acquire_generation_slot``. Had ``dispatch`` registered
    it, its token would stay at the head of the GPU FIFO (only cancelled heads are dropped), and every later job would
    wait forever on an idle GPU. The next job must get the GPU at once."""
    import threading

    from services import generation_preparation, h3_window_planner, image_generation_runtime, job_lifecycle

    launch = rig.launch
    started = []

    class RecordingThread:
        def __init__(self, *, target, args, name, daemon):
            self.target, self.args, self.ident = target, args, None

        def start(self):
            self.ident = 1
            started.append(self)

    def planner_down(*_args, **_kwargs):
        raise RuntimeError("planner down")

    monkeypatch.setattr(image_generation_runtime, "threading", SimpleNamespace(Thread=RecordingThread))
    monkeypatch.setattr(generation_preparation, "_ensure_llm_loaded", lambda: None)
    monkeypatch.setattr(h3_window_planner, "plan_h3_sliding_windows", planner_down)
    job = launch._new_generation_job(
        {"model_type": "fake_t2v", "prompt": "a calm lake",
         "_h3_window_plan_pending": {"expected_count": 2, "window_frames": 81}},
        "default", job_id="dispatch-h3-plan-fails", reserve_generation=False, publish_task=True,
    )
    launch._image_generation_commands.dispatch(job)
    [worker] = started
    assert worker.target(*worker.args) is False
    assert job["status"] == "failed" and "planner down" in job["message"]
    assert [entry[2] for entry in job_lifecycle._generation_queues.get(id(launch._gen_lock), ())] == []

    following = {"id": "after-failed-plan", "status": "queued", "params": {}}
    acquired = []
    waiter = threading.Thread(
        target=lambda: acquired.append(job_lifecycle.acquire_generation_slot(launch._gen_lock, following)),
        daemon=True,
    )
    waiter.start()
    waiter.join(5)
    if not acquired:  # free the waiter before failing, so it does not poll for the rest of the session
        following["cancel_requested"] = True
        waiter.join(5)
    assert acquired == [True], "the next job never got the GPU"
    launch._gen_lock.release()


# One bind() per moved service. The injected names come from each module's source.
BOUND_SERVICES = (
    "services.generation_jobs",
    "services.generation_recovery",
    "services.generation_preparation",
    "services.generation_h3_release",
)


def test_every_bound_service_name_is_the_servers_object(full_server, monkeypatch) -> None:
    """Every global a moved service binds is the full server's object. A forwarder follows a patched name."""
    launch = importlib.import_module("_launch_runtime")
    checked = 0
    for module_name in BOUND_SERVICES:
        module = importlib.import_module(module_name)
        source = Path(module.__file__).read_text(encoding="utf-8")
        injected = _injected(ast.parse(source))
        assert injected, module_name
        for name in injected:
            value = getattr(module, name)
            assert value is not None, f"{module_name}.{name} was never bound"
            assert hasattr(launch, name), f"{module_name}.{name}: the full server has no {name}"
            checked += 1
            if _is_forwarder(value, launch):
                assert name in value.__code__.co_names, f"{module_name}.{name} forwards to {value.__code__.co_names}"
                calls = []
                monkeypatch.setattr(launch, name, lambda *args, **kwargs: calls.append((args, kwargs)) or "forwarded")
                assert value("probe", flag=True) == "forwarded" and calls == [(("probe",), {"flag": True})]
                monkeypatch.undo()
                continue
            assert value is getattr(launch, name), f"{module_name}.{name} is not the server's object"
    assert checked > 0


def test_the_hardware_probe_and_the_h3_lock_are_the_servers_objects(full_server) -> None:
    """The probe is one function object, and the idle-release lock is the holder's one RLock."""
    launch = importlib.import_module("_launch_runtime")
    probe = importlib.import_module("services.hardware_probe")
    release = importlib.import_module("services.generation_h3_release")
    coefficients = importlib.import_module("services.generation_coefficients")
    director_router = importlib.import_module("routers.director")
    director = importlib.import_module("services.director_pipeline")
    assert launch._get_cached_hardware is probe._get_cached_hardware
    assert coefficients._get_cached_hardware is probe._get_cached_hardware
    # The director router holds the probe from import and hands it to the pipeline when the pipeline first starts,
    # which only an earlier director test (or request) does. Check the pipeline's copy once it exists.
    assert director_router._get_cached_hardware is probe._get_cached_hardware
    if director_router._pipeline_init_state.initialized:
        assert director._get_cached_hardware is probe._get_cached_hardware
    assert launch._h3_idle_release_lock is release._h3_idle_release.lock
    assert launch._cancel_h3_idle_release is release._cancel_h3_idle_release
    assert launch._interrupt_wan_model is release._interrupt_wan_model
    assert launch._release_h3_when_queue_allows is release._release_h3_when_queue_allows
    assert launch._release_legacy_h3_when_queue_allows is release._release_legacy_h3_when_queue_allows
