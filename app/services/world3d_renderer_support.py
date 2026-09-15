"""Check the built renderer and installed browser without launching a render."""
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess


@lru_cache(maxsize=4)
def _browser_path(module: str) -> str:
    try:
        result = subprocess.run(
            ["node", "--input-type=module", "-e", "const { chromium } = await import(process.argv[1]); process.stdout.write(chromium.executablePath())", Path(module).as_uri()],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def renderer_available(app_url: str, module: Path | None) -> bool:
    entry = Path(__file__).resolve().parents[2] / "ui" / "dist" / "world3d-render.html"
    if not app_url or not entry.is_file() or not module or not shutil.which("node"):
        return False
    browser = _browser_path(str(module))
    return bool(browser and Path(browser).is_file())
