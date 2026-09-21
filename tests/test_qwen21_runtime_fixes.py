import pytest
from models.qwen.autoencoder_kl_qwenimage21 import AutoencoderKLQwenImage21
from shared.utils.generation_timing import inference_progress_clock


@pytest.mark.parametrize('precision32,tile', [(False, 512), (True, 256)])
def test_auto_vae_keeps_4090_tiled_even_at_native_2k(precision32, tile):
    assert AutoencoderKLQwenImage21.get_VAE_tile_size(0, 24075, precision32, 2048, 2048) == (True, tile)
    assert AutoencoderKLQwenImage21.get_VAE_tile_size(0, 8000, precision32, 1024, 1024) == (True, 256)
    assert AutoencoderKLQwenImage21.get_VAE_tile_size(1, 24075, precision32, 2048, 2048) == (False, 256)


def test_inference_clock_excludes_loading_and_restarts_for_next_image():
    assert inference_progress_clock({}, 'Encoding Reference Images', 0, 500) == {}
    job = {'phase': 'Encoding Reference Images', 'step': 0}
    job.update(inference_progress_clock(job, 'Denoising | 2m', 0, 510))
    assert job['inference_started_at'] == 510
    job.update(phase='Denoising | 2m', step=1)
    assert inference_progress_clock(job, 'Denoising | 2m 2s', 2, 512) == {}
    assert inference_progress_clock(job, 'VAE Decoding', 40, 550) == {}
    job.update(phase='VAE Decoding', step=40)
    assert inference_progress_clock(job, 'Denoising', 0, 600)['inference_started_at'] == 600


def test_masked_source_latents_expand_to_output_batch():
    import types
    import torch
    from PIL import Image
    from models.qwen.pipeline_qwenimage21 import QwenImage21Pipeline

    encoded = torch.arange(32, dtype=torch.float32).reshape(1, 2, 1, 4, 4)
    pipeline = types.SimpleNamespace(
        vae_scale_factor=16,
        _as_vae_tensor=lambda *_: torch.zeros(1, 4, 1, 64, 64),
        _encode_vae_image=lambda *_: encoded,
        _pack_latents=QwenImage21Pipeline._pack_latents,
    )
    mask, original, first_step, _ = QwenImage21Pipeline._prepare_local_edit(
        pipeline, Image.new('L', (64, 64), 255), Image.new('RGBA', (64, 64)),
        64, 64, 2, 2, torch.float32, 'cpu', torch.Generator().manual_seed(1), .5, 1, 40,
    )
    assert original.shape == (2, 16, 2)
    torch.testing.assert_close(original[0], original[1])
    assert mask.shape == (1, 16, 1)
    assert first_step == 20


def test_native_cancel_property_reaches_qwen_pipeline():
    import types
    from models.qwen.qwen21_main import model_factory
    model = object.__new__(model_factory)
    model.pipeline = types.SimpleNamespace(interrupt=False)
    model._interrupt = True
    assert model.pipeline.interrupt is True
    model._interrupt = False
    assert model.pipeline.interrupt is False
