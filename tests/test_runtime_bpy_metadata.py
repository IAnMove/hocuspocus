"""The installer repairs only a verified upstream tag; ABI failures stay errors."""
import base64
import hashlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("bpy_metadata_test", Path(__file__).parents[1] / "scripts/runtime_bpy_metadata.py")
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    folder = tmp_path / "bpy-4.2.22.dist-info"; folder.mkdir()
    wheel = folder / "WHEEL"
    wheel.write_text("Wheel-Version: 1.0\nTag: cp39-cp39-manylinux_2_28_x86_64\n")
    (folder / "RECORD").write_text("bpy-4.2.22.dist-info/WHEEL,sha256=old,1\nother/file,sha256=keep,4\n")
    distribution = SimpleNamespace(version="4.2.22", metadata={"Requires-Python": "==3.11.*"},
                                   files=[Path("bpy-4.2.22.dist-info/WHEEL")], locate_file=lambda entry: tmp_path / entry)
    monkeypatch.setattr(helper, "sys", SimpleNamespace(platform="linux", version_info=(3, 11), prefix=str(tmp_path)))
    monkeypatch.setattr(helper.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(helper.importlib.metadata, "distribution", lambda _: distribution)
    monkeypatch.setattr(helper.importlib, "import_module", lambda _: SimpleNamespace(app=SimpleNamespace(version=(4, 2, 22))))
    return helper, wheel, distribution


def test_verified_repair_updates_record_and_leaves_shared_cache_intact(fixture, tmp_path):
    helper, wheel, _ = fixture
    cached = tmp_path / "cached-wheel"; os.link(wheel, cached)
    assert helper.repair_bpy_metadata()
    assert "cp311-cp311" in wheel.read_text()
    assert "cp39-cp39" in cached.read_text()
    digest = base64.urlsafe_b64encode(hashlib.sha256(wheel.read_bytes()).digest()).decode().rstrip("=")
    record = wheel.with_name("RECORD").read_text()
    assert f"sha256={digest},{wheel.stat().st_size}" in record
    assert "other/file,sha256=keep,4" in record
    assert not helper.repair_bpy_metadata()  # Retry is harmless, not another edit.


@pytest.mark.parametrize("case", ["different_version", "different_python", "different_tag"])
def test_unknown_mismatch_is_left_for_uv_to_reject(fixture, monkeypatch, case):
    helper, wheel, distribution = fixture
    if case == "different_version": distribution.version = "4.3.0"
    elif case == "different_python": distribution.metadata["Requires-Python"] = "==3.12.*"
    else: wheel.write_text("Tag: cp310-cp310-manylinux_2_28_x86_64\n")
    original = wheel.read_bytes()
    monkeypatch.setattr(helper.importlib, "import_module", lambda _: pytest.fail("Unverified binary must not be imported"))
    assert not helper.repair_bpy_metadata()
    assert wheel.read_bytes() == original


@pytest.mark.parametrize("case", ["import_error", "binary_version", "outside_environment", "missing_record"])
def test_unverified_binary_and_invalid_destination_never_rewrite_metadata(fixture, monkeypatch, tmp_path, case):
    helper, wheel, _ = fixture
    if case == "import_error":
        def fail(_): raise ImportError("Blender ABI failed")
        monkeypatch.setattr(helper.importlib, "import_module", fail)
    elif case == "binary_version":
        monkeypatch.setattr(helper.importlib, "import_module", lambda _: SimpleNamespace(app=SimpleNamespace(version=(4, 2, 0))))
    elif case == "outside_environment": helper.sys.prefix = str(tmp_path / "different-env")
    else: wheel.with_name("RECORD").write_text("other/file,sha256=keep,4\n")
    original = wheel.read_bytes()
    with pytest.raises((ImportError, RuntimeError)):
        helper.repair_bpy_metadata()
    assert wheel.read_bytes() == original
