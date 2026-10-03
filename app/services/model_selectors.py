"""Read closed selector values from the model definition already in use.

This is not a second catalog. Choice widgets on the model schema
(``choices``, ``selection``, ``values``) are the allowed set. A rejected
submission names that set, or a short prefix plus the model detail.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

_SHORT = 12

# name, request fields, schema keys, enforce on submit
_SPECS = (
    ("duration", ("duration", "duration_seconds"), ("duration", "duration_seconds", "duration_slider", "duration_choices"), True),
    ("size", ("size", "resolution"), ("size", "resolution"), True),
    ("fps", ("fps", "force_fps"), ("fps_choices", "force_fps_choices", "fps", "force_fps"), True),
    ("guidance", ("guidance", "guidance_scale"), ("guidance_choices", "guidance_scale", "guidance"), True),
    ("lora", ("lora", "activated_loras"), ("lora_choices", "lora"), True),
    ("sample_solver", ("sample_solver",), ("sample_solvers", "sample_solver"), True),
    ("model_mode", ("model_mode",), ("model_modes", "model_mode"), True),
    ("audio_prompt_type", ("audio_prompt_type",), ("audio_prompt_type_sources",), False),
    ("skip_steps_multiplier", ("skip_steps_multiplier",), ("skip_steps_multiplier_choices",), False),
    ("minimax_h3_text_encoder", ("minimax_h3_text_encoder",), ("minimax_h3_text_encoder_variants",), True),
    ("minimax_h3_reference_detail", ("minimax_h3_reference_detail",), ("omni_reference_detail_choices",), True),
)

_CONDITIONING = {
    "image_refs": ("video_prompt_type", "I", "image_ref_choices"),
    "image_guide": ("video_prompt_type", "V", "guide_custom_choices"),
    "image_mask": ("video_prompt_type", "VA", None),
    "image_start": ("image_prompt_type", "S", None),
    "image_end": ("image_prompt_type", "E", None),
}


class InvalidSelector(Exception):
    """Submitted selector is outside the model definition's allowed values."""

    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(detail.get("message", "invalid_selector"))


def _as_value(item):
    if isinstance(item, bool) or item is None:
        return None
    if isinstance(item, (int, float, str)):
        return item
    return None


def _is_url(value) -> bool:
    return isinstance(value, str) and ("://" in value or value.startswith("http"))


def _is_pair(item) -> bool:
    return isinstance(item, (list, tuple)) and len(item) >= 2 and _as_value(item[1]) is not None


def _is_value_mapping(item) -> bool:
    return isinstance(item, Mapping) and "value" in item and _as_value(item.get("value")) is not None


def _choice_value(item):
    if _is_pair(item):
        return _as_value(item[1])
    if _is_value_mapping(item):
        return _as_value(item.get("value"))
    return None


def _dedupe(values):
    unique = []
    seen = set()
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            marker = ("n", float(value))
        else:
            marker = ("s", value)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(value)
    return unique


def _pair_values(items):
    values = []
    for item in items:
        value = _choice_value(item)
        if value is None or _is_url(value):
            return []
        values.append(value)
    return _dedupe(values)


def _scalar_values(items):
    values = []
    for item in items:
        value = _as_value(item)
        if value is None or _is_url(value):
            return []
        values.append(value)
    return _dedupe(values)


def _from_sequence(items):
    if isinstance(items, (str, bytes)) or not isinstance(items, Sequence) or not items:
        return []
    if all(_is_pair(item) or _is_value_mapping(item) for item in items):
        return _pair_values(items)
    return _scalar_values(items)


def _variant_keys(node):
    keys = []
    for key, value in node.items():
        if isinstance(key, str) and isinstance(value, Mapping):
            keys.append(key)
    return keys


def _from_node(node, schema_key):
    if schema_key == "minimax_h3_text_encoder_variants" and isinstance(node, Mapping):
        return _variant_keys(node)
    if isinstance(node, Mapping):
        for key in ("choices", "selection", "values"):
            if key in node:
                return _from_sequence(node.get(key))
        return []
    return _from_sequence(node)


def _allowed_for_keys(model_def, keys):
    allowed = []
    for key in keys:
        if key not in model_def:
            continue
        allowed.extend(_from_node(model_def.get(key), key))
    return _dedupe(allowed)


def _entry_from_spec(model_def, spec):
    name, fields, keys, enforce = spec
    allowed = _allowed_for_keys(model_def, keys)
    if not allowed:
        return None
    return {"name": name, "fields": fields, "allowed": allowed, "enforce": enforce}


def _custom_entries(model_def):
    settings = model_def.get("custom_settings")
    if not isinstance(settings, list):
        return []
    entries = []
    for setting in settings:
        if not isinstance(setting, Mapping):
            continue
        kind = str(setting.get("type") or "").strip().lower()
        if kind not in {"dropdown", "choice", "enum"}:
            continue
        field = setting.get("id") or setting.get("name")
        allowed = _from_sequence(setting.get("choices"))
        if not isinstance(field, str) or not field.strip() or not allowed:
            continue
        entries.append({
            "name": field.strip(),
            "fields": (field.strip(),),
            "allowed": allowed,
            "enforce": True,
        })
    return entries


def _size_entry(model_def):
    allowed = _from_node(model_def.get("resolutions"), "resolutions")
    if not allowed:
        return None
    return {
        "name": "size",
        "fields": ("size", "resolution"),
        "allowed": allowed,
        "enforce": False,
    }


def _entries(model_def):
    if not isinstance(model_def, Mapping):
        return []
    entries = []
    seen = set()
    for spec in _SPECS:
        entry = _entry_from_spec(model_def, spec)
        if entry is None:
            continue
        entries.append(entry)
        seen.add(entry["name"])
    for entry in _custom_entries(model_def):
        if entry["name"] in seen:
            continue
        entries.append(entry)
        seen.add(entry["name"])
    if "size" not in seen:
        size = _size_entry(model_def)
        if size is not None:
            entries.append(size)
    return entries


def _conditioning(model_def):
    if not isinstance(model_def, Mapping):
        return {}
    letters = str(model_def.get("image_prompt_types_allowed") or "")
    hints = {}
    for field, (selector, requires, choice_key) in _CONDITIONING.items():
        present = bool(choice_key) and choice_key in model_def
        allowed = _from_node(model_def.get(choice_key), choice_key) if present else []
        letter_known = selector == "image_prompt_type" and requires in letters
        if not allowed and not present and not letter_known:
            continue
        item = {"selector": selector, "requires": requires}
        if allowed:
            item["allowed"] = allowed
        hints[field] = item
    return hints


def selector_catalog(model_def) -> dict:
    """Allowed selector values for the model detail an agent already requests."""
    catalog = {}
    for entry in _entries(model_def):
        catalog[entry["name"]] = {
            "allowed": list(entry["allowed"]),
            "fields": list(entry["fields"]),
        }
    hints = _conditioning(model_def)
    if hints:
        catalog["conditioning"] = hints
    return catalog


def _blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple)):
        return len(value) == 0
    return False


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _same(left, right) -> bool:
    if isinstance(left, str):
        left = left.strip()
    if isinstance(right, str):
        right = right.strip()
    if left == right:
        return True
    left_number = _number(left)
    right_number = _number(right)
    return left_number is not None and left_number == right_number


def _one_accepted(value, allowed) -> bool:
    for item in allowed:
        if _same(value, item):
            return True
    return False


def _accepted(value, allowed) -> bool:
    if isinstance(value, (list, tuple)):
        for item in value:
            if not _one_accepted(item, allowed):
                return False
        return True
    return _one_accepted(value, allowed)


def _format_value(value) -> str:
    if isinstance(value, str):
        return repr(value)
    return str(value)


def _payload(field, value, allowed, model_type):
    shown = list(allowed[:_SHORT])
    truncated = len(allowed) > _SHORT
    listed = ", ".join(_format_value(item) for item in shown)
    if truncated:
        message = (
            f"{field} {value!r} is not an allowed value. "
            f"Allowed values include: {listed}. "
            "See the model detail for the full set."
        )
    else:
        message = f"{field} {value!r} is not an allowed value. Allowed values: {listed}."
    detail = {
        "code": "invalid_selector",
        "message": message,
        "field": field,
        "allowed": shown,
        "retryable": False,
    }
    if truncated:
        detail["truncated"] = True
        detail["model_detail"] = "models"
    if isinstance(model_type, str) and model_type.strip():
        detail["model_type"] = model_type.strip()
    return detail


def _reject_value(field, value, allowed, model_type):
    if _blank(value) or _accepted(value, allowed):
        return
    raise InvalidSelector(_payload(field, value, allowed, model_type))


def _reject_entry(body, entry, model_type):
    allowed = entry["allowed"]
    nested = body.get("custom_settings")
    for field in entry["fields"]:
        if field in body:
            _reject_value(field, body.get(field), allowed, model_type)
        if isinstance(nested, Mapping) and field in nested:
            _reject_value(field, nested.get(field), allowed, model_type)


def validate_submitted_selectors(body, model_def):
    """Reject a submitted selector that is outside the model schema.

    Returns without enqueuing. Callers stop before a model runs.
    """
    if not isinstance(body, Mapping) or not isinstance(model_def, Mapping):
        return None
    model_type = body.get("model_type")
    for entry in _entries(model_def):
        if not entry["enforce"]:
            continue
        _reject_entry(body, entry, model_type)
    return None


def conditioning_hint(field, definition) -> str:
    """Sentence naming the native selector an image input requires."""
    row = _CONDITIONING.get(field)
    if row is None or not isinstance(definition, Mapping):
        return ""
    selector, letter, choice_key = row
    allowed = []
    if choice_key and choice_key in definition:
        allowed = _from_node(definition.get(choice_key), choice_key)
    shown = ", ".join(_format_value(item) for item in allowed[:_SHORT])
    extra = f" Allowed {selector} values: {shown}." if shown else ""
    more = " See the model detail for the full set." if len(allowed) > _SHORT else ""
    tail = "" if more else " See the model detail."
    return f" Set {selector} so it includes {letter}.{extra}{more}{tail}"
