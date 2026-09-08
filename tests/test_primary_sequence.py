import copy
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from scripts.run_primary_sequence import validate_design, remaining_resources


class PrimarySequenceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.plan = json.loads((self.root / 'evaluation/protocols/gtx1650-primary-sequence-20260908.json').read_text())
        self.children = [json.loads((self.root / b['plan']).read_text()) for b in self.plan['blocks']]

    def test_exact_primary_matrix_has_56_slots(self):
        self.assertEqual(validate_design(self.plan, self.children), 56)

    def test_missing_and_duplicate_repetitions_rejected(self):
        children = copy.deepcopy(self.children)
        children[0]['matrix'].pop()
        with self.assertRaises(ValueError):
            validate_design(self.plan, children)
        plan = copy.deepcopy(self.plan)
        children = copy.deepcopy(self.children)
        plan['blocks'][-1]['study_repetition'] = 0
        for row in children[-1]['matrix']:
            row['study_repetition'] = 0
        with self.assertRaises(ValueError):
            validate_design(plan, children)

    def test_runtime_or_harness_drift_rejected(self):
        for field in ('gpu_layers', 'conditions'):
            children = copy.deepcopy(self.children)
            if field == 'gpu_layers':
                children[0][field] = 99
            else:
                children[0][field]['B2']['observation_hints'] = False
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_design(self.plan, children)

    def test_cleanup_check_ignores_other_runner_resources(self):
        observed = SimpleNamespace(returncode=0, stdout='sabakan-lfm-diagnostic-1234\nsabakan-http-model-1234-0-front\nother-123\n')
        with patch('scripts.run_primary_sequence.subprocess.run', return_value=observed):
            result = remaining_resources(123)
        self.assertTrue(result['complete'])
        observed.stdout += 'sabakan-http-model-123-0-front\n'
        with patch('scripts.run_primary_sequence.subprocess.run', return_value=observed):
            result = remaining_resources(123)
        self.assertFalse(result['complete'])
        self.assertEqual(result['containers'], ['sabakan-http-model-123-0-front'])

    def test_unavailable_cleanup_observation_is_not_success(self):
        with patch('scripts.run_primary_sequence.subprocess.run', return_value=SimpleNamespace(returncode=1, stdout='')):
            self.assertFalse(remaining_resources(123)['complete'])
