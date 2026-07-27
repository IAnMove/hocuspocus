"""Structured per-task timing for multi-panel generation queues."""

from __future__ import annotations

import re
import time
from typing import Callable


class GenerationTaskTimer:
    """Measure total and phase durations for one queue task."""

    def __init__(
        self,
        panel_no: int,
        panel_total: int,
        prompt_preview: str = "",
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._started_at = self._clock()
        self._phase_started_at = self._started_at
        self._phase = ""
        self._finished = False
        self.data = {
            "panel_no": int(panel_no),
            "panel_total": int(panel_total),
            "prompt_preview": str(prompt_preview),
            "status": "running",
            "phase_timings": [],
        }

    @staticmethod
    def _normalize_phase(value: object) -> str:
        phase = str(value or "").split("|", 1)[0].strip()
        phase = re.sub(r"\b\d+/\d+\b", "#/#", phase)
        return re.sub(r"\s+", " ", phase)

    def phase(self, value: object) -> None:
        phase = self._normalize_phase(value)
        if not phase or phase == self._phase or self._finished:
            return
        now = self._clock()
        self._close_phase(now)
        self._phase = phase
        self._phase_started_at = now

    def finish(self, status: str) -> dict:
        if self._finished:
            return self.data
        now = self._clock()
        self._close_phase(now)
        self.data["total_seconds"] = round(now - self._started_at, 3)
        self.data["status"] = str(status)
        self._finished = True
        return self.data

    def _close_phase(self, now: float) -> None:
        if not self._phase:
            return
        self.data["phase_timings"].append(
            {
                "phase": self._phase,
                "seconds": round(now - self._phase_started_at, 3),
            }
        )
