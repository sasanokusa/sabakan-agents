from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from evaluation.approval_scenarios import FixtureApprovalScenario
from sabakan_broker.models import ApprovalRequest


class ApprovalScenarioTests(unittest.TestCase):
    def request(self):
        return ApprovalRequest('request', 'docker-fixture', 'local', 'config_patch', 'nginx-main',
                               'before', 'patch', 'operation', datetime.now(timezone.utc) + timedelta(seconds=60),
                               'private-nonce', 'approval')

    def test_refusal_states_remain_distinct_without_signing(self):
        for state in ('deny', 'pending', 'unanswered'):
            scenario = FixtureApprovalScenario(state)
            with patch('evaluation.approval_scenarios.trusted_fixture_approval_handler') as signer:
                self.assertIsNone(scenario(self.request()))
                signer.assert_not_called()
            self.assertEqual(scenario.events[0]['state'], state)
            self.assertNotIn('private-nonce', str(scenario.events))

    def test_expiry_and_trusted_state_change_are_explicit(self):
        expired = FixtureApprovalScenario('expired')
        self.assertLess(expired(self.request()).expires_at, datetime.now(timezone.utc))
        changes = []
        scenario = FixtureApprovalScenario('state_changed', change_state=lambda: changes.append(True))
        approval = scenario(self.request())
        self.assertEqual(changes, [True])
        self.assertEqual(approval.before_hash, 'before')
        self.assertNotIn(approval.signature, str(scenario.events))
        self.assertTrue(scenario.events[0]['trusted_state_change_completed'])
