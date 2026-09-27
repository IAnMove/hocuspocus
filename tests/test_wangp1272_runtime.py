"""Small CPU contract tests at the WanGP adapters' temporal and model boundaries."""
import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_face_refiner_advertises_and_enforces_its_cuda_requirement(monkeypatch):
    import torch
    from postprocessing.h3_face_refiner.wgp_bridge import H3FaceRefinerBridge
    from postprocessing.processor_status import handler_reason_disabled, handler_status
    monkeypatch.setattr(torch.cuda, 'is_available', lambda: False)
    handler = H3FaceRefinerBridge({}, None)
    assert handler_status(handler) == 'disabled'
    assert 'CUDA' in handler_reason_disabled(handler)
    assert 'CUDA' in handler.validate_upsampling('h3facerefine', 0)


def engine_function(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text())
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), namespace)
    return namespace[name]


@pytest.mark.parametrize('real_frames,native_frames', [(3, 107), (124, 124), (19, 107), (87, 107)])
def test_viggle_guide_keeps_real_tail_and_pads_native_window(real_frames, native_frames):
    torch = pytest.importorskip('torch')
    prepare = engine_function('app/shared/utils/utils.py', 'prepare_video_guide_and_mask', {'torch': torch, 'to_rgb_tensor': lambda value, **kw: torch.tensor([value] * 3).reshape(3, 1, 1)})
    guide = torch.arange(real_frames).reshape(1, -1, 1, 1).expand(3, -1, 2, 2).float()
    videos, _ = prepare([guide], [None], None, (2, 2), native_frames, 17, frame_offset=5, pad_last_frame=True)
    output = videos[0]
    assert output.shape[1] == native_frames
    assert torch.equal(output[:, :real_frames], guide)
    assert torch.all(output[:, real_frames:] == real_frames - 1)
    if real_frames == 19:
        assert output[:, 17:].shape[1] == 90  # Viggle removes native history here.


def test_old_control_grid_and_short_clips_are_preserved():
    torch = pytest.importorskip('torch')
    prepare = engine_function('app/shared/utils/utils.py', 'prepare_video_guide_and_mask', {'torch': torch, 'to_rgb_tensor': lambda value, **kw: torch.tensor([value] * 3).reshape(3, 1, 1)})
    old = torch.zeros(3, 82, 2, 2)
    assert prepare([old], [None], None, (2, 2))[0][0].shape[1] == 81
    assert prepare([old[:, :3]], [None], None, (2, 2), latent_size=17, frame_offset=5)[0][0].shape[1] == 3


def test_rife_three_uses_actual_thirds_and_keeps_endpoints():
    torch = pytest.importorskip('torch')
    from postprocessing.rife import inference
    times = []
    class Model:
        supports_timestep = True
        def inference(self, a, b, timestep, scale):
            times.append(timestep)
            return a * (1 - timestep) + b * timestep
    original_ssim = inference.ssim_matlab
    inference.ssim_matlab = lambda *_: .5
    try:
        frames = torch.stack([torch.zeros(3, 32, 32), torch.ones(3, 32, 32)], dim=1)
        output = inference.process_frames(Model(), 'cpu', frames, 0, multiplier=3)
    finally:
        inference.ssim_matlab = original_ssim
    assert times == [1/3, 2/3]
    assert output.shape[1] == 4
    assert torch.allclose(output[:, 0], frames[:, 0])
    assert torch.allclose(output[:, -1], frames[:, -1])


def test_new_defaults_have_unique_ids_and_immutable_weight_revisions():
    names = ['viggle_animate', 'h3_advanced_fl2va_pruned', 'h3_advanced_ref2va_pruned', 'h3_advanced_vdn_pruned', 'sensenova_u1_5_8b_mot']
    for name in names:
        data = json.loads((ROOT / 'app/defaults' / f'{name}.json').read_text())
        assert data['model']['wangp_1272']
        assert '/resolve/main/' not in json.dumps(data)
    old = json.loads((ROOT / 'app/defaults/minimax_h3.json').read_text())
    assert not old['model'].get('wangp_1272')


@pytest.mark.parametrize('count', [1, 3, 48, 72, 108, 120, 124, 231])
def test_requested_duration_is_independent_of_native_padding(count):
    torch = pytest.importorskip('torch')
    from shared.wangp1272.timeline import trim_timeline, first_window_length
    model = {'wangp_1272': True, 'sliding_window_exact_total_frames': True, 'frames_minimum': 107,
             'frames_maximum': 124, 'frame_alignment_modulus': 17, 'frame_alignment_remainder': 5, 'frame_alignment_mode': 'ceil'}
    namespace = {}
    align = engine_function('app/wgp.py', 'align_model_frame_count', namespace)
    normalize = engine_function('app/wgp.py', 'normalize_model_total_frame_count', namespace)
    assert normalize(count, model) == count
    assert first_window_length(min(count, 124), model, align) in {107, 124}
    produced = 0
    while produced < count:
        remaining = count - produced
        native = first_window_length(min(remaining, 124), model, align)
        sample, audio, end = trim_timeline(torch.zeros(3, native, 1, 1), list(range(native)), produced + native,
            requested=count, produced=produced, fps=24, sample_rate=24, enabled=True,
            truncate_audio=lambda audio, _start, tail, _fps, _rate: audio[:-tail])
        produced += sample.shape[1]
        assert len(audio) == sample.shape[1]
        assert end == produced
    assert produced == count


def test_processor_settings_cannot_override_runtime_and_ranges_are_enforced(monkeypatch):
    from shared.wangp1272 import processors
    monkeypatch.setattr(processors.spatial_api, 'method_parameters', lambda _: [
        {'name': 'spatial_upsampler_face_count', 'type': 'integer', 'minimum': 0, 'maximum': 5},
        {'name': 'spatial_upsampler_h3_strength', 'type': 'number', 'minimum': 0, 'maximum': 1},
    ])
    assert processors.validated_settings('h3facerefine', {'main_offloadobj': 'bad', 'spatial_upsampler_face_count': 2}) == {'spatial_upsampler_face_count': 2}
    for value in (True, 1.5, -1, 6, float('nan')):
        with pytest.raises(ValueError):
            processors.validated_settings('h3facerefine', {'spatial_upsampler_face_count': value})


@pytest.mark.parametrize('audio_only,is_image,shape,expected_count', [
    (True, False, (160,), 12),
    (True, False, (2, 160), 12),
    (False, True, (3, 1, 2, 2), 12),
    (False, False, (3, 7, 2, 2), 19),
])
def test_postprocessing_clock_counts_video_frames_without_indexing_audio(audio_only, is_image, shape, expected_count):
    """Execute the engine's clock update without bootstrapping model services."""
    from types import SimpleNamespace

    tree = ast.parse((ROOT / 'app/wgp.py').read_text())
    statement_lists = (value for node in ast.walk(tree) for _, value in ast.iter_fields(node)
                       if isinstance(value, list) and value and isinstance(value[0], ast.stmt))
    for body in statement_lists:
        start = next((index for index, node in enumerate(body)
                      if isinstance(node, ast.Assign) and any(
                          isinstance(target, ast.Name) and target.id == 'postprocess_audio_offset'
                          for target in node.targets)), None)
        if start is not None:
            end = next(index for index in range(start + 1, len(body))
                       if isinstance(body[index], ast.Assign) and any(
                           isinstance(target, ast.Name) and target.id == 'output_fps'
                           for target in body[index].targets))
            statements = body[start:end]
            break
    else:
        raise AssertionError('Native postprocessing clock not found')
    sample = SimpleNamespace(shape=shape)
    namespace = {'sample': sample, 'audio_only': audio_only, 'is_image': is_image, 'native_frames_processed_count': 12}
    code = compile(ast.Module(body=statements, type_ignores=[]), 'native-postprocessing-clock', 'exec')
    exec(code, namespace)
    assert namespace['postprocess_audio_offset'] == 12
    assert namespace['native_frames_processed_count'] == expected_count
    assert namespace['sample'] is sample
    exec(code, namespace)
    assert namespace['postprocess_audio_offset'] == expected_count
    assert namespace['native_frames_processed_count'] == 12 + 2 * (expected_count - 12)


@pytest.mark.parametrize('method,still_image,height,expected_size', [
    ('lanczos2', True, 180, (640, 360)),
    ('lanczos2', True, 176, (640, 352)),
    ('lanczos1.5', True, 180, (480, 270)),
    ('lanczos2', False, 180, (640, 352)),
    ('vae1', True, 180, (160, 96)),
])
def test_lanczos_stills_keep_exact_dimensions_and_video_keeps_alignment(method, still_image, height, expected_size):
    from types import SimpleNamespace
    import numpy as np
    from PIL import Image

    torch = pytest.importorskip('torch')
    upscale = engine_function('app/wgp.py', 'perform_spatial_upsampling', {
        'torch': torch, 'np': np, 'Image': Image,
        'wangp_processors': SimpleNamespace(is_spatial=lambda _: False),
        'find_edit_spatial_upsampler': lambda _: None,
        'process_images_multithread': lambda fn, frames, *_args, **_kwargs: [fn(frame) for frame in frames],
        'get_default_workers': lambda: 1,
    })
    frame_count = 1 if still_image else 3
    sample = torch.full((3, frame_count, height, 320), 127, dtype=torch.uint8)
    result = upscale(sample, method, still_image=still_image)
    width, output_height = expected_size
    assert result.shape == (3, frame_count, output_height, width)
    assert result.dtype == torch.uint8
    assert torch.all(result == 127)


def _spatial_upsampling_still_image_value(function_name):
    tree = ast.parse((ROOT / 'app/wgp.py').read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
    calls = [
        node for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'perform_spatial_upsampling'
    ]
    assert len(calls) == 1, f'{function_name} should call perform_spatial_upsampling once'
    still_image = next((keyword.value for keyword in calls[0].keywords if keyword.arg == 'still_image'), None)
    assert still_image is not None, f'{function_name} must pass still_image into perform_spatial_upsampling'
    return still_image


def test_generate_video_forwards_image_mode_into_spatial_upsampling():
    still_image = _spatial_upsampling_still_image_value('generate_video')
    assert isinstance(still_image, ast.Name) and still_image.id == 'is_image'


def test_edit_video_marks_gallery_images_as_still_spatial_inputs():
    still_image = _spatial_upsampling_still_image_value('edit_video')
    assert isinstance(still_image, ast.Call)
    assert isinstance(still_image.func, ast.Name) and still_image.func.id == 'has_image_file_extension'
    assert [arg.id for arg in still_image.args if isinstance(arg, ast.Name)] == ['video_source']


@pytest.mark.parametrize('prompt_type,has_source,invalid', [('VO', False, True), ('VOAY', True, True), ('VO', True, False)])
def test_aligned_pose_validation_reports_invalid_inputs(prompt_type, has_source, invalid):
    from types import SimpleNamespace
    messages = []
    tree = ast.parse((ROOT / 'app/wgp.py').read_text(encoding='utf-8'))
    block = next(node for node in ast.walk(tree) if isinstance(node, ast.If)
                 and isinstance(node.test, ast.BoolOp)
                 and ast.unparse(node.test) == "'V' in video_prompt_type and 'O' in video_prompt_type")
    wrapper = ast.parse('def validate():\n    pass').body[0]
    wrapper.body = [block]
    namespace = {
        'video_prompt_type': prompt_type, 'image_start': object() if has_source else None,
        'video_source': None, 'all_letters': lambda value, chars: all(c in value for c in chars),
        'any_letters': lambda value, chars: any(c in value for c in chars),
        'gr': SimpleNamespace(Info=messages.append), 'ret': lambda: 'rejected',
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])), '<pose-validation>', 'exec'), namespace)
    assert namespace['validate']() == ('rejected' if invalid else None)
    assert bool(messages) == invalid
