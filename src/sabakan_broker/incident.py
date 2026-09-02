from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .models import canonical_json


class AgentState(str, Enum):
    RECEIVE = "RECEIVE"
    OBSERVE = "OBSERVE"
    DIAGNOSE = "DIAGNOSE"
    PROPOSE = "PROPOSE"
    POLICY_CHECK = "POLICY_CHECK"
    AUTO = "AUTO"
    APPROVAL = "APPROVAL"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RE_DIAGNOSE = "RE-DIAGNOSE"
    REPORT = "REPORT"


_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.RECEIVE: frozenset({AgentState.OBSERVE}),
    AgentState.OBSERVE: frozenset({AgentState.DIAGNOSE}),
    AgentState.DIAGNOSE: frozenset({AgentState.PROPOSE, AgentState.RE_DIAGNOSE}),
    AgentState.PROPOSE: frozenset({AgentState.POLICY_CHECK}),
    AgentState.POLICY_CHECK: frozenset({AgentState.AUTO, AgentState.APPROVAL, AgentState.FAILED}),
    AgentState.AUTO: frozenset({AgentState.EXECUTE, AgentState.FAILED}),
    AgentState.APPROVAL: frozenset({AgentState.EXECUTE, AgentState.FAILED}),
    AgentState.EXECUTE: frozenset({AgentState.VERIFY, AgentState.FAILED}),
    AgentState.VERIFY: frozenset({AgentState.SUCCESS, AgentState.RE_DIAGNOSE, AgentState.FAILED}),
    AgentState.SUCCESS: frozenset({AgentState.REPORT}),
    AgentState.FAILED: frozenset({AgentState.REPORT, AgentState.RE_DIAGNOSE}),
    AgentState.RE_DIAGNOSE: frozenset({AgentState.OBSERVE}),
    AgentState.REPORT: frozenset(),
}


@dataclass
class Incident:
    incident_id: str
    objective: str
    current_state: AgentState = AgentState.RECEIVE
    observations: list[Any] = field(default_factory=list)
    hypotheses: list[Any] = field(default_factory=list)
    operations: list[Any] = field(default_factory=list)
    mutation_budget: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    updated_at: str = ""


class IncidentStateStore:
    """Structured incident memory; raw LLM history is intentionally not stored."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                objective TEXT NOT NULL,
                current_state TEXT NOT NULL,
                observations_json TEXT NOT NULL,
                hypotheses_json TEXT NOT NULL,
                operations_json TEXT NOT NULL,
                mutation_budget_json TEXT NOT NULL,
                verification_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def create(self, incident_id: str, objective: str) -> Incident:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO incidents (
                    incident_id, objective, current_state, observations_json,
                    hypotheses_json, operations_json, mutation_budget_json,
                    verification_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (incident_id, objective, AgentState.RECEIVE.value, "[]", "[]", "[]", "{}", "{}", now),
            )
            self._connection.commit()
        return self.get(incident_id)  # type: ignore[return-value]

    def get(self, incident_id: str) -> Incident | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)).fetchone()
        if row is None:
            return None
        return Incident(
            incident_id=row["incident_id"],
            objective=row["objective"],
            current_state=AgentState(row["current_state"]),
            observations=json.loads(row["observations_json"]),
            hypotheses=json.loads(row["hypotheses_json"]),
            operations=json.loads(row["operations_json"]),
            mutation_budget=json.loads(row["mutation_budget_json"]),
            verification=json.loads(row["verification_json"]),
            updated_at=row["updated_at"],
        )

    def transition(self, incident_id: str, target: AgentState) -> Incident:
        current = self.get(incident_id)
        if current is None:
            raise KeyError(f"incident does not exist: {incident_id}")
        if target not in _TRANSITIONS[current.current_state]:
            raise ValueError(f"invalid incident transition {current.current_state.value} -> {target.value}")
        current.current_state = target
        self._save(current)
        return current

    def append_observation(self, incident_id: str, observation: Any) -> Incident:
        current = self._required(incident_id)
        current.observations.append(observation)
        self._save(current)
        return current

    def append_hypothesis(self, incident_id: str, hypothesis: Any) -> Incident:
        current = self._required(incident_id)
        current.hypotheses.append(hypothesis)
        self._save(current)
        return current

    def append_operation(self, incident_id: str, operation: Any) -> Incident:
        current = self._required(incident_id)
        current.operations.append(operation)
        self._save(current)
        return current

    def set_verification(self, incident_id: str, verification: Any) -> Incident:
        current = self._required(incident_id)
        current.verification = dict(verification) if isinstance(verification, dict) else {"result": verification}
        self._save(current)
        return current

    def _required(self, incident_id: str) -> Incident:
        value = self.get(incident_id)
        if value is None:
            raise KeyError(f"incident does not exist: {incident_id}")
        return value

    def _save(self, incident: Incident) -> None:
        incident.updated_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._connection.execute(
                """
                UPDATE incidents SET current_state = ?, observations_json = ?,
                    hypotheses_json = ?, operations_json = ?, mutation_budget_json = ?,
                    verification_json = ?, updated_at = ? WHERE incident_id = ?
                """,
                (
                    incident.current_state.value,
                    canonical_json(incident.observations),
                    canonical_json(incident.hypotheses),
                    canonical_json(incident.operations),
                    canonical_json(incident.mutation_budget),
                    canonical_json(incident.verification),
                    incident.updated_at,
                    incident.incident_id,
                ),
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()
