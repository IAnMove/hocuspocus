"""Comic Director JSON parse, repair and generation.

Series planning, comics and Story call these. The bodies moved verbatim from
the full server. This module does not import WanGP or ``_launch_runtime``.
"""
from __future__ import annotations

import json

def _parse_comic_director_json(
    raw,
    stage: str,
    *,
    root_array_key: str | None = None,
) -> dict:
    if not isinstance(raw, str) or not raw.strip():
        raise RuntimeError(f"LLM returned no text while {stage}")
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as parse_error:
        from json_repair import repair_json
        print(
            f"[Comic Director] Repairing malformed {stage} JSON "
            f"at line {parse_error.lineno}, column {parse_error.colno}"
        )
        parsed = repair_json(cleaned, return_objects=True)
    # Some OpenAI-compatible providers occasionally honor an object schema by
    # returning either a one-item array or JSON encoded as a JSON string.
    # Normalize those losslessly before spending another provider request.
    if isinstance(parsed, str):
        nested = parsed.strip()
        if nested and nested != cleaned:
            try:
                parsed = json.loads(nested)
            except json.JSONDecodeError:
                from json_repair import repair_json
                parsed = repair_json(nested, return_objects=True)
    if not root_array_key and isinstance(parsed, list) and len(parsed) == 1:
        sole_item = parsed[0]
        if isinstance(sole_item, dict):
            print(f"[Comic Director] Unwrapped one-item array while {stage}")
            parsed = sole_item
    if root_array_key and isinstance(parsed, list):
        print(
            f"[Comic Director] Wrapped top-level array as "
            f"{root_array_key!r} while {stage}"
        )
        parsed = {root_array_key: parsed}
    if not isinstance(parsed, dict):
        raise ValueError(f"LLM response for {stage} is not a JSON object")
    return _repair_comic_text_encoding(parsed)

def _repair_comic_text_encoding(value):
    """Repair UTF-8 bytes that an older SSE decoder treated as Latin-1."""
    if isinstance(value, dict):
        return {key: _repair_comic_text_encoding(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_repair_comic_text_encoding(item) for item in value]
    if not isinstance(value, str) or not any(marker in value for marker in ("Ã", "Â", "â")):
        return value
    try:
        repaired = value.encode("latin-1").decode("utf-8")
        return repaired if repaired != value else value
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value

def _generate_comic_director_json(
    *,
    prompt: str,
    system_prompt: str,
    schema: dict,
    max_new_tokens: int,
    stage: str,
    llm_override: dict | None = None,
    root_array_key: str | None = None,
    image_paths: list[str] | None = None,
) -> dict:
    from services import llm_service
    # A streaming HTTP response resets the read timeout on every token.
    # This lets slow CPU-hosted Ollama models finish healthy generations
    # instead of losing all work after one ten-minute blocking request.
    common = {
        "prompt": prompt,
        "system_prompt": system_prompt,
        "max_new_tokens": max_new_tokens,
        "temperature": 0.2,
        "frequency_penalty": 0.25,
        "presence_penalty": 0.1,
        "json_schema": schema,
        "image_paths": image_paths or [],
    }
    parse_error = None
    for attempt in range(1, 3):
        request = dict(common)
        if parse_error is not None:
            # Remote OpenAI-compatible providers are stateless: they do not
            # know what they emitted on the previous request.  Give the
            # correction pass the actual response, rather than asking it to
            # regenerate the whole document from scratch.  The cap prevents
            # a pathological provider response from turning recovery into an
            # unbounded prompt-token bill.
            previous_response = raw.strip()
            previous_limit = 16000
            if len(previous_response) > previous_limit:
                previous_response = (
                    previous_response[:previous_limit]
                    + "\n[previous response truncated for bounded JSON repair]"
                )
            request["prompt"] = (
                f"{prompt}\n\nJSON CORRECTION RETRY: Your previous response could not be "
                "decoded as the required JSON object. Preserve every usable fact from the "
                "previous response and repair only its JSON structure. Return exactly one "
                "complete JSON object matching the supplied schema, with no prose, markdown "
                "or outer array.\n\nPREVIOUS RESPONSE TO REPAIR:\n"
                f"{previous_response}"
            )
            print(f"[Comic Director] Retrying malformed {stage} response once")
        if llm_override:
            raw = llm_service.generate_openai_compatible(
                **request,
                model_id=llm_override["model"],
                base_url=llm_override["base_url"],
                api_key=llm_override["api_key"],
            )
        else:
            raw = llm_service.generate_streaming(
                **request,
                enable_thinking=False,
                thinking_budget=0,
            )
        try:
            return _parse_comic_director_json(
                raw,
                f"{stage}, attempt {attempt}",
                root_array_key=root_array_key,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            parse_error = exc
            if attempt >= 2:
                raise
    raise parse_error  # pragma: no cover - the loop always returns or raises
