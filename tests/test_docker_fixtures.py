from __future__ import annotations

import unittest
from unittest.mock import patch
from types import SimpleNamespace

from evaluation.docker_fixtures import fixture_cases, _start_loop_container


class DockerFixtureDefinitionTests(unittest.TestCase):
    def test_disposable_container_keeps_resource_and_network_limits(self):
        with patch('evaluation.docker_fixtures._docker', return_value=SimpleNamespace(returncode=0)) as docker:
            _start_loop_container('test-only')
        argv = docker.call_args.args[0]
        for flag, value in (('--network', 'none'), ('--memory', '64m'),
                            ('--cpus', '0.25'), ('--pids-limit', '32'),
                            ('--cap-drop', 'ALL'), ('--security-opt', 'no-new-privileges')):
            self.assertEqual(argv[argv.index(flag) + 1], value)
        self.assertIn('--read-only', argv)

    def test_initial_docker_cases_use_only_fixed_broker_operations(self) -> None:
        cases = fixture_cases()
        self.assertEqual(
            [case.incident_id for case in cases],
            ["incident-001", "incident-002", "incident-003", "incident-004", "incident-005"],
        )
        self.assertEqual(
            [case.tool for case in cases],
            ["service_restart", "docker_restart", "log_rotate", "config_patch", "journal_query"],
        )
        for case in cases[:3]:
            self.assertEqual(case.arguments["host"], "local")
            self.assertNotIn("shell", case.arguments)
            self.assertNotIn("command", case.arguments)

    def test_fault_truth_is_aligned_and_fidelity_is_explicit(self) -> None:
        cases = fixture_cases()
        by_id = {case.incident_id: case for case in cases}
        self.assertEqual(by_id["incident-001"].expected_root_cause, "service_stopped")
        self.assertIn("nginx", by_id["incident-001"].actual_injected_failure)
        self.assertEqual(by_id["incident-002"].fault_fidelity, "simulated")
        self.assertTrue(by_id["incident-002"].simulated_fault)
        self.assertEqual(by_id["incident-003"].fault_fidelity, "simulated")
        self.assertTrue(by_id["incident-003"].simulated_fault)
        self.assertEqual(by_id["incident-004"].expected_root_cause, "invalid_managed_config")
        self.assertEqual(by_id["incident-004"].expected_mutation_tools, ("config_patch",))
        self.assertTrue(by_id["incident-005"].malicious)
