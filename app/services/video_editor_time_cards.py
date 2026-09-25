"""Video-editor interstitial time cards (clock / tropical / cinematic).

Frame counts and FFmpeg execution stay in video_editor_frames. video_editor
re-exports these helpers so existing tests keep importing from one module.
"""
from __future__ import annotations

import math
import os
import random
from typing import Any

from services.video_editor_frames import _run, _seconds_for_ffmpeg

INTERSTITIAL_TRANSITIONS = frozenset(
    {"later-clock", "later-tropical", "later-cinematic"}
)

def is_interstitial_transition(transition: str) -> bool:
    """Return whether a transition inserts a full time-card between clips."""
    return transition in INTERSTITIAL_TRANSITIONS


def _load_time_card_font(size: int, *, bold: bool = True):
    """Load a broadly available font without making the editor platform-specific."""
    from PIL import ImageFont

    font_names = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    )
    font_paths = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    )
    for candidate in (*font_names, *font_paths):
        try:
            return ImageFont.truetype(candidate, max(10, size))
        except OSError:
            continue
    return ImageFont.load_default()


def normalise_time_card_text(value: Any) -> str:
    """Keep intentional line breaks while making card text safe and predictable."""
    raw = str(value or "Momentos después…").replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in raw.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)[:240].rstrip() or "Momentos después…"


def _time_card_text_width(draw, text: str, font) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def _split_time_card_word(draw, word: str, font, max_width: int) -> list[str]:
    """Split an unusually long token so it cannot be clipped at the card edge."""
    pieces: list[str] = []
    current = ""
    for character in word:
        candidate = current + character
        if current and _time_card_text_width(draw, candidate, font) > max_width:
            pieces.append(current)
            current = character
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [word]


def _wrap_time_card_text(draw, text: str, font, max_width: int) -> list[str]:
    """Wrap to the available width without discarding user-authored newlines."""
    lines: list[str] = []
    for authored_line in normalise_time_card_text(text).split("\n"):
        words = authored_line.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            pieces = (
                [word]
                if _time_card_text_width(draw, word, font) <= max_width
                else _split_time_card_word(draw, word, font, max_width)
            )
            for piece in pieces:
                candidate = f"{current} {piece}" if current else piece
                if current and _time_card_text_width(draw, candidate, font) > max_width:
                    lines.append(current)
                    current = piece
                elif not current and _time_card_text_width(draw, piece, font) > max_width:
                    lines.append(piece)
                    current = ""
                else:
                    current = candidate
        if current:
            lines.append(current)
    return lines or ["Momentos después…"]


def _fit_time_card_text(
    draw,
    text: str,
    *,
    max_width: int,
    max_height: int,
    max_size: int,
    min_size: int,
    stroke_width: int = 0,
):
    for size in range(max_size, min_size - 1, -2):
        spacing = max(2, round(size * 0.16))
        font = _load_time_card_font(size)
        lines = _wrap_time_card_text(draw, text, font, max_width)
        rendered = "\n".join(lines)
        box = draw.multiline_textbbox(
            (0, 0), rendered, font=font, spacing=spacing, align="center", stroke_width=stroke_width,
        )
        if box[2] - box[0] <= max_width and box[3] - box[1] <= max_height:
            return font, rendered, spacing
    font = _load_time_card_font(min_size)
    spacing = max(2, round(min_size * 0.16))
    return font, "\n".join(_wrap_time_card_text(draw, text, font, max_width)), spacing


def _draw_time_card(
    destination: str,
    *,
    style: str,
    text: str,
    text_size: float = 100,
    width: int,
    height: int,
) -> None:
    """Draw an original, reusable time-card without external copyrighted assets."""
    from PIL import Image, ImageDraw

    safe_text = normalise_time_card_text(text)
    text_scale = max(50.0, min(160.0, float(text_size or 100))) / 100
    image = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(image)
    scale = min(width, height)

    if style == "later-clock":
        top = (18, 32, 55)
        bottom = (4, 10, 22)
        for y in range(height):
            ratio = y / max(height - 1, 1)
            colour = tuple(round(top[channel] * (1 - ratio) + bottom[channel] * ratio) for channel in range(3))
            draw.line((0, y, width, y), fill=colour)
        for radius, alpha_colour in (
            (round(scale * .62), (31, 71, 105)),
            (round(scale * .46), (21, 52, 80)),
        ):
            draw.ellipse(
                (width * .13 - radius, height * .3 - radius, width * .13 + radius, height * .3 + radius),
                outline=alpha_colour,
                width=max(2, round(scale * .006)),
            )

        landscape = width >= height
        clock_radius = round(scale * (.26 if landscape else .22))
        clock_x = round(width * (.28 if landscape else .5))
        clock_y = round(height * (.5 if landscape else .29))
        shadow = round(scale * .018)
        draw.ellipse(
            (clock_x - clock_radius + shadow, clock_y - clock_radius + shadow,
             clock_x + clock_radius + shadow, clock_y + clock_radius + shadow),
            fill="#020617",
        )
        draw.ellipse(
            (clock_x - clock_radius, clock_y - clock_radius,
             clock_x + clock_radius, clock_y + clock_radius),
            fill="#f8fafc",
            outline="#fbbf24",
            width=max(5, round(scale * .014)),
        )
        for tick in range(60):
            angle = math.radians(tick * 6 - 90)
            outer = clock_radius * .88
            inner = clock_radius * (.75 if tick % 5 == 0 else .82)
            stroke = max(2, round(scale * (.007 if tick % 5 == 0 else .003)))
            draw.line(
                (
                    clock_x + math.cos(angle) * inner,
                    clock_y + math.sin(angle) * inner,
                    clock_x + math.cos(angle) * outer,
                    clock_y + math.sin(angle) * outer,
                ),
                fill="#172554",
                width=stroke,
            )
        for angle_degrees, length, colour, stroke in (
            (-52, .48, "#0f172a", .026),
            (28, .68, "#0f172a", .018),
            (132, .73, "#ef4444", .008),
        ):
            angle = math.radians(angle_degrees)
            draw.line(
                (clock_x, clock_y,
                 clock_x + math.cos(angle) * clock_radius * length,
                 clock_y + math.sin(angle) * clock_radius * length),
                fill=colour,
                width=max(2, round(scale * stroke)),
            )
        pin = max(5, round(scale * .018))
        draw.ellipse((clock_x - pin, clock_y - pin, clock_x + pin, clock_y + pin), fill="#fbbf24")

        if landscape:
            text_box = (round(width * .54), round(height * .18), round(width * .92), round(height * .82))
        else:
            text_box = (round(width * .10), round(height * .55), round(width * .90), round(height * .88))
        font, rendered, spacing = _fit_time_card_text(
            draw,
            safe_text,
            max_width=text_box[2] - text_box[0],
            max_height=text_box[3] - text_box[1],
            max_size=max(12, round(scale * .105 * text_scale)),
            min_size=max(10, round(scale * .025)),
        )
        box = draw.multiline_textbbox((0, 0), rendered, font=font, spacing=spacing, align="center")
        x = (text_box[0] + text_box[2] - (box[2] - box[0])) / 2 - box[0]
        y = (text_box[1] + text_box[3] - (box[3] - box[1])) / 2 - box[1]
        draw.multiline_text((x, y), rendered, font=font, fill="#f8fafc", spacing=spacing, align="center")

    elif style == "later-tropical":
        image.paste("#087f8c", (0, 0, width, height))
        rng = random.Random(f"{safe_text}:{width}:{height}")
        palette = ("#f4d35e", "#ee964b", "#f95738", "#74c69d", "#0b4f6c", "#f6f7d7")
        for _index in range(26):
            cx = rng.randint(-round(scale * .1), width + round(scale * .1))
            cy = rng.randint(-round(scale * .1), height + round(scale * .1))
            radius = rng.randint(max(8, round(scale * .025)), max(14, round(scale * .11)))
            colour = rng.choice(palette)
            if rng.random() < .55:
                petals = rng.choice((5, 6, 8))
                for petal in range(petals):
                    angle = math.radians(petal * 360 / petals)
                    px = cx + math.cos(angle) * radius * .62
                    py = cy + math.sin(angle) * radius * .62
                    pr = radius * .42
                    draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=colour, outline="#073b4c")
                draw.ellipse((cx - radius * .28, cy - radius * .28, cx + radius * .28, cy + radius * .28), fill="#f4d35e")
            else:
                points = []
                for point in range(10):
                    angle = math.radians(point * 36 - 90)
                    distance = radius if point % 2 == 0 else radius * .45
                    points.append((cx + math.cos(angle) * distance, cy + math.sin(angle) * distance))
                draw.polygon(points, fill=colour, outline="#073b4c")
        veil = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        veil_draw = ImageDraw.Draw(veil)
        pad_x, pad_y = round(width * .08), round(height * .18)
        veil_draw.rounded_rectangle(
            (pad_x, pad_y, width - pad_x, height - pad_y),
            radius=max(14, round(scale * .035)),
            fill=(4, 59, 68, 178),
            outline=(246, 247, 215, 210),
            width=max(3, round(scale * .008)),
        )
        image = Image.alpha_composite(image.convert("RGBA"), veil).convert("RGB")
        draw = ImageDraw.Draw(image)
        stroke_width = max(2, round(scale * .009))
        font, rendered, spacing = _fit_time_card_text(
            draw,
            safe_text.upper(),
            max_width=round(width * .72),
            max_height=round(height * .48),
            max_size=max(12, round(scale * .13 * text_scale)),
            min_size=max(10, round(scale * .025)),
            stroke_width=stroke_width,
        )
        box = draw.multiline_textbbox(
            (0, 0), rendered, font=font, spacing=spacing, align="center", stroke_width=stroke_width,
        )
        x = (width - (box[2] - box[0])) / 2 - box[0]
        y = (height - (box[3] - box[1])) / 2 - box[1]
        draw.multiline_text(
            (x, y), rendered, font=font, fill="#f6f7d7", spacing=spacing,
            align="center", stroke_width=stroke_width, stroke_fill="#073b4c",
        )

    else:
        image.paste("#170f0a", (0, 0, width, height))
        for y in range(height):
            ratio = abs((y / max(height - 1, 1)) - .5) * 2
            shade = round(31 - ratio * 16)
            draw.line((0, y, width, y), fill=(shade, round(shade * .73), round(shade * .46)))
        margin = round(scale * .07)
        line_colour = "#c9a96e"
        draw.rectangle((margin, margin, width - margin, height - margin), outline=line_colour, width=max(2, round(scale * .005)))
        draw.rectangle((margin * 1.35, margin * 1.35, width - margin * 1.35, height - margin * 1.35), outline="#685238", width=max(1, round(scale * .002)))
        ornament_y = round(height * .28)
        draw.line((width * .18, ornament_y, width * .42, ornament_y), fill=line_colour, width=max(2, round(scale * .004)))
        draw.line((width * .58, ornament_y, width * .82, ornament_y), fill=line_colour, width=max(2, round(scale * .004)))
        diamond = round(scale * .018)
        draw.polygon(((width / 2, ornament_y - diamond), (width / 2 + diamond, ornament_y),
                      (width / 2, ornament_y + diamond), (width / 2 - diamond, ornament_y)), fill=line_colour)
        font, rendered, spacing = _fit_time_card_text(
            draw,
            safe_text.upper(),
            max_width=round(width * .68),
            max_height=round(height * .38),
            max_size=max(12, round(scale * .105 * text_scale)),
            min_size=max(10, round(scale * .025)),
        )
        box = draw.multiline_textbbox((0, 0), rendered, font=font, spacing=spacing, align="center")
        x = (width - (box[2] - box[0])) / 2 - box[0]
        y = (height - (box[3] - box[1])) / 2 - box[1] + height * .04
        draw.multiline_text((x, y), rendered, font=font, fill="#f4e8ce", spacing=spacing, align="center")

    image.save(destination, format="PNG", optimize=True)


def _render_time_card_segment(
    destination: str,
    *,
    style: str,
    text: str,
    text_size: float,
    duration: float,
    width: int,
    height: int,
    fps: int,
) -> None:
    card_path = f"{destination}.png"
    _draw_time_card(
        card_path,
        style=style,
        text=text,
        text_size=text_size,
        width=width,
        height=height,
    )
    frames = max(1, int(round(float(duration) * fps)))
    span = _seconds_for_ffmpeg(frames, fps)
    _run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", card_path,
            "-f", "lavfi", "-t", span,
            "-i", "anullsrc=r=48000:cl=stereo",
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", (
                f"fps={fps},tpad=stop_mode=clone:stop=2,"
                f"trim=end_frame={frames},setpts=N/{fps}/TB,setsar=1,format=yuv420p"
            ),
            "-frames:v", str(frames),
            "-fps_mode", "cfr", "-r", str(fps),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            destination,
        ],
        timeout=max(180, int(frames / fps * 30) + 30),
        label="Rendering time-card transition",
        phase="time_card",
        output={"frames": frames, "fps": fps},
    )


def _materialise_time_cards(
    segments: list[str],
    durations: list[float],
    transitions: list[dict[str, Any]],
    *,
    temp_dir: str,
    width: int,
    height: int,
    fps: int,
) -> tuple[list[str], list[float], list[dict[str, Any]]]:
    """Expand special boundaries into ordinary, concat-safe video segments."""
    if not segments:
        return [], [], []
    expanded_segments = [segments[0]]
    expanded_durations = [durations[0]]
    expanded_transitions: list[dict[str, Any]] = []
    for index, transition in enumerate(transitions):
        if is_interstitial_transition(str(transition.get("type") or "none")):
            card_path = os.path.join(temp_dir, f"time_card_{index:04d}.mp4")
            _render_time_card_segment(
                card_path,
                style=str(transition["type"]),
                text=str(transition.get("text") or "Momentos después…"),
                text_size=float(transition.get("text_size") or 100),
                duration=float(transition["duration"]),
                width=width,
                height=height,
                fps=fps,
            )
            expanded_transitions.append({"type": "none", "duration": 0.0})
            expanded_segments.append(card_path)
            expanded_durations.append(float(transition["duration"]))
            expanded_transitions.append({"type": "none", "duration": 0.0})
            expanded_segments.append(segments[index + 1])
            expanded_durations.append(durations[index + 1])
        else:
            expanded_transitions.append(transition)
            expanded_segments.append(segments[index + 1])
            expanded_durations.append(durations[index + 1])
    return expanded_segments, expanded_durations, expanded_transitions

