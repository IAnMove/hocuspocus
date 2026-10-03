"""Optional asset library: list, install on request, cancel, and serve installed files by hash."""
import mimetypes
from pathlib import PurePosixPath

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from services.asset_library import ARCHIVE_HOSTS, AssetLibrary, asset_library
from services.example_collections import CollectionDownloads
from services.media_kinds import MEDIA_TYPES
from services.secure_download import opener_for

ACTION = "install-library"


def _require_action(request: Request) -> None:
    if request.headers.get("X-Hocus-Action") != ACTION:
        raise HTTPException(403, "Explicit download action required")


def create_asset_library_router(library: AssetLibrary = asset_library, opener=None) -> APIRouter:
    router = APIRouter(tags=["asset-library"])
    downloads = CollectionDownloads(library, opener=opener or opener_for(ARCHIVE_HOSTS),
                                    busy_message="Another library download is already running")

    @router.get("/api/v1/library")
    def catalog():
        """Catalog and installed state. Never downloads anything."""
        state = downloads.catalog()
        collections = [{**{key: value for key, value in row.items() if key != "gallery"}, **library.summary(row["id"])}
                       for row in state["collections"]]
        items = [item for row in collections if row["cached"] for item in library.items(row["id"])]
        return {"revision": library.revision, "collections": collections, "items": items, "job": state["job"]}

    @router.post("/api/v1/library/install", status_code=202)
    def install(body: dict, request: Request):
        _require_action(request)
        names = body.get("collections")
        if not isinstance(names, list) or not names or len(names) > 32 \
                or any(not isinstance(name, str) or name not in library.collections for name in names):
            raise HTTPException(422, "Choose known library collections")
        try:
            return downloads.start(names)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    @router.delete("/api/v1/library/install/{job_id}")
    def cancel(job_id: str, request: Request):
        _require_action(request)
        try:
            downloads.cancel(job_id)
        except KeyError:
            raise HTTPException(404, "Unknown download") from None
        return {"status": "cancelling"}

    @router.get("/api/v1/library/files/{key}")
    @router.head("/api/v1/library/files/{key}", include_in_schema=False)
    def installed_file(key: str, request: Request):
        name = library.file_for(key)
        if name is None:
            raise HTTPException(404, "Unknown library file")
        suffix = PurePosixPath(name).suffix.casefold()
        media_type = MEDIA_TYPES.get(suffix) or mimetypes.guess_type(name)[0] or "application/octet-stream"
        # The name is the content hash, so the bytes behind it never change.
        headers = {"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"}
        if request.method == "HEAD":
            return Response(media_type=media_type, headers={**headers, "Content-Length": str(library.entry(name)["size"])})
        path = library.cached(name)
        if path is None:
            raise HTTPException(409, "Install this collection from the library first",
                                headers={"Cache-Control": "no-store"})
        return FileResponse(path, media_type=media_type, headers=headers)

    return router
