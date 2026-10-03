"""One engine policy, CPU lane and receipt for UI, Wizard and MCP lip sync."""
from __future__ import annotations

from typing import Literal
import uuid

from services import phoneme_analysis, phoneme_runtime, resource_scheduler, scene3d_speech
from services.speech_language import speech_language_code
from services.scene3d_speech import SpeechAnalysisError, SpeechAnalysisUnavailable, validate_voice_wav

SpeechEngine = Literal["auto", "phoneme", "rhubarb"]


def capabilities():
    from services.vocal_isolation import isolation_capability
    phonemes = phoneme_runtime.capabilities()
    rhubarb = bool(scene3d_speech.rhubarb_executable())
    return {"rhubarb": rhubarb, "phonemes": phonemes, "vocalIsolation": isolation_capability(),
            "defaultEngine": "phoneme" if phonemes["installed"] else "rhubarb" if rhubarb else None}


def setup_phonemes(install=False):
    if type(install) is not bool:
        raise ValueError("Use install as an explicit boolean")
    if not install:
        return phoneme_runtime.capabilities()
    with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("speech-install"),
                                                task_id=f"phoneme-install-{uuid.uuid4().hex}"):
        return phoneme_runtime.install()


def analyze_voice(data, isolate_vocals=False, dialogue="", language="", engine: SpeechEngine = "auto"):
    validate_voice_wav(data)
    if engine not in ("auto", "phoneme", "rhubarb"):
        raise SpeechAnalysisError("Use auto, phoneme or rhubarb for the speech engine.")
    if not isinstance(dialogue, str) or len(dialogue) > 4000 or "\x00" in dialogue:
        raise SpeechAnalysisError("Use up to 4000 exact dialogue characters.")
    if not isinstance(language, str) or len(language) > 16:
        raise SpeechAnalysisError("Use a language code up to 16 characters.")
    # Series/Story labels ("Español", "English") would otherwise reach eSpeak verbatim.
    language = speech_language_code(language)
    installed = phoneme_runtime.capabilities()["installed"] if engine != "rhubarb" else False
    selected = "phoneme" if engine == "phoneme" or engine == "auto" and installed else "rhubarb"
    if selected == "phoneme" and not installed:
        raise SpeechAnalysisUnavailable("Install the phoneme engine in Voice and lip-sync or with audio.phonemes.setup input.install=true.")
    analyzer = phoneme_analysis.analyze_voice if selected == "phoneme" else scene3d_speech.analyze_voice
    with resource_scheduler.coordinator.acquire(resource_scheduler.cpu_lane("speech-analysis"),
                                                task_id=f"speech-{uuid.uuid4().hex}"):
        result = analyzer(data, isolate_vocals=isolate_vocals, dialogue=dialogue, language=language)
    return {**result, "engine": selected, "requestedEngine": engine,
            "fallbackReason": "phoneme_not_installed" if engine == "auto" and not installed else None,
            "driver": selected + ("-vocals" if isolate_vocals else ""),
            "analysisSource": "isolated-vocals" if isolate_vocals else "original"}
