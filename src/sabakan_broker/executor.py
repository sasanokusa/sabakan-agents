from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Protocol

from .models import ExecutionResult, ToolRequest, ToolRequest as Request, canonical_json
from .resources import ResourceRegistry


class Executor(Protocol):
    """Privileged boundary implemented by local or authenticated remote executors."""

    def execute_read(self, request: ToolRequest) -> ExecutionResult: ...

    def state_hash(self, request: ToolRequest) -> str: ...

    def execute_mutation(self, request: ToolRequest, expected_state_hash: str | None = None) -> ExecutionResult: ...

    def verify(self, request: ToolRequest, execution: ExecutionResult) -> ExecutionResult: ...


class SystemExecutor:
    """A conservative local executor using argv-only commands.

    It accepts only the logical host alias configured at construction time. Remote
    hosts must use a separate authenticated ops-agentd implementation.
    """

    def __init__(
        self,
        registry: ResourceRegistry,
        *,
        local_host: str = "local",
        command_timeout: float = 30,
        max_command_output_bytes: int = 1_048_576,
    ):
        self.registry = registry
        self.local_host = local_host
        self.command_timeout = command_timeout
        self.max_command_output_bytes = max_command_output_bytes

    def _local_only(self, request: ToolRequest) -> ExecutionResult | None:
        if request.host() != self.local_host:
            return ExecutionResult(False, "REMOTE_EXECUTOR_UNAVAILABLE", error="no remote executor is registered")
        return None

    def _run(self, argv: list[str]) -> ExecutionResult:
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.command_timeout,
            )
        except FileNotFoundError:
            return ExecutionResult(False, "COMMAND_NOT_FOUND", error=argv[0])
        except subprocess.TimeoutExpired as exc:
            return ExecutionResult(False, "COMMAND_TIMEOUT", error=str(exc))
        except OSError as exc:
            return ExecutionResult(False, "EXECUTOR_ERROR", error=str(exc))
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        stdout = stdout.encode("utf-8", errors="replace")[: self.max_command_output_bytes].decode(
            "utf-8", errors="ignore"
        )
        stderr = stderr.encode("utf-8", errors="replace")[: self.max_command_output_bytes].decode(
            "utf-8", errors="ignore"
        )
        data = {"returncode": completed.returncode, "stdout": stdout, "stderr": stderr}
        if completed.returncode != 0:
            return ExecutionResult(False, "COMMAND_FAILED", data=data, error=stderr.strip() or stdout.strip())
        return ExecutionResult(True, "EXECUTED", data=data)

    def execute_read(self, request: ToolRequest) -> ExecutionResult:
        denied = self._local_only(request)
        if denied is not None:
            return denied
        args = request.arguments
        tool = request.tool
        if tool == "host_status":
            try:
                load = os.getloadavg()
            except OSError:
                load = None
            return ExecutionResult(
                True,
                "READ_OK",
                data={"host": self.local_host, "node": platform.node(), "platform": platform.platform(), "load": load},
            )
        if tool == "service_status":
            checked = self._run(["systemctl", "is-active", str(args["service"])])
            if checked.data is None:
                return checked
            output = checked.data.get("stdout", "")
            return ExecutionResult(
                True,
                "READ_OK",
                data={
                    "service": args["service"],
                    "active": checked.ok and str(output).strip() == "active",
                    "status": str(output).strip() or str(checked.data.get("stderr", "")).strip(),
                    "returncode": checked.data.get("returncode"),
                },
            )
        if tool == "service_list":
            return self._run(["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--no-pager"])
        if tool == "journal_query":
            return self._run(
                [
                    "journalctl",
                    "-u",
                    str(args["service"]),
                    "--since",
                    str(args["since"]),
                    "-p",
                    str(args["severity"]),
                    "-n",
                    str(args["limit"]),
                    "--no-pager",
                    "-o",
                    "short-iso",
                ]
            )
        if tool == "process_list":
            sort = {"cpu": "-pcpu", "memory": "-pmem", "pid": "pid", "name": "comm"}[str(args["sort"])]
            return self._run(["ps", "-eo", "pid,comm,pcpu,pmem", f"--sort={sort}"])
        if tool == "disk_status":
            usage = shutil.disk_usage("/")
            return ExecutionResult(True, "READ_OK", data={"path": "/", "total": usage.total, "used": usage.used, "free": usage.free})
        if tool == "disk_usage":
            path = self.registry.resource_path(self.local_host, str(args["resource"]))
            if path is None:
                return ExecutionResult(False, "PATH_DENIED", error="resource path is not readable")
            try:
                usage = shutil.disk_usage(path)
            except OSError as exc:
                return ExecutionResult(False, "READ_FAILED", error=str(exc))
            return ExecutionResult(True, "READ_OK", data={"path": path, "total": usage.total, "used": usage.used, "free": usage.free})
        if tool == "memory_status":
            return self._memory_status()
        if tool == "network_status":
            try:
                interfaces = sorted(item.name for item in Path("/sys/class/net").iterdir())
            except OSError as exc:
                return ExecutionResult(False, "READ_FAILED", error=str(exc))
            return ExecutionResult(True, "READ_OK", data={"interfaces": interfaces})
        if tool == "port_list":
            return self._run(["ss", "-lntup"])
        if tool == "docker_list":
            return self._run(["docker", "ps", "--all", "--no-trunc", "--format", "{{.Names}}\t{{.Status}}"])
        if tool == "docker_status":
            checked = self._run(["docker", "inspect", "--format", "{{.State.Status}}", str(args["container"])])
            if checked.data is None:
                return checked
            status = str(checked.data.get("stdout", "")).strip()
            return ExecutionResult(
                True,
                "READ_OK",
                data={
                    "container": args["container"],
                    "running": checked.ok and status == "running",
                    "status": status or str(checked.data.get("stderr", "")).strip(),
                    "returncode": checked.data.get("returncode"),
                },
            )
        if tool == "docker_logs":
            return self._run(["docker", "logs", "--tail", str(args["limit"]), str(args["container"])])
        if tool == "config_read":
            path = self.registry.resource_path(self.local_host, str(args["resource"]))
            if path is None:
                return ExecutionResult(False, "PATH_DENIED", error="resource path is not readable")
            try:
                content = Path(path).read_bytes()[: self.max_command_output_bytes]
            except OSError as exc:
                return ExecutionResult(False, "READ_FAILED", error=str(exc))
            return ExecutionResult(True, "READ_OK", data={"path": path, "content": content.decode("utf-8", errors="replace")})
        return ExecutionResult(False, "UNSUPPORTED_READ", error=f"read tool is not implemented: {tool}")

    @staticmethod
    def _memory_status() -> ExecutionResult:
        try:
            values: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, _, rest = line.partition(":")
                number = rest.strip().split()[0] if rest.strip() else ""
                if number.isdigit():
                    values[key] = int(number) * 1024
        except (OSError, ValueError, IndexError) as exc:
            return ExecutionResult(False, "READ_FAILED", error=str(exc))
        return ExecutionResult(True, "READ_OK", data=values)

    def _state_read_request(self, request: ToolRequest) -> ToolRequest:
        args = dict(request.arguments)
        if request.tool == "service_restart":
            tool = "service_status"
        elif request.tool == "docker_restart":
            tool = "docker_status"
        elif request.tool in {"config_patch", "log_rotate"}:
            tool = "config_read"
        else:
            tool = "host_status"
        args.pop("patch", None)
        return Request(tool, args, incident_id=request.incident_id, session_id=request.session_id, model=request.model)

    def state_hash(self, request: ToolRequest) -> str:
        if request.tool in {"config_patch", "log_rotate"}:
            path = self.registry.resource_path(self.local_host, str(request.arguments["resource"]))
            if path is None:
                raise RuntimeError("PATH_DENIED")
            raw = Path(path).read_bytes()
            return hashlib.sha256(raw).hexdigest()
        state_request = self._state_read_request(request)
        result = self.execute_read(state_request)
        if not result.ok:
            raise RuntimeError(result.code)
        return hashlib.sha256(canonical_json(result.data).encode("utf-8")).hexdigest()

    def execute_mutation(self, request: ToolRequest, expected_state_hash: str | None = None) -> ExecutionResult:
        denied = self._local_only(request)
        if denied is not None:
            return denied
        if expected_state_hash is not None:
            try:
                if self.state_hash(request) != expected_state_hash:
                    return ExecutionResult(False, "PRECONDITION_FAILED", error="state changed before execution")
            except (OSError, RuntimeError) as exc:
                return ExecutionResult(False, "PRECONDITION_FAILED", error=str(exc))
        args = request.arguments
        if request.tool == "service_restart":
            return self._run(["systemctl", "restart", str(args["service"])])
        if request.tool == "docker_restart":
            return self._run(["docker", "restart", str(args["container"])])
        if request.tool == "system_reboot":
            return self._run(["systemctl", "reboot"])
        return ExecutionResult(False, "UNSUPPORTED_MUTATION", error=f"mutation is not implemented: {request.tool}")

    def verify(self, request: ToolRequest, execution: ExecutionResult) -> ExecutionResult:
        if not execution.ok:
            return ExecutionResult(False, "VERIFICATION_SKIPPED", error="execution did not succeed")
        if request.tool == "service_restart":
            checked = self.execute_read(self._state_read_request(request))
            if not checked.ok:
                return ExecutionResult(False, "VERIFICATION_FAILED", error=checked.error)
            active = bool((checked.data or {}).get("active"))
            return ExecutionResult(active, "VERIFIED" if active else "VERIFICATION_FAILED", data={"active": active})
        if request.tool == "docker_restart":
            checked = self.execute_read(self._state_read_request(request))
            if not checked.ok:
                return ExecutionResult(False, "VERIFICATION_FAILED", error=checked.error)
            running = bool((checked.data or {}).get("running"))
            return ExecutionResult(running, "VERIFIED" if running else "VERIFICATION_FAILED", data={"running": running})
        return ExecutionResult(False, "VERIFICATION_FAILED", error="no verifier is registered for this mutation")
