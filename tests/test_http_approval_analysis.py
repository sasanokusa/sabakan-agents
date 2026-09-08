import json
from pathlib import Path
import unittest
from scripts.analyze_http_approval import analyze


class HttpApprovalAnalysisTests(unittest.TestCase):
    def report(self):
        plan = json.loads(Path('evaluation/protocols/http-approval-comparison-dev-20260908.json').read_text())
        return {'protocol': plan['protocol'], 'plan': plan, 'status': 'completed',
                'trials': [{**row, 'started': True, 'loop': {}} for row in plan['matrix']]}

    def test_unknown_unreached_and_arrived_remain_distinct(self):
        report = self.report()
        report['trials'][1]['loop']['approval_required_count'] = 0
        report['trials'][2]['approval_scenario_events'] = [{'state': 'allow', 'decision_returned': True}]
        rows = analyze(report)['rows']
        self.assertIsNone(rows[0]['approval_reached'])
        self.assertFalse(rows[1]['approval_reached'])
        self.assertTrue(rows[2]['approval_reached'])
        self.assertIsNone(rows[0]['mutations'])

    def test_equal_count_with_wrong_condition_is_not_complete(self):
        report = self.report()
        self.assertTrue(analyze(report)['matrix_complete'])
        report['trials'][-1] = dict(report['trials'][0])
        result = analyze(report)
        self.assertFalse(result['matrix_complete'])
        self.assertEqual(len(result['missing']), 1)
        self.assertEqual(len(result['extra']), 1)

    def test_running_report_rejected(self):
        report = self.report()
        report['status'] = 'running'
        with self.assertRaises(ValueError):
            analyze(report)
