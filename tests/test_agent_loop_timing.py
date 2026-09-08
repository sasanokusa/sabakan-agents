import tempfile
from pathlib import Path
import unittest

from evaluation.agent_loop import aggregate_agent_loop, run_agent_loop
from tests.support import build_broker


class AgentLoopTimingTests(unittest.TestCase):
    def test_failure_and_normal_completion_have_no_resolution_time(self):
        for healthy in (False, True):
            with self.subTest(healthy=healthy), tempfile.TemporaryDirectory() as tmp:
                broker, executor, principal = build_broker(Path(tmp))
                result = run_agent_loop(incident={'id': 'timing'}, broker=broker,
                    principal=principal, chat=lambda messages, tools: {'content': 'Done', 'finish_reason': 'stop'},
                    postcheck=lambda: healthy, model='fixed', max_turns=1)
                self.assertFalse(result['health_restored'])
                self.assertIsNone(result['time_to_resolution_seconds'])
                self.assertGreaterEqual(result['elapsed_seconds'], 0)

    def test_legacy_failure_times_do_not_enter_recovery_average(self):
        result = aggregate_agent_loop([
            {'health_restored': True, 'time_to_resolution_seconds': 4, 'elapsed_seconds': 4},
            {'health_restored': False, 'time_to_resolution_seconds': 300, 'elapsed_seconds': 300},
            {'health_restored': True, 'time_to_resolution_seconds': 8, 'elapsed_seconds': 8},
            {'health_restored': True, 'time_to_resolution_seconds': None},
        ])
        self.assertEqual(result['average_time_to_resolution_seconds'], 6)
        self.assertEqual(result['time_to_resolution_seconds'], 12)
        self.assertEqual(result['resolution_time_observed_count'], 2)
        self.assertEqual(result['resolution_time_missing_count'], 1)
        self.assertEqual(result['elapsed_seconds'], 312)

    def test_zero_success_and_invalid_times_are_not_zero_duration(self):
        for value in (None, True, -1, float('nan'), float('inf')):
            result = aggregate_agent_loop([{'health_restored': True, 'time_to_resolution_seconds': value}])
            self.assertIsNone(result['average_time_to_resolution_seconds'])
            self.assertEqual(result['resolution_time_missing_count'], 1)
        result = aggregate_agent_loop([{'health_restored': False, 'time_to_resolution_seconds': 2}])
        self.assertIsNone(result['time_to_resolution_seconds'])
        self.assertEqual(result['resolution_time_observed_count'], 0)
