"""Shared-GPU admission waits; disk shortfalls stop before a generation."""
import threading
from types import SimpleNamespace

import pytest

from services.production_control import Cancelled
from services.production_resource_gate import (
    ResourceUnavailable, external_gpu_jobs, gpu_wait_seconds, guard_mcp, guard_workspace_mcp,
)


def test_own_resident_model_is_excluded_but_external_jobs_above_limit_wait():
    assert external_gpu_jobs("11, 6000\n22, 1176\n33, 6200", 11, 2048) == [33]


@pytest.mark.parametrize('operation', ['scenes.world3d.export', 'scenes.video2d.export'])
def test_cpu_scene_export_checks_disk_without_waiting_for_external_gpu(tmp_path, monkeypatch, operation):
    monkeypatch.setenv('HOCUS_SCENE_RENDER_DEVICE', 'cpu')
    monkeypatch.setenv('HOCUS_PRODUCTION_EXTERNAL_VRAM_MB', '2048')
    monkeypatch.setenv('HOCUS_PRODUCTION_MIN_FREE_GB', '15')
    production = SimpleNamespace(root=tmp_path, log=lambda _: None)
    submitted, commands = [], []
    def run(command, **_):
        commands.append(command)
        assert command[0] == 'df'
        return SimpleNamespace(stdout='Filesystem\nlocal 16G')
    free = SimpleNamespace(free=14 * 1024 ** 3)
    guarded = guard_mcp(production, lambda *args: submitted.append(args), run=run, usage=lambda _: free)
    with pytest.raises(ValueError, match='resource_disk_low'):
        guarded(operation, {})
    assert not submitted
    free.free = 16 * 1024 ** 3
    guarded(operation, {})
    assert len(submitted) == 1 and len(commands) == 2


def test_cpu_scene_mode_keeps_the_gpu_guard_for_music(tmp_path, monkeypatch):
    monkeypatch.setenv('HOCUS_SCENE_RENDER_DEVICE', 'cpu')
    monkeypatch.setenv('HOCUS_PRODUCTION_EXTERNAL_VRAM_MB', '2048')
    production = SimpleNamespace(root=tmp_path, log=lambda _: None)
    reports, waits, submitted = iter(['99999999, 6000', '99999999, 1176']), [], []
    guarded = guard_mcp(production, lambda *args: submitted.append(args),
                        run=lambda *_args, **_kwargs: SimpleNamespace(stdout=next(reports)),
                        sleep=lambda seconds: waits.append(seconds))
    guarded('generation.music', {})
    assert waits == [30] and len(submitted) == 1


def test_no_generation_is_submitted_until_external_gpu_clears(tmp_path, monkeypatch):
    monkeypatch.setenv('HOCUS_PRODUCTION_EXTERNAL_VRAM_MB', '2048')
    monkeypatch.setenv('HOCUS_PRODUCTION_MIN_FREE_GB', '15')
    production = SimpleNamespace(root=tmp_path, log=lambda _: None)
    submitted, waits, commands = [], [], []
    reports = iter(['99999999, 6000', '99999999, 1176'])

    def run(command, **_):
        commands.append(command)
        return SimpleNamespace(stdout=next(reports) if command[0] == 'nvidia-smi' else 'Filesystem\nlocal 16G')

    def sleep(seconds):
        assert not submitted
        waits.append(seconds)

    guarded = guard_mcp(production, lambda *args: submitted.append(args), run=run,
                        usage=lambda _: SimpleNamespace(free=16 * 1024 ** 3), sleep=sleep)
    guarded('scenes.world3d.export', {'version': 1})
    assert waits == [30] and len(submitted) == 1
    assert [c[0] for c in commands] == ['df', 'nvidia-smi', 'df', 'nvidia-smi']


def test_low_disk_stops_and_disabled_or_cpu_calls_do_not_probe(tmp_path, monkeypatch):
    monkeypatch.setenv('HOCUS_PRODUCTION_EXTERNAL_VRAM_MB', '2048')
    monkeypatch.setenv('HOCUS_PRODUCTION_MIN_FREE_GB', '15')
    production = SimpleNamespace(root=tmp_path, log=lambda _: None)
    submitted, commands = [], []

    def run(command, **_):
        commands.append(command)
        return SimpleNamespace(stdout='Filesystem\nlocal 14G')

    guarded = guard_mcp(production, lambda *args: submitted.append(args), run=run,
                        usage=lambda _: SimpleNamespace(free=14 * 1024 ** 3))
    with pytest.raises(ValueError, match='resource_disk_low'):
        guarded('generation.music', {})
    assert not submitted and len(commands) == 1
    guarded('scenes.world3d.export.receipt', {})
    assert len(commands) == 1 and len(submitted) == 1
    monkeypatch.delenv('HOCUS_PRODUCTION_MIN_FREE_GB')
    monkeypatch.delenv('HOCUS_PRODUCTION_EXTERNAL_VRAM_MB')
    guarded('generation.music', {})
    assert len(commands) == 1 and len(submitted) == 2


@pytest.mark.parametrize('operation', ['generation.speech', 'generation.sfx'])
def test_workspace_audio_generation_waits_before_admission(tmp_path, monkeypatch, operation):
    monkeypatch.setenv('HOCUS_PRODUCTION_EXTERNAL_VRAM_MB', '2048')
    monkeypatch.setenv('HOCUS_PRODUCTION_MIN_FREE_GB', '15')
    reports = iter(['99999999, 6000', '99999999, 1176'])
    submitted, waits, roots = [], [], []
    def run(command, **_):
        if command[0] == 'df':
            roots.append(command[-1])
            return SimpleNamespace(stdout='Filesystem\nlocal 16G')
        return SimpleNamespace(stdout=next(reports))
    guarded = guard_workspace_mcp(lambda *args: submitted.append(args), lambda ws: tmp_path / ws,
                                  run=run, usage=lambda _: SimpleNamespace(free=16 * 1024 ** 3),
                                  sleep=lambda seconds: waits.append(seconds))
    guarded(operation, {'version': 2, 'input': {'workspace': 'anime'}})
    assert waits == [30] and len(submitted) == 1
    assert roots == [str(tmp_path / 'anime')] * 2


def test_workspace_gate_requires_scope_only_for_resource_admissions():
    submitted = []
    def no_workspace(_):
        raise AssertionError('Receipt polling must not resolve a workspace')
    guarded = guard_workspace_mcp(lambda *args: submitted.append(args), no_workspace)
    guarded('jobs.wait', {'version': 1, 'input': {'job_id': 'job-1'}})
    assert len(submitted) == 1
    with pytest.raises(ValueError, match='resource_workspace_required'):
        guarded('generation.speech', {'version': 2, 'input': {}})
    assert len(submitted) == 1


def test_the_gpu_wait_has_a_default_limit_that_the_environment_can_change(monkeypatch):
    monkeypatch.delenv('HOCUS_PRODUCTION_GPU_WAIT_SECONDS', raising=False)
    assert gpu_wait_seconds() == 3600
    for raw, expected in (('90', 90), ('0', 0), ('-5', 3600), ('soon', 3600), ('inf', 3600), ('nan', 3600)):
        monkeypatch.setenv('HOCUS_PRODUCTION_GPU_WAIT_SECONDS', raw)
        assert gpu_wait_seconds() == expected, raw


def test_a_gpu_that_stays_busy_fails_the_admission_after_the_wait_limit(tmp_path, monkeypatch):
    monkeypatch.setenv('HOCUS_PRODUCTION_EXTERNAL_VRAM_MB', '2048')
    monkeypatch.setenv('HOCUS_PRODUCTION_GPU_WAIT_SECONDS', '75')
    lines, submitted, waits, now = [], [], [], [0.0]
    production = SimpleNamespace(root=tmp_path, log=lines.append)

    def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    guarded = guard_mcp(production, lambda *args: submitted.append(args),
                        run=lambda *_args, **_kwargs: SimpleNamespace(stdout='99999999, 6000'),
                        sleep=sleep, clock=lambda: now[0])
    with pytest.raises(ResourceUnavailable, match='resource_gpu_busy') as error:
        guarded('generation.image', {})
    # Polls every 30 s and never sleeps past the limit; a production records the ValueError as a failed, resumable run.
    assert waits == [30, 30, 15] and not submitted
    assert isinstance(error.value, ValueError) and '[99999999]' in str(error.value)
    assert 'HOCUS_PRODUCTION_GPU_WAIT_SECONDS=75' in str(error.value)


def test_a_zero_gpu_wait_limit_waits_until_the_gpu_is_free(tmp_path, monkeypatch):
    monkeypatch.setenv('HOCUS_PRODUCTION_EXTERNAL_VRAM_MB', '2048')
    monkeypatch.setenv('HOCUS_PRODUCTION_GPU_WAIT_SECONDS', '0')
    reports = iter(['99999999, 6000'] * 5 + ['99999999, 1176'])
    submitted, waits, now = [], [], [0.0]
    guarded = guard_mcp(SimpleNamespace(root=tmp_path, log=lambda _: None), lambda *args: submitted.append(args),
                        run=lambda *_args, **_kwargs: SimpleNamespace(stdout=next(reports)),
                        sleep=lambda seconds: waits.append(seconds) or now.__setitem__(0, now[0] + 99999),
                        clock=lambda: now[0])
    guarded('generation.music', {})
    assert waits == [30] * 5 and len(submitted) == 1


def test_a_cancel_ends_the_gpu_wait_without_submitting(tmp_path, monkeypatch):
    monkeypatch.setenv('HOCUS_PRODUCTION_EXTERNAL_VRAM_MB', '2048')
    probes, submitted = [], []

    def run(command, **_):
        probes.append(command)
        return SimpleNamespace(stdout='99999999, 6000')

    # A music production arms production._cancel for its run.
    cancel = threading.Event()
    production = SimpleNamespace(root=tmp_path, log=lambda _: None, _cancel=cancel)
    guarded = guard_mcp(production, lambda *args: submitted.append(args), run=run, sleep=lambda _seconds: cancel.set())
    with pytest.raises(Cancelled, match='waiting for the GPU'):
        guarded('generation.music', {})
    # A Series job says whether it was cancelled through ``cancelled``.
    flag = []
    guarded = guard_workspace_mcp(lambda *args: submitted.append(args), lambda ws: tmp_path / ws, cancelled=lambda: bool(flag),
                                  run=run, sleep=lambda _seconds: flag.append(True))
    with pytest.raises(Cancelled, match='waiting for the GPU'):
        guarded('generation.speech', {'version': 2, 'input': {'workspace': 'anime'}})
    assert len(probes) == 2 and not submitted
