import unittest
from unittest.mock import patch

from evaluation.delayed_recovery import DelayedDependencyRecovery
from evaluation.http_fixtures import HttpFixture, HttpCase


class DelayedRecoveryTests(unittest.TestCase):
    def fixture(self):
        return HttpFixture(HttpCase('dependency_down'), '/tmp/unused', 'sabakan-http-timer-test', 'unused')

    def test_cancelled_delay_never_starts_container(self):
        controller = DelayedDependencyRecovery(self.fixture(), 180)
        with patch('evaluation.delayed_recovery.docker') as command:
            controller.start()
            controller.close()
        command.assert_not_called()
        self.assertEqual(controller.record['status'], 'cancelled')
        with self.assertRaises(RuntimeError):
            controller.start()

    def test_elapsed_trigger_does_not_claim_http_recovery(self):
        controller = DelayedDependencyRecovery(self.fixture(), 0)
        with patch('evaluation.delayed_recovery.docker') as command:
            controller.start()
            controller.thread.join(timeout=2)
            controller.close()
        command.assert_called_once_with('start', 'sabakan-http-timer-test-back')
        self.assertEqual(controller.record['status'], 'container_started')
        self.assertNotIn('healthy', controller.record)

    def test_start_failure_retained(self):
        controller = DelayedDependencyRecovery(self.fixture(), 0)
        with patch('evaluation.delayed_recovery.docker', side_effect=RuntimeError('private detail')):
            controller.start()
            controller.thread.join(timeout=2)
            controller.close()
        self.assertEqual(controller.record['status'], 'error')
        self.assertEqual(controller.record['error_type'], 'RuntimeError')
        self.assertNotIn('private detail', repr(controller.record))

    def test_invalid_delay_rejected(self):
        for delay in (True, -1, 181, float('nan'), float('inf')):
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                DelayedDependencyRecovery(self.fixture(), delay)
