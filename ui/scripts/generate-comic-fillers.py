"""Draw the licence-free filler pictures for the comic-page templates.

Page size, cell rectangles and the paper itself come from `comic-layout`
(`ui/src/features/scene3d/comicLayout.ts`). The panel pictures and cutouts
are original drawings in this file. No third-party image is copied. Run
from the repo root:

    python3 ui/scripts/generate-comic-fillers.py
"""
from __future__ import annotations

import base64
import json
import struct
import subprocess
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "scene3d" / "comic"
TOOL = ROOT / "scripts" / "world3d-template-tool.mjs"
LOADER = ROOT / "node_modules" / "tsx" / "dist" / "loader.mjs"
INK = (28, 20, 15, 255)
PANELS = (
    (196, 90, 74, 255),
    (61, 122, 154, 255),
    (212, 162, 74, 255),
    (74, 122, 82, 255),
    (122, 86, 158, 255),
    (70, 110, 96, 255),
)


def write_png(path: Path, width: int, height: int, pixel) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixel(x, y))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def layout(fmt: str) -> dict:
    proc = subprocess.run(
        ["node", "--import", str(LOADER), str(TOOL), "comic-layout"],
        input=json.dumps({"format": fmt, "count": 4, "seed": 0, "fromPanel": 0, "toPanel": 3}),
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    if proc.returncode:
        raise SystemExit(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def panel_pixel(color, width: int, height: int):
    def pixel(x: int, y: int):
        if abs(x - y * width / height) < 3 or abs((width - 1 - x) - y * width / height) < 3:
            return INK
        return color
    return pixel


def cutout_pixel(width: int, height: int):
    cx, cy = (width - 1) / 2, (height - 1) / 2
    rx, ry = width * 0.22, height * 0.28

    def pixel(x: int, y: int):
        nx = (x - cx) / rx
        ny = (y - cy) / ry
        if nx * nx + ny * ny <= 1:
            return (196, 90, 74, 255)
        return (0, 0, 0, 0)
    return pixel


def main() -> None:
    for fmt in ("landscape", "portrait"):
        page = layout(fmt)
        (OUT / f"page-{fmt}.png").write_bytes(base64.b64decode(page["png"]))
        for index, cell in enumerate(page["cells"]):
            color = PANELS[index % len(PANELS)]
            write_png(OUT / f"panel-{fmt}-{index}.png", cell["w"], cell["h"], panel_pixel(color, cell["w"], cell["h"]))
            write_png(OUT / f"cutout-{fmt}-{index}.png", cell["w"], cell["h"], cutout_pixel(cell["w"], cell["h"]))
        print(f"{fmt}: page {page['pageW']}x{page['pageH']} cells {len(page['cells'])}")


if __name__ == "__main__":
    main()
