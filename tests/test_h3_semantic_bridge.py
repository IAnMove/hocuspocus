"""Math and request-boundary checks for the optional, default-off adapter."""
import pytest

pytest.importorskip("torch")

import torch
from models.minimax_h3 import semantic_bridge as bridge

NATIVE = {'architecture': 'minimax_h3'}


def test_disabled_is_exact_identity_and_never_resolves_assets(monkeypatch):
    marker = object()
    monkeypatch.setattr(bridge, '_asset_path', lambda: pytest.fail('disabled adapter must not resolve assets'))
    assert bridge.apply_bridge(marker, 0, model_def=NATIVE) is marker


@pytest.mark.parametrize('value', [True, False, float('nan'), float('inf'), -0.01, 1.01, 'bad', []])
def test_invalid_strength_rejected_before_any_inference(value):
    with pytest.raises(ValueError):
        bridge.validate_options(value, 'per_token', NATIVE)


@pytest.mark.parametrize('definition,model_type', [
    ({'architecture': 'wan'}, ''),
    ({'architecture': 'minimax_h3', 'omni_reference': True}, 'minimax_h3_ref2va'),
    ({'architecture': 'minimax_h3', 'minimax_h3_fused_turbo': True}, 'minimax_h3_fused_turbo'),
    (NATIVE, 'minimax_h3_legacy'),
])
def test_unsupported_model_rejects_enabled_adapter(definition, model_type):
    with pytest.raises(ValueError, match='supports standard H3'):
        bridge.validate_options(.1, 'per_token', definition, model_type)
    assert bridge.validate_options(0, 'per_token', definition, model_type) == 0


@pytest.mark.parametrize('mode', ['per_token', 'global', 'none'])
def test_blend_matches_published_rms_formula_without_mutating_native(mode):
    native = torch.tensor([[[1., 2., 3.], [5., -2., 1.]]], dtype=torch.bfloat16)
    projected = torch.tensor([[[4., -2., 6.], [1., 3., -4.]]])
    original = native.clone()
    expected = projected.clone()
    if mode == 'per_token':
        expected *= torch.sqrt(native.float().square().mean(-1, keepdim=True) + 1e-8) / torch.sqrt(projected.square().mean(-1, keepdim=True) + 1e-8)
    elif mode == 'global':
        expected *= torch.sqrt(native.float().square().mean() + 1e-8) / torch.sqrt(projected.square().mean() + 1e-8)
    expected = (native.float() + .15 * (expected - native.float())).to(native.dtype)
    actual = bridge.blend_projection(native, projected, .15, mode)
    torch.testing.assert_close(actual, expected)
    assert actual.dtype == native.dtype
    assert torch.equal(native, original)


def test_request_normalization_does_not_accept_boolean_strength():
    with pytest.raises(ValueError):
        bridge.normalize_request({'minimax_h3_semantic_bridge_alpha': True}, NATIVE)
    with pytest.raises(ValueError):
        bridge.normalize_request({'minimax_h3_semantic_bridge_alpha': .1, 'minimax_h3_semantic_bridge_magnitude': 'invalid'}, NATIVE)


def test_wrong_size_file_is_rejected(tmp_path):
    path = tmp_path / 'adapter.safetensors'
    path.write_bytes(b'not an adapter')
    with pytest.raises(ValueError, match='size'):
        bridge._verify(path)


@pytest.mark.parametrize('mode', [False, 0, [], {}, 'unknown'])
def test_magnitude_type_is_not_silently_coerced(mode):
    with pytest.raises(ValueError, match='magnitude'):
        bridge.normalize_request({'minimax_h3_semantic_bridge_magnitude': mode}, NATIVE)
