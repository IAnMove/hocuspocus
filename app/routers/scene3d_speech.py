"""Small router mounted by the existing character-kit boundary, without loading AI runtimes."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from services.scene3d_speech import MAX_BYTES, SpeechAnalysisError, SpeechAnalysisUnavailable, analyze_voice
from services.speech_analysis_request import MAX_REQUEST_BYTES, speech_request


class SpeechMouthCue(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    value: str = Field(pattern="^[ABCDEFGHX]$")


class SpeechAnalysisResponse(BaseModel):
    mouthCues: list[SpeechMouthCue]
    recognizer: str = "phonetic"
    duration: float
    analysisSource: str = 'original'


def create_scene3d_speech_router() -> APIRouter:
    router = APIRouter()

    @router.get('/speech/capabilities')
    def capabilities():
        from services.vocal_isolation import isolation_capability
        from services.scene3d_speech import rhubarb_executable
        return {'rhubarb': bool(rhubarb_executable()), 'vocalIsolation': isolation_capability()}

    @router.post("/speech/analyze", response_model=SpeechAnalysisResponse)
    async def analyze(request: Request, isolate_vocals: bool = False):
        content_type = request.headers.get("content-type", "").split(";")[0]
        if content_type not in {"audio/wav", "application/json"}:
            raise HTTPException(415, "Expected audio/wav or application/json.")
        maximum = MAX_BYTES if content_type == "audio/wav" else MAX_REQUEST_BYTES
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > maximum:
                raise HTTPException(413, "Voice clip exceeds the 90-second limit.")
            data.extend(chunk)
        try:
            audio, options = speech_request(bytes(data), content_type)
            return await run_in_threadpool(analyze_voice, audio, isolate_vocals=isolate_vocals, **options)
        except SpeechAnalysisError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SpeechAnalysisUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    return router
