#!/usr/bin/env python3
"""Create a contact sheet and simple reproducible fidelity/motion metrics."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _probe(video: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _decode(video: Path) -> np.ndarray:
    width, height = _probe(video)
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    frame_size = width * height * 3
    frame_count = len(result.stdout) // frame_size
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(
        frame_count, height, width, 3
    )


def _psnr(reference: np.ndarray, frame: np.ndarray) -> float:
    mse = float(np.mean((reference.astype(np.float32) - frame) ** 2))
    return float("inf") if mse == 0 else 20 * math.log10(255.0 / math.sqrt(mse))


def _make_sheet(frames: np.ndarray, output: Path, label: str) -> None:
    indexes = np.linspace(0, len(frames) - 1, 6).round().astype(int)
    thumb_width = 320
    scale = thumb_width / frames.shape[2]
    thumb_height = round(frames.shape[1] * scale)
    sheet = Image.new("RGB", (thumb_width * 3, (thumb_height + 28) * 2), "white")
    draw = ImageDraw.Draw(sheet)
    for position, index in enumerate(indexes):
        image = Image.fromarray(frames[index]).resize(
            (thumb_width, thumb_height), Image.Resampling.LANCZOS
        )
        x = (position % 3) * thumb_width
        y = (position // 3) * (thumb_height + 28)
        sheet.paste(image, (x, y))
        draw.text((x + 8, y + thumb_height + 5), f"{label} · frame {index}", fill="black")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--contact-sheet", required=True, type=Path)
    args = parser.parse_args()

    frames = _decode(args.video.resolve())
    reference = np.asarray(
        Image.open(args.reference)
        .convert("RGB")
        .resize((frames.shape[2], frames.shape[1]), Image.Resampling.LANCZOS)
    )
    # Stream reductions frame-by-frame. Materializing float32 differences for
    # a 117-frame 720p clip would temporarily consume several GiB.
    source_maes = [
        float(
            np.abs(frame.astype(np.int16) - reference.astype(np.int16)).mean()
        )
        for frame in frames
    ]
    consecutive_maes = [
        float(
            np.abs(
                frames[index].astype(np.int16)
                - frames[index - 1].astype(np.int16)
            ).mean()
        )
        for index in range(1, len(frames))
    ]
    report = {
        "video": str(args.video.resolve()),
        "reference": str(args.reference.resolve()),
        "frames": int(len(frames)),
        "resolution": f"{frames.shape[2]}x{frames.shape[1]}",
        "first_frame_psnr_db": round(_psnr(reference, frames[0]), 4),
        "first_frame_mae_0_255": round(source_maes[0], 4),
        "all_frames_source_mae_mean_0_255": round(
            float(np.mean(source_maes)), 4
        ),
        "consecutive_frame_mae_mean_0_255": round(
            float(np.mean(consecutive_maes)), 4
        ),
        "consecutive_frame_mae_p95_0_255": round(
            float(np.percentile(consecutive_maes, 95)), 4
        ),
        "contact_sheet": str(args.contact_sheet.resolve()),
    }
    _make_sheet(frames, args.contact_sheet, args.label)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
