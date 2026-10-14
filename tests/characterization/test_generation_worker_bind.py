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
