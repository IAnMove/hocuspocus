"""MCP profiles: a smaller tool list for agents that do one job.

The full ``/api/v1/mcp`` endpoint lists about 160 tools. A general chat agent
(ChatGPT, a phone client) works better with only the tools of its task, and a
connector may cap how many tools it loads. ``/api/v1/mcp/<profile>`` serves
the same handlers filtered to a profile, with its own first instructions.
"""
from __future__ import annotations

SERIES_TOOLS = frozenset({
    # Start here, then the series itself.
    "series.guide", "series.list", "series.get", "series.episode.get", "series.create", "series.update", "series.canon.approve",
    "series.templates", "series.create_from_template",
    "series.episode.from_script", "series.episode.produce", "series.episode.produce.status", "series.episode.produce.cancel",
    "series.episode.produce.resume",
    "series.episode.create", "series.episode.update", "series.episode.language_version.set", "series.episode.translate",
    "series.episode.render_native", "series.episode.render_native.status", "series.episode.render_native.cancel",
    "series.episode.render_native.resume", "series.asset.import", "series.take.approve",
    "series.assembly.start", "series.assembly.status", "series.location.plate3d", "series.location.plate3d.status",
    # Characters: one-click kits and voices.
    "characters.list", "characters.get", "characters.save", "characters.styles", "characters.rig.flat",
    "characters.rig.flat.preview",
    # Generation and checks.
    "generation.image", "generation.speech", "generation.music", "generation.sfx", "generation.receipt", "jobs.wait",
    "studio.key", "qa.speech", "qa.export", "audio.mouth_cues", "scenes.assets.inspect",
    # One shot by its number or id, and the media steps that used to need scripts outside the app.
    "series.shot.get", "series.shot.update", "media.frame", "media.compose", "audio.trim", "assets.import_from_workspace",
    # Editing a take's scene and Video 3D.
    "scenes.document.get", "scenes.document.save", "scenes.effects.catalog", "scenes.effects.apply",
    "scenes.video2d.export", "scenes.video2d.export.receipt", "scenes.video2d.preview",
    "world3d.templates.list", "world3d.templates.get", "world3d.templates.user.put", "world3d.scene.instantiate",
    "world3d.scene.inspect", "world3d.scene.patch", "world3d.scene.talk", "world3d.scene.preview", "world3d.scene.publish",
    "scenes.world3d.export", "scenes.world3d.export.receipt",
})

PROFILES: dict[str, dict] = {
    "series": {
        "tools": SERIES_TOOLS,
        "instructions": (
            "HocusPocus Series Lab: animated series made locally (2D cutout characters, Video 3D, local voices and lip-sync). "
            "Call series.guide first with the workspace and series id: it returns how to make an episode with these tools, "
            "the shot format, the house conventions and the series bible (characters with their kits, poses and voices, "
            "locations, music and sound files, episodes). Write the episode with series.episode.from_script and make it with "
            "series.episode.produce. Long jobs return an id: poll their status tool. Reuse intent_id on retries."
        ),
    },
}


def profile(name: str) -> dict | None:
    return PROFILES.get(name)
