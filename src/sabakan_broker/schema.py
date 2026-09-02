from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .models import PermissionLevel, ToolRequest


class ToolValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ToolSpec:
    name: str
    level: PermissionLevel
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()

    @property
    def minimum_level(self) -> PermissionLevel:
        """Code-owned permission floor; policy config cannot lower it."""

        return self.level

    @property
    def allowed_arguments(self) -> frozenset[str]:
        return frozenset(self.required + self.optional)


_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/+-]{0,127}$")
_SAFE_SINCE_RE = re.compile(r"^[A-Za-z0-9_ .:+TZ-]{1,64}$")


TOOL_SPECS: dict[str, ToolSpec] = {
    "host_status": ToolSpec("host_status", PermissionLevel.L0, ("host",)),
    "service_list": ToolSpec("service_list", PermissionLevel.L0, ("host",)),
    "service_status": ToolSpec("service_status", PermissionLevel.L0, ("host", "service")),
    "journal_query": ToolSpec(
        "journal_query",
        PermissionLevel.L0,
        ("host", "service", "since", "severity", "limit"),
    ),
    "process_list": ToolSpec("process_list", PermissionLevel.L0, ("host", "sort")),
    "disk_status": ToolSpec("disk_status", PermissionLevel.L0, ("host",)),
    "disk_usage": ToolSpec("disk_usage", PermissionLevel.L0, ("host", "resource")),
    "memory_status": ToolSpec("memory_status", PermissionLevel.L0, ("host",)),
    "network_status": ToolSpec("network_status", PermissionLevel.L0, ("host",)),
    "port_list": ToolSpec("port_list", PermissionLevel.L0, ("host",)),
    "docker_list": ToolSpec("docker_list", PermissionLevel.L0, ("host",)),
    "docker_status": ToolSpec("docker_status", PermissionLevel.L0, ("host", "container")),
    "docker_logs": ToolSpec("docker_logs", PermissionLevel.L0, ("host", "container", "limit")),
    "config_read": ToolSpec("config_read", PermissionLevel.L0, ("host", "resource")),
    "service_restart": ToolSpec("service_restart", PermissionLevel.L1, ("host", "service")),
    "docker_restart": ToolSpec("docker_restart", PermissionLevel.L1, ("host", "container")),
    "log_rotate": ToolSpec("log_rotate", PermissionLevel.L1, ("host", "resource")),
    "config_patch": ToolSpec("config_patch", PermissionLevel.L2, ("host", "resource", "patch")),
    "package_install": ToolSpec("package_install", PermissionLevel.L2, ("host", "package")),
    "package_remove": ToolSpec("package_remove", PermissionLevel.L2, ("host", "package")),
    "system_reboot": ToolSpec("system_reboot", PermissionLevel.L3, ("host",)),
}


def _require_safe_identifier(key: str, value: Any) -> None:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ToolValidationError("INVALID_ARGUMENT", f"{key} must be a non-empty string")
    if value in {".", ".."} or ".." in value.split("/"):
        raise ToolValidationError("INVALID_ARGUMENT", f"{key} contains a path traversal segment")
    if not _ID_RE.fullmatch(value):
        raise ToolValidationError("INVALID_ARGUMENT", f"{key} contains unsupported characters")


def _require_limit(key: str, value: Any, maximum: int = 5000) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= maximum:
        raise ToolValidationError("INVALID_ARGUMENT", f"{key} must be an integer between 1 and {maximum}")


def _validate_patch(value: Any, max_bytes: int = 32768, depth: int = 0) -> None:
    if depth > 6:
        raise ToolValidationError("INVALID_ARGUMENT", "patch nesting is too deep")
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ToolValidationError("INVALID_ARGUMENT", "patch has too many keys")
        for key, child in value.items():
            if not isinstance(key, str) or not key or len(key) > 128 or ".." in key:
                raise ToolValidationError("INVALID_ARGUMENT", "patch contains an invalid key")
            _validate_patch(child, max_bytes, depth + 1)
    elif isinstance(value, list):
        if len(value) > 512:
            raise ToolValidationError("INVALID_ARGUMENT", "patch list is too long")
        for child in value:
            _validate_patch(child, max_bytes, depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ToolValidationError("INVALID_ARGUMENT", "patch contains an unsupported value")
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ToolValidationError("INVALID_ARGUMENT", "patch is not JSON serializable") from exc
    if len(encoded) > max_bytes:
        raise ToolValidationError("ARGUMENT_TOO_LARGE", f"patch exceeds {max_bytes} bytes")


def validate_tool_request(request: ToolRequest, max_patch_bytes: int = 32768) -> ToolSpec:
    if not isinstance(request.tool, str) or request.tool not in TOOL_SPECS:
        raise ToolValidationError("UNKNOWN_TOOL", f"unknown tool: {request.tool!r}")
    if not isinstance(request.arguments, Mapping):
        raise ToolValidationError("INVALID_ARGUMENT", "arguments must be an object")
    spec = TOOL_SPECS[request.tool]
    keys = set(request.arguments)
    missing = [key for key in spec.required if key not in keys]
    unknown = sorted(keys - spec.allowed_arguments)
    if missing:
        raise ToolValidationError("MISSING_ARGUMENT", f"missing arguments: {', '.join(missing)}")
    if unknown:
        raise ToolValidationError("UNKNOWN_ARGUMENT", f"unknown arguments: {', '.join(unknown)}")

    for key in spec.required + spec.optional:
        if key not in request.arguments:
            continue
        value = request.arguments[key]
        if key in {"host", "service", "container", "resource", "package", "sort", "severity"}:
            _require_safe_identifier(key, value)
        elif key == "since":
            if not isinstance(value, str) or not _SAFE_SINCE_RE.fullmatch(value):
                raise ToolValidationError("INVALID_ARGUMENT", "since contains unsupported characters")
        elif key in {"limit"}:
            _require_limit(key, value)
        elif key == "patch":
            if request.tool == "config_patch" and not isinstance(value, Mapping):
                raise ToolValidationError("INVALID_ARGUMENT", "patch must be an object")
            _validate_patch(value, max_patch_bytes)

    if request.tool == "journal_query" and request.arguments["severity"] not in {
        "debug", "info", "notice", "warning", "err", "crit", "alert", "emerg"
    }:
        raise ToolValidationError("INVALID_ARGUMENT", "unsupported journal severity")
    if request.tool == "process_list" and request.arguments["sort"] not in {"cpu", "memory", "pid", "name"}:
        raise ToolValidationError("INVALID_ARGUMENT", "unsupported process sort")
    return spec
