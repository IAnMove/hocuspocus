"""Sources are balanced by measured loudness: quiet lines come up, loud music is scaled down."""
import shutil
import subprocess

import pytest

from services.audio_levels import gain_to, integrated_lufs, level_file

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


def tone(path, volume_db, seconds=2.0):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}",
                    "-af", f"volume={volume_db}dB", str(path)], check=True)


def test_a_quiet_line_is_levelled_to_dialogue_loudness_once(tmp_path):
    line = tmp_path / "line.wav"
    tone(line, -6)  # about -28 LUFS, like a quiet local voice
    before = integrated_lufs(str(line))
    assert before is not None and before < -25
    assert level_file(str(line)) > 5
    assert abs(integrated_lufs(str(line)) + 16) < 0.6
    assert level_file(str(line)) == 0.0, "already at the target"


def test_loud_music_gets_a_gain_below_one_and_unreadable_files_keep_theirs(tmp_path):
    loud = tmp_path / "theme.wav"
    tone(loud, 12)  # about -10 LUFS, like generated music
    assert 0.1 <= gain_to(str(loud)) < 0.6
    (tmp_path / "junk.wav").write_bytes(b"not audio")
    assert gain_to(str(tmp_path / "junk.wav")) == 1.0 and level_file(str(tmp_path / "junk.wav")) == 0.0
