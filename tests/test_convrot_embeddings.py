"""Exercise real MMGP loading: text embeddings must return to the model's basis."""
import json

import pytest
import torch
from mmgp import offload, quant_router
from shared.qtypes import int8_convrot


def load_embedding(model, rotated=True, group=4):
    quant_router.register_handler('shared.qtypes.int8_convrot')
    rows = torch.tensor([[2, 4, 6, 8], [-2, 0, 2, 4], [8, 2, -4, 6]], dtype=torch.int8)
    config = {'format': 'int8_tensorwise', 'convrot': rotated, 'convrot_groupsize': group}
    state = {
        'ordinary.weight': model.ordinary.weight.detach().clone(),
        'embed.weight': rows,
        'embed.weight_scale': torch.tensor([.5, 1., 2.]),
        'embed.comfy_quant': torch.tensor(list(json.dumps(config).encode()), dtype=torch.uint8),
    }
    offload.load_model_data(model, (state, None), default_dtype=torch.float32, verboseLevel=0)
    return rows.float() * torch.tensor([.5, 1., 2.])[:, None]


def model_with_embedding():
    model = torch.nn.Module()
    model.embed = torch.nn.Embedding(3, 4)
    model.ordinary = torch.nn.Embedding(3, 4)
    return model


@pytest.mark.parametrize('rotated', [True, False])
def test_loaded_embedding_inverts_only_checkpoint_rotation(rotated):
    model = model_with_embedding()
    ordinary = model.ordinary(torch.tensor([0, 2])).detach().clone()
    rows = load_embedding(model, rotated)
    # Independent explicit regular H4; do not compute expected via the handler.
    h = torch.tensor([[1, 1, 1, -1], [1, 1, -1, 1], [1, -1, 1, 1], [-1, 1, 1, 1.]]) / 2
    ids = torch.tensor([[2, 0], [1, 2]])
    expected = rows[ids] @ h if rotated else rows[ids]
    with torch.inference_mode():
        torch.testing.assert_close(model.embed(ids), expected)
        torch.testing.assert_close(model.ordinary(torch.tensor([0, 2])), ordinary)
        # Re-loading must not apply the inverse twice, including after offload.
        load_embedding(model, rotated)
        torch.testing.assert_close(model.embed(ids), expected)


def test_reloading_plain_weights_removes_owned_rotation_hook():
    model = model_with_embedding()
    load_embedding(model)
    rows = load_embedding(model, False)
    torch.testing.assert_close(model.embed(torch.tensor([0, 2])), rows[[0, 2]])


def test_invalid_embedding_group_fails_during_load_not_during_inference():
    with pytest.raises(ValueError, match='Invalid ConvRot embedding group'):
        load_embedding(model_with_embedding(), group=16)
