"""Direct contracts for the Recast helpers no other test calls.

Recorded against the helpers while they still live in ``app/_launch_runtime.py``.
The loader follows a moved helper into its service module, so the same
assertions keep running after the move. Nothing here downloads a model:
U2Net is stubbed and the socket connect path is blocked.
"""
from __future__ import annotations

import ast
import json
import os
import socket
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"
SERVICE_FILES = (
    ROOT / "app" / "services" / "recast_masks.py",
    ROOT / "app" / "services" / "recast_matte.py",
    ROOT / "app" / "services" / "recast_reference_compose.py",
    ROOT / "app" / "services" / "recast_reference_prepare.py",
)


def _function_source(path: Path) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def _load(names: tuple[str, ...], namespace: dict | None = None) -> dict:
    """Exec the named functions from the module that currently defines them."""
    found: dict[str, ast.FunctionDef] = {}
    by_file: list[tuple[Path, list[ast.FunctionDef]]] = []
    pools = [LAUNCH, *[path for path in SERVICE_FILES if path.is_file()]]
    parsed = {path: _function_source(path) for path in pools}
    for name in names:
        home = next((path for path in pools if name in parsed[path]), None)
        if home is None:
            raise AssertionError(f"missing helper {name}")
        found[name] = parsed[home][name]
    # Keep each function's source file so a traceback names the module it moved to.
    grouped: dict[Path, list[ast.FunctionDef]] = {}
    for name in names:
        home = next(path for path in pools if name in parsed[path])
        grouped.setdefault(home, []).append(parsed[home][name])
    loaded = dict(namespace or {})
    for path, nodes in grouped.items():
        module = ast.Module(body=nodes, type_ignores=[])
        ast.fix_missing_locations(module)
        exec(compile(module, str(path), "exec"), loaded)
    return loaded


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("this test must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)


def test_resolve_recast_media_checks_absolute_workspace_uploads_and_outputs(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    uploads = tmp_path / "uploads"
    outputs = tmp_path / "outputs"
    for folder in (workspace, uploads, outputs):
        folder.mkdir()
    absolute = tmp_path / "absolute.png"
    absolute.write_bytes(b"abs")
    (workspace / "from-workspace.png").write_bytes(b"ws")
    (uploads / "from-uploads.png").write_bytes(b"up")
    (outputs / "from-outputs.png").write_bytes(b"out")
    relative = tmp_path / "relative.png"
    relative.write_bytes(b"rel")
    monkeypatch.chdir(tmp_path)
    resolve = _load(
        ("_resolve_recast_media",),
        {"os": os, "_workspace_dir": lambda _name: str(workspace)},
    )["_resolve_recast_media"]

    assert resolve(None, "demo") is None
    assert resolve("", "demo") is None
    assert resolve(str(absolute), "demo") == str(absolute)
    assert resolve("from-workspace.png", "demo") == str(workspace / "from-workspace.png")
    assert resolve("nested/from-uploads.png", "demo") == str(uploads / "from-uploads.png")
    assert resolve("from-outputs.png", "demo") == str(outputs / "from-outputs.png")
    assert resolve(str(relative), "demo") == str(relative)
    assert resolve("missing.png", "demo") is None


def test_character_mappings_keep_the_legacy_shape_and_refuse_a_bad_explicit_list(tmp_path):
    reference = tmp_path / "captain.png"
    extra = tmp_path / "captain-side.png"
    mate = tmp_path / "mate.png"
    for path in (reference, extra, mate):
        path.write_bytes(b"png")
    helpers = _load(
        ("_normalize_recast_character_mappings", "_resolve_recast_media"),
        {
            "os": os,
            "_workspace_dir": lambda _name: str(tmp_path),
            "_RECAST_MASK_COLORS": [(0, 0, 255)] * 5,
        },
    )
    normalize = helpers["_normalize_recast_character_mappings"]

    legacy, explicit = normalize(
        {
            "ref_image_path": "captain.png",
            "target": "the captain",
            "additional_ref_image_paths": ["captain-side.png"],
            "reference_aligned_to_source": True,
        },
        "demo",
    )
    assert explicit is False
    assert legacy == [{
        "id": "recast-1",
        "target": "the captain",
        "ref_image_path": str(reference),
        "additional_ref_image_paths": [str(extra)],
        "reference_aligned_to_source": True,
    }]

    mappings, explicit = normalize(
        {"character_mappings": [
            {"id": "a", "target": "captain", "ref_image_path": "captain.png"},
            {"target": "mate", "reference_image_path": "mate.png"},
        ]},
        "demo",
    )
    assert explicit is True
    assert [item["id"] for item in mappings] == ["a", "recast-2"]
    assert mappings[1]["ref_image_path"] == str(mate)
    assert mappings[0]["reference_aligned_to_source"] is False

    with pytest.raises(ValueError, match="at most five"):
        normalize(
            {"character_mappings": [
                {"target": f"person {index}", "ref_image_path": "captain.png"}
                for index in range(6)
            ]},
            "demo",
        )
    with pytest.raises(ValueError, match="edited full-frame reference"):
        normalize(
            {"character_mappings": [
                {"target": "captain", "ref_image_path": "captain.png",
                 "reference_aligned_to_source": True},
                {"target": "mate", "ref_image_path": "mate.png"},
            ]},
            "demo",
        )
    with pytest.raises(ValueError, match="Character mapping 1 is invalid"):
        normalize({"character_mappings": ["nope"]}, "demo")
    with pytest.raises(ValueError, match="reference was not found"):
        normalize(
            {"character_mappings": [{"target": "captain", "ref_image_path": "gone.png"}]},
            "demo",
        )
    with pytest.raises(ValueError, match="Additional reference views must be a list"):
        normalize(
            {"ref_image_path": "captain.png", "additional_ref_image_paths": "side.png"},
            "demo",
        )


def _probe(width, height, monkeypatch):
    import subprocess

    def run(command, **_kwargs):
        if command[0] == "ffprobe":
            return subprocess.CompletedProcess(
                command, 0,
                stdout=json.dumps({"streams": [{"width": width, "height": height}]}),
                stderr="",
            )
        raise AssertionError(command)

    monkeypatch.setattr(subprocess, "run", run)


def test_mask_lock_command_keeps_generated_audio_then_source_audio_then_none(tmp_path, monkeypatch):
    _probe(64, 48, monkeypatch)
    audio = {"generated": False, "source": False}
    build = _load(
        ("_build_recast_mask_lock_command",),
        {"_recast_video_has_audio": lambda path: audio["generated"] if path.endswith("generated.mp4") else audio["source"]},
    )["_build_recast_mask_lock_command"]
    output = str(tmp_path / "protected.mp4")

    silent = build("source.mp4", "mask.mp4", "generated.mp4", output)
    assert silent[:4] == ["ffmpeg", "-y", "-i", "source.mp4"]
    assert "colorkey=0xFFFFFF:0.18:0.04" in silent[silent.index("-filter_complex") + 1]
    assert silent[silent.index("-map_metadata") + 1] == "2"
    assert "-an" in silent
    assert silent[-1] == output

    audio["generated"] = True
    with_generated = build("source.mp4", "mask.mp4", "generated.mp4", output)
    assert ["-map", "2:a:0", "-c:a", "copy"] == [
        with_generated[index]
        for index in range(with_generated.index("2:a:0") - 1, with_generated.index("2:a:0") + 3)
    ]

    audio["generated"] = False
    audio["source"] = True
    with_source = build("source.mp4", "mask.mp4", "generated.mp4", output)
    assert ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k"] == [
        with_source[index]
        for index in range(with_source.index("0:a:0") - 1, with_source.index("0:a:0") + 5)
    ]

    monkeypatch.setattr(
        __import__("subprocess"), "run",
        lambda command, **_kwargs: __import__("subprocess").CompletedProcess(command, 0, stdout="{}", stderr=""),
    )
    with pytest.raises(ValueError, match="Could not read generated Recast dimensions"):
        build("source.mp4", "mask.mp4", "generated.mp4", output)


def test_mask_locked_render_writes_the_protected_sibling_and_drops_a_failed_one(tmp_path, monkeypatch):
    import subprocess

    generated = tmp_path / "shot.mp4"
    generated.write_bytes(b"generated")
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        target = Path(command[-1])
        if command[0] == "fail":
            target.write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="ffmpeg exploded")
        target.write_bytes(b"protected")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    render = _load(
        ("_render_recast_mask_locked_video",),
        {
            "os": os,
            "_build_recast_mask_lock_command": lambda source, mask, generated_path, output: [
                "ffmpeg", source, mask, generated_path, output,
            ],
        },
    )["_render_recast_mask_locked_video"]

    protected = render(str(tmp_path / "source.mp4"), str(tmp_path / "mask.mp4"), str(generated))
    assert protected == str(tmp_path / "shot.recast-protected.mp4")
    assert Path(protected).read_bytes() == b"protected"
    assert calls[-1][-1] == protected

    render_fail = _load(
        ("_render_recast_mask_locked_video",),
        {
            "os": os,
            "_build_recast_mask_lock_command": lambda *_args: ["fail", str(tmp_path / "shot.recast-protected.mp4")],
        },
    )["_render_recast_mask_locked_video"]
    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        render_fail("source.mp4", "mask.mp4", str(generated))
    assert not (tmp_path / "shot.recast-protected.mp4").exists()


class _U2NetState:
    """The same shape as the service holder, injected into the exec'd helpers."""

    def __init__(self) -> None:
        self.session = None
        self.session_lock = threading.Lock()
        self.run_lock = threading.Lock()
        self.cache_lock = threading.Lock()
        self.cache = {}


def test_u2net_session_loads_once_on_cpu_without_a_network_call(tmp_path, monkeypatch):
    import services.rembg_adapter as rembg

    calls = []

    def fake_session(model="u2net", *, force_cpu=False):
        calls.append((model, force_cpu))
        return {"model": model}

    monkeypatch.setattr(rembg, "background_session", fake_session)
    _block_network(monkeypatch)
    previous_home = os.environ.pop("U2NET_HOME", None)
    state = _U2NetState()
    namespace = {
        "os": os,
        "_app_dir": str(tmp_path),
        "_recast_u2net": state,
    }
    try:
        get_session = _load(("_get_recast_u2net_session",), namespace)["_get_recast_u2net_session"]
        first = get_session()
        second = get_session()
    finally:
        if previous_home is None:
            os.environ.pop("U2NET_HOME", None)
        else:
            os.environ["U2NET_HOME"] = previous_home

    assert first is second
    assert first == {"model": "u2net"}
    assert calls == [("u2net", True)]
    assert state.session is first
    assert (tmp_path / "ckpts" / "rembg").is_dir()


def test_u2net_matte_caches_one_cutout_and_evicts_the_oldest(tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image

    import services.rembg_adapter as rembg

    calls = []

    def fake_remove(image, *, model, session, **options):
        calls.append((model, session, options["alpha_matting"], image.size))
        array = np.zeros((image.size[1], image.size[0], 4), dtype=np.uint8)
        array[..., 0] = 9
        array[..., 3] = 255
        return Image.fromarray(array)

    monkeypatch.setattr(rembg, "remove_background_image", fake_remove)
    _block_network(monkeypatch)
    frame = np.zeros((4, 6, 3), dtype=np.uint8)
    first_path = tmp_path / "one.png"
    second_path = tmp_path / "two.png"
    first_path.write_bytes(b"one")
    second_path.write_bytes(b"two")
    state = _U2NetState()
    namespace = {
        "os": os,
        "_get_recast_u2net_session": lambda: "session",
        "_recast_u2net": state,
        "_RECAST_U2NET_CACHE_LIMIT": 1,
    }
    run = _load(("_run_recast_u2net_matte",), namespace)["_run_recast_u2net_matte"]

    foreground, alpha = run(frame, str(first_path))
    again_fg, again_alpha = run(frame, str(first_path))
    assert calls == [("u2net", "session", True, (6, 4))]
    assert foreground.shape == (4, 6, 3)
    assert foreground[0, 0, 0] == 9
    assert alpha.shape == (4, 6)
    assert float(alpha[0, 0]) == 1.0
    assert not np.shares_memory(foreground, again_fg)
    assert len(state.cache) == 1

    run(frame, str(second_path))
    assert len(state.cache) == 1
    assert calls[-1][1] == "session"
    # The first file's pixels changed, so the cached key no longer matches.
    first_path.write_bytes(b"one-changed")
    run(frame, str(first_path))
    assert len(calls) == 3

    monkeypatch.setattr(rembg, "remove_background_image", lambda *_args, **_kwargs: "not-an-image")
    with pytest.raises(ValueError, match="unsupported Recast matte"):
        run(frame, None)


def test_target_group_reference_refuses_a_bad_pair_and_writes_the_cast_sheet(tmp_path):
    import numpy as np
    from PIL import Image

    saved = {}

    def compose(layers, count, canvas):
        saved["compose"] = (len(layers), count, canvas)
        frame = np.zeros((canvas[1], canvas[0], 3), dtype=np.uint8)
        mask = np.zeros_like(frame)
        frame[0, 0] = (1, 2, 3)
        return frame, mask

    build = _load(
        ("_build_recast_target_group_reference",),
        {
            "os": os,
            "_compose_recast_cast_reference_frame": compose,
            "_compose_recast_group_reference_frame": lambda *_args: (_ for _ in ()).throw(
                ValueError("no shared layout")
            ),
            "_normalize_recast_person_count": lambda value: value,
        },
    )["_build_recast_target_group_reference"]

    with pytest.raises(ValueError, match="prepared target image/mask pairs"):
        build({"primary_target_refs": [{"image": "", "mask": ""}]}, str(tmp_path), "job", 2)

    image = tmp_path / "target.png"
    mask = tmp_path / "target-mask.png"
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8)).save(image)
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8)).save(mask)
    result = build(
        {
            "primary_target_refs": [{"image": str(image), "mask": str(mask)}],
            "reference_canvas": (32, 16),
        },
        str(tmp_path / "out"),
        "job-7",
        2,
    )
    assert result["mode"] == "cast_sheet"
    assert result["character_count"] == 2
    assert result["image"].endswith("recast_cast_ref_job-7.png")
    assert result["mask"].endswith("recast_cast_mask_job-7.png")
    assert Path(result["image"]).is_file()
    assert saved["compose"] == (1, 2, (32, 16))
    assert tuple(np.asarray(Image.open(result["image"]))[0, 0]) == (1, 2, 3)


def test_native_people_conditioning_returns_the_target_mask_when_nobody_else_is_kept(tmp_path, monkeypatch):
    import numpy as np
    import shared.magic_mask as magic_mask

    frames = np.zeros((2, 4, 4, 3), dtype=np.uint8)
    monkeypatch.setattr(
        magic_mask, "prepare_video_mask_input",
        lambda path: (path, frames, 8),
    )
    monkeypatch.setattr(
        magic_mask, "generate_keyword_masks",
        lambda *_args, **_kwargs: frames,
    )
    build = _load(
        ("_build_recast_native_people_conditioning",),
        {
            "os": os,
            "_RECAST_PROTECTION_COLORS": [(0, 0, 255)],
            "_normalize_recast_person_count": lambda value: int(value),
            "_compose_recast_native_people_masks": lambda *_args, **_kwargs: (
                frames, frames, 1, [{"kept": False}],
            ),
        },
    )["_build_recast_native_people_conditioning"]

    result = build("source.mp4", "mask.mp4", 1, str(tmp_path), "job")
    assert result == {
        "video_mask": "mask.mp4",
        "reference_image": None,
        "reference_mask": None,
        "conditioning_count": 1,
        "assignments": [{"kept": False}],
    }


def test_adaptive_mask_paints_the_matched_track_and_refuses_an_empty_target(tmp_path, monkeypatch, capsys):
    import numpy as np
    import shared.magic_mask as magic_mask

    mask_color = (0, 0, 255)
    saved = {}

    def prepare(path):
        if path == "generated.mp4":
            frames = np.zeros((1, 20, 20, 3), dtype=np.uint8)
            return path, frames, 8
        source = np.full((3, 10, 10, 3), 255, dtype=np.uint8)
        source[:, 4:6, 4:6] = mask_color
        return path, source, 8

    def people(frames, *_args, **_kwargs):
        painted = np.zeros_like(frames)
        painted[:, 8:12, 8:12] = mask_color
        return painted

    def save(_source, masks, _fps, labels, **kwargs):
        saved["masks"] = masks.copy()
        saved["labels"] = labels
        saved["background"] = kwargs["background_color"]
        path = str(tmp_path / "adaptive.mp4")
        saved["path"] = path
        return path

    monkeypatch.setattr(magic_mask, "prepare_video_mask_input", prepare)
    monkeypatch.setattr(magic_mask, "generate_keyword_masks", people)
    monkeypatch.setattr(magic_mask, "save_mask_video", save)
    loaded = _load(
        (
            "_build_recast_adaptive_mask",
            "_select_recast_generated_regions",
            "_recast_color_region",
        ),
        {
            "os": os,
            "_RECAST_MASK_COLORS": [mask_color, (255, 0, 0)],
            "_RECAST_PROTECTION_COLORS": [mask_color, (255, 255, 0)],
        },
    )
    build = loaded["_build_recast_adaptive_mask"]
    assert build("generated.mp4", "source.mp4", 1, str(tmp_path)) == saved["path"]
    painted = saved["masks"]
    assert painted.shape == (1, 20, 20, 3)
    assert tuple(painted[0, 10, 10]) == mask_color
    # The 7px close+dilate grows the 4x4 match. Corners stay unpainted.
    assert int((painted[0] == mask_color).all(axis=-1).sum()) > 16
    assert tuple(painted[0, 0, 0]) == (0, 0, 0)
    assert saved["labels"] == ["adaptive recast target"]
    assert saved["background"] == (255, 255, 255)
    assert "track 0:" in capsys.readouterr().out

    def empty_source(path):
        if path == "generated.mp4":
            frames = np.zeros((1, 8, 8, 3), dtype=np.uint8)
            return path, frames, 8
        return path, np.full((1, 8, 8, 3), 255, dtype=np.uint8), 8

    monkeypatch.setattr(magic_mask, "prepare_video_mask_input", empty_source)
    with pytest.raises(ValueError, match="approved Recast target mask is empty"):
        build("generated.mp4", "source.mp4", 1, str(tmp_path))

    def nobody(path):
        frames = np.zeros((1, 8, 8, 3), dtype=np.uint8)
        frames[:, 2:4, 2:4] = mask_color
        return path, frames, 8

    monkeypatch.setattr(magic_mask, "prepare_video_mask_input", nobody)
    monkeypatch.setattr(
        magic_mask, "generate_keyword_masks",
        lambda frames, *_args, **_kwargs: np.zeros_like(frames),
    )
    with pytest.raises(ValueError, match="SAM3 found no people"):
        build("generated.mp4", "source.mp4", 1, str(tmp_path))


def test_video_frame_count_is_the_decoded_length(monkeypatch):
    import sys
    import types

    fake = types.ModuleType("decord")

    class VideoReader:
        def __init__(self, path):
            self.path = path

        def __len__(self):
            return 7 if self.path.endswith("shot.mp4") else 0

    fake.VideoReader = VideoReader
    monkeypatch.setitem(sys.modules, "decord", fake)
    count = _load(("_recast_video_frame_count",), {})["_recast_video_frame_count"]
    assert count("shot.mp4") == 7


RECAST_SERVICES = ("recast_masks", "recast_matte", "recast_reference_compose", "recast_reference_prepare")


def test_each_recast_service_binds_exactly_its_free_launch_names():
    """The bind lists come from the modules, not from a hand-written list.

    A slot is a module global set to None that :func:`bind` fills. The slots of
    a module are exactly the names its functions read that nothing in the slice
    defines and the module does not import; ``bind`` takes one keyword per slot
    and writes it there; launch calls each ``bind`` once, passing the launch
    name itself or a forwarder that calls that launch name.
    """
    import builtins

    services = ROOT / "app" / "services"
    assert sorted(path.stem for path in services.glob("recast_*.py")) == sorted(RECAST_SERVICES)
    trees = {
        stem: ast.parse((services / f"{stem}.py").read_text(encoding="utf-8"), filename=f"{stem}.py")
        for stem in RECAST_SERVICES
    }
    defined: dict[str, str] = {}
    slots: dict[str, set[str]] = {stem: set() for stem in RECAST_SERVICES}
    for stem, tree in trees.items():
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name != "bind":
                assert node.name not in defined, f"{node.name} is defined twice in the slice"
                defined[node.name] = stem
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    assert isinstance(target, ast.Name)
                    if isinstance(node.value, ast.Constant) and node.value.value is None:
                        slots[stem].add(target.id)
                    else:
                        assert target.id not in defined, f"{target.id} is defined twice in the slice"
                        defined[target.id] = stem

    launch_tree = ast.parse(LAUNCH.read_text(encoding="utf-8"))
    launch_names: set[str] = set()
    launch_functions: dict[str, ast.FunctionDef] = {}
    bind_aliases: dict[str, str] = {}
    for node in launch_tree.body:
        if isinstance(node, ast.FunctionDef):
            launch_functions[node.name] = node
            launch_names.add(node.name)
        elif isinstance(node, ast.Assign):
            launch_names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            launch_names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("services.recast_"):
                for alias in node.names:
                    if alias.name == "bind":
                        bind_aliases[alias.asname or alias.name] = node.module.rsplit(".", 1)[-1]
    bind_calls: dict[str, list[ast.Call]] = {}
    for node in ast.walk(launch_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in bind_aliases:
            bind_calls.setdefault(bind_aliases[node.func.id], []).append(node)

    for stem, tree in trees.items():
        source = (services / f"{stem}.py").read_text(encoding="utf-8")
        assert _undefined_globals(source, f"{stem}.py") == set(), stem
        imported: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("services.recast_"):
                home = node.module.rsplit(".", 1)[-1]
                for alias in node.names:
                    if alias.name != "bind":
                        assert defined.get(alias.name) == home, f"{stem} imports {alias.name} from {home}"
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                imported.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        free = {
            name for name in _global_reads(source, f"{stem}.py", skip={"bind"})
            if name not in defined and name not in imported and not hasattr(builtins, name)
        }
        assert free == slots[stem], stem

        bind = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "bind"), None)
        if not slots[stem]:
            assert bind is None and stem not in bind_calls, f"{stem} has nothing to bind"
            continue
        assert bind is not None and not bind.args.args and not bind.args.vararg and not bind.args.kwarg
        params = [arg.arg for arg in bind.args.kwonlyargs]
        assert {"_" + param for param in params} == slots[stem], stem
        update = bind.body[-1].value
        assert isinstance(update, ast.Call) and ast.unparse(update.func) == "globals().update"
        assert {keyword.arg: ast.unparse(keyword.value) for keyword in update.keywords} == {
            "_" + param: param for param in params
        }, stem

        assert len(bind_calls.get(stem, [])) == 1, f"launch must bind {stem} exactly once"
        call = bind_calls[stem][0]
        assert not call.args and {keyword.arg for keyword in call.keywords} == set(params), stem
        for keyword in call.keywords:
            slot = "_" + keyword.arg
            assert slot in launch_names, f"launch has no {slot} to hand to {stem}"
            assert isinstance(keyword.value, ast.Name), stem
            if keyword.value.id == slot:
                continue
            forwarder = launch_functions[keyword.value.id]
            body = [node for node in forwarder.body if not isinstance(node, ast.Expr)]
            assert len(body) == 1 and isinstance(body[0], ast.Return), forwarder.name
            assert ast.unparse(body[0].value) == f"{slot}(*args, **kwargs)", forwarder.name
            assert ast.unparse(forwarder.args) == "*args, **kwargs", forwarder.name
    assert set(bind_calls) <= {stem for stem in RECAST_SERVICES if slots[stem]}


def _global_reads(source: str, filename: str, skip: set[str]) -> set[str]:
    """Global names read inside the module's functions and classes, except the scopes named in ``skip``."""
    import symtable

    names: set[str] = set()

    def walk(table: symtable.SymbolTable) -> None:
        names.update(
            item.get_name() for item in table.get_symbols() if item.is_global() and item.is_referenced()
        )
        for child in table.get_children():
            walk(child)

    for child in symtable.symtable(source, filename, "exec").get_children():
        if child.get_name() not in skip:
            walk(child)
    return names


def _undefined_globals(source: str, filename: str) -> set[str]:
    import builtins
    import symtable

    top = symtable.symtable(source, filename, "exec")
    bound = {
        item.get_name()
        for item in top.get_symbols()
        if item.is_assigned() or item.is_imported() or item.is_namespace()
    }

    def declare(table: symtable.SymbolTable) -> None:
        bound.update(
            item.get_name()
            for item in table.get_symbols()
            if item.is_declared_global() and item.is_assigned()
        )
        for child in table.get_children():
            declare(child)

    declare(top)
    missing: set[str] = set()

    def walk(table: symtable.SymbolTable) -> None:
        for item in table.get_symbols():
            name = item.get_name()
            if (
                table is not top
                and item.is_global()
                and item.is_referenced()
                and name not in bound
                and not hasattr(builtins, name)
                and not name.startswith("__")
            ):
                missing.add(name)
        for child in table.get_children():
            walk(child)

    walk(top)
    return missing


def test_video_has_audio_follows_the_ffprobe_answer(monkeypatch):
    import subprocess

    answers = {}

    def run(command, **_kwargs):
        path = command[-1]
        ok = answers[path]
        return subprocess.CompletedProcess(
            command, 0 if ok else 1,
            stdout="audio\n" if ok else "",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", run)
    has_audio = _load(("_recast_video_has_audio",), {})["_recast_video_has_audio"]
    answers["with.mp4"] = True
    answers["without.mp4"] = False
    assert has_audio("with.mp4") is True
    assert has_audio("without.mp4") is False
