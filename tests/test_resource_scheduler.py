import threading
import time

from app.services.resource_scheduler import (
    ResourceCoordinator,
    image_lane,
    llm_lane,
    may_overlap,
    video_lane,
)


def test_local_image_and_video_share_one_gpu_lane():
    image = image_lane("flux2_klein_9b", gpu_index=0)
    video = video_lane("minimax_h3", gpu_index=0)
    assert image.key == video.key == "local_gpu:0"
    assert not may_overlap(image, video)


def test_remote_images_can_overlap_local_video():
    image = image_lane("minimax:image-01")
    video = video_lane("minimax_h3", gpu_index=0)
    assert may_overlap(image, video)


def test_local_images_can_overlap_remote_video():
    image = image_lane("flux2_klein_9b", gpu_index=0)
    video = video_lane("future-video-api", base_url="https://video.example/v1")
    assert may_overlap(image, video)


def test_remote_llm_or_cpu_can_overlap_local_generation():
    gpu = video_lane("minimax_h3")
    assert may_overlap(llm_lane("minimax"), gpu)
    assert may_overlap(llm_lane("local", device="cpu"), gpu)


def test_same_remote_server_is_one_lane_even_for_different_paths():
    first = llm_lane("openai-compatible", base_url="https://models.example/v1")
    second = video_lane("remote-video", base_url="https://models.example/api/video")
    assert first.key == second.key
    assert not may_overlap(first, second)


def test_two_local_gpus_are_independent():
    assert may_overlap(image_lane("local-image", gpu_index=0), video_lane("local-video", gpu_index=1))


def test_coordinator_serializes_tasks_in_the_same_lane():
    coordinator = ResourceCoordinator()
    lane = image_lane("local-image")
    entered: list[str] = []
    release_first = threading.Event()

    def first():
        with coordinator.acquire(lane, task_id="first"):
            entered.append("first")
            release_first.wait(1)

    def second():
        with coordinator.acquire(lane, task_id="second"):
            entered.append("second")

    one = threading.Thread(target=first)
    two = threading.Thread(target=second)
    one.start()
    time.sleep(0.02)
    two.start()
    time.sleep(0.02)
    assert entered == ["first"]
    snapshot = coordinator.snapshot()[0]
    assert snapshot["active"] == 1
    assert snapshot["waiting"] == 1
    release_first.set()
    one.join(1)
    two.join(1)
    assert entered == ["first", "second"]
