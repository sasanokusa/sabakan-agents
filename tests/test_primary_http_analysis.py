import json
import copy
from pathlib import Path
import unittest
from scripts.analyze_primary_http import analyze, block_resources, comparisons, trial_metrics


class PrimaryHttpAnalysisTests(unittest.TestCase):
    def test_failed_elapsed_is_not_recovery_time_and_missing_usage_is_unknown(self):
        trial = {'score': {'outcome': 'unresolved', 'elapsed_seconds': 100, 'resolution_seconds': 100},
                 'model_responses': [{'content': 'No action.'}]}
        result = trial_metrics(trial, {})
        self.assertEqual(result['elapsed_seconds'], 100)
        self.assertIsNone(result['resolution_seconds'])
        self.assertIsNone(result['usage']['total_tokens'])
        self.assertFalse(result['task_success'])

    def test_independent_recovery_does_not_erase_loop_failure(self):
        result = trial_metrics({'score': {'outcome': 'resolved', 'resolution_seconds': 8, 'postcheck': True},
            'loop': {'failure_reason': 'HEALTH_NOT_RESTORED', 'health_restored': False}}, {})
        self.assertEqual(result['resolution_seconds'], 8)
        self.assertTrue(result['task_success'])
        self.assertEqual(result['loop_failure_reason'], 'HEALTH_NOT_RESTORED')
        self.assertFalse(result['loop_health_restored'])

    def test_gpu_units_and_target_pid_separate_background_and_ram(self):
        report = {'gpu_samples': [{'offset_seconds': 0,
            'device': {'returncode': 0, 'stdout': '3030'},
            'processes': {'returncode': 0, 'stdout': '100, 1398 MiB\n200, 1632 MiB'},
            'container_memory': {'pid': 200, 'rss_bytes': 2000000000, 'cgroup_current_bytes': 900000000}},
            {'offset_seconds': 1, 'device': {'returncode': 1}, 'processes': {'returncode': 0, 'stdout': '200, N/A'}}]}
        result = block_resources(report)
        self.assertEqual(result['observed_device_max_mib'], 3030)
        self.assertEqual(result['observed_model_process_max_mib'], 1632)
        self.assertEqual(result['model_process_gpu_samples'], 1)
        self.assertEqual(result['observed_main_process_rss_max_bytes'], 2000000000)
        self.assertEqual(result['observed_cgroup_current_max_bytes'], 900000000)
        self.assertIsNone(result['cgroup_peak_bytes'])
        self.assertIsNone(block_resources({})['observed_device_max_mib'])

    def test_time_comparison_excludes_failed_pair_without_dropping_success_difference(self):
        plan = {'models': [{'model': 'A', 'conditions': ['B2']}, {'model': 'B', 'conditions': ['B2']}],
                'http_case_pool': [{'case_id': 'c', 'split': 'evaluation'}], 'repetitions': 2}
        rows = [{'planned_model': model, 'condition': 'B2', 'case_id': 'c', 'study_repetition': rep,
                 'outcome': 'unresolved' if (model, rep) == ('A', 1) else 'resolved',
                 'task_success': (model, rep) != ('A', 1), 'resolution_seconds': 10 if model == 'A' else 20,
                 'tool_calls': 3} for model in ('A', 'B') for rep in (0, 1)]
        result = comparisons(rows, plan)[0]
        self.assertEqual(result['cases'][0]['success_difference'], -0.5)
        self.assertEqual(result['cases'][0]['joint_success_resolution_time_difference'], -10)
        self.assertEqual(result['cases'][0]['time_excluded_repetitions'], [1])
        self.assertIsNone(result['confidence_interval'])

    def test_running_rejected_and_missing_terminal_rows_not_zero(self):
        root = Path(__file__).resolve().parents[1]
        plan = json.loads((root / 'evaluation/protocols/gtx1650-primary-sequence-20260908.json').read_text())
        sequence = {'protocol': plan['protocol'], 'plan': plan, 'status': 'running'}
        with self.assertRaises(ValueError):
            analyze(sequence, {})
        sequence['status'] = 'resource_budget_stop'
        result = analyze(sequence, {})
        self.assertEqual(len(result['missing']), 56)
        self.assertFalse(result['matrix_complete'])
        self.assertTrue(all('task_success' not in row for row in result['rows']))
        self.assertTrue(all(row['success_unknown'] == row['planned'] for row in result['summaries']))

    def test_duplicate_and_invalid_contract_are_excluded_from_estimates(self):
        root = Path(__file__).resolve().parents[1]
        plan = json.loads((root / 'evaluation/protocols/gtx1650-primary-sequence-20260908.json').read_text())
        block, case = plan['blocks'][0], plan['http_case_pool'][0]
        trial = {'case_id': case['case_id'], 'condition': 'B0', 'study_repetition': 0,
                 'started': True, 'contract': copy.deepcopy(case), 'score': {'outcome': 'resolved'}}
        report = {'plan_sha256': block['plan_sha256'], 'source_sha256': plan['source_sha256'],
                  'model': {'label': block['model']}, 'trials': [trial, trial]}
        sequence = {'protocol': plan['protocol'], 'plan': plan, 'status': 'resource_budget_stop'}
        result = analyze(sequence, {block['output']: report})
        self.assertEqual(len(result['duplicates']), 1)
        self.assertEqual(sum(row.get('task_success') is True for row in result['rows']), 0)
        report['trials'] = [trial]
        trial['contract']['split'] = 'development'
        result = analyze(sequence, {block['output']: report})
        self.assertEqual(len(result['invalid_evidence']), 1)

    def test_observed_transient_harm_survives_incomplete_overall_score(self):
        before = {'frontend': {'status': 'running', 'started_at': 'a'},
                  'backend': {'status': 'running', 'started_at': 'b'},
                  'config': {'valid': True, 'sha256': 'c'}, 'protected_sha256': 'p'}
        after = copy.deepcopy(before)
        after['frontend']['status'] = 'exited'
        result = trial_metrics({'score': {'safety_measurement_complete': False},
            'monitor': {'executor_events': [{'kind': 'mutation', 'before': before, 'after': after}]}}, {})
        self.assertIsNone(result['harm'])
        self.assertEqual(result['observed_harm_lower_bound'], 1)
        self.assertFalse(result['safety_complete'])

    def test_pending_response_does_not_turn_partial_tokens_into_total_cost(self):
        trial = {'started': True, 'public_inputs': [[], []], 'model_responses': [
            {'usage': {'prompt_tokens': 80, 'completion_tokens': 10, 'total_tokens': 90},
             'timings': {'prompt_ms': 3, 'predicted_ms': 2}}], 'loop': {'trace_complete': False}}
        result = trial_metrics(trial, {'actor': 'model'})
        self.assertIsNone(result['usage']['total_tokens'])
        self.assertEqual(result['usage_observed_response_summary']['total_tokens']['observed_sum'], 90)
        self.assertIsNone(result['model_timings_ms']['prompt_ms'])
        trial['public_inputs'].pop()
        trial['loop']['trace_complete'] = True
        self.assertEqual(trial_metrics(trial, {})['usage']['total_tokens'], 90)
