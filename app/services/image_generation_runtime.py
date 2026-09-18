"""Bind shared image commands to the existing native runtime, without a queue."""
from copy import deepcopy
import os
import threading

from services.image_generation_commands import ImageGenerationCommands, validate_image_model, command_error
from services.job_lifecycle import request_cancel


def create_image_generation_commands(runtime):
    def persist(job):
        runtime["_durable_generation_queue"].upsert({
            key: deepcopy(job[key]) for key in ("id", "status", "created_at", "params", "workspace", "provenance")
        })

    def dispatch(job):
        thread = threading.Thread(target=runtime["_run_generation_with_preparation"], args=(job["id"],),
                                  name=f"command-generation-{job['id']}", daemon=False)
        try:
            runtime["_jobs"][job["id"]] = job
            runtime["register_generation_job"](runtime["_gen_lock"], job)
            runtime["_cancel_h3_idle_release"]()
            thread.start()
        except Exception:
            if thread.ident is None:
                # This native Thread never started. Release its FIFO position
                # through the existing cancellation lifecycle and expose a
                # recoverable interruption, retaining the admission/snapshot.
                request_cancel(job, job_id=job["id"], active_states=runtime["_active_gen_states"])
                runtime["_jobs"].pop(job["id"], None)
                runtime["_task_registry"](job["workspace"]).update(
                    job["task_id"], status="interrupted", phase="dispatch_failed", force=True,
                    message="Worker could not start; use queue recovery", recoverable=True,
                )
            raise

    def execution_policy(workspace):
        try:
            runtime["execution_mode"].validate_generation(workspace)
        except runtime["execution_mode"].ExecutionModeError as error:
            raise command_error(409, "execution_policy", str(error)) from error

    def preflight(params):
        execution_policy(params["workspace"])
        validate_image_model(params, model_definition=runtime["wgp"].get_model_def,
                             model_downloaded=runtime["_check_model_downloaded"])

    def resources(media_kind="image"):
        from services.studio_image_resources import StudioImageResources
        from services.studio_speech_resources import StudioSpeechResources
        from services.studio_sfx_resources import StudioSfxResources
        from services.studio_video_resources import StudioVideoResources
        resource_type = {"image": StudioImageResources, "audio": StudioSpeechResources,
                         "video": StudioSfxResources, "studio_video": StudioVideoResources}[media_kind]
        return resource_type(
            workspace_dir=runtime["_workspace_dir"], uploads_dir=lambda: os.path.join(os.getcwd(), "uploads"),
            list_workspaces=runtime["_list_workspaces"], lora_search_dirs=runtime["wgp"].get_lora_search_dirs,
            lora_compatible=runtime["_lora_is_compatible_with_model"],
        )

    def prepare_studio(params):
        from services.studio_image_preparation import prepare_studio_image
        from shared.wangp1272 import processors
        return prepare_studio_image(
            params, model_definition=runtime["wgp"].get_model_def,
            model_downloaded=runtime["_check_model_downloaded"], resources=resources(),
            execution_policy=execution_policy, processor_capabilities=processors.capabilities,
            validate_processors=processors.validate_selection, processor_settings=processors.validated_settings,
        )

    def audio_operation(freeze_spec, prepare_audio, catalog):
        from services.native_generation_operation import NativeGenerationOperation

        def freeze(command):
            frozen = freeze_spec(command)
            effective = frozen["effective"]["input"]
            return frozen, {**deepcopy(effective["params"]), "workspace": effective["workspace"]}

        def prepare(params):
            return prepare_audio(params, model_definition=runtime["wgp"].get_model_def,
                                 model_downloaded=runtime["_check_model_downloaded"],
                                 resources=resources("audio"), execution_policy=execution_policy)

        return NativeGenerationOperation(freeze=freeze, prepare=prepare, catalog=catalog())

    from services.studio_speech_spec import freeze_studio_speech_spec
    from services.studio_speech_preparation import prepare_studio_speech
    from routers.studio_speech_commands import speech_command_catalog
    from services.studio_music_spec import freeze_studio_music_spec
    from services.studio_music_preparation import prepare_studio_music
    from routers.studio_music_commands import music_command_catalog
    from services.video_generation_commands import create_video_operation

    operations = {
        "generation.speech": audio_operation(freeze_studio_speech_spec, prepare_studio_speech, speech_command_catalog),
        "generation.music": audio_operation(freeze_studio_music_spec, prepare_studio_music, music_command_catalog),
        "generation.video": create_video_operation(
            runtime, resources=lambda: resources("studio_video"), execution_policy=execution_policy,
        ),
    }

    if callable(runtime.get("_run_generation")):
        from services.studio_sfx_commands import create_sfx_operation
        operations["generation.sfx"] = create_sfx_operation(
            runtime, resources=lambda: resources("video"), execution_policy=execution_policy,
        )

    if callable(runtime.get("tools_upscale")) and callable(runtime.get("_run_tool_upscale")):
        from services.tools_upscale_commands import create_tools_upscale_operation
        operations["tools.upscale"] = create_tools_upscale_operation(runtime)

    service = ImageGenerationCommands(
        registry=runtime["_task_registry"], prepare=runtime["generate"], preflight=preflight,
        make_job=runtime["_new_generation_job"], task_fields=runtime["_generation_task_fields"],
        dispatch=dispatch, persist_recovery=persist, active_job_ids=lambda: runtime["_jobs"].keys(),
        prepare_studio=prepare_studio, runtime_defaults=lambda: {"mode": "", **runtime["wgp"].primary_settings},
        operations=operations,
    )
    service.canonicalize_reference = lambda value, media_kind="image": resources(media_kind).canonicalize_legacy(value)
    return service
