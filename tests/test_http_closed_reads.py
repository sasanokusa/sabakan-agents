from types import SimpleNamespace
import unittest
from unittest.mock import patch
from evaluation.http_fixtures import HttpCase, HttpExecutor, HttpClosedReadMonitor

from sabakan_broker.models import ExecutionResult, ToolRequest


class HttpClosedReadTests(unittest.TestCase):
    def executor(self):
        return HttpExecutor(SimpleNamespace(frontend='front', backend='back', config_path=None))

    def test_closed_branch_never_reads_and_preserves_prior_gap(self):
        executor = self.executor()
        monitor = HttpClosedReadMonitor(executor, HttpCase('healthy'))
        request = ToolRequest('disk_status', {'host': 'local'})
        with patch('evaluation.docker_fixtures.DockerFixtureExecutor.execute_read', side_effect=AssertionError('unexpected I/O')):
            result = monitor.execute_read(request)
        self.assertFalse(result.ok)
        self.assertFalse(monitor.incomplete)
        self.assertTrue(monitor.events[-1]['fixed_no_io_rejection'])
        monitor.incomplete = True
        monitor.execute_read(request)
        self.assertTrue(monitor.incomplete)

    def test_supported_read_failure_remains_incomplete(self):
        monitor = HttpClosedReadMonitor(self.executor(), HttpCase('healthy'))
        with patch('evaluation.docker_fixtures.DockerFixtureExecutor.execute_read', return_value=ExecutionResult(False, 'READ_ERROR')):
            monitor.execute_read(ToolRequest('service_status', {'host': 'local', 'service': 'nginx'}))
        self.assertTrue(monitor.incomplete)
        self.assertNotIn('fixed_no_io_rejection', monitor.events[-1])
