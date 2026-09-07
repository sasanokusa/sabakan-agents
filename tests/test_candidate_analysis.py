import copy
import unittest
from scripts.analyze_candidate_development import candidate_analysis


class CandidateAnalysisTests(unittest.TestCase):
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
