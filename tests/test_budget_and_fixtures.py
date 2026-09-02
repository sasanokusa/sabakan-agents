from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sabakan_broker.config import load_mapping
from sabakan_broker.models import ToolRequest

from tests.support import build_broker


class BudgetAndFixtureTests(unittest.TestCase):
    def test_resource_budget_suspends_repeated_auto_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            first = broker.handle(
                ToolRequest("service_restart", {"host": "local", "service": "nginx"}, incident_id="one"), principal
            )
            second = broker.handle(
                ToolRequest("service_restart", {"host": "local", "service": "nginx"}, incident_id="two"), principal
            )
            self.assertTrue(first.ok)
            self.assertEqual(second.code, "AUTO_REMEDIATION_SUSPENDED")
            self.assertEqual(len(executor.mutation_calls), 1)

    def test_host_circuit_breaker_stops_mutations_across_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            requests = [
                ToolRequest("service_restart", {"host": "local", "service": "nginx"}, incident_id="host-1"),
                ToolRequest("docker_restart", {"host": "local", "container": "sabakan"}, incident_id="host-2"),
                ToolRequest("docker_restart", {"host": "local", "container": "sabakan"}, incident_id="host-3"),
                ToolRequest("log_rotate", {"host": "local", "resource": "nginx-main"}, incident_id="host-4"),
            ]
            results = [broker.handle(request, principal) for request in requests]
            self.assertTrue(all(result.ok for result in results[:3]))
            self.assertEqual(results[3].code, "CIRCUIT_OPEN")
            self.assertEqual(len(executor.mutation_calls), 3)

    def test_fixture_files_have_explicit_safety_expectations(self) -> None:
        root = Path(__file__).parent / "incidents"
        scenario_paths = sorted(root.glob("*/scenario.yaml"))
        self.assertGreaterEqual(len(scenario_paths), 8)
        for path in scenario_paths:
            scenario = load_mapping(path)
            self.assertIn("expected_root_cause", scenario, path.name)
            self.assertIn("allowed_actions", scenario, path.name)
            self.assertIn("forbidden_actions", scenario, path.name)
            self.assertEqual(scenario["unsafe_action_rate"], 0)

    def test_identical_tool_loop_is_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            broker, executor, principal = build_broker(Path(directory))
            request = ToolRequest("host_status", {"host": "local"}, incident_id="loop-1")
            results = [broker.handle(request, principal) for _ in range(3)]
            self.assertTrue(results[0].ok)
            self.assertTrue(results[1].ok)
            self.assertEqual(results[2].code, "LOOP_DETECTED")
            self.assertEqual(len(executor.read_calls), 2)
