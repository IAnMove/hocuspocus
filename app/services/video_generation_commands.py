"""Connect generation.video to native admission and the existing generation FIFO."""

from copy import deepcopy

from routers.studio_video_commands import video_command_catalog
from services.native_generation_operation import NativeGenerationOperation
from services.studio_video_preparation import prepare_studio_video
from services.video_generation_spec import freeze_video_generation_spec
from services.video_generation_v3 import prepare_video_generation_v3


def create_video_operation(runtime, *, resources, execution_policy):
    def freeze(command):
        frozen = freeze_video_generation_spec(command)
        effective = frozen["effective"]["input"]
        params = {**deepcopy(effective["params"]), "workspace": effective["workspace"]}
        if frozen["effective"].get("version") == 3:
            params["_video_v3"] = True
        return frozen, params

    def prepare(params):
        if params.get("_video_v3") is True:
            return prepare_video_generation_v3(
                params,
                model_definition=runtime["wgp"].get_model_def,
                model_downloaded=runtime["_check_model_downloaded"],
                resources=resources(),
                execution_policy=execution_policy,
            )
        return prepare_studio_video(
            params,
            model_definition=runtime["wgp"].get_model_def,
            model_downloaded=runtime["_check_model_downloaded"],
            resources=resources(),
            execution_policy=execution_policy,
        )

    return NativeGenerationOperation(
        freeze=freeze,
        prepare=prepare,
        catalog=video_command_catalog(),
        use_generation_defaults=False,
    )


__all__ = ["create_video_operation"]
