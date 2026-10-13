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
This surface is the future engine port of the refactor.

Every attribute here must be a module-level name of ``app/wgp.py`` (or of
``shared/utils/files_locator.py`` for ``fl``), and every function must take
the real one's parameters, in the same order and with the same plain
defaults. ``tests/test_fake_wgp.py`` checks that by reading the real source,
so a WanGP update that renames or reshapes one of them fails there first.
"""
from __future__ import annotations

import os
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
