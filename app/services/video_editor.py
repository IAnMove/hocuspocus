"""Small, dependable FFmpeg assembly backend for Maestro's video editor.

The editor deliberately stores only references to uploads/workspace outputs.
Path validation remains the responsibility of the API layer; every path passed
to this module must already be resolved to a permitted local file.
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any


ProgressCallback = Callable[[int, str], None]

INTERSTITIAL_TRANSITIONS = frozenset(
    {"later-clock", "later-tropical", "later-cinematic"}
)


def is_interstitial_transition(transition: str) -> bool:
    """Return whether a transition inserts a full time-card between clips."""
    return transition in INTERSTITIAL_TRANSITIONS


def _run(command: list[str], *, timeout: int, label: str) -> None:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Unknown FFmpeg error").strip()
        raise RuntimeError(f"{label} failed: {detail[-1200:]}")


def probe_media(path: str) -> dict[str, Any]:
    """Return the timing and primary stream information needed by the editor."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,width,height,r_frame_rate,pix_fmt:stream_tags=alpha_mode",
            "-of",
            "json",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError((result.stderr or "ffprobe could not read this media file").strip()[-600:])

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe returned invalid media information") from exc

    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    if not video:
        raise ValueError("The selected file does not contain a video stream")

    duration = float((payload.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError("The selected video has no readable duration")

    rate = str(video.get("r_frame_rate") or "0/1")
    try:
        numerator, denominator = rate.split("/", 1)
        fps = float(numerator) / max(float(denominator), 1)
    except (TypeError, ValueError, ZeroDivisionError):
        fps = 0

    pixel_format = str(video.get("pix_fmt") or "unknown").lower()
    alpha_formats = ("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya8", "ya16")
    video_tags = video.get("tags") if isinstance(video.get("tags"), dict) else {}
    alpha_mode = str(video_tags.get("ALPHA_MODE") or video_tags.get("alpha_mode") or "")

    return {
        "duration": round(duration, 4),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": round(fps, 3),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in streams),
        "pixel_format": pixel_format,
        "has_alpha": alpha_mode == "1" or any(marker in pixel_format for marker in alpha_formats),
    }


def extract_frame(
    source: str,
    destination: str,
    time_seconds: float,
) -> dict[str, Any]:
    """Extract one accurately-seeked native-resolution PNG from a video."""
    media = probe_media(source)
    fps = max(float(media.get("fps") or 0), 1.0)
    duration = float(media["duration"])
    requested = max(0.0, float(time_seconds))
    # Container duration can extend a fraction beyond the final video PTS.
    # Seeking to duration-1/fps may then return success but write no frame.
    end_margin_frames = 2 if requested >= duration - (1.0 / fps) else 1
    timestamp = max(0.0, min(requested, duration - (end_margin_frames / fps)))

    def capture(at: float) -> None:
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                source,
                "-ss",
                f"{at:.6f}",
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                destination,
            ],
            timeout=120,
            label=f"Capturing {os.path.basename(source)} at {at:.3f}s",
        )

    capture(timestamp)
    if not os.path.isfile(destination) or os.path.getsize(destination) <= 0:
        timestamp = max(0.0, duration - (3.0 / fps))
        capture(timestamp)
    if not os.path.isfile(destination) or os.path.getsize(destination) <= 0:
        raise RuntimeError(
            f"FFmpeg did not produce a frame from {os.path.basename(source)} "
            f"near {time_seconds:.3f}s."
        )
    return {
        "time": round(timestamp, 6),
        "width": int(media["width"]),
        "height": int(media["height"]),
    }


def _video_filter(width: int, height: int, fps: int, fit: str) -> str:
    if fit == "fill":
        sizing = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    else:
        sizing = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    return f"{sizing},fps={fps},setsar=1,format=yuv420p"


def _normalise_clip(
    source: str,
    destination: str,
    clip: dict[str, Any],
    width: int,
    height: int,
    fps: int,
) -> float:
    media = probe_media(source)
    source_duration = float(media["duration"])
    trim_start = max(0.0, min(float(clip.get("trim_start") or 0), source_duration - 0.05))
    requested_end = float(clip.get("trim_end") or source_duration)
    trim_end = max(trim_start + 0.05, min(requested_end, source_duration))
    duration = trim_end - trim_start
    volume = 0.0 if clip.get("muted") else max(0.0, min(float(clip.get("volume", 1)), 2.0))
    fit = "fill" if clip.get("fit") == "fill" else "fit"

    command = ["ffmpeg", "-y", "-ss", f"{trim_start:.6f}", "-i", source]
    if not media["has_audio"]:
        command.extend(
            ["-f", "lavfi", "-t", f"{duration:.6f}", "-i", "anullsrc=r=48000:cl=stereo"]
        )

    command.extend(["-t", f"{duration:.6f}", "-map", "0:v:0"])
    command.extend(["-map", "0:a:0" if media["has_audio"] else "1:a:0"])
    command.extend(
        [
            "-vf",
            _video_filter(width, height, fps, fit),
            "-af",
            f"aresample=48000:async=1:first_pts=0,volume={volume:.4f},apad",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            destination,
        ]
    )
    _run(command, timeout=max(300, int(duration * 20)), label=f"Preparing {os.path.basename(source)}")
    return duration


def _concat_without_transition(segments: list[str], output_path: str) -> None:
    if len(segments) == 1:
        shutil.copy2(segments[0], output_path)
        return

    list_path = os.path.join(os.path.dirname(segments[0]), "concat.txt")
    with open(list_path, "w", encoding="utf-8") as handle:
        for segment in segments:
            escaped = os.path.abspath(segment).replace("\\", "/").replace("'", "'\\''")
            handle.write(f"file '{escaped}'\n")
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            list_path,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            output_path,
        ],
        timeout=1200,
        label="Joining clips",
    )


def _concat_with_transitions(
    segments: list[str],
    durations: list[float],
    output_path: str,
    transitions: list[dict[str, Any]],
) -> None:
    command = ["ffmpeg", "-y"]
    for segment in segments:
        command.extend(["-i", segment])

    filters: list[str] = []
    video_label = "0:v"
    audio_label = "0:a"
    running_duration = durations[0]
    for index in range(1, len(segments)):
        out_video = f"v{index}"
        out_audio = f"a{index}"
        transition = transitions[index - 1]
        transition_type = str(transition.get("type") or "none")
        fade_duration = float(transition.get("duration") or 0)
        if transition_type == "none" or fade_duration <= 0:
            filters.append(
                f"[{video_label}][{index}:v]concat=n=2:v=1:a=0[{out_video}]"
            )
            filters.append(
                f"[{audio_label}][{index}:a]concat=n=2:v=0:a=1[{out_audio}]"
            )
            running_duration += durations[index]
        else:
            transition_name = {
                "crossfade": "fade",
                "fade-black": "fadeblack",
                "wipe-left": "wipeleft",
                "slide-left": "slideleft",
                "slide-right": "slideright",
                "circle-open": "circleopen",
                "dissolve": "dissolve",
                "pixelize": "pixelize",
                "blur": "hblur",
                "zoom-in": "zoomin",
            }.get(transition_type, "fade")
            offset = max(0.0, running_duration - fade_duration)
            filters.append(
                f"[{video_label}][{index}:v]xfade=transition={transition_name}:"
                f"duration={fade_duration:.6f}:offset={offset:.6f}[{out_video}]"
            )
            filters.append(
                f"[{audio_label}][{index}:a]acrossfade=d={fade_duration:.6f}:"
                f"c1=tri:c2=tri[{out_audio}]"
            )
            running_duration += durations[index] - fade_duration
        video_label = out_video
        audio_label = out_audio

    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{video_label}]",
            "-map",
            f"[{audio_label}]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            output_path,
        ]
    )
    _run(
        command,
        timeout=max(1200, int(sum(durations) * 30)),
        label="Rendering transitions",
    )


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
    _run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", card_path,
            "-f", "lavfi", "-t", f"{duration:.6f}",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-t", f"{duration:.6f}", "-map", "0:v:0", "-map", "1:a:0",
            "-vf", f"fps={fps},setsar=1,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest", destination,
        ],
        timeout=max(180, int(duration * 30)),
        label="Rendering time-card transition",
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


def render_project(
    clips: list[dict[str, Any]],
    output_path: str,
    *,
    width: int,
    height: int,
    fps: int,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Normalise, trim and assemble clips into a shareable H.264 MP4."""
    if not clips:
        raise ValueError("Add at least one video clip")
    if width < 240 or height < 240 or width > 3840 or height > 3840:
        raise ValueError("Output resolution must be between 240 and 3840 pixels")
    if width % 2 or height % 2:
        raise ValueError("Output width and height must be even numbers")
    if fps not in (24, 25, 30, 50, 60):
        raise ValueError("Unsupported frame rate")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    total_stages = len(clips) + 1
    with tempfile.TemporaryDirectory(prefix=".video_editor_", dir=os.path.dirname(output_path)) as temp_dir:
        segments: list[str] = []
        durations: list[float] = []
        for index, clip in enumerate(clips):
            if progress:
                progress(
                    round((index / total_stages) * 100),
                    f"Preparing clip {index + 1} of {len(clips)}…",
                )
            segment = os.path.join(temp_dir, f"segment_{index:04d}.mp4")
            durations.append(
                _normalise_clip(
                    str(clip["resolved_path"]),
                    segment,
                    clip,
                    width,
                    height,
                    fps,
                )
            )
            segments.append(segment)

        if progress:
            progress(
                round((len(clips) / total_stages) * 100),
                "Joining clips and writing the final MP4…",
            )
        transitions: list[dict[str, Any]] = []
        for index in range(max(0, len(clips) - 1)):
            transition_type = str(clips[index].get("transition") or "none")
            requested_duration = float(clips[index].get("transition_duration") or 0.4)
            actual_duration = max(0.5, min(requested_duration, 5.0)) if is_interstitial_transition(transition_type) else (
                max(
                    0.05,
                    min(requested_duration, durations[index] * 0.45, durations[index + 1] * 0.45),
                )
                if transition_type != "none"
                else 0.0
            )
            transitions.append({
                "type": transition_type,
                "duration": actual_duration,
                "text": normalise_time_card_text(clips[index].get("transition_text")),
                "text_size": max(50.0, min(160.0, float(clips[index].get("transition_text_size") or 100))),
            })

        if any(is_interstitial_transition(item["type"]) for item in transitions):
            if progress:
                progress(88, "Creating time-card transitions…")
            render_segments, render_durations, render_transitions = _materialise_time_cards(
                segments,
                durations,
                transitions,
                temp_dir=temp_dir,
                width=width,
                height=height,
                fps=fps,
            )
        else:
            render_segments, render_durations, render_transitions = segments, durations, transitions

        if not any(item["type"] != "none" for item in render_transitions) or len(render_segments) == 1:
            _concat_without_transition(render_segments, output_path)
        else:
            _concat_with_transitions(
                render_segments,
                render_durations,
                output_path,
                render_transitions,
            )

    if progress:
        progress(100, "Video export complete")
    return {
        "duration": round(
            sum(durations)
            + sum(
                float(item["duration"])
                if is_interstitial_transition(item["type"])
                else -float(item["duration"])
                for item in transitions
            ),
            3,
        ),
        "clip_count": len(clips),
        "transitions": transitions,
    }


def _comic_preview_video_filter(
    *,
    duration: float,
    width: int,
    height: int,
    fps: int,
    motion: str,
) -> str:
    """Build a restrained FFmpeg filter that never crops comic artwork."""
    frames = max(2, round(duration * fps))
    progress = f"on/{max(frames - 1, 1)}"
    if motion == "pull-out":
        zoom = f"1.04-0.04*{progress}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan-left":
        zoom = "1.04"
        x = f"(iw-iw/zoom)*(1-{progress})"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "pan-right":
        zoom = "1.04"
        x = f"(iw-iw/zoom)*{progress}"
        y = "ih/2-(ih/zoom/2)"
    elif motion == "none":
        zoom = "1"
        x = "0"
        y = "0"
    else:
        zoom = f"1+0.04*{progress}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
        "setsar=1,format=yuv420p"
    )


def _render_still_segment(
    source: str,
    destination: str,
    *,
    duration: float,
    width: int,
    height: int,
    fps: int,
    motion: str,
) -> None:
    """Turn one lettered comic panel into a silent storyboard-preview shot."""
    video_filter = _comic_preview_video_filter(
        duration=duration,
        width=width,
        height=height,
        fps=fps,
        motion=motion,
    )
    _run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", source,
            "-f", "lavfi", "-t", f"{duration:.6f}",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-t", f"{duration:.6f}", "-map", "0:v:0", "-map", "1:a:0",
            "-vf", video_filter,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", "-shortest", destination,
        ],
        timeout=max(180, int(duration * 30)),
        label=f"Animating {os.path.basename(source)}",
    )


def render_comic_animatic(
    panels: list[dict[str, Any]],
    output_path: str,
    *,
    width: int,
    height: int,
    fps: int = 30,
    transition: str = "none",
    transition_duration: float = 0.35,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Render ordered, already-lettered comic panels as a cinematic animatic."""
    if not panels:
        raise ValueError("The comic has no panels to animate")
    if width < 240 or height < 240 or width > 3840 or height > 3840 or width % 2 or height % 2:
        raise ValueError("Invalid animatic resolution")
    if fps not in (24, 25, 30, 50, 60):
        raise ValueError("Unsupported animatic frame rate")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".comic_animatic_", dir=os.path.dirname(output_path)) as temp_dir:
        segments: list[str] = []
        durations: list[float] = []
        for index, panel in enumerate(panels):
            if progress:
                progress(round(index / (len(panels) + 1) * 100), f"Animating panel {index + 1} of {len(panels)}…")
            duration = max(0.8, min(float(panel.get("duration") or 3.0), 20.0))
            destination = os.path.join(temp_dir, f"panel_{index:04d}.mp4")
            _render_still_segment(
                str(panel["resolved_path"]), destination, duration=duration,
                width=width, height=height, fps=fps,
                motion=str(panel.get("motion") or "none"),
            )
            segments.append(destination)
            durations.append(duration)
        transitions = []
        for index in range(max(0, len(segments) - 1)):
            duration = max(0.05, min(transition_duration, durations[index] * .45, durations[index + 1] * .45)) if transition != "none" else 0
            transitions.append({"type": transition, "duration": duration})
        if len(segments) == 1 or transition == "none":
            _concat_without_transition(segments, output_path)
        else:
            _concat_with_transitions(segments, durations, output_path, transitions)
    if progress:
        progress(100, "Comic animatic complete")
    return {
        "duration": round(sum(durations) - sum(item["duration"] for item in transitions), 3),
        "clip_count": len(segments),
        "transitions": transitions,
    }
