"""Draw the licence-free filler pictures for the comic-page templates.

The pixel grid matches `comicPagePixels` in ui/src/features/scene3d/comicPage.ts
(landscape panels 640×360, portrait 360×640, gutter 16, margin 28).
Original art: no third-party image is copied. Run from the repo root:

    python3 ui/scripts/generate-comic-fillers.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "public" / "scene3d" / "comic"
PAPER = (244, 239, 228, 255)
INK = (28, 20, 15, 255)
BORDER = 8
PANELS = (
    (196, 90, 74, 255),
    (61, 122, 154, 255),
    (212, 162, 74, 255),
    (74, 122, 82, 255),
)
GRIDS = {
    "landscape": (640, 360, 16, 28),
    "portrait": (360, 640, 16, 28),
}


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


def page_size(panel_w: int, panel_h: int, gutter: int, margin: int) -> tuple[int, int]:
    return margin * 2 + panel_w * 2 + gutter, margin * 2 + panel_h * 2 + gutter


def panel_rects(panel_w: int, panel_h: int, gutter: int, margin: int):
    rects = []
    for row in range(2):
        for col in range(2):
            x0 = margin + col * (panel_w + gutter)
            y0 = margin + row * (panel_h + gutter)
            rects.append((x0, y0, x0 + panel_w, y0 + panel_h))
    return rects


def page_pixel(rects):
    def pixel(x: int, y: int):
        for x0, y0, x1, y1 in rects:
            outer = x0 - BORDER <= x < x1 + BORDER and y0 - BORDER <= y < y1 + BORDER
            inner = x0 <= x < x1 and y0 <= y < y1
            if outer and not inner:
                return INK
        return PAPER
    return pixel


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
    for name, (panel_w, panel_h, gutter, margin) in GRIDS.items():
        page_w, page_h = page_size(panel_w, panel_h, gutter, margin)
        rects = panel_rects(panel_w, panel_h, gutter, margin)
        write_png(ROOT / f"page-{name}.png", page_w, page_h, page_pixel(rects))
        for index, color in enumerate(PANELS):
            write_png(ROOT / f"panel-{name}-{index}.png", panel_w, panel_h, panel_pixel(color, panel_w, panel_h))
        write_png(ROOT / f"cutout-{name}.png", panel_w, panel_h, cutout_pixel(panel_w, panel_h))
        print(f"{name}: page {page_w}x{page_h}, panels {panel_w}x{panel_h}")


if __name__ == "__main__":
    main()
