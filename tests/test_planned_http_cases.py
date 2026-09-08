import unittest
from evaluation.http_case_pool import http_cases


class PlannedHttpCasesTests(unittest.TestCase):
    def plan(self):
        return {'failure_family_holdout': False, 'http_case_pool': [
            {'fault': 'dependency_down+frontend_down', 'case_id': 'primary-http-pair-01',
             'split': 'evaluation', 'symptom': 'Investigate the service availability alert.',
             'prior_exposure': 'unexecuted_combination_at_freeze'},
            {'fault': 'healthy', 'case_id': 'primary-http-normal-reference',
             'split': 'reference', 'symptom': 'Investigate the service availability alert.',
             'prior_exposure': 'previously_used_control'}]}

    def test_public_input_does_not_reveal_fault_or_split(self):
        cases = list(http_cases(self.plan()).values())
        self.assertEqual(cases[0].public_incident(), cases[1].public_incident())
        self.assertEqual(cases[0].faults, {'dependency_down', 'frontend_down'})
        self.assertEqual(cases[0].contract()['split'], 'evaluation')
        self.assertEqual(cases[1].contract()['split'], 'reference')
        self.assertEqual(cases[0].contract()['case_id'], 'primary-http-pair-01')

    def test_known_single_fault_cannot_be_relabeled_unused(self):
        plan = self.plan()
        plan['http_case_pool'][0]['fault'] = 'frontend_down'
        with self.assertRaises(ValueError):
            http_cases(plan)

    def test_holdout_duplicate_and_mixed_pool_rejected(self):
        for modification in ('holdout', 'duplicate', 'mixed'):
            plan = self.plan()
            if modification == 'holdout':
                plan['failure_family_holdout'] = True
            elif modification == 'duplicate':
                plan['http_case_pool'].append(plan['http_case_pool'][0])
            else:
                plan['compound_http_faults'] = []
            with self.subTest(modification=modification), self.assertRaises(ValueError):
                http_cases(plan)
