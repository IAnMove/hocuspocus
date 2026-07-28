"""Comic Movie Planner — adapt finished comic panels into I2V shots.

The comic has already done the expensive narrative and visual planning. This
planner therefore keeps one shot per supplied panel, asks the LLM only for the
motion/performance treatment, and falls back deterministically per panel when a
remote provider ignores structured output.
"""

from __future__ import annotations

import json
from typing import Any

from ..schema import (
    AudioPlan,
    CameraPlan,
    ProductionPlan,
    ShotPlan,
    SubjectRef,
)
from .base import BasePlanner


_MOVEMENT_LABELS = {
    "none": "locked-off camera",
    "push-in": "slow cinematic push-in",
    "pull-out": "slow cinematic pull-out",
    "pan-left": "controlled pan left",
    "pan-right": "controlled pan right",
}


class ComicMoviePlanner(BasePlanner):
    """Create an I2V production plan while preserving panel order exactly."""

    skill_type = "comic_movie"

    def plan(
        self,
        comic_context: str,
        comic_shots: list[dict],
        **_: Any,
    ) -> ProductionPlan:
        if not comic_shots:
            return ProductionPlan(skill_type=self.skill_type, shots=[], total_duration_sec=0)

        # Storyboard mode may already contain a manually reviewed, render-ready
        # prompt. Treat it as source of truth and ask the LLM only for missing
        # shots; this avoids silently rewriting approved camera/performance work.
        treatments: dict[int, str] = {
            index: str(shot.get("video_prompt") or "").strip()
            for index, shot in enumerate(comic_shots)
            if str(shot.get("video_prompt") or "").strip()
        }
        batch_size = 6
        for batch_start in range(0, len(comic_shots), batch_size):
            batch = comic_shots[batch_start:batch_start + batch_size]
            missing = [
                (batch_start + local_index, shot)
                for local_index, shot in enumerate(batch)
                if batch_start + local_index not in treatments
            ]
            if not missing:
                continue
            missing_indices = {item[0] for item in missing}
            schema = {
                "type": "array",
                "minItems": len(missing),
                "maxItems": len(missing),
                "items": {
                    "type": "object",
                    "properties": {
                        "source_index": {"type": "integer"},
                        "video_prompt": {"type": "string"},
                    },
                    "required": ["source_index", "video_prompt"],
                    "additionalProperties": False,
                },
            }
            system = """You are adapting finished comic panels into image-to-video shots.
Return ONLY the requested JSON array, one object for every source panel.

The supplied panel image is the ACTUAL FIRST FRAME. Never redesign it and never
invent a different opening composition. Write a concise but specific I2V prompt
describing only motion after that frame: character acting, environmental motion,
camera movement, timing and the final beat. Use dialogue/script only to guide
performance; do not ask the video model to draw subtitles, captions, speech
bubbles, logos or new written text. Preserve faces, wardrobe, props, palette,
linework and panel geography.

EACH PANEL MUST PLAY AS ITS OWN SHOT, NOT AS A TRANSITION TO THE NEXT PANEL.
Give the visible subject at least one clear, narratively meaningful action; for a
quiet beat, use expressive acting plus concrete environmental motion. Camera
movement is secondary and must never be the only thing that happens. Describe
the action chronologically for the supplied duration and finish on a stable,
intentional beat inside the same scene. Do not dissolve, morph or travel toward
an unseen next panel.

One panel is one continuous shot: no montage and no internal cuts. Preserve the
explicitly supplied visual_style, including
anime/cel-shaded rendering when present. Never convert illustrated artwork to
photorealism or 3D. Keep each video_prompt under 130 words."""
            items = []
            for source_index, shot in missing:
                items.append({
                    "source_index": source_index,
                    "page": shot.get("page_number"),
                    "panel": shot.get("panel_number"),
                    "duration_seconds": shot.get("duration", 3),
                    "narrative_role": shot.get("narrative_role", ""),
                    "scene": shot.get("scene_description", ""),
                    "first_frame_visual_description": shot.get("image_prompt", ""),
                    "script_for_performance": shot.get("script", ""),
                    "framing": shot.get("framing", ""),
                    "requested_camera": shot.get("camera_move", ""),
                    "characters": shot.get("characters", []),
                    "visual_style": shot.get("visual_style", ""),
                })
            user = (
                f"MASTER COMIC CONTEXT:\n{(comic_context or '')[:24000]}\n\n"
                f"PANELS IN THIS BATCH:\n{json.dumps(items, ensure_ascii=False)}\n\n"
                f"Return exactly {len(missing)} objects and preserve source_index."
            )
            generated = self._call_llm_json(
                user_prompt=user,
                system_prompt=system,
                max_tokens=max(2048, len(missing) * 650),
                thinking_budget=0,
                temperature=0.45,
                streaming=True,
                json_schema=schema,
            )
            for item in generated:
                try:
                    source_index = int(item.get("source_index"))
                except (TypeError, ValueError):
                    continue
                if source_index not in missing_indices:
                    continue
                prompt = str(item.get("video_prompt") or "").strip()
                if prompt:
                    treatments[source_index] = prompt

        shots: list[ShotPlan] = []
        for index, source in enumerate(comic_shots):
            duration = max(0.8, min(20.0, float(source.get("duration") or 3)))
            camera_key = str(source.get("camera_move") or "push-in")
            camera_movement = _MOVEMENT_LABELS.get(camera_key, camera_key)
            scene = str(source.get("scene_description") or "").strip()
            script = str(source.get("script") or "").strip()
            first_frame_visual = str(source.get("image_prompt") or "").strip()
            visual_style = str(source.get("visual_style") or "").strip()
            fallback = (
                "Animate the supplied comic artwork as the exact first frame. "
                f"Starting from the visible situation ({first_frame_visual or scene or 'the supplied panel'}), "
                f"perform this continuous story beat: {scene or source.get('narrative_role') or 'the visible action advances naturally'}. "
                + (f"Use this script only to guide acting and lip movement: {script}. " if script else "")
                + "Give the visible subject a clear action, add concrete environmental "
                "motion, and settle on a stable final pose within this same scene. "
                + f"Camera: {camera_movement}; camera motion is secondary to the performance. "
                "Preserve every face, costume, prop, color, "
                "drawing style and spatial relationship. Add subtle natural secondary motion. "
                "Do not transition, dissolve or morph toward the next panel. "
                "Do not create subtitles, captions, speech bubbles, logos or new written text."
            )
            characters = [
                SubjectRef(visual_description=str(name), character_id=str(name))
                for name in (source.get("characters") or [])
                if str(name).strip()
            ]
            shots.append(ShotPlan(
                shot_id=self._make_shot_id(index, "comic"),
                index=index,
                duration_sec=duration,
                skill_type=self.skill_type,
                scene_goal=str(source.get("narrative_role") or f"Panel {index + 1}"),
                narrative_role=str(source.get("narrative_role") or "story beat"),
                scene_type="dialogue" if script else "action",
                source_mode_preference="i2v",
                image_strategy="none",
                continuity_strategy="independent",
                subjects_on_screen=characters,
                spatial_setup=str(source.get("framing") or "Preserve the supplied panel composition."),
                environment="The exact environment visible in the supplied comic panel.",
                visual_style=(
                    f"{visual_style}. Preserve the exact comic artwork, palette, "
                    "linework and rendering medium."
                    if visual_style
                    else "Preserve the exact comic artwork, palette, linework and rendering medium."
                ),
                lighting="Preserve the lighting established by the supplied first frame.",
                mood=str(source.get("narrative_role") or "cinematic"),
                action_beats=[scene] if scene else ["Continue the visible action naturally."],
                camera_plan=CameraPlan(
                    framing=str(source.get("framing") or "match supplied panel"),
                    movement=camera_movement,
                    movement_intensity="static" if camera_key == "none" else "subtle",
                ),
                audio_plan=AudioPlan(mode="ambient_only"),
                ending_beat=f"Complete panel {source.get('page_number', '?')}.{source.get('panel_number', '?')} cleanly.",
                metadata={
                    "page_number": source.get("page_number"),
                    "panel_number": source.get("panel_number"),
                    "provided_image_path": source.get("image_path"),
                },
                image_prompt=str(source.get("image_prompt") or scene),
                video_prompt=treatments.get(index, fallback),
                visual_changes=[],
                image_source="original",
                keyframe_prompts=[],
                window_prompts=[],
            ))

        return ProductionPlan(
            skill_type=self.skill_type,
            shots=shots,
            title=str(comic_shots[0].get("comic_title") or "Comic movie"),
            global_style="Preserve the exact visual language of the finished comic.",
            total_duration_sec=sum(shot.duration_sec for shot in shots),
            continuity_notes=[
                "Every shot starts from its corresponding finished comic panel artwork.",
                "Panel order, character identity and story continuity are immutable.",
            ],
        )
