from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import Approval, ApprovalRequest, Principal, ToolRequest, canonical_json


class ApprovalError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class SQLiteNonceStore:
    """Durable one-time nonce store used to prevent approval replay after restart."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS approval_nonces (nonce TEXT PRIMARY KEY, consumed_at TEXT NOT NULL)"
        )
        self._connection.commit()

    def used(self, nonce: str) -> bool:
        with self._lock:
            row = self._connection.execute("SELECT 1 FROM approval_nonces WHERE nonce = ?", (nonce,)).fetchone()
        return row is not None

    def consume(self, nonce: str) -> bool:
        with self._lock:
            try:
                self._connection.execute(
                    "INSERT INTO approval_nonces (nonce, consumed_at) VALUES (?, datetime('now'))", (nonce,)
                )
                self._connection.commit()
            except sqlite3.IntegrityError:
                return False
        return True

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def make_approval_request(
    request: ToolRequest,
    principal: Principal,
    before_hash: str,
    required_plane: str,
    *,
    ttl_seconds: float = 300,
    nonce: str | None = None,
) -> ApprovalRequest:
    target = request.target() or "host"
    patch = request.arguments.get("patch")
    patch_hash = hashlib.sha256(canonical_json(patch).encode("utf-8")).hexdigest() if patch is not None else None
    return ApprovalRequest(
        request_id=request.request_id,
        principal=principal.name,
        host=request.host() or "",
        operation=request.tool,
        resource=target,
        before_hash=before_hash,
        patch_hash=patch_hash,
        operation_hash=request.operation_hash(before_hash),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        nonce=nonce or secrets.token_urlsafe(24),
        required_plane=required_plane,
    )


def sign_approval(approval: Approval, secret: bytes) -> str:
    """Signing helper for an external Approval Plane or deterministic tests."""

    return hmac.new(secret, canonical_json(approval.unsigned_payload()).encode("utf-8"), hashlib.sha256).hexdigest()


def approval_from_request(request: ApprovalRequest, *, plane: str, secret: bytes) -> Approval:
    unsigned = Approval(
        request_id=request.request_id,
        principal=request.principal,
        host=request.host,
        operation=request.operation,
        resource=request.resource,
        before_hash=request.before_hash,
        patch_hash=request.patch_hash,
        operation_hash=request.operation_hash,
        expires_at=request.expires_at,
        nonce=request.nonce,
        plane=plane,
        signature="",
    )
    return Approval(**{**unsigned.__dict__, "signature": sign_approval(unsigned, secret)})


class ApprovalVerifier:
    """Verifies an approval object and enforces one-time nonce use."""

    def __init__(self, verification_secret: bytes, clock: Any | None = None, nonce_store: Any | None = None):
        if not verification_secret:
            raise ValueError("approval verification secret must not be empty")
        self._secret = bytes(verification_secret)
        self._used_nonces: set[str] = set()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._nonce_store = nonce_store

    def verify(
        self,
        request: ToolRequest,
        principal: Principal,
        approval: Approval,
        *,
        before_hash: str,
        required_plane: str,
    ) -> None:
        now = self._clock()
        if approval.request_id != request.request_id:
            raise ApprovalError("APPROVAL_MISMATCH", "approval request_id does not match")
        if approval.principal != principal.name:
            raise ApprovalError("APPROVAL_PRINCIPAL_MISMATCH", "approval principal does not match")
        if approval.host != request.host() or approval.operation != request.tool:
            raise ApprovalError("APPROVAL_MISMATCH", "approval operation does not match")
        if approval.resource != (request.target() or "host"):
            raise ApprovalError("APPROVAL_MISMATCH", "approval resource does not match")
        if approval.plane != required_plane:
            raise ApprovalError("APPROVAL_PLANE_REQUIRED", f"approval must come from {required_plane} plane")
        if approval.expires_at.tzinfo is None or approval.expires_at <= now:
            raise ApprovalError("APPROVAL_EXPIRED", "approval has expired")
        if approval.nonce in self._used_nonces or (
            self._nonce_store is not None and self._nonce_store.used(approval.nonce)
        ):
            raise ApprovalError("APPROVAL_REPLAY", "approval nonce has already been used")
        if approval.before_hash != before_hash:
            raise ApprovalError("PRECONDITION_FAILED", "resource state changed after approval")
        patch = request.arguments.get("patch")
        expected_patch_hash = (
            hashlib.sha256(canonical_json(patch).encode("utf-8")).hexdigest() if patch is not None else None
        )
        if approval.patch_hash != expected_patch_hash:
            raise ApprovalError("APPROVAL_MISMATCH", "patch changed after approval")
        if approval.operation_hash != request.operation_hash(before_hash):
            raise ApprovalError("APPROVAL_MISMATCH", "operation hash does not match")
        expected_signature = sign_approval(approval, self._secret)
        if not hmac.compare_digest(approval.signature, expected_signature):
            raise ApprovalError("APPROVAL_SIGNATURE_INVALID", "approval signature is invalid")

    def consume(self, approval: Approval) -> None:
        if self._nonce_store is not None and not self._nonce_store.consume(approval.nonce):
            raise ApprovalError("APPROVAL_REPLAY", "approval nonce has already been used")
        self._used_nonces.add(approval.nonce)
