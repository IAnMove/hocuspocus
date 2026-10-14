"""Story Lab schema, stage normalisation and problem checks.

Moved verbatim from the launch runtime. ``_storyboard_page_problem`` still
calls ``_comic_page_problem``, which the comic batch owns. The full server
assigns that function onto this module before any request. This module does
not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import copy
import json
import re

# The comic page check stays in the launch runtime until the comic batch.
# The full server assigns the real function before any request.
_comic_page_problem = None


def _storyboard_page_problem(page, expected_panels: int = 1) -> str | None:
    """Validate video-specific fields after the shared comic shape is safe."""
    problem = _comic_page_problem(page, expected_panels)
    if problem:
        return problem
    for panel_index, panel in enumerate(page["panels"], 1):
        if not str(panel.get("imagePrompt") or "").strip():
            return f"shot {panel_index} has no first-frame image prompt"
        video_prompt = str(panel.get("videoPrompt") or "").strip()
        if not video_prompt:
            return f"shot {panel_index} has no video motion prompt"
        if len(video_prompt) > 1400:
            return f"shot {panel_index} video prompt is too long"
        try:
            duration = float(panel.get("durationSeconds"))
        except (TypeError, ValueError):
            return f"shot {panel_index} durationSeconds is not a number"
        if duration < 0.8 or duration > 20:
            return f"shot {panel_index} durationSeconds is outside 0.8–20 seconds"
        if panel.get("cameraMove") not in {
            "none", "push-in", "pull-out", "pan-left", "pan-right",
        }:
            return f"shot {panel_index} cameraMove is invalid"
        if panel.get("captions") or panel.get("dialogue") or panel.get("soundEffects"):
            return f"shot {panel_index} contains lettering instead of a clean video frame"
    return None

def _story_lab_schema(scope: str, project_type: str = "full_story") -> dict:
    """Return the strict editable Story Lab payload requested for one stage."""
    string = {"type": "string"}
    string_array = {"type": "array", "items": string, "maxItems": 12}
    location = {
        "type": "object",
        "properties": {
            "id": string, "name": string, "purpose": string, "description": string,
            "visualPrompt": string, "negativePrompt": string,
        },
        "required": [
            "id", "name", "purpose", "description", "visualPrompt", "negativePrompt",
        ],
        "additionalProperties": False,
    }
    world = {
        "type": "object",
        "properties": {
            "summary": string, "period": string, "geography": string,
            "society": string, "technology": string, "rules": string_array,
            "visualLanguage": string, "visualPrompt": string, "negativePrompt": string,
            "locations": {"type": "array", "items": location, "maxItems": 8},
        },
        "required": [
            "summary", "period", "geography", "society", "technology", "rules",
            "visualLanguage", "visualPrompt", "negativePrompt", "locations",
        ],
        "additionalProperties": False,
    }
    character = {
        "type": "object",
        "properties": {
            "id": string, "name": string, "role": string, "age": string,
            "pronouns": string, "personality": string, "desire": string,
            "need": string, "flaw": string, "conflict": string, "arc": string,
            "voice": string, "appearance": string, "wardrobe": string,
            "visualPrompt": string, "negativePrompt": string,
        },
        "required": [
            "id", "name", "role", "age", "pronouns", "personality", "desire",
            "need", "flaw", "conflict", "arc", "voice", "appearance", "wardrobe",
            "visualPrompt", "negativePrompt",
        ],
        "additionalProperties": False,
    }
    relationship = {
        "type": "object",
        "properties": {
            "id": string, "fromCharacterId": string, "toCharacterId": string,
            "label": string, "dynamic": string, "evolution": string,
        },
        "required": [
            "id", "fromCharacterId", "toCharacterId", "label", "dynamic", "evolution",
        ],
        "additionalProperties": False,
    }
    beat = {
        "type": "object",
        "properties": {
            "id": string, "stage": string, "title": string, "summary": string,
            "goal": string, "conflict": string, "turn": string,
        },
        "required": ["id", "stage", "title", "summary", "goal", "conflict", "turn"],
        "additionalProperties": False,
    }
    music_cue = {
        "type": "object",
        "properties": {
            "id": string,
            "kind": {"type": "string", "enum": ["world", "character", "story"]},
            "targetId": string,
            "title": string,
            "purpose": string,
            "referenceSong": string,
            "brief": string,
            "style": string,
            "lyrics": string,
            "instrumental": {"type": "boolean"},
            "durationSeconds": {"type": "integer", "minimum": 20, "maximum": 360},
        },
        "required": [
            "id", "kind", "targetId", "title", "purpose", "referenceSong",
            "brief", "style", "lyrics", "instrumental", "durationSeconds",
        ],
        "additionalProperties": False,
    }
    beat_minimum = 3 if project_type == "quick_video" else 4 if project_type == "music_video" else 6
    beat_maximum = 8 if project_type == "quick_video" else 10 if project_type == "music_video" else 12 if project_type == "trailer" else 14
    music_minimum = 1 if project_type == "music_video" else 4
    music_maximum = 1 if project_type == "music_video" else 16
    creative_brief = {
        "type": "object",
        "properties": {
            "generalIdea": string, "context": string, "performer": string,
            "musicStyle": string, "songStory": string, "subjects": string,
            "setting": string, "action": string,
            "quickFormat": {"type": "string", "enum": [
                "dialogue", "meme", "parody", "sketch", "viral", "announcement",
            ]},
            "durationSeconds": {"type": "integer", "minimum": 5, "maximum": 360},
        },
        "required": [
            "generalIdea", "context", "performer", "musicStyle", "songStory",
            "subjects", "setting", "action", "quickFormat", "durationSeconds",
        ],
        "additionalProperties": False,
    }
    properties = {
        "overview": {
            "type": "object",
            "properties": {
                "title": string, "creativeBrief": creative_brief,
                "language": string, "genre": string, "tone": string,
                "audience": string, "visualStyle": string,
                "characterVisualStyle": string,
                "enforceVisualStyle": {"type": "boolean"},
                "allowClipText": {"type": "boolean"},
                "musicVideoGenerationMode": {"type": "string", "enum": ["image_guided", "direct_video"]},
                "premise": string, "logline": string, "synopsis": string,
                "theme": string, "ending": string,
            },
            "required": [
                "title", "creativeBrief", "language", "genre", "tone", "audience",
                "visualStyle", "characterVisualStyle", "enforceVisualStyle",
                "allowClipText", "musicVideoGenerationMode", "premise", "logline",
                "synopsis", "theme", "ending",
            ],
            "additionalProperties": False,
        },
        "world": world,
        "characters": {"type": "array", "items": character, "minItems": 1, "maxItems": 12},
        "relationships": {"type": "array", "items": relationship, "maxItems": 24},
        "beats": {"type": "array", "items": beat, "minItems": beat_minimum, "maxItems": beat_maximum},
        "music": {
            "type": "object",
            "properties": {
                "cues": {"type": "array", "items": music_cue, "minItems": music_minimum, "maxItems": music_maximum},
            },
            "required": ["cues"],
            "additionalProperties": False,
        },
    }
    keys = list(properties) if scope == "all" else [scope]
    return {
        "type": "object",
        "properties": {key: properties[key] for key in keys},
        "required": keys,
        "additionalProperties": False,
    }

def _story_id_token(value) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().casefold()).strip("-")

def _normalize_story_stage_ids(
    result: dict,
    scope: str,
    project: dict,
    *,
    drop_unknown_relationships: bool = False,
) -> dict:
    """Repair harmless LLM omissions and ID drift before validation."""
    normalized = copy.deepcopy(result)
    if scope == "structure" and isinstance(normalized, dict):
        # Smaller/local providers occasionally ignore the top-level JSON
        # schema while still returning a useful visual sequence. Preserve
        # that work instead of spending another full call asking for the same
        # story under the literal ``beats`` key.
        raw_beats = normalized.get("beats")
        if isinstance(raw_beats, dict):
            raw_beats = next((
                raw_beats.get(key)
                for key in ("items", "beats", "moments", "scenes", "sequences")
                if isinstance(raw_beats.get(key), list)
            ), raw_beats)

        visual_sequence = normalized.get("visual_sequence_outline")
        visual_sequence = visual_sequence if isinstance(visual_sequence, list) else []
        plot_points = normalized.get("plot_points")
        plot_points = plot_points if isinstance(plot_points, list) else []
        if not isinstance(raw_beats, list):
            raw_beats = next((
                normalized.get(key)
                for key in ("structure", "moments", "scenes", "sequences")
                if isinstance(normalized.get(key), list)
            ), None)
        if not isinstance(raw_beats, list):
            raw_beats = visual_sequence or plot_points

        if isinstance(raw_beats, list):
            def field(item, *keys):
                if not isinstance(item, dict):
                    return str(item or "").strip()
                return next((
                    str(item.get(key) or "").strip()
                    for key in keys if str(item.get(key) or "").strip()
                ), "")

            beats = []
            used_ids: set[str] = set()
            total = len(raw_beats)
            for index, item in enumerate(raw_beats):
                visual = visual_sequence[index] if index < len(visual_sequence) else {}
                plot = plot_points[index] if index < len(plot_points) else {}
                source = item if isinstance(item, dict) else {"description": item}
                title = (
                    field(source, "title", "name", "focus")
                    or field(plot, "title", "name", "focus")
                    or field(visual, "title", "name", "focus")
                    or f"Moment {index + 1}"
                )
                summary = (
                    field(visual, "summary", "description", "action", "visual")
                    or field(source, "summary", "description", "action", "visual")
                    or field(plot, "summary", "description", "action")
                    or title
                )
                goal = (
                    field(source, "goal", "objective", "purpose", "focus")
                    or field(plot, "goal", "objective", "purpose", "focus")
                    or title
                )
                conflict = (
                    field(source, "conflict", "obstacle", "tension", "problem")
                    or field(plot, "conflict", "obstacle", "tension", "description")
                    or summary
                )
                turn = (
                    field(source, "turn", "change", "outcome", "result", "reversal")
                    or field(plot, "turn", "change", "outcome", "result", "description")
                    or field(visual, "turn", "change", "outcome", "description")
                    or summary
                )
                stage = field(source, "stage", "section", "phase")
                if not stage:
                    stage = (
                        "setup" if index == 0 else
                        "resolution" if index == total - 1 else
                        "climax" if total > 2 and index == total - 2 else
                        "rising action"
                    )
                candidate = _story_id_token(field(source, "id") or title) or f"beat-{index + 1}"
                base = candidate
                suffix = 2
                while candidate in used_ids:
                    candidate = f"{base}-{suffix}"
                    suffix += 1
                used_ids.add(candidate)
                beats.append({
                    "id": candidate,
                    "stage": stage,
                    "title": title,
                    "summary": summary,
                    "goal": goal,
                    "conflict": conflict,
                    "turn": turn,
                })
            normalized["beats"] = beats
        return normalized

    if scope == "world" and isinstance(normalized.get("world"), dict):
        locations = normalized["world"].get("locations")
        if not isinstance(locations, list):
            return normalized
        for location in locations:
            if not isinstance(location, dict):
                continue
            name = str(location.get("name") or "this location").strip()
            description = str(
                location.get("description") or location.get("purpose") or ""
            ).strip()
            # These are presentation-only fields.  When an otherwise useful
            # location omits them, deterministic defaults are safer and
            # cheaper than throwing away the whole world and asking the LLM
            # to regenerate it.  The user can still edit both fields later.
            if not isinstance(location.get("visualPrompt"), str) or not location["visualPrompt"].strip():
                location["visualPrompt"] = " ".join(part for part in (
                    name,
                    description,
                    "single coherent environment concept art, no text or labels",
                ) if part)
            if not isinstance(location.get("negativePrompt"), str) or not location["negativePrompt"].strip():
                location["negativePrompt"] = (
                    "text, lettering, captions, logos, UI, collage, contact sheet, grid"
                )
        return normalized

    if scope == "characters" and isinstance(normalized.get("characters"), list):
        used: set[str] = set()
        for index, character in enumerate(normalized["characters"]):
            if not isinstance(character, dict):
                continue
            candidate = str(character.get("id") or "").strip()
            if not candidate:
                candidate = _story_id_token(character.get("name")) or f"character-{index + 1}"
            base = candidate
            suffix = 2
            while candidate in used:
                candidate = f"{base}-{suffix}"
                suffix += 1
            character["id"] = candidate
            used.add(candidate)
        return normalized

    if scope == "music" and isinstance(normalized, dict):
        # Keep a useful song when a provider returns the right content under
        # a harmless wrapper alias (or returns the single music-video cue as
        # the music object itself).  This also lets us repair small internal
        # contradictions before a schema-repair call can discard the song.
        raw_music = normalized.get("music")
        if isinstance(raw_music, list):
            music = {"cues": raw_music}
        elif isinstance(raw_music, dict):
            music = raw_music
        else:
            music = {}

        cues = music.get("cues")
        if not isinstance(cues, list):
            cues = next((
                music.get(key)
                for key in ("songs", "tracks", "proposals", "items")
                if isinstance(music.get(key), list)
            ), None)
        if not isinstance(cues, list):
            single = next((
                music.get(key)
                for key in ("song", "track", "cue")
                if isinstance(music.get(key), dict)
            ), None)
            if single is None and any(
                key in music
                for key in ("lyrics", "songLyrics", "song_lyrics", "style", "musicStyle")
            ):
                single = music
            if isinstance(single, dict):
                cues = [single]
        if not isinstance(cues, list):
            cues = next((
                normalized.get(key)
                for key in ("cues", "songs", "tracks", "proposals")
                if isinstance(normalized.get(key), list)
            ), None)
        if not isinstance(cues, list):
            return normalized
        normalized["music"] = {"cues": cues}

        project_type = str(project.get("projectType") or "full_story").strip().lower()
        creative_brief = (
            project.get("creativeBrief")
            if isinstance(project.get("creativeBrief"), dict)
            else {}
        )
        project_music = (
            project.get("music") if isinstance(project.get("music"), dict) else {}
        )

        def cue_text(cue: dict, *keys: str) -> str:
            for key in keys:
                value = cue.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return ""

        def cue_lyrics(cue: dict) -> str:
            value = next((
                cue.get(key)
                for key in ("lyrics", "songLyrics", "song_lyrics", "text")
                if cue.get(key) not in (None, "")
            ), "")
            if isinstance(value, list):
                return "\n".join(str(line).strip() for line in value if str(line).strip())
            if isinstance(value, dict):
                tags = {
                    "intro": "Intro", "verse": "Verse", "verse1": "Verse",
                    "verse2": "Verse", "prechorus": "Pre Chorus",
                    "chorus": "Chorus", "hook": "Hook", "bridge": "Bridge",
                    "outro": "Outro",
                }
                sections = []
                for key, lines in value.items():
                    text = (
                        "\n".join(str(line).strip() for line in lines if str(line).strip())
                        if isinstance(lines, list) else str(lines or "").strip()
                    )
                    if not text:
                        continue
                    token = re.sub(r"[^a-z0-9]+", "", str(key).casefold())
                    sections.append(f"[{tags.get(token, 'Verse')}]\n\n{text}")
                return "\n\n".join(sections)
            return str(value or "").strip()

        characters = [
            character for character in project.get("characters", [])
            if isinstance(character, dict) and str(character.get("id") or "").strip()
        ]
        character_lookup = {}
        for character in characters:
            canonical = str(character["id"]).strip()
            for alias in (character.get("id"), character.get("name")):
                token = _story_id_token(alias)
                if token:
                    character_lookup[token] = canonical
        used: set[str] = set()
        for index, cue in enumerate(cues):
            if not isinstance(cue, dict):
                continue
            kind = str(cue.get("kind") or "").strip().lower()
            target = str(cue.get("targetId") or "").strip()
            if project_type == "music_video":
                # A non-empty lyrics field is authoritative for a vocal song;
                # providers sometimes copy an instrumental default despite
                # the explicit music-video contract.
                kind = "story"
                target = "story"
                cue["kind"] = kind
                cue["targetId"] = target
                cue["title"] = cue_text(cue, "title", "name", "songTitle", "song_title") or (
                    str(project.get("title") or "Main story song").strip()
                )
                story_direction = str(
                    creative_brief.get("songStory")
                    or project_music.get("brief")
                    or project.get("premise")
                    or "This song drives the visual story."
                ).strip()
                cue["purpose"] = cue_text(
                    cue, "purpose", "goal", "concept", "description"
                ) or story_direction
                cue["brief"] = cue_text(
                    cue, "brief", "description", "prompt", "songBrief", "song_brief"
                ) or story_direction
                cue["referenceSong"] = cue_text(
                    cue, "referenceSong", "reference_song", "reference", "inspiration"
                ) or "Original composition — No direct reference"
                style = cue_text(
                    cue, "style", "musicStyle", "music_style", "stylePrompt", "style_prompt"
                ) or str(
                    creative_brief.get("musicStyle")
                    or project_music.get("style")
                    or "cinematic story song, expressive lead vocal, dynamic original production"
                ).strip()
                cue["style"] = style[:300]
                lyrics = cue_lyrics(cue)[:3500].strip()
                if lyrics and not re.search(
                    r"^\[(Verse|Chorus|Hook)\]\s*$", lyrics, re.MULTILINE
                ):
                    if "\n" not in lyrics and "/" in lyrics:
                        lyrics = re.sub(r"\s*/\s*", "\n", lyrics)
                    lyrics = f"[Verse]\n\n{lyrics}"[:3500].rstrip()
                cue["lyrics"] = lyrics
                cue["instrumental"] = False
                requested_duration = creative_brief.get(
                    "durationSeconds", project_music.get("targetDurationSeconds")
                )
                duration = (
                    requested_duration
                    if requested_duration not in (None, "")
                    else cue.get("durationSeconds", cue.get("duration_seconds"))
                )
                if isinstance(duration, bool):
                    duration = None
                try:
                    duration = int(float(duration))
                except (TypeError, ValueError):
                    duration = creative_brief.get(
                        "durationSeconds", project_music.get("targetDurationSeconds", 90)
                    )
                    try:
                        duration = int(float(duration))
                    except (TypeError, ValueError):
                        duration = 90
                cue["durationSeconds"] = max(20, min(360, duration))
            elif kind == "character":
                target = character_lookup.get(_story_id_token(target), target)
            elif kind == "world":
                target = "world"
            cue["targetId"] = target
            candidate = _story_id_token(cue.get("id")) or f"music-{kind or 'cue'}-{index + 1}"
            base = candidate
            suffix = 2
            while candidate in used:
                candidate = f"{base}-{suffix}"
                suffix += 1
            cue["id"] = candidate
            used.add(candidate)
        return normalized

    if scope != "relationships" or not isinstance(normalized.get("relationships"), list):
        return normalized
    characters = [
        character for character in project.get("characters", [])
        if isinstance(character, dict) and str(character.get("id") or "").strip()
    ]
    canonical_ids = {str(character["id"]).strip() for character in characters}
    lookup: dict[str, str] = {}
    for character in characters:
        canonical = str(character["id"]).strip()
        for alias in (character.get("id"), character.get("name")):
            stripped = str(alias or "").strip()
            if stripped:
                lookup.setdefault(stripped.casefold(), canonical)
                token = _story_id_token(stripped)
                if token:
                    lookup.setdefault(token, canonical)

    def resolve(value) -> str:
        stripped = str(value or "").strip()
        if stripped in canonical_ids:
            return stripped
        return lookup.get(stripped.casefold()) or lookup.get(_story_id_token(stripped)) or stripped

    relationships = []
    used_ids: set[str] = set()
    for index, relationship in enumerate(normalized["relationships"]):
        if not isinstance(relationship, dict):
            relationships.append(relationship)
            continue
        relationship["fromCharacterId"] = resolve(relationship.get("fromCharacterId"))
        relationship["toCharacterId"] = resolve(relationship.get("toCharacterId"))
        relation_id = str(relationship.get("id") or "").strip()
        if not relation_id:
            relation_id = f"relationship-{index + 1}"
        base = relation_id
        suffix = 2
        while relation_id in used_ids:
            relation_id = f"{base}-{suffix}"
            suffix += 1
        relationship["id"] = relation_id
        used_ids.add(relation_id)
        valid = (
            relationship["fromCharacterId"] in canonical_ids
            and relationship["toCharacterId"] in canonical_ids
            and relationship["fromCharacterId"] != relationship["toCharacterId"]
        )
        if valid or not drop_unknown_relationships:
            relationships.append(relationship)
    normalized["relationships"] = relationships
    return normalized

def _story_stage_problem(result: dict, scope: str, project: dict) -> str | None:
    project_type = str(project.get("projectType") or "full_story").strip().lower()
    if not isinstance(result, dict):
        return "response root is not a JSON object"
    key = "beats" if scope == "structure" else scope
    value = result.get(key)
    if scope in {"overview", "world", "music"} and not isinstance(value, dict):
        return f"{key} is not an object"
    if scope in {"characters", "relationships", "structure"} and not isinstance(value, list):
        return f"{key} is not an array"
    required = {
        "overview": {
            "title", "creativeBrief", "language", "genre", "tone", "audience",
            "visualStyle", "characterVisualStyle", "enforceVisualStyle",
            "allowClipText", "musicVideoGenerationMode", "premise", "logline",
            "synopsis", "theme", "ending",
        },
        "world": {
            "summary", "period", "geography", "society", "technology", "rules",
            "visualLanguage", "visualPrompt", "negativePrompt", "locations",
        },
        "characters": {
            "id", "name", "role", "age", "pronouns", "personality", "desire",
            "need", "flaw", "conflict", "arc", "voice", "appearance", "wardrobe",
            "visualPrompt", "negativePrompt",
        },
        "relationships": {
            "id", "fromCharacterId", "toCharacterId", "label", "dynamic", "evolution",
        },
        "structure": {"id", "stage", "title", "summary", "goal", "conflict", "turn"},
    }
    if scope == "overview":
        missing = required["overview"] - set(value)
        if missing:
            return f"overview is missing {', '.join(sorted(missing))}"
        string_fields = required["overview"] - {
            "creativeBrief", "enforceVisualStyle", "allowClipText",
        }
        for field in string_fields:
            if not isinstance(value.get(field), str):
                return f"overview field {field} is not a string"
        if not isinstance(value.get("enforceVisualStyle"), bool) or not isinstance(value.get("allowClipText"), bool):
            return "overview style/text flags must be boolean"
        generated_brief = value.get("creativeBrief")
        if not isinstance(generated_brief, dict):
            return "overview creativeBrief is not an object"
        brief_fields = {
            "generalIdea", "context", "performer", "musicStyle", "songStory",
            "subjects", "setting", "action", "quickFormat", "durationSeconds",
        }
        brief_missing = brief_fields - set(generated_brief)
        if brief_missing:
            return f"overview creativeBrief is missing {', '.join(sorted(brief_missing))}"
        if any(not isinstance(generated_brief.get(field), str) for field in brief_fields - {"durationSeconds"}):
            return "overview creativeBrief contains a non-string field"
        duration = generated_brief.get("durationSeconds")
        if not isinstance(duration, int) or isinstance(duration, bool) or not 5 <= duration <= 360:
            return "overview creativeBrief durationSeconds is outside 5–360"
        return None
    if scope == "world":
        missing = required["world"] - set(value)
        if missing:
            return f"world is missing {', '.join(sorted(missing))}"
        if not isinstance(value.get("rules"), list) or not isinstance(value.get("locations"), list):
            return "world rules and locations must be arrays"
        if len(value["rules"]) > 12 or not all(isinstance(item, str) for item in value["rules"]):
            return "world rules must contain at most twelve strings"
        if len(value["locations"]) > 8:
            return "world has more than eight locations"
        for field in required["world"] - {"rules", "locations"}:
            if not isinstance(value.get(field), str):
                return f"world field {field} is not a string"
        for index, location in enumerate(value["locations"]):
            if not isinstance(location, dict):
                return f"location {index + 1} is not an object"
            location_missing = {
                "id", "name", "purpose", "description", "visualPrompt", "negativePrompt",
            } - set(location)
            if location_missing:
                return (
                    f"location {index + 1} is missing "
                    f"{', '.join(sorted(location_missing))}"
                )
            for field in {
                "id", "name", "purpose", "description", "visualPrompt", "negativePrompt",
            }:
                if not isinstance(location.get(field), str):
                    return f"location {index + 1} field {field} is not a string"
        return None
    if scope == "music":
        cues = value.get("cues")
        if not isinstance(cues, list):
            return "music cues is not an array"
        character_ids = {
            str(item.get("id") or "").strip()
            for item in project.get("characters", []) if isinstance(item, dict)
        }
        expected_count = 1 if project_type == "music_video" else len(character_ids) + 4
        if len(cues) != expected_count:
            return f"music must contain exactly {expected_count} cues"
        required_cue = {
            "id", "kind", "targetId", "title", "purpose", "referenceSong",
            "brief", "style", "lyrics", "instrumental", "durationSeconds",
        }
        ids = []
        for index, cue in enumerate(cues):
            if not isinstance(cue, dict):
                return f"music cue {index + 1} is not an object"
            missing = required_cue - set(cue)
            if missing:
                return f"music cue {index + 1} is missing {', '.join(sorted(missing))}"
            for field in required_cue - {"instrumental", "durationSeconds"}:
                if not isinstance(cue.get(field), str):
                    return f"music cue {index + 1} field {field} is not a string"
            if not isinstance(cue.get("instrumental"), bool):
                return f"music cue {index + 1} instrumental is not a boolean"
            duration = cue.get("durationSeconds")
            if not isinstance(duration, int) or isinstance(duration, bool) or not 20 <= duration <= 360:
                return f"music cue {index + 1} durationSeconds is outside 20–360"
            style = cue["style"].strip()
            lyrics = cue["lyrics"].strip()
            if not 10 <= len(style) <= 300:
                return f"music cue {index + 1} style must contain 10–300 characters"
            if not cue["referenceSong"].strip():
                return f"music cue {index + 1} needs an editable reference song"
            if cue["instrumental"] and lyrics:
                return f"instrumental music cue {index + 1} must have empty lyrics"
            if not cue["instrumental"]:
                if not 10 <= len(lyrics) <= 3500:
                    return f"vocal music cue {index + 1} lyrics must contain 10–3500 characters"
                if not re.search(r"^\[(Verse|Chorus|Hook)\]\s*$", lyrics, re.MULTILINE):
                    return f"vocal music cue {index + 1} needs supported structural tags"
            ids.append(cue["id"])
        if len(ids) != len(set(ids)):
            return "music contains duplicate IDs"
        if project_type == "music_video":
            cue = cues[0]
            if cue["kind"] != "story" or cue["targetId"] != "story":
                return "music-video mode needs one story song"
            if cue["instrumental"]:
                return "the music-video song must include vocals"
            return None
        world_cues = [cue for cue in cues if cue["kind"] == "world" and cue["targetId"] == "world"]
        character_targets = {
            cue["targetId"] for cue in cues if cue["kind"] == "character"
        }
        story_cues = [cue for cue in cues if cue["kind"] == "story"]
        if len(world_cues) != 1:
            return "music needs exactly one world ambience cue"
        if not world_cues[0]["instrumental"]:
            return "the world ambience cue must be instrumental"
        if character_targets != character_ids or len(character_targets) != len([
            cue for cue in cues if cue["kind"] == "character"
        ]):
            return "music needs exactly one presentation cue per character ID"
        if len(story_cues) != 3:
            return "music needs exactly three story songs"
        if any(cue["instrumental"] for cue in story_cues):
            return "the three story songs must include vocals"
        return None
    if not value and scope != "relationships":
        return f"{key} is empty"
    limits = {
        "characters": (1, 12),
        "relationships": (0, 24),
        "structure": (
            (3, 8) if project_type == "quick_video"
            else (4, 10) if project_type == "music_video"
            else (6, 12) if project_type == "trailer"
            else (6, 14)
        ),
    }
    minimum, maximum = limits[scope]
    if len(value) < minimum or len(value) > maximum:
        return f"{key} must contain between {minimum} and {maximum} items"
    item_required = required[scope]
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            return f"{key} item {index + 1} is not an object"
        missing = item_required - set(item)
        if missing:
            return f"{key} item {index + 1} is missing {', '.join(sorted(missing))}"
        for field in item_required:
            if not isinstance(item.get(field), str):
                return f"{key} item {index + 1} field {field} is not a string"
    ids = [item.get("id") for item in value]
    if len(ids) != len(set(ids)):
        return f"{key} contains duplicate IDs"
    if scope == "relationships":
        character_ids = {
            str(item.get("id") or "") for item in project.get("characters", [])
            if isinstance(item, dict)
        }
        for item in value:
            if (
                item.get("fromCharacterId") not in character_ids
                or item.get("toCharacterId") not in character_ids
            ):
                return "a relationship references an unknown character ID"
    return None

def _story_project_prompt_context(project: dict, scope: str) -> str:
    """Return bounded, valid JSON with editorial facts but no heavy runtime data."""
    from services.writing_guide import accepted_guidance
    overview_keys = (
        "title", "projectType", "creativeBrief", "language", "spokenLanguage", "languageIntent", "locationVariety",
        "protagonistConsistency", "protagonistCharacterId", "genre", "tone", "audience", "premise",
        "logline", "synopsis", "theme", "ending", "visualStyle",
        "characterVisualStyle", "enforceVisualStyle", "allowClipText",
    )
    compact = {key: project.get(key) for key in overview_keys if key in project}
    compact["writingDecisions"] = accepted_guidance(project)
    # Characters are useful grounding for every downstream phase and are
    # required for relationship IDs. The active section keeps its full facts;
    # other stages only need a concise identity summary.
    raw_characters = project.get("characters")
    if isinstance(raw_characters, list):
        if scope == "characters":
            compact["characters"] = raw_characters
        else:
            compact["characters"] = [
                {
                    key: item.get(key)
                    for key in ("id", "name", "role", "personality", "desire", "arc", "appearance")
                    if key in item
                }
                for item in raw_characters if isinstance(item, dict)
            ]
    if scope in {"world", "relationships", "structure", "music"} and isinstance(project.get("world"), dict):
        compact["world"] = project["world"]
    if scope in {"relationships", "structure", "music"} and isinstance(project.get("relationships"), list):
        compact["relationships"] = project["relationships"]
    if scope in {"structure", "music"} and isinstance(project.get("beats"), list):
        compact["beats"] = project["beats"]

    def bounded(value, string_limit: int):
        if isinstance(value, str):
            return value if len(value) <= string_limit else value[:string_limit] + "…"
        if isinstance(value, list):
            return [bounded(item, string_limit) for item in value[:24]]
        if isinstance(value, dict):
            return {
                str(key): bounded(item, string_limit)
                for key, item in value.items()
                if key not in {
                    "assets", "productions", "approvals", "sectionVersions",
                    "visualJobs", "packedAssets", "approval",
                }
            }
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return str(value)

    bounded_context = bounded(compact, 2000)
    encoded = json.dumps(bounded_context, ensure_ascii=False)
    if len(encoded) > 24000:
        encoded = json.dumps(bounded(compact, 600), ensure_ascii=False)
    return encoded

def _story_checkpoint_request(body: dict) -> dict:
    """Keep durable writing checkpoints small and free of editor/runtime history."""
    request = copy.deepcopy(body)
    project = request.get("project")
    if isinstance(project, dict):
        for key in (
            "assets", "productions", "approvals", "sectionVersions",
            "visualJobs", "packedAssets",
        ):
            project.pop(key, None)
        for character in project.get("characters", []):
            if isinstance(character, dict):
                character.pop("referenceAssetIds", None)
                character.pop("primaryReferenceAssetId", None)
                character.pop("approval", None)
        world = project.get("world")
        if isinstance(world, dict):
            world.pop("referenceAssetIds", None)
            for location in world.get("locations", []):
                if isinstance(location, dict):
                    location.pop("referenceAssetIds", None)
        music = project.get("music")
        if isinstance(music, dict):
            music.pop("candidates", None)
            music.pop("selectedCandidateId", None)
            music.pop("coverReferenceFilename", None)
            for cue in music.get("cues", []):
                if isinstance(cue, dict):
                    cue.pop("candidates", None)
                    cue.pop("selectedCandidateId", None)
    return request

def _story_resume_request(request: dict, override: dict | None) -> dict:
    """Apply an explicit current writing profile to a durable resume request."""
    updated = copy.deepcopy(request)
    if not isinstance(override, dict):
        return updated
    provider = str(override.get("writingProvider") or "").strip()
    if not provider:
        return updated
    updated["writingProvider"] = provider
    updated["writingModel"] = str(override.get("writingModel") or "").strip()
    updated["writingBaseUrl"] = str(override.get("writingBaseUrl") or "").strip()
    project = updated.get("project")
    if isinstance(project, dict):
        profile = project.get("provider") if isinstance(project.get("provider"), dict) else {}
        project["provider"] = {
            **profile,
            "writingProvider": updated["writingProvider"],
            "writingModel": updated["writingModel"],
            "writingBaseUrl": updated["writingBaseUrl"],
        }
    return updated

def _merge_story_stage_project(project: dict, result: dict) -> dict:
    merged = copy.deepcopy(project)
    overview = result.get("overview")
    if isinstance(overview, dict):
        merged.update(overview)
    for key in ("world", "characters", "relationships"):
        if key in result:
            merged[key] = copy.deepcopy(result[key])
    if "structure" in result:
        merged["beats"] = copy.deepcopy(result["structure"])
    if isinstance(result.get("music"), dict):
        music = merged.get("music") if isinstance(merged.get("music"), dict) else {}
        merged["music"] = {
            **music,
            "cues": copy.deepcopy(result["music"].get("cues") or []),
        }
    return merged
