from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import evaluation.request_controls as request_controls
from evaluation.request_controls import (
    PROTOCOL,
    SafeFakeExecutor,
    _run_case,
    _observed_label,
    _build_broker,
    fixed_request_cases,
    run_request_controls,
    summarize_control_results,
)
from sabakan_broker.models import ExecutionResult, ToolResult


class RequestControlEvaluationTests(unittest.TestCase):
    def test_fixed_expectations_are_declared_independently(self) -> None:
        cases = fixed_request_cases()
        self.assertGreaterEqual(len(cases), 10)
        self.assertEqual(
            {case.expected_label for case in cases},
            {"allow", "deny", "approval_required"},
        )
        self.assertEqual(len({case.case_id for case in cases}), len(cases))
        # The expected label is protocol data, separate from any Broker result.
        self.assertEqual(
            next(case for case in cases if case.case_id == "legitimate_read").expected_label,
            "allow",
        )
        self.assertEqual(
            next(case for case in cases if case.case_id == "forbidden_request").expected_label,
            "deny",
        )

    def test_run_is_bounded_json_serializable_and_uses_real_broker(self) -> None:
        report = run_request_controls()
        json.dumps(report, ensure_ascii=False, allow_nan=False)
        self.assertEqual(report["protocol"], PROTOCOL)
        self.assertTrue(report["bounded"])
        self.assertFalse(report["model_runtime"])
        self.assertEqual(report["broker_implementation"], "sabakan_broker.broker.Broker")
        self.assertEqual(report["executor"], "safe_fake_executor")
        self.assertEqual(report["case_count"], len(fixed_request_cases()))
        self.assertEqual(report["metrics"]["unknown_case_count"], 0)

    def test_control_cases_cover_allow_approval_rejection_and_preconditions(self) -> None:
        report = run_request_controls()
        cases = {item["case_id"]: item for item in report["cases"]}

        self.assertEqual(cases["legitimate_read"]["observed_label"], "allow")
        self.assertEqual(cases["legitimate_read"]["code"], "READ_OK")
        self.assertEqual(cases["legitimate_l1"]["code"], "MUTATION_VERIFIED")
        self.assertEqual(cases["valid_l2_approval_required"]["observed_label"], "approval_required")
        self.assertEqual(cases["valid_l2_approved"]["code"], "MUTATION_VERIFIED")
        self.assertEqual(cases["invalid_resource"]["code"], "RESOURCE_NOT_ALLOWED")
        self.assertEqual(cases["forbidden_request"]["code"], "POLICY_DENIED")
        self.assertEqual(cases["approval_tamper"]["code"], "APPROVAL_MISMATCH")
        self.assertEqual(cases["approval_expiry"]["code"], "APPROVAL_EXPIRED")
        self.assertEqual(cases["approval_replay"]["code"], "APPROVAL_REPLAY")
        self.assertEqual(cases["changed_precondition"]["code"], "PRECONDITION_FAILED")
        self.assertEqual(cases["mutation_budget"]["code"], "AUTO_REMEDIATION_SUSPENDED")

        for case_id in (
            "invalid_resource",
            "forbidden_request",
            "approval_tamper",
            "approval_expiry",
            "approval_replay",
            "changed_precondition",
            "mutation_budget",
        ):
            self.assertTrue(cases[case_id]["blocked"], case_id)
            self.assertEqual(cases[case_id]["executor_target_entries"]["mutation"], 0, case_id)

    def test_aggregates_keep_false_rejection_blocking_unknown_and_na_distinct(self) -> None:
        records = [
            {"expected_label": "allow", "observed_label": "deny", "false_rejection": True, "blocked": False},
            {"expected_label": "deny", "observed_label": "deny", "false_rejection": False, "blocked": True},
            {"expected_label": "approval_required", "observed_label": "unknown", "false_rejection": None, "blocked": None},
        ]
        metrics = summarize_control_results(records)
        self.assertEqual(metrics["false_rejection"], {"numerator": 1, "denominator": 1, "unknown": 0, "rate": 1.0})
        self.assertEqual(metrics["blocking"], {"numerator": 1, "denominator": 1, "unknown": 0, "rate": 1.0})
        self.assertEqual(metrics["approval_required"]["unknown"], 1)
        self.assertIsNone(summarize_control_results([])["allow"]["rate"])
        self.assertIsNone(summarize_control_results([])["blocking"]["rate"])

    def test_all_refusal_is_visible_as_false_rejection(self) -> None:
        # A system that refuses every request can look perfect on a deny-only
        # score. The allow denominator keeps that failure visible.
        records = [
            {"expected_label": "allow", "observed_label": "deny", "false_rejection": True, "blocked": True}
            for _ in range(3)
        ]
        metrics = summarize_control_results(records)
        self.assertEqual(metrics["false_rejection"]["numerator"], 3)
        self.assertEqual(metrics["false_rejection"]["denominator"], 3)
        self.assertEqual(metrics["false_rejection"]["rate"], 1.0)
        self.assertEqual(metrics["blocking"]["denominator"], 0)
        self.assertIsNone(metrics["blocking"]["rate"])

    def test_executor_and_verification_failures_are_unknown(self) -> None:
        for result in (
            ToolResult(False, "EXECUTOR_ERROR", execution_attempted=True),
            ToolResult(False, "VERIFICATION_FAILED", execution_attempted=True),
            ToolResult(False, "PRECONDITION_FAILED", execution_attempted=True),
            ToolResult(False, "AUDIT_FAILED"),
        ):
            self.assertEqual(_observed_label(result), "unknown")
        self.assertEqual(_observed_label(ToolResult(False, "POLICY_DENIED")), "deny")

    def test_failed_replay_or_budget_setup_is_unknown(self) -> None:
        class FailingSeedExecutor(SafeFakeExecutor):
            def execute_mutation(self, request, expected_state_hash=None):
                if request.incident_id in {
                    "request-controls-approval-replay",
                    "request-controls-mutation-budget-seed",
                }:
                    return ExecutionResult(False, "EXECUTOR_ERROR", error="seed failed")
                return super().execute_mutation(request, expected_state_hash)

        original_builder = _build_broker

        def failing_builder(directory, *, executor=None, clock=None):
            return original_builder(directory, executor=FailingSeedExecutor(), clock=clock)

        with patch.object(request_controls, "_build_broker", failing_builder):
            for case_id in ("approval_replay", "mutation_budget"):
                case = next(case for case in fixed_request_cases() if case.case_id == case_id)
                with tempfile.TemporaryDirectory() as directory:
                    record = _run_case(case, Path(directory))
                self.assertEqual(record["observed_label"], "unknown", case_id)
                self.assertTrue(record["unknown"], case_id)
                self.assertIsNone(record["blocked"], case_id)


if __name__ == "__main__":
    unittest.main()
