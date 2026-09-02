from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sabakan_broker.approval import ApprovalVerifier
from sabakan_broker.audit import AuditLogger
from sabakan_broker.broker import Broker
from sabakan_broker.config import load_mapping
from sabakan_broker.executor import Executor
from sabakan_broker.guard import MutationGuard
from sabakan_broker.guard_store import MutationStateStore
from sabakan_broker.kill_switch import KillSwitch
from sabakan_broker.models import Approval, ExecutionResult, Principal, ToolRequest, canonical_json
from sabakan_broker.policy import PolicyEngine
from sabakan_broker.resources import ResourceRegistry


ROOT = Path(__file__).resolve().parents[1]
SECRET = b"test-approval-secret"


class FakeExecutor:
    def __init__(self) -> None:
        self.service_active = False
        self.container_running = False
        self.config: dict[str, Any] = {"upstream": "backend:8080", "enabled": True}
        self.log = ""
        self.mutation_calls: list[ToolRequest] = []
        self.read_calls: list[ToolRequest] = []
        self.state_version = 0
        self.force_verification_failure = False

    def execute_read(self, request: ToolRequest) -> ExecutionResult:
        self.read_calls.append(request)
        args = request.arguments
        if request.tool == "host_status":
            return ExecutionResult(True, "READ_OK", {"host": args["host"], "password": "do-not-leak", "ok": True})
        if request.tool == "service_status":
            return ExecutionResult(
                True,
                "READ_OK",
                {"stdout": "active" if self.service_active else "inactive", "service": args["service"]},
            )
        if request.tool == "docker_status":
            return ExecutionResult(
                True,
                "READ_OK",
                {"stdout": "running" if self.container_running else "exited", "container": args["container"]},
            )
        if request.tool == "journal_query" or request.tool == "docker_logs":
            return ExecutionResult(True, "READ_OK", {"stdout": self.log})
        if request.tool == "config_read":
            return ExecutionResult(True, "READ_OK", {"path": "/safe/config.json", "content": dict(self.config)})
        return ExecutionResult(True, "READ_OK", {"host": args["host"], "value": "safe"})

    def _state(self, request: ToolRequest) -> Any:
        if request.tool in {"service_restart"}:
            return {"service_active": self.service_active, "version": self.state_version}
        if request.tool == "docker_restart":
            return {"container_running": self.container_running, "version": self.state_version}
        if request.tool in {"config_patch", "log_rotate"}:
            return {"config": self.config, "version": self.state_version}
        return {"version": self.state_version}

    def state_hash(self, request: ToolRequest) -> str:
        return hashlib.sha256(canonical_json(self._state(request)).encode("utf-8")).hexdigest()

    def execute_mutation(self, request: ToolRequest, expected_state_hash: str | None = None) -> ExecutionResult:
        if expected_state_hash is not None and expected_state_hash != self.state_hash(request):
            return ExecutionResult(False, "PRECONDITION_FAILED", error="fake state changed")
        before = self._state(request)
        self.mutation_calls.append(request)
        if request.tool == "service_restart":
            self.service_active = True
        elif request.tool == "docker_restart":
            self.container_running = True
        elif request.tool == "config_patch":
            patch = request.arguments["patch"]
            if isinstance(patch, dict):
                self.config.update(patch)
        self.state_version += 1
        return ExecutionResult(True, "EXECUTED", {"changed": True}, before_state=before, after_state=self._state(request))

    def verify(self, request: ToolRequest, execution: ExecutionResult) -> ExecutionResult:
        if self.force_verification_failure:
            return ExecutionResult(False, "VERIFICATION_FAILED", error="fixture requested verification failure")
        if request.tool == "service_restart":
            return ExecutionResult(self.service_active, "VERIFIED" if self.service_active else "VERIFICATION_FAILED", {"active": self.service_active})
        if request.tool == "docker_restart":
            return ExecutionResult(self.container_running, "VERIFIED" if self.container_running else "VERIFICATION_FAILED", {"running": self.container_running})
        return ExecutionResult(True, "VERIFIED", {"state_version": self.state_version})


def build_broker(
    tmp_path: Path,
    *,
    armed: bool = True,
    guard_state_path: Path | None = None,
) -> tuple[Broker, FakeExecutor, Principal]:
    resources = ResourceRegistry.from_mapping(load_mapping(ROOT / "config" / "resources.yaml"))
    policy = PolicyEngine.from_mapping(load_mapping(ROOT / "config" / "policy.yaml"), resources)
    audit = AuditLogger(tmp_path / "audit.db")
    armed_path = tmp_path / "run" / "sabakan" / "ARMED"
    disabled_path = tmp_path / "etc" / "sabakan" / "DISABLED"
    if armed:
        armed_path.parent.mkdir(parents=True, exist_ok=True)
        armed_path.touch()
    executor = FakeExecutor()
    broker = Broker(
        policy=policy,
        executor=executor,
        audit=audit,
        kill_switch=KillSwitch(armed_path, disabled_path),
        approval_verifier=ApprovalVerifier(SECRET),
        guard_state_store=MutationStateStore(guard_state_path or (tmp_path / "guard.db")),
    )
    return broker, executor, Principal("alice", plane="conversation", roles=frozenset({"owner"}))
