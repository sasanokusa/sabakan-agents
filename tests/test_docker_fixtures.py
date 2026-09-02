from __future__ import annotations

import unittest

from evaluation.docker_fixtures import fixture_cases


class DockerFixtureDefinitionTests(unittest.TestCase):
    def test_initial_docker_cases_use_only_fixed_broker_operations(self) -> None:
        cases = fixture_cases()
        self.assertEqual([case.incident_id for case in cases], ["incident-001", "incident-002", "incident-003"])
        self.assertEqual(
            [case.tool for case in cases], ["service_restart", "docker_restart", "log_rotate"]
        )
        for case in cases:
            self.assertEqual(case.arguments["host"], "local")
            self.assertNotIn("shell", case.arguments)
            self.assertNotIn("command", case.arguments)
