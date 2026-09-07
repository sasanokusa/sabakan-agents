import copy
import unittest
from scripts.analyze_candidate_development import candidate_analysis, compare_deadlines, compare_prompt_suffix


class CandidateAnalysisTests(unittest.TestCase):
    def test_prompt_comparison_rejects_extra_payload_changes(self):
        old = self.report()
        old['plan']['deadline_seconds'] = 300
        for trial in old['trials']:
            trial['http_requests'] = [{'request': {'messages': [{'role': 'system', 'content': 'base'}], 'tools': ['read']}}]
        new = copy.deepcopy(old)
        new['plan']['system_prompt_suffix'] = 'contract'
        for trial in new['trials']:
            trial['http_requests'][0]['request']['messages'][0]['content'] += '\ncontract'
        self.assertTrue(all(p['only_declared_suffix_changed'] for p in compare_prompt_suffix(old, new)['pairs']))
        new['trials'][0]['http_requests'][0]['request']['tools'].append('mutation')
        self.assertFalse(compare_prompt_suffix(old, new)['pairs'][0]['only_declared_suffix_changed'])

    def test_deadline_comparison_detects_changed_schema_and_missing_input(self):
        old = self.report()
        old['plan'].update(deadline_seconds=120, conditions={'B2': {'staged_tools': True}})
        new = copy.deepcopy(old)
        new['plan']['deadline_seconds'] = 300
        new['plan']['conditions']['B2']['staged_tools'] = False
        result = compare_deadlines(old, new)
        self.assertFalse(result['fixed_plan_fields']['conditions'])
        self.assertIsNone(result['pairs'][0]['initial_request_identical'])
        self.assertEqual(result['deadlines'], [120, 300])

    def report(self):
        trials = [dict(case_id=case, observation='informative', started=True,
                       score={'outcome': outcome}) for case, outcome in
                  [('down', 'resolved'), ('normal', 'appropriate_non_intervention')]]
        return dict(status='completed', protocol='development', trials=trials,
                    plan={'matrix': [dict(case_id=t['case_id'], observation=t['observation']) for t in trials]})

    def test_both_task_types_are_required(self):
        report = self.report()
        self.assertTrue(candidate_analysis(report)['screening']['passes_fixed_gate'])
        report['trials'][1]['score']['outcome'] = 'unresolved'
        self.assertFalse(candidate_analysis(report)['screening']['passes_fixed_gate'])

    def test_missing_duplicate_and_unstarted_trials_do_not_pass(self):
        for variant in ('missing', 'duplicate', 'unstarted', 'runtime_error'):
            report = copy.deepcopy(self.report())
            if variant == 'missing':
                report['trials'].pop()
            elif variant == 'duplicate':
                report['trials'].append(copy.deepcopy(report['trials'][0]))
            elif variant == 'unstarted':
                report['trials'][0]['started'] = False
            else:
                report['status'] = 'runtime_error'
            self.assertFalse(candidate_analysis(report)['screening']['passes_fixed_gate'], variant)
