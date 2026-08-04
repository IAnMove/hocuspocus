"""Small, persistent client for MiniMax Music candidate generation."""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Any

import requests


API_URL = "https://api.minimax.io/v1/music_generation"
MODEL = "music-3.0"
ORIGINAL_MODELS = {"music-3.0", "music-2.6", "music-3.0-free", "music-2.6-free"}
COVER_MODELS = {"music-cover", "music-cover-free"}
ALLOWED_MODELS = ORIGINAL_MODELS | COVER_MODELS
MAX_COVER_BYTES = 50 * 1024 * 1024


class MiniMaxMusicError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _audio_bytes(response: dict[str, Any], session: requests.Session) -> bytes:
    value = str((response.get("data") or {}).get("audio") or "").strip()
    if not value:
        raise MiniMaxMusicError("MiniMax Music returned no audio")
    if value.startswith(("https://", "http://")):
        download = session.get(value, timeout=(15, 180))
        download.raise_for_status()
        audio = download.content
    else:
        try:
            audio = bytes.fromhex(value)
        except ValueError as exc:
            raise MiniMaxMusicError("MiniMax Music returned invalid audio data") from exc
    if not audio:
        raise MiniMaxMusicError("MiniMax Music returned an empty audio file")
    if len(audio) > 100 * 1024 * 1024:
        raise MiniMaxMusicError("MiniMax Music audio exceeds Maestro's 100 MB limit")
    return audio


def generate_candidates(
    *,
    api_key: str,
    prompt: str,
    lyrics: str,
    count: int,
    output_dir: str,
    instrumental: bool = False,
    model: str = MODEL,
    reference_audio_path: str | None = None,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Generate and persist 1–3 independently sampled song candidates."""
    if not str(api_key).strip():
        raise MiniMaxMusicError("Configure the MiniMax API key in Settings → Services first", 400)
    model = str(model or MODEL).strip()
    if model not in ALLOWED_MODELS:
        raise MiniMaxMusicError(f"Unsupported MiniMax Music model: {model}", 400)
    is_cover = model in COVER_MODELS
    prompt = str(prompt or "").strip()[:300]
    lyrics = str(lyrics or "").strip()[:3500]
    if not prompt:
        raise MiniMaxMusicError("A music style prompt is required", 400)
    if not is_cover and not instrumental and not lyrics:
        raise MiniMaxMusicError("Lyrics are required for a vocal song", 400)
    reference_audio = None
    if is_cover:
        reference_audio_path = str(reference_audio_path or "").strip()
        if not reference_audio_path or not os.path.isfile(reference_audio_path):
            raise MiniMaxMusicError("A valid reference audio file is required for a cover", 400)
        size = os.path.getsize(reference_audio_path)
        if size <= 0:
            raise MiniMaxMusicError("The cover reference audio file is empty", 400)
        if size > MAX_COVER_BYTES:
            raise MiniMaxMusicError("The cover reference exceeds MiniMax's 50 MB limit", 413)
        with open(reference_audio_path, "rb") as handle:
            reference_audio = base64.b64encode(handle.read()).decode("ascii")
        lyrics = lyrics[:1000]
    count = max(1, min(3, int(count or 1)))
    os.makedirs(output_dir, exist_ok=True)
    client = session or requests.Session()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "output_format": "hex",
        "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
    }
    if is_cover:
        payload["audio_base64"] = reference_audio
        if lyrics:
            payload["lyrics"] = lyrics
    else:
        payload["lyrics"] = "" if instrumental else lyrics
        payload["is_instrumental"] = bool(instrumental)
    results: list[dict[str, Any]] = []
    for index in range(count):
        try:
            raw = client.post(API_URL, headers=headers, json=payload, timeout=(20, 600))
        except requests.RequestException as exc:
            raise MiniMaxMusicError(f"MiniMax Music request failed: {exc}") from exc
        try:
            response = raw.json()
        except ValueError as exc:
            raise MiniMaxMusicError("MiniMax Music returned an invalid response", raw.status_code or 502) from exc
        base = response.get("base_resp") or {}
        if not raw.ok or int(base.get("status_code") or 0) != 0:
            message = str(base.get("status_msg") or response.get("message") or f"HTTP {raw.status_code}")
            raise MiniMaxMusicError(f"MiniMax Music rejected the request: {message}", raw.status_code or 502)
        audio = _audio_bytes(response, client)
        token = uuid.uuid4().hex[:12]
        filename = f"minimax-music-{time.strftime('%Y%m%d-%H%M%S')}-{index + 1}-{token}.mp3"
        path = os.path.join(output_dir, filename)
        with open(path, "wb") as handle:
            handle.write(audio)
        extra = response.get("extra_info") or {}
        metadata = {
            "provider": "minimax",
            "model": model,
            "prompt": prompt,
            "lyrics": lyrics,
            "instrumental": bool(instrumental),
            "mode": "cover" if is_cover else "original",
            "reference_audio_name": os.path.basename(reference_audio_path) if is_cover else None,
            "duration_seconds": float(extra.get("music_duration") or 0) / 1000,
            "trace_id": response.get("trace_id"),
            "created_at": time.time(),
        }
        with open(f"{path}.json", "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
        results.append({
            "filename": filename,
            "audio_path": path,
            "duration_seconds": metadata["duration_seconds"],
            "provider": "minimax",
            "model": model,
        })
    return results
