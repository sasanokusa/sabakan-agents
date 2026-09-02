from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class MutationStateStore:
    """Durable state for mutation budgets and circuit-breaker flags.

    Incident loop counters intentionally remain in :class:`MutationGuard` memory.
    This store contains only host/resource safety state, so restarting the Broker
    cannot silently reset a mutation budget or close an open circuit.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mutation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                host TEXT NOT NULL,
                resource TEXT,
                occurred_at REAL NOT NULL
            )
            """
        )
        self._connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_mutation_events_scope_target
            ON mutation_events(scope, host, resource, occurred_at)
            """
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mutation_flags (
                scope TEXT NOT NULL,
                host TEXT NOT NULL,
                resource TEXT NOT NULL DEFAULT '',
                flag TEXT NOT NULL,
                PRIMARY KEY(scope, host, resource)
            )
            """
        )
        self._connection.commit()

    def events(self, scope: str, host: str, resource: str | None = None) -> list[float]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT occurred_at FROM mutation_events
                WHERE scope = ? AND host = ? AND resource IS ?
                ORDER BY occurred_at ASC
                """,
                (scope, host, resource),
            ).fetchall()
        return [float(row[0]) for row in rows]

    def record_mutation(
        self,
        *,
        host: str,
        resource: str,
        occurred_at: float,
        record_host: bool,
        record_resource: bool,
    ) -> None:
        """Atomically persist the event(s) for one admitted mutation."""

        rows: list[tuple[str, str, str | None, float]] = []
        if record_host:
            rows.append(("host", host, None, occurred_at))
        if record_resource:
            rows.append(("resource", host, resource, occurred_at))
        if not rows:
            return
        with self._lock:
            try:
                self._connection.execute("BEGIN")
                self._connection.executemany(
                    "INSERT INTO mutation_events(scope, host, resource, occurred_at) VALUES (?, ?, ?, ?)",
                    rows,
                )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    def has_flag(self, scope: str, host: str, resource: str | None = None) -> bool:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT 1 FROM mutation_flags
                WHERE scope = ? AND host = ? AND resource = ?
                """,
                (scope, host, resource or ""),
            ).fetchone()
        return row is not None

    def set_flag(self, scope: str, host: str, resource: str | None, flag: str) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO mutation_flags(scope, host, resource, flag)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, host, resource) DO UPDATE SET flag = excluded.flag
                """,
                (scope, host, resource or "", flag),
            )
            self._connection.commit()

    def clear_flag(self, scope: str, host: str, resource: str | None = None) -> None:
        with self._lock:
            self._connection.execute(
                "DELETE FROM mutation_flags WHERE scope = ? AND host = ? AND resource = ?",
                (scope, host, resource or ""),
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()
