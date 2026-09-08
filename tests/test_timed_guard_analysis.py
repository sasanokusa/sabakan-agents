import json
from pathlib import Path
import unittest
from scripts.analyze_timed_guard import analyze, observed_ready


class TimedGuardAnalysisTests(unittest.TestCase):
    def ready(self):
        return {'role': 'tool', 'name': 'service_status', 'content': json.dumps(
            {'ok': True, 'data': {'http_ok': True, 'http_status': 200}})}

    def test_final_http_alone_does_not_prove_actor_observation(self):
        trial = {'public_inputs': [[]], 'model_responses': [{}],
                 'final_state': {'http': {'ok': True}}}
        self.assertFalse(observed_ready(trial))
        trial['public_inputs'][0].append(self.ready())
        self.assertTrue(observed_ready(trial))

    def test_prepared_input_and_partial_trace_remain_unknown(self):
        self.assertIsNone(observed_ready({'public_inputs': [[self.ready()]], 'model_responses': []}))
        self.assertIsNone(observed_ready({'public_inputs': [[]], 'model_responses': [{}],
                                         'loop': {'trace_complete': False}}))
        self.assertIsNone(observed_ready({}))

    def test_equal_count_wrong_rows_suppress_pairs(self):
        plan = json.loads(Path('evaluation/protocols/http-timed-guard-dev-20260908.json').read_text())
        report = {'protocol': plan['protocol'], 'plan': plan, 'status': 'completed',
                  'trials': [dict(row) for row in plan['matrix']]}
        self.assertTrue(analyze(report)['matrix_complete'])
        report['trials'][-1] = dict(report['trials'][0])
        result = analyze(report)
        self.assertFalse(result['matrix_complete'])
        self.assertEqual(result['pairs'], [])

    def test_running_report_rejected(self):
        with self.assertRaises(ValueError):
            analyze({'protocol': 'sabakan-http-timed-guard-development-v1', 'status': 'running'})
