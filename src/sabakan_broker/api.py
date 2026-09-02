from __future__ import annotations

import uuid
from typing import Any, Mapping

from .broker import Broker
from .models import Approval, Principal, ToolRequest


class BrokerAPI:
    """Small JSON-facing adapter for Hermes, a dummy agent, or a future gateway.

    Authentication and role assignment happen outside this adapter. The incoming
    payload cannot claim a different principal, role, or approval plane.
    """

    def __init__(self, broker: Broker):
        self.broker = broker

    def handle(
        self,
        payload: Mapping[str, Any],
        *,
        principal: Principal,
        approval: Approval | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            return {"ok": False, "code": "INVALID_REQUEST", "error": "request must be an object"}
        try:
            request = ToolRequest(
                tool=payload["tool"],
                arguments=payload["arguments"],
                request_id=str(payload.get("request_id") or uuid.uuid4().hex),
                incident_id=str(payload.get("incident_id", "default")),
                session_id=str(payload.get("session_id", "unknown")),
                model=str(payload.get("model", "unknown")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "code": "INVALID_REQUEST", "error": str(exc)}
        return self.broker.handle(request, principal, approval).as_dict()
