"""
Music Video Planner — creates a ProductionPlan from song analysis data.

Inputs: song audio, transcript/lyrics, beat map, section labels,
performer map, optional reference image, user scene concept.

Outputs: ProductionPlan with ShotPlan objects (NOT final prompts).
"""

from __future__ import annotations
import json
import os
import re
from typing import Optional, Any

from ..schema import (
    ProductionPlan, ShotPlan, CharacterProfile, ReferenceAssets,
    AssetRef, SubjectRef, DialogueBeat, CameraPlan, AudioPlan,
    SpeakerMapEntry,
)
from ..policies import (
    build_camera_style_block,
    build_character_rules_block,
    build_character_visual_style_contract,
    build_visible_text_contract,
)
from .base import BasePlanner


# ── Section-based visual strategy ────────────────────────────────────

_SECTION_VISUAL_STRATEGY = {
    "intro": {
        "camera_default": "wide establishing shot",
        "movement_intensity": "subtle",
        "energy": "building",
        "hints": "atmospheric, slow reveal, moody lighting, set the tone",
    },
    "verse": {
        "camera_default": "medium shot",
        "movement_intensity": "subtle",
        "energy": "steady",
        "hints": "storytelling, character focus, steady camera, intimate",
    },
    "pre-chorus": {
        "camera_default": "medium close-up",
        "movement_intensity": "moderate",
        "energy": "building",
        "hints": "build anticipation, camera approaches, lighting grows, prepare the hook",
    },
    "chorus": {
        "camera_default": "dynamic angle",
        "movement_intensity": "dynamic",
        "energy": "peak",
        "hints": "bold energy, wide and close-up mix, confident movement",
    },
    "bridge": {
        "camera_default": "unique angle",
        "movement_intensity": "moderate",
        "energy": "contrasting",
        "hints": "change of scenery, dreamy or surreal, unexpected perspective",
    },
    "outro": {
        "camera_default": "wide shot",
        "movement_intensity": "subtle",
        "energy": "fading",
        "hints": "pulling back, reflective, fading light, resolution",
    },
    "instrumental": {
        "camera_default": "sweeping shot",
        "movement_intensity": "moderate",
        "energy": "atmospheric",
        "hints": "environment focus, dramatic sweep, textures, abstract visuals",
    },
}


_DEFAULT_TREATMENT = {
    "generation_mode": "image_guided",
    "direct_video_master_prompt": (
        "Maintain one coherent visual language across every clip. Keep recurring characters, "
        "materials, palette, lighting and rendering technique consistent. Do not introduce "
        "another medium or visual style unless it is explicitly requested."
    ),
    "mode": "hybrid",
    "performer_presence": 60,
    "lip_sync": "frequent",
    "recurring_sets": ["main performance set", "story world", "contrast set"],
    "wardrobe": "",
    "palette": "",
    "camera_language": "controlled cinematic movement with energetic chorus coverage",
    "recurring_motif": "",
    "chorus_signature": "return to the main performance set with the boldest lighting and direct-to-camera delivery",
    "surrealism": 35,
    "forbidden_elements": "",
}

_COVERAGE_SEQUENCE = (
    "hero wide performance",
    "direct-to-camera medium performance",
    "beauty close-up",
    "moving profile coverage",
    "low-angle performance",
    "detail insert",
)


def _treatment_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[\n,;]+", str(value or "")) if item.strip()]


def normalize_music_video_treatment(value: Any) -> dict[str, Any]:
    """Return a compact, backwards-compatible music-video treatment."""
    raw = value if isinstance(value, dict) else {}
    mode = str(raw.get("mode") or _DEFAULT_TREATMENT["mode"]).strip().lower()
    if mode not in {"performance", "narrative", "hybrid", "abstract"}:
        mode = "hybrid"
    default_presence = {"performance": 85, "narrative": 30, "hybrid": 60, "abstract": 15}[mode]
    try:
        performer_presence = int(raw.get("performer_presence", default_presence))
    except (TypeError, ValueError):
        performer_presence = default_presence
    lip_sync = str(raw.get("lip_sync") or _DEFAULT_TREATMENT["lip_sync"]).strip().lower()
    if lip_sync not in {"frequent", "occasional", "none"}:
        lip_sync = "frequent"
    try:
        surrealism = int(raw.get("surrealism", _DEFAULT_TREATMENT["surrealism"]))
    except (TypeError, ValueError):
        surrealism = int(_DEFAULT_TREATMENT["surrealism"])
    sets = _treatment_list(raw.get("recurring_sets")) or list(_DEFAULT_TREATMENT["recurring_sets"])
    generation_mode = str(
        raw.get("generation_mode") or _DEFAULT_TREATMENT["generation_mode"]
    ).strip().lower()
    if generation_mode not in {"image_guided", "direct_video"}:
        generation_mode = "image_guided"
    direct_video_master_prompt = str(
        raw.get("direct_video_master_prompt")
        or _DEFAULT_TREATMENT["direct_video_master_prompt"]
    ).strip()
    return {
        "generation_mode": generation_mode,
        "direct_video_master_prompt": direct_video_master_prompt,
        "mode": mode,
        "performer_presence": max(0, min(100, performer_presence)),
        "lip_sync": lip_sync,
        "recurring_sets": sets[:5],
        "wardrobe": str(raw.get("wardrobe") or "").strip(),
        "palette": str(raw.get("palette") or "").strip(),
        "camera_language": str(raw.get("camera_language") or _DEFAULT_TREATMENT["camera_language"]).strip(),
        "recurring_motif": str(raw.get("recurring_motif") or "").strip(),
        "chorus_signature": str(raw.get("chorus_signature") or _DEFAULT_TREATMENT["chorus_signature"]).strip(),
        "surrealism": max(0, min(100, surrealism)),
        "forbidden_elements": str(raw.get("forbidden_elements") or "").strip(),
    }


def build_music_video_coverage(clips: list[dict], treatment: dict[str, Any]) -> list[dict[str, Any]]:
    """Assign recurring sets and a balanced coverage role before prompting.

    This makes recurrence deliberate: choruses return to one signature setup,
    while verses vary shot size without inventing an unrelated world per line.
    """
    count = len(clips)
    desired = round(count * int(treatment["performer_presence"]) / 100)
    priorities: list[tuple[int, int]] = []
    for index, clip in enumerate(clips):
        section = str(clip.get("label") or "verse").lower()
        score = {
            "chorus": 100,
            "pre-chorus": 80,
            "verse": 65,
            "bridge": 45,
            "intro": 25,
            "outro": 20,
            "instrumental": 5,
        }.get(section, 50)
        # Stable spacing prevents all selected performance clips clustering.
        priorities.append((score - (index % 3) * 3, index))
    performance_indexes = {
        index for _score, index in sorted(priorities, reverse=True)[:desired]
    }
    sets = treatment["recurring_sets"]
    coverage: list[dict[str, Any]] = []
    for index, clip in enumerate(clips):
        section = str(clip.get("label") or "verse").lower()
        performer = index in performance_indexes
        if performer:
            scene_type = "performance"
        elif treatment["mode"] == "abstract" or section == "instrumental":
            scene_type = "abstract"
        elif section in {"intro", "outro"}:
            scene_type = "atmospheric"
        else:
            scene_type = "narrative"
        if section == "chorus":
            recurring_set = sets[0]
        elif section == "bridge":
            recurring_set = sets[-1]
        else:
            recurring_set = sets[min(1 + (index % max(1, len(sets) - 1)), len(sets) - 1)] if len(sets) > 1 else sets[0]
        coverage.append({
            "scene_type": scene_type,
            "performer_present": performer,
            "recurring_set": recurring_set,
            "coverage": _COVERAGE_SEQUENCE[index % len(_COVERAGE_SEQUENCE)],
            "section_rule": _SECTION_VISUAL_STRATEGY.get(section, _SECTION_VISUAL_STRATEGY["verse"])["hints"],
            "reuse_chorus_signature": section == "chorus",
        })
    return coverage

_MUSIC_IMAGE_FIELDS = frozenset({
    "image_source",
    "image_prompt",
    "visual_changes",
    "keyframe_prompts",
})

_MUSIC_SHOT_PROPERTIES = {
    "scene_goal": {"type": "string"},
    "scene_type": {"type": "string"},
    "subjects_on_screen": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "character_id": {"type": "string"},
                "speaker_name": {"type": "string"},
                "visual_description": {"type": "string"},
                "position_or_relation": {"type": "string"},
            },
            "required": ["visual_description"],
            "additionalProperties": False,
        },
    },
    "spatial_setup": {"type": "string"},
    "environment": {"type": "string"},
    "visual_style": {"type": "string"},
    "lighting": {"type": "string"},
    "mood": {"type": "string"},
    "action_beats": {"type": "array", "items": {"type": "string"}},
    "camera_plan": {
        "type": "object",
        "properties": {
            "framing": {"type": "string"},
            "angle": {"type": "string"},
            "movement": {"type": "string"},
            "movement_intensity": {"type": "string"},
            "lens_feel": {"type": "string"},
        },
        "required": ["framing"],
        "additionalProperties": False,
    },
    "ending_beat": {"type": "string"},
    "image_source": {"type": "string"},
    "image_prompt": {"type": "string"},
    "visual_changes": {"type": "array", "items": {"type": "string"}},
    "video_prompt": {"type": "string"},
    "keyframe_prompts": {"type": "array", "items": {"type": "string"}},
    "window_prompts": {"type": "array", "items": {"type": "string"}},
}


def _music_shot_schema(count: int, *, include_image_fields: bool) -> dict:
    properties = {
        key: value
        for key, value in _MUSIC_SHOT_PROPERTIES.items()
        if include_image_fields or key not in _MUSIC_IMAGE_FIELDS
    }
    required = [
        "scene_goal",
        "scene_type",
        "subjects_on_screen",
        "environment",
        "visual_style",
        "lighting",
        "mood",
        "action_beats",
        "camera_plan",
        "ending_beat",
        "image_source",
        "image_prompt",
        "visual_changes",
        "video_prompt",
        "window_prompts",
    ]
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": [field for field in required if field in properties],
            "additionalProperties": False,
        },
        "minItems": max(1, count),
        "maxItems": max(1, count),
    }


def _discard_unused_image_fields(shot_dicts: list[dict]) -> list[dict]:
    for shot in shot_dicts:
        if isinstance(shot, dict):
            for field in _MUSIC_IMAGE_FIELDS:
                shot.pop(field, None)
    return shot_dicts


# ── Performer Map Parsing ────────────────────────────────────────────

_PRONOUN_MAP = {
    "he": "man", "she": "woman", "him": "man", "her": "woman",
    "guy": "man", "girl": "woman", "boy": "man",
    "male": "man", "female": "woman",
    "rapper": "man", "singer": "woman",
}

_SECTION_ALIASES = {
    "verse": ["verse", "verses", "rap", "raps"],
    "chorus": ["chorus", "choruses", "hook", "hooks", "sing", "sings"],
    "bridge": ["bridge", "bridges"],
    "intro": ["intro", "introduction"],
    "outro": ["outro", "ending"],
    "instrumental": ["instrumental", "break"],
}


def _parse_performer_map(scene_description: str) -> dict[str, str]:
    """Extract section→performer mapping from natural language scene description.

    Returns: {"verse": "the man in the dark jacket", "chorus": "the woman", ...}
    """
    result = {}
    if not scene_description:
        return result

    text = scene_description.lower()
    # Pattern: "the man raps the verses", "chorus by the woman", etc.
    for section, aliases in _SECTION_ALIASES.items():
        for alias in aliases:
            patterns = [
                rf'(\bthe\s+\w+(?:\s+\w+)?)\s+(?:raps?|sings?|performs?|does?|handles?)\s+(?:the\s+)?{alias}',
                rf'{alias}\s+(?:by|from|performed by|sung by|rapped by)\s+(\bthe\s+\w+(?:\s+\w+)?)',
                rf'(\bthe\s+\w+(?:\s+\w+)?)\s+(?:is|are)\s+(?:on|in|doing)\s+(?:the\s+)?{alias}',
            ]
            for pat in patterns:
                m = re.search(pat, text)
                if m:
                    performer = m.group(1).strip()
                    # Normalize pronouns
                    for pronoun, replacement in _PRONOUN_MAP.items():
                        performer = re.sub(rf'\b{pronoun}\b', replacement, performer)
                    result[section] = performer
                    break
    return result


class MusicVideoPlanner(BasePlanner):
    skill_type = "music_video"

    def plan(
        self,
        clips: list[dict],
        scene_description: str,
        lyrics: Optional[list[dict]] = None,
        bpm: float = 120.0,
        reference_image_path: Optional[str] = None,
        speaker_mappings: Optional[dict] = None,
        characters: Optional[list[dict]] = None,
        **kwargs,
    ) -> ProductionPlan:
        """Create a ProductionPlan for a music video.

        Args:
            clips: List of PlannedClip dicts with beat_count, duration_frames, label, start, end, etc.
            scene_description: User's scene concept/vibe/setting.
            lyrics: Transcribed lyrics with optional speaker tags.
            bpm: Song tempo.
            reference_image_path: Path to reference photo (optional).
            speaker_mappings: {speaker_id: {name, role}} from UI.
            characters: List of character dicts [{name, description}].
        """
        video_model = str(kwargs.get("video_model") or "")
        shot_image_policy = str(kwargs.get("shot_image_policy") or "")
        treatment = normalize_music_video_treatment(kwargs.get("music_video_treatment"))
        direct_video = treatment["generation_mode"] == "direct_video"
        self._uses_generated_shot_images = not direct_video and shot_image_policy not in {
            "prompt_only",
            "direct_references",
        }
        self._preserve_video_character_names = (
            video_model.lower().startswith("minimax_h3")
            and not self._uses_generated_shot_images
        )
        performer_map = _parse_performer_map(scene_description)
        has_reference = bool(reference_image_path) and not direct_video
        if direct_video:
            reference_image_path = None
        coverage_plan = build_music_video_coverage(clips, treatment)

        # Normalize speaker_mappings: frontend sends list, we need dict
        if isinstance(speaker_mappings, list):
            sm_dict: dict = {}
            for entry in speaker_mappings:
                if isinstance(entry, dict):
                    sid = entry.get("speakerId") or entry.get("speaker_id", "")
                    if sid:
                        sm_dict[sid] = {"name": entry.get("name", ""), "role": entry.get("role", "")}
            speaker_mappings = sm_dict

        # Build character profiles
        char_profiles = self._build_characters(characters, speaker_mappings, lyrics, performer_map)

        # Build speaker lookup
        speaker_names = self._build_speaker_names(speaker_mappings, lyrics)

        # Build reference assets
        ref_assets = ReferenceAssets(
            start_image=AssetRef(id="ref_image", type="image", uri=reference_image_path) if has_reference else None,
            lyrics=self._format_lyrics_text(lyrics) if lyrics else None,
            speaker_map=[
                SpeakerMapEntry(speaker_id=sid, name=info.get("name", ""), voice_description=info.get("role", ""))
                for sid, info in (speaker_mappings or {}).items()
            ] if speaker_mappings else None,
        )

        # Build clip context for LLM
        clip_contexts = self._build_clip_contexts(
            clips, lyrics, performer_map, speaker_names, speaker_mappings,
            coverage_plan,
            allow_clip_text=kwargs.get("allow_clip_text") is True,
        )

        # Call LLM for creative planning
        nsfw = kwargs.get("nsfw", False)
        shot_dicts = self._plan_with_llm(
            clips=clips,
            clip_contexts=clip_contexts,
            scene_description=scene_description,
            bpm=bpm,
            has_reference=has_reference,
            reference_image_path=reference_image_path,
            char_profiles=char_profiles,
            performer_map=performer_map,
            music_video_treatment=treatment,
            nsfw=nsfw,
            **{k: v for k, v in kwargs.items() if k not in ("nsfw", "music_video_treatment")},
        )

        if direct_video:
            # Text-only mode never lets a planner accidentally reintroduce an
            # image stage through a non-empty image/keyframe field.
            for shot in shot_dicts:
                if isinstance(shot, dict):
                    shot["image_prompt"] = ""
                    shot["keyframe_prompts"] = []

        self._validate_llm_shot_plans(
            shot_dicts,
            len(clips),
            require_image=self._uses_generated_shot_images,
        )

        # ── Image-prompt sanitization (Layer 1) ──────────────────────
        # Strip GARMENT BAN violations and narrative-filler phrases the
        # image model can't render. Mirrors the same hook in short_film.py
        # so music-video shots also benefit from the deterministic cleanup
        # regardless of whether Pass 3 polish is enabled. See
        # prompt_polish.sanitize_image_prompt for the full ruleset.
        try:
            from ..prompt_polish import sanitize_image_prompt as _sanitize_ip
            for sd in shot_dicts:
                ip = sd.get("image_prompt") or ""
                if ip.strip():
                    sd["image_prompt"] = _sanitize_ip(
                        ip, log_prefix=f"[MusicVideoPlanner Pass2 image sanitize '{sd.get('scene_goal', 'untitled')[:40]}']"
                    )
                kfs = sd.get("keyframe_prompts") or []
                if isinstance(kfs, list) and kfs:
                    cleaned_kfs = []
                    for ki, kf in enumerate(kfs):
                        if isinstance(kf, str) and kf.strip():
                            cleaned_kfs.append(_sanitize_ip(
                                kf, log_prefix=f"[MusicVideoPlanner Pass2 keyframe[{ki}] sanitize]"
                            ))
                        else:
                            cleaned_kfs.append(kf)
                    sd["keyframe_prompts"] = cleaned_kfs
        except Exception as e:
            print(f"[MusicVideoPlanner] Image-prompt sanitization skipped: {e}")

        # ── Sex-act leet trigger strip (always-on safety net) ────────
        # User-reported leak: a SFW music video about a football coach
        # had "bl0wj0b" in a keyframe_prompt because the LLM treated
        # leet-coded LoRA triggers as generic energy boosters. The
        # leet tokens (bl0wj0b, m15510n4ry, c0wg1rl, etc.) are SEX-ACT
        # video-LoRA triggers — they should NEVER appear in:
        #   - image_prompt or keyframe_prompts (still images, video
        #     LoRA triggers don't apply)
        #   - SFW content of any kind
        # Strip runs on EVERY prompt field unconditionally for image
        # and keyframe fields. For video_prompt and window_prompts,
        # strip only when the surrounding screenplay/scene context
        # is SFW (handled below via nsfw flag).
        try:
            from ..prompt_polish import strip_sex_act_leet_tokens
            total_stripped = 0
            for sd in shot_dicts:
                if not isinstance(sd, dict):
                    continue
                # Image + keyframe: always strip (still images don't
                # use video LoRA triggers regardless of NSFW mode).
                ip = sd.get("image_prompt") or ""
                if ip:
                    new_ip, n = strip_sex_act_leet_tokens(ip)
                    if n:
                        sd["image_prompt"] = new_ip
                        total_stripped += n
                kfs = sd.get("keyframe_prompts") or []
                if isinstance(kfs, list):
                    new_kfs = []
                    for kf in kfs:
                        if isinstance(kf, str):
                            new_kf, n = strip_sex_act_leet_tokens(kf)
                            new_kfs.append(new_kf)
                            total_stripped += n
                        else:
                            new_kfs.append(kf)
                    sd["keyframe_prompts"] = new_kfs
                # Video / windows: strip only if NSFW mode is OFF
                # (effective_nsfw could differ from request nsfw; we
                # use the planner's own nsfw flag which is wired
                # from services config).
                if not nsfw:
                    vp = sd.get("video_prompt") or ""
                    if vp:
                        new_vp, n = strip_sex_act_leet_tokens(vp)
                        if n:
                            sd["video_prompt"] = new_vp
                            total_stripped += n
                    wps = sd.get("window_prompts") or []
                    if isinstance(wps, list):
                        new_wps = []
                        for w in wps:
                            if isinstance(w, str):
                                new_w, n = strip_sex_act_leet_tokens(w)
                                new_wps.append(new_w)
                                total_stripped += n
                            else:
                                new_wps.append(w)
                        sd["window_prompts"] = new_wps
            if total_stripped:
                print(
                    f"[MusicVideoPlanner] Stripped {total_stripped} sex-act "
                    f"leet trigger token(s) (bl0wj0b/m15510n4ry/c0wg1rl/etc.) "
                    f"from prompts that should never contain them. The LLM "
                    f"misplaced trigger words from the active LoRA selection."
                )
        except Exception as e:
            print(f"[MusicVideoPlanner] Leet trigger strip skipped: {e}")

        # Convert LLM output to ShotPlan objects
        shots = self._convert_to_shots(
            shot_dicts=shot_dicts,
            clips=clips,
            char_profiles=char_profiles,
            has_reference=has_reference,
            performer_map=performer_map,
            lyrics=lyrics,
            speaker_names=speaker_names,
            coverage_plan=coverage_plan,
        )

        total_duration = sum(c.get("end", 0) - c.get("start", 0) for c in clips) if clips else None

        return ProductionPlan(
            skill_type="music_video",
            title=None,
            global_style=scene_description,
            total_duration_sec=total_duration,
            reference_assets=ref_assets,
            characters=char_profiles if char_profiles else None,
            shots=shots,
            continuity_notes=[
                "Controlled recurrence is intentional: choruses return to the signature setup",
                "Verses vary coverage inside the same authored visual world",
                "Performer visibility follows the editable treatment instead of every lyric literally",
            ],
            treatment=treatment,
            alternative_shots=getattr(self, "_planning_alternatives", None) or None,
        )

    @staticmethod
    def _validate_llm_shot_plans(
        shot_dicts: list[dict],
        expected: int,
        *,
        require_image: bool = True,
    ) -> None:
        """Reject prose/partial planner output before generic fallbacks hide it.

        A malformed music-video response previously became ``expected`` empty
        ShotPlans.  The image renderer then had only its defaults available and
        emitted repeated ``REFRAME: medium shot | MOOD: steady`` prompts.  That
        looks like a successful plan in the UI even though planning failed.
        """
        if len(shot_dicts) < expected:
            raise RuntimeError(
                f"Music-video planning returned {len(shot_dicts)} valid shots; "
                f"{expected} were required. No images were queued."
            )
        incomplete = []
        for index, shot in enumerate(shot_dicts[:expected]):
            if not isinstance(shot, dict):
                incomplete.append(index + 1)
                continue
            image_prompt = str(shot.get("image_prompt") or "").strip()
            video_prompt = str(shot.get("video_prompt") or "").strip()
            if (require_image and len(image_prompt) < 24) or len(video_prompt) < 16:
                incomplete.append(index + 1)
        if incomplete:
            preview = ", ".join(str(i) for i in incomplete[:12])
            suffix = "…" if len(incomplete) > 12 else ""
            raise RuntimeError(
                "Music-video planning produced incomplete "
                f"{'image/video ' if require_image else 'video '}prompts "
                f"for shots {preview}{suffix}. No images were queued."
            )

    @staticmethod
    def _shot_is_complete(shot: Any, *, require_image: bool = True) -> bool:
        if not isinstance(shot, dict):
            return False
        return (
            (not require_image or len(str(shot.get("image_prompt") or "").strip()) >= 24)
            and len(str(shot.get("video_prompt") or "").strip()) >= 16
        )

    @classmethod
    def _partition_shot_plans(
        cls,
        candidates: list[dict],
        expected: int,
        positional_indices: Optional[list[int]] = None,
        *,
        require_image: bool = True,
    ) -> tuple[dict[int, dict], list[int], list[dict]]:
        """Map valid candidates onto fixed audio slots and retain overflow.

        New responses use one-based ``clip_index`` values. Older/provider-
        ignored schemas remain recoverable through positional mapping.
        """
        slots: dict[int, dict] = {}
        alternatives: list[dict] = []
        for position, candidate in enumerate(candidates):
            if not cls._shot_is_complete(candidate, require_image=require_image):
                continue
            raw_index = candidate.get("clip_index") if isinstance(candidate, dict) else None
            try:
                if raw_index not in (None, ""):
                    index = int(raw_index) - 1
                elif positional_indices is not None and position < len(positional_indices):
                    index = positional_indices[position]
                else:
                    index = position
            except (TypeError, ValueError):
                index = (
                    positional_indices[position]
                    if positional_indices is not None and position < len(positional_indices)
                    else position
                )
            if 0 <= index < expected and index not in slots:
                normalized = dict(candidate)
                normalized["clip_index"] = index + 1
                slots[index] = normalized
            else:
                alternatives.append(dict(candidate))
        missing = [index for index in range(expected) if index not in slots]
        return slots, missing, alternatives

    @staticmethod
    def _compact_repair_context(value: str, limit: int = 7000) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(normalized) <= limit:
            return normalized
        head = int(limit * 0.72)
        tail = limit - head
        return f"{normalized[:head]} … [context compacted] … {normalized[-tail:]}"

    # ── Character Building ───────────────────────────────────────────

    def _build_characters(
        self,
        characters: Optional[list[dict]],
        speaker_mappings: Optional[dict],
        lyrics: Optional[list[dict]],
        performer_map: dict[str, str],
    ) -> list[CharacterProfile]:
        """Build character profiles from available sources."""
        profiles = []

        # From explicit characters
        if characters:
            for i, c in enumerate(characters):
                profiles.append(CharacterProfile(
                    id=f"char_{i}",
                    display_name=c.get("name", ""),
                    physical_description=c.get("description", "person"),
                ))

        # From speaker mappings (if no explicit characters)
        if not profiles and speaker_mappings:
            for sid, info in speaker_mappings.items():
                name = info.get("name", sid)
                role = info.get("role", "")
                profiles.append(CharacterProfile(
                    id=sid,
                    display_name=name,
                    physical_description=f"the {name}" if name else "a performer",
                    voice_description=role,
                ))

        # From performer map
        if not profiles and performer_map:
            seen = set()
            for section, performer in performer_map.items():
                if performer not in seen:
                    seen.add(performer)
                    profiles.append(CharacterProfile(
                        id=f"perf_{len(profiles)}",
                        display_name=None,
                        physical_description=performer,
                    ))

        return profiles

    def _build_speaker_names(
        self,
        speaker_mappings: Optional[dict],
        lyrics: Optional[list[dict]],
    ) -> dict[str, str]:
        """Map speaker_id → display name."""
        names: dict[str, str] = {}
        if speaker_mappings:
            for sid, info in speaker_mappings.items():
                names[sid] = info.get("name", sid)
        return names

    def _format_lyrics_text(self, lyrics: Optional[list[dict]]) -> str:
        """Format lyrics list into plain text."""
        if not lyrics:
            return ""
        return "\n".join(line.get("text", "") for line in lyrics if line.get("text", "").strip())

    # ── Clip Context Building ────────────────────────────────────────

    def _build_clip_contexts(
        self,
        clips: list[dict],
        lyrics: Optional[list[dict]],
        performer_map: dict[str, str],
        speaker_names: dict[str, str],
        speaker_mappings: Optional[dict],
        coverage_plan: Optional[list[dict[str, Any]]] = None,
        allow_clip_text: bool = False,
    ) -> list[str]:
        """Build text descriptions for each clip (context for LLM)."""
        contexts = []
        for i, clip in enumerate(clips):
            section = (clip.get("label") or "verse").lower()
            beat_count = clip.get("beat_count", 8)
            start_sec = clip.get("start", 0)
            end_sec = clip.get("end", start_sec + 5)

            # Gather overlapping lyrics
            lyrics_snippet = ""
            if lyrics:
                overlapping = [
                    l.get("text", "")
                    for l in lyrics
                    if l.get("start", 0) < end_sec and l.get("end", 0) > start_sec
                ]
                if overlapping:
                    lyrics_snippet = " ".join(overlapping)

            # Identify dominant speaker
            performer_hint = ""
            if section in performer_map:
                performer_hint = f" Performer: {performer_map[section]}."
            elif clip.get("dominant_speaker") and speaker_names.get(clip["dominant_speaker"]):
                name = speaker_names[clip["dominant_speaker"]]
                role = ""
                if speaker_mappings and clip["dominant_speaker"] in speaker_mappings:
                    role = speaker_mappings[clip["dominant_speaker"]].get("role", "")
                performer_hint = f" Performer: the {name}"
                if role:
                    performer_hint += f" ({role})"
                performer_hint += "."

            # Vocal info
            if lyrics_snippet:
                vocal_info = (
                    f'lyrics available for intentional on-screen use: "{lyrics_snippet}"'
                    if allow_clip_text
                    else f"audio lyrics for timing and semantic inspiration only; never render as visible text: {lyrics_snippet}"
                )
            else:
                vocal_info = "instrumental"

            coverage = coverage_plan[i] if coverage_plan and i < len(coverage_plan) else {}
            coverage_hint = (
                f" Planned role: {coverage.get('scene_type', 'narrative')}; "
                f"recurring set: {coverage.get('recurring_set', 'main set')}; "
                f"coverage: {coverage.get('coverage', 'medium shot')}; "
                f"section direction: {coverage.get('section_rule', '')}."
            )
            if coverage.get("performer_present"):
                coverage_hint += " Show the assigned performer delivering the vocal when lyrics are present."
            elif lyrics_snippet:
                coverage_hint += " Deliberate b-roll: no lip-sync; any visible mouth remains closed."
            if coverage.get("reuse_chorus_signature"):
                coverage_hint += " Return to the same chorus signature instead of inventing a new location."
            ctx = f"Clip {i + 1}: {section}, {beat_count} beats, {vocal_info}.{performer_hint}{coverage_hint}"
            contexts.append(ctx)

        return contexts

    # ── LLM Planning Call ────────────────────────────────────────────

    def _plan_with_llm(
        self,
        clips: list[dict],
        clip_contexts: list[str],
        scene_description: str,
        bpm: float,
        has_reference: bool,
        reference_image_path: Optional[str],
        char_profiles: list[CharacterProfile],
        performer_map: dict[str, str],
        nsfw: bool = False,
        **kwargs,
    ) -> list[dict]:
        """Call LLM to generate structured shot plans."""
        from ..nsfw_guidance import inject_nsfw_if_enabled

        num_character_refs = len(kwargs.get("character_ref_paths", []) or [])
        num_location_refs = len(kwargs.get("location_ref_paths", []) or [])
        has_asset_references = bool(
            has_reference or num_character_refs or num_location_refs
        )
        preserve_names = bool(
            getattr(self, "_preserve_video_character_names", False)
        )
        uses_generated_images = bool(
            getattr(self, "_uses_generated_shot_images", True)
        )
        char_rules = build_character_rules_block(
            has_reference or bool(num_character_refs),
            char_profiles if char_profiles else None,
            preserve_names=preserve_names,
        )
        camera_block = build_camera_style_block()
        # video_guide now merged into ltx2_music_video_rules.md — no separate load needed

        treatment = normalize_music_video_treatment(kwargs.get("music_video_treatment"))
        direct_video = treatment["generation_mode"] == "direct_video"
        image_prompt_rules = ""
        if uses_generated_images:
            from ..image_prompt_rules import get_image_prompt_rules
            image_prompt_rules = get_image_prompt_rules(
                has_reference,
                num_character_refs=num_character_refs,
                num_location_refs=num_location_refs,
                character_ref_labels=kwargs.get("character_ref_labels"),
                location_ref_labels=kwargs.get("location_ref_labels"),
                seamless=kwargs.get("seamless", True),
                image_model=kwargs.get("image_model", ""),
            )

        from ..guide_loader import load_guide
        video_model = str(kwargs.get("video_model") or "")
        video_model_lower = video_model.lower()
        is_ltx = video_model_lower.startswith(("ltx2", "ltxv"))
        music_video_rules = (
            load_guide("minimax_h3_shot_breakdown.md")
            if video_model_lower.startswith("minimax_h3")
            else "" if direct_video
            else load_guide(
                "ltx2_music_video_rules.md"
                if is_ltx else "music_video_treatment_rules.md"
            )
        )
        character_style_contract = "" if direct_video else build_character_visual_style_contract(
            kwargs.get("character_visual_style", ""),
            preserve=bool(kwargs.get("preserve_visual_style", False)),
        )
        visible_text_contract = build_visible_text_contract(
            kwargs.get("allow_clip_text") is True,
        )
        motion_prompt_rule = (
            "Only the concrete situation for this clip: subjects, visible action, environment "
            "and one camera move. Do not repeat, summarize or rewrite the master prompt."
            if direct_video else
            "Short energetic prompt describing action AFTER the start frame. Keywords. Vibes. Camera. 15-40 words."
            if is_ltx else
            "Chronological action path after the first frame with concrete subject movement, sound, and one coherent camera move."
        )
        h3_direct_rules = (
            "H3 DIRECT-REFERENCE MUSIC VIDEO:\n"
            "- No generated start frame will be supplied. Make each video_prompt "
            "self-contained with setting, composition, named identities plus "
            "visible traits, wardrobe, performance, camera, lighting, ambience, "
            "effects, and music.\n"
            "- The per-shot source-audio slice is mapped as driving audio. "
            "Describe visible singing, lip movement, dance, action, and camera "
            "that synchronize to it; do not invent or transcribe lyrics.\n"
            "- Character/location references are soft guidance, not fixed first "
            "frames. Describe the finished target shot.\n"
            "- Do not create image_prompt, image_source, visual_changes, or "
            "keyframe_prompts. Those fields are intentionally absent from the "
            "video-only output schema."
            if not uses_generated_images else ""
        )
        reference_aesthetic_rules = (
            """VISUAL AESTHETIC — the reference photo defines the visual style for the entire music video.
Match its aesthetic (color grading, film texture, era, tone) in every image_prompt unless the
scene concept explicitly calls for a style change. End each image_prompt with
"Use lighting and color temp from reference image." to preserve the look."""
            if uses_generated_images and has_reference else ""
        )
        image_output_fields = (
            '''    "image_source": "original or previous",
    "image_prompt": "FIRST FRAME BEFORE action — initial state, static pose, environment. No motion verbs.",
    "visual_changes": ["what transforms during the clip — e.g. 'performer jumps off stage', 'lights shift to red'"],
'''
            if uses_generated_images else ""
        )
        keyframe_output_field = (
            '    "keyframe_prompts": [],\n'
            if uses_generated_images else ""
        )
        image_workflow_notes = (
            """- image_source: "original" = user's reference photo (default). "previous" = previous scene's output for same-location continuity.
- FIELD ORDER: Write image_prompt FIRST (starting state), then visual_changes, then video_prompt.
- visual_changes: If the performer jumps off stage, image_prompt shows them still ON stage.
- keyframe_prompts: DEFAULT IS EMPTY. Add one only for a specific visual state the video model cannot infer from the start image and prompt; never for ordinary movement, camera, expression, lighting, or energy changes.
"""
            if uses_generated_images else ""
        )
        if uses_generated_images and has_reference:
            scene_anchoring_rules = """SCENE-ANCHORING (avoid off-topic content):
The user's main reference is visual ground truth. Every image_prompt and video_prompt must match its identity, setting, and aesthetic plus the Scene Concept. Do not invent unrelated worlds."""
        elif has_asset_references:
            scene_anchoring_rules = """SCENE-ANCHORING (avoid off-topic content):
Character references define identity and location references define the setting. Follow their labels and the Scene Concept in every self-contained video prompt; do not invent conflicting identities or settings."""
        else:
            scene_anchoring_rules = """SCENE-ANCHORING (avoid off-topic content):
No visual reference was provided. Invent one consistent performer and setting that fit the Scene Concept, then reuse the same artist and world across every clip. Show the performer delivering vocals on lyric clips and do not drift off-concept."""
        direct_video_contract = f"""DIRECT TEXT-TO-VIDEO MODE — STRICT:
- There is no start image, generated image, keyframe or visual reference.
- The immutable master prompt below defines the visual medium and world. It is automatically
  prefixed by Maestro after planning. Never repeat it, paraphrase it, dilute it or invent a
  competing style in video_prompt.
- Your only variable prompt contribution is the concrete situation for this clip: who/what is
  visible, where they are, the chronological action, and at most one coherent camera move.
- Omit image_prompt, image_source, visual_changes and keyframe_prompts. window_prompts stays empty.
- Do not mention first frames, supplied pictures, references, image conditioning or continuity frames.

IMMUTABLE MASTER VIDEO PROMPT (context only; do not copy into video_prompt):
{treatment['direct_video_master_prompt']}""" if direct_video else ""
        if direct_video:
            scene_anchoring_rules = """SCENE-ANCHORING (direct text-to-video):
The immutable master prompt is the only visual-world authority. Create situations that belong
inside that world and the user's Scene Concept. Keep recurring subjects descriptively stable,
but never mention a source image, reference frame or alternate visual style."""

        system_prompt = f"""You are a music video director. Plan each clip AND write its prompts. Output ONLY the JSON array.

{f"You are given a REFERENCE PHOTO. Use it to identify appearance, clothing, and setting." if has_reference else ""}

{char_rules}

{camera_block}

{reference_aesthetic_rules}

{character_style_contract}

{visible_text_contract}

{direct_video_contract}

MUSIC VIDEO RULES:
- Chorus = high energy, bold framing. Verse = intimate, character focus.
- Instrumental = environment, textures. Bridge = contrasting, unexpected.
- Use controlled recurrence. Revisit the same chorus set, wardrobe and visual motif.
- Vary framing and camera coverage inside recurring sets; do not invent a new world for every lyric.
- Performer visibility and lip-sync follow the editable treatment and each clip's planned role.

EDITABLE MUSIC-VIDEO TREATMENT:
{json.dumps(treatment, ensure_ascii=False, indent=2)}

{music_video_rules}

{h3_direct_rules}

{image_prompt_rules}


OUTPUT — respond with ONLY a JSON array:
[
  {{
    "clip_index": 1,
    "scene_goal": "What this clip achieves",
    "scene_type": "performance|narrative|atmospheric",
    "subjects_on_screen": [{{"visual_description": "the woman in red", "position_or_relation": "center frame"}}],
    "environment": "Setting details",
    "visual_style": "Style",
    "lighting": "Lighting",
    "mood": "Tone",
    "action_beats": ["Action 1", "Action 2"],
    "camera_plan": {{"framing": "medium shot", "movement": "slow dolly in", "movement_intensity": "subtle"}},
    "ending_beat": "Final image",
{image_output_fields}    "video_prompt": "{motion_prompt_rule}",
{keyframe_output_field}    "window_prompts": []
  }}
]

Notes:
{'''- Direct mode: write only the situation in video_prompt; Maestro deterministically prepends the immutable master prompt.
- Do not create still-image fields, keyframes, or continuation windows.''' if direct_video else ''}
{image_workflow_notes}
- window_prompts: empty ([]) unless the scene needs >26s continuous video.

{scene_anchoring_rules}

KEEP MUSIC-VIDEO PROMPTS EXECUTABLE:
For each scene, the music drives the pacing and energy. You only need to identify:
  - WHO is in frame ({"preserve user-supplied proper names and pair them with useful visible traits" if preserve_names else "the performer, by descriptor — never by name"})
  - CAMERA MOVEMENT (push-in, pull-back, orbit, handheld, low angle, etc.)
  - ATMOSPHERIC ELEMENTS (smoke, pyro, crowd cheering, lighting flashes, etc.)
  - The performer's BODY MOVEMENT in broad strokes (head bob, arms raised,
    walking forward, etc.) — but don't over-specify; the model interpolates.
{"Use the H3 Context-IR fields above. Be concise but complete; do not enforce the legacy 15-40 word LTX limit." if preserve_names else "Keep video_prompt 15-40 words. Anything longer is over-described for music video."}

{"Most scenes should use a single video_prompt with empty keyframe_prompts." if uses_generated_images else "Every scene should use video_prompt/window_prompts only; omit all still-image fields."}
Return exactly one object for every requested clip. Preserve each one-based clip_index. Output exactly {len(clips)} objects. Go:"""

        # Inject model-specific prompt polish guide if provided
        polish_block = kwargs.get("polish_block", "")
        if polish_block and not direct_video:
            system_prompt = f"{system_prompt}\n\n{polish_block}"

        # Inject content guidance (NSFW or safety guardrails)
        system_prompt = inject_nsfw_if_enabled(
            system_prompt,
            nsfw,
            "both" if uses_generated_images else "video",
        )

        user_prompt = f"""Scene Concept: {scene_description}
Song tempo: {bpm:.0f} BPM

Clips:
{chr(10).join(clip_contexts)}

Write {len(clips)} structured shot plans for clip indexes 1-{len(clips)}. Go:"""

        # Send ALL reference images to the LLM (main + character + location refs)
        image_paths = []
        if not direct_video and has_reference and reference_image_path:
            image_paths.append(reference_image_path)
        for cp in (() if direct_video else (kwargs.get("character_ref_paths") or [])):
            if cp and os.path.isfile(cp):
                image_paths.append(cp)
        for lp in (() if direct_video else (kwargs.get("location_ref_paths") or [])):
            if lp and os.path.isfile(lp):
                image_paths.append(lp)
        if not image_paths:
            image_paths = None
        per_clip_tokens = 700 if uses_generated_images else 520
        max_tokens = max(4096, len(clips) * per_clip_tokens + 1024)
        response_schema = _music_shot_schema(
            len(clips),
            include_image_fields=uses_generated_images,
        )
        shot_schema = response_schema["items"]
        shot_schema["properties"] = {
            "clip_index": {
                "type": "integer",
                "minimum": 1,
                "maximum": len(clips),
            },
            **shot_schema["properties"],
        }
        shot_schema["required"] = [
            "clip_index",
            *shot_schema["required"],
        ]
        candidates = self._call_llm_json(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            image_paths=image_paths,
            json_schema=response_schema,
        )
        slots, missing, alternatives = self._partition_shot_plans(
            candidates,
            len(clips),
            require_image=uses_generated_images,
        )

        if alternatives:
            print(
                f"[MusicVideoPlanner] Preserving {len(alternatives)} valid surplus "
                f"shot plan(s) as alternatives for {len(clips)} timeline slots."
            )

        if missing:
            missing_numbers = [index + 1 for index in missing]
            missing_contexts = [clip_contexts[index] for index in missing]
            repair_schema = {
                "type": "array",
                "items": shot_schema,
                "minItems": len(missing),
                "maxItems": len(missing),
            }
            repair_system = f"""You repair missing music-video shot plans.
Return ONLY a JSON array with exactly one complete object for each requested clip_index.
Do not return already completed indexes. Preserve the requested one-based clip_index values.
{("image_prompt must be empty. video_prompt must contain only the concrete clip situation; never repeat the master prompt." if direct_video else "Every image_prompt must describe a static first frame and contain at least 24 characters. Every video_prompt must describe subsequent action.")}
{("Use concise chronological, visually executable natural English." if direct_video else "Use 15-40 words." if is_ltx else "Use chronological, visually executable natural English.")}
{character_style_contract}
{visible_text_contract}
Use empty keyframe_prompts and window_prompts unless strictly necessary.
Required object schema:
{json.dumps(shot_schema, ensure_ascii=False)}"""
            repair_prompt = f"""Compact production context:
{self._compact_repair_context(scene_description)}

Song tempo: {bpm:.0f} BPM
Missing clip indexes: {', '.join(map(str, missing_numbers))}
Missing clip context:
{chr(10).join(missing_contexts)}

Return only these {len(missing)} missing shot plans."""
            print(
                f"[MusicVideoPlanner] Requesting one compact repair for missing "
                f"clip indexes {missing_numbers}."
            )
            repaired = self._call_llm_json(
                user_prompt=repair_prompt,
                system_prompt=repair_system,
                max_tokens=max(2048, len(missing) * 700 + 512),
                image_paths=image_paths,
                json_schema=repair_schema,
                temperature=0.35,
            )
            repaired_slots, _repair_missing, repaired_alternatives = self._partition_shot_plans(
                repaired,
                len(clips),
                positional_indices=missing,
                require_image=uses_generated_images,
            )
            for index in missing:
                if index in repaired_slots:
                    slots[index] = repaired_slots[index]
            alternatives.extend(repaired_alternatives)
            missing = [index for index in range(len(clips)) if index not in slots]

        if missing:
            missing_numbers = ", ".join(str(index + 1) for index in missing)
            raise RuntimeError(
                "Music-video planning remained incomplete after one compact repair; "
                f"missing clip indexes {missing_numbers}. No images were queued."
            )

        self._planning_alternatives = alternatives
        shot_dicts = [slots[index] for index in range(len(clips))]
        if not uses_generated_images:
            _discard_unused_image_fields(shot_dicts)
        return shot_dicts

    # ── Convert LLM Output to ShotPlans ──────────────────────────────

    def _convert_to_shots(
        self,
        shot_dicts: list[dict],
        clips: list[dict],
        char_profiles: list[CharacterProfile],
        has_reference: bool,
        performer_map: dict[str, str],
        lyrics: Optional[list[dict]],
        speaker_names: dict[str, str],
        coverage_plan: Optional[list[dict[str, Any]]] = None,
    ) -> list[ShotPlan]:
        """Convert raw LLM JSON output into validated ShotPlan objects."""
        shots = []
        for i, clip in enumerate(clips):
            raw = shot_dicts[i] if i < len(shot_dicts) else {}
            section = (clip.get("label") or "verse").lower()
            strategy = _SECTION_VISUAL_STRATEGY.get(section, _SECTION_VISUAL_STRATEGY["verse"])
            duration = clip.get("end", 0) - clip.get("start", 0)
            coverage = coverage_plan[i] if coverage_plan and i < len(coverage_plan) else {}

            # Parse subjects
            subjects = []
            for s in raw.get("subjects_on_screen", []):
                if isinstance(s, dict):
                    subjects.append(SubjectRef.from_dict(s))
                elif isinstance(s, str):
                    subjects.append(SubjectRef(visual_description=s))

            # Fallback subjects from performer map
            if not subjects and section in performer_map:
                subjects.append(SubjectRef(visual_description=performer_map[section], position_or_relation="center frame"))

            # Parse camera plan
            cam_raw = raw.get("camera_plan", {})
            camera = CameraPlan(
                framing=cam_raw.get("framing", strategy["camera_default"]),
                angle=cam_raw.get("angle"),
                movement=cam_raw.get("movement"),
                movement_intensity=cam_raw.get("movement_intensity", strategy["movement_intensity"]),
                lens_feel=cam_raw.get("lens_feel"),
            )

            # Parse audio plan
            audio_raw = raw.get("audio_plan", {})
            audio = AudioPlan(
                mode=audio_raw.get("mode", "music_driven"),
                ambience=audio_raw.get("ambience"),
                timing_anchor="audio",
            )

            # Parse dialogue beats if present
            dialogue_beats = None
            if raw.get("dialogue_beats"):
                dialogue_beats = [DialogueBeat.from_dict(db) for db in raw["dialogue_beats"]]

            # Determine image strategy
            image_strategy = "reference_edit" if has_reference else "fresh_generation"
            if section == "instrumental" and not has_reference:
                image_strategy = "fresh_generation"

            shot = ShotPlan(
                shot_id=self._make_shot_id(i, "mv"),
                index=i,
                duration_sec=duration,
                skill_type="music_video",
                scene_goal=raw.get("scene_goal", f"{section} clip — {strategy['energy']} energy"),
                narrative_role=section,
                scene_type=raw.get("scene_type") or coverage.get("scene_type") or ("performance" if section != "instrumental" else "atmospheric"),
                source_mode_preference="i2v" if has_reference else "t2v",
                image_strategy=image_strategy,
                continuity_strategy="independent",
                subjects_on_screen=subjects,
                spatial_setup=raw.get("spatial_setup", ""),
                environment=raw.get("environment", ""),
                visual_style=raw.get("visual_style", ""),
                lighting=raw.get("lighting", ""),
                mood=raw.get("mood", strategy["energy"]),
                action_beats=raw.get("action_beats", []),
                performance_beats=raw.get("performance_beats"),
                dialogue_beats=dialogue_beats,
                camera_plan=camera,
                audio_plan=audio,
                ending_beat=raw.get("ending_beat", ""),
                metadata={
                    "section": section,
                    "beat_count": clip.get("beat_count", 0),
                    "bpm": clip.get("bpm", 120),
                    "clip_start": clip.get("start", 0),
                    "clip_end": clip.get("end", 0),
                    "music_video_role": coverage.get("scene_type"),
                    "recurring_set": coverage.get("recurring_set"),
                    "coverage": coverage.get("coverage"),
                    "performer_present": coverage.get("performer_present"),
                    "reuse_chorus_signature": coverage.get("reuse_chorus_signature", False),
                },
                # LLM-generated prompts (used directly, skipping renderer pass 2)
                video_prompt=raw.get("video_prompt"),
                image_prompt=raw.get("image_prompt"),
                window_prompts=raw.get("window_prompts"),
                visual_changes=raw.get("visual_changes"),
                image_source=raw.get("image_source"),
                keyframe_prompts=raw.get("keyframe_prompts"),
            )
            shots.append(shot)

        return shots
