#!/usr/bin/env python3
"""Audit the three local LTX-2.3 Phase 2A candidates without downloading."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


MODEL_FILES = {
    "ltx2_22B_distilled_gguf_q6_k": (
        "LTX-2.3 Distilled GGUF Q6_K Light 22B",
        "ltx-2.3-22b-distilled-Q6_K_light.gguf",
        "distilled",
    ),
    "ltx2_22B_distilled_1_1": (
        "LTX-2.3 Distilled Quanto BF16 INT8 22B",
        "ltx-2.3-22b-distilled-1.1_diffusion_model_quanto_bf16_int8.safetensors",
        "distilled",
    ),
    "ltx2_22B_fp8": (
        "LTX-2.3 Dev FP8 22B",
        "ltx-2.3-22b-dev-fp8.safetensors",
        "dev_two_stage",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", type=Path, default=Path("app"))
    parser.add_argument("--shared-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--read-bytes", type=int, default=1024 * 1024)
    args = parser.parse_args()

    app_root = args.app_root.resolve()
    local_root = app_root / "ckpts"
    shared_root = args.shared_root.resolve()
    os.environ["MAESTRO_READ_ONLY_CHECKPOINTS"] = str(shared_root)

    import sys

    sys.path.insert(0, str(app_root))
    from shared.utils import files_locator

    files_locator.set_checkpoints_paths([str(local_root), str(app_root)])
    report = {
        "environment": {
            "MAESTRO_READ_ONLY_CHECKPOINTS": os.environ[
                "MAESTRO_READ_ONLY_CHECKPOINTS"
            ],
            "local_checkpoint_root": str(local_root),
            "shared_checkpoint_roots": files_locator.get_read_only_checkpoints_paths(),
        },
        "models": {},
    }

    for model_id, (name, filename, pipeline) in MODEL_FILES.items():
        locate_started = time.perf_counter()
        path = Path(files_locator.locate_file(filename)).resolve()
        locate_seconds = time.perf_counter() - locate_started

        open_started = time.perf_counter()
        with path.open("rb", buffering=0) as handle:
            prefix = handle.read(args.read_bytes)
        open_seconds = time.perf_counter() - open_started

        simulated = Path(
            files_locator.get_smart_download_location(
                f"phase2a-simulated-{filename}"
            )
        ).resolve()
        blocked = False
        try:
            files_locator.assert_writable_path(path, operation="benchmark mutation")
        except PermissionError:
            blocked = True

        report["models"][model_id] = {
            "catalog_name": name,
            "pipeline": pipeline,
            "filename": filename,
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "read_only": files_locator.is_read_only_path(path),
            "mutation_guard_blocked": blocked,
            "locate_seconds": round(locate_seconds, 6),
            "open_and_read_seconds": round(open_seconds, 6),
            "bytes_read": len(prefix),
            "simulated_new_download": str(simulated),
            "simulated_download_is_local": (
                simulated == local_root / simulated.name
                and not files_locator.is_read_only_path(simulated)
            ),
        }

    report["all_present"] = all(
        item["read_only"] and item["mutation_guard_blocked"]
        for item in report["models"].values()
    )
    report["downloads_performed"] = False

    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["all_present"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
