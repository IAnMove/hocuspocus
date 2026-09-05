"""Read the split HTTP client surface as one string for source contracts."""
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1] / "ui" / "src" / "api"


def api_client_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(API_DIR.glob("*.ts"))
    )
