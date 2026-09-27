from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool


def create_director_review_router(workspace_dir) -> APIRouter:
    router = APIRouter()

    @router.put("/api/v1/director/pipelines/{pid}/review")
    async def save(pid: str, request: Request):
        from services.director_pipeline import PipelineBusyError
        from services.director_review import save_review
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("workspace"), str):
                raise ValueError("Use an explicit review workspace")
            return await run_in_threadpool(save_review, workspace_dir(body["workspace"]), pid, body.get("commands"))
        except PipelineBusyError as error:
            raise HTTPException(409, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    return router
