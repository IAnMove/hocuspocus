"""Timed layers for the Video Editor: image overlays and extra audio cues.

A montage keeps captions, titles and voice-over as editable timeline entries
instead of burning them into the clips. This module validates those entries,
resolves their media through the caller's workspace boundary and applies them
to an already assembled MP4 in one FFmpeg pass.

Contract
--------
* ``overlays`` are still images (PNG/JPEG/WebP) shown from ``start`` to ``end``
  seconds. ``x``/``y`` are the image centre in percent of the frame and
  ``width`` is its width in percent of the frame width (height keeps aspect).
  ``fade_in``/``fade_out`` fade the image alpha.
* ``audio_cues`` are audio files placed at ``start`` seconds with ``volume``.
  When ``duck`` is above zero the existing mix (clip audio + soundtrack) is
  compressed while a cue is speaking, so narration stays intelligible.
* The video stream length never changes: overlays are clipped to the video and
  cues are trimmed at its end.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from services.media_refs import parse_media_ref
from services.video_editor_frames import _check_abort, _run

MAX_OVERLAYS = 200
MAX_AUDIO_CUES = 64
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"})
Resolver = Callable[[str, str | None], str]


class LayerValidationError(ValueError):
    """A timed layer is malformed; the message is safe to show to users."""


def _number(value: Any, label: str, *, low: float, high: float, default: float | None = None) -> float:
    if value is None and default is not None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise LayerValidationError(f"{label} must be a number") from exc
    if number != number or number < low or number > high:
        raise LayerValidationError(f"{label} must be between {low:g} and {high:g}")
    return number


def _text(value: Any, label: str, limit: int, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise LayerValidationError(f"{label} is missing")
    return text[:limit]


def clean_overlays(raw: Any) -> list[dict[str, Any]]:
    """Validate overlay entries from an export body or a montage document."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_OVERLAYS:
        raise LayerValidationError(f"overlays must be a list of at most {MAX_OVERLAYS} entries")
    cleaned = []
    for index, item in enumerate(raw):
        label = f"Overlay {index + 1}"
        if not isinstance(item, dict):
            raise LayerValidationError(f"{label} is invalid")
        start = _number(item.get("start"), f"{label} start", low=0, high=3600)
        end = _number(item.get("end"), f"{label} end", low=0, high=3600)
        if end <= start:
            raise LayerValidationError(f"{label} must end after it starts")
        cleaned.append({
            "id": _text(item.get("id") or f"overlay-{index + 1}", f"{label} id", 160),
            "name": _text(item.get("name"), f"{label} name", 300),
            "source": _text(item.get("source"), f"{label} source", 2000, required=True),
            "start": start,
            "end": end,
            "x": _number(item.get("x"), f"{label} x", low=0, high=100, default=50),
            "y": _number(item.get("y"), f"{label} y", low=0, high=100, default=50),
            "width": _number(item.get("width"), f"{label} width", low=1, high=100, default=100),
            "opacity": _number(item.get("opacity"), f"{label} opacity", low=0, high=1, default=1),
            "fade_in": _number(item.get("fade_in"), f"{label} fade_in", low=0, high=5, default=0),
            "fade_out": _number(item.get("fade_out"), f"{label} fade_out", low=0, high=5, default=0),
        })
    return cleaned


def clean_audio_cues(raw: Any) -> list[dict[str, Any]]:
    """Validate timed audio cues (voice-over, stingers, effects)."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_AUDIO_CUES:
        raise LayerValidationError(f"audio_cues must be a list of at most {MAX_AUDIO_CUES} entries")
    cleaned = []
    for index, item in enumerate(raw):
        label = f"Audio cue {index + 1}"
        if not isinstance(item, dict):
            raise LayerValidationError(f"{label} is invalid")
        trim_start = _number(item.get("trim_start"), f"{label} trim_start", low=0, high=3600, default=0)
        trim_end = _number(item.get("trim_end"), f"{label} trim_end", low=0, high=3600, default=0)
        if trim_end and trim_end <= trim_start:
            raise LayerValidationError(f"{label} trim_end must be after trim_start")
        cleaned.append({
            "id": _text(item.get("id") or f"cue-{index + 1}", f"{label} id", 160),
            "name": _text(item.get("name"), f"{label} name", 300),
            "source": _text(item.get("source"), f"{label} source", 2000, required=True),
            "start": _number(item.get("start"), f"{label} start", low=0, high=3600),
            "volume": _number(item.get("volume"), f"{label} volume", low=0, high=2, default=1),
            "trim_start": trim_start,
            "trim_end": trim_end,
        })
    return cleaned


def clean_duck(raw: Any) -> float:
    """Ducking strength 0..1 (0 disables sidechain compression)."""
    return _number(raw, "duck", low=0, high=1, default=0)


def resolve_layer_media(
    overlays: list[dict[str, Any]],
    audio_cues: list[dict[str, Any]],
    workspace: str | None,
    *,
    resolve_path: Resolver,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach ``resolved_path`` using the API layer's workspace resolver."""
    resolved_overlays = []
    for item in overlays:
        path = resolve_path(item["source"], workspace)
        if os.path.splitext(path)[1].lower() not in IMAGE_EXTENSIONS:
            raise LayerValidationError(f"Overlay {item['id']} must be a PNG, JPEG or WebP image")
        resolved_overlays.append({**item, "resolved_path": path})
    resolved_cues = []
    for item in audio_cues:
        path = resolve_path(item["source"], workspace)
        if os.path.splitext(path)[1].lower() not in AUDIO_EXTENSIONS:
            raise LayerValidationError(f"Audio cue {item['id']} has an unsupported audio format")
        resolved_cues.append({**item, "resolved_path": path})
    return resolved_overlays, resolved_cues


def clean_export_layers(body: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the optional ``overlays``/``audio_cues``/``duck`` of an export body."""
    overlays = clean_overlays(body.get("overlays"))
    audio_cues = clean_audio_cues(body.get("audio_cues"))
    if not overlays and not audio_cues:
        return None
    return {"overlays": overlays, "audio_cues": audio_cues, "duck": clean_duck(body.get("duck"))}


def resolve_export_layers(
    layers: dict[str, Any] | None,
    workspace: str | None,
    *,
    resolve_path: Resolver,
) -> dict[str, Any] | None:
    """Resolve a cleaned ``layers`` dict for :func:`services.video_editor.render_project`."""
    if not layers:
        return None
    overlays, audio_cues = resolve_layer_media(
        list(layers.get("overlays") or []), list(layers.get("audio_cues") or []),
        workspace, resolve_path=resolve_path,
    )
    return {"overlays": overlays, "audio_cues": audio_cues, "duck": float(layers.get("duck") or 0)}


def workspace_media_resolver(resolve_input_path: Callable[[str, str | None], str | None]) -> Resolver:
    """Build a resolver that honours ``/api/v1/file/...?workspace=`` references."""
    def resolve(source: str, workspace: str | None) -> str:
        path, scoped = parse_media_ref(source, workspace)
        resolved = resolve_input_path(path, scoped)
        if not resolved or not os.path.isfile(resolved):
            raise LayerValidationError(f"Layer media could not be found: {os.path.basename(path) or path}")
        return resolved

    return resolve


def _overlay_chain(index: int, item: dict[str, Any], width: int, duration: float) -> str:
    start = min(float(item["start"]), duration)
    end = min(float(item["end"]), duration)
    span = max(0.0, end - start)
    fade_in = min(float(item["fade_in"]), span / 2)
    fade_out = min(float(item["fade_out"]), span / 2)
    pixels = max(2, int(round(width * float(item["width"]) / 100 / 2)) * 2)
    chain = f"[{index}:v]format=rgba,scale={pixels}:-2"
    if float(item["opacity"]) < 1:
        chain += f",colorchannelmixer=aa={float(item['opacity']):.4f}"
    if fade_in > 0:
        chain += f",fade=t=in:st=0:d={fade_in:.4f}:alpha=1"
    if fade_out > 0:
        chain += f",fade=t=out:st={span - fade_out:.4f}:d={fade_out:.4f}:alpha=1"
    return chain + f",setpts=PTS+{start:.4f}/TB[ov{index}]"


def build_layer_filter(
    overlays: list[dict[str, Any]],
    audio_cues: list[dict[str, Any]],
    *,
    width: int,
    height: int,
    fps: int,
    duration: float,
    duck: float,
) -> tuple[list[str], str, bool, bool]:
    """Return ``(extra_inputs, filter_graph, maps_video, maps_audio)``.

    Input 0 is the assembled MP4 (video + audio). Overlay images follow, then
    audio cues. Pure so the graph can be unit tested without FFmpeg.
    """
    inputs: list[str] = []
    parts: list[str] = []
    video = "[0:v]"
    visible = [item for item in overlays if float(item["start"]) < duration]
    for offset, item in enumerate(visible, start=1):
        span = max(0.05, min(float(item["end"]), duration) - float(item["start"]))
        inputs += ["-loop", "1", "-t", f"{span:.4f}", "-framerate", str(int(fps)), "-i", str(item["resolved_path"])]
        parts.append(_overlay_chain(offset, item, width, duration))
        x = f"{float(item['x']) / 100:.5f}*W-w/2"
        y = f"{float(item['y']) / 100:.5f}*H-h/2"
        parts.append(f"{video}[ov{offset}]overlay=x={x}:y={y}:eof_action=pass[v{offset}]")
        video = f"[v{offset}]"
    audible = [item for item in audio_cues if float(item["start"]) < duration]
    first_cue = len(visible) + 1
    labels = []
    for offset, item in enumerate(audible, start=first_cue):
        delay = int(round(float(item["start"]) * 1000))
        trim = ""
        if float(item["trim_start"]) or float(item["trim_end"]):
            end = f":{float(item['trim_end']):.4f}" if float(item["trim_end"]) else ""
            trim = f"atrim={float(item['trim_start']):.4f}{end},asetpts=PTS-STARTPTS,"
        inputs += ["-i", str(item["resolved_path"])]
        parts.append(
            f"[{offset}:a]{trim}aresample=48000,aformat=channel_layouts=stereo,"
            f"volume={float(item['volume']):.4f},adelay={delay}|{delay}[cue{offset}]"
        )
        labels.append(f"[cue{offset}]")
    maps_audio = bool(labels)
    if labels:
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,"
                     f"apad=whole_dur={duration:.4f}[cues]")
        # Pad the assembled audio: a soundtrack shorter than the video must not shorten the export.
        parts.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={duration:.4f}[base]")
        if duck > 0:
            ratio = 1 + 9 * duck
            parts.append("[cues]asplit=2[cuemix][sidechain]")
            parts.append(f"[base][sidechain]sidechaincompress=threshold=0.03:ratio={ratio:.3f}:attack=15:release=350[ducked]")
            parts.append(
                "[ducked][cuemix]amix=inputs=2:normalize=0:duration=first:dropout_transition=0,"
                f"alimiter=limit=0.97,atrim=0:{duration:.4f}[mixed]"
            )
        else:
            parts.append(
                "[base][cues]amix=inputs=2:normalize=0:duration=first:dropout_transition=0,"
                f"alimiter=limit=0.97,atrim=0:{duration:.4f}[mixed]"
            )
    maps_video = video != "[0:v]"
    if maps_video:
        parts.append(f"{video}format=yuv420p[vout]")
    return inputs, ";".join(parts), maps_video, maps_audio


def apply_layers(
    video_path: str,
    output_path: str,
    *,
    overlays: list[dict[str, Any]],
    audio_cues: list[dict[str, Any]],
    width: int,
    height: int,
    fps: int,
    duration: float,
    duck: float = 0.0,
) -> bool:
    """Burn overlays and mix cues into ``output_path``. False when nothing to do."""
    inputs, graph, maps_video, maps_audio = build_layer_filter(
        overlays, audio_cues, width=width, height=height, fps=fps, duration=duration, duck=duck,
    )
    if not maps_video and not maps_audio:
        return False
    command = ["ffmpeg", "-y", "-i", video_path, *inputs, "-filter_complex", graph]
    command += ["-map", "[vout]"] if maps_video else ["-map", "0:v:0"]
    command += ["-map", "[mixed]"] if maps_audio else ["-map", "0:a:0"]
    if maps_video:
        command += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "0", "-r", str(int(fps)), "-pix_fmt", "yuv420p"]
    else:
        command += ["-c:v", "copy"]
    command += ["-c:a", "aac", "-b:a", "192k", "-t", f"{duration:.6f}", "-movflags", "+faststart", output_path]
    _run(
        command,
        timeout=3600,
        label="Applying editor overlays and audio cues",
        phase="layers",
        output={"path": os.path.basename(output_path), "overlays": len(overlays), "audio_cues": len(audio_cues)},
    )
    return True


def apply_render_layers(
    staging_path: str,
    temp_dir: str,
    layers: dict[str, Any] | None,
    *,
    width: int,
    height: int,
    fps: int,
    duration: float,
    progress: Callable[[int, str], None] | None = None,
    abort_callback: Callable[[], bool] | None = None,
) -> str:
    """Render-project stage: return the layered MP4 path, or the input when unused."""
    if not layers or not (layers.get("overlays") or layers.get("audio_cues")):
        return staging_path
    _check_abort(abort_callback, phase="layers")
    if progress:
        progress(97, "Applying overlays and audio cues…")
    layered_path = os.path.join(temp_dir, "layered.mp4")
    applied = apply_layers(
        staging_path, layered_path,
        overlays=list(layers.get("overlays") or []), audio_cues=list(layers.get("audio_cues") or []),
        width=width, height=height, fps=fps, duration=duration, duck=float(layers.get("duck") or 0),
    )
    return layered_path if applied else staging_path


__all__ = [
    "AUDIO_EXTENSIONS", "IMAGE_EXTENSIONS", "LayerValidationError", "MAX_AUDIO_CUES", "MAX_OVERLAYS",
    "apply_layers", "apply_render_layers", "build_layer_filter", "clean_audio_cues", "clean_duck", "clean_export_layers", "clean_overlays",
    "resolve_export_layers", "resolve_layer_media", "workspace_media_resolver",
]
