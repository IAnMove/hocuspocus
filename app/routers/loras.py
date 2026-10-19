"""LoRA library routes, mounted where the launch module registered them."""
from __future__ import annotations

from fastapi import APIRouter, Request

from services import lora_library


def create_lora_library_router():
    """Directories through the update manifest, in the original order."""
    router = APIRouter()

    @router.get("/api/v1/loras/directories")
    def list_lora_directories():
        """Return all available LoRA directories for target selection during download."""
        return lora_library.list_lora_directories()

    @router.get("/api/v1/loras/preview/{filename}")
    def serve_lora_preview(filename: str):
        """Serve a locally downloaded LoRA preview file (video or image)."""
        return lora_library.serve_lora_preview(filename)

    @router.get("/api/v1/loras/installed")
    def list_all_installed_loras():
        """List ALL installed LoRAs across all directories with CivitAI metadata.

        Walks the primary loras root PLUS each linked install's loras root
        (issue #16: linked LoRAs never appeared in "My LoRAs" even though the
        guide scan processed them). Same enumeration and mirror convention as
        the scan: linked files are deduped against primary by relative key,
        and their sidecars/guides are read from the PRIMARY MIRROR path first
        (where the scan writes them, since linked installs stay read-only),
        then from beside the file itself.
        """
        return lora_library.list_all_installed_loras()

    @router.delete("/api/v1/loras/file")
    def delete_lora_file(directory: str, filename: str):
        """Delete an installed LoRA plus its sidecar, guide, and preview files.

        Takes the {directory, filename} pair exactly as /loras/installed
        reports it (directory is relative, "." for the root). Only files in
        the primary loras root are deletable — linked installs are read-only,
        same rule as checkpoint deletes.
        """
        return lora_library.delete_lora_file(directory, filename)

    @router.get("/api/v1/loras/{model_type}")
    def list_loras(model_type: str):
        """List available LoRA files for a model type."""
        return lora_library.list_loras(model_type)

    @router.get("/api/v1/loras/{model_type}/details")
    def list_loras_details(model_type: str):
        """List LoRAs with metadata from .civitai.json sidecars."""
        return lora_library.list_loras_details(model_type)

    @router.post("/api/v1/loras/nsfw-override")
    async def set_lora_nsfw_override(request: Request):
        """Manually flag a LoRA as SFW or NSFW, overriding CivitAI's nsfw value.

        CivitAI's model-level `nsfw` boolean is "worst content across the model"
        and gets set true if any version or example image is NSFW — even when
        the LoRA itself is SFW. Their browser uses a granular `nsfwLevel` int
        that we don't currently capture, so users with misclassified LoRAs need
        a way to correct the local sidecar.

        Body: `{"filename": "<basename>", "nsfw": true|false|null}`
          - `true` / `false`: write `nsfw_override` to sidecar
          - `null`: clear the override, fall back to CivitAI's flag

        Returns: `{filename, nsfw, nsfw_overridden}` — the new effective state.
        """
        return await lora_library.set_lora_nsfw_override(request)

    @router.post("/api/v1/loras/check-updates")
    def check_lora_updates(force: bool = False):
        """Walk all installed LoRAs, query CivitAI for the latest version of
        each one that has a sidecar `modelId`, and update the manifest with
        the results. Returns a summary the UI can display in a toast.

        Honors a 24h staleness window unless `force=true` is passed: a manifest
        less than 24h old is returned as-is so we don't hammer CivitAI on every
        app start. Uses a small thread pool for parallelism — typical libraries
        of <100 LoRAs finish in a few seconds.
        """
        return lora_library.check_lora_updates(force)

    @router.get("/api/v1/loras/update-manifest")
    def get_lora_update_manifest():
        """Return the cached manifest without hitting CivitAI. The frontend
        reads this on app start to populate badges immediately, and triggers
        /check-updates separately if the cache is stale."""
        return lora_library.get_lora_update_manifest()

    return router
