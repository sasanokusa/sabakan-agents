from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from evaluation.adapters import adapt_output
from scripts.evaluate_llamacpp import build_chat_completion_payload
from scripts.evaluate_models import (
    MODEL_TOOL_SCHEMAS,
    MODEL_VISIBLE_TOOLS,
    build_assessment_broker,
    build_prompt,
    evaluate_output,
    read_benchmark,
)
from sabakan_broker.api import BrokerAPI
from sabakan_broker.config import load_mapping
from sabakan_broker.models import ExecutionResult, Principal, ToolRequest
from sabakan_broker.policy import PolicyEngine
from sabakan_broker.resources import ResourceRegistry
from sabakan_broker.schema import TOOL_SPECS, openai_tool_schemas

from tests.support import build_broker


ROOT = Path(__file__).resolve().parents[1]


class NextStageSecurityTests(unittest.TestCase):
    def test_openai_tools_are_generated_from_broker_tool_specs(self) -> None:
        generated = openai_tool_schemas()
        self.assertEqual(
            [item["function"]["name"] for item in generated], list(TOOL_SPECS)
        )
        for item in generated:
            function = item["function"]
            spec = TOOL_SPECS[function["name"]]
            parameters = function["parameters"]
            self.assertEqual(parameters["required"], list(spec.required))
            self.assertEqual(set(parameters["properties"]), set(spec.allowed_arguments))
            self.assertFalse(parameters["additionalProperties"])

    def test_llama_cpp_payload_passes_same_broker_tools_and_token_budget(self) -> None:
        payload = build_chat_completion_payload(build_prompt({"id": "incident-001"}), MODEL_TOOL_SCHEMAS, 384)
        self.assertEqual(payload["tools"], list(MODEL_TOOL_SCHEMAS))
        self.assertEqual(
            [item["function"]["name"] for item in payload["tools"]], list(MODEL_VISIBLE_TOOLS)
        )
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertEqual(payload["max_tokens"], 384)

    def test_function_message_without_tool_call_is_a_valid_empty_proposal(self) -> None:
        result = adapt_output(
            "",
            {"content": "The root cause is DNS resolution failure.", "tool_calls": []},
        )
        self.assertTrue(result.envelope_valid)
        self.assertEqual(result.source_format, "llama_cpp_message")
        self.assertEqual(result.proposal["tool_calls"], [])

    def test_model_prompt_contains_only_opaque_id_and_public_context(self) -> None:
        fixtures = read_benchmark(ROOT / "evaluation" / "benchmark.json")
        for fixture in fixtures:
            messages = build_prompt(fixture)
            serialized = json.dumps(messages, ensure_ascii=False)
            self.assertIn(fixture["id"], serialized)
            self.assertNotIn(fixture["fixture"], serialized)
            self.assertNotIn(fixture["expected_root_cause"], serialized)
            for hidden_key in (
                "expected_root_cause",
                "expected_remediation",
                "success_criteria",
                "allowed_mutation_tools",
                "forbidden_tools",
                "malicious",
            ):
                self.assertNotIn(f'"{hidden_key}"', serialized)
            self.assertNotIn(json.dumps(fixture["allowed_mutation_tools"], ensure_ascii=False), serialized)
            self.assertNotIn(json.dumps(fixture["forbidden_tools"], ensure_ascii=False), serialized)
        user_view = json.loads(build_prompt(fixtures[0])[1]["content"])
        self.assertEqual(set(user_view), {"incident_id", "symptom", "observations", "task"})
        self.assertNotIn("approval_required", build_prompt(fixtures[0])[0]["content"])

    def test_model_adapters_normalize_json_openai_and_lfm_native(self) -> None:
        json_result = adapt_output(
            json.dumps(
                {
                    "hypothesis": "container out of memory",
                    "tool_calls": [
                        {"tool": "docker_status", "parameters": {"host": "local", "container": "sabakan"}}
                    ],
                    "approval_required": False,
                }
            )
        )
        self.assertTrue(json_result.envelope_valid)
        self.assertFalse("approval_required" in json_result.proposal)
        self.assertEqual(json_result.proposal["tool_calls"][0]["arguments"]["container"], "sabakan")
        self.assertFalse(json_result.llm_approval_signal)

        openai_result = adapt_output(
            "diagnosis",
            {
                "content": "diagnosis",
                "tool_calls": [
                    {"type": "function", "function": {"name": "host_status", "arguments": '{"host":"local"}'}}
                ],
            },
        )
        self.assertEqual(openai_result.source_format, "llama_cpp_tool_calls")
        self.assertEqual(openai_result.proposal["tool_calls"][0]["arguments"], {"host": "local"})

        native_result = adapt_output(
            "<|tool_call_start|>[docker_status(host='local', container='sabakan')]<|tool_call_end|>"
        )
        self.assertTrue(native_result.envelope_valid)
        self.assertEqual(native_result.source_format, "lfm_native")
        self.assertEqual(native_result.proposal["tool_calls"][0]["tool"], "docker_status")
        self.assertEqual(native_result.proposal["tool_calls"][0]["arguments"]["host"], "local")

    def test_permission_floor_cannot_be_lowered_but_can_be_raised(self) -> None:
        resources = ResourceRegistry.from_mapping(load_mapping(ROOT / "config" / "resources.yaml"))
        raw = load_mapping(ROOT / "config" / "policy.yaml")
        raw["tool_levels"]["system_reboot"] = "L0"
        raw["tool_levels"]["config_patch"] = "L0"
        raw["tool_levels"]["service_restart"] = "L3"
        policy = PolicyEngine.from_mapping(raw, resources)
        self.assertEqual(policy.level_for("system_reboot").value, "L3")
        self.assertEqual(policy.level_for("config_patch").value, "L2")
        self.assertEqual(policy.level_for("service_restart").value, "L3")

    def test_broker_schema_rejects_shell_like_and_unknown_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            invalid_patch = ToolRequest(
                "config_patch",
                {
                    "host": "local",
                    "resource": "nginx-main",
                    "permission_fix": "chmod 600 /etc/ssl/private/site.key",
                },
            )
            assessed = broker.assess_proposal(invalid_patch, principal)
            self.assertFalse(assessed["tool_arguments_valid"])
            self.assertFalse(assessed["broker_acceptance"])
            self.assertEqual(broker.handle(invalid_patch, principal).code, "MISSING_ARGUMENT")

            unknown = broker.handle(
                ToolRequest("host_status", {"host": "local", "command": "rm -rf /"}), principal
            )
            self.assertEqual(unknown.code, "UNKNOWN_ARGUMENT")
            shell_like = broker.handle(
                ToolRequest("service_status", {"host": "local", "service": "nginx; reboot"}), principal
            )
            self.assertEqual(shell_like.code, "INVALID_ARGUMENT")
            self.assertEqual(executor.read_calls, [])

    def test_approval_is_broker_policy_result_not_llm_protocol(self) -> None:
        fixture = {
            "id": "incident-test",
            "expected_root_cause": "certificate_expired",
            "allowed_mutation_tools": ["config_patch"],
            "forbidden_tools": [],
            "malicious": False,
        }
        result = evaluate_output(
            json.dumps(
                {
                    "hypothesis": "certificate expired",
                    "tool_calls": [
                        {
                            "tool": "config_patch",
                            "arguments": {
                                "host": "local",
                                "resource": "nginx-main",
                                "patch": {"enabled": True},
                            },
                        }
                    ],
                    "approval_required": False,
                }
            ),
            fixture,
            10,
            5,
            0.5,
            assessor=build_assessment_broker(),
        )
        self.assertTrue(result["plan_validity"])
        self.assertTrue(result["broker_acceptance"])
        self.assertTrue(result["broker_approval_required"])
        self.assertEqual(result["approval_requests"], 1)
        self.assertFalse("approval_required" in result["canonical_proposal"])
        self.assertFalse(result["llm_approval_signal_alignment"])

        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            response = BrokerAPI(broker).handle(
                {
                    "tool": "config_patch",
                    "arguments": {
                        "host": "local",
                        "resource": "nginx-main",
                        "patch": {"enabled": True},
                    },
                    "approval_required": False,
                },
                principal=principal,
            )
            self.assertEqual(response["code"], "APPROVAL_REQUIRED")
            self.assertEqual(executor.mutation_calls, [])

    def test_guard_budget_and_circuit_survive_broker_recreation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            first, executor, principal = build_broker(path)
            requests = [
                ToolRequest("service_restart", {"host": "local", "service": "nginx"}, incident_id="p-1"),
                ToolRequest("docker_restart", {"host": "local", "container": "sabakan"}, incident_id="p-2"),
                ToolRequest("docker_restart", {"host": "local", "container": "sabakan"}, incident_id="p-3"),
            ]
            self.assertTrue(all(first.handle(request, principal).ok for request in requests))
            self.assertEqual(len(executor.mutation_calls), 3)
            self.assertEqual(
                first.handle(
                    ToolRequest("log_rotate", {"host": "local", "resource": "nginx-main"}, incident_id="p-4"),
                    principal,
                ).code,
                "CIRCUIT_OPEN",
            )

            second, second_executor, second_principal = build_broker(path)
            fourth = second.handle(
                ToolRequest("log_rotate", {"host": "local", "resource": "nginx-main"}, incident_id="p-4"),
                second_principal,
            )
            self.assertEqual(fourth.code, "CIRCUIT_OPEN")
            self.assertTrue(second.guard.circuit_open("local"))
            self.assertEqual(second_executor.mutation_calls, [])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            first, _, principal = build_broker(path)
            self.assertTrue(
                first.handle(
                    ToolRequest("service_restart", {"host": "local", "service": "nginx"}, incident_id="r-1"),
                    principal,
                ).ok
            )
            self.assertEqual(
                first.handle(
                    ToolRequest("service_restart", {"host": "local", "service": "nginx"}, incident_id="r-2"),
                    principal,
                ).code,
                "AUTO_REMEDIATION_SUSPENDED",
            )
            second, executor, principal = build_broker(path)
            suspended = second.handle(
                ToolRequest("service_restart", {"host": "local", "service": "nginx"}, incident_id="r-2"),
                principal,
            )
            self.assertEqual(suspended.code, "AUTO_REMEDIATION_SUSPENDED")
            self.assertTrue(second.guard.resource_suspended("local", "nginx"))
            self.assertEqual(executor.mutation_calls, [])

    def test_mutation_has_intent_and_result_audits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            result = broker.handle(
                ToolRequest("service_restart", {"host": "local", "service": "nginx"}), principal
            )
            self.assertTrue(result.ok)
            event_types = {event["event_type"] for event in broker.audit.list_events()}
            self.assertIn("MUTATION_INTENT", event_types)
            self.assertIn("MUTATION_RESULT", event_types)
            self.assertEqual(len(executor.mutation_calls), 1)

    def test_intent_audit_failure_is_fail_closed(self) -> None:
        class FailingIntentAudit:
            def record(self, *args: Any, **kwargs: Any) -> None:
                if kwargs.get("event_type") == "MUTATION_INTENT":
                    raise OSError("audit unavailable")

        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            broker.audit = FailingIntentAudit()  # type: ignore[assignment]
            result = broker.handle(
                ToolRequest("service_restart", {"host": "local", "service": "nginx"}), principal
            )
            self.assertEqual(result.code, "AUDIT_INTENT_FAILED")
            self.assertEqual(executor.mutation_calls, [])

    def test_result_audit_failure_is_reported_after_execution(self) -> None:
        class FailingResultAudit:
            def record(self, *args: Any, **kwargs: Any) -> None:
                if kwargs.get("event_type") == "MUTATION_RESULT":
                    raise OSError("result audit unavailable")

        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            broker.audit = FailingResultAudit()  # type: ignore[assignment]
            result = broker.handle(
                ToolRequest("service_restart", {"host": "local", "service": "nginx"}), principal
            )
            self.assertEqual(result.code, "AUDIT_FAILED")
            self.assertEqual(len(executor.mutation_calls), 1)

    def test_total_result_bytes_bound_nested_values_lists_and_logs(self) -> None:
        payloads: list[tuple[ToolRequest, Any]] = [
            (
                ToolRequest("host_status", {"host": "local"}),
                {f"small_{index}": "x" * 12 for index in range(100)},
            ),
            (
                ToolRequest("host_status", {"host": "local"}),
                {"level": {"child": {"nested": {"value": "x" * 1000}}}},
            ),
            (ToolRequest("host_status", {"host": "local"}), ["item" * 20 for _ in range(100)]),
        ]
        for request, payload in payloads:
            with self.subTest(request=request.tool, payload_type=type(payload).__name__), tempfile.TemporaryDirectory() as directory:
                broker, executor, _ = build_broker(Path(directory))
                broker.policy.limits["max_total_result_bytes"] = 256

                def read(_request: ToolRequest, value: Any = payload) -> ExecutionResult:
                    executor.read_calls.append(_request)
                    return ExecutionResult(True, "READ_OK", value)

                executor.execute_read = read  # type: ignore[method-assign]
                result = broker.handle(request, Principal("alice", roles=frozenset({"owner"})))
                self.assertTrue(result.ok)
                self.assertLessEqual(broker._json_size(result.data), 256)
                self.assertLessEqual(broker._json_size(result.as_dict()), 256)

        with tempfile.TemporaryDirectory() as directory:
            broker, executor, _ = build_broker(Path(directory))
            broker.policy.limits["max_total_result_bytes"] = 256
            executor.log = "\n".join(f"INFO unique log event {index} {'x' * 40}" for index in range(100))
            result = broker.handle(
                ToolRequest(
                    "journal_query",
                    {"host": "local", "service": "nginx", "since": "1 hour ago", "severity": "info", "limit": 500},
                ),
                Principal("alice", roles=frozenset({"owner"})),
            )
            self.assertTrue(result.ok)
            self.assertLessEqual(broker._json_size(result.data), 256)
            self.assertLessEqual(broker._json_size(result.as_dict()), 256)
