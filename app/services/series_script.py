"""An episode from a compact script (``series.episode.from_script``).

An agent writes what happens; this turns it into the episode the server renders:
ids from the episode number, scenes, shots with ``layout2d`` (cast, framing,
camera, card, music, timed sound and screen effects, timing, props, voice room,
set layers and the cast's depth among them),
``scene3d`` for Video 3D shots, ``foley`` (sound generated from the rendered
picture), the original's lines and a language version for every other
language in the script. It checks the script against the
series first, so a typo in a pose, a file or a character fails here with a
clear message instead of halfway through a render::

    {"title": {"es": "...", "en": "..."}, "premise": {...},
     "scenes": [{"id": "cold_open", "location": "street", "variant": "day", "purpose": "..."}],
     "shots": [{"scene": "cold_open", "framing": "wide", "camera": "push",
                "cast": [["kevin", "base", 58], {"characterId": "mark", "poseId": "wave", "x": 30, "enterFrom": "left"},
                         ["boss", "bust", 80, {"edgeSnap": false}]],
                "lines": [{"who": "kevin", "es": "...", "en": "...", "pauseBefore": 0.6},
                          {"who": "narrator", "es": "...", "voiceRoom": "radio"}],
                "card": {"kind": "title", "es": ["TITLE", "Episode 3"], "en": [...]},
                "music": {"file": "mus-theme-es.wav", "en": "mus-theme-en.wav", "volume": 0.9},
                "sfx": [{"file": "sfx-pen.wav", "line": 1, "offset": 0.2},
                        {"file": "sfx-step.wav", "anchor": "enter", "cast": 1, "repeat": "steps"}],
                "fx": [{"kind": "confetti", "line": 1}],
                "props": [{"file": "prop-truck-key.png", "x": 12, "y": 74, "scale": 0.36},
                          {"file": "prop-robot-key.png", "x": 80, "scale": 0.5, "ground": true}], "timing": {"intro": 1.0},
                "layers": [{"file": "fg-pillar.png", "depth": 0.9, "front": true, "x": 8},
                           {"file": "bg-crowd.mp4", "depth": 0.2, "start": 2.5, "loop": "pingpong", "speed": 0.5}], "castDepth": 0.6,
                "voiceRoom": "cathedral", "duration": 7, "kind": "3d", "scene3d": {"template": "...", "cast": [...]},
                "foley": {"prompt": "wooden airship creaking, wind", "volume": 0.5}}]}
"""
from __future__ import annotations

from typing import Any, Callable

from services.series_entrances import GAITS
from services.series_layers import layout_layers
from services.series_shot3d import normalize_scene3d
from services.series_shot_extras import EFFECT_KINDS
from services.series_shot_foley import normalize_foley
from services.series_shot_plan import FRAMINGS, LANGUAGE_KEYS, MOTIONS, language_key
from services.series_voice_rooms import PRESETS

CODES = {key: code for code, key in LANGUAGE_KEYS.items()}
CARD_KINDS = ("title", "disclaimer", "end")


class ScriptError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems[:12]) + (f" (+{len(problems) - 12} more)" if len(problems) > 12 else ""))


def _language(key: str) -> str | None:
    """'es', 'spanish' or 'Spanish' -> 'spanish'."""
    lowered = str(key).strip().lower()
    return LANGUAGE_KEYS.get(lowered) or (lowered if lowered in CODES else None)


def _texts(value: Any) -> dict[str, Any]:
    """{'es': x, 'en': y} -> {'spanish': x, 'english': y}; a plain value counts for every language."""
    if isinstance(value, dict):
        return {lang: text for key, text in value.items() if (lang := _language(key))}
    return {"*": value} if value is not None else {}


def _pick(texts: dict[str, Any], language: str) -> Any:
    return texts.get(language, texts.get("*"))


def _line_text(line: Any, language: str) -> str:
    """A line's text in a language, '' when it has none."""
    if not isinstance(line, dict):
        return ""
    text = _pick(_texts({key: value for key, value in line.items() if _language(key)}), language)
    return text.strip() if isinstance(text, str) else ""


def _cast_entry(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        return {"characterId": raw}
    if isinstance(raw, (list, tuple)) and raw:
        entry = {"characterId": raw[0], "poseId": raw[1] if len(raw) > 1 else "base", "x": raw[2] if len(raw) > 2 else None}
        if len(raw) > 3 and isinstance(raw[3], dict):
            entry.update(raw[3])
    else:
        entry = dict(raw) if isinstance(raw, dict) else {}
    return {key: value for key, value in entry.items() if value is not None}


class Checker:
    """Everything the script names must exist in the series, its kits and its workspace."""

    def __init__(self, series: dict[str, Any], kits: dict[str, Any], files: set[str]) -> None:
        self.series, self.kits, self.files, self.problems = series, kits, files, []
        self.characters = {item["id"]: item for item in series.get("characters") or []}
        self.locations = {item["id"]: item for item in series.get("locations") or []}

    def character(self, cid: str, pose: str, where: str) -> None:
        character = self.characters.get(cid)
        if not character:
            self.problems.append(f"{where}: unknown character {cid}")
            return
        kit = self.kits.get(((character.get("voiceProfile") or {}).get("characterKitRef") or {}).get("id") or "")
        if not kit:
            self.problems.append(f"{where}: {cid} has no Character Kit")
        elif pose != "base" and pose not in (kit.get("poses") or {}):
            self.problems.append(f"{where}: {cid} has no pose {pose} (poses: base, {', '.join(sorted(kit.get('poses') or {}))})")

    def location(self, lid: str | None, variant: str | None, where: str) -> None:
        location = self.locations.get(lid or "")
        if not location:
            self.problems.append(f"{where}: unknown location {lid}")
        elif variant and variant not in {item.get("id") for item in location.get("variants") or []}:
            self.problems.append(f"{where}: location {lid} has no variant {variant}")

    def file(self, name: Any, where: str) -> None:
        if not isinstance(name, str) or name.replace("\\", "/").strip("/") not in self.files:
            self.problems.append(f"{where}: file {name} is not in the workspace")

    def voice(self, cid: str, language: str, where: str) -> None:
        """A line in a language version needs a voice designed for that language; the default voice has the wrong accent."""
        character = self.characters.get(cid) or {}
        kit = self.kits.get(((character.get("voiceProfile") or {}).get("characterKitRef") or {}).get("id") or "") or {}
        if kit and not (kit.get("voicesByLanguage") or {}).get(language):
            problem = f"{cid} has no {language} voice (voicesByLanguage); design one in the Character Kit"
            if problem not in self.problems:
                self.problems.append(problem)


class EpisodeScript:
    """Turn a script into the episode patch and its language versions; ``check`` lists every problem first."""

    def __init__(self, series: dict[str, Any], script: dict[str, Any], number: int, kits: dict[str, Any], files: set[str]) -> None:
        self.series, self.script, self.number = series, script, number
        self.original = language_key(series)
        self.checker = Checker(series, kits, files)
        self.scenes = {str(scene.get("id")): scene for scene in script.get("scenes") or [] if isinstance(scene, dict)}
        self.languages = self._languages()

    def _languages(self) -> list[str]:
        found = {lang for shot in self.script.get("shots") or [] if isinstance(shot, dict)
                 for line in shot.get("lines") or [] if isinstance(line, dict) for key in line if (lang := _language(key))}
        return [self.original, *sorted(found - {self.original})]

    def shot_id(self, index: int) -> str:
        return f"e{self.number}s{index:02d}"

    def check(self) -> None:
        if not self.script.get("shots"):
            self.checker.problems.append("the script has no shots")
        for key, scene in self.scenes.items():
            self.checker.location(scene.get("location"), scene.get("variant"), f"scene {key}")
        for index, shot in enumerate(self.script.get("shots") or []):
            self._check_shot(index, shot if isinstance(shot, dict) else {})
        if self.checker.problems:
            raise ScriptError(self.checker.problems)

    def _check_shot(self, index: int, shot: dict[str, Any]) -> None:
        where, check = f"shot {index} ({self.shot_id(index)})", self.checker
        if shot.get("scene") not in self.scenes:
            check.problems.append(f"{where}: unknown scene {shot.get('scene')}")
        if shot.get("location"):
            check.location(shot["location"], shot.get("variant"), where)
        if shot.get("framing", "wide") not in FRAMINGS:
            check.problems.append(f"{where}: framing must be one of {', '.join(FRAMINGS)}")
        if shot.get("voiceRoom") is not None and shot["voiceRoom"] not in PRESETS:
            check.problems.append(f"{where}: voiceRoom must be one of {', '.join(PRESETS)}")
        self._check_cast(shot, where)
        self._check_lines(shot, where)
        self._check_files(shot, where)
        self._check_effects(shot, where)
        self._check_layers(shot, where)

    def _check_cast(self, shot: dict[str, Any], where: str) -> None:
        cast = [_cast_entry(raw) for raw in shot.get("cast") or []]
        for entry in cast:
            self.checker.character(str(entry.get("characterId")), str(entry.get("poseId") or "base"), where)
            if entry.get("motion") not in (None, *MOTIONS):
                self.checker.problems.append(f"{where}: motion must be one of {', '.join(MOTIONS)}")
            if entry.get("enterGait") not in (None, *GAITS):
                self.checker.problems.append(f"{where}: enterGait must be one of {', '.join(GAITS)}")
        for kind in ("sfx", "fx"):
            for index, cue in enumerate(shot.get(kind) or []):
                if isinstance(cue, dict) and cue.get("anchor") == "enter":
                    self._check_entrance_cue(cue, cast, f"{where} {kind} {index}")

    def _check_entrance_cue(self, cue: dict[str, Any], cast: list[dict[str, Any]], where: str) -> None:
        """A cue on an entrance names a cast member of the shot (by index or id) who walks in."""
        ref, problems = cue.get("cast"), self.checker.problems
        if isinstance(ref, int) and not isinstance(ref, bool):
            named = cast[ref] if 0 <= ref < len(cast) else None
        else:
            named = next((entry for entry in cast if entry.get("characterId") == ref), None)
        if named is None:
            problems.append(f"{where}: anchor enter needs cast, an index into the shot's cast or one of its characters")
        elif named.get("enterFrom") not in ("left", "right"):
            problems.append(f"{where}: {named.get('characterId')} does not enter (give it enterFrom left or right)")

    def _check_lines(self, shot: dict[str, Any], where: str) -> None:
        for index, line in enumerate(shot.get("lines") or []):
            who = line.get("who") if isinstance(line, dict) else None
            if isinstance(line, dict) and line.get("voiceRoom") is not None and line["voiceRoom"] not in PRESETS:
                self.checker.problems.append(f"{where}: line {index} voiceRoom must be one of {', '.join(PRESETS)}")
            if who not in self.checker.characters:
                self.checker.problems.append(f"{where}: line {index} has an unknown speaker {who}")
            elif not _line_text(line, self.original):
                self.checker.problems.append(f"{where}: line {index} has no {self.original} text")
            else:
                for language in self.languages[1:]:
                    if _line_text(line, language):
                        self.checker.voice(str(who), language, f"{where} line {index}")

    def _check_files(self, shot: dict[str, Any], where: str) -> None:
        music = shot.get("music") if isinstance(shot.get("music"), dict) else {}
        named = [(name, "music") for key, name in music.items() if key == "file" or _language(key)]
        named += [((cue or {}).get("file"), "sfx") for cue in shot.get("sfx") or []]
        named += [(prop["file"], "prop") for prop in shot.get("props") or [] if isinstance(prop, dict) and prop.get("file")]
        for name, kind in named:
            self.checker.file(name, f"{where} {kind}")

    def _check_effects(self, shot: dict[str, Any], where: str) -> None:
        problems = self.checker.problems
        problems += [f"{where}: unknown effect {(cue or {}).get('kind')}" for cue in shot.get("fx") or [] if (cue or {}).get("kind") not in EFFECT_KINDS]
        if shot.get("card") and (shot["card"] or {}).get("kind") not in CARD_KINDS:
            problems.append(f"{where}: card kind must be one of {', '.join(CARD_KINDS)}")
        try:
            normalize_foley(shot.get("foley"))
        except ValueError as error:
            problems.append(f"{where}: {error}")
        if shot.get("kind") != "3d":
            return
        config = normalize_scene3d(shot.get("scene3d"))
        if not config:
            problems.append(f"{where}: a 3d shot needs scene3d with a template or a saved scene and its cast")
        elif config.get("scene"):
            self.checker.file(config["scene"], f"{where} scene3d")

    def _check_layers(self, shot: dict[str, Any], where: str) -> None:
        """Set layers (a shot's own list replaces its location's; [] turns them off) and the cast's depth among them."""
        try:
            found = layout_layers(shot, "")
        except ValueError as error:
            self.checker.problems.append(f"{where}: {error}")
            return
        assets = self.checker.series.get("assets") or {}
        for index, layer in enumerate(found.get("layers") or []):
            if layer.get("file"):
                self.checker.file(layer["file"], f"{where} layer {index}")
            elif (assets.get(layer["assetId"]) or {}).get("kind") not in ("image", "video"):
                self.checker.problems.append(f"{where}: layer {index} names {layer['assetId']}, not an image or video asset of the series")

    # Building -------------------------------------------------------------
    def _card(self, card: dict[str, Any], language: str) -> dict[str, str]:
        texts = _texts({key: value for key, value in card.items() if _language(key)})
        title, body = (list(_pick(texts, language) or ["", ""]) + ["", ""])[:2]
        return {"title": str(title), "body": str(body)}

    def _layout(self, shot: dict[str, Any]) -> dict[str, Any]:
        layout: dict[str, Any] = {"framing": shot.get("framing", "wide"), "camera": shot.get("camera", "static")}
        cast = [_cast_entry(raw) for raw in shot.get("cast") or []]
        if cast:
            layout["cast"] = cast
        for key in ("props", "sfx", "fx", "timing", "voiceRoom"):
            if shot.get(key):
                layout[key] = shot[key]
        layout.update(layout_layers(shot, "layout2d"))
        if isinstance(shot.get("card"), dict):
            layout["card"] = {"kind": shot["card"].get("kind"), **self._card(shot["card"], self.original)}
        music = shot.get("music") if isinstance(shot.get("music"), dict) else None
        if music:
            original = music.get(CODES.get(self.original, "")) or music.get(self.original) or music.get("file")
            layout["music"] = {"file": original, "volume": music.get("volume", 0.6), "start": music.get("start", 0)}
        return layout

    def _beats(self, sid: str, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"id": f"{sid}_b{n}", "characterId": line["who"], "emotion": line.get("emotion", ""), "delivery": line.get("delivery", ""),
                 "text": _line_text(line, self.original),
                 **({"pauseBefore": line["pauseBefore"]} if isinstance(line.get("pauseBefore"), (int, float)) else {}),
                 **({"voiceRoom": line["voiceRoom"]} if line.get("voiceRoom") is not None else {})}
                for n, line in enumerate(lines)]

    def _shot(self, index: int, shot: dict[str, Any]) -> dict[str, Any]:
        sid, scene, lines = self.shot_id(index), self.scenes[shot["scene"]], shot.get("lines") or []
        body = {"id": sid, "order": index + 1, "sceneId": f"e{self.number}_{shot['scene']}",
                "locationId": shot.get("location") or scene.get("location"),
                "productionMethod": "animation_3d" if shot.get("kind") == "3d" else "animation_2d",
                "framing": shot.get("framing", "wide"), "camera": shot.get("camera", "static"),
                "visibleCharacterIds": [_cast_entry(raw)["characterId"] for raw in shot.get("cast") or []],
                "speakingCharacterIds": sorted({line["who"] for line in lines}), "dialogueBeats": self._beats(sid, lines),
                "layout2d": self._layout(shot)}
        variant = shot.get("variant") or (None if shot.get("location") else scene.get("variant"))
        if variant:
            body["locationVariantId"] = variant
        if not lines:
            body["durationSeconds"] = float(shot.get("duration") or 5)
        if shot.get("kind") == "3d":
            body["scene3d"] = shot["scene3d"]
        if shot.get("foley") is not None:
            body["foley"] = normalize_foley(shot["foley"])
        return body

    def shots(self) -> list[dict[str, Any]]:
        return [self._shot(index, shot) for index, shot in enumerate(self.script.get("shots") or [])]

    def scene_list(self) -> list[dict[str, Any]]:
        return [{"id": f"e{self.number}_{key}", "order": index + 1, "locationId": scene.get("location"), "purpose": scene.get("purpose", ""),
                 "participatingCharacterIds": sorted({_cast_entry(raw)["characterId"] for shot in self.script.get("shots") or []
                                                      if shot.get("scene") == key for raw in shot.get("cast") or []})}
                for index, (key, scene) in enumerate(self.scenes.items())]

    def version(self, language: str) -> dict[str, Any]:
        dialogue, cards, music = {}, {}, {}
        for index, shot in enumerate(self.script.get("shots") or []):
            sid = self.shot_id(index)
            for n, line in enumerate(shot.get("lines") or []):
                if _line_text(line, language):
                    dialogue[f"{sid}_b{n}"] = _line_text(line, language)
            if isinstance(shot.get("card"), dict):
                cards[sid] = self._card(shot["card"], language)
            own = (shot.get("music") or {}).get(CODES.get(language, "")) if isinstance(shot.get("music"), dict) else None
            if own:
                music[sid] = own
        title = _pick(_texts(self.script.get("title")), language)
        return {"title": str(title or ""), "dialogue": dialogue, "cards": cards, "music": music}


def _episode_number(episodes: dict[str, Any], episode_id: str | None) -> int:
    if episode_id and episode_id not in episodes:
        raise ScriptError([f"unknown episode {episode_id}"])
    if episode_id:
        return int(episodes[episode_id].get("number") or 1)
    return max([episode.get("number") or 0 for episode in episodes.values()] + [0]) + 1


def _tool_caller(call: Callable[[str, dict], dict], workspace: str, series_id: str) -> Callable[[str, dict], dict]:
    def tool(name: str, data: dict[str, Any]) -> dict[str, Any]:
        reply = call(name, {"version": 1, "input": {"workspace": workspace, "series_id": series_id, **data}})
        if reply.get("_is_error"):
            raise ScriptError([f"{name}: {(reply.get('error') or {}).get('message')}"])
        return reply.get("result") or reply
    return tool


def apply_script(call: Callable[[str, dict], dict], read_series: Callable[[], dict], kits: dict[str, Any], files: set[str],
                 workspace: str, script: dict[str, Any], episode_id: str | None = None, check_only: bool = False) -> dict[str, Any]:
    """Check, then create (or rewrite) the episode and its language versions through the series tools."""
    series = read_series()
    number = _episode_number(series.get("episodesById") or {}, episode_id)
    built = EpisodeScript(series, script, number, kits, files)
    built.check()
    shots = built.shots()
    summary = {"number": number, "shots": [shot["id"] for shot in shots], "original": built.original, "languages": built.languages}
    if check_only:
        return {"checked": True, **summary}
    tool = _tool_caller(call, workspace, series["id"])
    title = str(_pick(_texts(script.get("title")), built.original) or f"Episode {number}")
    premise = str(_pick(_texts(script.get("premise")), built.original) or "")
    if not episode_id:
        episode_id = tool("series.episode.create", {"episode": {"title": title, "premise": premise}})["episode"]["id"]
    current = read_series()
    # The script is the whole episode: shots it no longer has are removed, and a shot whose content changed
    # loses its takes instead of keeping a video of other lines (replaceShots).
    tool("series.episode.update", {"episode_id": episode_id, "base_revision": current["revision"], "episode": {
        "title": title, "premise": premise, "script": built.scene_list(), "shots": shots, "replaceShots": True}})
    missing = {language: tool("series.episode.language_version.set", {
        "episode_id": episode_id, "language": language, **built.version(language)}).get("missingLines") or []
        for language in built.languages[1:]}
    removed = [shot["id"] for shot in (current["episodesById"][episode_id].get("shots") or []) if shot["id"] not in summary["shots"]]
    return {"episodeId": episode_id, **summary, "missingLines": missing, **({"removedShots": removed} if removed else {})}
