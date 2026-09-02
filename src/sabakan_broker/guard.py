from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from .guard_store import MutationStateStore
from .models import ToolRequest
from .policy import BudgetRule


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    code: str = "ALLOWED"
    reason: str = ""


class MutationGuard:
    """Resource/host mutation budgets and incident tool-loop limits."""

    def __init__(
        self,
        *,
        host_rule: Callable[[str], BudgetRule | None],
        resource_rule: Callable[[str], BudgetRule | None],
        max_tool_calls: int = 20,
        max_identical_tool_repeat: int = 2,
        max_wall_time_seconds: float = 300,
        max_mutations: int = 3,
        clock: Callable[[], float] = time.time,
        state_store: MutationStateStore | None = None,
    ):
        self._host_rule = host_rule
        self._resource_rule = resource_rule
        self._max_tool_calls = max_tool_calls
        self._max_identical_tool_repeat = max_identical_tool_repeat
        self._max_wall_time_seconds = max_wall_time_seconds
        self._max_mutations = max_mutations
        self._clock = clock
        self._state_store = state_store
        self._lock = threading.RLock()
        self._host_events: dict[str, deque[float]] = defaultdict(deque)
        self._resource_events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._open_hosts: set[str] = set()
        self._suspended_resources: set[tuple[str, str]] = set()
        self._loaded_hosts: set[str] = set()
        self._loaded_resources: set[tuple[str, str]] = set()
        self._incidents: dict[str, dict[str, object]] = {}

    @staticmethod
    def _trim(events: deque[float], now: float, window: float) -> None:
        while events and now - events[0] >= window:
            events.popleft()

    def admit_tool_call(self, request: ToolRequest) -> GuardDecision:
        now = self._clock()
        with self._lock:
            context = self._incidents.setdefault(
                request.incident_id,
                {"started": now, "calls": 0, "mutations": 0, "last_signature": None, "repeat": 0},
            )
            started = float(context["started"])
            if now - started > self._max_wall_time_seconds:
                return GuardDecision(False, "INCIDENT_TIMEOUT", "incident wall-time budget exceeded")
            if int(context["calls"]) >= self._max_tool_calls:
                return GuardDecision(False, "TOOL_CALL_LIMIT", "incident tool-call budget exceeded")
            try:
                signature = request.operation_hash()
            except (TypeError, ValueError):
                # Schema validation will produce the user-facing error. The loop
                # guard must still remain fail-safe for malformed JSON-like input.
                signature = f"invalid:{request.tool}:{type(request.arguments).__name__}"
            if context["last_signature"] == signature:
                context["repeat"] = int(context["repeat"]) + 1
            else:
                context["last_signature"] = signature
                context["repeat"] = 1
            if int(context["repeat"]) > self._max_identical_tool_repeat:
                return GuardDecision(False, "LOOP_DETECTED", "identical tool request repeated too often")
            context["calls"] = int(context["calls"]) + 1
            return GuardDecision(True)

    def reserve_mutation(self, host: str, resource: str, incident_id: str) -> GuardDecision:
        now = self._clock()
        with self._lock:
            if host in self._open_hosts or self._store_has_flag("host", host):
                self._open_hosts.add(host)
                return GuardDecision(False, "CIRCUIT_OPEN", "host circuit breaker is open")
            resource_key = (host, resource)
            if resource_key in self._suspended_resources or self._store_has_flag("resource", host, resource):
                self._suspended_resources.add(resource_key)
                return GuardDecision(False, "AUTO_REMEDIATION_SUSPENDED", "resource mutation budget is suspended")
            context = self._incidents.setdefault(
                incident_id,
                {"started": now, "calls": 0, "mutations": 0, "last_signature": None, "repeat": 0},
            )
            if int(context["mutations"]) >= self._max_mutations:
                return GuardDecision(False, "MUTATION_LIMIT", "incident mutation budget exceeded")

            host_rule = self._host_rule(host)
            if host_rule is not None:
                host_events = self._host_events[host]
                if not self._load_host_events(host, host_events):
                    return GuardDecision(False, "GUARD_STATE_UNAVAILABLE", "cannot load host mutation state")
                self._trim(host_events, now, host_rule.window_seconds)
                if len(host_events) >= host_rule.maximum:
                    if not self._set_flag("host", host, None, "CIRCUIT_OPEN"):
                        return GuardDecision(False, "GUARD_STATE_UNAVAILABLE", "cannot persist host circuit state")
                    self._open_hosts.add(host)
                    return GuardDecision(False, "CIRCUIT_OPEN", "host mutation budget exceeded")

            resource_rule = self._resource_rule(resource)
            if resource_rule is not None:
                resource_events = self._resource_events[resource_key]
                if not self._load_resource_events(host, resource, resource_events):
                    return GuardDecision(False, "GUARD_STATE_UNAVAILABLE", "cannot load resource mutation state")
                self._trim(resource_events, now, resource_rule.window_seconds)
                if len(resource_events) >= resource_rule.maximum:
                    if not self._set_flag("resource", host, resource, "AUTO_REMEDIATION_SUSPENDED"):
                        return GuardDecision(False, "GUARD_STATE_UNAVAILABLE", "cannot persist resource guard state")
                    self._suspended_resources.add(resource_key)
                    return GuardDecision(False, "AUTO_REMEDIATION_SUSPENDED", "resource mutation budget exceeded")

            if not self._record_events(
                host,
                resource,
                now,
                record_host=host_rule is not None,
                record_resource=resource_rule is not None,
            ):
                return GuardDecision(False, "GUARD_STATE_UNAVAILABLE", "cannot persist mutation budget state")
            if host_rule is not None:
                self._host_events[host].append(now)
            if resource_rule is not None:
                self._resource_events[resource_key].append(now)
            context["mutations"] = int(context["mutations"]) + 1
            return GuardDecision(True)

    def reset_host(self, host: str) -> None:
        with self._lock:
            self._open_hosts.discard(host)
            self._clear_flag("host", host, None)

    def reset_resource(self, host: str, resource: str) -> None:
        with self._lock:
            self._suspended_resources.discard((host, resource))
            self._clear_flag("resource", host, resource)

    def reset_incident(self, incident_id: str) -> None:
        with self._lock:
            self._incidents.pop(incident_id, None)

    def circuit_open(self, host: str) -> bool:
        with self._lock:
            if host in self._open_hosts or self._store_has_flag("host", host):
                self._open_hosts.add(host)
                return True
            return False

    def resource_suspended(self, host: str, resource: str) -> bool:
        with self._lock:
            key = (host, resource)
            if key in self._suspended_resources or self._store_has_flag("resource", host, resource):
                self._suspended_resources.add(key)
                return True
            return False

    def _load_host_events(self, host: str, events: deque[float]) -> bool:
        if self._state_store is None or host in self._loaded_hosts:
            return True
        try:
            events.extend(self._state_store.events("host", host))
        except Exception:
            return False
        self._loaded_hosts.add(host)
        return True

    def _load_resource_events(self, host: str, resource: str, events: deque[float]) -> bool:
        key = (host, resource)
        if self._state_store is None or key in self._loaded_resources:
            return True
        try:
            events.extend(self._state_store.events("resource", host, resource))
        except Exception:
            return False
        self._loaded_resources.add(key)
        return True

    def _record_events(
        self,
        host: str,
        resource: str,
        occurred_at: float,
        *,
        record_host: bool,
        record_resource: bool,
    ) -> bool:
        if self._state_store is None:
            return True
        try:
            self._state_store.record_mutation(
                host=host,
                resource=resource,
                occurred_at=occurred_at,
                record_host=record_host,
                record_resource=record_resource,
            )
        except Exception:
            return False
        return True

    def _store_has_flag(self, scope: str, host: str, resource: str | None = None) -> bool:
        if self._state_store is None:
            return False
        try:
            return self._state_store.has_flag(scope, host, resource)
        except Exception:
            # A missing durable guard state is unsafe: callers must not mutate.
            return True

    def _set_flag(self, scope: str, host: str, resource: str | None, flag: str) -> bool:
        if self._state_store is None:
            return True
        try:
            self._state_store.set_flag(scope, host, resource, flag)
        except Exception:
            return False
        return True

    def _clear_flag(self, scope: str, host: str, resource: str | None) -> None:
        if self._state_store is None:
            return
        try:
            self._state_store.clear_flag(scope, host, resource)
        except Exception:
            # Reset is an operator action; retaining the durable deny is safer
            # than allowing a mutation after a failed state update.
            return
