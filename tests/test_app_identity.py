from pathlib import Path

from app_identity import VERSION_PATH, read_app_version


def test_product_version_comes_only_from_version_file():
    root = Path(__file__).resolve().parents[1]
    asserted = (root / "VERSION").read_text(encoding="utf-8").splitlines()[0].strip()
    assert VERSION_PATH.resolve() == (root / "VERSION").resolve()
    assert read_app_version() == asserted
    assert asserted
    assert asserted != "1.6.5"
