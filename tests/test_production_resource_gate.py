"""Shared-GPU admission waits; disk shortfalls stop before a generation."""
from types import SimpleNamespace

import pytest

from services.production_resource_gate import external_gpu_jobs, guard_mcp


def test_own_resident_model_is_excluded_but_external_jobs_above_limit_wait():
    assert external_gpu_jobs("11, 6000\n22, 1176\n33, 6200", 11, 2048) == [33]


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
