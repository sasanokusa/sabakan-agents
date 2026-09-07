from dataclasses import replace
from unittest.mock import patch
import unittest

from evaluation.docker_fixtures import fixture_cases
from scripts.evaluate_mac_research import TrialTimeout
from scripts.run_legacy_controls import run_control


class LegacyControlTests(unittest.TestCase):
    def test_setup_timeout_is_saved_as_unstarted_and_cleanup_runs(self):
        def timeout(*_):
            raise TrialTimeout()
        case = replace(fixture_cases()[0], setup=timeout)
        with patch('scripts.run_legacy_controls._remove_container') as cleanup, patch(
                'scripts.run_legacy_controls.subprocess.check_output', return_value=''):
            record = run_control(case, 'fake-container')
        cleanup.assert_called_once_with('fake-container')
        self.assertFalse(record['started'])
        self.assertFalse(record['matches_expected'])
        self.assertTrue(record['cleanup_complete'])
        self.assertIsNone(record['score']['operational_harm_count'])
        self.assertIn('TrialTimeout', record['error'])
