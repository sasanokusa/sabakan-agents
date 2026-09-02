from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from typing import Any, Mapping


_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----(?:.|\n)*?-----END [^-]*PRIVATE KEY-----",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret|private[_-]?key|client_secret|cookie)\b"
    r"(\s*[:=]\s*)([\"']?)([^\s,;\"']+)\3"
)
_URL_CREDENTIAL_RE = re.compile(r"(?i)(://[^:/\s]+:)[^@\s]+@")
_LONG_TOKEN_RE = re.compile(r"\b(?:sk|ghp|glpat|xox[baprs])-[-A-Za-z0-9_]{12,}\b")
_TIMESTAMP_RE = re.compile(r"^\s*(?:\d{4}-\d\d-\d\d[T ]\S+|\[[^]]+\])\s+")
_SEVERITY_RE = re.compile(r"\b(EMERG|ALERT|CRIT|ERROR|ERR|WARN(?:ING)?|NOTICE|INFO|DEBUG)\b", re.IGNORECASE)


class Redactor:
    """Redact secrets recursively before data reaches an LLM or audit log."""

    def __init__(self, replacement: str = "[REDACTED]"):
        self.replacement = replacement

    def text(self, value: str) -> str:
        value = _PRIVATE_KEY_RE.sub(self.replacement, value)
        value = _BEARER_RE.sub(f"Bearer {self.replacement}", value)
        value = _URL_CREDENTIAL_RE.sub(rf"\g<1>{self.replacement}@", value)
        value = _LONG_TOKEN_RE.sub(self.replacement, value)

        def replace_assignment(match: re.Match[str]) -> str:
            return f"{match.group(1)}{match.group(2)}{match.group(3)}{self.replacement}{match.group(3)}"

        return _ASSIGNMENT_RE.sub(replace_assignment, value)

    def value(self, value: Any, key: str | None = None) -> Any:
        if key and self._secret_key(key):
            return self.replacement
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, Mapping):
            return {str(k): self.value(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, tuple):
            return [self.value(item) for item in value]
        return value

    @staticmethod
    def _secret_key(key: str) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "", key.lower())
        return normalized in {
            "password",
            "passwd",
            "secret",
            "apikey",
            "accesstoken",
            "authtoken",
            "clientsecret",
            "privatekey",
            "cookie",
            "credential",
        } or normalized.endswith("token")


def _severity(line: str) -> str:
    match = _SEVERITY_RE.search(line)
    if not match:
        return "INFO"
    value = match.group(1).upper()
    return "WARNING" if value == "WARN" else value


_SEVERITY_ORDER = {
    "DEBUG": 0,
    "INFO": 1,
    "NOTICE": 2,
    "WARNING": 3,
    "ERROR": 4,
    "ERR": 4,
    "CRIT": 5,
    "ALERT": 6,
    "EMERG": 7,
}


def normalize_log(
    value: Any,
    *,
    max_bytes: int = 65536,
    max_lines: int = 400,
    severity: str | None = None,
    redactor: Redactor | None = None,
) -> dict[str, Any]:
    """Turn raw logs into bounded, source content rather than prompt text."""

    if isinstance(value, Mapping):
        for key in ("log", "logs", "lines", "stdout", "stderr", "content"):
            if key in value:
                value = value[key]
                break
    if isinstance(value, list):
        raw_lines = [str(item) for item in value]
    else:
        raw_lines = str(value if value is not None else "").splitlines()
    raw = "\n".join(raw_lines).encode("utf-8", errors="replace")
    truncated_bytes = len(raw) > max_bytes
    bounded = raw[:max_bytes].decode("utf-8", errors="ignore")
    lines = bounded.splitlines()[:max_lines]
    truncated_lines = len(bounded.splitlines()) > max_lines or len(raw_lines) > len(lines)
    minimum = _SEVERITY_ORDER.get(str(severity or "debug").upper(), 0)

    counts: OrderedDict[str, dict[str, Any]] = OrderedDict()
    samples: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        level = _severity(line)
        if _SEVERITY_ORDER.get(level, 1) < minimum:
            continue
        # Folding timestamps keeps repeated events compact without merging arbitrary messages.
        fingerprint_source = _TIMESTAMP_RE.sub("", line)
        fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
        event = counts.get(fingerprint)
        if event is None:
            event = {"severity": level, "message": line, "count": 0}
            counts[fingerprint] = event
            if len(samples) < 20:
                samples.append(line)
        event["count"] += 1

    if redactor is not None:
        for event in counts.values():
            event["message"] = redactor.text(event["message"])
        samples = [redactor.text(item) for item in samples]
    return {
        "events": list(counts.values()),
        "representative_samples": samples,
        "truncated": truncated_bytes or truncated_lines,
        "line_count": len(lines),
        "byte_limit": max_bytes,
        "line_limit": max_lines,
    }


def source_metadata(tool: str, host: str | None, resource: str | None) -> dict[str, Any]:
    if tool in {"journal_query", "docker_logs"}:
        source_type = "untrusted_log"
    elif tool in {"config_read", "disk_usage"}:
        source_type = "untrusted_file_or_metric"
    else:
        source_type = "untrusted_command_output"
    return {
        "source_type": source_type,
        "host": host,
        "resource": resource,
        "trusted": False,
        "instructions_are_data": True,
    }
