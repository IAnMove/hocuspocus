"""Numbers read from a JSON request body.

A Studio edit route used to cast fields with a bare ``float(body.get(key, default))``. A value that is not a
number (``"abc"``, ``null``, an object) then raised inside the handler and the client got a 500 with no hint
(validation findings edit-01, edit-02, edit-03; 30 casts in all). These helpers read the same value the same way
but refuse a non-number with ``400`` and the field's name, before the route decodes a video, starts SAM or
registers a job. ``400`` is what these routes, and the neighbouring Repaint trim check, answer for every other
bad request field; ``422`` in this code base belongs to the typed command layer and FastAPI's own schema checks.

Only the type is checked. Ranges stay with each route's own clamps, and numeric text such as ``"4"`` is still
accepted, as it always was.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from fastapi import HTTPException

NOT_A_NUMBER_STATUS = 400


def _refuse(key: str, kind: Callable[[Any], Any]) -> HTTPException:
    what = "a whole number" if kind is int else "a number"
    return HTTPException(status_code=NOT_A_NUMBER_STATUS, detail=f"{key} must be {what}")


def number_field(body: dict, key: str, default: Any, kind: Callable[[Any], Any] = float):
    """``kind(body.get(key, default))``; a value that does not convert answers 400 naming ``key``.

    ``kind`` is ``float`` (the default) or ``int``. NaN and infinity are not numbers here either: they pass
    ``float()`` and then fail later (``int(round(inf))``) as a 500.
    """
    value = body.get(key, default)
    try:
        number = kind(value)
    except (TypeError, ValueError, OverflowError):
        raise _refuse(key, kind) from None
    if isinstance(number, float) and not math.isfinite(number):
        raise _refuse(key, kind)
    return number


def optional_number(body: dict, key: str, kind: Callable[[Any], Any] = float):
    """The number in ``body[key]``, or ``None`` when the field is absent or ``null``."""
    if body.get(key) is None:
        return None
    return number_field(body, key, None, kind)
