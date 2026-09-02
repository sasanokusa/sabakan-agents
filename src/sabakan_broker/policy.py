from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .models import PermissionLevel, PolicyDecision, Principal, ToolRequest
from .resources import ResourceRegistry
from .schema import TOOL_SPECS


@dataclass(frozen=True)
class BudgetRule:
    maximum: int
    window_seconds: float


def _level(value: Any, fallback: PermissionLevel) -> PermissionLevel:
    try:
        return PermissionLevel(str(value))
    except (TypeError, ValueError):
        return fallback


def _max_level(left: PermissionLevel, right: PermissionLevel) -> PermissionLevel:
    return left if left.number >= right.number else right


class PolicyEngine:
    """Policy decision point independent of the LLM and Hermes."""

    def __init__(self, raw: Mapping[str, Any], registry: ResourceRegistry):
        self.registry = registry
        raw_levels = raw.get("tool_levels", {})
        self._levels = {
            # Configuration may tighten a tool's level, but never weaken the
            # code-owned schema floor. The model cannot influence either value.
            name: _max_level(spec.minimum_level, _level(raw_levels.get(name), spec.minimum_level))
            for name, spec in TOOL_SPECS.items()
        }
        self._allowlist = tuple(
            dict(item) for item in raw.get("mutation_allowlist", []) if isinstance(item, Mapping)
        )
        self._roles = {
            str(role): _level(item.get("max_level"), PermissionLevel.L0)
            for role, item in raw.get("roles", {}).items()
            if isinstance(item, Mapping)
        }
        approval_planes = raw.get("approval_planes", {})
        self._approval_planes = {
            "L2": str(approval_planes.get("L2", "approval")),
            "L3": str(approval_planes.get("L3", "oob")),
        }
        limits = raw.get("limits", {})
        self.limits = {
            "max_tool_calls": int(limits.get("max_tool_calls", 20)),
            "max_identical_tool_repeat": int(limits.get("max_identical_tool_repeat", 2)),
            "max_wall_time_seconds": float(limits.get("max_wall_time_seconds", 300)),
            "max_mutations": int(limits.get("max_mutations", 3)),
            "max_read_bytes": int(limits.get("max_read_bytes", 65536)),
            "max_read_lines": int(limits.get("max_read_lines", 400)),
            "max_patch_bytes": int(limits.get("max_patch_bytes", 32768)),
            "max_total_result_bytes": int(limits.get("max_total_result_bytes", 65536)),
        }
        self.host_budget_rules = self._parse_budget_rules(raw.get("host_mutation_budget", {}))
        self.resource_budget_rules = self._parse_budget_rules(raw.get("resource_mutation_budget", {}))

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], registry: ResourceRegistry) -> "PolicyEngine":
        return cls(raw, registry)

    @staticmethod
    def _parse_budget_rules(value: Any) -> dict[str, BudgetRule]:
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, BudgetRule] = {}
        for key, item in value.items():
            if not isinstance(item, Mapping):
                continue
            try:
                maximum = int(item["max"])
                window = float(item["window_seconds"])
            except (KeyError, TypeError, ValueError):
                continue
            if maximum > 0 and window > 0:
                result[str(key)] = BudgetRule(maximum, window)
        return result

    def level_for(self, tool: str) -> PermissionLevel:
        return self._levels[tool]

    @property
    def tool_names(self) -> frozenset[str]:
        return frozenset(self._levels)

    def resource_allowed(self, request: ToolRequest) -> tuple[bool, str]:
        host = request.host()
        if host is None or host not in self.registry.hosts:
            return False, "HOST_NOT_ALLOWED"
        args = request.arguments
        if "service" in args and not self.registry.has_service(host, str(args["service"])):
            return False, "SERVICE_NOT_ALLOWED"
        if "container" in args and not self.registry.has_container(host, str(args["container"])):
            return False, "CONTAINER_NOT_ALLOWED"
        if "resource" in args:
            resource = self.registry.resource(host, str(args["resource"]))
            if resource is None:
                return False, "RESOURCE_NOT_ALLOWED"
            if request.tool in {"config_read", "config_patch"} and resource.kind != "config":
                return False, "RESOURCE_KIND_DENIED"
            if request.tool in {"config_read", "config_patch"} and self.registry.resource_path(
                host, str(args["resource"])
            ) is None:
                return False, "PATH_DENIED"
        return True, "ALLOWED"

    def _allowlist_match(self, request: ToolRequest) -> bool:
        for entry in self._allowlist:
            if entry.get("tool") != request.tool:
                continue
            if all(request.arguments.get(key) == value for key, value in entry.items() if key != "tool"):
                return True
        return False

    def _principal_max_level(self, principal: Principal) -> PermissionLevel:
        levels = [self._roles[role] for role in principal.roles if role in self._roles]
        return max(levels, key=lambda item: item.number, default=PermissionLevel.L0)

    def check(self, request: ToolRequest, principal: Principal) -> PolicyDecision:
        if request.tool not in self._levels:
            return PolicyDecision(False, PermissionLevel.L3, code="UNKNOWN_TOOL", reason="tool is not registered")
        level = self._levels[request.tool]
        allowed, code = self.resource_allowed(request)
        if not allowed:
            return PolicyDecision(False, level, code=code, reason="resource is outside the registry")
        if self._principal_max_level(principal).number < level.number:
            return PolicyDecision(False, level, code="ROLE_DENIED", reason="principal role cannot perform this level")
        if level == PermissionLevel.L0:
            return PolicyDecision(True, level)
        if level == PermissionLevel.L1 and not self._allowlist_match(request):
            return PolicyDecision(
                False,
                level,
                code="POLICY_DENIED",
                reason="L1 mutation is not explicitly present in the mutation allowlist",
            )
        required_plane = self._approval_planes.get(level.value)
        if level.number >= 2:
            return PolicyDecision(
                True,
                level,
                requires_approval=True,
                approval_plane=required_plane,
                code="APPROVAL_REQUIRED",
                reason=f"{level.value} mutation requires {required_plane} approval",
            )
        return PolicyDecision(True, level)

    def budget_rule_for_host(self, host: str) -> BudgetRule | None:
        return self.host_budget_rules.get(host) or self.host_budget_rules.get("default")

    def budget_rule_for_resource(self, resource: str) -> BudgetRule | None:
        return self.resource_budget_rules.get(resource) or self.resource_budget_rules.get("default")
