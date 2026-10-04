"""Plan one Series Lab shot as a Video 2D shot: framing, cast, timing, background, sound and cards.

A shot already says what the planner or the writer decided: free-text
``framing`` and ``camera`` ("wide shot", "plano medio", "slow push-in"), the
visible characters, the location and its variant, and the dialogue. An
optional ``layout2d`` block overrides any of it explicitly:

    {"framing": "two", "camera": "push",
     "cast": [{"characterId": "kevin", "poseId": "panic", "x": 30, "motion": "shake", "enterFrom": "left"}],
     "card": {"kind": "title", "title": "...", "body": "..."},
     "music": {"file": "mus-moral.wav", "volume": 0.45, "start": 0}}

Locations may carry ``layout2d.homes`` (x % per character, for continuity
between shots) and ``layout2d.backgroundAssetId``. ``series.soundDesign``
holds a stinger for the first shot of each scene and an ambience per
location. Timing follows the recorded lines: 0.35 s in, 0.22 s between
lines, 0.45 s out, at least 1.5 s.
"""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import quote

from services import series_shot_extras as extras
from services.speech_language import speech_language_code

FRAMINGS = ("wide", "two", "medium", "close", "insert", "title")
_FRAMING_WORDS = (
    ("close", ("close-up", "close up", "closeup", "primer plano", "primerísimo", "extreme close")),
    ("medium", ("medium", "plano medio", "mid shot", "waist", "plano americano", "cowboy")),
    ("two", ("two-shot", "two shot", "plano a dos", "over the shoulder", "over-the-shoulder")),
    ("insert", ("insert", "inserto", "detail", "detalle")),
    ("title", ("title card", "cartela", "end card")),
    ("wide", ("wide", "general", "establishing", "long shot", "full shot", "de situación", "plano de conjunto")),
)
_PUSH_WORDS = ("push", "dolly in", "zoom in", "creep in", "acerc", "zoom lento", "travelling hacia")
LANGUAGE_KEYS = {"en": "english", "es": "spanish", "fr": "french", "de": "german", "it": "italian", "pt": "portuguese",
                 "ja": "japanese", "ko": "korean", "cmn": "chinese", "zh": "chinese", "ru": "russian"}
MOTIONS = ("idle", "still", "shake")
FPS = 24
FINISH = {"texture": {"kind": "paper", "amount": 0.08}, "grain": {"amount": 0.03, "size": 1.2},
          "vignette": {"amount": 0.12, "softness": 0.7}, "applyToTexts": False}


def _number(value: Any, low: float, high: float) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high else None


def _text_field(value: Any, key: str, limit: int) -> dict[str, str]:
    return {key: value[key][:limit]} if isinstance(value.get(key), str) and value[key] else {}


def _numbers(value: dict, limits: tuple[tuple[str, float, float], ...]) -> dict[str, float]:
    return {key: float(value[key]) for key, low, high in limits if _number(value.get(key), low, high) is not None}


def _choice(value: dict, key: str, allowed: tuple[str, ...]) -> dict[str, str]:
    return {key: value[key]} if value.get(key) in allowed else {}


def _explicit_transform(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    numbers = _numbers(value, (("x", -200, 300), ("y", -200, 300), ("scale", 0.01, 10)))
    return {"transform": numbers} if len(numbers) == 3 else {}


def _cast_entry(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("characterId"), str) or not value["characterId"]:
        return None
    return {"characterId": value["characterId"][:160], **_text_field(value, "poseId", 120),
            **_numbers(value, (("x", -50, 150), ("scale", 0.2, 4))), **_choice(value, "motion", MOTIONS),
            **_choice(value, "enterFrom", ("left", "right")), **_explicit_transform(value.get("transform"))}


def _prop_entry(value: Any) -> dict[str, Any] | None:
    """A prop on the set: a series asset or a workspace file, at a background anchor or at x/y %."""
    if not isinstance(value, dict):
        return None
    source = {**_text_field(value, "assetId", 300), **_text_field(value, "file", 300)}
    if len(source) != 1:
        return None
    return {**source, "scale": _number(value.get("scale"), 0.01, 4) or 0.3, **_text_field(value, "anchor", 80),
            **_numbers(value, (("x", -50, 150), ("y", -50, 150), ("z", 0, 100)))}


def _layout_card(card: Any) -> dict[str, Any]:
    if not isinstance(card, dict) or card.get("kind") not in ("title", "disclaimer", "end"):
        return {}
    return {"card": {"kind": card["kind"], "title": str(card.get("title") or "")[:200], "body": str(card.get("body") or "")[:1200]}}


def _layout_music(music: Any) -> dict[str, Any]:
    if not isinstance(music, dict) or not isinstance(music.get("file"), str) or not music["file"]:
        return {}
    return {"music": {"file": music["file"][:300], "volume": _number(music.get("volume"), 0, 1) or 0.5,
                      "start": _number(music.get("start"), 0, 600) or 0.0}}


def _layout_list(value: dict, key: str, limit: int, normalize: Any) -> dict[str, list]:
    items = [entry for entry in (normalize(item) for item in (value.get(key) or [])[:limit]) if entry]
    return {key: items} if items else {}


def normalize_layout2d(value: Any) -> dict[str, Any] | None:
    """The editable 2D plan of a shot; unknown keys and bad values are dropped."""
    if not isinstance(value, dict):
        return None
    layout = {**_choice(value, "framing", FRAMINGS), **_choice(value, "camera", ("static", "push")),
              **_layout_list(value, "cast", 8, _cast_entry), **_layout_card(value.get("card")),
              **_layout_list(value, "props", 12, _prop_entry), **_layout_music(value.get("music")),
              **extras.normalize_timing(value.get("timing")), **_layout_list(value, "sfx", 12, extras.sfx_entry),
              **_layout_list(value, "fx", 12, extras.fx_entry)}
    return layout or None


def classify_framing(text: str, cast_count: int) -> str:
    lowered = f" {str(text or '').lower()} "
    for framing, words in _FRAMING_WORDS:
        if any(word in lowered for word in words):
            return framing
    return "title" if cast_count == 0 else "medium" if cast_count == 1 else "two" if cast_count == 2 else "wide"


def classify_camera(text: str) -> str:
    lowered = str(text or "").lower()
    return "push" if any(word in lowered for word in _PUSH_WORDS) else "static"


def spread(count: int, portrait: bool = False) -> list[float]:
    """Default x positions: 50; 34/66; then evenly between 15 and 85. A vertical frame is narrow, so two
    characters stand further apart (25/75) and more go between 18 and 82."""
    if count <= 1:
        return [50.0] * count
    if count == 2:
        return [25.0, 75.0] if portrait else [34.0, 66.0]
    low, high = (18, 82) if portrait else (15, 85)
    return [round(low + (high - low) * index / (count - 1), 2) for index in range(count)]


def frame_size(series: dict[str, Any]) -> tuple[int, int]:
    """1080x1920 for a vertical series (TikTok, Reels: ``provider.videoSettings.orientation`` portrait), else 1920x1080."""
    settings = ((series.get("provider") or {}).get("videoSettings") or {}) if isinstance(series.get("provider"), dict) else {}
    return (1080, 1920) if settings.get("orientation") == "portrait" else (1920, 1080)


def language_key(series: dict[str, Any]) -> str:
    """Spoken language of the series as a voice key (``english``, ``spanish``...)."""
    for label in (series.get("spokenLanguage"), series.get("language")):
        code = str(speech_language_code(str(label or "")) or "").lower().split("-")[0]
        if code in LANGUAGE_KEYS:
            return LANGUAGE_KEYS[code]
    return "english"


def kit_ref(series: dict[str, Any], character_id: str) -> dict[str, str] | None:
    for character in series.get("characters") or []:
        if character.get("id") == character_id:
            ref = (character.get("voiceProfile") or {}).get("characterKitRef")
            return ref if isinstance(ref, dict) and ref.get("id") else None
    return None


def voice_for(kit: dict[str, Any], key: str) -> dict[str, Any] | None:
    return (kit.get("voicesByLanguage") or {}).get(key) or kit.get("voice")


def plan_timing(durations: list[float], *, intro: float = 0.35, gap: float = 0.22, tail: float = 0.45,
                minimum: float = 1.5, at_least: float = 0.0, pauses: list[float] | None = None) -> tuple[list[tuple[float, float]], float]:
    """Line spans and shot length; ``pauses[i]`` is extra silence before line ``i`` (a dramatic beat)."""
    cursor, timing = intro, []
    for index, duration in enumerate(durations):
        cursor += (pauses or [])[index] if index < len(pauses or []) else 0.0
        timing.append((round(cursor, 3), round(cursor + duration, 3)))
        cursor += duration + gap
    end = max([end for _, end in timing], default=0.0)
    duration = max(minimum, at_least, end + tail)
    return timing, round(round(duration * FPS) / FPS, 4)


def _asset_url(series: dict[str, Any], asset_id: str, workspace: str) -> tuple[str, str] | None:
    asset = (series.get("assets") or {}).get(asset_id)
    if not isinstance(asset, dict) or asset.get("kind") not in ("image", "video") or not asset.get("uri"):
        return None
    uri = str(asset["uri"])
    uri = uri[len("outputs/"):] if uri.startswith("outputs/") else uri
    return f"/api/v1/file/{quote(uri)}?workspace={quote(workspace)}", asset["kind"]


def background_for(series: dict[str, Any], shot: dict[str, Any], workspace: str) -> dict[str, Any] | None:
    location = next((item for item in series.get("locations") or [] if item.get("id") == shot.get("locationId")), None)
    if not location:
        return None
    layout = location.get("layout2d") if isinstance(location.get("layout2d"), dict) else {}
    variant = next((item for item in location.get("variants") or [] if item.get("id") == shot.get("locationVariantId")), {})
    candidates = [layout.get("plateAssetId"), layout.get("backgroundAssetId"), *(variant.get("referenceAssetIds") or []),
                  *(location.get("referenceAssetIds") or [])]
    for asset_id in candidates:
        found = _asset_url(series, asset_id, workspace) if asset_id else None
        if found:
            return {"source": found[0], "kind": found[1]}
    return None


def _homes(series: dict[str, Any], shot: dict[str, Any]) -> dict[str, float]:
    location = next((item for item in series.get("locations") or [] if item.get("id") == shot.get("locationId")), {})
    homes = (location.get("layout2d") or {}).get("homes") if isinstance(location.get("layout2d"), dict) else None
    return {key: float(value) for key, value in (homes or {}).items() if isinstance(value, (int, float))}


def _character_scale(series: dict[str, Any], entry: dict[str, Any]) -> float:
    """Shot scale, else the character's own ``layout2d.scale`` (a small robot, a tall giant), else 1."""
    if _number(entry.get("scale"), 0.2, 4) is not None:
        return float(entry["scale"])
    character = next((item for item in series.get("characters") or [] if item.get("id") == entry["characterId"]), {})
    own = (character.get("layout2d") or {}).get("scale") if isinstance(character.get("layout2d"), dict) else None
    return float(own) if _number(own, 0.2, 4) is not None else 1.0


def _cast_x(entry: dict[str, Any], framing: str, count: int, homes: dict[str, float], default: float) -> float:
    if isinstance(entry.get("x"), (int, float)):
        return float(entry["x"])
    if framing in ("medium", "close") and count == 1:
        return 50.0
    return homes.get(entry["characterId"], default)


def _cast_item(series: dict[str, Any], entry: dict[str, Any], x: float, duration: float, workspace: str = "") -> dict[str, Any] | None:
    ref = kit_ref(series, entry["characterId"])
    if not ref:
        return None
    item = {"kitId": ref["id"], "characterId": entry["characterId"], "poseId": entry.get("poseId") or "base", "x": x,
            "motion": entry.get("motion") if entry.get("motion") in MOTIONS else "idle", "boost": _character_scale(series, entry)}
    if isinstance(entry.get("transform"), dict):
        item["transform"] = entry["transform"]
    else:
        character = next((value for value in series.get("characters") or [] if value.get("id") == entry["characterId"]), {})
        seat = extras.perch(character, workspace)
        if seat:
            item["perch"] = seat
    if entry.get("enterFrom") in ("left", "right"):
        item["enter"] = {"fromX": -15.0 if entry["enterFrom"] == "left" else 115.0, "start": 0.2, "end": min(duration, 1.4)}
    return item


def plan_cast(series: dict[str, Any], shot: dict[str, Any], framing: str, duration: float, workspace: str = "",
              portrait: bool = False) -> list[dict[str, Any]]:
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    explicit = [item for item in layout.get("cast") or [] if isinstance(item, dict) and item.get("characterId")]
    entries = explicit or [{"characterId": cid} for cid in shot.get("visibleCharacterIds") or []]
    homes, defaults = _homes(series, shot), spread(len(entries), portrait)
    items = (_cast_item(series, entry, _cast_x(entry, framing, len(entries), homes, defaults[index]), duration, workspace)
             for index, entry in enumerate(entries))
    return [item for item in items if item]


def _text(tid: str, value: str, start: float, end: float, y: float, size: float, **extra: Any) -> dict[str, Any]:
    base = {"id": tid, "text": value, "start": round(start, 3), "end": round(end, 3), "preset": "impact", "x": 50, "y": y, "size": size,
            "color": "#ffffff", "font": "display", "weight": 800, "align": "center", "maxWidth": 86}
    base.update(extra)
    return base


BACKGROUND_ZOOM = {"wide": 1.0, "two": 1.12, "medium": 1.28, "close": 1.5, "insert": 1.0, "title": 1.0}


def background_point(framing: str, focus: float, u: float, v: float) -> tuple[float, float]:
    """Frame position (%) of a point (u, v) of a full-frame background, zoomed and panned like the compiler does."""
    zoom = BACKGROUND_ZOOM.get(framing, 1.0)
    span = 50 * (zoom - 1)
    x = max(50 - span, min(50 + span, 50 - (focus / 100 - 0.5) * 100 * zoom))
    return round(x + (u - 0.5) * 100 * zoom, 3), round(50 + (v - 0.5) * 100 * zoom, 3)


def _prop_source(series: dict[str, Any], prop: dict[str, Any], workspace: str) -> str | None:
    if prop.get("assetId"):
        found = _asset_url(series, prop["assetId"], workspace)
        return found[0] if found else None
    return f"/api/v1/file/{quote(prop['file'])}?workspace={quote(workspace)}"


def _prop_position(prop: dict[str, Any], anchors: dict[str, Any], framing: str, focus: float, scale: float) -> tuple[float, float]:
    anchor = anchors.get(prop.get("anchor", "")) if prop.get("anchor") else None
    if isinstance(anchor, dict) and all(isinstance(anchor.get(key), (int, float)) for key in ("u", "v")):
        x, y = background_point(framing, focus, float(anchor["u"]), float(anchor["v"]))
        return x, y - scale * 50  # the prop stands on its anchor
    return prop.get("x", 50.0), prop.get("y", 60.0)


def plan_props(series: dict[str, Any], shot: dict[str, Any], framing: str, focus: float, workspace: str) -> list[dict[str, Any]]:
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    location = next((item for item in series.get("locations") or [] if item.get("id") == shot.get("locationId")), {})
    anchors = ((location.get("layout2d") or {}).get("anchors") if isinstance(location.get("layout2d"), dict) else None) or {}
    zoom = BACKGROUND_ZOOM.get(framing, 1.0)
    props = []
    for index, prop in enumerate(layout.get("props") or []):
        source = _prop_source(series, prop, workspace)
        if not source:
            continue
        scale = round(prop.get("scale", 0.3) * zoom, 4)
        x, y = _prop_position(prop, anchors, framing, focus, scale)
        props.append({"id": f"prop-{index + 1}", "name": prop.get("anchor") or f"Prop {index + 1}", "source": source,
                      "x": round(x, 3), "y": round(y, 3), "scale": scale, "z": prop.get("z", 8)})
    return props


def _disclaimer_texts(title: str, body: str, duration: float) -> list[dict[str, Any]]:
    fade = {"preset": "fade", "duration": 0.5}
    texts = [_text("card-title", title, 0.3, duration - 0.3, 30, 8, font="condensed", enter=fade, exit=fade)] if title else []
    if body:
        texts.append(_text("card-body", body, 0.6, duration - 0.3, 56, 4.4, font="sans", weight=500, maxWidth=78, lineHeight=1.35,
                           enter=fade, exit=fade))
    return texts


def _title_texts(kind: str, title: str, body: str, duration: float) -> list[dict[str, Any]]:
    stroke = {"color": "#2b1a0e", "width": 0.12}
    opening = kind == "title"
    texts = [_text("card-title", title, 0.5, duration, 26 if opening else 30, 11 if opening else 10, color="#fff4c2", font="marker",
                   stroke=stroke, enter={"preset": "drop", "duration": 0.6})] if title else []
    if body:
        lettering = {"font": "hand", "stroke": stroke} if opening else {"font": "sans"}
        texts.append(_text("card-body", body, 1.6, duration, 44 if opening else 54, 4 if opening else 3, weight=600, **lettering,
                           enter={"preset": "typewriter" if opening else "fade", "duration": 1.0}))
    return texts


def card_texts(card: dict[str, Any], duration: float, portrait: bool = False) -> list[dict[str, Any]]:
    """Title, disclaimer and end cards in the production's lettering. Sizes are % of the frame height, so a
    vertical frame (0.56 as wide) draws them smaller and wider to keep the same line length."""
    kind, title, body = card.get("kind"), str(card.get("title") or ""), str(card.get("body") or "")
    if kind == "disclaimer":
        texts = _disclaimer_texts(title, body, duration)
    else:
        texts = _title_texts(kind, title, body, duration) if kind in ("title", "end") else []
    if portrait:
        texts = [{**text, "size": round(text["size"] * 0.6, 2), "maxWidth": 90} for text in texts]
    return texts


def sound_tracks(series: dict[str, Any], shot: dict[str, Any], first_of_scene: bool) -> list[dict[str, Any]]:
    design = series.get("soundDesign") if isinstance(series.get("soundDesign"), dict) else {}
    tracks = []
    ambience = (design.get("ambienceByLocation") or {}).get(shot.get("locationId") or "")
    if isinstance(ambience, dict) and ambience.get("file"):
        tracks.append({"id": "ambience", "filename": ambience["file"], "name": "Ambience", "kind": "sfx", "startTime": 0,
                       "volume": float(ambience.get("volume", 0.22))})
    stinger = design.get("stinger")
    if first_of_scene and isinstance(stinger, dict) and stinger.get("file"):
        tracks.append({"id": "stinger", "filename": stinger["file"], "name": "Stinger", "kind": "music", "startTime": 0,
                       "volume": float(stinger.get("volume", 0.6))})
    music = (shot.get("layout2d") or {}).get("music") if isinstance(shot.get("layout2d"), dict) else None
    if isinstance(music, dict) and music.get("file"):
        tracks.append({"id": "music", "filename": music["file"], "name": "Music", "kind": "music",
                       "startTime": float(music.get("start", 0)), "volume": float(music.get("volume", 0.5))})
    return tracks


def line_id(episode_id: str, beat_id: str) -> str:
    return f"{episode_id}-{beat_id}"[:120]


def _shot_framing(layout: dict[str, Any], shot: dict[str, Any], card: dict[str, Any] | None) -> str:
    if layout.get("framing") in FRAMINGS:
        return layout["framing"]
    entries = layout.get("cast") or shot.get("visibleCharacterIds") or []
    return classify_framing(shot.get("framing", ""), 0 if card else len(entries))


def _shot_lines(series: dict[str, Any], episode: dict[str, Any], beats: list[dict], timing: list[tuple[float, float]],
                recorded: dict[str, dict[str, Any]], visible: set[str]) -> list[dict[str, Any]]:
    lines = []
    for beat, (start, end) in zip(beats, timing):
        ref = kit_ref(series, beat.get("characterId", ""))
        heard = recorded[beat["id"]]
        lines.append({"id": line_id(episode["id"], beat["id"]), "kitId": ref["id"] if ref else beat.get("characterId", ""),
                      "text": beat["text"], "start": start, "end": end, "filename": heard["filename"],
                      "cues": heard.get("cues") or None, "driver": heard.get("driver"),
                      "visible": beat.get("characterId") in visible, "name": beat.get("characterId")})
    return lines


def _shot_camera(layout: dict[str, Any], shot: dict[str, Any]) -> str:
    return layout["camera"] if layout.get("camera") in ("static", "push") else classify_camera(shot.get("camera", ""))


def _focus(cast: list[dict[str, Any]], framing: str) -> float:
    """Tighter framings pan the background toward the cast."""
    return sum(item["x"] for item in cast) / len(cast) if cast and framing in ("two", "medium", "close") else 50.0


def _narrative(series: dict[str, Any], episode: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    return {"templateId": "series-shot", "controls": {"seriesId": series["id"], "episodeId": episode["id"], "shotId": shot["id"]},
            "visualIntent": str(shot.get("action") or shot.get("prompt") or "")[:500]}


def _with_set(spec: dict[str, Any], series: dict[str, Any], shot: dict[str, Any], focus: float, workspace: str) -> dict[str, Any]:
    background = background_for(series, shot, workspace)
    if background:
        spec["background"] = {**background, "focusX": focus}
    props = plan_props(series, shot, spec["framing"], focus, workspace)
    if props:
        spec["props"] = props
    return spec


def build_shot_spec(series: dict[str, Any], episode: dict[str, Any], shot: dict[str, Any], *, workspace: str,
                    recorded: dict[str, dict[str, Any]], first_of_scene: bool = False,
                    size: tuple[int, int] | None = None) -> dict[str, Any]:
    """The compiler input for one shot. ``recorded`` maps beat id to {filename, duration, cues, driver}."""
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    card = layout.get("card") if isinstance(layout.get("card"), dict) else None
    beats = [beat for beat in shot.get("dialogueBeats") or [] if str(beat.get("text") or "").strip()]
    timing, duration = plan_timing([float(recorded[beat["id"]]["duration"]) for beat in beats], **extras.timing_args(layout),
                                   at_least=0.0 if beats else float(shot.get("durationSeconds") or 0), pauses=extras.pauses(beats))
    framing = _shot_framing(layout, shot, card)
    size = size or frame_size(series)
    portrait = size[1] > size[0]
    cast = [] if framing == "title" else plan_cast(series, shot, framing, duration, workspace, portrait)
    title = f"{series.get('title') or series.get('id')} · {episode.get('title') or episode['id']} · {shot['id']}"
    spec = {
        "name": title[:200], "workspace": workspace, "width": size[0], "height": size[1], "fps": FPS, "duration": duration,
        "framing": framing, "cast": cast, "lines": _shot_lines(series, episode, beats, timing, recorded, {item["characterId"] for item in cast}),
        "audioTracks": [*sound_tracks(series, shot, first_of_scene), *extras.sfx_tracks(layout, timing, duration)],
        "texts": card_texts(card, duration, portrait) if card else [], "sfx": extras.fx_cues(layout, timing, duration),
        "camera": _shot_camera(layout, shot), "finish": FINISH, "narrative": _narrative(series, episode, shot),
    }
    return _with_set(spec, series, shot, _focus(cast, framing), workspace)


def recording_key(text: str, voice: dict[str, Any] | None) -> str:
    """Same text and voice reuse the same recording across runs and resumes."""
    digest = hashlib.sha1(repr((text, sorted((voice or {}).items()))).encode("utf-8")).hexdigest()
    return digest[:12]
