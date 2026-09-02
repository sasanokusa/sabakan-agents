from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Mapping

from .approval import ApprovalError, ApprovalVerifier, make_approval_request
from .audit import AuditLogger
from .executor import Executor
from .guard import MutationGuard
from .guard_store import MutationStateStore
from .kill_switch import KillSwitch
from .models import Approval, ApprovalRequest, ExecutionResult, PermissionLevel, PolicyDecision, Principal, ToolRequest, ToolResult
from .policy import PolicyEngine
from .proposal import classify_proposal
from .redaction import Redactor, normalize_log, source_metadata
from .schema import ToolValidationError, validate_tool_request


class Broker:
    """Sabakan's trusted decision and execution boundary."""

    def __init__(
        self,
        *,
        policy: PolicyEngine,
        executor: Executor,
        audit: AuditLogger,
        kill_switch: KillSwitch,
        approval_verifier: ApprovalVerifier | None = None,
        redactor: Redactor | None = None,
        guard: MutationGuard | None = None,
        guard_state_store: MutationStateStore | None = None,
    ):
        self.policy = policy
        self.executor = executor
        self.audit = audit
        self.kill_switch = kill_switch
        self.approval_verifier = approval_verifier
        self.redactor = redactor or Redactor()
        self.guard = guard or MutationGuard(
            host_rule=policy.budget_rule_for_host,
            resource_rule=policy.budget_rule_for_resource,
            max_tool_calls=policy.limits["max_tool_calls"],
            max_identical_tool_repeat=policy.limits["max_identical_tool_repeat"],
            max_wall_time_seconds=policy.limits["max_wall_time_seconds"],
            max_mutations=policy.limits["max_mutations"],
            state_store=guard_state_store,
        )

    def assess_proposal(self, request: ToolRequest, principal: Principal) -> dict[str, Any]:
        """Assess a model proposal without executing it or consuming guards.

        Evaluation uses this same Broker schema and policy path to distinguish a
        well-formed proposal, a registry-valid resource, and a policy-accepted
        operation. Approval remains a Broker result (``requires_approval``), not
        an LLM protocol field.
        """

        try:
            spec = validate_tool_request(request, self.policy.limits["max_patch_bytes"])
        except ToolValidationError as exc:
            assessment = {
                "tool_name_valid": request.tool in self.policy.tool_names,
                "tool_arguments_valid": False,
                "resource_valid": False,
                "broker_acceptance": False,
                "requires_approval": False,
                "code": exc.code,
                "reason": exc.message,
            }
            assessment.update(classify_proposal(request, assessment))
            return assessment
        resource_valid, resource_code = self.policy.resource_allowed(request)
        decision = self.policy.check(request, principal)
        assessment = {
            "tool_name_valid": True,
            "tool_arguments_valid": True,
            "resource_valid": resource_valid,
            "broker_acceptance": decision.allowed,
            "requires_approval": decision.requires_approval,
            "level": spec.minimum_level.value,
            "code": decision.code if not decision.allowed else "ACCEPTED",
            "policy_code": decision.code,
            "resource_code": resource_code,
            "reason": decision.reason,
        }
        assessment.update(classify_proposal(request, assessment))
        return assessment

    def handle(
        self,
        request: ToolRequest,
        principal: Principal,
        approval: Approval | Mapping[str, Any] | None = None,
    ) -> ToolResult:
        """Validate, authorize, execute and verify one typed request."""

        # An approval submission is the trusted Approval Plane continuation of an
        # already-admitted conversation proposal. It still passes the guard's
        # incident time gate, but is not counted as a second model call. Mutation
        # budgets remain enforced by reserve_mutation below.
        try:
            is_approval_level = self.policy.level_for(request.tool).number >= 2
        except KeyError:
            is_approval_level = False
        guard_decision = self.guard.admit_tool_call(
            request,
            approval_continuation=approval is not None and is_approval_level,
        )
        if not guard_decision.allowed:
            result = self._failure(request, guard_decision.code, guard_decision.reason)
            self._audit(request, principal, "GUARD_DENIED", result)
            return result

        try:
            spec = validate_tool_request(request, self.policy.limits["max_patch_bytes"])
        except ToolValidationError as exc:
            result = self._failure(request, exc.code, exc.message)
            self._audit(request, principal, "SCHEMA_DENIED", result)
            return result

        decision = self.policy.check(request, principal)
        if not decision.allowed:
            result = self._failure(request, decision.code, decision.reason)
            self._audit(request, principal, decision.code, result)
            return result

        if decision.level == PermissionLevel.L0:
            return self._read(request, principal, decision)

        allowed, kill_status = self.kill_switch.mutation_allowed()
        if not allowed:
            result = self._failure(request, kill_status.code, kill_status.reason)
            self._audit(request, principal, kill_status.code, result)
            return result

        before_hash = self._state_hash(request)
        if before_hash is None:
            result = self._failure(request, "PRECONDITION_UNAVAILABLE", "cannot obtain current resource state")
            self._audit(request, principal, "PRECONDITION_UNAVAILABLE", result)
            return result

        approval_object: Approval | None = None
        if decision.requires_approval:
            if approval is None:
                approval_request = self._approval_request(request, principal, decision, before_hash)
                if approval_request is None:
                    result = self._failure(request, "APPROVAL_UNAVAILABLE", "cannot create approval request")
                else:
                    result = ToolResult(
                        False,
                        "APPROVAL_REQUIRED",
                        data={"reason": decision.reason},
                        request_id=request.request_id,
                        approval_request=approval_request,
                    )
                result = self._finalize_result(result)
                self._audit(request, principal, "APPROVAL_REQUIRED", result, operation_hash=request.operation_hash(before_hash))
                return result
            try:
                approval_object = approval if isinstance(approval, Approval) else Approval.from_mapping(approval)
                if self.approval_verifier is None:
                    raise ApprovalError("APPROVAL_UNAVAILABLE", "Broker has no approval verifier")
                self.approval_verifier.verify(
                    request,
                    principal,
                    approval_object,
                    before_hash=before_hash,
                    required_plane=decision.approval_plane or "approval",
                )
            except (ApprovalError, KeyError, TypeError, ValueError) as exc:
                code = exc.code if isinstance(exc, ApprovalError) else "APPROVAL_INVALID"
                result = self._failure(request, code, str(exc))
                self._audit(request, principal, code, result, operation_hash=request.operation_hash(before_hash))
                return result

        target = request.target() or request.host() or "host"
        guard_decision = self.guard.reserve_mutation(request.host() or "", target, request.incident_id)
        if not guard_decision.allowed:
            result = self._failure(request, guard_decision.code, guard_decision.reason)
            self._audit(request, principal, guard_decision.code, result, operation_hash=request.operation_hash(before_hash))
            return result

        operation_hash = request.operation_hash(before_hash)
        intent = ToolResult(
            True,
            "MUTATION_INTENT",
            data={"status": "validated", "before_hash": before_hash},
            source=source_metadata(request.tool, request.host(), request.target()),
            request_id=request.request_id,
        )
        if not self._audit(
            request,
            principal,
            "ALLOWED",
            intent,
            operation_hash=operation_hash,
            approval_id=approval_object.request_id if approval_object else None,
            before_state={"hash": before_hash},
            event_type="MUTATION_INTENT",
        ):
            # Guard state may have been reserved, but the privileged executor is
            # never entered when the pre-execution audit cannot be committed.
            return self._failure(
                request,
                "AUDIT_INTENT_FAILED",
                "mutation intent audit could not be written; execution was skipped",
            )

        if approval_object is not None and self.approval_verifier is not None:
            # Consume before entering the privileged executor. A failed operation must
            # not make a signed approval reusable.
            try:
                self.approval_verifier.consume(approval_object)
            except ApprovalError as exc:
                result = self._failure(request, exc.code, exc.message)
                self._audit(request, principal, exc.code, result, operation_hash=operation_hash)
                return result

        try:
            execution = self.executor.execute_mutation(request, expected_state_hash=before_hash)
        except Exception as exc:  # executor failures are converted into safe results
            execution = ExecutionResult(False, "EXECUTOR_ERROR", error=str(exc))
        verification = self._verify(request, execution)
        rollback: ExecutionResult | None = None
        rollback_attempted = False
        if execution.ok and not verification.ok:
            rollback_fn = getattr(self.executor, "rollback", None)
            if request.tool == "config_patch" and callable(rollback_fn):
                rollback_attempted = True
                try:
                    rollback = rollback_fn(request, execution)
                except Exception as exc:  # rollback is best-effort but observable
                    rollback = ExecutionResult(False, "ROLLBACK_FAILED", error=str(exc))

        result_code = "MUTATION_VERIFIED" if execution.ok and verification.ok else (
            verification.code if execution.ok else execution.code
        )
        execution_data = execution.data if isinstance(execution.data, Mapping) else {}
        internal_rollback_attempted = bool(execution_data.get("rollback_attempted"))
        internal_rollback_success = bool(execution_data.get("rollback_success"))
        result = ToolResult(
            execution.ok and verification.ok,
            result_code,
            data={
                "execution": self._sanitize_value(execution.data),
                "verification": self._sanitize_value(verification.data),
                "rollback": self._sanitize_value(rollback.data if rollback is not None else None),
                "rollback_code": rollback.code if rollback is not None else None,
                "rollback_attempted": rollback_attempted or internal_rollback_attempted,
                "rollback_success": bool(rollback is not None and rollback.ok) or internal_rollback_success,
            },
            error=self._sanitize_text(verification.error if execution.ok and not verification.ok else execution.error),
            source=source_metadata(request.tool, request.host(), request.target()),
            request_id=request.request_id,
            execution_attempted=True,
            mutation_executed=bool(
                execution.ok
                or (isinstance(execution.data, Mapping) and execution.data.get("mutation_executed") is True)
            ),
        )
        result = self._finalize_result(result)
        if not self._audit(
            request,
            principal,
            "ALLOWED",
            result,
            operation_hash=operation_hash,
            approval_id=approval_object.request_id if approval_object else None,
            before_state={"hash": before_hash},
            after_state={"data": self._sanitize_value(execution.after_state)},
            verification_result=self._sanitize_value(verification.data),
            event_type="MUTATION_RESULT",
        ):
            # The operation has already run, so surface the audit failure loudly. It
            # is never hidden behind a successful LLM-facing response.
            return self._finalize_result(
                replace(result, ok=False, code="AUDIT_FAILED", error="audit record could not be written")
            )
        return result

    def prepare_approval(self, request: ToolRequest, principal: Principal) -> ApprovalRequest | ToolResult:
        """Create a concrete approval request without executing a mutation."""

        try:
            spec = validate_tool_request(request, self.policy.limits["max_patch_bytes"])
        except ToolValidationError as exc:
            return self._failure(request, exc.code, exc.message)
        decision = self.policy.check(request, principal)
        if not decision.allowed:
            return self._failure(request, decision.code, decision.reason)
        if not decision.requires_approval:
            return self._failure(request, "APPROVAL_NOT_REQUIRED", f"{spec.level.value} does not require approval")
        before_hash = self._state_hash(request)
        if before_hash is None:
            return self._failure(request, "PRECONDITION_UNAVAILABLE", "cannot obtain current resource state")
        approval_request = self._approval_request(request, principal, decision, before_hash)
        return approval_request or self._failure(request, "APPROVAL_UNAVAILABLE", "cannot create approval request")

    def _approval_request(
        self,
        request: ToolRequest,
        principal: Principal,
        decision: PolicyDecision,
        before_hash: str,
    ) -> ApprovalRequest | None:
        if decision.approval_plane is None or request.host() is None:
            return None
        try:
            return make_approval_request(
                request,
                principal,
                before_hash,
                decision.approval_plane,
                ttl_seconds=min(300, self.policy.limits["max_wall_time_seconds"]),
            )
        except (TypeError, ValueError):
            return None

    def _state_hash(self, request: ToolRequest) -> str | None:
        try:
            value = self.executor.state_hash(request)
        except Exception:
            return None
        return value if isinstance(value, str) and value else None

    def _read(self, request: ToolRequest, principal: Principal, decision: PolicyDecision) -> ToolResult:
        try:
            execution = self.executor.execute_read(request)
        except Exception as exc:
            execution = ExecutionResult(False, "EXECUTOR_ERROR", error=str(exc))
        data = self._sanitize_read(request, execution.data)
        result = ToolResult(
            execution.ok,
            execution.code if execution.ok else execution.code,
            data=data,
            error=self._sanitize_text(execution.error),
            source=source_metadata(request.tool, request.host(), request.target()),
            request_id=request.request_id,
        )
        result = self._finalize_result(result)
        if not self._audit(request, principal, "ALLOWED", result, event_type="read"):
            return self._finalize_result(
                replace(result, ok=False, code="AUDIT_FAILED", error="audit record could not be written")
            )
        return result

    def _verify(self, request: ToolRequest, execution: ExecutionResult) -> ExecutionResult:
        try:
            return self.executor.verify(request, execution)
        except Exception as exc:
            return ExecutionResult(False, "VERIFICATION_FAILED", error=str(exc))

    def _sanitize_read(self, request: ToolRequest, data: Any) -> Any:
        if request.tool in {"journal_query", "docker_logs"}:
            normalized = normalize_log(
                data,
                max_bytes=self.policy.limits["max_read_bytes"],
                max_lines=self.policy.limits["max_read_lines"],
                severity=request.arguments.get("severity") if request.tool == "journal_query" else None,
                redactor=self.redactor,
            )
            return self._sanitize_value(normalized)
        return self._sanitize_value(data)

    def _sanitize_value(self, value: Any) -> Any:
        bounded = self._bound_value(value)
        redacted = self.redactor.value(bounded)
        return self._fit_total_result(redacted, self.policy.limits["max_total_result_bytes"])

    def _bound_value(self, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[DEPTH_LIMIT]"
        if isinstance(value, str):
            raw = value.encode("utf-8", errors="replace")
            bounded = raw[: self.policy.limits["max_read_bytes"]].decode("utf-8", errors="ignore")
            lines = bounded.splitlines()
            if len(lines) > self.policy.limits["max_read_lines"]:
                return "\n".join(lines[: self.policy.limits["max_read_lines"]]) + "\n[LINE_LIMIT]"
            return bounded
        if isinstance(value, Mapping):
            return {str(key): self._bound_value(child, depth + 1) for key, child in value.items()}
        if isinstance(value, list):
            return [self._bound_value(child, depth + 1) for child in value[: self.policy.limits["max_read_lines"]]]
        if isinstance(value, tuple):
            return [self._bound_value(child, depth + 1) for child in value[: self.policy.limits["max_read_lines"]]]
        return value

    @staticmethod
    def _json_size(value: Any) -> int:
        try:
            return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))
        except (TypeError, ValueError):
            return len(json.dumps(str(value), ensure_ascii=False).encode("utf-8"))

    @classmethod
    def _minimal_truncated_value(cls, budget: int) -> Any:
        marker = {"_truncated": True}
        if cls._json_size(marker) <= budget:
            return marker
        if cls._json_size(None) <= budget:
            return None
        return ""

    @classmethod
    def _fit_string(cls, value: str, budget: int) -> str:
        if cls._json_size(value) <= budget:
            return value
        low, high = 0, len(value)
        best = ""
        while low <= high:
            middle = (low + high) // 2
            candidate = value[:middle]
            if cls._json_size(candidate) <= budget:
                best = candidate
                low = middle + 1
            else:
                high = middle - 1
        return best

    @classmethod
    def _fit_total_result(cls, value: Any, budget: int) -> Any:
        """Keep the final serialized result within one aggregate byte budget."""

        budget = max(1, int(budget))
        if cls._json_size(value) <= budget:
            return value
        if isinstance(value, str):
            return cls._fit_string(value, budget)
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            truncated = False
            for raw_key, child in value.items():
                key = str(raw_key)
                candidate = dict(result)
                candidate[key] = child
                if cls._json_size(candidate) <= budget:
                    result = candidate
                    continue
                remaining = max(1, budget - cls._json_size(result))
                bounded_child = cls._fit_total_result(child, remaining)
                candidate[key] = bounded_child
                if cls._json_size(candidate) <= budget:
                    result = candidate
                else:
                    truncated = True
                    break
            if truncated:
                marker_candidate = dict(result)
                marker_candidate["_truncated"] = True
                while cls._json_size(marker_candidate) > budget and result:
                    result.pop(next(reversed(result)))
                    marker_candidate = dict(result)
                    marker_candidate["_truncated"] = True
                if cls._json_size(marker_candidate) <= budget:
                    return marker_candidate
            if cls._json_size(result) <= budget:
                return result
            return cls._minimal_truncated_value(budget)
        if isinstance(value, (list, tuple)):
            result: list[Any] = []
            truncated = False
            for child in value:
                candidate = result + [child]
                if cls._json_size(candidate) <= budget:
                    result = candidate
                    continue
                remaining = max(1, budget - cls._json_size(result))
                bounded_child = cls._fit_total_result(child, remaining)
                candidate = result + [bounded_child]
                if cls._json_size(candidate) <= budget:
                    result = candidate
                else:
                    truncated = True
                    break
            if truncated:
                marker_candidate = result + [{"_truncated": True}]
                while cls._json_size(marker_candidate) > budget and result:
                    result.pop()
                    marker_candidate = result + [{"_truncated": True}]
                if cls._json_size(marker_candidate) <= budget:
                    return marker_candidate
            if cls._json_size(result) <= budget:
                return result
            return cls._minimal_truncated_value(budget)
        return cls._minimal_truncated_value(budget)

    def _sanitize_text(self, value: str | None) -> str | None:
        return self.redactor.text(value) if isinstance(value, str) else value

    def _failure(self, request: ToolRequest, code: str, error: str) -> ToolResult:
        return self._finalize_result(
            ToolResult(False, code, error=self._sanitize_text(error), request_id=request.request_id)
        )

    def _finalize_result(self, result: ToolResult) -> ToolResult:
        """Bound the complete serialized ToolResult sent across the boundary."""

        budget = max(1, int(self.policy.limits["max_total_result_bytes"]))
        if self._json_size(result.as_dict()) <= budget:
            return result

        # Preserve the envelope and as much data as the remaining budget allows.
        base = replace(result, data=None, error=None, source=None, approval_request=None)
        remaining = max(1, budget - self._json_size(base.as_dict()))
        data = self._fit_total_result(result.data, remaining)
        candidate = replace(result, data=data, error=None, source=None, approval_request=None)
        if self._json_size(candidate.as_dict()) <= budget:
            return candidate

        # Errors and metadata are less useful than a bounded, explicit result
        # marker. Drop them if necessary; never return an oversized response.
        candidate = replace(
            result,
            data=self._minimal_truncated_value(remaining),
            error=None,
            source=None,
            approval_request=None,
            request_id=str(result.request_id or "")[:64],
        )
        if self._json_size(candidate.as_dict()) <= budget:
            return candidate
        return ToolResult(
            ok=False,
            code="RESULT_TOO_LARGE",
            data=None,
            error="tool result exceeded the Broker aggregate byte limit",
            request_id=str(result.request_id or "")[:32],
        )

    def _audit(
        self,
        request: ToolRequest,
        principal: Principal,
        policy_result: str,
        result: ToolResult,
        *,
        operation_hash: str | None = None,
        approval_id: str | None = None,
        before_state: Any = None,
        after_state: Any = None,
        verification_result: Any = None,
        event_type: str = "tool_call",
    ) -> bool:
        try:
            self.audit.record(
                request,
                principal,
                policy_result=policy_result,
                arguments=self._sanitize_value(dict(request.arguments)),
                result=result,
                approval_id=approval_id,
                operation_hash=operation_hash,
                before_state=self._sanitize_value(before_state),
                after_state=self._sanitize_value(after_state),
                verification_result=self._sanitize_value(verification_result),
                event_type=event_type,
            )
        except Exception:
            return False
        return True
