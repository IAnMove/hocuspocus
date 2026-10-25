"""One OpenPose control video of a catalog walk, from the gait guide (services/walk_guides.py).

A cycle is two steps. The clip is that one cycle at the LTX-2.3 frame rate: each frame is the skeleton at that
phase, from the camera of one direction. The sheet samples its poses across the same cycle (services/walk_video_method.py).
"""
from __future__ import annotations

import os
import subprocess
import tempfile

from services.walk_guides import TURN, WalkGuideError, guide_image

# 17+8k, the shortest LTX-2.3 length, one second at the 22B handler's 25 fps. 832x1104 is the portrait preset
# nearest the sheet's 896x1152 (LTX has no 896x1152). The sheet joiner scales the keyed cells.
CLIP_FPS = 25
CLIP_FRAMES = 25
CLIP_SIZE = (832, 1104)
STEPS = 2


def sample_indices(frame_count: int, pose_count: int) -> list[int]:
    """The frame nearest each sheet phase ``index / pose_count``."""
    if frame_count < 1 or pose_count < 1 or pose_count > frame_count:
        raise WalkGuideError("the clip has at least one frame for every pose")
    indices = [min(frame_count - 1, int(round(index / pose_count * frame_count))) for index in range(pose_count)]
    if len(set(indices)) != pose_count:
        raise WalkGuideError("each pose samples a different frame of the clip")
    return indices


def _ffmpeg(args: list[str]) -> None:
    try:
        result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *args], capture_output=True, check=False)
    except OSError as error:
        raise WalkGuideError("ffmpeg could not write the walk guide video") from error
    if result.returncode != 0:
        raise WalkGuideError("ffmpeg could not write the walk guide video")


def _frames_of(path: str) -> int:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries", "stream=nb_read_frames",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, check=False,
        )
    except OSError as error:
        raise WalkGuideError("ffprobe could not read the walk clip") from error
    text = (result.stdout or "").strip()
    if result.returncode != 0 or not text.isdigit() or int(text) < 1:
        raise WalkGuideError("the walk clip has no frames")
    return int(text)


def render_guide_video(direction: str, dest: str, *, frames: int | None = None, fps: int | None = None,
                       size: tuple[int, int] | None = None) -> dict[str, object]:
    """Write ``dest``: ``frames`` skeleton frames of one cycle (``STEPS`` steps) from ``direction``, at ``fps``.

    The defaults are the module constants, read when the function runs, so a test can shrink the picture.
    """
    frames = CLIP_FRAMES if frames is None else frames
    fps = CLIP_FPS if fps is None else fps
    size = CLIP_SIZE if size is None else size
    if direction not in TURN:
        raise WalkGuideError(f"direction is one of {', '.join(TURN)}")
    if frames < 1 or fps < 1:
        raise WalkGuideError("the guide video needs frames and a frame rate")
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="walk-guide-") as folder:
        for index in range(frames):
            guide_image(direction, index / frames, size, "skeleton").convert("RGB").save(os.path.join(folder, f"frame_{index:04d}.png"))
        _ffmpeg(["-framerate", str(fps), "-start_number", "0", "-i", os.path.join(folder, "frame_%04d.png"),
                 "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", dest])
    return {"file": os.path.basename(dest), "fps": fps, "frames": frames, "direction": direction, "steps": STEPS,
            "width": size[0], "height": size[1], "phases": [round(index / frames, 4) for index in range(frames)]}


def sample_frames(clip: str, dest_dir: str, names: list[str]) -> list[str]:
    """Write one PNG per name, the frame of ``clip`` nearest that pose's phase. Returns the names."""
    indices = sample_indices(_frames_of(clip), len(names))
    for index, name in zip(indices, names):
        # The comma splits an ffmpeg filtergraph, so it is escaped for ffmpeg. The argument is not a shell command.
        _ffmpeg(["-i", clip, "-vf", f"select=eq(n\\,{index})", "-frames:v", "1", os.path.join(dest_dir, name)])
    return list(names)


__all__ = ["CLIP_FPS", "CLIP_FRAMES", "CLIP_SIZE", "STEPS", "render_guide_video", "sample_frames", "sample_indices"]
