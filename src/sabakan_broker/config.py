from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    pass


def load_mapping(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config {path}: {exc}") from exc
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ConfigError(
                f"{path} is not JSON-compatible YAML and PyYAML is not installed"
            ) from exc
        try:
            value = yaml.safe_load(text)
        except Exception as exc:  # pragma: no cover - depends on optional parser
            raise ConfigError(f"cannot parse config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"config {path} must contain an object at its root")
    return value
