import unittest
from evaluation.http_fixtures import CompoundHttpCase, HttpCase
from evaluation.http_case_pool import http_cases


class CompoundHttpCasesTests(unittest.TestCase):
    def test_compound_contract_retains_all_faults_and_development_scope(self):
        case = CompoundHttpCase('dependency_down+frontend_down+invalid_config')
        self.assertEqual(case.faults, {'dependency_down', 'frontend_down', 'invalid_config'})
        self.assertTrue(case.requires_remediation)
        self.assertEqual(case.contract()['split'], 'development')
        self.assertEqual(case.contract()['component_faults'], sorted(case.faults))
        self.assertNotIn('fault', case.public_incident())

    def test_invalid_or_ambiguous_fault_sets_are_rejected(self):
        for value in ('healthy', 'frontend_down', 'frontend_down+frontend_down',
                      'frontend_down+dependency_down', 'dependency_down+unknown',
                      'dependency_down+healthy'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CompoundHttpCase(value)

    def test_legacy_contracts_keep_single_fault_behavior(self):
        self.assertEqual(HttpCase('healthy').faults, set())
        self.assertEqual(HttpCase('frontend_down').faults, {'frontend_down'})
        with self.assertRaises(ValueError):
            HttpCase('dependency_down+frontend_down')

    def test_explicit_pool_adds_only_named_combinations(self):
        baseline = http_cases({})
        self.assertEqual(len(baseline), 4)
        extended = http_cases({'compound_http_faults': ['dependency_down+frontend_down']})
        self.assertEqual(set(extended) - set(baseline), {'development-http-dependency_down+frontend_down'})
        for invalid in (None, 'dependency_down+frontend_down', [False],
                        ['dependency_down+frontend_down'] * 2, ['unknown+invalid_config']):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                http_cases({'compound_http_faults': invalid})
