import pytest

from app.services import model3d_service, rig_service


@pytest.fixture(autouse=True)
def restore_job_registries():
    with model3d_service._lock:
        model3d_jobs = dict(model3d_service._jobs)
        model3d_processes = dict(model3d_service._processes)
        model3d_service._jobs.clear()
        model3d_service._processes.clear()
    with rig_service._lock:
        rig_jobs = dict(rig_service._jobs)
        rig_processes = dict(rig_service._processes)
        rig_service._jobs.clear()
        rig_service._processes.clear()
    try:
        yield
    finally:
        with model3d_service._lock:
            model3d_service._jobs.clear()
            model3d_service._jobs.update(model3d_jobs)
            model3d_service._processes.clear()
            model3d_service._processes.update(model3d_processes)
        with rig_service._lock:
            rig_service._jobs.clear()
            rig_service._jobs.update(rig_jobs)
            rig_service._processes.clear()
            rig_service._processes.update(rig_processes)


@pytest.mark.parametrize(
    "status",
    ["queued", "waiting", "waiting_resource", "running", "cancelling"],
)
def test_model3d_active_states_block_the_model_cache(status):
    model3d_service._jobs["job"] = {
        "status": status,
        "model_id": "hunyuan3d-2.1",
    }

    assert model3d_service.has_active_jobs()
    assert model3d_service.has_active_jobs("hunyuan3d-2.1")
    assert not model3d_service.has_active_jobs("hunyuan3d-2-turbo")


def test_model3d_model_filter_covers_siblings_in_the_same_cache_repo():
    model3d_service._jobs["job"] = {
        "status": "running",
        "model_id": "hunyuan3d-2mini-fast",
    }

    assert model3d_service.has_active_jobs("hunyuan3d-2mini-turbo")
    assert not model3d_service.has_active_jobs("hunyuan3d-2.1")


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_model3d_terminal_jobs_do_not_block_cache_deletion(status):
    model3d_service._jobs["job"] = {
        "status": status,
        "model_id": "hunyuan3d-2.1",
    }

    assert not model3d_service.has_active_jobs("hunyuan3d-2.1")


def test_model3d_cancelled_job_blocks_until_its_worker_is_reaped():
    model3d_service._jobs["job"] = {
        "status": "cancelled",
        "model_id": "hunyuan3d-2.1",
    }
    model3d_service._processes["job"] = object()

    assert model3d_service.has_active_jobs("hunyuan3d-2.1")

    model3d_service._processes.pop("job")
    assert not model3d_service.has_active_jobs("hunyuan3d-2.1")


@pytest.mark.parametrize(
    "status",
    ["queued", "waiting", "waiting_resource", "running", "cancelling"],
)
def test_unirig_active_states_block_only_the_unirig_cache(status):
    rig_service._jobs["job"] = {
        "status": status,
        "engine": "unirig",
    }

    assert rig_service.has_active_jobs()
    assert rig_service.has_active_jobs("unirig")
    assert rig_service.has_active_unirig_jobs()
    assert not rig_service.has_active_jobs("procedural")


def test_procedural_rig_does_not_block_the_unirig_cache():
    rig_service._jobs["job"] = {
        "status": "running",
        "engine": "procedural",
    }

    assert rig_service.has_active_jobs()
    assert not rig_service.has_active_unirig_jobs()


def test_cancelled_unirig_job_blocks_until_its_worker_is_reaped():
    rig_service._jobs["job"] = {
        "status": "cancelled",
        "engine": "unirig",
    }
    rig_service._processes["job"] = object()

    assert rig_service.has_active_unirig_jobs()

    rig_service._processes.pop("job")
    assert not rig_service.has_active_unirig_jobs()
