#!/usr/bin/env python3
"""Resume Hunyuan3D-2 turbo weights with a single download stream."""

from __future__ import annotations

import os
import time

os.environ.setdefault("HF_HOME", "/home/ina/pinokio/api/Maestro-next.git/app/ckpts/model3d/huggingface")
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", os.path.join(os.environ["HF_HOME"], "hub"))
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("HF_ENDPOINT", "https://huggingface.co")

from huggingface_hub import snapshot_download

PATTERNS = [
    "hunyuan3d-dit-v2-0-turbo/*",
    "hunyuan3d-paint-v2-0-turbo/*",
]


def main() -> None:
    last_error: Exception | None = None
    for attempt in range(1, 12):
        try:
            path = snapshot_download(
                "tencent/Hunyuan3D-2",
                allow_patterns=PATTERNS,
                max_workers=1,
            )
            print(f"OK {path}", flush=True)
            return
        except Exception as exc:
            last_error = exc
            print(f"attempt {attempt}/11 failed: {exc}", flush=True)
            time.sleep(min(60, attempt * 5))
    raise SystemExit(str(last_error))


if __name__ == "__main__":
    main()
