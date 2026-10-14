"""The process-wide hardware probe.

``detect_hardware`` is machine-specific, so the answer is cached on
``hardware_cache``. The full server imports ``_get_cached_hardware`` and
passes that function object to the coefficient pass and the director
pipeline. Nothing here is injected: the cache is this module's own object.
"""


class HardwareCache:
    """The one cached probe result. ``value`` is None until the first call."""

    def __init__(self) -> None:
        self.value: dict | None = None


hardware_cache = HardwareCache()


def _get_cached_hardware() -> dict:
    if hardware_cache.value is None:
        try:
            from services.hardware_detect import detect_hardware
            hardware_cache.value = detect_hardware()
        except Exception as e:
            print(f"[VRAM] hardware probe failed ({e}); per-job adjustment disabled")
            hardware_cache.value = {"gpu_vram_gb": 0.0}
    return hardware_cache.value
