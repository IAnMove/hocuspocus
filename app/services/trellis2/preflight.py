"""Fail before source/package downloads when the optional runtime cannot fit."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
if shutil.disk_usage(ROOT).free < 40 * 1024**3:
    raise SystemExit("Error: TRELLIS.2 needs at least 40 GiB free for its isolated CUDA runtime and optional weights. Free space and retry; the main studio is unaffected.")
