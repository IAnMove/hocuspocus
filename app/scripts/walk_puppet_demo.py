"""Try the puppet walk (services/walk_puppet.py) on one drawing and look at the result.

python scripts/walk_puppet_demo.py <drawing.png> <out_dir> [--direction side|front|front34|back34|back] [--layers <folder of See-through layers>] [--frames 12]

Writes puppet_00.png … (RGBA, twice the drawing's size), a contact sheet (sheet.png) and info.json. The drawing is a keyed picture of the
character in a pose with the limbs apart (a contact pose of a walk sheet from the side, a standing pose from the front). The layers come from
``services.see_through.worker.run_pipeline`` / ``publish_layers`` on the same picture; without them the drawing is cut by the bones alone,
which works for limbs apart and no skirt."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
from PIL import Image

from services import walk_puppet


def contact_sheet(frames: list[np.ndarray], columns: int = 6, scale: float = 0.25) -> Image.Image:
    boxes = [Image.fromarray(frame).getbbox() for frame in frames]
    left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
    right, bottom = max(b[2] for b in boxes), max(b[3] for b in boxes)
    width, height = int((right - left) * scale), int((bottom - top) * scale)
    sheet = Image.new("RGB", (width * columns, height * ((len(frames) + columns - 1) // columns)), (255, 255, 255))
    for index, frame in enumerate(frames):
        cell = Image.fromarray(frame).crop((left, top, right, bottom)).resize((width, height), Image.LANCZOS)
        page = Image.new("RGBA", cell.size, (255, 255, 255, 255))
        page.alpha_composite(cell)
        sheet.paste(page.convert("RGB"), ((index % columns) * width, (index // columns) * height))
    return sheet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("drawing")
    parser.add_argument("out")
    parser.add_argument("--direction", default="side", choices=("side", "front", "front34", "back34", "back"))
    parser.add_argument("--layers")
    parser.add_argument("--frames", type=int, default=12)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    rgba = np.array(Image.open(args.drawing).convert("RGBA"))
    layers = walk_puppet.load_layers(args.layers) if args.layers else None
    frames, info = walk_puppet.build(rgba, args.direction, args.frames, layers)
    for index, frame in enumerate(frames):
        Image.fromarray(frame).save(os.path.join(args.out, f"puppet_{index:02d}.png"))
    contact_sheet(frames).save(os.path.join(args.out, "sheet.png"))
    with open(os.path.join(args.out, "info.json"), "w") as handle:
        json.dump(info, handle, default=float)
    print(f"{len(frames)} frames, the drawing shows phase {info['start']:.3f} of the cycle, limbs paired {info['pairs']}")


if __name__ == "__main__":
    main()
