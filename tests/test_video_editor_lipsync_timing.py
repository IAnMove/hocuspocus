"""Decoded flash/beep timing must survive AAC cuts and nested episode assembly."""
import array
import json
import math
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from app.services import video_editor

pytestmark = pytest.mark.skipif(
    not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg required',
)


def run(*args):
    result = subprocess.run(args, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr.decode(errors='replace')[-1500:]
    return result.stdout


def flash_beep(path: Path, frames: int, fps: int):
    rate = 48000
    samples = array.array('h', (
        int(20000 * math.sin(2 * math.pi * 660 * i / rate))
        if 5 * rate // fps <= i < 8 * rate // fps else 0
        for i in range(frames * rate // fps)
    ))
    audio = path.with_suffix('.wav')
    with wave.open(str(audio), 'wb') as output:
        output.setparams((1, 2, rate, len(samples), 'NONE', 'not compressed'))
        output.writeframes(samples.tobytes())
    run('ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
        f"color=black:s=320x240:r={fps},drawbox=color=white:t=fill:enable='gte(n,5)*lt(n,8)'",
        '-i', str(audio), '-frames:v', str(frames), '-c:v', 'libx264',
        '-preset', 'ultrafast', '-c:a', 'aac', str(path))


def assert_flash_beep_alignment(path: Path, fps: int, expected_frames: int, flashes: int):
    streams = json.loads(run('ffprobe', '-v', 'error', '-show_entries',
                            'stream=codec_type,start_time', '-of', 'json', str(path)))['streams']
    starts = {x['codec_type']: float(x.get('start_time', 0)) for x in streams}
    pixels = run('ffmpeg', '-v', 'error', '-i', str(path), '-an',
                 '-vf', 'scale=1:1,format=gray', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-')
    assert len(pixels) == expected_frames
    video_onsets = [starts['video'] + i / fps for i, x in enumerate(pixels)
                    if x > 128 and (i == 0 or pixels[i-1] <= 128)]
    pcm = array.array('h', run('ffmpeg', '-v', 'error', '-i', str(path),
                             '-vn', '-ac', '1', '-ar', '48000', '-f', 's16le', '-'))
    # 2 ms RMS bins detect the beep, ignoring the low-level AAC ringing.
    block = 96
    active = [sum(x*x for x in pcm[i:i+block]) / block > 4000**2
              for i in range(0, len(pcm)-block, block)]
    audio_onsets = [starts['audio'] + i * block / 48000 for i, x in enumerate(active)
                    if x and (i == 0 or not active[i-1])]
    assert len(video_onsets) == len(audio_onsets) == flashes
    assert max(abs(v-a) for v, a in zip(video_onsets, audio_onsets)) < .01


@pytest.mark.parametrize('fps', [24, 25, 30, 50, 60])
def test_aac_cuts_keep_speech_aligned_in_scene_and_episode(tmp_path, fps):
    counts = [13, 17, 19]
    clips = []
    for i, frames in enumerate(counts):
        source = tmp_path / f'clip-{i}.mp4'
        flash_beep(source, frames, fps)
        clips.append({'resolved_path': str(source), 'transition': 'none', 'volume': 1})
    scene = tmp_path / 'scene.mp4'
    video_editor.render_project(clips, str(scene), width=320, height=240, fps=fps)
    assert_flash_beep_alignment(scene, fps, sum(counts), 3)
    episode = tmp_path / 'episode.mp4'
    video_editor.render_project([
        {'resolved_path': str(scene), 'transition': 'none'},
        {'resolved_path': str(scene), 'transition': 'none'},
    ], str(episode), width=320, height=240, fps=fps)
    assert_flash_beep_alignment(episode, fps, 2 * sum(counts), 6)


def test_time_card_and_soundtrack_preserve_flash_beep_timing(tmp_path):
    clips = []
    for i, frames in enumerate([13, 17, 19]):
        source = tmp_path / f'clip-{i}.mp4'
        flash_beep(source, frames, 30)
        clips.append({'resolved_path': str(source), 'transition': 'none'})
    clips[0].update(transition='later-cinematic', transition_duration=.5, transition_text='')
    silence = tmp_path / 'silence.wav'
    with wave.open(str(silence), 'wb') as output:
        output.setparams((1, 2, 48000, 48000, 'NONE', 'not compressed'))
        output.writeframes(bytes(96000))
    movie = tmp_path / 'with-music.mp4'
    video_editor.render_project(clips, str(movie), width=320, height=240, fps=30,
                                soundtrack={'resolved_path': str(silence), 'volume': 1})
    # Time cards may have bright text, so inspect the actual clock around the
    # first and last beep rather than counting their deliberately bright pixels.
    pcm = array.array('h', run('ffmpeg', '-v', 'error', '-i', str(movie),
                             '-vn', '-ac', '1', '-ar', '48000', '-f', 's16le', '-'))
    for start in [5/30, (13+15+5)/30, (13+15+17+5)/30]:
        window = pcm[round((start-.04)*48000):round((start+.04)*48000)]
        first = next(i for i, x in enumerate(window) if abs(x) > 4000)
        assert abs(first/48000 - .04) < .01
