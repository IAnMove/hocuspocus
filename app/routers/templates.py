"""HTTP projection of the template library (``/api/v1/templates``).

The editors list, save, apply, export and import templates here; agents use the
same service through the MCP ``templates.*`` operations.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from services.template_commands import TemplateCommands, command_catalog
from services.template_format import TemplateError
from services.template_library import MAX_ZIP_BYTES


def create_templates_router(commands: TemplateCommands) -> APIRouter:
    router = APIRouter()
    library = commands.library

    async def run(name: str, payload: dict) -> dict:
        try:
            return (await run_in_threadpool(commands.execute, name, {"version": 1, "input": payload}))["result"]
        except TemplateError as error:
            raise HTTPException(error.status, {"code": error.code, "message": str(error)}) from error

    async def call(function, *args, **kwargs):
        try:
            return await run_in_threadpool(function, *args, **kwargs)
        except TemplateError as error:
            raise HTTPException(error.status, {"code": error.code, "message": str(error)}) from error

    async def json_body(request: Request, allowed: set[str]) -> dict:
        if len(await request.body()) > 8 * 1024 * 1024:
            raise HTTPException(413, "Request exceeds 8 MB")
        try:
            value = await request.json()
        except ValueError as error:
            raise HTTPException(422, "Request must be valid JSON") from error
        if not isinstance(value, dict):
            raise HTTPException(422, "Request must be a JSON object")
        return {key: item for key, item in value.items() if key in allowed}

    async def package_body(request: Request) -> bytes:
        data = await request.body()
        if not data:
            raise HTTPException(422, "Send the .hptemplate file as the request body")
        if len(data) > MAX_ZIP_BYTES:
            raise HTTPException(413, "Template package exceeds 64 MB")
        return data

    @router.get("/api/v1/templates/commands")
    def catalog():
        return {"version": 1, "operations": command_catalog()}

    @router.get("/api/v1/templates")
    async def list_templates(editor: str | None = None, tag: str | None = None, q: str | None = None):
        payload = {key: value for key, value in (("editor", editor), ("tag", tag), ("query", q)) if value}
        return await run("templates.list", payload)

    @router.post("/api/v1/templates")
    async def save_template(request: Request):
        from services.template_commands import OPERATIONS
        return await run("templates.save", await json_body(request, set(OPERATIONS["templates.save"][0])))

    @router.post("/api/v1/templates/preflight")
    async def preflight(request: Request):
        return await call(library.preflight, await package_body(request))

    @router.post("/api/v1/templates/import")
    async def import_template(request: Request, replace: bool = False):
        return await call(library.import_package, await package_body(request), replace=replace)

    @router.get("/api/v1/templates/{author}/{slug}")
    async def get_template(author: str, slug: str):
        return await run("templates.get", {"id": f"{author}/{slug}"})

    @router.delete("/api/v1/templates/{author}/{slug}")
    async def delete_template(author: str, slug: str):
        return await run("templates.delete", {"id": f"{author}/{slug}"})

    @router.post("/api/v1/templates/{author}/{slug}/apply")
    async def apply_template(author: str, slug: str, request: Request):
        payload = await json_body(request, {"workspace", "slots", "controls"})
        return await run("templates.apply", {"id": f"{author}/{slug}", **payload})

    @router.get("/api/v1/templates/{author}/{slug}/package")
    async def download_package(author: str, slug: str):
        name, data = await call(library.export, f"{author}/{slug}")
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @router.get("/api/v1/templates/{author}/{slug}/preview")
    async def preview(author: str, slug: str):
        return FileResponse(await call(library.preview_path, f"{author}/{slug}"))

    @router.get("/api/v1/templates/{author}/{slug}/media/{name}")
    async def media(author: str, slug: str, name: str):
        return FileResponse(await call(library.file, f"{author}/{slug}", f"media/{name}"))

    return router


__all__ = ["create_templates_router"]
