from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from evaluation.http_fixtures import HttpExecutor, HttpCase
from evaluation.http_trials import run_http_trial
from sabakan_broker.models import ExecutionResult, ToolRequest


class HttpRollbackFaultTests(unittest.TestCase):
    def test_snapshot_loss_leaves_applied_bytes_and_other_snapshots(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_bytes(b'candidate')
            executor = HttpExecutor(SimpleNamespace(frontend='front', backend='back', config_path=path))
            request = ToolRequest('config_patch', {'host': 'local', 'resource': 'nginx-main'})
            executor._config_snapshots[request.request_id] = b'original'
            executor._config_snapshots['other-request'] = b'other'
            executor.lose_rollback_snapshot = True
            with patch.object(executor, '_restore_config', side_effect=AssertionError('snapshot unavailable')):
                result = executor.rollback(request, ExecutionResult(True, 'EXECUTED'))
            self.assertFalse(result.ok)
            self.assertEqual(result.code, 'ROLLBACK_UNAVAILABLE')
            self.assertEqual(path.read_bytes(), b'candidate')
            self.assertEqual(executor._config_snapshots, {'other-request': b'other'})

    def test_invalid_fault_plan_rejected_before_fixture_setup(self):
        plan = {'deadline_seconds': 1, 'conditions': {'B2': {}},
                'fixture_rollback_snapshot_loss': True}
        with patch('evaluation.http_trials.HttpFixture', side_effect=AssertionError('no setup')):
            with self.assertRaises(ValueError):
                run_http_trial(HttpCase('invalid_config'), 'B2', None, plan, 'unused', 'unused', 'unused')

    def test_default_delegates_normal_rollback(self):
        executor = HttpExecutor(SimpleNamespace(frontend='front', backend='back', config_path=None))
        request = ToolRequest('config_patch', {})
        expected = ExecutionResult(True, 'ROLLED_BACK')
        with patch('evaluation.docker_fixtures.DockerFixtureExecutor.rollback', return_value=expected) as rollback:
            self.assertIs(executor.rollback(request, ExecutionResult(True, 'EXECUTED')), expected)
            rollback.assert_called_once()
