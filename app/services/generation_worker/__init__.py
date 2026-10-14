"""The generation worker: ``_run_generation`` split into a frame and the phases it chains through.

The code was ``_run_generation`` in ``app/_launch_runtime.py``. ``bind_generation_worker`` hands each module
the full server objects it uses, once, after the server has defined them.
"""
from services.generation_worker import finalize


def bind_generation_worker(**names):
    """Bind the full server's objects into every worker module (keyword names are the names they use)."""
    finalize.bind(**names)
