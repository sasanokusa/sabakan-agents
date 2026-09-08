import unittest
from evaluation.agent_loop import OBSERVATION_HINT, tool_schemas_for_state
from evaluation.mechanism_audit import audit_surface


class MechanismAuditTests(unittest.TestCase):
    def request(self, state, messages):
        return {'request': {'messages': messages, 'tools': list(tool_schemas_for_state(state))}}

    def test_stage_transition_requires_delivered_successful_read(self):
        messages = [{'role': 'tool', 'content': '{"code":"READ_OK"}'}]
        trial = {'http_requests': [self.request('observe', []), self.request('remediation', messages)]}
        options = {'staged_tools': True, 'observation_hints': True}
        self.assertEqual(audit_surface(trial, options)['schema_mismatches'], 0)
        messages[0]['content'] = '{"code":"RESOURCE_NOT_ALLOWED"}'
        self.assertEqual(audit_surface(trial, options)['schema_mismatches'], 1)

    def test_disabled_hint_and_exposure_checked_from_payload(self):
        trial = {'http_requests': [self.request('observe', [{'role': 'system', 'content': OBSERVATION_HINT}])]}
        result = audit_surface(trial, {'staged_tools': False, 'observation_hints': False})
        self.assertEqual(result['forbidden_hint_requests'], 1)
        self.assertEqual(result['schema_mismatches'], 1)

    def test_unrecorded_surface_is_unknown(self):
        result = audit_surface({}, {'staged_tools': True, 'observation_hints': True})
        self.assertFalse(result['measured'])
        self.assertIsNone(result['schema_mismatches'])
