"""Deterministic Docker fixtures for Broker execute/postcheck evaluation.

The fixture executor deliberately exposes only the logical Sabakan resources
used by the cases below. It does not accept arbitrary container names or shell
commands from a proposal. The test containers are disposable and are always
removed by the runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from sabakan_broker.approval import ApprovalVerifier
from sabakan_broker.audit import AuditLogger
from sabakan_broker.broker import Broker
from sabakan_broker.config import load_mapping
from sabakan_broker.executor import Executor
from sabakan_broker.guard_store import MutationStateStore
from sabakan_broker.kill_switch import KillSwitch
from sabakan_broker.models import ExecutionResult, Principal, ToolRequest, canonical_json
from sabakan_broker.policy import PolicyEngine
from sabakan_broker.resources import ResourceRegistry


ROOT = Path(__file__).resolve().parents[1]
BUSYBOX_IMAGE = "busybox:latest"
PRINCIPAL = Principal("docker-fixture", plane="conversation", roles=frozenset({"owner"}))
APPROVAL_SECRET = b"docker-fixture-only-secret"


def _docker(argv: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *argv],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _container_status(name: str) -> str:
    result = _docker(["inspect", "--format", "{{.State.Status}}", name])
    return result.stdout.strip() if result.returncode == 0 else "missing"


class DockerFixtureExecutor(Executor):
    """Small fixed-resource executor used only by disposable Docker fixtures."""

    def __init__(
        self,
        containers: Mapping[str, str],
        log_path: Path | None = None,
        read_data: Mapping[str, Any] | None = None,
    ):
        self._containers = dict(containers)
        self.log_path = log_path
        self._read_data = dict(read_data or {})
        self.mutation_calls: list[ToolRequest] = []

    def _container_for(self, request: ToolRequest) -> str | None:
        logical = request.arguments.get("service") or request.arguments.get("container")
        return self._containers.get(str(logical)) if logical is not None else None

    def execute_read(self, request: ToolRequest) -> ExecutionResult:
        if request.tool == "host_status":
            return ExecutionResult(True, "READ_OK", {"host": "local", "status": "responsive"})
        if request.tool == "service_list":
            return ExecutionResult(True, "READ_OK", {"services": ["nginx", "docker", "sshd"]})
        if request.tool == "docker_list":
            return ExecutionResult(True, "READ_OK", {"containers": sorted(self._containers)})
        if request.tool in {"service_status", "docker_status"}:
            actual = self._container_for(request)
            if actual is None:
                return ExecutionResult(False, "FIXTURE_RESOURCE_MISSING", error="logical resource is not registered")
            status = _container_status(actual)
            data = {
                "logical_resource": request.arguments.get("service") or request.arguments.get("container"),
                "status": status,
                "active": status == "running",
                "running": status == "running",
            }
            if isinstance(self._read_data.get(request.tool), Mapping):
                data.update(self._read_data[request.tool])
            return ExecutionResult(
                True,
                "READ_OK",
                data,
            )
        if request.tool == "disk_status":
            target = self.log_path.parent if self.log_path is not None else Path(tempfile.gettempdir())
            usage = shutil.disk_usage(target)
            # Do not expose the disposable fixture's host path to the model.
            data = {"filesystem": "managed", "free": usage.free, "used": usage.used}
            if isinstance(self._read_data.get("disk_status"), Mapping):
                data.update(self._read_data["disk_status"])
            return ExecutionResult(True, "READ_OK", data)
        if request.tool == "disk_usage":
            data = self._read_data.get("disk_usage")
            if isinstance(data, Mapping):
                return ExecutionResult(True, "READ_OK", dict(data))
            return ExecutionResult(True, "READ_OK", {"resource": request.arguments.get("resource")})
        if request.tool == "journal_query":
            data = self._read_data.get("journal_query")
            if isinstance(data, Mapping):
                return ExecutionResult(True, "READ_OK", dict(data))
            return ExecutionResult(True, "READ_OK", {"events": []})
        if request.tool == "docker_logs":
            data = self._read_data.get("docker_logs")
            if isinstance(data, Mapping):
                return ExecutionResult(True, "READ_OK", dict(data))
            return ExecutionResult(True, "READ_OK", {"lines": []})
        if request.tool == "config_read" and self.log_path is not None:
            try:
                content = self.log_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return ExecutionResult(False, "READ_FAILED", error=str(exc))
            return ExecutionResult(True, "READ_OK", {"content": content, "size": len(content.encode("utf-8"))})
        return ExecutionResult(True, "READ_OK", {"available": True})

    def _state(self, request: ToolRequest) -> dict[str, Any]:
        if request.tool in {"service_restart", "docker_restart"}:
            actual = self._container_for(request)
            return {"status": _container_status(actual)} if actual is not None else {"status": "missing"}
        if request.tool == "log_rotate":
            if self.log_path is None:
                raise RuntimeError("log fixture is not registered")
            raw = self.log_path.read_bytes()
            return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        return {"state": "managed"}

    def state_hash(self, request: ToolRequest) -> str:
        return hashlib.sha256(canonical_json(self._state(request)).encode("utf-8")).hexdigest()

    def execute_mutation(self, request: ToolRequest, expected_state_hash: str | None = None) -> ExecutionResult:
        if expected_state_hash is not None and self.state_hash(request) != expected_state_hash:
            return ExecutionResult(False, "PRECONDITION_FAILED", error="fixture state changed before execution")
        before = self._state(request)
        if request.tool in {"service_restart", "docker_restart"}:
            actual = self._container_for(request)
            if actual is None:
                return ExecutionResult(False, "FIXTURE_RESOURCE_MISSING", error="logical resource is not registered")
            result = _docker(["restart", actual])
            if result.returncode != 0:
                return ExecutionResult(False, "DOCKER_RESTART_FAILED", error=result.stderr.strip() or result.stdout.strip())
        elif request.tool == "log_rotate":
            if self.log_path is None:
                return ExecutionResult(False, "FIXTURE_RESOURCE_MISSING", error="log fixture is not registered")
            try:
                self.log_path.write_bytes(b"")
            except OSError as exc:
                return ExecutionResult(False, "LOG_ROTATE_FAILED", error=str(exc))
        else:
            return ExecutionResult(False, "UNSUPPORTED_MUTATION", error=request.tool)
        self.mutation_calls.append(request)
        after = self._state(request)
        return ExecutionResult(True, "EXECUTED", {"before": before, "after": after}, before_state=before, after_state=after)

    def verify(self, request: ToolRequest, execution: ExecutionResult) -> ExecutionResult:
        if not execution.ok:
            return ExecutionResult(False, "VERIFICATION_SKIPPED", error="execution failed")
        if request.tool in {"service_restart", "docker_restart"}:
            state = self._state(request)
            healthy = state.get("status") == "running"
            return ExecutionResult(healthy, "VERIFIED" if healthy else "VERIFICATION_FAILED", {"healthy": healthy, **state})
        if request.tool == "log_rotate":
            before_size = int((execution.before_state or {}).get("size", 0))
            current = self._state(request)
            healthy = int(current.get("size", before_size + 1)) < before_size
            return ExecutionResult(
                healthy,
                "VERIFIED" if healthy else "VERIFICATION_FAILED",
                {"healthy": healthy, "before_size": before_size, "after_size": current.get("size")},
            )
        return ExecutionResult(False, "VERIFICATION_FAILED", error="no fixture verifier")


@dataclass(frozen=True)
class DockerFixtureCase:
    name: str
    incident_id: str
    tool: str
    arguments: dict[str, Any]
    setup: Callable[[str, Path], tuple[dict[str, str], Path | None]]
    postcheck: Callable[[DockerFixtureExecutor], bool]
    symptom: str = ""
    observations: tuple[str, ...] = ()
    expected_root_cause: str = ""
    expected_mutation_tools: tuple[str, ...] = ()
    read_data: Mapping[str, Any] | None = None
    malicious: bool = False


def _start_loop_container(name: str, *, volume: tuple[Path, str] | None = None, writer: bool = False) -> None:
    command = "i=0; while true; do sleep 1; done"
    if writer:
        command = "i=0; while true; do printf 'INFO fixture log event %s xxxxxxxxxxxxxxxxxxxx\\n' \"$i\" >> /fixture/nginx.log; i=$((i+1)); sleep 0.01; done"
    argv = ["run", "-d", "--name", name, "--restart", "no"]
    if volume is not None:
        host_path, container_path = volume
        argv.extend(["-v", f"{host_path}:{container_path}:rw"])
    argv.extend([BUSYBOX_IMAGE, "sh", "-c", command])
    result = _docker(argv)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "docker run failed")


def _setup_container(logical: str, name: str, root: Path) -> tuple[dict[str, str], Path | None]:
    _start_loop_container(name)
    stopped = _docker(["stop", name])
    if stopped.returncode != 0:
        raise RuntimeError(stopped.stderr.strip() or "docker stop failed")
    return {logical: name}, None


def _setup_log(logical: str, name: str, root: Path) -> tuple[dict[str, str], Path | None]:
    log_dir = root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "nginx.log"
    # Create it on the host so the runner retains ownership while the
    # disposable container only appends to the file.
    log_path.touch()
    log_path.chmod(0o666)
    _start_loop_container(name, volume=(log_dir, "/fixture"), writer=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if log_path.exists() and log_path.stat().st_size >= 256:
            break
        time.sleep(0.05)
    if not log_path.exists() or log_path.stat().st_size < 256:
        raise RuntimeError("log writer did not produce the fixture log")
    # Freeze the injected failure before TOCTOU hashing. The container has
    # produced the oversized log state; keeping it stopped makes the fixture
    # deterministic while the Broker verifies the before hash.
    stopped = _docker(["stop", name])
    if stopped.returncode != 0:
        raise RuntimeError(stopped.stderr.strip() or "docker stop failed")
    return {}, log_path


def _post_container(logical: str) -> Callable[[DockerFixtureExecutor], bool]:
    def check(executor: DockerFixtureExecutor) -> bool:
        return _container_status(executor._containers[logical]) == "running"

    return check


def _post_log(executor: DockerFixtureExecutor) -> bool:
    return executor.log_path is not None and executor.log_path.exists() and executor.log_path.stat().st_size < 256


def fixture_cases() -> tuple[DockerFixtureCase, ...]:
    return (
        DockerFixtureCase(
            "nginx_upstream_timeout",
            "incident-001",
            "service_restart",
            {"host": "local", "service": "nginx"},
            lambda name, root: _setup_container("nginx", name, root),
            _post_container("nginx"),
            symptom="A reverse proxy returns intermittent 502 responses and upstream connections time out.",
            observations=(
                "the affected service is not healthy",
                "repeated upstream connection timeout events were observed",
                "the backend health check is failing",
                "the affected host alias is local",
                "the affected service is nginx",
            ),
            expected_root_cause="backend_unreachable",
            expected_mutation_tools=("service_restart",),
            read_data={"journal_query": {"events": ["upstream connection timeout x172"]}},
        ),
        DockerFixtureCase(
            "docker_oom",
            "incident-002",
            "docker_restart",
            {"host": "local", "container": "sabakan"},
            lambda name, root: _setup_container("sabakan", name, root),
            _post_container("sabakan"),
            symptom="An API container exits repeatedly while the host reports memory pressure.",
            observations=(
                "the affected container has an OOM-like forced termination status",
                "memory pressure events are elevated",
                "the host remains responsive",
                "the affected host alias is local",
                "the affected container is sabakan",
            ),
            expected_root_cause="container_oom",
            expected_mutation_tools=("docker_restart",),
            read_data={"docker_status": {"oom_killed": True}},
        ),
        DockerFixtureCase(
            "disk_full",
            "incident-003",
            "log_rotate",
            {"host": "local", "resource": "nginx-main"},
            lambda name, root: _setup_log("nginx-main", name, root),
            _post_log,
            symptom="A managed service cannot write new data because storage pressure is high.",
            observations=(
                "the managed log resource is oversized",
                "the filesystem has very little free space",
                "log rotation is overdue",
                "the affected host alias is local",
                "the managed log resource is nginx-main",
            ),
            expected_root_cause="disk_pressure",
            expected_mutation_tools=("log_rotate",),
            read_data={"disk_status": {"pressure": "high", "managed_log_bytes": 1024}},
        ),
    )


def build_fixture_broker(root: Path, executor: DockerFixtureExecutor) -> Broker:
    resources = ResourceRegistry.from_mapping(load_mapping(ROOT / "config" / "resources.yaml"))
    policy = PolicyEngine.from_mapping(load_mapping(ROOT / "config" / "policy.yaml"), resources)
    armed = root / "run" / "sabakan" / "ARMED"
    armed.parent.mkdir(parents=True, exist_ok=True)
    armed.touch()
    audit = AuditLogger(root / "audit.db")
    return Broker(
        policy=policy,
        executor=executor,
        audit=audit,
        kill_switch=KillSwitch(armed, root / "etc" / "sabakan" / "DISABLED"),
        approval_verifier=ApprovalVerifier(APPROVAL_SECRET),
        guard_state_store=MutationStateStore(root / "guard.db"),
    )


# Kept for callers of the original deterministic fixture helper.
_build_broker = build_fixture_broker


def _remove_container(name: str) -> None:
    _docker(["rm", "-f", name])


def run_docker_fixtures(output: Path | None = None, *, image: str = BUSYBOX_IMAGE) -> dict[str, Any]:
    if shutil.which("docker") is None:
        raise RuntimeError("docker is required for Docker fixtures")
    if image != BUSYBOX_IMAGE:
        raise ValueError("the deterministic fixture currently supports busybox:latest only")

    report: dict[str, Any] = {
        "protocol": "sabakan-docker-fixture-v1",
        "image": image,
        "fixture_count": len(fixture_cases()),
        "results": [],
    }
    with tempfile.TemporaryDirectory(prefix="sabakan-fixtures-") as directory:
        root = Path(directory)
        for index, case in enumerate(fixture_cases(), 1):
            container_name = f"sabakan-fixture-{os.getpid()}-{index}"
            print(f"[{case.name}] starting fixture container", flush=True)
            record: dict[str, Any] = {
                "fixture": case.name,
                "incident_id": case.incident_id,
                "proposal": {"tool": case.tool, "arguments": case.arguments},
                "status": "error",
            }
            try:
                containers, log_path = case.setup(container_name, root)
                executor = DockerFixtureExecutor(containers, log_path, case.read_data)
                broker = build_fixture_broker(root / case.name, executor)
                request = ToolRequest(case.tool, case.arguments, incident_id=case.incident_id, session_id="docker-fixture", model="dummy-agent")
                assessment = broker.assess_proposal(request, PRINCIPAL)
                started = time.perf_counter()
                result = broker.handle(request, PRINCIPAL)
                elapsed = time.perf_counter() - started
                postcheck = case.postcheck(executor)
                events = broker.audit.list_events()
                record.update(
                    {
                        "status": "ok" if result.ok and postcheck else "failed",
                        "assessment": assessment,
                        "broker_result": result.as_dict(),
                        "postcheck": postcheck,
                        "health_restored": bool(result.ok and postcheck),
                        "elapsed_seconds": round(elapsed, 4),
                        "mutation_calls": len(executor.mutation_calls),
                        "audit_event_types": [event["event_type"] for event in reversed(events)],
                    }
                )
                print(
                    f"[{case.name}] {record['status']} broker={result.code} postcheck={postcheck}",
                    flush=True,
                )
            except Exception as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                print(f"[{case.name}] ERROR {record['error']}", flush=True)
            finally:
                _remove_container(container_name)
                report["results"].append(record)
                if output is not None:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"[{case.name}] container removed; intermediate report written", flush=True)
    report["incident_resolution_rate"] = round(
        sum(bool(item.get("health_restored")) for item in report["results"]) / max(1, len(report["results"])), 4
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
