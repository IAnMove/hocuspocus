"""Cheap checks before a music video spends GPU time.

``uncover_titles`` keeps a full-frame title card off shots that already have a
picture. ``dry_run`` reports ``hold_after_clip`` and compiles every scene
in-process (no MCP). ``through: "animatic"`` stores its video apart from the
finished cut. Caption contrast is measured with Pillow against one real frame.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from services.music_production import Production, ProductionError, h3_frames_for
from services.scene2d_text_boxes import _sample, contrast_ratio
from services.video2d_edit import MAX_OPERATIONS, Video2dEditError, edit

_IMAGE = frozenset({"h3", "still"})
_MOVING = frozenset({"h3", "clip", "scene3d", "screen"})
_CONTRAST_MIN = 3.0
_BOX_OPAQUE = 0.5
_DEAD_S = 10.0
_GAP_S = 0.3
FILLER_URL = "/api/v1/file/preview.png?workspace=preview"
_CAPTION_BAND = {"left": 10, "top": 70, "right": 90, "bottom": 92}


def uncover_titles(shots: Any) -> Any:
    """Rewrite title-card to a lower third on h3 and still shots. Other kinds stay."""
    if not isinstance(shots, list):
        return shots
    return [_retitle(shot) for shot in shots]


def _retitle(shot: Any) -> Any:
    if not isinstance(shot, dict):
        return shot
    title = shot.get("title")
    if shot.get("kind") not in _IMAGE or not isinstance(title, dict) or title.get("template") != "title-card":
        return shot
    return {**shot, "title": {**title, "template": "lower-third-date"}}


def title_card_warnings(shots: Any) -> list[dict]:
    """Hand-written title cards on a picture. Validation still accepts the spec."""
    if not isinstance(shots, list):
        return []
    return [{"code": "title_card_on_image", "key": shot.get("key")}
            for shot in shots if _wears_title_card(shot)]


def _wears_title_card(shot: Any) -> bool:
    if not isinstance(shot, dict) or shot.get("kind") not in _IMAGE:
        return False
    title = shot.get("title")
    return isinstance(title, dict) and title.get("template") == "title-card"


def log_title_cards(production: Any, spec: Any) -> None:
    shots = spec.get("shots") if isinstance(spec, dict) else None
    for item in title_card_warnings(shots):
        production.log(f"title card covers the image on {item.get('key')}")


def _duration(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fill_moves(fill: Any) -> bool:
    """A moving fill absorbs the tail an H3 clip cannot cover. A still fill does not."""
    if not isinstance(fill, list) or not fill:
        return False
    return all(isinstance(item, dict) and item.get("kind") in _MOVING for item in fill)


def _cuts(windows: list, duration: float) -> list[float]:
    cuts = [_duration(shot.get("t0")) if isinstance(shot, dict) else 0.0 for shot in windows]
    if cuts:
        cuts[0] = 0.0
    cuts.append(duration)
    return cuts


def _span_hold(shot: Any, start: float, end: float, moving: bool) -> float:
    if not isinstance(shot, dict) or shot.get("kind") != "h3" or moving:
        return 0.0
    try:
        span = max(0.0, _duration(shot["t1"]) - _duration(shot["t0"]))
        clip = h3_frames_for(span) / 24 - max(0.0, start - _duration(shot["t0"]))
    except (KeyError, TypeError, ValueError):
        return 0.0
    over = end - start - max(clip, 0.0)
    if over <= _GAP_S:
        return 0.0
    return round(over, 3)


def hold_after_clip(windows: list, duration: Any, fill: Any) -> list[float]:
    """Seconds each window would sit still after its H3 clip. 0 for other kinds and for a moving fill."""
    if not windows:
        return []
    length = _duration(duration)
    cuts = _cuts(windows, length)
    moving = _fill_moves(fill)
    return [_span_hold(shot, cuts[index], cuts[index + 1], moving) for index, shot in enumerate(windows)]


def dead_time_warnings(windows: list, duration: Any, fill: Any) -> list[dict]:
    """A still scene, or an H3 tail, with nothing moving for more than 10 seconds."""
    if not windows:
        return []
    length = _duration(duration)
    holds = hold_after_clip(windows, length, fill)
    cuts = _cuts(windows, length)
    found = []
    for index, shot in enumerate(windows):
        if not isinstance(shot, dict):
            continue
        seconds = holds[index]
        if shot.get("kind") == "still":
            seconds = max(seconds, cuts[index + 1] - cuts[index])
        if seconds > _DEAD_S:
            found.append({"code": "dead_time", "key": shot.get("key"), "seconds": round(seconds, 1)})
    return found


def image_repeated(windows: list, frames: Any) -> list[dict]:
    """Two uses of the same still or the same start frame. dry_run still waits for three."""
    frames = frames if isinstance(frames, dict) else {}
    uses: dict[str, list] = {}
    for shot in windows:
        token = _image_token(shot, frames)
        if token is None:
            continue
        uses.setdefault(token, []).append(shot.get("key") if isinstance(shot, dict) else None)
    return [{"code": "image_repeated", "image": token.split(":", 1)[1], "shots": keys}
            for token, keys in uses.items() if len(keys) >= 2]


def _image_token(shot: Any, frames: dict) -> str | None:
    if not isinstance(shot, dict):
        return None
    if shot.get("kind") == "still" and isinstance(shot.get("still"), str):
        return "still:" + shot["still"]
    if shot.get("kind") != "h3":
        return None
    name = frames.get(shot.get("key"))
    if isinstance(name, str) and name:
        return "frame:" + name
    return None


class _Host:
    """Stand-in so scene_ops can build ops without a workspace or an upload."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = {"frames": {}, "held": []}

    def upload(self, name: str) -> tuple[str, str]:
        return name, FILLER_URL

    def log(self, line: str) -> None:
        return None

    @staticmethod
    def _title_ops(shot: dict, dur: float, style: dict):
        return Production._title_ops(shot, dur, style)

    def _lyric_ops(self, shot: dict, a: float, b: float, dur: float, score: dict, style: dict, used: int):
        return Production._lyric_ops(self, shot, a, b, dur, score, style, used)

    @staticmethod
    def _footer_ops(dur: float, style: dict):
        return Production._footer_ops(dur, style)


def _filler_stills(spec: dict, windows: list) -> dict[str, str]:
    names: set[str] = set()
    raw = spec.get("stills") if isinstance(spec.get("stills"), dict) else {}
    names.update(key for key in raw if isinstance(key, str))
    for shot in windows:
        if isinstance(shot, dict) and isinstance(shot.get("still"), str):
            names.add(shot["still"])
    return {name: FILLER_URL for name in names}


def _remember_clip(clips: dict, key: Any) -> None:
    if isinstance(key, str) and key:
        clips[key] = {"url": FILLER_URL, "file": "preview.mp4", "qa": {}}


def _filler_clips(windows: list) -> dict[str, dict]:
    clips: dict[str, dict] = {}
    for shot in windows:
        if not isinstance(shot, dict):
            continue
        if shot.get("kind") == "clip":
            _remember_clip(clips, shot.get("key"))
            _remember_clip(clips, shot.get("clip"))
        elif shot.get("kind") == "scene3d":
            _remember_clip(clips, shot.get("key"))
    return clips


def _apply_ops(document: dict, ops: list) -> None:
    if not ops:
        edit({"version": 1, "input": {"document": document, "operations": [], "full": True}})
        return
    for index in range(0, len(ops), MAX_OPERATIONS):
        result = edit({"version": 1, "input": {"document": document, "operations": ops[index:index + MAX_OPERATIONS], "full": True}})
        document = result["result"]["document"]


def _compile_shot(host: _Host, shot: dict, score: dict, clips: dict, style: dict, stills: dict) -> None:
    start = _duration(shot.get("t0"))
    end = _duration(shot.get("t1"))
    dur = round(end - start, 3)
    if dur <= 0:
        dur = 0.2
    ops = Production.scene_ops(host, shot, start, start + dur, dur, score, clips, style, stills)
    name = str(shot.get("key") or "shot")[:80] or "shot"
    document = {"version": 1, "name": name, "width": 1920, "height": 1080, "fps": 24,
                "duration": dur, "layers": [], "texts": []}
    _apply_ops(document, ops)


def scene_compile_errors(spec: dict, score: dict, windows: list) -> list[dict]:
    """Build each scene with the in-process editor. One bad shot becomes a warning."""
    if not windows:
        return []
    host = _Host()
    for shot in windows:
        if isinstance(shot, dict) and shot.get("kind") == "h3" and isinstance(shot.get("key"), str):
            host.state["frames"][shot["key"]] = "preview.png"
    style = spec.get("style") if isinstance(spec.get("style"), dict) else {}
    stills = _filler_stills(spec, windows)
    clips = _filler_clips(windows)
    found = []
    for shot in windows:
        if not isinstance(shot, dict):
            continue
        try:
            _compile_shot(host, shot, score, clips, style, stills)
        except (Video2dEditError, ProductionError) as error:
            found.append({"code": "scene_invalid", "key": shot.get("key"), "message": str(error)[:200]})
        except Exception as error:
            found.append({"code": "scene_invalid", "key": shot.get("key"), "message": str(error)[:200]})
    return found


def preview_extras(spec: dict, score: dict, windows: list, shots: list) -> tuple[list[float], list[dict]]:
    holds = hold_after_clip(windows, _duration(score.get("duration")), spec.get("fill") or [])
    warnings = [*title_card_warnings(shots), *scene_compile_errors(spec, score, windows)]
    return holds, warnings


def _hex(color: Any) -> tuple[int, int, int] | None:
    text = str(color or "").strip()
    if len(text) != 7 or not text.startswith("#"):
        return None
    try:
        return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)
    except ValueError:
        return None


def _mix(photo: tuple[int, int, int], plate: tuple[int, int, int], opacity: float) -> tuple[int, int, int]:
    weight = max(0.0, min(1.0, opacity))
    return tuple(int(round(plate[channel] * weight + photo[channel] * (1.0 - weight))) for channel in range(3))


def _background(pixels: bytes, width: int, height: int, cue: dict) -> tuple[int, int, int] | None:
    bounds = cue.get("bounds") if isinstance(cue.get("bounds"), dict) else {}
    box = {"left": _duration(bounds.get("left")), "top": _duration(bounds.get("top")),
           "right": _duration(bounds.get("right", 100)), "bottom": _duration(bounds.get("bottom", 100))}
    photo = _sample(pixels, width, height, box)
    if photo is None:
        return None
    plate = cue.get("box") if isinstance(cue.get("box"), dict) else None
    if plate is None:
        return photo
    color = _hex(plate.get("color"))
    if color is None:
        return photo
    try:
        opacity = float(plate.get("opacity", 1))
    except (TypeError, ValueError):
        opacity = 1.0
    if opacity < _BOX_OPAQUE:
        return photo
    return _mix(photo, color, opacity)


def measure_caption(pixels: bytes, width: int, height: int, cues: list) -> dict | None:
    """Worst text-to-seen contrast. An opaque box is what the viewer reads against."""
    worst = None
    for cue in cues or []:
        if not isinstance(cue, dict):
            continue
        text = _hex(cue.get("color"))
        seen = _background(pixels, width, height, cue)
        if text is None or seen is None:
            continue
        ratio = contrast_ratio(text, seen)
        if worst is None or ratio < worst["ratio"]:
            worst = {"ratio": ratio, "against_box": isinstance(cue.get("box"), dict), "cue": cue.get("id")}
    return worst


def caption_failure(measurement: Any, scene: Any) -> dict | None:
    if not isinstance(measurement, dict):
        return None
    try:
        ratio = float(measurement["ratio"])
    except (KeyError, TypeError, ValueError):
        return None
    if ratio >= _CONTRAST_MIN:
        return None
    return {"code": "caption_unreadable", "scene": scene, "ratio": round(ratio, 2)}


def lyric_cues(style: Any) -> list[dict]:
    """One caption sample. Dymo without its own box uses the readable cream tape."""
    style = style if isinstance(style, dict) else {}
    own = style.get("lyric_style") if isinstance(style.get("lyric_style"), dict) else {}
    base: dict = {}
    if style.get("lyric_template") == "dymo" and "box" not in own:
        base = {"color": "#141210", "box": {"color": "#F4EEE2", "opacity": 1}}
    look = {**base, **own}
    if "color" not in look:
        return []
    box = look.get("box") if isinstance(look.get("box"), dict) else None
    return [{"id": "lyric", "color": look.get("color"), "box": box, "bounds": dict(_CAPTION_BAND)}]


def _lyric_chars(shot: dict, lines: list) -> int:
    start, end = _duration(shot.get("t0")), _duration(shot.get("t1"))
    total = 0
    for line in lines:
        if not isinstance(line, dict):
            continue
        if _duration(line.get("t1")) <= start or _duration(line.get("t0")) >= end:
            continue
        total += len(str(line.get("text") or ""))
    return total


def _busiest(windows: list, score: dict) -> dict | None:
    lines = score.get("lines") if isinstance(score.get("lines"), list) else []
    best, best_n = None, -1
    for shot in windows:
        if not isinstance(shot, dict):
            continue
        count = _lyric_chars(shot, lines)
        if count > best_n:
            best, best_n = shot, count
    return best


def _frame_file(production: Any, shot: dict | None):
    if shot is None:
        return None
    frames = production.state.get("frames") if isinstance(production.state.get("frames"), dict) else {}
    name = frames.get(shot.get("key"))
    if not isinstance(name, str) or not name:
        return None
    path = production.root / name
    return path if path.is_file() else None


def _sampled(production: Any, spec: dict, shot: dict | None) -> dict | None:
    path = _frame_file(production, shot)
    if path is None:
        return None
    cues = lyric_cues(spec.get("style") if isinstance(spec, dict) else {})
    if not cues:
        return None
    try:
        from PIL import Image
        image = Image.open(path).convert("RGB")
    except (OSError, ImportError):
        return None
    return measure_caption(image.tobytes(), image.width, image.height, cues)


def _probe_failure(state: dict, windows: list, score: dict) -> dict | None:
    probe = state.get("caption_probe")
    if not isinstance(probe, dict) or "ratio" not in probe:
        return None
    try:
        ratio = float(probe["ratio"])
    except (TypeError, ValueError):
        return None
    scene = probe.get("scene")
    if not scene:
        shot = _busiest(windows, score)
        scene = shot.get("key") if shot else None
    return caption_failure({"ratio": ratio}, scene)


def _remember_caption(state: dict, failure: dict) -> None:
    warnings = state.setdefault("animatic_warnings", [])
    if any(isinstance(item, dict) and item.get("code") == "caption_unreadable" and item.get("scene") == failure.get("scene")
           for item in warnings):
        return
    warnings.append(failure)


def _apply_caption(state: dict, failure: dict | None) -> None:
    if not failure:
        return
    if state.get("caption_gate") == "warn":
        _remember_caption(state, failure)
        return
    raise ProductionError("caption_unreadable", f"caption unreadable ratio {failure['ratio']} scene {failure['scene']}")


def ensure_caption_contrast(production: Any, spec: dict, windows: list, score: dict) -> None:
    """Stop before exporting every scene when the busiest caption is under 3:1.

    ``state["caption_probe"]`` is the test seam: existing scene mocks have no
    frame file, so the default path samples only when that file is on disk.
    """
    if isinstance(production.state.get("caption_probe"), dict):
        _apply_caption(production.state, _probe_failure(production.state, windows, score))
        return
    shot = _busiest(windows, score)
    measured = _sampled(production, spec, shot)
    scene = shot.get("key") if shot else None
    _apply_caption(production.state, caption_failure(measured, scene) if measured else None)


def animatic_report(spec: Any, windows: list, score: Any, state: Any) -> list[dict]:
    spec = spec if isinstance(spec, dict) else {}
    score = score if isinstance(score, dict) else {}
    state = state if isinstance(state, dict) else {}
    shots = spec.get("shots") if isinstance(spec.get("shots"), list) else windows
    return [
        *title_card_warnings(shots),
        *image_repeated(windows, state.get("frames") or {}),
        *dead_time_warnings(windows, _duration(score.get("duration")), spec.get("fill") or []),
    ]


def _workspace_file(root, name: object) -> Path | None:
    if not isinstance(name, str) or not name or Path(name).name != name:
        return None
    path = Path(root) / name
    return path if path.is_file() else None


def snapshot_cut_artifacts(root, state: dict) -> dict[str, dict[str, bytes | str]]:
    """Bytes of the finished montage and contact sheet, keyed by state field."""
    kept: dict[str, dict[str, bytes | str]] = {}
    for key in ("montage_file", "contact_sheet"):
        path = _workspace_file(root, state.get(key))
        if path is None:
            continue
        kept[key] = {"name": path.name, "data": path.read_bytes()}
    return kept


def restore_cut_artifacts(root, state: dict, kept: dict[str, dict[str, bytes | str]]) -> None:
    """Put the finished montage and contact sheet back after a preview export.

    ``montage()`` rebuilds the timeline in place (same ``montage_file``, same
    ``{id}-contact.jpg``). A later ``through: animatic`` on a completed cut
    must not keep those preview bytes as the published / editable artifacts.
    """
    for key, item in kept.items():
        name = item.get("name")
        data = item.get("data")
        if not isinstance(name, str) or not isinstance(data, (bytes, bytearray)):
            continue
        if Path(name).name != name:
            continue
        (Path(root) / name).write_bytes(data)
        state[key] = name


def claim_animatic_video(state: dict, previous: str | None) -> None:
    """Keep the preview off ``final`` so the run is not marked completed.

    A later animatic still writes a new montage filename into ``final``. That
    name is the preview; a prior completed cut must stay in ``final``.
    """
    video = state.get("final")
    if video and video != previous:
        state["animatic_video"] = video
    if previous:
        state["final"] = previous
    else:
        state.pop("final", None)


_CUT_KEYS = ("final", "montage_file", "contact_sheet")


def remember_completed_cut(state: dict, prior_status: object, through: object = "animatic") -> None:
    """Persist the finished-cut names before ``status`` becomes ``running``.

    A crash mid-animatic leaves the file ``running``. Resume then sees
    ``prior_status != completed`` and would fail or demote the production
    unless this snapshot is already on disk.
    """
    if through != "animatic" or prior_status != "completed":
        return
    final = state.get("final")
    if not isinstance(final, str) or not final:
        return
    state["completed_cut"] = {key: state[key] for key in _CUT_KEYS
                              if isinstance(state.get(key), str) and state[key]}


def completed_cut_final(state: dict) -> str | None:
    """Finished-cut filename: the persisted snapshot, else the current ``final``."""
    cut = state.get("completed_cut")
    if isinstance(cut, dict) and isinstance(cut.get("final"), str) and cut["final"]:
        return cut["final"]
    final = state.get("final")
    return final if isinstance(final, str) and final else None


def keep_completed_cut(state: dict, prior_status: object) -> bool:
    """True when this animatic must not fail or demote a finished production."""
    if prior_status == "completed" and isinstance(state.get("final"), str) and state["final"]:
        return True
    return completed_cut_final(state) is not None and isinstance(state.get("completed_cut"), dict)
