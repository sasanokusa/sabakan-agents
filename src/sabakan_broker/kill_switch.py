from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KillSwitchStatus:
    state: str
    code: str
    reason: str


class KillSwitch:
    """External, fail-closed mutation arming.

    The Broker only reads these markers. There is deliberately no arm/disarm method
    in this class, so an LLM or Hermes adapter cannot change the security state.
    """

    def __init__(
        self,
        armed_path: str | Path = "/run/sabakan/ARMED",
        disabled_path: str | Path = "/etc/sabakan/DISABLED",
    ):
        self.armed_path = Path(armed_path)
        self.disabled_path = Path(disabled_path)

    def status(self) -> KillSwitchStatus:
        try:
            if self.disabled_path.exists():
                return KillSwitchStatus("DISABLED", "KILL_SWITCH_DISABLED", "persistent disable marker exists")
            if not self.armed_path.exists():
                return KillSwitchStatus("DISARMED", "KILL_SWITCH_DISARMED", "runtime armed marker is absent")
        except OSError as exc:
            return KillSwitchStatus("UNKNOWN", "KILL_SWITCH_UNREADABLE", f"cannot inspect kill switch: {exc}")
        return KillSwitchStatus("ARMED", "ARMED", "mutation runtime is armed")

    def mutation_allowed(self) -> tuple[bool, KillSwitchStatus]:
        status = self.status()
        return status.state == "ARMED", status
