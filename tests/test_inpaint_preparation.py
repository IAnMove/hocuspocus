"""Exercise inpaint preparation without starting SAM or a generation worker."""
import ast
import asyncio
import os
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException


@pytest.mark.parametrize('resolution, scaled', [('960x544', True), ('', False)])
def test_inpaint_reads_source_before_sam_scaling(tmp_path, monkeypatch, resolution, scaled):
    handler, request, segment, jobs, ffmpeg = _inpaint(tmp_path, monkeypatch, resolution)
    result = asyncio.run(handler(request))
    assert result['status'] == 'queued'
    assert bool(ffmpeg.call_count) is scaled
    sam_path = segment.call_args.kwargs['video_path']
    assert sam_path.endswith('_sam_scaled.mp4') is scaled
    if scaled:
        assert 'scale=960:512:flags=lanczos' in ffmpeg.call_args.args[0]
        assert not Path(sam_path).exists()
    assert jobs[0]['params']['video_length'] == 120
    assert jobs[0]['params']['retake_end_frame'] == 120
    assert jobs[0]['params']['resolution'] == (resolution or '1920x1080')


def test_unreadable_source_fails_before_sam_is_started(tmp_path, monkeypatch):
    handler, request, segment, jobs, ffmpeg = _inpaint(tmp_path, monkeypatch, '960x544')
    monkeypatch.setitem(sys.modules, 'decord', SimpleNamespace(VideoReader=Mock(side_effect=ValueError('corrupt'))))
    with pytest.raises(HTTPException, match='Cannot read video') as error:
        asyncio.run(handler(request))
    assert error.value.status_code == 400
    sys.modules['services.inpaint_service'].ensure_sam_running.assert_not_called()
    segment.assert_not_called()
    ffmpeg.assert_not_called()
    assert jobs == []


def _inpaint(tmp_path, monkeypatch, resolution):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'video')
    masks = tmp_path / 'masks.npy'
    masks.write_bytes(b'mask')
    class Reader:
        def __init__(self, _path): pass
        def get_avg_fps(self): return 24
        def __len__(self): return 120
        def __getitem__(self, _index): return SimpleNamespace(shape=(1080, 1920, 3))
    monkeypatch.setitem(sys.modules, 'decord', SimpleNamespace(VideoReader=Reader))
    segment = Mock(return_value={'masks_path': str(masks)})
    sam = SimpleNamespace(check_sam_status=Mock(), parse_inpaint_intent=Mock(),
                          segment_video=segment, unload_sam=Mock(),
                          ensure_sam_running=Mock(return_value=True), shutdown_sam=Mock())
    monkeypatch.setitem(sys.modules, 'services.inpaint_service', sam)
    def scale(args, **_kwargs):
        Path(args[-1]).write_bytes(b'scaled')
        return SimpleNamespace(returncode=0)
    ffmpeg = Mock(side_effect=scale)
    monkeypatch.setattr('subprocess.run', ffmpeg)
    jobs = []
    namespace = {
        'os': os, 'time': time, 'uuid': uuid, 'Request': object, 'HTTPException': HTTPException,
        'api': SimpleNamespace(post=lambda *_: lambda fn: fn),
        'threading': SimpleNamespace(Thread=lambda **_: SimpleNamespace(start=lambda: None)),
        '_get_active_workspace': lambda: 'default', '_workspace_dir': lambda _: str(tmp_path),
        '_register_manual_generation_job': jobs.append, '_run_generation': lambda _: None,
        '_generation_job_acceptance': lambda _: {},
    }
    path = Path(__file__).resolve().parents[1] / 'app/_launch_runtime.py'
    node = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == 'inpaint_endpoint')
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    async def body():
        return {'video_path': str(source), 'description': 'a blue coat',
                'model_type': 'ltx2', 'sam_target': 'coat', 'resolution': resolution}
    return namespace['inpaint_endpoint'], SimpleNamespace(json=body), segment, jobs, ffmpeg
