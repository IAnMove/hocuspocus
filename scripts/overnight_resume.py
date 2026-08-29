#!/usr/bin/env python3
"""Resume Fangorn mux, Skull Island MV, then iconic scenes after a Lab restart."""
from __future__ import annotations

import os
import sys
import time
import urllib.request
from pathlib import Path

os.environ.setdefault("MAESTRO_API", "http://127.0.0.1:42003")
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from overnight_surprise import (
    API,
    CLAY,
    FANGORN_SHOTS,
    KONG_MV_LYRICS,
    KONG_MV_SHOTS,
    KONG_MV_STYLE,
    generate_sequence,
    log,
    music_video,
    mux_song,
    run_iconic_scenes,
    wait_idle,
)

FANGORN_WAV = next(
    Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs").glob(
        "2026-08-22-09h08m08s_seed806135099_*.wav"
    ),
    None,
)


def wait_api() -> None:
    for _ in range(90):
        try:
            urllib.request.urlopen(API, timeout=3)
            log(f"resume api up {API}")
            return
        except Exception:
            time.sleep(4)
    raise RuntimeError(f"Maestro not up at {API}")


def main() -> None:
    wait_api()
    wait_idle("resume-start")
    visual = CLAY + " Fangorn Ents, Treebeard, Last March, Isengard flood."
    if FANGORN_WAV and FANGORN_WAV.is_file():
        log(f"reuse fangorn song {FANGORN_WAV.name}")
        try:
            video = generate_sequence("fangorn", visual, FANGORN_SHOTS)
            dest = Path("/home/ina/pinokio/api/Maestro-next.git/app/outputs/overnight_fangorn_mv.mp4")
            mux_song(video, FANGORN_WAV, dest)
            log(f"music video {dest.name}")
        except Exception as exc:
            log(f"mv fangorn failed: {exc}")
    else:
        log("fangorn wav missing; skip")
    try:
        music_video(
            "skull_island",
            KONG_MV_STYLE,
            KONG_MV_LYRICS,
            KONG_MV_SHOTS,
            CLAY + " King Kong 2005 music video, Skull Island and 1933 New York.",
        )
    except Exception as exc:
        log(f"mv skull_island failed: {exc}")
    run_iconic_scenes()
    try:
        from overnight_surprise import run_war_and_alien_scenes
        run_war_and_alien_scenes()
    except Exception as exc:
        log(f"ryan/enemy mine failed: {exc}")
    log("overnight resume finished")


if __name__ == "__main__":
    main()
