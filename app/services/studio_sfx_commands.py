"""Connect SFX to the existing native facade, admission and generation FIFO."""
from copy import deepcopy
from pathlib import Path

from services.native_generation_operation import NativeGenerationOperation
from services.studio_sfx_preparation import prepare_studio_sfx
from services.studio_sfx_resources import missing_mmaudio_files, validate_mmaudio_files
from services.studio_sfx_spec import SFX_MODEL_VARIANTS, freeze_studio_sfx_spec, studio_sfx_schema


def sfx_command_catalog():
    schema = studio_sfx_schema()
    input_schema = dict(schema["input"])
    definitions = input_schema.pop("$defs", {})
    return {
        "name": "generation.sfx", "version": 2, "supportedVersions": [2],
        "domain": "studio", "mutation": True,
        "description": "Generate sound effects with installed MMAudio files in an explicit output workspace. Preserve literal prompts. Text-only requests produce audio with a duration up to 20 seconds; video-guided requests use the inspected video duration and produce a video with new audio. Sources require canonical references. Reuse intent_id only to recover an existing admission; follow its task for completion.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "$defs": definitions,
            "properties": {"version": {"type": "integer", "const": 2},
                           "operation": {"const": "generation.sfx"},
                           "intent_id": schema["intent_id"], "input": input_schema},
            "required": ["version", "operation", "intent_id", "input"],
        },
    }


def sfx_file_exists(runtime, filename):
    """Use the same installed-file locator as MMAudio, without creating paths."""
    locator = getattr(getattr(runtime["wgp"], "fl", None), "locate_file", None)
    if not callable(locator):
        raise ValueError("The installed MMAudio file locator is unavailable")
    path = locator(filename, error_if_none=False)
    return bool(path and Path(path).is_file() and Path(path).stat().st_size > 0)


def check_sfx_models(runtime, variant):
    return validate_mmaudio_files(variant, lambda filename: sfx_file_exists(runtime, filename))


def create_sfx_operation(runtime, *, resources, execution_policy):
    def freeze(command):
        frozen = freeze_studio_sfx_spec(command)
        effective = frozen["effective"]["input"]
        return frozen, {**deepcopy(effective["params"]), "workspace": effective["workspace"]}

    def model_downloaded(model_type):
        return not missing_mmaudio_files(model_type, lambda filename: sfx_file_exists(runtime, filename))

    def prepare(params):
        return prepare_studio_sfx(
            params, model_definition={
                name: {"model_type": name, "architecture": "mmaudio", "variant": variant}
                for name, variant in SFX_MODEL_VARIANTS.items()
            }, model_downloaded=model_downloaded, resources=resources(), execution_policy=execution_policy,
        )

    return NativeGenerationOperation(
        freeze=freeze, prepare=prepare, catalog=sfx_command_catalog(),
        # Selecting a registered worker first verifies the canonical admission
        # in ImageGenerationCommands.native_worker, including during recovery.
        worker=runtime["_run_generation"], use_generation_defaults=False,
    )
