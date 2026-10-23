"""A known wrong wheel tag is corrected only when the package really loads; all else is left to uv."""
import base64
import hashlib
import importlib.metadata as metadata
import importlib.util
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[1]
WRONG = "Tag: cp36-cp36m-manylinux2010_x86_64\n"


def _not_installed(name):
    raise metadata.PackageNotFoundError(name)


@pytest.fixture
def case(tmp_path):
    spec = importlib.util.spec_from_file_location("wheel_tags_test", ROOT / "scripts/runtime_wheel_tags.py")
    tags = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tags)
    info = tmp_path / "site-packages" / "decord-0.6.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: decord\nVersion: 0.6.0\n")
    wheel = info / "WHEEL"
    wheel.write_text("Wheel-Version: 1.0\n" + WRONG)
    (info / "RECORD").write_text("decord-0.6.0.dist-info/WHEEL,sha256=old,1\ndecord/__init__.py,sha256=keep,4\n")
    distribution = metadata.PathDistribution(info)
    loaded = []
    # Replace the module's own references, so the interpreter's real importlib stays untouched.
    tags.sys = SimpleNamespace(platform="linux", prefix=str(tmp_path))
    tags.platform = SimpleNamespace(machine=lambda: "x86_64")
    tags.importlib = SimpleNamespace(
        import_module=loaded.append,
        metadata=SimpleNamespace(
            distribution=lambda name: distribution if name == "decord" else _not_installed(name),
            PackageNotFoundError=metadata.PackageNotFoundError))
    return SimpleNamespace(tags=tags, wheel=wheel, loaded=loaded, tmp=tmp_path,
                           record=info / "RECORD", metadata=info / "METADATA")


def test_known_tag_is_corrected_after_the_package_loads_and_record_follows(case, capsys):
    assert case.tags.repair_known_tags() == ["decord"]
    assert case.loaded == ["decord"]
    assert case.wheel.read_text() == "Wheel-Version: 1.0\nTag: py3-none-manylinux2010_x86_64\n"
    digest = base64.urlsafe_b64encode(hashlib.sha256(case.wheel.read_bytes()).digest()).decode().rstrip("=")
    record = case.record.read_text()
    assert f"decord-0.6.0.dist-info/WHEEL,sha256={digest},{case.wheel.stat().st_size}" in record
    assert "decord/__init__.py,sha256=keep,4" in record
    assert "corrected its upstream WHEEL tag" in capsys.readouterr().out


def test_shared_uv_cache_copy_is_never_modified(case):
    cached = case.tmp / "uv-cache-copy"
    os.link(case.wheel, cached)
    case.tags.repair_known_tags()
    assert "py3-none" in case.wheel.read_text()
    assert "cp36-cp36m" in cached.read_text()


def test_a_second_run_changes_nothing(case):
    case.tags.repair_known_tags()
    corrected = case.wheel.read_bytes()
    assert case.tags.repair_known_tags() == []
    assert case.wheel.read_bytes() == corrected


@pytest.mark.parametrize("scenario", [
    "other_version", "other_tag", "extra_tag", "windows", "macos", "arm", "not_installed", "wheel_not_in_record"])
def test_anything_else_is_left_for_uv_to_report(case, scenario):
    if scenario == "other_version":
        case.metadata.write_text("Metadata-Version: 2.1\nName: decord\nVersion: 0.6.1\n")
    elif scenario == "other_tag":
        case.wheel.write_text("Tag: cp310-cp310-manylinux2010_x86_64\n")
    elif scenario == "extra_tag":
        case.wheel.write_text(WRONG + "Tag: py3-none-any\n")
    elif scenario == "windows":
        case.tags.sys.platform = "win32"
    elif scenario == "macos":
        case.tags.sys.platform = "darwin"
    elif scenario == "arm":
        case.tags.platform.machine = lambda: "aarch64"
    elif scenario == "wheel_not_in_record":
        case.record.write_text("decord/__init__.py,sha256=keep,4\n")
    else:
        case.tags.importlib.metadata.distribution = _not_installed
    before = case.wheel.read_bytes(), case.record.read_bytes()
    assert case.tags.repair_known_tags() == []
    assert (case.wheel.read_bytes(), case.record.read_bytes()) == before
    assert case.loaded == [], "A package whose tag is not the known one must not even be imported"


@pytest.mark.parametrize("scenario", ["import_error", "outside_environment", "malformed_record_row"])
def test_unverified_package_or_invalid_destination_never_rewrites_metadata(case, scenario):
    if scenario == "import_error":
        def fail(_):
            raise ImportError("libdecord.so failed to load")
        case.tags.importlib.import_module = fail
        expected = ImportError
    elif scenario == "outside_environment":
        case.tags.sys.prefix = str(case.tmp / "a-different-environment")
        expected = RuntimeError
    else:
        case.record.write_text("decord-0.6.0.dist-info/WHEEL\n")
        expected = RuntimeError
    before = case.wheel.read_bytes(), case.record.read_bytes()
    with pytest.raises(expected):
        case.tags.repair_known_tags()
    assert (case.wheel.read_bytes(), case.record.read_bytes()) == before


def test_repair_does_not_make_existing_installs_look_out_of_date(tmp_path):
    """The repair only helps a new install, so editing it must not change any install fingerprint."""
    from services import runtime_profiles as profiles
    source = tmp_path / "source"
    for name in ["app/runtime", "app/requirements.txt", "app/scripts/install_gguf_kernels.py", "app/services/sam/requirements.txt",
                 "runtime_install.js", "vendor_revisions.js", "hunyuan_native.js", "torch.js",
                 "scripts/runtime_verify.py", "scripts/runtime_pip.py", "scripts/runtime_failed.py",
                 "scripts/runtime_vendor.py", "scripts/runtime_wheel_tags.py", "app/services/runtime_sources.py"]:
        src, dest = ROOT / name, source / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest) if src.is_dir() else shutil.copy2(src, dest)
    with patch.object(profiles, "APP_DIR", source / "app"):
        before = {(engine, system): profiles.dependency_fingerprint(engine, system)
                  for engine in ("wangp", "sam") for system in ("linux", "win32")}
        (source / "scripts/runtime_wheel_tags.py").write_text("# edited\n")
        runtime_install = source / "runtime_install.js"
        runtime_install.write_text(runtime_install.read_text() + "\n// edited\n")
        after = {key: profiles.dependency_fingerprint(*key) for key in before}
    assert after == before
