"""Dress the staged comic panels as printed paper, and bring the entering panel to life.

The clean pictures and stickers stay for the two cut panels: the scene fades them into their printed twins.
The other panels are printed outright. When the entering panel comes from a video, it also gets a short clip
that ends on the cut frame, so the panel is already moving before the camera arrives.
"""
from __future__ import annotations

import io
import subprocess
from pathlib import Path

from services import scene3d_comic_paper as paper

FPS = 30
# The layout's dark rim around the paper, in page pixels (comicLayout.ts BACKDROP).
PAGE_RIM = 32
# The entering panel's print dissolves from `hold + LIVE_FADE[0]` to `hold + LIVE_FADE[1]` seconds.
LIVE_FADE = (0.1, 0.7)


def dress(ctx: dict) -> dict:
    """`ctx`: panels, sources, cells, page_png, fmt, from_panel, to_panel, enter_duration, hold, seed, root, url, live.

    Returns the panels with print/printCutout/shadow/live, the page URL and the desk URL."""
    from PIL import Image

    root: Path = ctx["root"]
    page_w, page_h = Image.open(io.BytesIO(ctx["page_png"])).size
    heroes = {ctx["from_panel"], ctx["to_panel"]}
    live = _live_clip(ctx) if ctx.get("live", True) else None
    panels = []
    for index, (panel, cell) in enumerate(zip(ctx["panels"], ctx["cells"])):
        box = (cell["x"], cell["y"], cell["w"], cell["h"], page_w, page_h)
        dressed = _dress_panel(dict(panel), index, box, index in heroes, ctx, root)
        if index == ctx["to_panel"] and live:
            dressed = _go_live(dressed, live, index, box, ctx, root)
        panels.append(dressed)
    page = paper.newsprint_page(page_w, page_h, ctx["cells"], PAGE_RIM, ctx["seed"])
    page_url = _save(Image.fromarray(page), root, f"comic-page-{ctx['fmt']}.png", ctx["url"])
    desk = paper.desk_backdrop(page_w, page_h, ctx["seed"], 0.6)
    desk_url = _save(Image.fromarray(desk), root, f"comic-desk-{ctx['fmt']}.png", ctx["url"])
    return {"panels": panels, "pageUrl": page_url, "deskUrl": desk_url}


def _dress_panel(panel: dict, index: int, box, hero: bool, ctx: dict, root: Path) -> dict:
    seed = ctx["seed"] * 31 + index
    picture = root / f"comic-panel-{index}.png"
    printed = root / f"comic-print-{index}.png"
    paper.print_picture(picture, printed, seed, box)
    if hero:
        panel["print"] = ctx["url"](printed.name)
    else:
        panel["url"] = ctx["url"](printed.name)
    if not panel.get("cutout"):
        return panel
    sticker = root / f"comic-cutout-{index}.png"
    printed_sticker = root / f"comic-print-cutout-{index}.png"
    shadow = root / f"comic-shadow-{index}.png"
    paper.print_sticker(sticker, printed_sticker, seed + 101, box)
    paper.sticker_shadow(sticker, shadow)
    panel["shadow"] = ctx["url"](shadow.name)
    if hero:
        panel["printCutout"] = ctx["url"](printed_sticker.name)
    else:
        panel["cutout"] = ctx["url"](printed_sticker.name)
    return panel


def _live_clip(ctx: dict):
    """The entering panel's own frames up to the cut: (path, lines), or None for a still picture."""
    source = ctx["sources"][ctx["to_panel"]]
    if "video" not in source:
        return None
    frames = max(2, round(ctx["enter_duration"] * FPS))
    first = max(0.0, float(source["at"]) - (frames - 1) / FPS)
    dest = ctx["root"] / f"comic-live-{ctx['to_panel']}.mp4"
    # Untagged BT.601 like the extracted stills, so the browser decodes the same colours (36.8 dB measured).
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{first:.4f}", "-i", str(source["path"]), "-t", f"{(frames + 2) / FPS:.4f}",
         "-an", "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", str(dest)],
        check=True, capture_output=True,
    )
    return dest, first


def _go_live(panel: dict, live, index: int, box, ctx: dict, root: Path) -> dict:
    """Drop the sticker (a still cutout cannot follow a moving picture) and print the frame the dissolve shows."""
    from services.video_editor import extract_frame

    clip, first = live
    start, end = (ctx["hold"] + LIVE_FADE[0], ctx["hold"] + LIVE_FADE[1])
    still = root / f"comic-live-{index}.png"
    extract_frame(str(ctx["sources"][index]["path"]), str(still), first + (start + end) / 2)
    printed = root / f"comic-print-{index}.png"
    paper.print_picture(still, printed, ctx["seed"] * 31 + index, box)
    lines = _height(still)
    for key in ("cutout", "printCutout", "shadow"):
        panel.pop(key, None)
    panel["print"] = ctx["url"](printed.name)
    panel["live"] = {"url": ctx["url"](clip.name), "lines": lines, "fadeStart": start, "fadeEnd": end}
    return panel


def _height(path: Path) -> int:
    from PIL import Image
    with Image.open(path) as opened:
        return opened.size[1]


def _save(image, root: Path, name: str, url) -> str:
    image.save(root / name)
    return url(name)
