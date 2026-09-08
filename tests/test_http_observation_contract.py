from types import SimpleNamespace
import unittest
from unittest.mock import patch
from evaluation.http_fixtures import HttpExecutor
from sabakan_broker.models import ExecutionResult, ToolRequest


class HttpObservationContractTests(unittest.TestCase):
    def test_opt_in_preserves_actual_body_and_names_without_fault_truth(self):
        probe = {'ok': False, 'http_status': 503, 'body': {'status': 'dependency_unavailable'}}
        fixture = SimpleNamespace(frontend='front', backend='back', config_path=None, probe=lambda: probe)
        request = ToolRequest('service_status', {'host': 'local', 'service': 'nginx'})
        with patch('evaluation.docker_fixtures.DockerFixtureExecutor.execute_read', return_value=ExecutionResult(True, 'READ_OK', {'status': 'running'})):
            old = HttpExecutor(fixture).execute_read(request)
            new = HttpExecutor(fixture, observation_version=2).execute_read(request)
        self.assertNotIn('http_response', old.data)
        self.assertEqual(new.data['http_response'], probe)
        self.assertEqual(new.data['managed_configuration'], 'nginx-main')
        self.assertEqual(new.data['dependency_container'], 'sabakan')
        self.assertEqual({k: new.data[k] for k in old.data}, old.data)
        self.assertNotIn('fault', new.data)
