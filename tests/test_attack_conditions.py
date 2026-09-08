import unittest
from evaluation.attack_conditions import availability_executor, preserve_legacy_goal_scope
from evaluation.research_cases import research_cases


class AttackConditionTests(unittest.TestCase):
    def test_explicit_attack_and_clean_executor_selection(self):
        cases = {c.case_id: c for c in research_cases('development')}
        attacked = next(c for c in cases.values() if c.attack)
        clean = next(c for c in cases.values() if not c.attack)
        plan = {'attack_notices': {attacked.case_id: 'fixed attack'}}
        for case in (attacked, clean):
            factory = availability_executor(plan, {'case_id': case.case_id, 'observation': 'informative'}, cases)
            self.assertEqual(factory(case, 'unused').notice, 'fixed attack' if case.attack else None)

    def test_missing_notice_and_clean_injection_rejected(self):
        cases = {c.case_id: c for c in research_cases('development')}
        for case in cases.values():
            plan = {'attack_notices': {} if case.attack else {case.case_id: 'attack'}}
            with self.assertRaises(ValueError):
                availability_executor(plan, {'case_id': case.case_id, 'observation': 'informative'}, cases)

    def test_old_goal_metrics_are_preserved_but_not_custom_labels(self):
        record = {'attack_goal_proposed': False, 'score': {'operational_harm_count': 1}}
        preserve_legacy_goal_scope(record)
        self.assertNotIn('attack_goal_proposed', record)
        self.assertEqual(record['legacy_system_reboot_goal_metrics'], {'attack_goal_proposed': False})
        self.assertFalse(record['custom_attack_goal_measured'])
        self.assertEqual(record['score']['operational_harm_count'], 1)
