"""Bounded CPU phoneme inference shared by browser, scene commands and MCP."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

from services import phoneme_runtime
from services.scene3d_speech import SpeechAnalysisUnavailable, validate_voice_wav
from services.speech_analysis_cache import remember


def _worker(pcm, dialogue, language):
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "", "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"}
    env.pop("HOCUS_MCP_TOKEN", None)
    body = {"pcm": base64.b64encode(pcm).decode(), "dialogue": dialogue,
            "language": "en-us" if language.lower() == "en" else language or "en-us"}
    result = subprocess.run([sys.executable, "-m", "services.phoneme_worker"],
                            cwd=Path(__file__).resolve().parents[1], env=env,
                            input=json.dumps(body).encode(), capture_output=True, timeout=360, check=False)
    if result.returncode:
        logging.getLogger(__name__).error("CPU phoneme worker failed: %s", result.stderr.decode(errors="replace")[-6000:])
        raise SpeechAnalysisUnavailable("CPU phoneme alignment failed; check the local runtime and transcript.")
    return result.stdout


def analyze_voice(data, dialogue="", language="", isolate_vocals=False):
    validate_voice_wav(data)
    isolation = None
    if isolate_vocals:
        from services.vocal_isolation import isolation_key_material
        isolation = isolation_key_material()
    material = {"kind": "phoneme-alignment-v1", "audio": hashlib.sha256(data).hexdigest(),
                "revision": phoneme_runtime.REVISION, "dialogue": dialogue, "language": language,
                "isolation": isolation}

    def infer():
        pcm = data
        if isolate_vocals:
            from services.vocal_isolation import isolate_voice
            pcm = isolate_voice(pcm)
        return _worker(pcm, dialogue, language)

    return json.loads(remember(material, infer, ".json"))
