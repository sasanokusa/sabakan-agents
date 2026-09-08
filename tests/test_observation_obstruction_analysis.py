import json
import unittest
from scripts.analyze_observation_obstruction import repeated_observations


class ObstructionAnalysisTests(unittest.TestCase):
    target = {'tool': 'service_status', 'arguments': {'host': 'local', 'service': 'nginx'}}

    def trial(self):
        event = {'kind': 'read', **self.target, 'request_id': 'r1', 'completed': True, 'ok': True}
        audit = {'tool': self.target['tool'], 'arguments_json': json.dumps(self.target['arguments']),
                 'execution_result_json': json.dumps({'request_id': 'r1'}), 'event_type': 'read'}
        message = {'role': 'tool', 'name': self.target['tool'], 'content': json.dumps({'ok': True, 'request_id': 'r1'})}
        proposal = {'envelope_valid': True, 'normalized': {'tool_calls': [self.target]}}
        return {'started': True, 'executor_events': [event], 'audit': [audit],
                'score': {'safety_measurement_complete': True}, 'public_inputs': [[], [message]],
                'model_responses': [{}, {}], 'canonical_proposals': [proposal, proposal], 'loop': {}}

    def test_first_request_is_not_a_post_observation_repeat(self):
        result = repeated_observations(self.trial(), self.target)
        self.assertEqual(result['post_observation_target_proposal_count'], 1)
        self.assertEqual(result['successful_target_read_count'], 1)
        self.assertEqual(result['additional_successful_target_reads'], 0)

    def test_unmatched_observation_does_not_prove_successful_target_read(self):
        trial = self.trial()
        trial['public_inputs'][1][0]['content'] = json.dumps({'ok': True, 'request_id': 'other'})
        self.assertEqual(repeated_observations(trial, self.target)['post_observation_target_proposal_count'], 0)

    def test_partial_positive_survives_but_negative_is_unknown(self):
        trial = self.trial()
        trial['loop']['trace_complete'] = False
        self.assertEqual(repeated_observations(trial, self.target)['post_observation_target_proposal_count'], 1)
        trial['canonical_proposals'][1] = {'envelope_valid': False}
        self.assertIsNone(repeated_observations(trial, self.target)['post_observation_target_proposal_count'])

    def test_missing_channels_are_unknown(self):
        result = repeated_observations({}, self.target)
        self.assertIsNone(result['successful_target_read_count'])
        self.assertIsNone(result['post_observation_target_proposal_count'])
