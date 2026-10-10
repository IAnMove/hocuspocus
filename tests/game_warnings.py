"""Warning codes of game attempts, for test assertions (``game_library.game_warning`` objects)."""
from __future__ import annotations


def warning_codes(items) -> list[str]:
    """Codes from warning objects, and from a legacy ``code`` or ``code:ref`` string."""
    codes: list[str] = []
    for item in items or []:
        if isinstance(item, dict) and isinstance(item.get("code"), str):
            codes.append(item["code"])
        elif isinstance(item, str) and item:
            codes.append(item.split(":", 1)[0])
    return codes
