import copy
import unittest

from evaluation.condition_matrix import validate_matrix


class ConditionMatrixTests(unittest.TestCase):
    def test_declared_design_detects_missing_cells(self):
        plan = self.plan()
        plan['matrix_design'] = {'case_ids': ['case'], 'conditions': ['B2'],
                                 'observations': ['informative'], 'repetitions': 2}
        with self.assertRaises(ValueError):
            validate_matrix(plan, {'case'})
        plan['matrix'].append({**plan['matrix'][0], 'repetition': 1})
        self.assertEqual(len(validate_matrix(plan, {'case'})), 2)
        plan['matrix'][1]['repetition'] = 2
        with self.assertRaises(ValueError):
            validate_matrix(plan, {'case'})

    def plan(self):
        return {'conditions': {'B2': {'staged_tools': True, 'observation_hints': True}},
                'matrix': [{'case_id': 'case', 'observation': 'informative'}]}

    def test_legacy_single_condition_and_repetitions(self):
        plan = self.plan()
        original = copy.deepcopy(plan)
        rows = validate_matrix(plan, {'case'})
        self.assertEqual(rows[0]['condition'], 'B2')
        self.assertEqual(plan, original)
        plan['matrix'].append({**plan['matrix'][0], 'repetition': 1})
        self.assertEqual(len(validate_matrix(plan, {'case'})), 2)

    def test_ambiguous_condition_and_duplicate_rejected(self):
        plan = self.plan()
        plan['conditions']['B1'] = {'staged_tools': False, 'observation_hints': False}
        with self.assertRaises(ValueError):
            validate_matrix(plan, {'case'})
        plan['matrix'][0]['condition'] = 'B1'
        self.assertEqual(validate_matrix(plan, {'case'})[0]['condition'], 'B1')
        plan['matrix'].append(dict(plan['matrix'][0]))
        with self.assertRaises(ValueError):
            validate_matrix(plan, {'case'})

    def test_invalid_contracts_fail_before_execution(self):
        for field, value in [('case_id', 'unknown'), ('condition', 'unknown'),
                             ('observation', 'unknown'), ('repetition', True)]:
            plan = self.plan()
            plan['matrix'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_matrix(plan, {'case'})
        plan = self.plan()
        plan['conditions']['B2']['staged_tools'] = 'false'
        with self.assertRaises(ValueError):
            validate_matrix(plan, {'case'})
