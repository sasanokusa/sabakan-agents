import unittest
from unittest.mock import patch
from evaluation.attack_observations import AttackObservationExecutor
from evaluation.research_cases import research_cases
from evaluation.research_protocol import TrialEvidence
from sabakan_broker.models import ExecutionResult, ToolRequest


class AttackObservationTests(unittest.TestCase):
    def test_notice_preserves_evidence_and_original_result(self):
        case = next(c for c in research_cases('development') if c.attack)
        executor = AttackObservationExecutor(case, 'unused', notice='fixed attack text')
        original = ExecutionResult(True, 'READ_OK', {'status': 'running'})
        with patch('evaluation.diagnostic_observations.InformativeExecutor.execute_read', return_value=original):
            result = executor.execute_read(ToolRequest('service_status', case.arguments))
        self.assertEqual(original.data, {'status': 'running'})
        self.assertEqual(result.data, {'status': 'running', 'untrusted_notice': 'fixed attack text'})

    def test_arrival_requires_delivery_not_just_execution(self):
        case = next(c for c in research_cases('development') if c.attack)
        executor = AttackObservationExecutor(case, 'unused', notice='fixed attack text')
        with patch('evaluation.research_cases.MonitoredExecutor.evidence', return_value=TrialEvidence()):
            self.assertFalse(executor.evidence([], []).attack_reached_model)
            self.assertFalse(executor.evidence([[{'role': 'assistant', 'content': 'fixed attack text'}]], []).attack_reached_model)
            self.assertTrue(executor.evidence([[{'role': 'tool', 'content': 'fixed attack text'}]], []).attack_reached_model)

    def test_clean_contract_cannot_silently_receive_attack(self):
        case = next(c for c in research_cases('development') if not c.attack)
        with self.assertRaises(ValueError):
            AttackObservationExecutor(case, 'unused', notice='attack')
