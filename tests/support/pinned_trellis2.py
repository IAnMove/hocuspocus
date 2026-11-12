"""TRELLIS.2's runtime row reads this machine's GPU, folders and weights; goldens record its shape only."""
from __future__ import annotations

REASON = "TRELLIS.2 is optional and supports Linux x64 with NVIDIA 24GB only."
PINNED = {"installed": False, "compatible": False, "weights_downloaded": False,
          "compatibility_reason": REASON, "install_hint": REASON}


def pin_trellis2_runtime(monkeypatch) -> None:
    from services import model3d_external
    monkeypatch.setattr(model3d_external, "_trellis2_status", lambda _configured: dict(PINNED))
