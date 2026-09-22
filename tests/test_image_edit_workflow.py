"""Exercise legacy Qwen preparation without loading models or running inference."""
import ast
from copy import deepcopy
from pathlib import Path

import pytest

from services.image_edit_workflow import image_edit_capabilities, native_image_edit_params, validate_image_edit
from services.studio_image_spec import StudioImageParams
from tests.test_qwen_image_21 import _load_handler_class
from tests.test_studio_image_preparation import FakeResources, base_params, invoke


@pytest.fixture
def handler():
    return _load_handler_class()


@pytest.mark.parametrize("model,mode,method", [
    ("qwen_image_21", 1, 0), ("qwen_image_20B", 2, 2),
    ("qwen_image_edit_20B", 2, 1), ("qwen_image_edit_plus_20B", 2, 3),
    ("qwen_image_edit_plus2_20B", 2, 0),
])
@pytest.mark.parametrize("conditioning", ["mask", "outpaint"])
def test_public_image_commands_preserve_each_qwen_native_edit_method(handler, model, mode, method, conditioning):
    definition = handler.query_model_def(model, {})
    original = base_params(model_type=model, image_mode=1, seed=37, image_guide="/api/v1/uploads/source.png",
                           model_mode=method, image_mask="/api/v1/uploads/mask.png" if conditioning == "mask" else None,
                           video_guide_outpainting="0 10 0 0" if conditioning == "outpaint" else "",
                           video_prompt_type="VAG" if conditioning == "mask" else "V")
    resources = FakeResources(media_result=(deepcopy(original), []))
    (native, _), _ = invoke(original, definition=definition, resources=resources)
    assert native["image_mode"] == mode
    assert native["model_mode"] == method
    assert native["image_guide"] == original["image_guide"]
    assert native["video_guide_outpainting"] == original["video_guide_outpainting"]
    assert original["image_mode"] == 1
    # The translation happens after the frozen public contract, not by weakening it.
    public = {key: value for key, value in original.items() if key != "workspace"}
    if not public["video_guide_outpainting"]:
        del public["video_guide_outpainting"]
    StudioImageParams.model_validate(public)
    caps = image_edit_capabilities(definition)
    assert caps["outpaint_support"] and caps["image_source_support"]
    assert method in [item[1] for item in caps["image_edit_modes"]["choices"]]


@pytest.mark.parametrize("model", ["qwen_image_21", "qwen_image_edit_plus_20B", "qwen_image_edit_plus2_20B"])
def test_edit_and_reference_conditioning_survive_together(handler, model):
    definition = handler.query_model_def(model, {})
    params = base_params(image_mode=1, image_guide="/api/v1/uploads/source.png",
                         image_mask="/api/v1/uploads/mask.png", image_refs=["/api/v1/uploads/ref.png"],
                         video_prompt_type="VAGI", model_mode=0)
    resources = FakeResources(media_result=(deepcopy(params), []))
    (native, _), _ = invoke(params, definition=definition, resources=resources)
    assert native["image_refs"] == params["image_refs"]
    assert native["image_mask"] == params["image_mask"]


def test_old_inpainting_lora_is_selected_for_the_translated_request():
    tree = ast.parse(Path('app/models/qwen/qwen_main.py').read_text())
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'get_loras_transformer')
    from types import SimpleNamespace
    import os
    namespace = {'os': os, 'fl': SimpleNamespace(locate_file=lambda name: '/installed/' + name)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<native LoRA selector>', 'exec'), namespace)
    assert namespace['get_loras_transformer'](None, lambda *_: ['https://example.invalid/inpaint.safetensors'],
                                             'qwen_image_edit_20B', 1, 2) == (['/installed/inpaint.safetensors'], [1])
    assert namespace['get_loras_transformer'](None, lambda *_: [], 'qwen_image_edit_20B', 0, 1) == ([], [])


def test_layered_has_a_required_source_and_independent_layer_count(handler):
    definition = handler.query_model_def('qwen_image_layered_20B', {})
    caps = image_edit_capabilities(definition)
    assert caps['image_source_support'] and caps['image_source_required']
    assert caps['image_layer_count']['default'] == 4
    with pytest.raises(ValueError, match='requires a source'):
        validate_image_edit({}, definition)
    params = {'image_mode': 1, 'image_guide': '/api/v1/uploads/source.png', 'batch_size': 4}
    validate_image_edit(params, definition)
    assert native_image_edit_params(params, definition) == params
    with pytest.raises(ValueError, match='layer count'):
        validate_image_edit({**params, 'batch_size': 0}, definition)


def test_text_creation_and_unrelated_models_do_not_change_native_mode(handler):
    params = {'image_mode': 1, 'prompt': 'A synthetic cube'}
    for model in ('qwen_image_21', 'qwen_image_20B'):
        assert native_image_edit_params(params, handler.query_model_def(model, {})) == params
    assert native_image_edit_params(params, {}) == params


@pytest.mark.parametrize('source', [(800, 1600), (900, 2000), (1920, 1080), (1100, 2300)])
def test_qwen21_reference_fit_uses_the_same_32_grid_as_its_canvas(handler, source):
    definition = handler.query_model_def('qwen_image_21', {})
    assert definition['vae_block_size'] == 32
    utils = ast.parse(Path('app/shared/utils/utils.py').read_text())
    function = next(node for node in utils.body if isinstance(node, ast.FunctionDef) and node.name == 'calculate_new_dimensions')
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<dimension calculator>', 'exec'), namespace)
    main = ast.parse(Path('app/models/qwen/qwen21_main.py').read_text())
    call = next(node for node in ast.walk(main) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name) and node.func.id == 'calculate_new_dimensions')
    namespace.update(height=1024, width=1024, ref_w=source[0], ref_h=source[1], fit_into_canvas=0)
    dimensions = eval(compile(ast.Expression(call), '<actual Qwen fit call>', 'eval'), namespace)
    assert all(value % 32 == 0 for value in dimensions)
