from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from sabakan_broker.models import ToolRequest
from sabakan_broker.schema import TOOL_SPECS, ToolValidationError, openai_function_schema, validate_tool_request


class SchemaContractTests(unittest.TestCase):
    def setUp(self):
        self.requests = {
            "journal_query": {"host": "local", "service": "nginx", "since": "1 hour ago", "severity": "info", "limit": 10},
            "process_list": {"host": "local", "sort": "cpu"},
        }

    def assert_invalid(self, request, code="INVALID_ARGUMENT", **kwargs):
        with self.assertRaises(ToolValidationError) as raised:
            validate_tool_request(request, **kwargs)
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_declared_enum_values_are_accepted(self):
        for tool, arguments in self.requests.items():
            properties = openai_function_schema(tool)["parameters"]["properties"]
            for key, choices in TOOL_SPECS[tool].argument_enums.items():
                self.assertEqual(properties[key]["enum"], list(choices))
                for value in choices:
                    with self.subTest(tool=tool, key=key, value=value):
                        validate_tool_request(ToolRequest(tool, {**arguments, key: value}))

    def test_undeclared_enum_values_are_rejected(self):
        for tool, arguments in self.requests.items():
            for key in TOOL_SPECS[tool].argument_enums:
                with self.subTest(tool=tool, key=key):
                    self.assert_invalid(ToolRequest(tool, {**arguments, key: "not-a-choice"}))

    def test_narrowing_enum_metadata_also_narrows_validation(self):
        spec = replace(TOOL_SPECS["process_list"], argument_enums={"sort": ("pid",)})
        with patch.dict(TOOL_SPECS, {"process_list": spec}):
            self.assertEqual(openai_function_schema("process_list")["parameters"]["properties"]["sort"]["enum"], ["pid"])
            self.assert_invalid(ToolRequest("process_list", {"host": "local", "sort": "cpu"}))
            validate_tool_request(ToolRequest("process_list", {"host": "local", "sort": "pid"}))

    def test_extending_enum_metadata_also_extends_validation(self):
        # This changes only a test-local code-owned ToolSpec, never model input.
        spec = replace(TOOL_SPECS["process_list"], argument_enums={"sort": ("cpu", "elapsed")})
        with patch.dict(TOOL_SPECS, {"process_list": spec}):
            self.assertIn("elapsed", openai_function_schema("process_list")["parameters"]["properties"]["sort"]["enum"])
            validate_tool_request(ToolRequest("process_list", {"host": "local", "sort": "elapsed"}))

    def test_enum_validation_is_not_tied_to_tool_names(self):
        spec = replace(TOOL_SPECS["host_status"], argument_enums={"host": ("db02",)})
        with patch.dict(TOOL_SPECS, {"host_status": spec}):
            validate_tool_request(ToolRequest("host_status", {"host": "db02"}))
            self.assert_invalid(ToolRequest("host_status", {"host": "local"}))

    def test_enum_metadata_does_not_bypass_identifier_validation(self):
        spec = replace(TOOL_SPECS["process_list"], argument_enums={"sort": ("..",)})
        with patch.dict(TOOL_SPECS, {"process_list": spec}):
            error = self.assert_invalid(ToolRequest("process_list", {"host": "local", "sort": ".."}))
            self.assertIn("path traversal", error.message)

    def test_argument_validation_still_precedes_enum_validation(self):
        request = ToolRequest("journal_query", {**self.requests["journal_query"], "severity": "invalid", "limit": 0})
        self.assertIn("limit", self.assert_invalid(request).message)

    def test_request_shape_and_limits_remain_enforced(self):
        cases = [
            (ToolRequest("unknown", {}), "UNKNOWN_TOOL"),
            (ToolRequest("host_status", []), "INVALID_ARGUMENT"),
            (ToolRequest("host_status", {}), "MISSING_ARGUMENT"),
            (ToolRequest("host_status", {"host": "local", "command": "ls"}), "UNKNOWN_ARGUMENT"),
        ]
        for value in (True, False, 0, 5001, "10", 1.5, None):
            cases.append((ToolRequest("journal_query", {**self.requests["journal_query"], "limit": value}), "INVALID_ARGUMENT"))
        for request, code in cases:
            with self.subTest(tool=request.tool, arguments=request.arguments):
                self.assert_invalid(request, code)

    def test_patch_safety_limits_remain_enforced(self):
        arguments = {"host": "local", "resource": "nginx-main"}
        for value in ([], {"..": 1}, {"items": [0] * 513}):
            with self.subTest(value_type=type(value).__name__):
                self.assert_invalid(ToolRequest("config_patch", {**arguments, "patch": value}))
        self.assert_invalid(
            ToolRequest("config_patch", {**arguments, "patch": {"value": "x" * 40}}),
            "ARGUMENT_TOO_LARGE", max_patch_bytes=32,
        )


if __name__ == "__main__":
    unittest.main()
