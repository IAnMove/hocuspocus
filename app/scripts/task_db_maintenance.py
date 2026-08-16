"""Repository-friendly entry point for task database maintenance."""

from pathlib import Path
import sys


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from services.task_maintenance import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
