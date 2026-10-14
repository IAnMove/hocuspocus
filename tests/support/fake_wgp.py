"""A fake WanGP module, so tests can import the full server without a GPU.

The full server (``app/_launch_runtime.py``) imports ``wgp`` once and binds it
with ``services.generation.bind_wgp``. A test puts this fake in
``sys.modules["wgp"]`` first (``tests/support/full_server.py`` does it).

The fake has only the attributes the server reads while it imports. Any other
attribute raises ``AttributeError`` with its name, so a route that needs more
WanGP state fails loudly instead of reading a silent default. To test such a
route, give the fake the attribute in that test (``monkeypatch.setattr(fake,
name, value, raising=False)``), or add a helper here when several tests need
the same state, as :func:`catalog_attributes` does for the model catalog.
This surface is the future engine port of the refactor. The generation call itself
(``generate_video`` and the manifest parser the worker uses) is :class:`FakeEngine`
and :func:`generation_attributes`, below.

Every attribute here must be a module-level name of ``app/wgp.py`` (or of
``shared/utils/files_locator.py`` for ``fl``), and every function must take
the real one's parameters, in the same order and with the same plain
defaults. ``tests/test_fake_wgp.py`` checks that by reading the real source,
so a WanGP update that renames or reshapes one of them fails there first.
"""
from __future__ import annotations

import ast
import copy
import functools
import inspect
import json
import os
import re
import threading
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

APP_DIR = Path(__file__).resolve().parents[2] / "app"


class FakeWgp(types.ModuleType):
    """A module object whose unknown attributes fail with a clear message."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        raise AttributeError(
            f"fake wgp has no attribute {name!r}. Give it to the fake in the test "
            "(monkeypatch.setattr(fake, name, value, raising=False)) or in tests/support/fake_wgp.py."
        )


def _no_classic_ui() -> None:
    # The server mounts the Gradio UI at /classic inside a try/except, so this
    # only prints a warning and a traceback: the served table has no /classic mount.
    raise RuntimeError("fake wgp: the classic Gradio UI is not mounted in tests")


def get_available_filename(target_path, video_source, suffix="", force_extension=None):
    """WanGP's rule: the source's base name plus ``suffix``, numbered ``(2)``, ``(3)`` ... when taken."""
    name, extension = os.path.splitext(os.path.basename(video_source))
    if force_extension is not None:
        extension = force_extension
    name += suffix
    candidate = os.path.join(target_path, f"{name}{extension}")
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(target_path, f"{name}({counter}){extension}")
        counter += 1
    return candidate


def locate_file(file_name, create_path_if_none=False, error_if_none=True, extra_paths=None):
    """No checkpoint is ever on disk in tests."""
    if error_if_none:
        raise Exception(f"fake wgp: {file_name} is not on disk in tests")
    return None


def make_fake_wgp(state_root: Path) -> FakeWgp:
    """A fake whose output, LoRA and config paths all live under ``state_root``.

    ``services.auto_performance`` is off and already applied, so the import
    skips the first-boot auto-tune and the hardware probe.
    """
    outputs = state_root / "outputs"
    loras = state_root / "loras"
    for folder in (outputs, loras):
        folder.mkdir(parents=True, exist_ok=True)
    fake = FakeWgp("wgp")
    fake.__file__ = str(APP_DIR / "wgp.py")
    fake.server_config = {
        "save_path": str(outputs),
        "image_save_path": str(outputs),
        "audio_save_path": str(outputs),
        "services": {
            "auto_performance": False,
            "auto_performance_applied": True,
            "active_workspace": "default",
        },
    }
    fake.server_config_filename = str(state_root / "wgp_config.json")
    fake.save_path = str(outputs)
    fake.image_save_path = str(outputs)
    fake.audio_save_path = str(outputs)
    fake.displayed_model_types = []
    fake.get_lora_dir = lambda *_args, **_kwargs: str(loras)
    fake.get_available_filename = get_available_filename
    fake.concatenate_multi_clip_videos = lambda *_args, **_kwargs: None
    fake.get_model_def = lambda _model_type: None
    fake.get_default_settings = lambda _model_type: {}
    fake.create_ui = _no_classic_ui
    return fake


# Two models are enough to tell text-to-video from image-to-video in the
# catalog. No file is ever on disk: ``fl.locate_file`` finds nothing.
FAKE_MODELS: dict[str, dict[str, Any]] = {
    "fake_t2v": {
        "name": "Fake Text to Video",
        "description": "A model that exists only in tests.",
        "URLs": ["ckpts/fake_t2v.safetensors"],
        "fps": 16,
        "image_prompt_types_allowed": "",
    },
    "fake_i2v": {
        "name": "Fake Image to Video",
        "description": "A model that exists only in tests.",
        "URLs": ["ckpts/fake_i2v.safetensors"],
        "fps": 24,
        "image_prompt_types_allowed": "SE",
    },
}


def catalog_attributes() -> dict[str, Any]:
    """The WanGP attributes the model catalog routes read, over :data:`FAKE_MODELS`."""

    def model_def(model_type: str) -> dict[str, Any] | None:
        definition = FAKE_MODELS.get(model_type)
        return dict(definition) if definition is not None else None

    def recursive_prop(model_type, prop="URLs", sub_prop_name=None, return_list=True, stack=()):
        # WanGP's rule for a known model: a missing property is []. The fake
        # models never point at each other, so there is no reference to follow.
        if model_type not in FAKE_MODELS:
            raise Exception(f"Unknown model type '{model_type}'")
        value = FAKE_MODELS[model_type].get(prop)
        return [] if value is None else value

    return {
        "families_infos": {"fake": (10, "Fake family"), "unknown": (999, "Unknown")},
        "displayed_model_types": list(FAKE_MODELS),
        "get_model_def": model_def,
        "get_model_family": lambda _model_type, for_ui=False: "fake",
        "get_base_model_type": lambda model_type: model_type,
        "get_model_recursive_prop": recursive_prop,
        "test_class_i2v": lambda model_type: model_type == "fake_i2v",
        "test_class_t2v": lambda model_type: model_type == "fake_t2v",
        "fl": SimpleNamespace(locate_file=locate_file),
    }


# --- The generation call -------------------------------------------------------
# ``_run_generation`` (app/_launch_runtime.py) turns a job into a task manifest,
# asks WanGP to parse it, then runs ``wgp.generate_video`` on a worker thread and
# reads the progress commands that call sends back. ``FakeEngine`` is that call.
# A test scripts it, so the real worker runs end to end with no GPU.

GENERATED_STAMP = "2026-01-02-03h04m05s"  # one fixed stamp, so file names do not depend on the clock
_EXTENSIONS = {"video": ".mp4", "image": ".png", "audio": ".wav"}


def placeholder_media(path: str, kind: str) -> None:
    """Default media writer: a few bytes. Tests that need decodable files pass their own writer."""
    Path(path).write_bytes(f"fake {kind}".encode("ascii"))


def get_gen_info(state):
    cache = state.get("gen", None)
    if cache is None:
        cache = dict()
        state["gen"] = cache
    return cache


def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    elif seconds >= 60:
        return f"{minutes}m {secs:02d}s"
    else:
        return f"{seconds:.1f}s"


@functools.lru_cache(maxsize=1)
def engine_signature() -> inspect.Signature:
    """The parameters of WanGP's ``generate_video``, read from ``app/wgp.py`` (importing it needs the GPU stack).

    The worker hands the engine only the params whose names are in ``inspect.signature(wgp.generate_video)``, as
    keyword arguments. The fake declares the real names, so the worker filters and passes exactly what it would
    pass to WanGP, and a WanGP rename shows up in the goldens' ``engine_calls[].kwargs``.
    """
    tree = ast.parse((APP_DIR / "wgp.py").read_text(encoding="utf-8"))
    real = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "generate_video")
    names = [argument.arg for argument in (*real.args.posonlyargs, *real.args.args)]
    defaults = dict(zip(names[len(names) - len(real.args.defaults):], real.args.defaults))
    parameters = []
    for name in names:
        default: Any = inspect.Parameter.empty
        if name in defaults:
            try:
                default = ast.literal_eval(defaults[name])
            except ValueError:
                default = None
        parameters.append(inspect.Parameter(name, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=default))
    return inspect.Signature(parameters)


class EngineCall:
    """One ``generate_video`` call, as a script step sees it.

    ``kwargs`` are the keyword arguments the worker passed, which is all WanGP reads: the seed and prompt that name
    the file and the generation state (``state``) come from there. ``params`` are the task's params, where the
    fake reads ``generation_mode`` to pick the kind of media (WanGP decides that from the model).
    """

    def __init__(self, engine: "FakeEngine", index: int, task: dict, send_cmd: Callable[[str, Any], None],
                 kwargs: dict[str, Any]) -> None:
        self.engine = engine
        self.index = index
        self.task = task
        self.params = task["params"]
        self.kwargs = kwargs
        self.gen = get_gen_info(kwargs["state"])
        self.send_cmd = send_cmd

    @property
    def kind(self) -> str:
        mode = self.params.get("generation_mode")
        return mode if mode in _EXTENSIONS else "video"

    def send(self, command: str, data: Any = None) -> None:
        self.send_cmd(command, data)

    def save(self, kind: str | None = None, *, suffix: str = "", register: bool | str = True) -> str:
        """Write one output where WanGP does (a video into ``wgp.save_path``, an image into ``image_save_path``, a
        sound into ``audio_save_path``) and register it as WanGP does: in ``artifact_list`` right after the write,
        then in the gallery list (``file_list`` or ``audio_file_list``). ``register="artifact"`` stops after the
        first (WanGP failed in between); ``register=False`` leaves the file for the worker to find in the folder."""
        kind = kind or self.kind
        seed = self.kwargs.get("seed", -1)
        seed = seed if isinstance(seed, int) and seed >= 0 else self.engine.default_seed
        slug = re.sub(r"[^a-z0-9]+", "_", str(self.kwargs.get("prompt") or "").lower()).strip("_")[:24] or "clip"
        source = f"{GENERATED_STAMP}_seed{seed}_{slug}{suffix}{_EXTENSIONS[kind]}"
        module = self.engine.module
        folder = {"video": module.save_path, "image": module.image_save_path, "audio": module.audio_save_path}[kind]
        path = get_available_filename(folder, source)
        self.engine.write_media(path, kind)
        if register:
            self.gen.setdefault("artifact_list", []).append(path)
        if register is True:
            listing = "audio_file_list" if kind == "audio" else "file_list"
            self.gen.setdefault(listing, []).append(path)
            self.gen.setdefault("audio_file_settings_list" if kind == "audio" else "file_settings_list", []).append({"seed": seed})
        return path

    def hold(self, release: threading.Event, *, timeout: float = 60.0, ignore_abort: bool = False) -> bool:
        """Block like a long denoising loop until ``release`` is set, or the job is aborted unless ``ignore_abort``
        (a model that takes a while to notice). Returns whether the job was aborted."""
        self.engine.entered.set()
        waited = 0.0
        while not release.is_set() and (ignore_abort or not self.gen.get("abort")):
            if waited >= timeout:
                raise TimeoutError("fake engine: the test never released or cancelled the call")
            release.wait(0.01)
            waited += 0.01
        return bool(self.gen.get("abort"))


def default_script(call: EngineCall) -> None:
    """Status, two progress steps, an info line, then ``repeat_generation`` outputs."""
    call.send("status", "Loading fake model")
    call.send("progress", [(1, 2), "Sampling | 1/2"])
    call.send("progress", [(2, 2), "Sampling | 2/2"])
    call.send("info", "Saving")
    for _ in range(max(1, int(call.kwargs.get("repeat_generation") or 1))):
        call.save()


class FakeEngine:
    """What the fake ``wgp.generate_video`` does. ``script`` runs once per call, in the engine's worker thread.

    ``scripts`` are one-shot overrides, used in call order before ``script``.
    ``calls`` records every call: the task's params and the keyword arguments it received (both without the
    generation state).
    """

    def __init__(self, write_media: Callable[[str, str], None] = placeholder_media) -> None:
        self.write_media = write_media
        self.script: Callable[[EngineCall], None] = default_script
        self.scripts: list[Callable[[EngineCall], None]] = []
        self.calls: list[dict[str, Any]] = []
        self.default_seed = 1234
        self.entered = threading.Event()
        self.module: Any = None  # the fake wgp, set by generation_attributes

    def generate(self, task: dict, send_cmd: Callable[[str, Any], None], kwargs: dict[str, Any]) -> bool:
        if "state" not in kwargs:  # WanGP's generate_video takes it as a required parameter
            raise TypeError("generate_video() missing 1 required positional argument: 'state'")
        call = EngineCall(self, len(self.calls), task, send_cmd, kwargs)
        params = {key: value for key, value in task["params"].items() if key != "state"}
        received = {key: value for key, value in kwargs.items() if key != "state"}
        module = self.module
        self.calls.append({
            "task_id": task.get("id"),
            "prompt": task.get("prompt"),
            "params": json.loads(json.dumps(copy.deepcopy(params), default=str)),
            "kwargs": json.loads(json.dumps(copy.deepcopy(received), default=str)),
            "state_is_the_task_state": kwargs["state"] is task["params"].get("state"),
            # What the worker had pointed the engine at when it made the call.
            "save_path": module.save_path,
            "image_save_path": module.image_save_path,
            "audio_save_path": module.audio_save_path,
            "vram_safety_coefficient": module.args.vram_safety_coefficient,
        })
        if call.gen.get("abort", False):
            return False
        (self.scripts.pop(0) if self.scripts else self.script)(call)
        return True


def generation_attributes(engine: FakeEngine, module: Any) -> dict[str, Any]:
    """The WanGP attributes ``_run_generation`` reads, over a :class:`FakeEngine`.

    ``_parse_task_manifest`` keeps what the real one does for a simple manifest:
    every task dict with a known model becomes a runtime task that carries the
    generation state in its params. WanGP's settings merge, attachment loading
    and preview images are not reproduced, and neither is its ``task_id`` rule
    beyond "the counter moves past the largest id". ``validate_task`` does not
    merge WanGP's default settings either, so the engine receives fewer keyword
    arguments than WanGP would. ``generate_video`` declares WanGP's real
    parameters (:func:`engine_signature`), so the worker's own filter decides
    which params reach it, and an unknown keyword is refused as WanGP would.
    """
    engine.module = module

    def parse_task_manifest(manifest, state, media_base_path, cache_dir=None, log_prefix="[load]"):
        queue = []
        for task_data in manifest:
            if not isinstance(task_data, dict):
                continue
            params = task_data.get("params", {})
            model_type = params.get("model_type")
            if model_type is None or module.get_model_def(model_type) is None:
                continue
            params["state"] = state
            queue.append({
                "id": task_data.get("id", module.task_id + 1),
                "params": params,
                "plugin_data": task_data.get("plugin_data", {}),
                "repeats": params.get("repeat_generation", 1),
                "length": params.get("video_length"),
                "steps": params.get("num_inference_steps"),
                "prompt": params.get("prompt"),
            })
        if queue:
            highest = max([item["id"] for item in queue] + [0])
            if highest >= module.task_id:
                module.task_id = highest + 1
        return queue, None

    def validate_task(task, state):
        params = task.get("params", {})
        if not params.get("model_type"):
            return None
        inputs = dict(params)
        inputs["prompt"] = task.get("prompt", "")
        inputs.setdefault("mode", "")
        return inputs

    def generate_video(task, send_cmd, *_args, **kwargs):
        engine_signature().bind_partial(task, send_cmd, **kwargs)  # TypeError on a keyword WanGP does not take
        return engine.generate(task, send_cmd, kwargs)

    # The worker filters its params by this signature (see engine_signature).
    generate_video.__signature__ = engine_signature()

    def get_model_min_frames_and_step(model_type):
        model_def = module.get_model_def(model_type)
        frames_minimum = model_def.get("frames_minimum", 5)
        frames_steps = model_def.get("frames_steps", 4)
        latent_size = model_def.get("latent_size", frames_steps)
        return frames_minimum, frames_steps, latent_size

    return {
        "task_id": 0,
        "args": SimpleNamespace(vram_safety_coefficient=0.8),
        "wan_model": None,
        "get_gen_info": get_gen_info,
        "format_time": format_time,
        "_parse_task_manifest": parse_task_manifest,
        "validate_task": validate_task,
        "generate_video": generate_video,
        "get_model_min_frames_and_step": get_model_min_frames_and_step,
    }
