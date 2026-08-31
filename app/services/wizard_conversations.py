"""Durable Wizard conversation storage, one file per workspace.

Compare-and-swap revisions follow the Story Library contract so two tabs
cannot silently overwrite each other. The payload is the chat the Wizard
reconstructs on reload, including execution cards and job links.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any


CONVERSATION_FILENAME = ".wizard-conversation-v1.json"
MAX_MESSAGES = 80
MAX_BYTES = 2 * 1024 * 1024
_LOCK = threading.RLock()


class WizardConversationRevisionConflict(ValueError):
    def __init__(self, expected: int, current: int):
        super().__init__(
            f"Wizard conversation revision conflict: expected {expected}, current {current}"
        )
        self.expected = expected
        self.current = current


def empty_conversation() -> dict[str, Any]:
    return {
        "version": 1,
        "revision": 0,
        "messages": [],
        "executions": [],
        "requestedActions": [],
        "executedActions": [],
        "confirmations": [],
    }


def _clean_text(value: Any, limit: int) -> str:
    text = str(value or "")
    if any(ord(char) < 32 and char not in "\n\t" for char in text):
        text = "".join(char for char in text if ord(char) >= 32 or char in "\n\t")
    return text[:limit]


def _clean_card(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    state = str(value.get("state") or "")
    if state not in {"prepared", "queued", "running", "completed", "partial", "failed"}:
        return None
    card = {
        "id": _clean_text(value.get("id"), 200),
        "state": state,
        "message": _clean_text(value.get("message"), 4000),
        "recoverable": value.get("recoverable") is True,
        "executionKey": _clean_text(value.get("executionKey"), 500),
        "taskId": _clean_text(value.get("taskId"), 200),
        "pipelineId": _clean_text(value.get("pipelineId"), 200),
        "outputNames": [
            _clean_text(name, 300)
            for name in (value.get("outputNames") or [])[:40]
            if isinstance(name, str)
        ],
    }
    target = value.get("target")
    if isinstance(target, dict) and target.get("id"):
        card["target"] = {
            "kind": _clean_text(target.get("kind"), 80),
            "id": _clean_text(target.get("id"), 200),
            "title": _clean_text(target.get("title"), 300),
        }
    controls = value.get("controls")
    if isinstance(controls, dict):
        card["controls"] = {
            "open": controls.get("open") is True,
            "cancel": controls.get("cancel") is True,
            "resume": controls.get("resume") is True,
            "viewErrors": controls.get("viewErrors") is True,
            "retryPending": controls.get("retryPending") is True,
        }
    return card


def _clean_message(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    role = str(value.get("role") or "")
    if role not in {"user", "assistant"}:
        return None
    message_id = _clean_text(value.get("id"), 200)
    text = _clean_text(value.get("text"), 8000)
    created = value.get("createdAt")
    if not message_id or not text:
        return None
    if not isinstance(created, (int, float)):
        created = 0
    cards = []
    for raw_card in value.get("cards") or []:
        card = _clean_card(raw_card)
        if card:
            cards.append(card)
    return {
        "id": message_id,
        "role": role,
        "text": text,
        "createdAt": int(created),
        "cards": cards,
        "executionKey": _clean_text(value.get("executionKey"), 500),
        "jobLinks": [
            {
                "taskId": _clean_text(link.get("taskId"), 200),
                "pipelineId": _clean_text(link.get("pipelineId"), 200),
            }
            for link in (value.get("jobLinks") or [])[:20]
            if isinstance(link, dict)
        ],
        "lastState": _clean_text(value.get("lastState"), 40),
        "error": _clean_text(value.get("error"), 2000),
    }


def normalize_conversation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Wizard conversation must be a JSON object")
    revision = value.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Wizard conversation revision must be a non-negative integer")
    messages = []
    for raw in value.get("messages") or []:
        message = _clean_message(raw)
        if message:
            messages.append(message)
        if len(messages) >= MAX_MESSAGES:
            break
    executions = []
    for raw in value.get("executions") or []:
        card = _clean_card(raw)
        if card:
            executions.append(card)
    return {
        "version": 1,
        "revision": revision,
        "messages": messages,
        "executions": executions[:80],
        "requestedActions": list(value.get("requestedActions") or [])[:80],
        "executedActions": list(value.get("executedActions") or [])[:80],
        "confirmations": list(value.get("confirmations") or [])[:80],
    }


def conversation_path(workspace_dir: str) -> str:
    return os.path.join(workspace_dir, CONVERSATION_FILENAME)


def read_conversation(workspace_dir: str) -> dict[str, Any]:
    path = conversation_path(workspace_dir)
    with _LOCK:
        if not os.path.isfile(path):
            return empty_conversation()
        with open(path, "r", encoding="utf-8") as handle:
            return normalize_conversation(json.load(handle))


def write_conversation(
    workspace_dir: str,
    value: Any,
    *,
    base_revision: int,
) -> dict[str, Any]:
    if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision < 0:
        raise ValueError("baseRevision must be a non-negative integer")
    conversation = normalize_conversation(value)
    with _LOCK:
        current = read_conversation(workspace_dir)
        current_revision = int(current["revision"])
        if base_revision != current_revision:
            raise WizardConversationRevisionConflict(base_revision, current_revision)
        conversation["revision"] = current_revision + 1
        encoded = json.dumps(conversation, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_BYTES:
            raise ValueError("Wizard conversation is too large to save")
        os.makedirs(workspace_dir, exist_ok=True)
        path = conversation_path(workspace_dir)
        temporary = f"{path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                if os.path.isfile(temporary):
                    os.remove(temporary)
            except OSError:
                pass
        return conversation


def reconstruct_cards(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    """Rebuild execution cards from the canonical record."""
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in conversation.get("messages") or []:
        for card in message.get("cards") or []:
            key = str(card.get("executionKey") or card.get("id") or "")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            cards.append(card)
    for card in conversation.get("executions") or []:
        key = str(card.get("executionKey") or card.get("id") or "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        cards.append(card)
    return cards
