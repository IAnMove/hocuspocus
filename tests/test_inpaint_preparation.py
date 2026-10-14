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


def test_inpaint_finds_a_gallery_filename_in_the_named_workspace(tmp_path, monkeypatch):
    film = tmp_path / 'film'
    film.mkdir()
    source = film / 'hero-clip.mp4'
    source.write_bytes(b'video')
    handler, request, _segment, jobs, _ffmpeg = _inpaint(
        tmp_path, monkeypatch, '',
        source=source,
        workspace_dir=lambda ws: str(film) if ws == 'film' else str(tmp_path / 'missing'),
        body={'video_path': 'hero-clip.mp4', 'workspace': 'film', 'description': 'a blue coat',
              'model_type': 'ltx2', 'sam_target': 'coat'},
    )
    result = asyncio.run(handler(request))
    assert result['status'] == 'queued'
    assert jobs[0]['params']['retake_video'] == str(source)
    assert jobs[0]['workspace'] == 'film'


def test_inpaint_still_finds_an_uploads_filename(tmp_path, monkeypatch):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    source = uploads / 'dropped.mp4'
    source.write_bytes(b'video')
    handler, request, _segment, jobs, _ffmpeg = _inpaint(
        tmp_path, monkeypatch, '',
        source=source,
        cwd=tmp_path,
        workspace_dir=lambda _ws: str(tmp_path / 'empty-workspace'),
        body={'video_path': 'dropped.mp4', 'description': 'a blue coat',
              'model_type': 'ltx2', 'sam_target': 'coat'},
    )
    result = asyncio.run(handler(request))
    assert result['status'] == 'queued'
    assert jobs[0]['params']['retake_video'] == str(source)


def test_segment_preview_finds_a_gallery_filename_in_the_named_workspace(tmp_path, monkeypatch):
    from services import studio_segmentation

    film = tmp_path / 'film'
    film.mkdir()
    source = film / 'hero-clip.mp4'
    source.write_bytes(b'video')
    preview = Mock(return_value={'mask_preview': 'abc', 'masks_path': str(tmp_path / 'mask.npy'), 'frame_index': 0})
    sam = SimpleNamespace(check_sam_status=Mock(), segment_image_preview=preview, segment_video=Mock(),
                          ensure_sam_running=Mock(return_value=True))
    monkeypatch.setitem(sys.modules, 'services.inpaint_service', sam)
    monkeypatch.setattr(studio_segmentation, '_workspace_dir', lambda ws: str(film) if ws == 'film' else str(tmp_path))
    monkeypatch.setattr(studio_segmentation, '_get_active_workspace', lambda: 'default')

    async def body():
        return {'video_path': 'hero-clip.mp4', 'text': 'the coat', 'workspace': 'film'}

    result = asyncio.run(studio_segmentation.segment_preview_endpoint(SimpleNamespace(json=body)))
    assert result['target'] == 'the coat'
    assert preview.call_args.kwargs['video_path'] == str(source)


def test_segment_preview_takes_its_launch_objects_through_one_keyword_only_bind(monkeypatch):
    """bind() fills every slot the module starts at None, and nothing is bound by position."""
    import inspect
    from services import studio_segmentation

    tree = ast.parse(inspect.getsource(studio_segmentation))
    slots = {
        target.id for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value is None
        for target in node.targets if isinstance(target, ast.Name)
    }
    assert slots == {'_get_active_workspace', '_workspace_dir'}
    parameters = inspect.signature(studio_segmentation.bind).parameters
    assert all(item.kind is inspect.Parameter.KEYWORD_ONLY for item in parameters.values())
    assert {f'_{name}' for name in parameters} == slots

    for slot in slots:
        monkeypatch.setattr(studio_segmentation, slot, None)
    given = {name: object() for name in parameters}
    studio_segmentation.bind(**given)
    assert {slot: getattr(studio_segmentation, slot) for slot in slots} == {f'_{name}': value for name, value in given.items()}
    with pytest.raises(TypeError):
        studio_segmentation.bind(object(), object())


def _inpaint(tmp_path, monkeypatch, resolution, *, source=None, body=None, workspace_dir=None, cwd=None):
    source = source or (tmp_path / 'source.mp4')
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
    if cwd is not None:
        monkeypatch.setattr(os, 'getcwd', lambda: str(cwd))
    jobs = []
    namespace = {
        'os': os, 'time': time, 'uuid': uuid, 'Request': object, 'HTTPException': HTTPException,
        'api': SimpleNamespace(post=lambda *_: lambda fn: fn),
        'threading': SimpleNamespace(Thread=lambda **_: SimpleNamespace(start=lambda: None)),
        '_get_active_workspace': lambda: 'default',
        '_workspace_dir': workspace_dir or (lambda _: str(tmp_path)),
        '_register_manual_generation_job': jobs.append, '_run_generation': lambda _: None,
        '_generation_job_acceptance': lambda _: {},
    }
    path = Path(__file__).resolve().parents[1] / 'app/services/studio_edit_requests.py'
    node = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                if isinstance(n, ast.AsyncFunctionDef) and n.name == 'inpaint_endpoint')
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    payload = body or {'video_path': str(source), 'description': 'a blue coat',
                       'model_type': 'ltx2', 'sam_target': 'coat', 'resolution': resolution}
    async def request_body():
        return payload
    return namespace['inpaint_endpoint'], SimpleNamespace(json=request_body), segment, jobs, ffmpeg
