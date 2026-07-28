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

_LIVING_STILL_PROMPT = (
    "Animate the supplied comic artwork as a restrained living still from the "
    "exact approved first frame. Keep every visible character, object and "
    "background feature in the same position and preserve the original pose, "
    "silhouette, anatomy, linework, palette and lighting. The camera is locked. "
    "Use only tiny natural motion already supported by the image: gentle "
    "breathing or blinking for visible characters, a slight response in hair "
    "or cloth, and minimal ambient movement such as dust, light, mist or "
    "reflections. Do not introduce, remove, reveal, replace or transform any "
    "subject. Do not make anyone cross the frame or approach the viewer. End "
    "on a stable hold of the same composition."
)


def _motion_mode(source: dict) -> str:
    raw = str(source.get("motion_mode") or "action").strip().lower()
    if raw in {"living-still", "living_still", "still"}:
        return "living-still"
    if raw in {"contextual", "context", "directed"}:
        return "contextual"
    return "action"


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

        # Storyboard/action mode may already contain a manually reviewed,
        # render-ready prompt. Treat it as source of truth. Contextual mode is
        # intentionally rewritten from the complete scene and story canon so
        # old generic camera prompts cannot leak into a new conversion.
        treatments: dict[int, str] = {}
        for index, shot in enumerate(comic_shots):
            motion_mode = _motion_mode(shot)
            if motion_mode == "living-still":
                # Existing comic plans often contain ambitious action prompts.
                # Choosing living-still explicitly asks us not to reuse them:
                # they give the I2V model permission to redraw the panel.
                treatments[index] = _LIVING_STILL_PROMPT
                continue
            reviewed = str(shot.get("video_prompt") or "").strip()
            if motion_mode == "action" and reviewed:
                treatments[index] = reviewed
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
invent a different opening composition. Read the master story canon, panel
description, first-frame description, characters, script and narrative role
together. Write a literal chronological shot paragraph describing only what
happens after that frame: character performance, object/environment motion,
camera behavior, timing and the final beat. Use dialogue only to guide acting
and lip movement; do not draw subtitles, captions, speech bubbles, logos or new
written text. Preserve faces, wardrobe, props, palette, linework and geography.

EACH PANEL MUST PLAY AS ITS OWN SHOT, NOT AS A TRANSITION TO THE NEXT PANEL.
Give the visible subject at least one clear, narratively meaningful action. Do
not fall back to the same breathing/blinking template for every panel. A quiet
beat can be a held gaze, a hand tightening around an object, a hesitant pause,
a small change of posture or another performance justified by this exact story.
Camera movement is secondary and must never be the only thing that happens.
Describe the action chronologically for the supplied duration and finish on a
stable, intentional beat inside the same scene. Do not dissolve, morph or travel
toward an unseen next panel.

One panel is one continuous shot: no montage and no internal cuts. Preserve the
explicitly supplied visual_style, including
anime/cel-shaded rendering when present. Never convert illustrated artwork to
photorealism or 3D. When motion_mode is "contextual", keep the camera locked and
derive restrained but meaningful subject performance from the story; never
replace that performance with a generic zoom. When motion_mode is "action", use
requested_camera deliberately. If requested_camera is "none", "static" or "locked-off",
state that the exact first-frame crop, horizon and perspective remain fixed,
put all motion inside the frame, and do not introduce any zoom, pan, tilt,
dolly, crane, reframing or vertical drift. Follow LTX prompt style: plain,
chronological and concrete, without meta-commentary or negative instructions
inside video_prompt. Keep each video_prompt under 180 words."""
            items = []
            for source_index, shot in missing:
                items.append({
                    "source_index": source_index,
                    "page": shot.get("page_number"),
                    "panel": shot.get("panel_number"),
                    "duration_seconds": shot.get("duration", 3),
                    "motion_mode": _motion_mode(shot),
                    "narrative_role": shot.get("narrative_role", ""),
                    "scene": shot.get("scene_description", ""),
                    "first_frame_visual_description": shot.get("image_prompt", ""),
                    "script_for_performance": shot.get("script", ""),
                    "framing": shot.get("framing", ""),
                    "requested_camera": shot.get("camera_move") or "none",
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
                # Local multimodal writers inspect the exact clean first
                # frames in the same order as `items`. Scoped text-only
                # providers ignore this optional argument and still receive
                # the complete visual description and story context.
                image_paths=[
                    str(shot.get("image_path") or "")
                    for _, shot in missing
                    if str(shot.get("image_path") or "").strip()
                ],
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
            motion_mode = _motion_mode(source)
            duration = max(0.8, min(20.0, float(source.get("duration") or 3)))
            # No camera move is forced by default. The panel's action prompt
            # may still request camera work deliberately in action mode, but
            # contextual and living-still treatments keep composition fixed.
            camera_key = (
                "none"
                if motion_mode in {"living-still", "contextual"}
                else str(source.get("camera_move") or "none")
            )
            camera_movement = _MOVEMENT_LABELS.get(camera_key, camera_key)
            scene = str(source.get("scene_description") or "").strip()
            script = str(source.get("script") or "").strip()
            first_frame_visual = str(source.get("image_prompt") or "").strip()
            visual_style = str(source.get("visual_style") or "").strip()
            contextual_direction = (
                "Keep the camera fixed and turn the visible story information "
                "into one restrained, narratively meaningful performance. "
                if motion_mode == "contextual"
                else ""
            )
            fallback = (
                "Animate the supplied comic artwork as the exact first frame. "
                f"Starting from the visible situation ({first_frame_visual or scene or 'the supplied panel'}), "
                f"perform this continuous story beat: {scene or source.get('narrative_role') or 'the visible action advances naturally'}. "
                + (f"Use this script only to guide acting and lip movement: {script}. " if script else "")
                + contextual_direction
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
                    "motion_mode": motion_mode,
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
