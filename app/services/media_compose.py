"""``media.compose``: a still image from layers, on the CPU.

A base image (or a frame of a base video, or a blank canvas of ``size``) with
up to 16 image layers placed by their centre in % of the canvas, sized as a
fraction of the canvas height (``scale``) or width (``width``), with opacity,
clockwise rotation, a mirror flip and ``anchor: "bottom"`` to stand a cutout's
lowest opaque row on ``y``. It replaces pasting cutouts over frames with PIL
outside HocusPocus, e.g. a start frame for an image-to-video shot.
"""
from __future__ import annotations

import os
import re
from typing import Any

from PIL import Image, ImageOps

from services.production_media_common import (
    OUTPUT_NAME, SOURCE, WORKSPACE, MediaToolError, media_url, number, operation_schema, output_path,
    publish_sidecar, read_input, remove_quietly, resolve_source, sha256_file, source_ref, uploads_root,
    workspace_folder,
)

OPERATION = "media.compose"
MAX_LAYERS = 16
MAX_EDGE = 4096
_KEYS = frozenset({"workspace", "base", "base_at", "size", "background", "layers", "output_name", "format"})
_LAYER_KEYS = frozenset({"file", "x", "y", "scale", "width", "opacity", "rotation", "flip", "anchor"})
_COLOR = re.compile(r"#([0-9a-fA-F]{6})([0-9a-fA-F]{2})?")
_OPAQUE = 8


def catalog() -> dict[str, Any]:
    layer = {"type": "object", "additionalProperties": False, "required": ["file"], "properties": {
        "file": SOURCE,
        "x": {"type": "number", "minimum": -100, "maximum": 200, "description": "Centre, % of the canvas width (50)."},
        "y": {"type": "number", "minimum": -100, "maximum": 200, "description": (
            "Centre, % of the canvas height (50); with anchor bottom, where the lowest opaque row stands.")},
        "scale": {"type": "number", "minimum": 0.01, "maximum": 4, "description": "Layer height as a fraction of the canvas height."},
        "width": {"type": "number", "minimum": 0.01, "maximum": 4, "description": "Layer width as a fraction of the canvas width (instead of scale)."},
        "opacity": {"type": "number", "minimum": 0, "maximum": 1},
        "rotation": {"type": "number", "minimum": -360, "maximum": 360, "description": "Degrees, clockwise."},
        "flip": {"type": "boolean", "description": "Mirror horizontally."},
        "anchor": {"type": "string", "enum": ["center", "bottom"]},
    }}
    return operation_schema(OPERATION, (
        "Compose a still image from layers on the CPU (instead of pasting cutouts with PIL outside HocusPocus): the "
        "canvas is base (a workspace image, or a video with base_at seconds | first | last) or size [w, h] with "
        "background #rrggbb, #rrggbbaa or transparent (default). Up to 16 layers of workspace images (keyed PNG "
        "cutouts from studio.key), drawn in order: x / y are the layer's centre in % of the canvas (50, 50); scale "
        "is its height as a fraction of the canvas height (or width, a fraction of the canvas width; default its own "
        "pixels); opacity 0-1; rotation degrees clockwise; flip mirrors it; anchor bottom stands its lowest opaque "
        "row on y (a figure on the floor). format png (default) or jpg. Writes a provenance sidecar naming every "
        "source. Returns file, url, width, height, sha256, layers. Use it for an image-to-video start frame (the last "
        "frame of a clip with a character pasted in). To render a whole Video 2D scene at one time use "
        "scenes.video2d.preview with one time."
    ), {
        "workspace": WORKSPACE, "base": SOURCE,
        "base_at": {"anyOf": [{"type": "number", "minimum": 0}, {"type": "string", "enum": ["first", "last"]}]},
        "size": {"type": "array", "items": {"type": "integer", "minimum": 16, "maximum": MAX_EDGE}, "minItems": 2, "maxItems": 2},
        "background": {"type": "string", "maxLength": 11, "description": "#rrggbb, #rrggbbaa or transparent."},
        "layers": {"type": "array", "items": layer, "minItems": 1, "maxItems": MAX_LAYERS},
        "output_name": OUTPUT_NAME, "format": {"type": "string", "enum": ["png", "jpg"]},
    }, ["workspace", "layers"])


def _background(value: Any) -> tuple[int, int, int, int]:
    if value in (None, "transparent"):
        return (0, 0, 0, 0)
    match = _COLOR.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise MediaToolError("invalid_command", "background must be #rrggbb, #rrggbbaa or transparent.")
    rgb = bytes.fromhex(match.group(1))
    return (rgb[0], rgb[1], rgb[2], int(match.group(2), 16) if match.group(2) else 255)


def _size(value: Any) -> tuple[int, int]:
    if (not isinstance(value, list) or len(value) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) or not 16 <= item <= MAX_EDGE for item in value)):
        raise MediaToolError("invalid_command", f"size must be [width, height], 16-{MAX_EDGE} px each.")
    return value[0], value[1]


def _open_image(path: str) -> Image.Image:
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise MediaToolError("unsupported_media", f"{os.path.basename(path)} is not a readable image.") from exc
    if max(image.size) > 2 * MAX_EDGE:
        raise MediaToolError("source_too_large", f"{os.path.basename(path)} is larger than {2 * MAX_EDGE} px.")
    return image


def _canvas(payload: dict, ctx: dict) -> tuple[Image.Image, list[str]]:
    """The canvas and the files it came from."""
    if ("base" in payload) == ("size" in payload):
        raise MediaToolError("invalid_command", "Give base (an image or video) or size [w, h], not both.")
    if "size" in payload:
        if "base_at" in payload:
            raise MediaToolError("invalid_command", "base_at needs a video base.")
        return Image.new("RGBA", _size(payload["size"]), _background(payload.get("background"))), []
    base = resolve_source(payload["base"], ctx["workspace"], ctx["folder"], ctx["uploads"], ("image", "video"), "base")
    if os.path.splitext(base)[1].lower() in (".png", ".jpg", ".jpeg", ".webp"):
        if "base_at" in payload:
            raise MediaToolError("invalid_command", "base_at needs a video base.")
        canvas = _open_image(base)
    else:
        from services.media_frame import capture_to_temp, requested_time
        frame = capture_to_temp(base, requested_time(payload.get("base_at")), ctx["folder"])
        try:
            canvas = _open_image(frame)
        finally:
            remove_quietly(frame)
    if max(canvas.size) > MAX_EDGE:
        raise MediaToolError("source_too_large", f"The base is larger than {MAX_EDGE} px.")
    return canvas, [base]


def _layer_spec(raw: Any, index: int) -> dict[str, Any]:
    where = f"layers[{index}]"
    if not isinstance(raw, dict) or "file" not in raw or set(raw) - _LAYER_KEYS:
        raise MediaToolError("invalid_command", f"{where} needs file and only {', '.join(sorted(_LAYER_KEYS))}.")
    if "scale" in raw and "width" in raw:
        raise MediaToolError("invalid_command", f"{where}: give scale or width, not both.")
    if raw.get("anchor", "center") not in ("center", "bottom") or not isinstance(raw.get("flip", False), bool):
        raise MediaToolError("invalid_command", f"{where}: anchor is center or bottom and flip true or false.")
    try:
        return {"file": raw["file"], "x": number(raw, "x", -100, 200, 50), "y": number(raw, "y", -100, 200, 50),
                "scale": number(raw, "scale", 0.01, 4), "width": number(raw, "width", 0.01, 4),
                "opacity": number(raw, "opacity", 0, 1, 1), "rotation": number(raw, "rotation", -360, 360, 0),
                "flip": raw.get("flip", False), "anchor": raw.get("anchor", "center")}
    except MediaToolError as exc:
        raise MediaToolError(exc.code, f"{where}: {exc.message}") from exc


def _sized(image: Image.Image, spec: dict[str, Any], canvas: tuple[int, int]) -> Image.Image:
    factor = 1.0
    if spec["scale"] is not None:
        factor = spec["scale"] * canvas[1] / image.height
    elif spec["width"] is not None:
        factor = spec["width"] * canvas[0] / image.width
    if factor != 1.0:
        size = (max(1, round(image.width * factor)), max(1, round(image.height * factor)))
        if max(size) > 4 * MAX_EDGE:
            raise MediaToolError("invalid_command", "A layer would be larger than 16384 px.")
        image = image.resize(size, Image.Resampling.LANCZOS)
    if spec["flip"]:
        image = ImageOps.mirror(image)
    if spec["rotation"]:
        image = image.rotate(-spec["rotation"], resample=Image.Resampling.BICUBIC, expand=True)
    if spec["opacity"] < 1:
        alpha = image.getchannel("A").point(lambda value: round(value * spec["opacity"]))
        image.putalpha(alpha)
    return image


def _position(image: Image.Image, spec: dict[str, Any], canvas: tuple[int, int]) -> tuple[int, int]:
    left = round(spec["x"] / 100 * canvas[0] - image.width / 2)
    if spec["anchor"] == "bottom":
        box = image.getchannel("A").point(lambda value: 255 if value > _OPAQUE else 0).getbbox()
        bottom = box[3] if box else image.height
        return left, round(spec["y"] / 100 * canvas[1] - bottom)
    return left, round(spec["y"] / 100 * canvas[1] - image.height / 2)


def compose(payload: dict, ctx: dict) -> tuple[Image.Image, list[str]]:
    layers = payload.get("layers")
    if not isinstance(layers, list) or not 1 <= len(layers) <= MAX_LAYERS:
        raise MediaToolError("invalid_command", f"layers must list 1-{MAX_LAYERS} images.")
    specs = [_layer_spec(raw, index) for index, raw in enumerate(layers)]
    canvas, sources = _canvas(payload, ctx)
    for index, spec in enumerate(specs):
        path = resolve_source(spec["file"], ctx["workspace"], ctx["folder"], ctx["uploads"], ("image",), f"layers[{index}].file")
        image = _sized(_open_image(path), spec, canvas.size)
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        overlay.paste(image, _position(image, spec, canvas.size))  # onto a clear overlay: keeps the layer's own alpha
        canvas = Image.alpha_composite(canvas, overlay)
        sources.append(path)
    return canvas, sources


def _save(canvas: Image.Image, destination: str, fmt: str, background: tuple[int, int, int, int]) -> None:
    if fmt == "png":
        canvas.save(destination, format="PNG")
        return
    flat = Image.new("RGBA", canvas.size, background[:3] + (255,))
    Image.alpha_composite(flat, canvas).convert("RGB").save(destination, format="JPEG", quality=94)


def run(arguments: Any, *, workspace_dir, uploads_dir) -> dict[str, Any]:
    payload = read_input(arguments, _KEYS, ("workspace", "layers"))
    workspace = payload["workspace"]
    ctx = {"workspace": workspace, "folder": workspace_folder(workspace_dir, workspace), "uploads": uploads_root(uploads_dir)}
    fmt = payload.get("format", "png")
    if fmt not in ("png", "jpg"):
        raise MediaToolError("invalid_command", "format must be png or jpg.")
    canvas, sources = compose(payload, ctx)
    destination = output_path(ctx["folder"], payload.get("output_name"), "compose", f".{fmt}")
    try:
        _save(canvas, destination, fmt, _background(payload.get("background")))
    except OSError as exc:
        remove_quietly(destination)
        raise MediaToolError("compose_failed", "The composed image could not be saved.") from exc
    refs = [source_ref(path, workspace, "base" if index == 0 and "base" in payload else "layer")
            for index, path in enumerate(sources)]
    params = {key: payload[key] for key in ("base_at", "size", "background", "layers") if key in payload}
    sidecar = publish_sidecar(destination, workspace, OPERATION, "image", params, refs)
    return {"file": os.path.basename(destination), "url": media_url(destination, workspace, ctx["uploads"], ctx["folder"]),
            "width": canvas.width, "height": canvas.height, "sha256": sha256_file(destination),
            "layers": len(payload["layers"]), "sidecar": sidecar}
