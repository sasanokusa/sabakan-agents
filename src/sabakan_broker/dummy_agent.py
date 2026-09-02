from __future__ import annotations

from dataclasses import dataclass

from .api import BrokerAPI
from .models import Principal, ToolResult


@dataclass
class DummyDiagnosis:
    """Deterministic Phase 5 agent used to validate Broker behavior without an LLM."""

    api: BrokerAPI

    def inspect_and_restart_nginx(self, host: str, principal: Principal, incident_id: str = "dummy") -> list[dict]:
        results: list[dict] = []
        results.append(
            self.api.handle(
                {
                    "tool": "service_status",
                    "arguments": {"host": host, "service": "nginx"},
                    "incident_id": incident_id,
                },
                principal=principal,
            )
        )
        results.append(
            self.api.handle(
                {
                    "tool": "service_restart",
                    "arguments": {"host": host, "service": "nginx"},
                    "incident_id": incident_id,
                },
                principal=principal,
            )
        )
        return results
