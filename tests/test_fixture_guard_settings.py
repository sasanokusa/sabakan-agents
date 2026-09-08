from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from evaluation.docker_fixtures import build_fixture_broker
from sabakan_broker.models import ToolRequest


class FixtureGuardSettingsTests(unittest.TestCase):
    def test_only_repeat_limit_changes_and_real_guard_uses_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            executor = SimpleNamespace(config_path=None)
            baseline = build_fixture_broker(Path(tmp) / 'base', executor)
            relaxed = build_fixture_broker(Path(tmp) / 'relaxed', executor, identical_repeat_limit=4)
            expected = dict(baseline.policy.limits)
            expected['max_identical_tool_repeat'] = 4
            self.assertEqual(relaxed.policy.limits, expected)
            request = ToolRequest('service_status', {'host': 'local', 'service': 'nginx'})
            codes = [[broker.guard.admit_tool_call(request).code for _ in range(5)]
                     for broker in (baseline, relaxed)]
            self.assertEqual(codes[0], ['ALLOWED'] * 2 + ['LOOP_DETECTED'] * 3)
            self.assertEqual(codes[1], ['ALLOWED'] * 4 + ['LOOP_DETECTED'])
            self.assertEqual(baseline.policy.limits['max_mutations'], 3)
            self.assertEqual(relaxed.policy.limits['max_tool_calls'], 20)

    def test_invalid_limit_rejected_before_state_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'unused'
            for value in (True, 0, -1, 21, 2.5):
                with self.assertRaises(ValueError):
                    build_fixture_broker(root, SimpleNamespace(config_path=None), identical_repeat_limit=value)
            self.assertFalse(root.exists())
