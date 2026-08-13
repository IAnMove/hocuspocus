import threading
import time

from app.services.resource_scheduler import (
    ResourceCoordinator,
    ResourceAcquireCancelled,
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


def test_waiting_acquisition_can_be_cancelled_without_entering_lane():
    coordinator = ResourceCoordinator()
    lane = image_lane("local-image")
    release_first = threading.Event()
    cancel_second = threading.Event()
    entered: list[str] = []
    cancelled: list[bool] = []

    def first():
        with coordinator.acquire(lane, task_id="first"):
            entered.append("first")
            release_first.wait(1)

    def second():
        try:
            with coordinator.acquire(
                lane, task_id="second", cancelled=cancel_second.is_set,
                poll_interval=0.01,
            ):
                entered.append("second")
        except ResourceAcquireCancelled:
            cancelled.append(True)

    one = threading.Thread(target=first)
    two = threading.Thread(target=second)
    one.start()
    time.sleep(0.02)
    two.start()
    time.sleep(0.02)
    snapshot = coordinator.snapshot()[0]
    assert [waiter["id"] for waiter in snapshot["waiters"]] == ["second"]
    cancel_second.set()
    two.join(1)
    release_first.set()
    one.join(1)

    assert cancelled == [True]
    assert entered == ["first"]
    assert coordinator.snapshot()[0]["waiting"] == 0


def test_legacy_shared_lock_and_coordinator_use_the_same_physical_slot():
    coordinator = ResourceCoordinator()
    lane = video_lane("local-video")
    legacy_lock = coordinator.shared_lock(lane)
    entered = threading.Event()

    legacy_lock.acquire()

    def migrated_worker():
        with coordinator.acquire(lane, task_id="migrated", poll_interval=0.01):
            entered.set()

    worker = threading.Thread(target=migrated_worker)
    worker.start()
    time.sleep(0.03)
    assert not entered.is_set()
    assert coordinator.snapshot()[0]["waiting"] == 1
    legacy_lock.release()
    worker.join(1)
    assert entered.is_set()


def test_prepare_hook_runs_after_exclusive_acquisition():
    coordinator = ResourceCoordinator()
    lane = video_lane("local-video")
    events: list[str] = []
    coordinator.set_prepare_hook(
        lane,
        lambda _lane, task_id, description: events.append(
            f"prepare:{task_id}:{description}"
        ),
    )
    with coordinator.acquire(lane, task_id="job-a", description="3d"):
        events.append("running")
    assert events == ["prepare:job-a:3d", "running"]


def test_prepare_hook_can_reenter_its_owned_lane_for_cleanup():
    coordinator = ResourceCoordinator()
    lane = video_lane("local-video")
    events: list[str] = []

    def prepare(_lane, _task_id, _description):
        with coordinator.acquire(lane, task_id="nested-cleanup"):
            events.append("cleanup")

    coordinator.set_prepare_hook(lane, prepare)
    with coordinator.acquire(lane, task_id="job-a"):
        events.append("running")

    assert events == ["cleanup", "running"]
    assert coordinator.snapshot()[0]["active"] == 0


def test_adopted_legacy_lease_runs_handoff_and_is_observable():
    coordinator = ResourceCoordinator()
    lane = video_lane("local-video")
    legacy_lock = coordinator.shared_lock(lane)
    events: list[str] = []
    coordinator.set_prepare_hook(
        lane,
        lambda _lane, task_id, description: events.append(
            f"prepare:{task_id}:{description}"
        ),
    )

    legacy_lock.acquire()
    try:
        with coordinator.adopt_acquired(
            lane, task_id="legacy-job", description="Maestro WGP generation",
        ):
            snapshot = coordinator.snapshot()[0]
            assert snapshot["active"] == 1
            assert snapshot["tasks"] == [{
                "id": "legacy-job",
                "description": "Maestro WGP generation",
                "started_at": snapshot["tasks"][0]["started_at"],
            }]
            events.append("running")
    finally:
        legacy_lock.release()

    assert events == [
        "prepare:legacy-job:Maestro WGP generation",
        "running",
    ]
    assert coordinator.snapshot()[0]["active"] == 0


def test_adopted_legacy_lease_allows_prepare_hook_reentry():
    coordinator = ResourceCoordinator()
    lane = video_lane("local-video")
    legacy_lock = coordinator.shared_lock(lane)
    events: list[str] = []

    def prepare(_lane, _task_id, _description):
        with coordinator.acquire(lane, task_id="cleanup"):
            events.append("cleanup")

    coordinator.set_prepare_hook(lane, prepare)
    legacy_lock.acquire()
    try:
        with coordinator.adopt_acquired(lane, task_id="legacy-job"):
            events.append("running")
    finally:
        legacy_lock.release()

    assert events == ["cleanup", "running"]
    assert coordinator.snapshot()[0]["active"] == 0


def test_same_thread_can_nest_the_same_lane_without_deadlock():
    coordinator = ResourceCoordinator()
    lane = video_lane("local-video")
    with coordinator.acquire(lane, task_id="parent"):
        with coordinator.acquire(lane, task_id="child"):
            snapshot = coordinator.snapshot()[0]
            assert snapshot["active"] == 1
            assert [task["id"] for task in snapshot["tasks"]] == ["parent"]
    assert coordinator.snapshot()[0]["active"] == 0


def test_cancelled_nested_acquisition_never_enters_child_operation():
    coordinator = ResourceCoordinator()
    lane = video_lane("local-video")
    entered = []
    with coordinator.acquire(lane, task_id="parent"):
        try:
            with coordinator.acquire(
                lane,
                task_id="child",
                cancelled=lambda: True,
            ):
                entered.append("child")
        except ResourceAcquireCancelled:
            pass
        else:  # pragma: no cover - explicit assertion message
            raise AssertionError("cancelled nested acquisition entered child")
    assert entered == []
    assert coordinator.snapshot()[0]["active"] == 0
