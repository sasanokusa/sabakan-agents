from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for hashes and audit records."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class PermissionLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"

    @property
    def number(self) -> int:
        return int(self.value[1])


class Plane(str, Enum):
    CONVERSATION = "conversation"
    APPROVAL = "approval"
    OOB = "oob"


@dataclass(frozen=True)
class Principal:
    name: str
    plane: str = Plane.CONVERSATION.value
    roles: frozenset[str] = field(default_factory=lambda: frozenset({"observer"}))


@dataclass(frozen=True)
class ToolRequest:
    tool: str
    arguments: Mapping[str, Any]
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    incident_id: str = "default"
    session_id: str = "unknown"
    model: str = "unknown"

    def host(self) -> str | None:
        value = self.arguments.get("host")
        return value if isinstance(value, str) else None

    def target(self) -> str | None:
        for key in ("resource", "service", "container", "package"):
            value = self.arguments.get(key)
            if isinstance(value, str):
                return value
        return self.host()

    def operation_payload(self, before_hash: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool": self.tool,
            "arguments": dict(self.arguments),
        }
        if before_hash is not None:
            payload["before_hash"] = before_hash
        return payload

    def operation_hash(self, before_hash: str | None = None) -> str:
        return sha256_json(self.operation_payload(before_hash))


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    code: str
    data: Any = None
    error: str | None = None
    source: Mapping[str, Any] | None = None
    request_id: str | None = None
    approval_request: "ApprovalRequest | None" = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "code": self.code,
            "data": self.data,
            "error": self.error,
            "request_id": self.request_id,
        }
        if self.source is not None:
            result["source"] = dict(self.source)
        if self.approval_request is not None:
            result["approval_request"] = self.approval_request.as_dict()
        return result


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    level: PermissionLevel
    requires_approval: bool = False
    approval_plane: str | None = None
    code: str = "ALLOWED"
    reason: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    code: str = "EXECUTED"
    data: Any = None
    error: str | None = None
    before_state: Any = None
    after_state: Any = None


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    principal: str
    host: str
    operation: str
    resource: str
    before_hash: str
    patch_hash: str | None
    operation_hash: str
    expires_at: datetime
    nonce: str
    required_plane: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "principal": self.principal,
            "host": self.host,
            "operation": self.operation,
            "resource": self.resource,
            "before_hash": self.before_hash,
            "patch_hash": self.patch_hash,
            "operation_hash": self.operation_hash,
            "expires_at": self.expires_at.isoformat(),
            "nonce": self.nonce,
            "required_plane": self.required_plane,
        }


@dataclass(frozen=True)
class Approval:
    request_id: str
    principal: str
    host: str
    operation: str
    resource: str
    before_hash: str
    patch_hash: str | None
    operation_hash: str
    expires_at: datetime
    nonce: str
    plane: str
    signature: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Approval":
        expires_at = value.get("expires_at")
        if not isinstance(expires_at, str):
            raise ValueError("approval expires_at must be an ISO timestamp")
        return cls(
            request_id=str(value["request_id"]),
            principal=str(value["principal"]),
            host=str(value["host"]),
            operation=str(value["operation"]),
            resource=str(value["resource"]),
            before_hash=str(value["before_hash"]),
            patch_hash=value.get("patch_hash"),
            operation_hash=str(value["operation_hash"]),
            expires_at=datetime.fromisoformat(expires_at.replace("Z", "+00:00")),
            nonce=str(value["nonce"]),
            plane=str(value["plane"]),
            signature=str(value["signature"]),
        )

    def unsigned_payload(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "principal": self.principal,
            "host": self.host,
            "operation": self.operation,
            "resource": self.resource,
            "before_hash": self.before_hash,
            "patch_hash": self.patch_hash,
            "operation_hash": self.operation_hash,
            "expires_at": self.expires_at.isoformat(),
            "nonce": self.nonce,
            "plane": self.plane,
        }

    def as_dict(self) -> dict[str, Any]:
        result = self.unsigned_payload()
        result["signature"] = self.signature
        return result
