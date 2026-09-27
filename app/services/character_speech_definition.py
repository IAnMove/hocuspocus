"""Public reusable 3D/voice metadata. No scene audio, credentials, or AI imports."""
import json
import math
import re
from urllib.parse import urlsplit, parse_qsl, unquote

CHARACTER_VOICE_LANGUAGES = {"auto", "chinese", "english", "japanese", "korean", "german", "french", "russian", "portuguese", "spanish", "italian"}


def _voice_reference_query(kind, raw):
    if kind == "uploads":
        if raw is not None:
            raise ValueError("Upload references cannot contain query parameters.")
        return
    query = parse_qsl(raw or "", keep_blank_values=True)
    if (len(query) != 1 or query[0][0] != "workspace"
            or not re.fullmatch(r"[A-Za-z0-9_. -]{1,120}", query[0][1]) or query[0][1] in {".", ".."}):
        raise ValueError("The reference recording needs its source workspace.")


def normalize_character_voice_reference(value):
    """Persistent same-origin audio only, with an explicit source workspace."""
    if not isinstance(value, str) or not value or len(value) > 1200 or re.search(r"\s|[\\#]", value):
        raise ValueError("Import a local reference recording first.")
    match = re.fullmatch(r"/api/v1/(uploads|file)/([^?]+)(?:\?(.+))?", value)
    if not match:
        raise ValueError("Use a persistent local reference recording.")
    if re.search(r"%(?![0-9a-fA-F]{2})", value):
        raise ValueError("Invalid reference recording URL.")
    try:
        path = unquote(match[2], errors="strict")
        unquote(match[3] or "", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("Invalid reference recording URL.") from error
    if (re.search(r"[\x00-\x1f\x7f\\%?#]", path) or any(not part or part.startswith(".") for part in path.split("/"))
            or not re.search(r"\.(wav|mp3|m4a|aac|flac|ogg|opus)$", path, re.I)):
        raise ValueError("Choose a local audio recording.")
    _voice_reference_query(match[1], match[3])
    return value


def _asset_fields(value):
    if not isinstance(value, dict):
        raise ValueError("A persistent asset reference is required.")
    if set(value) - {"workspaceId", "filename", "url", "assetId"}:
        raise ValueError("Invalid asset fields.")
    for key in ("workspaceId", "filename", "url"):
        if not isinstance(value.get(key), str) or not value[key] or len(value[key]) > 1200:
            raise ValueError("Invalid asset reference.")
    if "assetId" in value and (not isinstance(value["assetId"], str) or len(value["assetId"]) > 240):
        raise ValueError("Invalid asset identity.")


def _persistent_url(url):
    parsed = urlsplit(url)
    if not (url.startswith("/") and not url.startswith("//") or parsed.scheme in {"http", "https"} and parsed.netloc):
        raise ValueError("Use a persistent HTTP asset.")
    if parsed.username or parsed.password or any(ord(c) <= 32 or c == "\\" for c in url):
        raise ValueError("Credentials are not asset references.")
    if any(re.search(r"token|key|secret|signature", key, re.I) for key, _ in parse_qsl(parsed.query)):
        raise ValueError("Import the asset instead of saving credential-bearing URLs.")


def source_ref(value):
    _asset_fields(value)
    _persistent_url(value["url"])
    return dict(value)


def _vector(raw, length, low, high):
    return isinstance(raw, list) and len(raw) == length and all(
        type(n) in (int, float) and math.isfinite(n) and low <= n <= high for n in raw)


def _eye_placement(eyes):
    return (isinstance(eyes, dict) and set(eyes) == {"left", "right", "size", "skinLeft", "skinRight"}
            and all(_vector(eyes.get(k), 3, -10000, 10000) for k in ("left", "right"))
            and _vector(eyes.get("size"), 2, .00001, 10000)
            and all(_vector(eyes.get(k), 3, 0, 1) for k in ("skinLeft", "skinRight")))


def _face_placement(face):
    if (set(face) != {"meshIndex", "center", "size", "skin", "eyes"}
        or type(face["meshIndex"]) is not int or not 0 <= face["meshIndex"] <= 1023
        or not _eye_placement(face.get("eyes"))
        or not _vector(face.get("center"), 3, -10000, 10000)
        or not _vector(face.get("size"), 2, .00001, 10000)
        or not _vector(face.get("skin"), 3, 0, 1)):
        raise ValueError("Invalid face placement.")


def _face_style(value):
    if "atlas" in value:
        source_ref(value["atlas"])
    for key in ("clean", "blink", "eyes"):
        if key in value and type(value[key]) is not bool:
            raise ValueError("Invalid face switch.")
    if "strength" in value and (type(value["strength"]) not in (int, float) or not 0 <= value["strength"] <= 1.5):
        raise ValueError("Invalid face strength.")
    for key, choices in (("style", {"soft", "toon", "pixel"}), ("expression", {"neutral", "happy", "angry", "worried", "surprised", "sleepy"})):
        if key in value and (not isinstance(value[key], str) or value[key] not in choices):
            raise ValueError("Invalid face style.")
    if "lip" in value and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(value["lip"])):
        raise ValueError("Invalid lip color.")


def face_settings(value):
    allowed = {"face", "atlas", "strength", "clean", "style", "lip", "expression", "blink", "eyes"}
    if not isinstance(value, dict) or not isinstance(value.get("face"), dict) or not set(value).issubset(allowed):
        raise ValueError("Only face settings may be stored.")
    _face_placement(value["face"])
    _face_style(value)
    if len(json.dumps(value, allow_nan=False)) > 24000:
        raise ValueError("Face profile too large.")
    return value


def normalize_speech3d(value):
    if not isinstance(value, dict) or set(value) - {"model", "digest", "settings"}:
        raise ValueError("Invalid 3D character definition.")
    model = source_ref(value.get("model"))
    if not model["filename"].lower().endswith(".glb") or not re.fullmatch("[a-f0-9]{64}", str(value.get("digest", ""))):
        raise ValueError("Save a GLB with its content digest.")
    result = {"model": model, "digest": value["digest"]}
    if value.get("settings") is not None:
        result["settings"] = face_settings(value["settings"])
    return result


def _voice_text(value, limit):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _normalize_reference_voice(value):
    if (set(value) != {"provider", "model", "voiceId", "name", "referenceAudio", "transcript", "language"}
            or value.get("provider") != "local" or value.get("voiceId") != "reference"
            or not _voice_text(value.get("name"), 120) or not _voice_text(value.get("transcript"), 4000)
            or not isinstance(value.get("language"), str) or value["language"] not in CHARACTER_VOICE_LANGUAGES):
        raise ValueError("Add a named local reference recording, its transcript and a supported language.")
    return {**value, "name": value["name"].strip(), "transcript": value["transcript"].strip(),
            "referenceAudio": normalize_character_voice_reference(value["referenceAudio"])}


def normalize_character_voice(value):
    if isinstance(value, dict) and value.get("model") == "qwen3_tts_base":
        return _normalize_reference_voice(value)
    if not isinstance(value, dict) or set(value) - {"provider", "model", "voiceId", "instructions"}:
        raise ValueError("Store voice preferences only, never credentials.")
    if value.get("provider") != "local" or value.get("model") != "qwen3_tts_customvoice":
        raise ValueError("Choose a supported local character voice.")
    if value.get("voiceId") not in {"vivian", "serena", "uncle_fu", "dylan", "eric", "ryan", "aiden", "ono_anna", "sohee"}:
        raise ValueError("Invalid voice preset.")
    if "instructions" in value and (not isinstance(value["instructions"], str) or len(value["instructions"]) > 1000):
        raise ValueError("Voice instructions are too long.")
    return dict(value)
