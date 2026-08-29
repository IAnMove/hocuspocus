import json
from types import SimpleNamespace

from app.shared.utils import video_decode


def test_packet_timing_recovers_chromium_media_recorder_webm(monkeypatch):
    responses = [
        {
            "streams": [{
                "width": 1280,
                "height": 720,
                "avg_frame_rate": "0/0",
                "r_frame_rate": "1000/1",
            }],
            "format": {},
        },
        {
            "streams": [{"nb_read_frames": "4"}],
            "packets": [
                {"pts_time": "0.000"},
                {"pts_time": "0.100"},
                {"pts_time": "0.250"},
                {"pts_time": "0.500"},
            ],
        },
    ]

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(responses.pop(0)))

    monkeypatch.setattr(video_decode, "_resolve_media_binary", lambda _name: "ffprobe")
    monkeypatch.setattr(video_decode.subprocess, "run", fake_run)
    video_decode.probe_video_stream_metadata.cache_clear()

    metadata = video_decode.probe_video_stream_metadata("recording.webm")

    assert metadata["duration"] == 0.5
    assert metadata["frame_count"] == 4
    assert metadata["fps_float"] == 6.0
    assert metadata["fps"] == 6
