"""
LTX Image-to-Video Renderer — motion/change-focused.

Used when a start image already exists. Does NOT re-describe what's visible.
Focuses on what CHANGES after the starting frame.

Pass 1: assembles motion/change fields into a tagged draft
Pass 2: LLM rewrites into a concise motion-focused prompt
"""

from __future__ import annotations
from typing import Optional

from ..schema import ShotPlan, ProductionPlan
from .base import BaseRenderer


class LtxI2VRenderer(BaseRenderer):
    mode = "i2v"

    @staticmethod
    def ensure_source_style(prompt: str, shot: ShotPlan) -> str:
        """Anchor every I2V prompt to the supplied first frame.

        Planner-written prompts are normally preferred over this renderer's
        deterministic draft.  That meant a planner could describe the motion
        perfectly while omitting the one instruction that matters most for
        illustrated/comic inputs: do not reinterpret the medium.  Keep this
        deterministic so it also protects prompts written by remote LLMs.
        """
        prompt = str(prompt or "").strip()
        metadata = getattr(shot, "metadata", None) or {}
        if metadata.get("motion_only_prompt"):
            # The approved clean keyframe already defines appearance. Repeating
            # it in text can contradict the actual pixels and cause a scene
            # replacement, so comic-film prompts describe changes only.
            return prompt
        lower = prompt.lower()
        anchors = []
        if "exact first frame" not in lower:
            anchors.append("Use the supplied image as the exact first frame.")
        if not any(term in lower for term in (
            "preserve its visual medium",
            "preserve the visual medium",
            "do not restyle",
            "never restyle",
        )):
            anchors.append(
                "Preserve its visual medium, palette, linework, shading and "
                "character design throughout; do not restyle it or turn an "
                "illustrated source photorealistic."
            )
        if shot.visual_style and shot.visual_style.lower() not in lower:
            anchors.append(f"Style direction: {shot.visual_style.strip()}")
        return " ".join([*anchors, prompt]).strip()

    def _refinement_system_prompt(self, shot: ShotPlan, **context) -> str:
        return (
            "Rewrite into 2-4 sentences, present tense. Preserve the exact "
            "visual medium and style of the supplied first frame. Describe "
            "ONLY what changes — motion, expressions and camera shifts. "
            "Keep short. Output ONLY the prompt."
        )

    def render(
        self,
        shot: ShotPlan,
        plan: Optional[ProductionPlan] = None,
        **context,
    ) -> str:
        """Pass 1: assemble tagged draft for I2V."""
        parts = []

        # Brief style anchor
        if shot.visual_style:
            parts.append(f"STYLE: {shot.visual_style}")

        # What changes / who moves first
        action = self._action_text(shot)
        if action:
            parts.append(f"ACTION: {action}")

        # Performance direction
        if shot.performance_beats:
            parts.append(f"PERFORMANCE: {'. '.join(shot.performance_beats)}")

        # Dialogue (critical for lip sync)
        dialogue = self._dialogue_text(shot, plan)
        if dialogue:
            parts.append(f"DIALOGUE: {dialogue}")

        # Camera shift
        if shot.camera_plan.movement:
            parts.append(f"CAMERA: {shot.camera_plan.movement}")

        # Sound beginning
        if shot.audio_plan.ambience:
            parts.append(f"AUDIO: {shot.audio_plan.ambience}")

        # Ending beat
        if shot.ending_beat:
            parts.append(f"ENDING: {shot.ending_beat}")

        return " | ".join(parts)
