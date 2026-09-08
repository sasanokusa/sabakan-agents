import copy
import json
from pathlib import Path
import unittest
from scripts.analyze_http_partial import analyze, file_evidence

ROOT = Path(__file__).resolve().parents[1]


class HttpPartialAnalysisTests(unittest.TestCase):
    def test_restored_invalid_config_does_not_imply_recovery(self):
        before = {'sha256':'original', 'valid':False}
        prefix = {'sha256':'partial', 'valid':False}
        trial = {'initial_state':{'config':before}, 'final_state':{'config':before},
            'partial_write':{'write_events':[
                {'phase':'candidate_partial_write', 'before':before,'after':prefix,'bytes_written':10},
                {'phase':'rollback_write','before':prefix,'after':before}]}}
        result = file_evidence(trial, 'partial_restore')
        self.assertTrue(result['injection_reached'])
        self.assertTrue(result['immediate_restoration'][0]['original_bytes_restored_immediately'])
        self.assertFalse(result['final_config_valid'])
        self.assertNotIn('task_success', result)

    def test_failed_restore_and_later_valid_write_remain_separate(self):
        before = {'sha256':'original','valid':False}
        prefix = {'sha256':'partial','valid':False}
        valid = {'sha256':'valid','valid':True}
        trial = {'initial_state':{'config':before},'final_state':{'config':valid},
            'partial_write':{'write_events':[
                {'phase':'candidate_partial_write','before':before,'after':prefix,'bytes_written':10},
                {'phase':'rollback_write_rejected','before':prefix,'after':prefix,'bytes_written':0},
                {'phase':'rollback_write','before':prefix,'after':valid,'bytes_written':20}]}}
        result = file_evidence(trial, 'partial_restore_failed')
        self.assertFalse(result['immediate_restoration'][0]['original_bytes_restored_immediately'])
        self.assertTrue(result['immediate_restoration'][0]['restore_write_rejected'])
        self.assertTrue(result['final_config_valid'])
        self.assertEqual(len(result['later_write_events']), 1)

    def test_partial_positive_missing_restore_and_absent_instrumentation(self):
        result = file_evidence({'partial_write':{'write_events':[{'phase':'candidate_partial_write'}]}}, 'partial_restore')
        self.assertTrue(result['injection_reached'])
        self.assertIsNone(result['immediate_restoration'][0]['original_bytes_restored_immediately'])
        self.assertIsNone(file_evidence({}, 'partial_restore')['injection_reached'])
        self.assertIsNone(file_evidence({}, None)['final_residual_config_change'])

    def test_terminal_matrix_retains_missing_and_duplicate_slots(self):
        plan = json.loads((ROOT/'evaluation/protocols/http-partial-write-dev-20260908.json').read_text())
        report = {'protocol':plan['protocol'],'plan':plan,'status':'running','trials':[]}
        with self.assertRaises(ValueError):
            analyze(report)
        report['status']='runtime_error'
        result = analyze(report)
        self.assertEqual(len(result['rows']),12)
        self.assertEqual(len(result['missing']),12)
        self.assertEqual(len(result['paired']),8)
        self.assertTrue(all(p['elapsed_seconds_fault_minus_clean'] is None for p in result['paired']))
        row = copy.deepcopy(plan['matrix'][0])
        report['trials']=[row,copy.deepcopy(row)]
        result=analyze(report)
        self.assertEqual(result['rows'][0]['measurement'],'duplicate')
        self.assertNotIn('task_success',result['rows'][0])


if __name__ == '__main__':
    unittest.main()
