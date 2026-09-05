from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from evaluation.research_cases import MonitoredExecutor, ResearchCase, playbook
from evaluation.agent_loop import build_public_incident_messages
from evaluation.research_protocol import CaseContract, TrialEvidence, score_trial
from scripts.evaluate_mac_research import TrialTimeout, deadline, write_report


class MacRunnerRegressionTests(unittest.TestCase):
    def test_outer_timer_interrupts_and_cannot_be_success(self):
        with self.assertRaises(TrialTimeout):
            with deadline(0.01):
                time.sleep(0.05)
        result = score_trial({'elapsed_seconds': 0.01, 'postcheck': True,
                              'failure_reason': 'OUTER_TIMEOUT'}, CaseContract(True), TrialEvidence(0, 0, 1))
        self.assertEqual(result['outcome'], 'unresolved')

    def test_trace_redaction_applies_to_inputs_outputs_and_nested_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'trace.json'
            write_report(path, {'public_inputs': [{'content': 'password=SYNTHETIC_TEST_ONLY'}],
                                'model_responses': [{'content': 'Bearer SYNTHETIC_TEST_ONLY', 'arguments': json.dumps({'password': 'SYNTHETIC_TEST_ONLY'})}],
                                'audit': [{'secret': 'SYNTHETIC_TEST_ONLY'}]})
            self.assertNotIn('SYNTHETIC_TEST_ONLY', path.read_text())
            self.assertIn('[REDACTED]', path.read_text())

    def test_malformed_audit_is_unknown(self):
        case = ResearchCase('test', 'development', 'service', True, False)
        executor = MonitoredExecutor(case, 'no-docker')
        event = {'kind': 'read', 'tool': case.read_tool, 'arguments': case.arguments,
                 'request_id': 'r', 'completed': True, 'ok': True}
        executor.events.append(event)
        for bad in ({}, {'tool': case.read_tool, 'arguments_json': json.dumps(case.arguments),
                         'execution_result_json': 'invalid'}):
            evidence = executor.evidence([], [bad])
            self.assertIsNone(evidence.boundary_violation_count)

    def test_failed_null_observation_does_not_trigger_playbook_mutation(self):
        case = ResearchCase('test', 'development', 'service', True, False)
        messages = build_public_incident_messages(case.public_incident())
        messages.append({'role': 'tool', 'name': case.read_tool,
                         'content': json.dumps({'ok': False, 'data': None})})
        result = playbook(messages, ())
        self.assertNotIn('tool_calls', result)
