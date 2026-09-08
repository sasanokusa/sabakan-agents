import json
from pathlib import Path
import unittest
from scripts.analyze_availability_followup import analyze, paired, safety_summary


class FollowupAnalysisTests(unittest.TestCase):
    def test_replication_identity_survives_analysis(self):
        report = self.report()
        report['plan'].update(study_id='replication', split='replication_known_cases',
                              scope='known cases', replication_disclosure={'prior_saved': 19})
        result = analyze(report)
        self.assertEqual(result['study_id'], 'replication')
        self.assertEqual(result['study_split'], 'replication_known_cases')
        self.assertEqual(result['replication_disclosure'], {'prior_saved': 19})
        self.assertIsNone(result['plan_sha256'])

    def test_safety_unknown_keeps_started_denominator(self):
        trials = [{'started': True, 'score': {'requires_remediation': True,
                   'constraint_compliant_resolution': False, 'safety_measurement_complete': False},
                   'loop': {'failure_reason': 'OUTER_TIMEOUT'}},
                  {'started': False, 'error': 'RUNTIME_UNAVAILABLE'}]
        result = safety_summary(trials)
        self.assertEqual(result['constraint_compliant_resolution'],
                         {'numerator': 0, 'denominator': 1, 'safety_unknown': 1})
        self.assertEqual(result['stop_reasons'], {'OUTER_TIMEOUT': 1})
        self.assertEqual(result['setup_errors'], {'RUNTIME_UNAVAILABLE': 1})

    def test_duplicate_matrix_suppresses_paired_estimates(self):
        report = self.report()
        self.assertTrue(analyze(report)['matrix_complete'])
        report['trials'].append(report['trials'][0])
        result = analyze(report)
        self.assertFalse(result['matrix_complete'])
        self.assertEqual(result['comparisons'], {})

    def report(self):
        plan = json.loads(Path('evaluation/protocols/availability-ablation-followup-20260908.json').read_text())
        states = {c['case_id']: c['unhealthy'] for c in plan['case_pool']}
        trials = []
        for row in plan['matrix']:
            remediation = states[row['case_id']]
            success = row['condition'] == 'B2'
            score = {'started': True, 'requires_remediation': remediation,
                     'outcome': ('resolved' if remediation else 'appropriate_non_intervention') if success else 'unresolved',
                     'safety_measurement_complete': True, 'necessary_observation_completed': True,
                     'executed_mutation_count': 0, 'operational_harm_count': 0,
                     'boundary_violation_count': 0, 'normal_completion': True}
            trials.append({**row, 'started': True, 'score': score})
        return {'protocol': plan['protocol'], 'plan': plan, 'status': 'completed', 'trials': trials}

    def test_repetitions_do_not_inflate_case_or_family_count(self):
        result = paired(self.report(), 'B1', 'resolution')
        self.assertEqual(result['paired_case_count'], 2)
        self.assertEqual(result['family_count'], 2)
        self.assertEqual(result['mean_difference'], 1)
        self.assertTrue(result['degenerate_interval'])

    def test_missing_repetition_excludes_case_without_zero_imputation(self):
        report = self.report()
        report['trials'] = [t for t in report['trials'] if not (
            t['condition'] == 'B1' and t['case_id'] == 'followup-availability-service-down' and t['repetition'] == 1)]
        result = paired(report, 'B1', 'resolution')
        self.assertEqual(result['paired_case_count'], 1)
        self.assertEqual(len(result['missing_pairs']), 1)

    def test_running_report_rejected(self):
        report = self.report()
        report['status'] = 'running'
        with self.assertRaises(ValueError):
            analyze(report)

    def test_unknown_harm_not_zero(self):
        report = self.report()
        for trial in report['trials']:
            trial['score']['operational_harm_count'] = None
        result = paired(report, 'B1', 'operational_harm')
        self.assertIsNone(result['mean_difference'])
        self.assertEqual(result['paired_case_count'], 0)
