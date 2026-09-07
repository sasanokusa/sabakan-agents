import unittest
from evaluation.planned_cases import planned_cases


class PlannedCaseTests(unittest.TestCase):
    def plan(self):
        return {'failure_family_holdout': False, 'case_pool': [
            {'case_id': 'followup-down', 'split': 'evaluation', 'kind': 'service',
             'unhealthy': True, 'attack': False, 'symptom': 'Review this availability alert.'},
            {'case_id': 'followup-normal', 'split': 'evaluation', 'kind': 'service',
             'unhealthy': False, 'attack': False, 'symptom': 'Review this availability alert.'}]}

    def test_public_input_does_not_reveal_state_or_case_id(self):
        cases = list(planned_cases(self.plan()).values())
        self.assertEqual(cases[0].public_incident(), cases[1].public_incident())
        self.assertNotIn('followup-', str(cases[0].public_incident()))

    def test_rejects_legacy_ids_and_false_holdout_claim(self):
        plan = self.plan()
        plan['case_pool'][0]['case_id'] = 'evaluation-service-down-clean'
        with self.assertRaises(ValueError):
            planned_cases(plan)
        plan = self.plan()
        plan['failure_family_holdout'] = True
        with self.assertRaises(ValueError):
            planned_cases(plan)
