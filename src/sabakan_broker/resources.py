from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class Resource:
    name: str
    kind: str
    path: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HostRecord:
    name: str
    services: frozenset[str] = frozenset()
    containers: frozenset[str] = frozenset()
    resources: Mapping[str, Resource] = field(default_factory=dict)


class ResourceRegistry:
    """Logical resource registry; callers never supply arbitrary filesystem paths."""

    def __init__(self, hosts: Mapping[str, HostRecord], forbidden_paths: tuple[str, ...] = ()):
        self._hosts = dict(hosts)
        self._forbidden_paths = tuple(forbidden_paths)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ResourceRegistry":
        raw_hosts = value.get("hosts", {})
        if not isinstance(raw_hosts, Mapping):
            raise ValueError("resources.hosts must be an object")
        hosts: dict[str, HostRecord] = {}
        for host, raw in raw_hosts.items():
            if not isinstance(host, str) or not isinstance(raw, Mapping):
                raise ValueError("each resource host must be an object")
            raw_resources = raw.get("resources", {})
            resources: dict[str, Resource] = {}
            if not isinstance(raw_resources, Mapping):
                raise ValueError(f"resources for {host} must be an object")
            for name, raw_resource in raw_resources.items():
                if not isinstance(name, str) or not isinstance(raw_resource, Mapping):
                    raise ValueError(f"invalid resource entry for {host}")
                path = raw_resource.get("path")
                if path is not None and not isinstance(path, str):
                    raise ValueError(f"resource path for {host}/{name} must be a string")
                resources[name] = Resource(
                    name=name,
                    kind=str(raw_resource.get("kind", "unknown")),
                    path=path,
                    metadata=dict(raw_resource),
                )
            hosts[host] = HostRecord(
                name=host,
                services=frozenset(str(item) for item in raw.get("services", [])),
                containers=frozenset(str(item) for item in raw.get("containers", [])),
                resources=resources,
            )
        forbidden = tuple(str(item) for item in value.get("forbidden_paths", []))
        return cls(hosts, forbidden)

    @property
    def hosts(self) -> frozenset[str]:
        return frozenset(self._hosts)

    def host(self, name: str) -> HostRecord | None:
        return self._hosts.get(name)

    def has_service(self, host: str, service: str) -> bool:
        record = self.host(host)
        return record is not None and service in record.services

    def has_container(self, host: str, container: str) -> bool:
        record = self.host(host)
        return record is not None and container in record.containers

    def resource(self, host: str, name: str) -> Resource | None:
        record = self.host(host)
        return record.resources.get(name) if record else None

    def path_allowed(self, path: str) -> bool:
        """Reject sensitive paths even if a future registry entry is misconfigured."""

        try:
            candidate = Path(path).expanduser()
        except (TypeError, ValueError):
            return False
        candidates = {str(candidate)}
        try:
            # Resolve existing symlinks so an innocent-looking allowlisted path
            # cannot point the executor at a private key or credential file.
            candidates.add(str(candidate.resolve(strict=False)))
        except OSError:
            return False
        for normalized in candidates:
            for pattern in self._forbidden_paths:
                if fnmatch.fnmatch(normalized, pattern) or pattern in normalized:
                    return False
                if pattern.startswith("~/") and normalized.startswith(str(Path.home()) + "/"):
                    suffix = pattern[2:]
                    home_relative = normalized[len(str(Path.home())) + 1 :]
                    if home_relative == suffix or home_relative.startswith(suffix.rstrip("/") + "/"):
                        return False
        return True

    def resource_path(self, host: str, name: str) -> str | None:
        resource = self.resource(host, name)
        if resource is None or resource.path is None or not self.path_allowed(resource.path):
            return None
        return resource.path
