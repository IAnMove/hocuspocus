"""Atomic command admission in the canonical TaskRegistry database.

Receipts describe admission, not execution or published assets. The domain
executor still owns its worker and uses the existing resource scheduler.
"""
from __future__ import annotations

import copy
import hashlib
import json


class TaskCommandConflict(ValueError):
    """An intention already belongs to a different effective request."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _snapshot_digest(original, effective, receipt):
    return hashlib.sha256(_json([original, effective, receipt]).encode("utf-8")).hexdigest()


def _valid_dispatch_owner(owner):
    return owner is None or (isinstance(owner, str) and 1 <= len(owner) <= 160 and bool(owner.strip()))


# 1: legacy receipts without a content fingerprint. 2 and later: the receipt carries the spec's content
# fingerprint and its version (typed H3/LTX video, generation.video v3, uses 3).
FINGERPRINT_VERSIONS = (1, 2, 3)


def _valid_fingerprint(row, values):
    receipt = values["receipt"]
    if row["fingerprint_version"] == 1:
        return "fingerprintVersion" not in receipt
    return (row["fingerprint_version"] in FINGERPRINT_VERSIONS and receipt.get("fingerprintVersion") == row["fingerprint_version"]
            and receipt.get("contentFingerprint") == row["digest"]
            and receipt.get("commandVersion") == values["original"].get("version"))


def _decode_admission(row):
    try:
        values = {key: json.loads(row[key]) for key in ("original", "effective", "receipt")}
        receipt = values["receipt"]
        valid = (all(isinstance(value, dict) for value in values.values())
                 and receipt["version"] == 1 and receipt["commandId"] == row["intent_id"]
                 and receipt["operation"] == row["operation"] and receipt["status"] == "queued"
                 and receipt["taskIds"] == [row["task_id"]]
                 and receipt["result"]["task_id"] == row["task_id"]
                 and _valid_fingerprint(row, values)
                 and _valid_dispatch_owner(row["dispatch_owner"])
                 and row["snapshot_digest"] == _snapshot_digest(**values))
        if not valid:
            raise ValueError("Invalid admission snapshot")
        return {**dict(row), **values}
    except (ValueError, KeyError, TypeError) as error:
        raise OSError("Command admission storage is corrupt") from error


def _receipt(intent_id: str, operation: str, task: dict) -> dict:
    return {
        "version": 1, "commandId": intent_id, "operation": operation, "status": "queued",
        "entities": [], "artifacts": [], "taskIds": [task["id"]], "pipelineIds": [],
        "result": {"job_id": task["backend_job_id"], "task_id": task["id"],
                   "root_task_id": task["root_id"], "workspace": task["workspace"], "status": "queued"},
    }


class TaskCommandAdmission:
    """Mixin using TaskRegistry's connection, snapshot, event and lock helpers."""

    @staticmethod
    def _initialize_command_admissions(connection) -> None:
        connection.execute("""CREATE TABLE IF NOT EXISTS task_command_admissions (
            intent_id TEXT PRIMARY KEY,
            operation TEXT NOT NULL,
            fingerprint_version INTEGER NOT NULL,
            digest TEXT NOT NULL,
            task_id TEXT NOT NULL,
            original TEXT NOT NULL,
            effective TEXT NOT NULL,
            receipt TEXT NOT NULL,
            snapshot_digest TEXT NOT NULL,
            dispatch_owner TEXT
        )""")

    def command_admission(self, intent_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM task_command_admissions WHERE intent_id = ?", (intent_id,)).fetchone()
        if row is None:
            return None
        return _decode_admission(row)

    def command_admission_for_task(self, task_id: str) -> dict | None:
        """The admission that created ``task_id``, for recovery lists that start from tasks."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM task_command_admissions WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        return _decode_admission(row)

    def claim_command_dispatch(self, intent_id: str, owner: str) -> bool:
        """Claim initial dispatch once, after admission and before queue effects.

        A claimed command is never automatically stolen after a timeout. A
        process crash requires the existing explicit queue recovery choice.
        """
        if owner is None or not _valid_dispatch_owner(owner):
            raise ValueError("A runtime dispatch owner is required")
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute("""UPDATE task_command_admissions SET dispatch_owner = ?
                WHERE intent_id = ? AND dispatch_owner IS NULL AND task_id IN
                (SELECT id FROM tasks WHERE status = 'queued')""", (owner, intent_id)).rowcount
            connection.commit()
        return bool(changed)

    def command_recovery_candidates(self) -> list[dict]:
        """Project interrupted admissions whose runtime snapshot can be restored."""
        with self._connect() as connection:
            rows = connection.execute("""SELECT c.intent_id FROM task_command_admissions c
                JOIN tasks t ON t.id = c.task_id WHERE t.status = 'interrupted'
                ORDER BY t.created_at""").fetchall()
        return [self.command_admission(row["intent_id"]) for row in rows]

    def admit_command_task(self, *, intent_id: str, operation: str, digest: str,
                           original: dict, effective: dict, task_fields: dict, fingerprint_version: int = 1) -> dict:
        """Commit one task/event and its recoverable receipt, or replay it.

        The caller validates the domain specification and supplies trusted task
        fields. A new intention is independent of its content fingerprint.
        No queue/worker is invoked while this transaction is open.
        """
        if not all(isinstance(value, str) and value for value in (intent_id, operation, digest)):
            raise ValueError("Command identity, operation and fingerprint are required")
        if type(fingerprint_version) is not int or fingerprint_version not in FINGERPRINT_VERSIONS:
            raise ValueError("Unsupported command fingerprint version")
        # Validate serialization before opening a write transaction. Do not apply
        # the public task metadata truncation rules to literal command inputs.
        original_json, effective_json = _json(original), _json(effective)
        task = self._build_task(task_fields)
        if task["status"] != "queued" or not task["backend_job_id"]:
            raise ValueError("Command admission requires a queued task and exact backend job ID")
        receipt = _receipt(intent_id, operation, task)
        if fingerprint_version >= 2:
            receipt.update(commandVersion=original["version"], contentFingerprint=digest, fingerprintVersion=fingerprint_version)
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT * FROM task_command_admissions WHERE intent_id = ?", (intent_id,),
            ).fetchone()
            if previous is not None:
                previous = _decode_admission(previous)
                if (previous["operation"] != operation or previous["digest"] != digest
                        or previous["fingerprint_version"] != fingerprint_version):
                    raise TaskCommandConflict("intent_id was already used with different parameters or preconditions")
                connection.rollback()
                return {"receipt": previous["receipt"], "replayed": True}
            # This uses the same task snapshot and event insertion as ordinary
            # TaskRegistry.create. A collision never adopts another task.
            self._insert_task(connection, task, {"metadata"})
            connection.execute("""INSERT INTO task_command_admissions
                (intent_id, operation, fingerprint_version, digest, task_id, original, effective, receipt, snapshot_digest)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (intent_id, operation, fingerprint_version, digest, task["id"], original_json, effective_json, _json(receipt),
                 _snapshot_digest(original, effective, receipt)))
            connection.commit()
        self._after_task_created(task)
        return {"receipt": copy.deepcopy(receipt), "replayed": False}
