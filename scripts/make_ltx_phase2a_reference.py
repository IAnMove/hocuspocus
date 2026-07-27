#!/usr/bin/env python3
"""Create the deterministic, text-free Phase 2A I2V reference image."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    image = Image.new("RGB", (768, 768), "#d9f0e5")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 500, 768, 768), fill="#efc879")
    draw.ellipse((570, 55, 690, 175), fill="#ffd45c")
    draw.polygon([(0, 430), (210, 230), (370, 430)], fill="#78b6a1")
    draw.polygon([(260, 430), (530, 170), (768, 430)], fill="#4e8e86")
    draw.ellipse((205, 620, 565, 705), fill="#397a78")

    # Asymmetric coral robot: the eye colors and antenna provide identity cues.
    draw.rounded_rectangle((290, 315, 478, 535), radius=34, fill="#e66b5b")
    draw.rounded_rectangle((310, 245, 458, 380), radius=42, fill="#f07b68")
    draw.line((384, 245, 405, 188), fill="#374d59", width=12)
    draw.ellipse((392, 170, 424, 202), fill="#ffd45c")
    draw.ellipse((338, 292, 372, 326), fill="#263c4a")
    draw.ellipse((398, 292, 432, 326), fill="#f7d35c")
    draw.arc((347, 320, 423, 362), 10, 170, fill="#263c4a", width=7)
    draw.rounded_rectangle((245, 360, 300, 488), radius=22, fill="#d9584c")
    draw.rounded_rectangle((470, 350, 532, 480), radius=22, fill="#d9584c")
    draw.rounded_rectangle((316, 520, 372, 625), radius=20, fill="#d9584c")
    draw.rounded_rectangle((400, 520, 456, 625), radius=20, fill="#d9584c")

    # A few clean leaves make temporal wobble and edge artifacts easy to spot.
    draw.line((125, 555, 125, 360), fill="#355a69", width=12)
    for box in [(70, 375, 125, 430), (125, 405, 185, 465), (70, 455, 125, 515)]:
        draw.ellipse(box, fill="#438fb0")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output, format="PNG", optimize=False)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
