"""Exercise settings updates against WanGP's effective profile selector on CPU."""
import ast
import asyncio
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    functions = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            functions.append(node)
    assert {node.name for node in functions} == set(names)
    exec(compile(ast.Module(body=functions, type_ignores=[]), path, "exec"), namespace)


@pytest.fixture
def settings_runtime(tmp_path):
    config = {"video_profile": 3, "image_profile": 3, "audio_profile": 3}
    config_path = tmp_path / "wgp_config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    resident_offload = object()
    wgp = SimpleNamespace(
        server_config=config, server_config_filename=str(config_path),
        default_profile_video=3, default_profile_image=3, default_profile_audio=3,
        default_profile=3, force_profile_no=-1, loaded_profile=3,
        offloadobj=resident_offload, attention_mode="auto", args=SimpleNamespace(),
    )
    load_functions("app/wgp.py", ["_normalize_output_type", "get_default_profile", "compute_profile"], wgp.__dict__)
    namespace = {"wgp": wgp, "Request": object, "HTTPException": HTTPException, "json": json, "os": os, "uuid": uuid}
    load_functions("app/_launch_runtime.py", ["_validated_memory_profile_updates", "update_system_config", "_save_server_config"], namespace)

    def update(body):
        async def read_body():
            return body
        return asyncio.run(namespace["update_system_config"](SimpleNamespace(json=read_body)))

    return wgp, config_path, update


@pytest.mark.parametrize("output_type", ["video", "image", "audio"])
@pytest.mark.parametrize("profile", [1, 2, 3, 3.5, 4, 4.5, 5])
def test_saved_profile_is_effective_for_the_next_selection_only(settings_runtime, output_type, profile):
    wgp, config_path, update = settings_runtime
    resident = wgp.offloadobj
    key = f"{output_type}_profile"

    assert update({key: profile})["updated"] == {key: profile}
    assert json.loads(config_path.read_text())[key] == profile
    assert wgp.compute_profile(-1, output_type) == profile
    assert wgp.compute_profile(2, output_type) == 2
    for other in {"video", "image", "audio"} - {output_type}:
        assert wgp.get_default_profile(other) == 3
    assert wgp.default_profile == (profile if output_type == "video" else 3)
    assert wgp.loaded_profile == 3
    assert wgp.offloadobj is resident


def test_partial_and_combined_updates_preserve_force_profile_precedence(settings_runtime):
    wgp, _, update = settings_runtime
    update({"video_profile": 5, "image_profile": 3.5, "audio_profile": 4.5})
    assert [wgp.get_default_profile(kind) for kind in ("video", "image", "audio")] == [5, 3.5, 4.5]
    assert wgp.get_default_profile(None) == 5
    assert wgp.default_profile == 5
    wgp.force_profile_no = 1
    update({"video_profile": 4})
    assert wgp.compute_profile(-1, "video") == 1
    assert wgp.compute_profile(5, "video") == 5
    wgp.force_profile_no = -1
    assert wgp.compute_profile(-1, "video") == 4


@pytest.mark.parametrize("invalid", [True, False, "5", None, 0, -1, 3.25, 6, float("nan"), float("inf")])
def test_invalid_profile_rejects_the_entire_update_before_mutation(settings_runtime, invalid):
    wgp, config_path, update = settings_runtime
    original_file = config_path.read_bytes()
    with pytest.raises(HTTPException) as caught:
        update({"attention_mode": "sdpa", "video_profile": 5, "image_profile": invalid})
    assert caught.value.status_code == 400
    assert config_path.read_bytes() == original_file
    assert wgp.server_config == {"video_profile": 3, "image_profile": 3, "audio_profile": 3}
    assert wgp.attention_mode == "auto"
    assert wgp.default_profile == wgp.get_default_profile("video") == 3
