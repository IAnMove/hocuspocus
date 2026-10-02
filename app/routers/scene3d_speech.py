"""Small router mounted by the existing character-kit boundary, without loading AI runtimes."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from typing import Literal

from services.scene3d_speech import MAX_BYTES, SpeechAnalysisError, SpeechAnalysisUnavailable
from services.speech_alignment import SpeechEngine, analyze_voice, capabilities as speech_capabilities
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
    engine: Literal['phoneme', 'rhubarb']
    requestedEngine: SpeechEngine
    driver: str
    fallbackReason: str | None = None
    phonemes: list[dict] = Field(default_factory=list)
    quality: dict | None = None
    alignment: str | None = None


def create_scene3d_speech_router() -> APIRouter:
    router = APIRouter()

    @router.get('/speech/capabilities')
    def capabilities():
        return speech_capabilities()

    @router.post('/speech/phonemes/setup')
    async def setup(arguments: dict):
        from services.phoneme_commands import SETUP, command_handlers
        return await command_handlers(lambda _: None)[SETUP](arguments)

    @router.post("/speech/analyze", response_model=SpeechAnalysisResponse)
    async def analyze(request: Request, isolate_vocals: bool = False, engine: SpeechEngine = 'auto'):
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
            options.setdefault('engine', engine)
            return await run_in_threadpool(analyze_voice, audio, isolate_vocals=isolate_vocals, **options)
        except SpeechAnalysisError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SpeechAnalysisUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc

    return router
