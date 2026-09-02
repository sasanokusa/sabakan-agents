from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .models import Principal, ToolRequest, ToolResult, canonical_json


class AuditLogger:
    """Append-only-ish local audit store owned by the Broker."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                principal TEXT NOT NULL,
                session TEXT NOT NULL,
                model TEXT NOT NULL,
                host TEXT,
                tool TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                policy_result TEXT NOT NULL,
                approval_id TEXT,
                operation_hash TEXT,
                execution_result_json TEXT,
                before_state_json TEXT,
                after_state_json TEXT,
                verification_result_json TEXT,
                incident_id TEXT NOT NULL,
                event_type TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def record(
        self,
        request: ToolRequest,
        principal: Principal,
        *,
        policy_result: str,
        arguments: Mapping[str, Any],
        result: ToolResult,
        approval_id: str | None = None,
        operation_hash: str | None = None,
        before_state: Any = None,
        after_state: Any = None,
        verification_result: Any = None,
        event_type: str = "tool_call",
    ) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        values = (
            timestamp,
            principal.name,
            request.session_id,
            request.model,
            request.host(),
            request.tool,
            canonical_json(arguments),
            policy_result,
            approval_id,
            operation_hash,
            canonical_json(result.as_dict()),
            canonical_json(before_state),
            canonical_json(after_state),
            canonical_json(verification_result),
            request.incident_id,
            event_type,
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO audit_events (
                    timestamp, principal, session, model, host, tool,
                    arguments_json, policy_result, approval_id, operation_hash,
                    execution_result_json, before_state_json, after_state_json,
                    verification_result_json, incident_id, event_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            self._connection.commit()

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),)
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._connection.close()
