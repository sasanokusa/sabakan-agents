import json
from pathlib import Path
import unittest
from unittest.mock import patch

from evaluation.diagnostic_observations import InformativeExecutor
from evaluation.research_cases import ResearchCase, MonitoredExecutor
from sabakan_broker.models import ExecutionResult, ToolRequest


class DiagnosticObservationTests(unittest.TestCase):
    def test_summary_uses_current_state_not_fixture_truth(self):
        case = ResearchCase('hidden-case', 'development', 'service', True, False)
        executor = InformativeExecutor(case, 'disposable')
        request = ToolRequest('host_status', {'host': 'local'})
        with patch.object(MonitoredExecutor, 'execute_read', return_value=ExecutionResult(True, 'READ_OK', {})), patch(
                'evaluation.diagnostic_observations.snapshot', return_value={'status': 'running'}):
            result = executor.execute_read(request)
        self.assertEqual(result.data['observed_target']['status'], 'running')
        self.assertNotIn('hidden-case', json.dumps(result.data))
        self.assertNotIn('restart', json.dumps(result.data))

    def test_status_payload_and_other_synthetic_tools_are_unchanged(self):
        executor = InformativeExecutor(ResearchCase('hidden', 'development', 'service', True, False), 'unused')
        for tool in ('service_status', 'disk_status'):
            original = ExecutionResult(True, 'READ_OK', {'status': 'original'})
            with patch.object(MonitoredExecutor, 'execute_read', return_value=original), patch(
                    'evaluation.diagnostic_observations.snapshot') as snapshot:
                self.assertIs(executor.execute_read(ToolRequest(tool, {'host': 'local'})), original)
                snapshot.assert_not_called()

    def test_protocol_is_paired_development_only(self):
        path = Path(__file__).resolve().parents[1] / 'evaluation/protocols/lfm-observation-dev-20260907.json'
        plan = json.loads(path.read_text())
        rows = plan['matrix']
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({(r['case_id'], r['observation']) for r in rows}), 8)
        for case in {r['case_id'] for r in rows}:
            self.assertTrue(case.startswith('development-'))
            self.assertEqual({r['observation'] for r in rows if r['case_id'] == case}, {'baseline', 'informative'})
