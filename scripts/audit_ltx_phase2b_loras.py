#!/usr/bin/env python3
"""Audit Maestro Next's local/write and shared/read-only LoRA resolution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.shared.utils import files_locator


TARGET = "ltx-2.3-22b-distilled-lora-384.safetensors"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=Path("."))
    parser.add_argument(
        "--shared-root",
        type=Path,
        default=Path("/home/ina/pinokio/api/Maestro.git/app/loras"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    repository = args.repository.resolve()
    local_root = repository / "app" / "loras"
    os.environ[files_locator.READ_ONLY_LORAS_ENV] = str(args.shared_root.resolve())
    files_locator.set_loras_paths([str(local_root)])

    resolved = files_locator.locate_lora_file(TARGET, relative_dir="ltx2")
    simulated = files_locator.get_lora_download_location(
        "phase2b-simulated.safetensors", relative_dir="ltx2"
    )
    mutation_blocked = False
    try:
        files_locator.assert_writable_lora_path(resolved, "rename")
    except PermissionError:
        mutation_blocked = True

    report = {
        "environment": {
            files_locator.READ_ONLY_LORAS_ENV: os.environ[
                files_locator.READ_ONLY_LORAS_ENV
            ]
        },
        "resolved": resolved,
        "resolved_read_only": files_locator.is_read_only_lora_path(resolved),
        "size_bytes": Path(resolved).stat().st_size,
        "simulated_download": simulated,
        "simulated_download_is_local": Path(simulated).is_relative_to(local_root),
        "mutation_blocked": mutation_blocked,
        "symlink": Path(resolved).is_symlink(),
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if all(
        (
            report["resolved_read_only"],
            report["simulated_download_is_local"],
            report["mutation_blocked"],
            not report["symlink"],
        )
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
