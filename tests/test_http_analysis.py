import unittest
from scripts.analyze_http_development import valid_window


class HttpAnalysisTests(unittest.TestCase):
    def window(self, offsets):
        return {'ok': True, 'elapsed_seconds': 2, 'samples': [
            {'offset_seconds': offset, 'ok': True, 'http_status': 200,
             'body': {'status': 'ready', 'dependency': 'ready'}} for offset in offsets]}

    def test_requires_real_sample_span_not_declared_elapsed(self):
        self.assertTrue(valid_window(self.window([0.1, .6, 1.2])))
        for offsets in ([0.1, .2, .3], [0, 1], [0, 2, 1], [0, 1, float('nan')]):
            self.assertFalse(valid_window(self.window(offsets)))

    def test_failure_sample_cannot_be_masked_by_summary(self):
        window = self.window([0, .5, 1.1])
        window['samples'][1]['http_status'] = 503
        self.assertFalse(valid_window(window))
