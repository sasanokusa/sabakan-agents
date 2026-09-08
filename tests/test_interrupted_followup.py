import hashlib
import json
import unittest
from tests import test_availability_followup_analysis as fixtures
from scripts.analyze_interrupted_followup import analyze_interrupted


class InterruptedFollowupTests(unittest.TestCase):
    def data(self):
        report = fixtures.FollowupAnalysisTests().report()
        report['trials'] = report['trials'][:19]
        report['status'] = 'running'
        raw = json.dumps(report).encode()
        evidence = {'raw_report_sha256': hashlib.sha256(raw).hexdigest(),
                    'saved_trials': 19, 'remaining_planned_rows': report['plan']['matrix'][19:],
                    'current_row_start_status': 'unknown', 'cleanup': {}}
        return raw, evidence

    def test_missing_cells_remain_missing_and_no_partial_repetition_estimate(self):
        raw, evidence = self.data()
        result = analyze_interrupted(raw, evidence)
        self.assertEqual(result['unsaved_cell_count'], 21)
        self.assertFalse(result['matrix_complete'])
        self.assertEqual(result['original_status'], 'running')
        self.assertEqual(result['comparisons']['B1']['resolution']['paired_case_count'], 0)
        self.assertEqual(json.loads(raw)['status'], 'running')

    def test_mismatched_evidence_rejected(self):
        raw, evidence = self.data()
        evidence['raw_report_sha256'] = 'wrong'
        with self.assertRaises(ValueError):
            analyze_interrupted(raw, evidence)
        raw, evidence = self.data()
        evidence['remaining_planned_rows'] = []
        with self.assertRaises(ValueError):
            analyze_interrupted(raw, evidence)
