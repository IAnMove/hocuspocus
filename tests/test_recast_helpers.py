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
    ROOT / "app" / "services" / "recast_shot_planning.py",
    ROOT / "app" / "services" / "recast_shot_manifest.py",
    ROOT / "app" / "services" / "recast_shot_run.py",
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
# The Recast shot modules (C8a). recast_masks imports six shot helpers from recast_shot_planning; their bind is
# checked by test_recast_shot_modules_bind_exactly_the_names_their_functions_read.
SHOT_SERVICES = ("recast_shot_planning", "recast_shot_manifest", "recast_shot_run")


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
    assert all((services / f"{stem}.py").is_file() for stem in RECAST_SERVICES)
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
    # A name the slice imports from a shot module must be defined there.
    for stem in SHOT_SERVICES:
        shot_tree = ast.parse((services / f"{stem}.py").read_text(encoding="utf-8"), filename=f"{stem}.py")
        for node in shot_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name != "bind":
                assert node.name not in defined, f"{node.name} is defined twice in the recast services"
                defined[node.name] = stem

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
            # The shot modules (C8a) have their own bind check below.
            if isinstance(node, ast.ImportFrom) and (node.module or "").rsplit(".", 1)[-1] in RECAST_SERVICES:
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


def test_recast_shot_modules_bind_exactly_the_names_their_functions_read():
    """The bind list is the free names of the moved functions, derived here.

    A module whose every collaborator is imported has no ``bind`` and no free
    name. A module that still needs a launch object names that object in
    ``bind``'s keyword-only parameters, and in nothing else. ``Name = None``
    is only the slot ``bind`` fills. Launch imports each module once and calls
    ``bind`` once, and only when the module defines it.
    """
    services = ROOT / "app" / "services"
    launch = LAUNCH.read_text(encoding="utf-8")
    stems = (
        "recast_shot_planning",
        "recast_shot_manifest",
        "recast_shot_run",
    )
    present = [stem for stem in stems if (services / f"{stem}.py").is_file()]
    assert present and present[0] == "recast_shot_planning"

    for stem in present:
        path = services / f"{stem}.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        bind = next(
            (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "bind"),
            None,
        )
        slots = [
            node.targets[0].id
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and node.value.value is None
        ]
        assert launch.count(f"from services.{stem} import (") == 1, stem
        if bind is None:
            assert slots == [], slots
            assert _undefined_globals(source, str(path)) == set()
            assert f"_bind_{stem}(" not in launch
            continue
        assert bind.args.args == [] and bind.args.posonlyargs == []
        assert bind.args.vararg is None and bind.args.kwarg is None
        assert bind.args.defaults == []
        params = [arg.arg for arg in bind.args.kwonlyargs]
        assert params, f"{stem}.bind takes no names"
        assert sorted(slots) == sorted(params)
        kept = []
        for node in tree.body:
            if node is bind:
                continue
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in params
                and isinstance(node.value, ast.Constant)
                and node.value.value is None
            ):
                continue
            kept.append(node)
        stripped = ast.unparse(ast.Module(body=kept, type_ignores=[]))
        assert _undefined_globals(stripped, str(path)) == set(params)
        assert launch.count(f"_bind_{stem}(") == 1
        # bind writes each keyword into the slot of the same name, and nothing else.
        update = bind.body[-1].value
        assert isinstance(update, ast.Call) and ast.unparse(update.func) == "globals().update"
        assert {keyword.arg: ast.unparse(keyword.value) for keyword in update.keywords} == {p: p for p in params}
        # Launch passes each slot its own name, or a forwarder whose body calls that launch name when it runs.
        launch_tree = ast.parse(launch, filename=str(LAUNCH))
        launch_functions = {node.name: node for node in launch_tree.body if isinstance(node, ast.FunctionDef)}
        (call,) = [
            node for node in ast.walk(launch_tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == f"_bind_{stem}"
        ]
        assert not call.args and sorted(keyword.arg for keyword in call.keywords) == sorted(params)
        for keyword in call.keywords:
            assert isinstance(keyword.value, ast.Name), keyword.arg
            if keyword.value.id == keyword.arg:
                continue
            forwarder = launch_functions[keyword.value.id]
            body = [node for node in forwarder.body if not isinstance(node, ast.Expr)]
            assert len(body) == 1 and isinstance(body[0], ast.Return), forwarder.name
            assert ast.unparse(body[0].value) == f"{keyword.arg}(*args, **kwargs)", forwarder.name
            assert ast.unparse(forwarder.args) == "*args, **kwargs", forwarder.name


def test_timeline_preview_blends_the_anchor_and_returns_the_first_frame_when_nothing_is_found():
    """The preview card is the anchor frame, the mask tint and a character label."""
    import numpy as np
    from PIL import Image

    preview = _load(("_compose_recast_timeline_preview",))["_compose_recast_timeline_preview"]
    frames = np.full((2, 10, 20, 3), 100, dtype=np.uint8)
    frames[0, :, :, 1] = 20
    mask = np.zeros_like(frames)
    mask[1, 2:6, 4:9] = (0, 0, 200)
    found = {
        "found": True,
        "anchor_sample_index": 1,
        "anchor_time_seconds": 1.5,
        "mapping_index": 0,
        "color": (0, 0, 255),
    }

    with pytest.raises(ValueError, match="T/H/W/RGB"):
        preview(frames[0], [mask], [found])

    untouched = preview(frames, [mask], [{"found": False}])
    assert isinstance(untouched, Image.Image)
    assert untouched.size == (20, 10)
    assert untouched.getpixel((0, 0)) == (100, 20, 100)

    card = preview(frames, [mask], [found])
    assert card.size == (20, 34)
    assert card.getpixel((0, 0)) == (22, 24, 29)
    assert card.getpixel((10, 10)) == (0, 0, 255)
    assert card.getpixel((6, 6)) == (235, 235, 235)
    # 100 * 0.45 + 200 * 0.55 = 155 on the blue channel of the painted mask.
    assert card.getpixel((4, 24 + 2)) == (45, 45, 155)
    assert card.getpixel((0, 24)) == (100, 100, 100)

    second = dict(found, mapping_index=1, color=(255, 0, 0), anchor_sample_index=0)
    sheet = preview(frames, [mask, mask], [found, second], max_tile_width=8)
    assert sheet.size == (16, 28)


def test_shot_frames_resize_to_the_canvas_and_refuse_a_bad_shape():
    import numpy as np

    resize = _load(("_resize_recast_shot_frames",))["_resize_recast_shot_frames"]
    frames = np.zeros((1, 2, 2, 3), dtype=np.uint8)
    frames[0, 0, 0] = (255, 0, 0)
    frames[0, 0, 1] = (0, 255, 0)
    frames[0, 1, 0] = (0, 0, 255)
    frames[0, 1, 1] = (255, 255, 0)

    with pytest.raises(ValueError, match="T/H/W/RGB"):
        resize(frames[0], (4, 4))
    with pytest.raises(ValueError, match="positive"):
        resize(frames, (0, 4))

    same = resize(frames, (2, 2))
    assert same.shape == (1, 2, 2, 3)
    assert same is not frames
    assert np.array_equal(same, frames)

    nearest = resize(frames, (4, 4), semantic=True)
    assert nearest.shape == (1, 4, 4, 3)
    assert tuple(nearest[0, 0, 0]) == (255, 0, 0)
    assert tuple(nearest[0, 0, 1]) == (255, 0, 0)
    assert tuple(nearest[0, 1, 0]) == (255, 0, 0)
    assert tuple(nearest[0, 3, 3]) == (255, 255, 0)

    solid = np.full((2, 3, 5, 3), 40, dtype=np.uint8)
    scaled = resize(solid, (6, 4))
    assert scaled.shape == (2, 4, 6, 3)
    assert int(scaled.max()) == 40 and int(scaled.min()) == 40


def test_shot_video_refuses_an_empty_clip_and_writes_a_silent_file(tmp_path, monkeypatch):
    import numpy as np

    _block_network(monkeypatch)
    write = _load(("_write_recast_shot_video",), {"os": os})["_write_recast_shot_video"]
    frames = np.zeros((2, 8, 8, 3), dtype=np.uint8)
    frames[:, :, :, 2] = 255
    with pytest.raises(ValueError, match="empty or malformed"):
        write(str(tmp_path / "empty.mp4"), frames[:0], 8)
    with pytest.raises(ValueError, match="empty or malformed"):
        write(str(tmp_path / "flat.mp4"), frames[0], 8)

    path = tmp_path / "nested" / "shot.mp4"
    assert write(str(path), frames, 8) == str(path)
    assert path.is_file() and path.stat().st_size > 0
    mask_path = tmp_path / "mask.mp4"
    assert write(str(mask_path), frames, 8, semantic=True) == str(mask_path)
    assert mask_path.is_file() and mask_path.stat().st_size > 0


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


# -- review additions (C7 review, Opus): the blocks no test reached, recorded on 7a58ddf1b before the move ------------
def _digest(array) -> str:
    import hashlib

    import numpy as np

    array = np.ascontiguousarray(array)
    return f"{array.dtype}{list(array.shape)}:" + hashlib.sha256(array.tobytes()).hexdigest()[:16]


# Outputs recorded on 7a58ddf1b (the helpers still in launch), then checked unchanged after the move.
_RECORDED: dict = {
    ("character mask", True): (
        ["uint8[6, 8, 10, 3]:219cd850c2bd05b7", "uint8[6, 8, 10, 3]:f92c5edf9645656f"],
        "uint8[6, 8, 10, 3]:608ada8554651d3f", [0.0, 0.117647],
    ),
    ("character mask", False): (
        ["uint8[6, 8, 10, 3]:9d081652c6444daf", "uint8[6, 8, 10, 3]:47ba80d45375a428"],
        "uint8[6, 8, 10, 3]:69f343454c417bff", [0.0, 0.25],
    ),
    ("native people target masks", False): "uint8[4, 6, 8, 3]:fe2a3ec02e3405f9",
    ("native people target masks", True): "uint8[4, 6, 8, 3]:b7ff4960c773edaf",
    ("adaptive mask grown", "counts"): [84, 92],
    ("adaptive mask grown", "digest"): "uint8[2, 20, 20, 3]:f12fe8062fc367f8",
    ("edge cleanup", "default"): "uint8[16, 16, 3]:49a57161a2e1cafc",
    ("source scene", "small"): ("uint8[64, 96, 3]:313f8252c8e75493", "uint8[64, 96, 3]:d06e492668d53571", 0.09375),
    ("native people", "capacity"): ("uint8[1, 40, 60, 3]:8be040022280d253", "uint8[40, 60, 3]:c6cdbabcac891808"),
    ("native people", "partly behind"): ("uint8[1, 40, 60, 3]:ad2bb04484258bb6", "uint8[40, 60, 3]:ee58578f7ae19a4a"),
    ("native people", "weak track"): ("uint8[1, 40, 60, 3]:aac56bc389ec2d55", "uint8[40, 60, 3]:169e19fa52ee053f"),
    ("fit", "faint pixel"): ("uint8[34, 34, 3]:166e8314b0fceedb", "uint8[34, 34, 3]:00e02db86ef3d5d3"),
}


def _recorded(key, observed) -> None:
    assert key in _RECORDED, f"record {key!r}: {observed!r}"
    assert observed == _RECORDED[key], key


def _fake_magic_mask(monkeypatch, **functions):
    import sys
    import types

    fake = types.SimpleNamespace(**functions)
    shared = types.ModuleType("shared")
    shared.magic_mask = fake
    monkeypatch.setitem(sys.modules, "shared", shared)
    monkeypatch.setitem(sys.modules, "shared.magic_mask", fake)
    return fake


@pytest.mark.parametrize("recovered", [True, False])
def test_character_mask_recovers_shots_no_mapping_was_grounded_in(tmp_path, monkeypatch, capsys, recovered):
    import numpy as np

    colors = [(0, 0, 255), (255, 0, 0)]
    source = np.zeros((6, 8, 10, 3), dtype=np.uint8)
    for index in range(6):
        source[index] = index * 10
    calls: list = []

    def generate(frames, target, **kwargs):
        calls.append(("generate", target, [int(frame[0, 0, 0]) for frame in frames], kwargs["color_palette"],
                      kwargs["max_colored_objects"], kwargs["tracking_segments"], kwargs["no_hole"],
                      kwargs["colorize_objects"]))
        kwargs["progress_callback"](1, 2)
        painted = np.zeros_like(frames)
        if target == "hero":
            painted[0:2, 1:4, 1:4] = colors[0]
        elif target == "sidekick":
            painted[0:2, 5:7, 5:8] = colors[1]
            painted[1, 2:4, 2:4] = colors[1]
        else:
            painted[:, 2:5, 2:5] = colors[0]
        return painted

    def save(source_path, merged, fps, labels, **kwargs):
        calls.append(("save", source_path, _digest(merged), fps, labels, sorted(kwargs)))
        return "merged.mp4"

    _fake_magic_mask(monkeypatch, prepare_video_mask_input=lambda path: ("src.mp4", source, 12.0),
                     generate_keyword_masks=generate, save_mask_video=save)
    summaries = {"count": 0}

    def summarize(mask, fps):
        summaries["count"] += 1
        if summaries["count"] == 4:
            return None
        frames = [index for index in range(len(mask)) if mask[index].any()]
        return {"first_frame_index": frames[0], "frames": len(frames), "fps": fps, "call": summaries["count"]}

    def find_unmapped(masks, shot_ranges):
        calls.append(("find", [_digest(mask) for mask in masks], shot_ranges))
        return [{"shot_index": 1, "start_frame": 2, "end_frame": 4},
                {"shot_index": 2, "start_frame": 4, "end_frame": 6}]

    def recover(frames, masks, shot_ranges, unresolved, people, compact_ranges):
        calls.append(("recover", _digest(frames), [_digest(mask) for mask in masks], shot_ranges, unresolved,
                      _digest(people), compact_ranges))
        if not recovered:
            return masks, []
        output = [mask.copy() for mask in masks]
        output[0][2:4, 2:5, 2:5] = colors[0]
        output[1][4:6, 2:5, 2:5] = colors[1]
        return output, [{"shot_index": 1, "mapping_index": 0, "similarity": 0.91},
                        {"shot_index": 2, "mapping_index": 1, "similarity": 0.8}]

    aborts: list = []
    progress: list = []
    build = _load(
        ("_build_recast_character_mask", "_compose_recast_character_masks", "_recast_mask_region"),
        {
            "_RECAST_MASK_COLORS": colors,
            "_detect_recast_shot_ranges": lambda frames: [(0, 2), (2, 4), (4, 6)],
            "_normalize_recast_tracking_target": lambda target: target.strip().lower(),
            "_summarize_recast_mapping_mask": summarize,
            "_find_recast_unmapped_shots": find_unmapped,
            "_recover_recast_unmapped_shots": recover,
            "_select_recast_timeline_anchor": lambda masks: (None, 4),
        },
    )["_build_recast_character_mask"]

    result = build("source.mp4", [{"target": " Hero "}, {"target": "sidekick"}], str(tmp_path),
                   progress_callback=lambda *args: progress.append(args), abort_callback=lambda: aborts.append(1))

    printed = capsys.readouterr().out.splitlines()
    assert printed[:3] == [
        "[Recast] Detected 3 camera shots; reacquiring mapped characters after cuts at 0.17s, 0.33s.",
        "[Recast] SAM3 tracking wording normalized: ' Hero ' -> 'hero'.",
        "[Recast] No mapped target was grounded in camera shots 2, 3; running generic-person appearance recovery.",
    ]
    assert progress == [(0, 2, 1, 2), (1, 2, 1, 2)]
    assert len(aborts) == 5
    assert calls[0] == ("generate", "hero", [0, 10, 20, 30, 40, 50], [(0, 0, 255)], 1, [(0, 2), (2, 4), (4, 6)],
                        True, True)
    assert calls[1][1] == "sidekick" and calls[1][3] == [(255, 0, 0)]
    assert calls[3] == ("generate", "person", [20, 30, 40, 50], colors, 2, [(0, 2), (2, 4)], True, True)
    assert calls[4][3:] == ([(0, 2), (2, 4), (4, 6)],
                            [{"shot_index": 1, "start_frame": 2, "end_frame": 4},
                             {"shot_index": 2, "start_frame": 4, "end_frame": 6}],
                            calls[4][5], [(0, 2), (2, 4)])
    assert calls[-1][0] == "save" and calls[-1][1] == "src.mp4" and calls[-1][3] == 12.0
    assert calls[-1][4] == [" Hero ", "sidekick"] and calls[-1][5] == ["abort_callback", "background_color", "output_dir"]
    assert result["video_mask"] == "merged.mp4"
    assert result["shot_ranges"] == [[0, 2], [2, 4], [4, 6]] and result["shot_count"] == 3
    assert (result["common_frame_index"], result["scene_anchor_index"], result["timeline_aware"]) == (None, 4, True)
    assert result["fps"] == 12.0 and result["source_frames"] is source
    if recovered:
        assert printed[3:] == ["[Recast] Appearance recovery accepted shot 2 -> character A (0.91), "
                               "shot 3 -> character B (0.80)."]
        assert result["recovered_shots"][1] == {"shot_index": 2, "mapping_index": 1, "similarity": 0.8}
        assert result["mapping_summaries"] == [
            {"first_frame_index": 0, "frames": 4, "fps": 12.0, "call": 3, "mapping_index": 0, "target": " Hero ",
             "tracking_target": "hero", "color": [0, 0, 255], "recovered_shot_indices": [1],
             "overlap_fraction": result["overlaps"][0]},
            {"first_frame_index": 0, "frames": 2, "fps": 12.0, "call": 2, "mapping_index": 1, "target": "sidekick",
             "tracking_target": "sidekick", "color": [255, 0, 0], "recovered_shot_indices": [2],
             "overlap_fraction": result["overlaps"][1]},
        ]
    else:
        assert printed[3:] == ["[Recast] Generic-person recovery found no sufficiently distinct identity match; "
                               "unresolved shots remain unchanged."]
        assert result["recovered_shots"] == []
        assert [summary["call"] for summary in result["mapping_summaries"]] == [1, 2]
        assert "recovered_shot_indices" not in result["mapping_summaries"][0]
    _recorded(("character mask", recovered), (
        [_digest(mask) for mask in result["mapping_masks"]], _digest(result["mask_frames"]),
        [round(float(overlap), 6) for overlap in result["overlaps"]],
    ))


def test_target_group_reference_uses_the_shared_frame_and_falls_back_to_a_cast_sheet(tmp_path, capsys):
    import numpy as np
    from PIL import Image

    image = tmp_path / "target.png"
    mask = tmp_path / "target-mask.png"
    pixels = np.zeros((4, 6, 3), dtype=np.uint8)
    pixels[1:3, 2:4] = (200, 120, 40)
    Image.fromarray(pixels).save(image)
    semantic = np.zeros((4, 6, 3), dtype=np.uint8)
    semantic[1:3, 2:4] = (0, 0, 255)
    Image.fromarray(semantic).save(mask)
    calls: list = []
    fail = {"group": False}

    def group(source_frame, semantic_mask, layers, selected_count):
        calls.append(("group", _digest(source_frame), _digest(semantic_mask),
                      [(_digest(rgb), _digest(sem)) for rgb, sem in layers], selected_count))
        if fail["group"]:
            raise ValueError("nobody to place")
        return np.full((8, 8, 3), 7, dtype=np.uint8), np.full((8, 8, 3), 9, dtype=np.uint8)

    def cast(layers, selected_count, canvas):
        calls.append(("cast", [(_digest(rgb), _digest(sem)) for rgb, sem in layers], selected_count, canvas))
        return np.full((4, 4, 3), 3, dtype=np.uint8), np.full((4, 4, 3), 5, dtype=np.uint8)

    build = _load(
        ("_build_recast_target_group_reference",),
        {
            "os": os,
            "_compose_recast_group_reference_frame": group,
            "_compose_recast_cast_reference_frame": cast,
            "_normalize_recast_person_count": lambda value: max(1, min(5, int(value))),
        },
    )["_build_recast_target_group_reference"]
    refs = {"primary_target_refs": [{"image": str(image), "mask": str(mask)}], "reference_canvas": [64, 32]}
    frame = np.full((8, 8, 3), 1, dtype=np.uint8)
    frame_mask = np.full((8, 8, 3), 2, dtype=np.uint8)

    shared = build(refs, str(tmp_path / "out"), "job-1", 2, shared_source_frame=frame, shared_semantic_mask=frame_mask)
    assert shared == {
        "image": str(tmp_path / "out" / "recast_cast_ref_job-1.png"),
        "mask": str(tmp_path / "out" / "recast_cast_mask_job-1.png"),
        "mode": "shared_timeline_frame",
        "character_count": 2,
    }
    assert np.asarray(Image.open(shared["image"])).max() == 7 and np.asarray(Image.open(shared["mask"])).max() == 9
    layer = (_digest(pixels), _digest(semantic))
    assert calls == [("group", _digest(frame), _digest(frame_mask), [layer], 2)]

    calls.clear()
    fail["group"] = True
    fallback = build(refs, str(tmp_path / "out"), "job-2", 7, shared_source_frame=frame, shared_semantic_mask=frame_mask)
    assert fallback["mode"] == "cast_sheet" and fallback["character_count"] == 5
    assert calls == [("group", _digest(frame), _digest(frame_mask), [layer], 7), ("cast", [layer], 7, [64, 32])]
    assert capsys.readouterr().out == (
        "[Recast] Shared-frame cast layout was unavailable; using a neutral cast sheet: nobody to place\n"
    )
    assert np.asarray(Image.open(fallback["image"])).max() == 3

    calls.clear()
    assert build(refs, str(tmp_path / "out"), "job-3", 1, shared_source_frame=frame)["mode"] == "cast_sheet"
    assert calls == [("cast", [layer], 1, [64, 32])]
    with pytest.raises(ValueError, match="needs prepared target image/mask pairs"):
        build({"primary_target_refs": [{"image": str(image)}]}, str(tmp_path / "out"), "job-4", 1)


@pytest.mark.parametrize("resize", [False, True])
def test_native_people_conditioning_keeps_bystanders_in_a_group_reference(tmp_path, monkeypatch, resize):
    import numpy as np
    from PIL import Image

    source = np.zeros((4, 6, 8, 3), dtype=np.uint8)
    for index in range(4):
        source[index] = 40 + index
    target_masks = np.zeros((2, 3, 4, 3) if resize else (2, 6, 8, 3), dtype=np.uint8)
    target_masks[1, 1:2, 1:3] = (0, 0, 255)
    calls: list = []

    def prepare(path):
        return (path, source, 10.0) if path == "source.mp4" else (path, target_masks, 10.0)

    def people(frames, target, **kwargs):
        calls.append(("people", _digest(frames), target, kwargs["color_palette"], kwargs["max_colored_objects"],
                      kwargs["progress_callback"]))
        return np.full_like(frames, 11)

    def save(source_path, driving, fps, labels, **kwargs):
        calls.append(("save", source_path, _digest(driving), fps, labels, kwargs))
        return str(tmp_path / "driving.mp4")

    _fake_magic_mask(monkeypatch, prepare_video_mask_input=prepare, generate_keyword_masks=people,
                     save_mask_video=save)

    def native(masks, all_people, selected_count, reference_frame_index=0):
        calls.append(("native", _digest(masks), _digest(all_people), selected_count, reference_frame_index))
        return np.full_like(masks, 21), np.full((6, 8, 3), 22, dtype=np.uint8), 3, [{"kept": True}]

    def group(frame, semantic, layers, selected_count):
        calls.append(("group", _digest(frame), _digest(semantic), [(_digest(a), _digest(b)) for a, b in layers],
                      selected_count))
        return np.full((6, 8, 3), 31, dtype=np.uint8), np.full((6, 8, 3), 32, dtype=np.uint8)

    image = tmp_path / "target.png"
    mask = tmp_path / "mask.png"
    Image.fromarray(np.full((2, 2, 3), 61, dtype=np.uint8)).save(image)
    Image.fromarray(np.full((2, 2, 3), 62, dtype=np.uint8)).save(mask)
    build = _load(
        ("_build_recast_native_people_conditioning",),
        {
            "os": os,
            "_RECAST_PROTECTION_COLORS": [(0, 0, 255), (255, 0, 0), (0, 255, 0)],
            "_normalize_recast_person_count": lambda value: int(value),
            "_compose_recast_native_people_masks": native,
            "_compose_recast_group_reference_frame": group,
        },
    )["_build_recast_native_people_conditioning"]
    progress = lambda *_args: None  # noqa: E731

    result = build("source.mp4", "mask.mp4", 1, str(tmp_path / "out"), "job",
                   target_references=[{"image": str(image), "mask": str(mask)}], progress_callback=progress,
                   reference_frame_index=2)
    assert result == {
        "video_mask": str(tmp_path / "driving.mp4"),
        "reference_image": str(tmp_path / "out" / "recast_group_ref_job.png"),
        "reference_mask": str(tmp_path / "out" / "recast_group_mask_job.png"),
        "conditioning_count": 3,
        "assignments": [{"kept": True}],
    }
    assert np.asarray(Image.open(result["reference_image"])).max() == 31
    assert np.asarray(Image.open(result["reference_mask"])).max() == 32
    assert calls[0] == ("people", _digest(source), "person", [(0, 0, 255), (255, 0, 0), (0, 255, 0)], 3, progress)
    assert calls[1][2:] == (_digest(np.full_like(source, 11)), 1, 2)
    assert calls[2] == ("save", "source.mp4", _digest(np.full((4, 6, 8, 3), 21, dtype=np.uint8)), 10.0,
                        ["recast people"], {"output_dir": str(tmp_path / "out")})
    assert calls[3] == ("group", _digest(source[2]), _digest(np.full((6, 8, 3), 22, dtype=np.uint8)),
                        [(_digest(np.full((2, 2, 3), 61, dtype=np.uint8)),
                          _digest(np.full((2, 2, 3), 62, dtype=np.uint8)))], 1)
    # The two-frame target mask was stretched to the four source frames (and resized to the source size).
    _recorded(("native people target masks", resize), calls[1][1])

    with pytest.raises(ValueError, match="needs prepared target image/mask pairs"):
        build("source.mp4", "mask.mp4", 1, str(tmp_path / "out"), "job", target_references=["not a pair"])


def _conditioning(monkeypatch, calls, detail_size, subject):
    import numpy as np
    from PIL import Image

    _fake_magic_mask(monkeypatch, generate_keyword_masks=lambda *args, **kwargs: calls.append(("sam", args, kwargs)))

    def prepare_frame(reference_path, color, *, isolate_reference, aligned_semantic_mask, subject_conditioning,
                      spatial_background, width, height):
        calls.append(("prepare", Path(reference_path).name, color, isolate_reference, aligned_semantic_mask,
                      None if subject_conditioning is None else _digest(subject_conditioning[0]),
                      spatial_background, width, height))
        shade = 40 + len(calls)
        return {
            "image": Image.new("RGB", (width, height), (shade, 0, 0)),
            "mask": Image.new("RGB", (width, height), tuple(color)),
            "identity_image": Image.new("RGB", (4, 4), (0, shade, 0)),
            "mask_source": "stub matte",
            "source_size": (12, 10),
            "prepared_size": (width, height),
        }

    def derive(reference_path, output_path, *, refine_cutout):
        calls.append(("derive", Path(reference_path).name, Path(output_path).name, refine_cutout))
        Path(output_path).write_bytes(b"detail")
        detail = np.zeros((10, 10), dtype=bool)
        detail[3:6, 3:6] = True
        return {
            "source_conditioning": (subject, None),
            "detail_conditioning": (detail, None),
            "metadata": {"crop_box": [1, 2, 7, 8], "detail_size": list(detail_size), "detail_source": "stub",
                         "ignored": True},
        }

    return _load(
        (
            "_prepare_recast_reference_conditioning",
            "_recast_should_add_auto_face_detail",
            "_recast_face_detail_upscale_factor",
            "_recast_region_bbox_aspect",
            "_recast_reference_preview_payload",
            "_recast_image_data_uri",
        ),
        {
            "os": os,
            "_RECAST_MASK_COLORS": [(0, 0, 255), (255, 0, 0)],
            "_prepare_recast_reference_frame": prepare_frame,
            "_derive_recast_face_detail_reference": derive,
            "_recast_reference_canvas_size": lambda frame: calls.append(("canvas", _digest(frame))) or (96, 64),
            "_build_recast_source_scene_layers": lambda *args, **kwargs: calls.append(("scene", kwargs)) or {
                "image": "scene"},
            "_align_recast_reference_mask": lambda *args: (_ for _ in ()).throw(AssertionError("not aligned")),
        },
    )["_prepare_recast_reference_conditioning"]


@pytest.mark.parametrize("case", ["enlarged too far", "full body", "kept"])
def test_reference_conditioning_drops_a_face_detail_view_it_will_not_use(tmp_path, monkeypatch, capsys, case):
    import numpy as np
    from PIL import Image

    reference = tmp_path / "hero.png"
    reference.write_bytes(b"png")
    wide = np.zeros((10, 10), dtype=bool)
    wide[2:5, 0:10] = True
    probe = np.zeros((10, 10, 3), dtype=np.uint8)
    probe[0:10, 4:6] = (0, 0, 255)
    calls: list = []
    prepare = _conditioning(monkeypatch, calls, [100, 100] if case == "enlarged too far" else [600, 400], wide)
    output = tmp_path / "out"

    result = prepare(
        [{"target": "hero", "ref_image_path": str(reference)}],
        None if case == "kept" else probe,
        str(output), "job", isolate_reference=True, selected_count=1, reference_canvas=[640, 352],
    )

    detail = output / "recast_auto_face_detail_job_1.png"
    assert calls[0] == ("derive", "hero.png", detail.name, True)
    assert calls[1] == ("prepare", "hero.png", (0, 0, 255), True, None, _digest(wide), None, 640, 352)
    assert result["reference_canvas"] == [640, 352]
    assert result["clip_identity_ref"] == str(output / "recast_clip_identity_ref_job_1_1.png")
    with Image.open(result["clip_identity_ref"]) as identity:  # the isolated identity view, not the prepared frame
        assert identity.size == (4, 4) and identity.getpixel((0, 0))[1] > 0
    assert result["primary_target_refs"] == [{"mapping_index": 0, "image": str(output / "recast_prepared_ref_job_1_1.png"),
                                              "mask": str(output / "recast_prepared_mask_job_1_1.png"),
                                              "color": [0, 0, 255]}]
    printed = capsys.readouterr().out
    if case == "kept":
        assert detail.read_bytes() == b"detail"
        assert printed == ""
        assert calls[2] == ("prepare", detail.name, (0, 0, 255), True, None, _digest(_detail_mask()), None, 640, 352)
        assert result["image_refs"] == [str(output / "recast_prepared_ref_job_1_1.png"),
                                        str(output / "recast_prepared_ref_job_1_2.png")]
        assert result["auto_face_detail_refs"] == [{"mapping_index": 0, "crop_box": [1, 2, 7, 8],
                                                    "detail_size": [600, 400], "detail_source": "stub",
                                                    "ignored": True, "detail_upscale_factor": 0.88}]
        assert [preview["kind"] for preview in result["previews"]] == ["primary", "auto_face_detail"]
        assert {key: result["previews"][1][key] for key in ("crop_box", "detail_size", "detail_upscale_factor")} == {
            "crop_box": [1, 2, 7, 8], "detail_size": [600, 400], "detail_upscale_factor": 0.88}
        assert "ignored" not in result["previews"][1] and "clip_identity_image" in result["previews"][0]
        assert result["expected_colors"] == [[0, 0, 255], [0, 0, 255]]
        assert result["additional_masks"] == [str(output / "recast_prepared_mask_job_1_2.png")]
    else:
        assert not detail.exists()
        reason = ("the crop would require 3.52x enlargement" if case == "enlarged too far" else
                  "the source target is full-body while the identity reference is already a tighter upper-body view")
        assert printed == f"[Recast] Skipped automatic face-detail spatial view for mapping 1: {reason}.\n"
        assert len(calls) == 2 and result["auto_face_detail_refs"] == []
        assert result["image_refs"] == [str(output / "recast_prepared_ref_job_1_1.png")]
        assert [preview["kind"] for preview in result["previews"]] == ["primary"]


def _detail_mask():
    import numpy as np

    detail = np.zeros((10, 10), dtype=bool)
    detail[3:6, 3:6] = True
    return detail


def test_reference_conditioning_checks_an_explicit_canvas_and_falls_back_to_the_anchor_frame(tmp_path, monkeypatch):
    import numpy as np

    reference = tmp_path / "hero.png"
    reference.write_bytes(b"png")
    calls: list = []
    prepare = _conditioning(monkeypatch, calls, [600, 400], np.ones((4, 4), dtype=bool))
    mappings = [{"target": "hero", "ref_image_path": str(reference), "additional_ref_image_paths": [str(reference)]}]
    for canvas, message in (([640], "must contain width and height"), (("wide", 64), "must contain width and height"),
                            ([100, 64], "divisible by 32"), ([64, 100], "divisible by 32"), ([0, 64], "divisible by 32"),
                            ([-64, 64], "divisible")):
        with pytest.raises(ValueError, match=message):
            prepare(mappings, None, str(tmp_path / "out"), "job", isolate_reference=False, selected_count=1,
                    reference_canvas=canvas)
    assert calls == []

    anchor = np.full((5, 7, 3), 9, dtype=np.uint8)
    mask = np.zeros((5, 7, 3), dtype=np.uint8)
    result = prepare(mappings, None, str(tmp_path / "out"), "job", isolate_reference=False, selected_count=2,
                     mapping_anchors=[{"source_frame": anchor, "source_mask": mask}])
    assert calls[0] == ("canvas", _digest(anchor))
    assert calls[1] == ("scene", {"output_size": (96, 64)})
    assert [call[:3] + call[6:] for call in calls[2:]] == [
        ("prepare", "hero.png", (0, 0, 255), "scene", 96, 64),
        ("prepare", "hero.png", (0, 0, 255), "scene", 96, 64),
    ]
    assert result["reference_canvas"] == [96, 64]
    assert result["clip_identity_ref"] == result["image_refs"][0]
    calls.clear()
    plain = prepare([{"target": "hero", "ref_image_path": str(reference)}], None, str(tmp_path / "plain"), "job",
                    isolate_reference=False, selected_count=1, auto_face_detail=False)
    assert plain["reference_canvas"] == [832, 480]
    assert calls == [("prepare", "hero.png", (0, 0, 255), False, None, None, None, 832, 480)]
    assert [preview["kind"] for preview in result["previews"]] == ["primary", "additional"]
    with pytest.raises(ValueError, match="needs at least one prepared reference"):
        prepare([], None, str(tmp_path / "out"), "job", isolate_reference=False, selected_count=1)


# -- review additions, round 2: one case per mutation the suite let through (failing first under that mutation) --------
def test_color_region_keeps_a_lossy_tracking_color_within_its_tolerance():
    import numpy as np

    region = _load(("_recast_color_region",))["_recast_color_region"]
    frames = np.zeros((1, 2, 3, 3), dtype=np.uint8)
    frames[0, 0] = [(0, 0, 255), (30, 20, 180), (0, 0, 160)]
    frames[0, 1] = [(90, 0, 255), (91, 0, 255), (0, 90, 165)]
    assert region(frames, (0, 0, 255)).tolist() == [[[True, True, False], [True, False, True]]]
    assert region(frames, (0, 0, 255), tolerance=0).tolist() == [[[True, False, False], [False, False, False]]]


def test_adaptive_mask_grows_the_matched_track_by_the_seven_pixel_kernel(tmp_path, monkeypatch, capsys):
    import numpy as np

    color = (0, 0, 255)
    saved = {}

    def prepare(path):
        if path == "generated.mp4":
            return path, np.zeros((2, 20, 20, 3), dtype=np.uint8), 8
        source = np.full((2, 10, 10, 3), 255, dtype=np.uint8)
        source[:, 4:6, 4:6] = color
        return path, source, 8

    def people(frames, *_args, **_kwargs):
        painted = np.zeros_like(frames)
        painted[:, 8:12, 8:12] = color
        painted[1, 9, 12:14] = color  # a two-pixel spur the close/dilate absorbs
        return painted

    def save(_source, masks, _fps, _labels, **_kwargs):
        saved["masks"] = masks.copy()
        return str(tmp_path / "adaptive.mp4")

    _fake_magic_mask(monkeypatch, prepare_video_mask_input=prepare, generate_keyword_masks=people,
                     save_mask_video=save)
    build = _load(
        ("_build_recast_adaptive_mask", "_select_recast_generated_regions", "_recast_color_region"),
        {"os": os, "_RECAST_MASK_COLORS": [color], "_RECAST_PROTECTION_COLORS": [color, (255, 255, 0)]},
    )["_build_recast_adaptive_mask"]
    build("generated.mp4", "source.mp4", 1, str(tmp_path))
    painted = (saved["masks"] == color).all(axis=-1)
    rows, cols = np.nonzero(painted[0])
    # 4x4 match at 8..11, grown by the 7x7 ellipse: three pixels on every side.
    assert (int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())) == (5, 14, 5, 14)
    _recorded(("adaptive mask grown", "counts"), [int(painted[0].sum()), int(painted[1].sum())])
    _recorded(("adaptive mask grown", "digest"), _digest(saved["masks"]))
    assert capsys.readouterr().out.startswith("  [Recast] Adaptive protection selected track 0: ")


def test_character_masks_refuse_an_overlap_over_35_percent():
    import numpy as np

    compose = _load(("_compose_recast_character_masks",))["_compose_recast_character_masks"]
    first = np.zeros((1, 4, 10), dtype=np.uint8)
    first[0, :, 0:5] = 1
    allowed = np.zeros_like(first)
    allowed[0, :, 3:10] = 1  # 8 of its 28 pixels (29%) lie on the first card
    refused = np.zeros_like(first)
    refused[0, :, 2:10] = 1  # 12 of 32 (37.5%)
    merged, overlaps = compose([first, allowed], [(0, 0, 255), (255, 0, 0)])
    assert overlaps == [0.0, 8 / 28]
    assert merged[0, 0].tolist() == [[0, 0, 255]] * 5 + [[255, 0, 0]] * 5
    with pytest.raises(ValueError, match="Character mapping 2 overlaps an earlier mapping by 38%"):
        compose([first, refused], [(0, 0, 255), (255, 0, 0)])
    assert compose([first, refused], [(0, 0, 255), (255, 0, 0)], overlap_limit=0.4)[1] == [0.0, 0.375]


def test_character_mappings_keep_at_most_four_additional_views_each():
    normalize = _load(
        ("_normalize_recast_character_mappings",),
        {"_RECAST_MASK_COLORS": [(0, 0, 255)] * 5, "_resolve_recast_media": lambda raw, workspace: f"/{workspace}/{raw}"},
    )["_normalize_recast_character_mappings"]
    views = [f"view-{index}.png" for index in range(6)]
    explicit, _ = normalize({"character_mappings": [{"target": "a", "ref_image_path": "a.png",
                                                     "additional_ref_image_paths": views}]}, "ws")
    legacy, _ = normalize({"ref_image_path": "a.png", "additional_ref_image_paths": views}, "ws")
    expected = [f"/ws/view-{index}.png" for index in range(4)]
    assert explicit[0]["additional_ref_image_paths"] == expected
    assert legacy[0]["additional_ref_image_paths"] == expected


def _recast_constants() -> dict:
    """The module constants of the slice, evaluated from the file that defines them (launch before the move)."""
    wanted = ("_RECAST_MASK_COLORS", "_RECAST_PROTECTION_COLORS", "_RECAST_U2NET_CACHE_LIMIT",
              "_RECAST_RELIGHTING_LORA_FILENAME", "_RECAST_RELIGHTING_LORA_REVISION",
              "_RECAST_RELIGHTING_LORA_REMOTE_PATH", "_RECAST_RELIGHTING_LORA_SHA256", "_RECAST_RELIGHTING_LORA_SIZE",
              "_RECAST_FAST_MODEL_TYPE", "_RECAST_LEGACY_FAST_MODEL_TYPE", "_RECAST_RESOLUTION_PROFILES",
              "_RECAST_WARMUP_FRAMES")
    namespace: dict = {}
    homes: dict = {}
    for path in (LAUNCH, *[path for path in SERVICE_FILES if path.is_file()]):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                    and node.targets[0].id in wanted:
                homes.setdefault(node.targets[0].id, []).append(path.name)
                exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    assert {name: len(files) for name, files in homes.items()} == dict.fromkeys(wanted, 1), homes
    return {name: namespace[name] for name in wanted}


def test_the_recast_constants_keep_their_values_and_one_definition():
    constants = _recast_constants()
    masks = [(0, 0, 255), (255, 0, 0), (0, 255, 0), (255, 0, 255), (0, 255, 255)]
    assert constants == {
        "_RECAST_MASK_COLORS": masks,
        "_RECAST_PROTECTION_COLORS": masks + [(255, 255, 0), (255, 128, 0), (128, 0, 255), (0, 192, 128),
                                              (255, 64, 128)],
        "_RECAST_U2NET_CACHE_LIMIT": 8,
        "_RECAST_RELIGHTING_LORA_FILENAME": "scail2_relighting_lora.safetensors",
        "_RECAST_RELIGHTING_LORA_REVISION": "150cc0ca4e98e50e60b9295dacde39442fdccab2",
        "_RECAST_RELIGHTING_LORA_REMOTE_PATH": "model/relighting-lora.pt",
        "_RECAST_RELIGHTING_LORA_SHA256": "80d338a7969c1b286c8f5c4996b37eb198d0864837fecb6c87c106ca74571a2b",
        "_RECAST_RELIGHTING_LORA_SIZE": 1_227_381_060,
        "_RECAST_FAST_MODEL_TYPE": "scail2_14B_recast_fast",
        "_RECAST_LEGACY_FAST_MODEL_TYPE": "scail2_14B_fast",
        "_RECAST_RESOLUTION_PROFILES": {"480p": (832, 480), "512p": (896, 512), "704p": (1280, 704)},
        "_RECAST_WARMUP_FRAMES": 8,
    }


def test_a_legacy_mapping_without_a_target_tracks_a_person():
    normalize = _load(
        ("_normalize_recast_character_mappings",),
        {"_RECAST_MASK_COLORS": [(0, 0, 255)] * 5, "_resolve_recast_media": lambda raw, workspace: f"/{raw}"},
    )["_normalize_recast_character_mappings"]
    for body in ({"ref_image_path": "a.png"}, {"ref_image_path": "a.png", "target": "   "},
                 {"ref_image_path": "a.png", "target": None}):
        mappings, explicit = normalize(body, "ws")
        assert (mappings[0]["target"], mappings[0]["id"], explicit) == ("person", "recast-1", False)


def test_mask_region_counts_any_channel_over_30():
    import numpy as np

    region = _load(("_recast_mask_region",))["_recast_mask_region"]
    rgb = np.zeros((1, 1, 4, 3), dtype=np.uint8)
    rgb[0, 0] = [(31, 0, 0), (30, 30, 30), (0, 0, 45), (0, 200, 0)]
    assert region(rgb).tolist() == [[[True, False, True, True]]]
    assert region(np.array([[0, 2, 1]], dtype=np.uint8)).tolist() == [[False, True, True]]


def test_recolor_paints_the_shot_local_slot_color():
    import numpy as np

    colors = [(0, 0, 255), (255, 0, 0), (0, 255, 0)]
    recolor = _load(("_recolor_recast_reference_mask",), {"_RECAST_MASK_COLORS": colors})[
        "_recolor_recast_reference_mask"]
    mask = np.zeros((1, 3, 3), dtype=np.uint8)
    mask[0, 0] = (0, 0, 255)
    mask[0, 1] = (255, 0, 0)
    out = recolor(mask, 0, 2)
    assert out.tolist() == [[[0, 255, 0], [0, 0, 0], [0, 0, 0]]]
    # A mask without the global color keeps every visible pixel, in the local color.
    loose = np.zeros((1, 2, 3), dtype=np.uint8)
    loose[0, 0] = (40, 40, 40)
    assert recolor(loose, 1, 0).tolist() == [[[0, 0, 255], [0, 0, 0]]]


def test_reference_alignment_accepts_any_overlap_above_one_percent():
    import numpy as np

    align = _load(("_align_recast_reference_mask",))["_align_recast_reference_mask"]
    target, other = (0, 0, 255), (255, 0, 0)
    source = np.zeros((20, 20, 3), dtype=np.uint8)
    source[0:10, 0:10] = target  # 100 px
    reference = np.zeros_like(source)
    reference[9:19, 7:17] = other  # 100 px, 3 of them on the target: IoU 3/197
    aligned, matched = align(source, reference, [target], [target, other])
    assert matched == 1
    assert (aligned == target).all(axis=-1).sum() == 100 and bool((aligned[9:19, 7:17] == target).all())
    far = np.zeros_like(source)
    far[15:20, 15:20] = other
    kept, none = align(source, far, [target], [target, other])
    assert none == 0 and bool((kept[0:10, 0:10] == target).all())


def test_generated_tracks_need_a_score_of_two_percent():
    import numpy as np

    colors = [(0, 0, 255)]
    select = _load(
        ("_select_recast_generated_regions", "_recast_color_region"),
        {"_RECAST_MASK_COLORS": colors, "_RECAST_PROTECTION_COLORS": colors + [(255, 255, 0)]},
    )["_select_recast_generated_regions"]
    source = np.full((1, 40, 40, 3), 255, dtype=np.uint8)
    source[0, 0:10, 0:10] = colors[0]  # 100 px target
    generated = np.zeros_like(source)
    generated[0, 9:29, 4:24] = (255, 255, 0)  # 400 px, 6 on the target: score 6 / 200
    adaptive, scores = select(source, generated, 1)
    assert scores == [(1, 0.03, 6)]
    assert int(adaptive.sum()) == 100 + 400 - 6
    generated[0, 9, 4:24] = 0  # 380 px, none on the target
    with pytest.raises(ValueError, match=r"\(0/1 matched\)"):
        select(source, generated, 1)


def test_u2net_matte_keys_its_cache_on_the_file_and_keeps_the_eight_newest(tmp_path, monkeypatch):
    """The moved module itself (not an exec'd copy): one lazily loaded CPU session, the alpha-matting call, the
    cache key (path, mtime, size) and the eviction of the oldest entry past eight. The same calls gave the same
    counts before the move (the review differential runs them against the launch functions at 7a58ddf1b)."""
    import numpy as np
    from PIL import Image

    import services.recast_matte as matte
    import services.rembg_adapter as rembg

    state = matte.RecastU2NetState()
    monkeypatch.setattr(matte, "_recast_u2net", state)
    monkeypatch.setattr(matte, "_app_dir", str(tmp_path))
    monkeypatch.delenv("U2NET_HOME", raising=False)
    _block_network(monkeypatch)
    sessions: list = []
    runs: list = []

    def background_session(model, force_cpu=False):
        sessions.append((model, force_cpu))
        return ("session", len(sessions))

    def remove_background_image(image, **kwargs):
        runs.append(kwargs)
        rgba = np.zeros((*np.asarray(image).shape[:2], 4), dtype=np.uint8)
        rgba[..., 3] = 255
        return Image.fromarray(rgba)

    monkeypatch.setattr(rembg, "background_session", background_session)
    monkeypatch.setattr(rembg, "remove_background_image", remove_background_image)
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    paths = []
    for index in range(9):
        path = tmp_path / f"ref-{index}.png"
        path.write_bytes(b"x" * (index + 1))
        paths.append(path)
        matte._run_recast_u2net_matte(frame, str(path))
    assert sessions == [("u2net", True)]
    assert state.session == ("session", 1)
    assert runs[0] == {"model": "u2net", "session": ("session", 1), "alpha_matting": True,
                       "alpha_matting_erode_size": 1, "bgcolor": (0, 0, 0, 0)}
    assert [key[0] for key in state.cache] == [os.path.normcase(os.path.realpath(path)) for path in paths[1:]]
    assert os.environ["U2NET_HOME"] == os.path.join(str(tmp_path), "ckpts", "rembg")
    matte._run_recast_u2net_matte(frame, str(paths[8]))
    assert len(runs) == 9  # cached
    matte._run_recast_u2net_matte(frame, str(paths[0]))
    assert len(runs) == 10  # the oldest was evicted
    os.utime(paths[8], ns=(1, 1))
    matte._run_recast_u2net_matte(frame, str(paths[8]))
    assert len(runs) == 11  # a new mtime is a new key
    matte._run_recast_u2net_matte(frame)
    assert len(runs) == 12 and len(state.cache) == 8  # no path, no cache entry
    state.session = None
    matte._get_recast_u2net_session()
    assert sessions == [("u2net", True), ("u2net", True)]


@pytest.mark.parametrize("first_frame, aware", [(0, False), (2, True)])
def test_character_mask_is_timeline_aware_only_when_the_target_enters_late(tmp_path, monkeypatch, first_frame, aware):
    import numpy as np

    colors = [(0, 0, 255)]
    source = np.zeros((4, 6, 6, 3), dtype=np.uint8)

    def generate(frames, target, **kwargs):
        painted = np.zeros_like(frames)
        painted[first_frame:, 1:3, 1:3] = colors[0]
        return painted

    _fake_magic_mask(monkeypatch, prepare_video_mask_input=lambda path: ("src.mp4", source, 10.0),
                     generate_keyword_masks=generate, save_mask_video=lambda *args, **kwargs: "mask.mp4")
    build = _load(
        ("_build_recast_character_mask", "_compose_recast_character_masks"),
        {
            "_RECAST_MASK_COLORS": colors,
            "_detect_recast_shot_ranges": lambda frames: [(0, 4)],
            "_normalize_recast_tracking_target": lambda target: target,
            "_summarize_recast_mapping_mask": lambda mask, fps: {"first_frame_index": first_frame},
            "_find_recast_unmapped_shots": lambda masks, ranges: [],
            "_select_recast_timeline_anchor": lambda masks: (first_frame, first_frame),
        },
    )["_build_recast_character_mask"]
    result = build("source.mp4", [{"target": "hero"}], str(tmp_path))
    assert (result["shot_count"], result["timeline_aware"], result["recovered_shots"]) == (1, aware, [])
    assert result["common_frame_index"] == first_frame


def test_reference_instance_lets_area_outweigh_centrality():
    import numpy as np

    select = _load(("_select_recast_reference_instance", "_clean_recast_reference_region"))[
        "_select_recast_reference_instance"]
    mask = np.zeros((40, 40, 3), dtype=np.uint8)
    mask[15:25, 15:25] = (0, 0, 255)  # 100 px in the middle
    mask[0:11, 0:11] = (255, 0, 0)  # 121 px in a corner: area wins with a 0.25 centrality weight
    region, info = select(mask, [(0, 0, 255), (255, 0, 0)])
    assert info == {"instance_count": 2, "selected_index": 1, "discarded_components": 0}
    assert int(region.sum()) == 121 and bool(region[0, 0])


def test_reference_matte_keeps_pixels_whose_mask_passes_30():
    import numpy as np

    matte = _load(("_matte_recast_reference_frame",))["_matte_recast_reference_frame"]
    frame = np.full((1, 3, 3), 200, dtype=np.uint8)
    mask = np.zeros((1, 3, 3), dtype=np.uint8)
    mask[0, 0] = (31, 0, 0)
    mask[0, 1] = (30, 30, 30)
    mask[0, 2] = (0, 0, 90)
    assert matte(frame, mask).tolist() == [[[200] * 3, [127] * 3, [200] * 3]]
    assert matte(frame, mask, neutral_value=0)[0, 1].tolist() == [0, 0, 0]


def test_edge_cleanup_defaults_to_three_pixel_rings():
    import numpy as np

    clean = _load(("_decontaminate_recast_reference_edges",))["_decontaminate_recast_reference_edges"]
    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    frame[..., 0] = np.arange(16, dtype=np.uint8)[None, :] * 15
    frame[..., 1] = np.arange(16, dtype=np.uint8)[:, None] * 11
    frame[..., 2] = 90
    subject = np.zeros((16, 16), dtype=bool)
    subject[2:14, 2:14] = True
    default = clean(frame, subject)
    assert default.tolist() == clean(frame, subject, width=3).tolist()
    assert default.tolist() != clean(frame, subject, width=2).tolist()
    _recorded(("edge cleanup", "default"), _digest(default))


def test_u2net_matte_hands_out_copies_of_a_cached_cutout(tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image

    import services.recast_matte as matte
    import services.rembg_adapter as rembg

    monkeypatch.setattr(matte, "_recast_u2net", matte.RecastU2NetState())
    monkeypatch.setattr(matte, "_app_dir", str(tmp_path))
    monkeypatch.delenv("U2NET_HOME", raising=False)
    _block_network(monkeypatch)
    monkeypatch.setattr(rembg, "background_session", lambda model, force_cpu=False: "session")
    monkeypatch.setattr(rembg, "remove_background_image",
                        lambda image, **_kwargs: Image.fromarray(np.full((2, 2, 4), 200, dtype=np.uint8)))
    path = tmp_path / "ref.png"
    path.write_bytes(b"ref")
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    matte._run_recast_u2net_matte(frame, str(path))
    first_rgb, first_alpha = matte._run_recast_u2net_matte(frame, str(path))
    first_rgb[:] = 0
    first_alpha[:] = 0
    again_rgb, again_alpha = matte._run_recast_u2net_matte(frame, str(path))
    assert again_rgb.tolist() == [[[200] * 3] * 2] * 2
    assert np.allclose(again_alpha, 200 / 255.0) and float(again_alpha.min()) > 0


def test_source_scene_hides_a_margin_of_at_least_two_pixels():
    import numpy as np

    colors = [(0, 0, 255)]
    layers = _load(
        ("_build_recast_source_scene_layers", "_recast_color_region"),
        {"_RECAST_MASK_COLORS": colors, "_normalize_recast_person_count": lambda value: int(value)},
    )["_build_recast_source_scene_layers"]
    frame = np.full((64, 96, 3), 120, dtype=np.uint8)
    mask = np.zeros_like(frame)
    mask[20:40, 30:50] = colors[0]
    small = layers(frame, mask, 1)
    assert small["expansion_pixels"] == 2
    _recorded(("source scene", "small"), (_digest(small["image"]), _digest(small["mask"]), small["hidden_fraction"]))
    assert layers(frame, mask, 1, output_size=(1600, 1200))["expansion_pixels"] == 12


def test_fit_crops_to_every_pixel_the_semantic_mask_marks_over_30():
    import numpy as np

    fit = _load(("_fit_recast_reference_layers", "_recast_subject_crop_box"))["_fit_recast_reference_layers"]
    rgb = np.full((40, 40, 3), 90, dtype=np.uint8)
    semantic = np.zeros((40, 40, 3), dtype=np.uint8)
    semantic[20:30, 20:30] = (0, 0, 255)
    semantic[2, 2] = (40, 0, 0)  # faint, still part of the subject
    image, mask = fit(rgb, semantic, 34, 34)
    assert mask.size == (34, 34)
    assert int((np.asarray(mask)[..., 0] == 40).sum()) == 1
    _recorded(("fit", "faint pixel"), (_digest(np.asarray(image)), _digest(np.asarray(mask))))


@pytest.mark.parametrize("case", ["capacity", "partly behind", "weak track"])
def test_native_people_masks_keep_four_bystanders_and_skip_target_duplicates(case):
    import numpy as np

    masks = [(0, 0, 255), (255, 0, 0), (0, 255, 0), (255, 0, 255), (0, 255, 255)]
    protection = masks + [(255, 255, 0), (255, 128, 0), (128, 0, 255), (0, 192, 128), (255, 64, 128)]
    compose = _load(
        ("_compose_recast_native_people_masks", "_recast_color_region"),
        {"_RECAST_MASK_COLORS": masks, "_RECAST_PROTECTION_COLORS": protection,
         "_normalize_recast_person_count": lambda value: int(value)},
    )["_compose_recast_native_people_masks"]
    targets = np.full((1, 40, 60, 3), 255, dtype=np.uint8)
    targets[0, 0:10, 0:10] = masks[0]  # the selected target, 100 px
    people = np.zeros_like(targets)
    if case == "weak track":
        people[0, 9:29, 4:24] = protection[5]  # its broad track: 6 px on it, a score of 0.03
        people[0, 0:20, 30:50] = protection[6]
        expected = (2, [(6, 1, 400)])
    else:
        people[0, 0:6, 0:10] = protection[5]  # its track
        people[0, 6:8, 0:10] = protection[2]  # a fragment of the target (all on it): never a bystander
        people[0, 0:20, 30:50] = protection[6]  # 400 px
        people[0, 20:35, 30:50] = protection[7]  # 300 px
        if case == "capacity":
            people[0, 30:40, 0:20] = protection[8]  # 200 px
            people[0, 35:40, 40:60] = protection[9]  # 100 px
            people[0, 0:5, 52:60] = protection[1]  # 40 px: no slot left
            expected = (5, [(6, 1, 400), (7, 2, 300), (8, 3, 200), (9, 4, 100)])
        else:
            people[0, 8:10, 0:6] = protection[4]  # 12 px on the target ...
            people[0, 10:12, 0:4] = protection[4]  # ... and 8 beside it: 60 % overlap, still a bystander
            expected = (4, [(6, 1, 400), (7, 2, 300), (4, 3, 20)])
    driving, group, count, assignments = compose(targets, people, 1)
    assert (count, assignments) == expected
    assert driving[0, 0, 0].tolist() == list(masks[0]) and driving[0, 0, 30].tolist() == list(masks[1])
    assert group[0, 0].tolist() == list(masks[0])
    _recorded(("native people", case), (_digest(driving), _digest(group)))


def test_reference_canvas_follows_the_source_orientation_on_a_32px_grid():
    import numpy as np

    canvas = _load(("_recast_reference_canvas_size",))["_recast_reference_canvas_size"]
    assert canvas(np.zeros((400, 500, 3), dtype=np.uint8)) == (576, 480)  # 600 floors to 576, not 592
    assert canvas(np.zeros((500, 400, 3), dtype=np.uint8)) == (480, 576)
    assert canvas(np.zeros((400, 500, 3), dtype=np.uint8), block_size=16) == (592, 480)
    with pytest.raises(ValueError, match="H/W/RGB"):
        canvas(np.zeros((4, 4), dtype=np.uint8))


def test_media_lookup_prefers_the_workspace_then_uploads_then_outputs(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    for folder in (workspace, tmp_path / "uploads", tmp_path / "outputs"):
        folder.mkdir()
        (folder / "same.png").write_bytes(folder.name.encode())
    (tmp_path / "uploads" / "both.png").write_bytes(b"up")
    (tmp_path / "outputs" / "both.png").write_bytes(b"out")
    monkeypatch.chdir(tmp_path)
    resolve = _load(("_resolve_recast_media",), {"os": os, "_workspace_dir": lambda _name: str(workspace)})[
        "_resolve_recast_media"]
    assert resolve("same.png", "demo") == str(workspace / "same.png")
    assert resolve("both.png", "demo") == os.path.join(str(tmp_path), "uploads", "both.png")


def test_audio_probe_needs_a_clean_exit_and_a_stream(monkeypatch):
    import subprocess

    answers = {}
    monkeypatch.setattr(subprocess, "run", lambda command, **_kwargs: subprocess.CompletedProcess(
        command, *answers[command[-1]], stderr=""))
    has_audio = _load(("_recast_video_has_audio",))["_recast_video_has_audio"]
    answers.update({"ok.mp4": (0, "audio\n"), "failed.mp4": (1, "audio\n"), "silent.mp4": (0, "  \n")})
    assert [has_audio(name) for name in ("ok.mp4", "failed.mp4", "silent.mp4")] == [True, False, False]


def test_crop_boxes_and_the_face_detail_limits():
    import numpy as np

    loaded = _load(("_recast_subject_crop_box", "_recast_should_add_auto_face_detail",
                    "_recast_face_detail_upscale_factor", "_recast_region_bbox_aspect"))
    subject = np.zeros((200, 200), dtype=bool)
    subject[50:150, 40:140] = True  # 100x100: an 8 px margin
    assert loaded["_recast_subject_crop_box"](subject) == (32, 42, 148, 158)
    tiny = np.zeros((20, 20), dtype=bool)
    tiny[5:10, 5:10] = True  # the margin never drops below 4 px
    assert loaded["_recast_subject_crop_box"](tiny) == (1, 1, 14, 14)
    should = loaded["_recast_should_add_auto_face_detail"]
    # A 450x260 crop needs 1.846x to fill 832x480: over the 1.75 limit.
    assert should({}, True, detail_size=(450, 260), canvas_size=(832, 480)) is False
    assert should({}, True, detail_size=(500, 290), canvas_size=(832, 480)) is True
    target = np.zeros((40, 40), dtype=bool)
    target[0:25, 0:17] = True  # 17/25 = 0.68: not a full-body silhouette
    wide = np.zeros((40, 40), dtype=bool)
    wide[0:10, 0:12] = True  # 1.2
    tall = np.zeros((40, 40), dtype=bool)
    tall[0:25, 0:15] = True  # 0.6
    assert should({}, True, source_probe_mask=target, semantic_color=(0, 0, 255), reference_subject=wide) is True
    assert should({}, True, source_probe_mask=tall, semantic_color=(0, 0, 255), reference_subject=wide) is False


def test_appearance_prototypes_keep_the_six_largest_shots_per_mapping():
    import numpy as np

    prototypes = _load(
        ("_build_recast_mapping_appearance_prototypes", "_recast_mask_region"),
        {"_recast_appearance_descriptor": lambda frame, region: (
            None if int(frame[0, 0, 0]) == 30 else [int(frame[0, 0, 0]), int(region.sum())])},
    )["_build_recast_mapping_appearance_prototypes"]
    frames = np.zeros((8, 12, 12, 3), dtype=np.uint8)
    mask = np.zeros((8, 12, 12), dtype=np.uint8)
    for index in range(8):
        frames[index] = index * 10
        mask[index, 0:index + 1, 0:4] = 1  # the later the shot, the larger the person
    shots = [(index, index + 1) for index in range(8)]
    built = prototypes(frames, [mask, np.zeros_like(mask)], shots)
    # Frame 3 gives no descriptor; the six largest of the rest, largest first.
    assert built == [[[70, 32], [60, 28], [50, 24], [40, 20], [20, 12], [10, 8]], []]
    assert prototypes(frames, [mask], shots, max_per_mapping=2) == [[[70, 32], [60, 28]]]
    assert prototypes(frames, [mask], None) == [[[70, 32]]]  # no shots: the whole clip is one
