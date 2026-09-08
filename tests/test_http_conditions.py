import unittest
from evaluation.http_conditions import http_condition


class HttpConditionTests(unittest.TestCase):
    def test_guard_overrides_preserve_outer_limits(self):
        plan = {'deadline_seconds': 300, 'conditions': {'delayed': {
            'identical_repeat_limit': 4, 'external_recovery_delay_seconds': 90, 'deadline_seconds': 999}}}
        _, selected = http_condition(plan, 'delayed')
        self.assertEqual(selected['identical_repeat_limit'], 4)
        self.assertEqual(selected['external_recovery_delay_seconds'], 90)
        self.assertEqual(selected['deadline_seconds'], 300)
        self.assertNotIn('identical_repeat_limit', plan)

    def test_invalid_guard_parameters_rejected(self):
        for options in ({'identical_repeat_limit': True}, {'identical_repeat_limit': 0},
                        {'external_recovery_delay_seconds': float('nan')},
                        {'external_recovery_delay_seconds': -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                http_condition({'conditions': {'B2': options}}, 'B2')

    def test_actor_and_approval_only_override(self):
        plan = {'generation': {'max_tokens': 1024}, 'deadline_seconds': 300,
                'approval_mode': 'fixture_auto_signature', 'conditions': {
                    'denied': {'actor': 'playbook', 'approval_scenario': 'deny', 'deadline_seconds': 1}}}
        actor, selected = http_condition(plan, 'denied')
        self.assertEqual(actor, 'playbook')
        self.assertEqual(selected['approval_scenario'], 'deny')
        self.assertEqual(selected['deadline_seconds'], 300)
        self.assertEqual(selected['generation'], plan['generation'])
        self.assertNotIn('approval_scenario', plan)

    def test_invalid_mode_and_scenario_rejected(self):
        for options in ({'actor': 'other'}, {'approval_mode': 'human'},
                        {'approval_mode': 'unassisted', 'approval_scenario': 'allow'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                http_condition({'conditions': {'B2': options}}, 'B2')
