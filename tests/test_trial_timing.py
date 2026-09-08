import unittest
from evaluation.timing import TrialTiming


class TrialTimingTests(unittest.TestCase):
    def test_completed_callback_preserves_result_without_recording_arguments(self):
        clock = iter([10, 12, 15])
        timing = TrialTiming(lambda: next(clock))
        result = object()
        callback = timing.wrap('approval_handler', lambda secret: result)
        self.assertIs(callback('signature-secret'), result)
        self.assertEqual(timing.events, [{'phase': 'approval_handler',
            'start_offset_seconds': 2, 'elapsed_seconds': 3, 'completed': True}])

    def test_outer_timeout_preserves_partial_elapsed_and_propagates(self):
        class OuterTimeout(BaseException):
            pass
        clock = iter([0, 1, 7])
        timing = TrialTiming(lambda: next(clock))
        error = OuterTimeout('secret')
        with self.assertRaises(OuterTimeout) as caught:
            with timing.span('actor_callback'):
                self.assertNotIn('elapsed_seconds', timing.events[0])
                raise error
        self.assertIs(caught.exception, error)
        self.assertEqual(timing.events[0]['elapsed_seconds'], 6)
        self.assertFalse(timing.events[0]['completed'])
        self.assertEqual(timing.events[0]['error_type'], 'OuterTimeout')
        self.assertNotIn('secret', repr(timing.events))
