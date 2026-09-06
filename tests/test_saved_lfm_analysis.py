import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_saved_lfm import analyze_report, main


class SavedLfmAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = json.loads((Path(__file__).resolve().parents[1] / 'evaluation/mac-pilot-results-v3.json').read_text())

    def test_saved_calls_match_and_failed_trials_are_retained(self):
        result = analyze_report(self.report)
        self.assertTrue(result['scope']['complete'])
        self.assertEqual(result['summary']['trial_count'], 64)
        self.assertEqual(result['summary']['canonical_loop_match']['true'], 64)
        self.assertEqual(sum(t['calls']['canonical_count'] for t in result['trials']), 431)
        self.assertEqual(result['summary']['stops'], {'LOOP_DETECTED': 48, 'TOOL_CALL_LIMIT': 16})

    def test_missing_responses_are_unknown_and_missing_trial_is_reported(self):
        report = copy.deepcopy(self.report)
        trial = next(t for t in report['trials'] if t['model'] == 'LFM2.5-2.6B')
        trial['model_responses'] = None
        result = analyze_report(report)
        self.assertEqual(result['summary']['canonical_loop_match']['unknown'], 1)
        report['trials'].remove(trial)
        result = analyze_report(report)
        self.assertFalse(result['scope']['complete'])
        self.assertEqual(len(result['scope']['missing_cells']), 1)

    def test_existing_artifact_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'keep.json'
            path.write_text('keep')
            with self.assertRaises(FileExistsError):
                main(['--output', str(path)])
            self.assertEqual(path.read_text(), 'keep')
