"""The existing WAV endpoint also accepts a bounded audio + script envelope."""
import base64
import binascii
import json

from services.scene3d_speech import SpeechAnalysisError

MAX_REQUEST_BYTES = 4_100_000


def speech_request(data: bytes, content_type: str) -> tuple[bytes, dict]:
    if content_type == "audio/wav":
        return data, {}
    try:
        body = json.loads(data)
        dialogue, language = body.get("dialogue", ""), body.get("language", "")
        if not isinstance(dialogue, str) or len(dialogue) > 4000 or "\x00" in dialogue:
            raise ValueError("Invalid dialogue")
        if not isinstance(language, str) or len(language) > 16:
            raise ValueError("Invalid language")
        audio = base64.b64decode(body["wavBase64"], validate=True)
        return audio, {"dialogue": dialogue, "language": language}
    except (ValueError, TypeError, AttributeError, KeyError, binascii.Error) as exc:
        raise SpeechAnalysisError("Expected a WAV with up to 4000 script characters and a language code.") from exc
