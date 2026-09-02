from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .audit import AuditLogger
from .approval import ApprovalVerifier, SQLiteNonceStore
from .broker import Broker
from .config import load_mapping
from .executor import SystemExecutor
from .kill_switch import KillSwitch
from .models import Principal, ToolRequest
from .policy import PolicyEngine
from .resources import ResourceRegistry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sabakanctl", description="Sabakan Broker typed control CLI")
    parser.add_argument("--policy", default="config/policy.yaml")
    parser.add_argument("--resources", default="config/resources.yaml")
    parser.add_argument("--audit", default="data/audit.db")
    parser.add_argument("--armed-path", default="/run/sabakan/ARMED")
    parser.add_argument("--disabled-path", default="/etc/sabakan/DISABLED")
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--principal", default="owner")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="read host status")
    status.add_argument("host")
    service_status = sub.add_parser("service-status", help="read service status")
    service_status.add_argument("host")
    service_status.add_argument("service")
    restart = sub.add_parser("restart", help="request an allowlisted service restart")
    restart.add_argument("host")
    restart.add_argument("service")
    return parser


def _request(args: argparse.Namespace) -> ToolRequest:
    if args.command == "status":
        tool = "host_status"
        arguments = {"host": args.host}
    elif args.command == "service-status":
        tool = "service_status"
        arguments = {"host": args.host, "service": args.service}
    elif args.command == "restart":
        tool = "service_restart"
        arguments = {"host": args.host, "service": args.service}
    else:  # pragma: no cover - argparse enforces commands
        raise ValueError(f"unsupported command {args.command}")
    return ToolRequest(tool, arguments, session_id="sabakanctl", model="none")


def _build_broker(args: argparse.Namespace) -> Broker:
    resources = ResourceRegistry.from_mapping(load_mapping(args.resources))
    policy = PolicyEngine.from_mapping(load_mapping(args.policy), resources)
    audit = AuditLogger(args.audit)
    # The CLI does not mint approvals. A process-local secret is enough to keep
    # read-only and L1 commands usable; Approval Plane deployments inject their
    # durable verifier secret through application code instead.
    secret = os.environ.get("SABAKAN_APPROVAL_VERIFY_SECRET", "").encode("utf-8")
    nonce_store = SQLiteNonceStore(args.audit) if secret else None
    verifier = ApprovalVerifier(secret, nonce_store=nonce_store) if secret else None
    return Broker(
        policy=policy,
        executor=SystemExecutor(resources),
        audit=audit,
        kill_switch=KillSwitch(args.armed_path, args.disabled_path),
        approval_verifier=verifier,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        broker = _build_broker(args)
        principal = Principal(args.principal, roles=frozenset({"owner"}))
        result = broker.handle(_request(args), principal)
        payload: Any = result.as_dict()
        if args.json_output:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            print(json.dumps(payload, ensure_ascii=False, default=str))
        return 0 if result.ok else 2
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "code": "CLI_ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
