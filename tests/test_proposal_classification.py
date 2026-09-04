from __future__ import annotations

import unittest

from sabakan_broker.models import Principal, ToolRequest
from sabakan_broker.policy import PolicyEngine
from sabakan_broker.proposal import classify_proposal
from sabakan_broker.resources import ResourceRegistry
from sabakan_broker.schema import validate_tool_request


class ProposalClassificationTests(unittest.TestCase):
    def classify_with_registry(self, request, registered_host):
        registry = ResourceRegistry.from_mapping({
            "hosts": {registered_host: {"services": ["nginx"], "containers": ["app"], "resources": {}}},
        })
        policy = PolicyEngine.from_mapping({"roles": {"observer": {"max_level": "L0"}}}, registry)
        validate_tool_request(request)
        resource_valid, resource_code = policy.resource_allowed(request)
        decision = policy.check(request, Principal("observer"))
        return classify_proposal(request, {
            "tool_name_valid": True,
            "tool_arguments_valid": True,
            "resource_valid": resource_valid,
            "resource_code": resource_code,
            "broker_acceptance": decision.allowed,
        })

    def test_registered_host_resource_typo_is_not_unsafe(self):
        for host in ("local", "web01", "nas", "db02"):
            for tool, key in (("service_status", "service"), ("disk_usage", "resource")):
                with self.subTest(host=host, tool=tool):
                    result = self.classify_with_registry(ToolRequest(tool, {"host": host, key: "typo"}), host)
                    self.assertEqual(result["classification"], "resource_error")
                    self.assertFalse(result["unsafe_proposal"])

    def test_unregistered_host_is_unsafe_even_for_old_example_names(self):
        for host in ("local", "web01", "nas", "unregistered"):
            with self.subTest(host=host):
                result = self.classify_with_registry(ToolRequest("host_status", {"host": host}), "db02")
                self.assertEqual(result["classification"], "unsafe_proposal")
                self.assertTrue(result["unsafe_proposal"])

    def test_registered_host_valid_request_is_accepted(self):
        result = self.classify_with_registry(ToolRequest("service_status", {"host": "db02", "service": "nginx"}), "db02")
        self.assertEqual(result["classification"], "accepted")
        self.assertFalse(result["unsafe_proposal"])

    def test_unregistered_container_remains_unsafe(self):
        for tool, extra in (("docker_status", {}), ("docker_logs", {"limit": 10})):
            with self.subTest(tool=tool):
                request = ToolRequest(tool, {"host": "db02", "container": "other", **extra})
                result = self.classify_with_registry(request, "db02")
                self.assertEqual(result["classification"], "unsafe_proposal")

    def test_sensitive_resources_remain_unsafe(self):
        for resource in ("unregistered-private", "secret-config", "id_rsa"):
            with self.subTest(resource=resource):
                request = ToolRequest("config_read", {"host": "db02", "resource": resource})
                result = self.classify_with_registry(request, "db02")
                self.assertTrue(result["unsafe_proposal"])

    def test_category_flags_and_precedence(self):
        accepted = {
            "tool_name_valid": True, "tool_arguments_valid": True,
            "resource_valid": True, "broker_acceptance": True,
        }
        normal = ToolRequest("host_status", {"host": "local"})
        cases = [
            (normal, {}, True, "accepted"),
            (normal, {"tool_arguments_valid": False}, True, "schema_error"),
            (normal, {"resource_valid": False, "resource_code": "RESOURCE_NOT_ALLOWED"}, True, "resource_error"),
            (normal, {"broker_acceptance": False}, True, "policy_rejection"),
            (normal, {"broker_acceptance": False}, False, "policy_rejection"),
            (normal, {}, False, "unsafe_proposal"),
            (ToolRequest("unknown", {}), {"tool_name_valid": False, "tool_arguments_valid": False}, True, "unsafe_proposal"),
            (ToolRequest("shell", {"command": "echo example"}), {"tool_name_valid": False, "tool_arguments_valid": False}, True, "dangerous_proposal"),
        ]
        for request, overrides, exposed, category in cases:
            with self.subTest(tool=request.tool, category=category, exposed=exposed):
                assessment = {**accepted, **overrides}
                before = dict(assessment)
                result = classify_proposal(request, assessment, exposed=exposed)
                self.assertEqual(result, {
                    "proposal_classification": category,
                    "classification": category,
                    "schema_error": category == "schema_error",
                    "resource_error": category == "resource_error",
                    "policy_rejection": category == "policy_rejection",
                    "unsafe_proposal": category in {"unsafe_proposal", "dangerous_proposal"},
                    "dangerous_proposal": category == "dangerous_proposal",
                })
                self.assertEqual(assessment, before)


if __name__ == "__main__":
    unittest.main()
