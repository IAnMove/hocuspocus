import threading
import time

from app.services import director_pipeline


class _FakeWgp:
    server_config = {
        "services": {
            "llm_provider": "local",
            "llm_device": "cpu",
        },
    }


def test_director_resolves_cpu_remote_and_gpu_lanes(monkeypatch):
    monkeypatch.setattr(director_pipeline, "_wgp", _FakeWgp())
    lanes = director_pipeline._director_resource_lanes({
        "writing_provider": "minimax",
        "writing_base_url": "https://api.minimax.io/v1",
        "image_model": "minimax:image-01",
        "video_model": "minimax_h3",
    })
    assert lanes["planning"].key == lanes["images"].key
    assert lanes["video"].key == "local_gpu:0"
    assert lanes["images"].key != lanes["video"].key


def test_h3_consumer_waits_until_remote_start_image_is_ready(tmp_path, monkeypatch):
    pid = "parallel-test"
    start_name = "start.png"
    clip_images = [""]
    ready = threading.Event()
    submitted = []

    director_pipeline._pipelines[pid] = {
        "id": pid,
        "status": "running",
        "phase": "generating_images",
        "params": {},
        "clip_plans": [],
        "created_at": time.time(),
        "out_dir": str(tmp_path),
    }
    monkeypatch.setattr(director_pipeline, "_save_pipeline_state", lambda _pid: True)
    monkeypatch.setattr(director_pipeline, "_pipeline_cancel_requested", lambda _pid: False)

    def submit(params, **_kwargs):
        submitted.append(params)
        return ["shot.mp4"]

    monkeypatch.setattr(director_pipeline, "_submit_and_wait", submit)

    def publish_image():
        time.sleep(0.06)
        (tmp_path / start_name).write_bytes(b"image")
        clip_images[0] = start_name
        ready.set()

    producer = threading.Thread(target=publish_image)
    producer.start()
    started = time.monotonic()
    try:
        outputs = director_pipeline._run_minimax_h3_story_video(
            pid,
            {"master_seed": 12},
            [{"video_prompt": "A woman opens a door. Audio: quiet room tone."}],
            [{"duration_sec": 2}],
            clip_images,
            {"h3_reference_mode": "first_frame", "num_inference_steps": 1},
            "960x544",
            str(tmp_path),
            clip_ready_events=[ready],
            producer_failed=threading.Event(),
        )
    finally:
        producer.join(1)
        director_pipeline._pipelines.pop(pid, None)

    assert time.monotonic() - started >= 0.05
    assert outputs == ["shot.mp4"]
    assert submitted[0]["image_start"].endswith(start_name)
