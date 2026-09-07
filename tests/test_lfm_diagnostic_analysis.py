import unittest

from scripts.analyze_lfm_observations import analyze, raw_tool_names, summarize_trial


class DiagnosticAnalysisTests(unittest.TestCase):
    def test_raw_canonical_mismatch_and_terminal_handoff_are_visible(self):
        trial = {'case_id': 'development-test', 'observation': 'baseline',
                 'http_requests': [{'response': {'choices': [{'message': {'tool_calls': [
                     {'function': {'name': 'service_status', 'arguments': '{"host":"local"}'}}]}}]}}],
                 'loop': {'turns': [
                     {'turn': 1, 'canonical_proposal': {'normalized': {'tool_calls': [
                         {'tool': 'docker_status', 'arguments': {'host': 'local'}}]}}},
                     {'turn': 1, 'tool_results': [{'result': {'request_id': 'terminal'}}]},
                 ]}}
        row = summarize_trial(trial)
        self.assertEqual(row['raw_canonical_matches'], [False])
        self.assertEqual(row['tool_result_handoffs'], {'terminal_not_forwarded': 1})

    def test_duplicate_cannot_hide_missing_condition(self):
        baseline = {'case_id': 'development-test', 'observation': 'baseline'}
        informative = {**baseline, 'observation': 'informative'}
        report = {'protocol': 'dev', 'status': 'completed',
                  'plan': {'matrix': [baseline, informative]}, 'trials': [baseline, baseline]}
        result = analyze(report)
        self.assertFalse(result['matrix_complete'])
        self.assertEqual(result['missing_rows'], [('development-test', 'informative')])
        report['status'] = 'running'
        with self.assertRaises(ValueError):
            analyze(report)

    def test_undelivered_auxiliary_read_does_not_establish_intervention(self):
        trial = {'case_id': 'development-test', 'observation': 'informative',
                 'executor_events': [{'kind': 'read', 'tool': 'service_list', 'ok': True, 'request_id': 'r'}]}
        row = summarize_trial(trial)
        self.assertEqual(row['auxiliary_successful_reads'], 1)
        self.assertEqual(row['auxiliary_results_delivered'], 0)
        self.assertIsNone(row['total_tokens'])
        trial['public_inputs'] = [[{'role': 'tool', 'content': '{"request_id":"r"}'}]]
        self.assertEqual(summarize_trial(trial)['auxiliary_results_delivered'], 1)

    def test_missing_response_is_not_an_empty_tool_response(self):
        self.assertIsNone(raw_tool_names({'error': 'timeout'}))
        self.assertEqual(raw_tool_names({'response': {'choices': [{'message': {'content': 'Done', 'tool_calls': None}}]}}), [])
